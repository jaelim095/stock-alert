"""Main loop: collect → update lots → prices → evaluate → send → record.

python -m src.main          run continuously (for launchd)
python -m src.main --once   one full cycle regardless of market hours (for testing)

Failure-handling principles (design doc §9):
- Nothing is marked 'processed' before write_lots (state save) succeeds
- Failed appends to 거래내역/알림로그 are only logged — trades are auto-rewritten
  next cycle from the local cache, and the cache blocks duplicate lot application
"""
import argparse
import json
import os
import time
import traceback
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, lot_engine
from .kis_client import KISClient
from .notifier import Notifier
from .sheet_client import SheetClient
from .state_cache import ProcessedOrders, norm_order_no

ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")


def _log(msg):
    print(f"[{datetime.now(KST).strftime('%m-%d %H:%M:%S')}] {msg}", flush=True)


def _write_heartbeat(status, mode=""):
    """Cycle liveness signal — the watchdog checks its age to detect hangs.

    Written on error cycles too: the point is to prove 'the loop is running',
    and the 6-day silence of 2026-07-20 (socket hang) is the target. Write failures are ignored.
    """
    try:
        hb = {"ts": datetime.now(KST).isoformat(timespec="seconds"),
              "status": status, "mode": mode, "pid": os.getpid()}
        p = Path(config.HEARTBEAT_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(hb, ensure_ascii=False))
    except OSError:
        pass


def collect_trades(kis, sheets, cache):
    """Collect executions → apply new fills/quantity increases to lots and the sheet.

    Order: decide → apply to lots (in memory) → write_lots → record cache → write 거래내역.
    If write_lots fails, nothing is cached, so the next cycle reprocesses as-is (idempotent);
    rows whose 거래내역 write failed stay in the cache and are auto-rewritten next cycle.
    """
    fetched = kis.fetch_executions()
    sheet_trades = {}
    for t in sheets.read_trades():
        n = norm_order_no(t["order_no"])
        if n:
            sheet_trades[n] = t

    events = []
    for t in sorted(fetched, key=lambda x: (x["trade_date"], x["order_no"])):
        n = norm_order_no(t["order_no"])
        if not n:
            continue
        cached = cache.get(n)
        old_qty = cached["qty"] if cached else (
            sheet_trades[n]["qty"] if n in sheet_trades else None)
        if old_qty is None:
            events.append({"type": "new", "trade": t})
        elif t["qty"] > old_qty:  # quantity grew after a partial fill
            prev_matched = (cached or {}).get("matched_lots") \
                or sheet_trades.get(n, {}).get("matched_lots", "")
            events.append({"type": "qty_update", "trade": t,
                           "old_qty": old_qty, "prev_matched": prev_matched})

    now = datetime.now(KST)
    if events:
        lots = sheets.read_lots()
        annotations = lot_engine.process_trades(events, lots)
        sheets.write_lots(lots)  # failure → exception → no cache entry → reprocessed next cycle
        for ev in events:
            t = ev["trade"]
            a = annotations.get(t["order_no"], {})
            cache.record(t, a.get("matched_lots", ""), a.get("note", ""), now)
        cache.save(now)

    try:
        pending = cache.pending_rows(set(sheet_trades))
        if pending:
            sheets.append_trades(pending)
        for ev in events:
            if ev["type"] != "qty_update":
                continue
            t = ev["trade"]
            if norm_order_no(t["order_no"]) in sheet_trades:
                a = cache.get(t["order_no"]) or {}
                sheets.update_trade(t["order_no"], t["qty"], t["amount"],
                                    matched_lots=a.get("matched_lots"),
                                    note=a.get("note") or None)
        if events or pending:
            _log(f"체결 반영: 이벤트 {len(events)}건, 신규 기록 {len(pending)}건")
    except Exception as e:
        _log(f"거래내역 기록 실패(다음 주기 자동 재시도): {e}")


