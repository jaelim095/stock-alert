"""메인 루프: 수집 → lot 갱신 → 시세 → 평가 → 발송 → 기록.

python -m src.main          상시 구동 (launchd 용)
python -m src.main --once   장 시간 무관 전체 사이클 1회 (테스트용)

실패 처리 원칙 (설계 9절):
- write_lots(상태 저장)가 성공하기 전에는 어떤 것도 '처리됨'으로 기록하지 않는다
- 거래내역/알림로그 append 실패는 로그만 남긴다 — 거래내역은 로컬 캐시로
  다음 주기에 자동 재기록, lot 중복 반영은 캐시가 막는다
"""
import argparse
import time
import traceback
from datetime import datetime, timedelta, time as dtime
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


def collect_trades(kis, sheets, cache):
    """체결내역 수집 → 신규/수량증가를 lot과 시트에 반영.

    순서: 판정 → lot 반영(메모리) → write_lots → 캐시 기록 → 거래내역 기록.
    write_lots 실패 시 캐시에 남지 않아 다음 주기에 그대로 재처리되고(멱등),
    거래내역 기록 실패분은 캐시에 남아 다음 주기에 자동 재기록된다.
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
        elif t["qty"] > old_qty:  # 부분 체결 후 수량 증가
            prev_matched = (cached or {}).get("matched_lots") \
                or sheet_trades.get(n, {}).get("matched_lots", "")
            events.append({"type": "qty_update", "trade": t,
                           "old_qty": old_qty, "prev_matched": prev_matched})

    now = datetime.now(KST)
    if events:
        lots = sheets.read_lots()
        annotations = lot_engine.process_trades(events, lots)
        sheets.write_lots(lots)  # 실패 → 예외 → 캐시 미기록 → 다음 주기 재처리
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
    """감시 종목 시세 조회 → lot 평가 → 알림 발송 → 상태 저장 → 로그."""
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
            _log(f"시세 조회 실패 {t}: {e}")  # 실패 종목은 이번 주기 평가 스킵
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
    # alert_state 저장이 로그보다 우선 — 저장 실패 시 재발송되는 쪽이 낫고,
    # 로그 실패가 저장을 막으면 5분마다 알림이 중복 발송된다
    sheets.write_lots(lots)
    try:
        if log_rows:
            sheets.append_alerts(log_rows)
    except Exception as e:
        _log(f"알림로그 기록 실패(무시): {e}")


def market_mode():
    """(mode, 폴링 간격 초). full=전체 루프, collect=체결 수집만."""
    now_et = datetime.now(ET)
    weekday = now_et.weekday() < 5
    t = now_et.time()
    regular = weekday and dtime(9, 30) <= t < dtime(16, 0)
    sweep = weekday and dtime(16, 0) <= t < dtime(16, 35)  # 마감 직후 최종 수집
    day_market = False
    if config.ENABLE_DAY_MARKET:
        now_kst = datetime.now(KST)
        day_market = (now_kst.weekday() < 5
                      and dtime(10, 0) <= now_kst.time() < dtime(16, 0))
    if regular or day_market:
        return "full", config.POLL_INTERVAL_MIN * 60
    if sweep:
        return "collect", config.POLL_INTERVAL_MIN * 60
    return "collect", 30 * 60  # 장외: 프리/애프터 체결 대비 수집만


def _sleep_seconds(interval):
    """다음 장 상태 전환(개장/마감) 시각을 넘겨 자지 않도록 간격을 자른다."""
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
    """부팅 직후 네트워크 미연결 등으로 실패해도 크래시 루프 대신 재시도."""
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
    while True:
        mode, interval = market_mode()
        try:
            run_cycle(kis, sheets, notifier, cache, full=(mode == "full"))
        except Exception:
            traceback.print_exc()  # 일시 오류는 다음 주기로 이월
        time.sleep(_sleep_seconds(interval))


if __name__ == "__main__":
    main()
