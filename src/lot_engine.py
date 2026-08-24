"""Pure lot-decision logic (implements docs/02-design.md §5-6).

No I/O — sheet/API wiring is the caller's (main) job. Standard library only.
lot dict keys: lot_id, ticker, kind, base_date, base_price, qty, status,
               last_price, change_pct, alert_state(dict), closed_reason
"""
from datetime import datetime

KIND_BUY = "매수lot"
KIND_SELL = "매도기준점"
ST_ACTIVE = "감시중"
ST_CLOSED = "종료"
SIDE_BUY = "매수"
SIDE_SELL = "매도"

# tolerance for threshold checks (e.g. the 81*1.1=89.10000000000001 problem)
_EPS = 1e-6


def _active(lots, ticker=None, kind=None):
    out = []
    for lot in lots:
        if lot["status"] != ST_ACTIVE:
            continue
        if ticker and lot["ticker"] != ticker:
            continue
        if kind and lot["kind"] != kind:
            continue
        out.append(lot)
    return out


def _seq_key(lot):
    try:
        seq = int(str(lot["lot_id"]).rsplit("-", 1)[1])
    except (IndexError, ValueError):
        seq = 0
    return (str(lot["base_date"]), seq)


def _new_lot_id(ticker, base_date, lots):
    # max+1 numbering: never collides with existing lot_ids even if the user deletes sheet rows
    prefix = f"{ticker}-{str(base_date).replace('-', '')}-"
    max_seq = 0
    for lot in lots:
        lid = str(lot["lot_id"])
        if lid.startswith(prefix):
            try:
                max_seq = max(max_seq, int(lid[len(prefix):]))
            except ValueError:
                pass
    return prefix + str(max_seq + 1)


def _make_lot(ticker, kind, base_date, base_price, qty, lots):
    return {
        "lot_id": _new_lot_id(ticker, base_date, lots),
        "ticker": ticker,
        "kind": kind,
        "base_date": base_date,
        "base_price": float(base_price),
        "qty": int(qty),
        "status": ST_ACTIVE,
        "last_price": "",
        "change_pct": "",
        "alert_state": {},
        "closed_reason": "",
    }


def _close_sell_points(lots, ticker):
    # A new buy fill counts as re-buy complete → close all sell reference points (KIND_SELL) for the ticker (design doc §5)
    for sp in _active(lots, ticker, KIND_SELL):
        sp["status"] = ST_CLOSED
        sp["closed_reason"] = "재매수됨"


def _apply_buy(lots, trade, qty=None):
    _close_sell_points(lots, trade["ticker"])
    lots.append(_make_lot(trade["ticker"], KIND_BUY, trade["trade_date"],
                          trade["price"], qty if qty is not None else trade["qty"], lots))


def _match_sell(lots, trade, qty, ann):
    """Match sell quantity against buy lots: exact quantity match (newest first) → LIFO split."""
    buys = _active(lots, trade["ticker"], KIND_BUY)
    exact = [lot for lot in buys if int(lot["qty"]) == qty]
    if exact:
        lot = max(exact, key=_seq_key)
        lot["qty"] = 0
        lot["status"] = ST_CLOSED
        lot["closed_reason"] = "전량매도"
        ann["matched_lots"].append(f"{lot['lot_id']}:{qty}")
        return
    remain = qty
    for lot in sorted(buys, key=_seq_key, reverse=True):  # LIFO
        if remain <= 0:
            break
        take = min(int(lot["qty"]), remain)
        if take <= 0:
            continue
        lot["qty"] = int(lot["qty"]) - take
        remain -= take
        ann["matched_lots"].append(f"{lot['lot_id']}:{take}")
        if lot["qty"] == 0:
            lot["status"] = ST_CLOSED
            lot["closed_reason"] = "전량매도"
    if remain > 0:
        note = f"감시 lot 없는 초과 매도 {remain}주"
        ann["note"] = (ann["note"] + " " if ann["note"] else "") + note


def _apply_sell(lots, trade, qty, ann):
    _match_sell(lots, trade, qty, ann)
    lots.append(_make_lot(trade["ticker"], KIND_SELL, trade["trade_date"],
                          trade["price"], qty, lots))