def watch_and_alert(kis, sheets, notifier):
    """Fetch prices for watched tickers → evaluate lots → send alerts → save state → log."""
    settings = sheets.read_settings()
    lots = sheets.read_lots()
    tickers = sorted({
        lot["ticker"] for lot in lots
        if lot["status"] == lot_engine.ST_ACTIVE
        and settings.get(lot["ticker"], {}).get("enabled")
    })
    if not tickers:
        return
    prices = {}
    for t in tickers:
        try:
            prices[t] = kis.fetch_price(settings[t]["excd"], t)
        except Exception as e:
            _log(f"시세 조회 실패 {t}: {e}")  # failed tickers skip evaluation this cycle
    now = datetime.now(KST)
    alerts = lot_engine.evaluate(
        lots, prices, settings, now,
        config.DEFAULT_DROP_PCT, config.DEFAULT_RISE_PCT, config.REMIND_INTERVAL_HOURS)
    messages = lot_engine.build_messages(alerts, lots, prices)
    log_rows = []
    for m in messages:
        res = notifier.send(f"[stock-alert] {m['ticker']} 매매 알림", m["text"])
        result = ", ".join(f"{k}:{v}" for k, v in res.items())
        sent = [label for key, label in (("kakao", "카카오"), ("email", "이메일"))
                if not str(res.get(key, "")).startswith(("생략", "꺼짐", "미설정"))]
        channel = "+".join(sent) or "없음"
        for a in m["alerts"]:
            log_rows.append({
                "sent_at": now.isoformat(timespec="seconds"),
                "ticker": a["ticker"], "lot_id": a["lot_id"],
                "condition": a["condition"], "base_price": a["base_price"],
                "price": a["price"], "change_pct": round(a["change_pct"], 2),
                "message": m["text"], "channel": channel, "result": result,
            })
        _log(f"알림 발송 {m['ticker']}: {len(m['alerts'])}건 ({result})")
    # Saving alert_state comes before logging — if the save fails, re-sending is the better failure,
    # whereas a log failure blocking the save would duplicate alerts every 5 minutes
    sheets.write_lots(lots)
    try:
        if log_rows:
            sheets.append_alerts(log_rows)
    except Exception as e:
        _log(f"알림로그 기록 실패(무시): {e}")


def market_mode():
    """(mode, poll interval in seconds). full=whole loop, collect=execution collection only."""
    now_et = datetime.now(ET)
    weekday = now_et.weekday() < 5
    t = now_et.time()
    regular = weekday and dtime(9, 30) <= t < dtime(16, 0)
    sweep = weekday and dtime(16, 0) <= t < dtime(16, 35)  # final collection right after the close
    day_market = False
    if config.ENABLE_DAY_MARKET:
        now_kst = datetime.now(KST)
        day_market = (now_kst.weekday() < 5
                      and dtime(10, 0) <= now_kst.time() < dtime(16, 0))
    if regular or day_market:
        return "full", config.POLL_INTERVAL_MIN * 60
    if sweep:
        return "collect", config.POLL_INTERVAL_MIN * 60
    return "collect", 30 * 60  # off-hours: collect only, to catch pre/after-market fills


def _sleep_seconds(interval):
    """Trim the interval so we never sleep past the next market transition (open/close)."""
    deltas = []
    now_et = datetime.now(ET)
    for d in (0, 1):
        day = now_et.date() + timedelta(days=d)
        for b in (dtime(9, 30), dtime(16, 0), dtime(16, 35)):
            bd = datetime.combine(day, b, tzinfo=ET)
            if bd > now_et:
                deltas.append((bd - now_et).total_seconds())
    if config.ENABLE_DAY_MARKET:
        now_kst = datetime.now(KST)
        for d in (0, 1):
            day = now_kst.date() + timedelta(days=d)
            for b in (dtime(10, 0), dtime(16, 0)):
                bd = datetime.combine(day, b, tzinfo=KST)
                if bd > now_kst:
                    deltas.append((bd - now_kst).total_seconds())
    return max(30, min(interval, min(deltas) + 5))


def run_cycle(kis, sheets, notifier, cache, full):
    collect_trades(kis, sheets, cache)
    if full:
        watch_and_alert(kis, sheets, notifier)


def _connect_sheets_forever():
    """Retry instead of crash-looping when e.g. the network is not up right after boot."""
    while True:
        try:
            return SheetClient(config.GOOGLE_SERVICE_ACCOUNT_JSON, config.SHEET_ID)
        except Exception as e:
            _log(f"구글시트 연결 실패, 60초 후 재시도: {e}")
            time.sleep(60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true",
                        help="장 시간 무관 전체 사이클 1회 실행")
    args = parser.parse_args()

    kis = KISClient(config.KIS_APP_KEY, config.KIS_APP_SECRET,
                    config.KIS_ACCOUNT_NO, config.KIS_ENV, config.KIS_TOKEN_PATH)
    notifier = Notifier()
    cache = ProcessedOrders(config.PROCESSED_ORDERS_PATH)

    if args.once:
        sheets = SheetClient(config.GOOGLE_SERVICE_ACCOUNT_JSON, config.SHEET_ID)
        run_cycle(kis, sheets, notifier, cache, full=True)
        return

    sheets = _connect_sheets_forever()
    _log(f"stock-alert 시작 (env={config.KIS_ENV})")
    _write_heartbeat("start")
    while True:
        mode, interval = market_mode()
        try:
            run_cycle(kis, sheets, notifier, cache, full=(mode == "full"))
            _write_heartbeat("ok", mode)
        except Exception:
            traceback.print_exc()  # transient errors carry over to the next cycle
            _write_heartbeat("error", mode)
        time.sleep(_sleep_seconds(interval))


if __name__ == "__main__":
    main()