def _parse_matched(s):
    """Comma-separated 'lot_id:qty' list → [(lot_id, qty)]. Non-conforming parts are ignored."""
    out = []
    for part in str(s or "").split(","):
        lot_id, _, q = part.strip().rpartition(":")
        if not lot_id:
            continue
        try:
            out.append((lot_id, int(q)))
        except ValueError:
            continue
    return out


def _find_lot(lots, trade, kind):
    """For partial-fill quantity corrections: the active lot with the same ticker, base date, and base price."""
    cands = [lot for lot in _active(lots, trade["ticker"], kind)
             if str(lot["base_date"]) == str(trade["trade_date"])
             and abs(float(lot["base_price"]) - float(trade["price"])) < 1e-9]
    return max(cands, key=_seq_key) if cands else None


def process_trades(events, lots):
    """Apply new-fill/quantity-increase events to lots in place.

    events: in time order [{"type": "new"|"qty_update", "trade": {...},
                            "old_qty": int, "prev_matched": "lot_id:qty,..."}]
    Returns: {order_no: {"matched_lots": "lot_id:qty,...", "note": str}}
    """
    annotations = {}
    for ev in events:
        t = ev["trade"]
        ann = annotations.setdefault(t["order_no"], {"matched_lots": [], "note": ""})
        if ev["type"] == "new":
            if t["side"] == SIDE_BUY:
                _apply_buy(lots, t)
            else:
                _apply_sell(lots, t, int(t["qty"]), ann)
        elif ev["type"] == "qty_update":
            delta = int(t["qty"]) - int(ev["old_qty"])
            if delta <= 0:
                continue
            if t["side"] == SIDE_BUY:
                _close_sell_points(lots, t["ticker"])  # an additional fill is still a new buy fill
                lot = _find_lot(lots, t, KIND_BUY)
                if lot:
                    lot["qty"] = int(lot["qty"]) + delta
                else:
                    _apply_buy(lots, t, qty=delta)
            else:
                # Partial-fill rematch: undo this order's previous matches and
                # rematch against the order's cumulative total quantity (design doc §5: exact match uses the order total).
                total = int(t["qty"])
                for lot_id, q in _parse_matched(ev.get("prev_matched", "")):
                    lot = next((l for l in lots if str(l["lot_id"]) == lot_id), None)
                    if lot is None:
                        continue
                    lot["qty"] = int(lot["qty"]) + q
                    if lot["status"] == ST_CLOSED and lot["closed_reason"] == "전량매도":
                        lot["status"] = ST_ACTIVE
                        lot["closed_reason"] = ""
                sp = _find_lot(lots, t, KIND_SELL)
                if sp:
                    sp["qty"] = total
                else:
                    sp = _make_lot(t["ticker"], KIND_SELL, t["trade_date"],
                                   t["price"], total, lots)
                    lots.append(sp)
                ann["matched_lots"] = []
                ann["note"] = ""
                _match_sell(lots, t, total, ann)
    return {o: {"matched_lots": ",".join(a["matched_lots"]), "note": a["note"]}
            for o, a in annotations.items()}


def _stale(last_iso, now, remind_hours):
    """Whether a reminder is due while the condition persists. Remind if the record is missing or broken."""
    if not last_iso:
        return True
    try:
        elapsed = now - datetime.fromisoformat(last_iso)
        return elapsed.total_seconds() >= remind_hours * 3600
    except (ValueError, TypeError):
        return True


def _alert(lot, condition, price, chg, action, reminder):
    return {
        "ticker": lot["ticker"],
        "lot_id": lot["lot_id"],
        "kind": lot["kind"],
        "base_date": lot["base_date"],
        "qty": int(lot["qty"]),
        "condition": condition,
        "base_price": float(lot["base_price"]),
        "price": price,
        "change_pct": chg,
        "action": action,
        "reminder": reminder,
    }


def evaluate(lots, prices, settings, now,
             default_drop=10.0, default_rise=10.0, remind_hours=24.0):
    """Compare active lots with prices and build the list of alerts to send.

    lots are updated in place (last_price, change_pct, alert_state).
    prices: {ticker: float}. A lot is skipped this cycle if its price is missing or <= 0.
    settings: {ticker: {"drop_pct", "rise_pct", "enabled", ...}}
    """
    alerts = []
    for lot in lots:
        if lot["status"] != ST_ACTIVE:
            continue
        s = settings.get(lot["ticker"])
        if not s or not s.get("enabled"):
            continue
        price = prices.get(lot["ticker"])
        if not price or price <= 0:
            continue
        base = float(lot["base_price"])
        if base <= 0:
            continue
        drop = float(s.get("drop_pct") or default_drop)
        rise = float(s.get("rise_pct") or default_rise)
        chg = (price / base - 1.0) * 100.0
        lot["last_price"] = price
        lot["change_pct"] = round(chg, 2)
        st = lot.get("alert_state") or {}
        last = st.get("last_alert") or {}

        # Drop (add-buy/re-buy) — stepped: -10%, -20%, -30% … once per step
        action = "추가매수" if lot["kind"] == KIND_BUY else "재매수"
        n = int(((base - price) / base) / (drop / 100.0) + _EPS)
        if n >= 1:
            cond = f"{action}-{n * drop:.0f}%"
            level = int(st.get("drop_level") or 0)
            if n > level:
                alerts.append(_alert(lot, cond, price, chg, action, reminder=False))
                st["drop_level"] = n
                last["drop"] = now.isoformat()
            elif _stale(last.get("drop"), now, remind_hours):
                alerts.append(_alert(lot, f"리마인드({cond})", price, chg, action, reminder=True))
                last["drop"] = now.isoformat()

        # Rise (sell) — buy lots only, once + reminder
        if lot["kind"] == KIND_BUY and price >= base * (1 + rise / 100.0) * (1 - _EPS):
            cond = f"매도+{rise:.0f}%"
            if not st.get("rise_alerted"):
                alerts.append(_alert(lot, cond, price, chg, "매도", reminder=False))
                st["rise_alerted"] = True
                last["rise"] = now.isoformat()
            elif _stale(last.get("rise"), now, remind_hours):
                alerts.append(_alert(lot, f"리마인드({cond})", price, chg, "매도", reminder=True))
                last["rise"] = now.isoformat()

        st["last_alert"] = last
        lot["alert_state"] = st
    return alerts


_SENTENCE = {
    "추가매수": "추가 매수 타이밍입니다.",
    "매도": "매도 타이밍입니다.",
    "재매수": "재매수 타이밍입니다.",
}


def _md(base_date):
    """'2026-05-01' → '5/1'"""
    parts = str(base_date).split("-")
    if len(parts) == 3:
        return f"{int(parts[1])}/{int(parts[2])}"
    return str(base_date)


def _lot_line(a):
    side = SIDE_BUY if a["kind"] == KIND_BUY else SIDE_SELL
    return (f"{_md(a['base_date'])} {side} ${a['base_price']:.2f} × {a['qty']}주 "
            f"대비 {a['change_pct']:+.1f}% (현재 ${a['price']:.2f})")


def _summary_line(lots, ticker, price):
    hold = [l for l in lots
            if l["ticker"] == ticker and l["kind"] == KIND_BUY and l["status"] == ST_ACTIVE]
    total = sum(int(l["qty"]) for l in hold)
    if total <= 0 or not price:
        return None
    avg = sum(float(l["base_price"]) * int(l["qty"]) for l in hold) / total
    pl = (price / avg - 1.0) * 100.0
    return f"보유 {total}주 · 평단 ${avg:.2f} · 평가손익 {pl:+.1f}%"


def build_messages(alerts, lots, prices):
    """Group alerts per ticker and build the message text (design doc §6 format)."""
    by_ticker = {}
    for a in alerts:
        by_ticker.setdefault(a["ticker"], []).append(a)
    messages = []
    for ticker, items in by_ticker.items():
        price = prices.get(ticker)
        actions = {i["action"] for i in items}
        if len(items) == 1:
            a = items[0]
            lines = [
                f"[{a['action']}] {ticker}",
                _lot_line(a),
                _SENTENCE[a["action"]] + (" (리마인드)" if a["reminder"] else ""),
            ]
        else:
            head = items[0]["action"] if len(actions) == 1 else "매매알림"
            lines = [f"[{head}] {ticker}"]
            for a in items:
                lines.append(f"- {_lot_line(a)} → {a['action']}"
                             + (" 리마인드" if a["reminder"] else ""))
        summary = _summary_line(lots, ticker, price)
        if summary:
            lines.append(summary)
        messages.append({"ticker": ticker, "text": "\n".join(lines), "alerts": items})
    return messages
