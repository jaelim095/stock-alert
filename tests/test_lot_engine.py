"""Pure-logic tests for lot_engine. Reproduces the design doc's example scenarios verbatim."""
from datetime import datetime, timedelta

from src.lot_engine import (
    KIND_BUY, KIND_SELL, ST_ACTIVE, ST_CLOSED,
    build_messages, evaluate, process_trades,
)

SETTINGS = {"TSLA": {"excd": "NAS", "drop_pct": 10, "rise_pct": 10, "enabled": True}}


def trade(date, side, price, qty, order_no, ticker="TSLA"):
    return {"recorded_at": "", "trade_date": date, "ticker": ticker, "name": "Tesla",
            "side": side, "price": price, "qty": qty, "amount": price * qty,
            "order_no": order_no, "matched_lots": "", "note": ""}


def new(t):
    return {"type": "new", "trade": t}


def ev(lots, price, now, settings=SETTINGS, ticker="TSLA"):
    return evaluate(lots, {ticker: price}, settings, now)


def lot_by_id(lots, lot_id):
    return next(l for l in lots if l["lot_id"] == lot_id)


def test_user_scenario_end_to_end():
    """5/1 buy → average down twice → 6/15 sell → 7/1 sell alert → re-buy alert."""
    lots = []
    # 5/1: buy $100 × 10 shares
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1"))], lots)
    assert lots[0]["lot_id"] == "TSLA-20260501-1"

    # 5/5: $90 → buy-more alert on the $100 lot
    alerts = ev(lots, 90.0, datetime(2026, 5, 5))
    assert [(a["lot_id"], a["condition"]) for a in alerts] == \
        [("TSLA-20260501-1", "추가매수-10%")]

    # 5/5: buy $90 × 15 shares
    process_trades([new(trade("2026-05-05", "매수", 90.0, 15, "2"))], lots)

    # 5/15: $81 → new alert on the $90 lot (+ the $100 lot gets a reminder after 10 days)
    alerts = ev(lots, 81.0, datetime(2026, 5, 15))
    got = {(a["lot_id"], a["condition"]) for a in alerts}
    assert ("TSLA-20260505-1", "추가매수-10%") in got
    assert ("TSLA-20260501-1", "리마인드(추가매수-10%)") in got

    # 5/15: buy $81 × 5 shares
    process_trades([new(trade("2026-05-15", "매수", 81.0, 5, "3"))], lots)

    # 6/15: $89.1 → sell alert on the $81 lot (81 × 1.1 = 89.1)
    alerts = ev(lots, 89.1, datetime(2026, 6, 15))
    rise = [a for a in alerts if a["condition"] == "매도+10%"]
    assert [a["lot_id"] for a in rise] == ["TSLA-20260515-1"]

    # 6/15: sell $89.1 × 5 shares → exact qty match closes the $81 lot + creates a sell reference point
    ann = process_trades([new(trade("2026-06-15", "매도", 89.1, 5, "4"))], lots)
    closed = lot_by_id(lots, "TSLA-20260515-1")
    assert closed["status"] == ST_CLOSED and closed["closed_reason"] == "전량매도"
    assert ann["4"]["matched_lots"] == "TSLA-20260515-1:5"
    sp = next(l for l in lots if l["kind"] == KIND_SELL)
    assert sp["status"] == ST_ACTIVE and sp["base_price"] == 89.1 and sp["qty"] == 5

    # 7/1: $99 → sell alert on the $90 lot (90 × 1.1 = 99)
    alerts = ev(lots, 99.0, datetime(2026, 7, 1))
    rise = [a for a in alerts if a["condition"] == "매도+10%"]
    assert [a["lot_id"] for a in rise] == ["TSLA-20260505-1"]

    # then $80.19 → re-buy alert at -10% vs the sell reference point (89.1)
    alerts = ev(lots, 80.19, datetime(2026, 7, 2))
    rebuy = [a for a in alerts if a["condition"] == "재매수-10%"]
    assert [a["lot_id"] for a in rebuy] == [sp["lot_id"]]


def test_partial_sell_lifo():
    """A sell with no exact qty match consumes lots newest-first (LIFO), splitting."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1")),
                    new(trade("2026-05-05", "매수", 90.0, 15, "2"))], lots)
    ann = process_trades([new(trade("2026-05-10", "매도", 95.0, 12, "3"))], lots)
    old = lot_by_id(lots, "TSLA-20260501-1")
    recent = lot_by_id(lots, "TSLA-20260505-1")
    assert recent["qty"] == 3 and recent["status"] == ST_ACTIVE
    assert old["qty"] == 10 and old["status"] == ST_ACTIVE
    assert ann["3"]["matched_lots"] == "TSLA-20260505-1:12"


def test_oversell_noted():
    """A sell exceeding the watched-lot total leaves the excess in the 비고 note."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1"))], lots)
    ann = process_trades([new(trade("2026-05-10", "매도", 95.0, 13, "2"))], lots)
    assert "초과 매도 3주" in ann["2"]["note"]
    assert lot_by_id(lots, "TSLA-20260501-1")["status"] == ST_CLOSED


def test_drop_ladder():
    """After a -10% alert, a new alert fires at -20%; re-entering -10% does not re-alert."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1"))], lots)
    t = datetime(2026, 5, 2)
    assert [a["condition"] for a in ev(lots, 90.0, t)] == ["추가매수-10%"]
    assert ev(lots, 89.0, t + timedelta(hours=1)) == []
    assert [a["condition"] for a in ev(lots, 80.0, t + timedelta(hours=2))] == ["추가매수-20%"]
    assert ev(lots, 89.0, t + timedelta(hours=3)) == []  # re-entering -10%
    assert ev(lots, 95.0, t + timedelta(hours=4)) == []  # condition cleared


def test_reminder_after_24h():
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1"))], lots)
    t = datetime(2026, 5, 2)
    ev(lots, 90.0, t)
    assert ev(lots, 89.5, t + timedelta(hours=23)) == []
    alerts = ev(lots, 89.5, t + timedelta(hours=25))
    assert [a["condition"] for a in alerts] == ["리마인드(추가매수-10%)"]


def test_rise_alert_once_then_reminder():
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1"))], lots)
    t = datetime(2026, 5, 2)
    assert [a["condition"] for a in ev(lots, 110.0, t)] == ["매도+10%"]
    assert ev(lots, 112.0, t + timedelta(hours=1)) == []
    alerts = ev(lots, 112.0, t + timedelta(hours=25))
    assert [a["condition"] for a in alerts] == ["리마인드(매도+10%)"]


def test_partial_fill_qty_update():
    """A qty increase on the same order no (partial fill) adjusts the lot qty."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 5, "1"))], lots)
    updated = trade("2026-05-01", "매수", 100.0, 10, "1")
    process_trades([{"type": "qty_update", "trade": updated, "old_qty": 5}], lots)
    buys = [l for l in lots if l["kind"] == KIND_BUY]
    assert len(buys) == 1 and buys[0]["qty"] == 10


def test_new_buy_closes_sell_points():
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1")),
                    new(trade("2026-05-10", "매도", 110.0, 10, "2"))], lots)
    sp = next(l for l in lots if l["kind"] == KIND_SELL)
    assert sp["status"] == ST_ACTIVE
    process_trades([new(trade("2026-05-20", "매수", 99.0, 10, "3"))], lots)
    assert sp["status"] == ST_CLOSED and sp["closed_reason"] == "재매수됨"


def test_disabled_ticker_no_alerts_but_lots_kept():
    """With 감시=N, lot records are still kept and only alerts are suppressed."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1"))], lots)
    off = {"TSLA": {"excd": "NAS", "drop_pct": 10, "rise_pct": 10, "enabled": False}}
    assert ev(lots, 80.0, datetime(2026, 5, 2), settings=off) == []
    assert len(lots) == 1


def test_missing_price_skips_evaluation():
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1"))], lots)
    assert evaluate(lots, {}, SETTINGS, datetime(2026, 5, 2)) == []
    assert evaluate(lots, {"TSLA": 0}, SETTINGS, datetime(2026, 5, 2)) == []


def test_per_ticker_threshold_override():
    """The per-ticker threshold (15%) from the 설정 tab applies instead of the default (10%)."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1"))], lots)
    s15 = {"TSLA": {"excd": "NAS", "drop_pct": 15, "rise_pct": 15, "enabled": True}}
    assert ev(lots, 90.0, datetime(2026, 5, 2), settings=s15) == []
    alerts = ev(lots, 85.0, datetime(2026, 5, 2, 1), settings=s15)
    assert [a["condition"] for a in alerts] == ["추가매수-15%"]


def test_message_format_single():
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1")),
                    new(trade("2026-05-05", "매수", 90.0, 15, "2"))], lots)
    alerts = ev(lots, 89.8, datetime(2026, 5, 6))
    msgs = build_messages(alerts, lots, {"TSLA": 89.8})
    assert len(msgs) == 1
    text = msgs[0]["text"]
    assert text.startswith("[추가매수] TSLA")
    assert "5/1 매수 $100.00 × 10주" in text
    assert "추가 매수 타이밍입니다." in text
    assert "보유 25주" in text and "평단 $94.00" in text


def test_message_format_grouped():
    """Multiple lots triggering in the same cycle are grouped into one message."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1")),
                    new(trade("2026-05-05", "매수", 98.0, 10, "2"))], lots)
    alerts = ev(lots, 88.0, datetime(2026, 5, 6))
    assert len(alerts) == 2
    msgs = build_messages(alerts, lots, {"TSLA": 88.0})
    assert len(msgs) == 1
    assert msgs[0]["text"].count("- ") == 2


def test_exact_match_prefers_latest_lot():
    """When multiple lots exactly match the qty, the most recent one is closed."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1")),
                    new(trade("2026-05-05", "매수", 90.0, 10, "2"))], lots)
    ann = process_trades([new(trade("2026-05-10", "매도", 95.0, 10, "3"))], lots)
    assert ann["3"]["matched_lots"] == "TSLA-20260505-1:10"
    assert lot_by_id(lots, "TSLA-20260505-1")["status"] == ST_CLOSED
    assert lot_by_id(lots, "TSLA-20260501-1")["status"] == ST_ACTIVE


def test_lifo_spans_multiple_lots():
    """A no-exact-match sell spanning multiple lots drains newest-first and records every match."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1")),
                    new(trade("2026-05-05", "매수", 90.0, 15, "2"))], lots)
    ann = process_trades([new(trade("2026-05-10", "매도", 95.0, 20, "3"))], lots)
    assert ann["3"]["matched_lots"] == "TSLA-20260505-1:15,TSLA-20260501-1:5"
    assert lot_by_id(lots, "TSLA-20260505-1")["status"] == ST_CLOSED
    old = lot_by_id(lots, "TSLA-20260501-1")
    assert old["qty"] == 5 and old["status"] == ST_ACTIVE


def test_sell_qty_update_rematches_by_total():
    """A sell order filled as 5+5 ends in the same final state as a single 10-share fill."""
    def base_lots():
        lots = []
        process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1")),
                        new(trade("2026-05-05", "매수", 90.0, 5, "2"))], lots)
        return lots

    single = base_lots()
    process_trades([new(trade("2026-05-10", "매도", 95.0, 10, "3"))], single)

    split = base_lots()
    ann1 = process_trades([new(trade("2026-05-10", "매도", 95.0, 5, "3"))], split)
    assert ann1["3"]["matched_lots"] == "TSLA-20260505-1:5"  # exact match on the chunk
    upd = trade("2026-05-10", "매도", 95.0, 10, "3")
    ann2 = process_trades([{"type": "qty_update", "trade": upd, "old_qty": 5,
                            "prev_matched": ann1["3"]["matched_lots"]}], split)
    assert ann2["3"]["matched_lots"] == "TSLA-20260501-1:10"  # re-matched on the total qty
    for lid in ("TSLA-20260501-1", "TSLA-20260505-1"):
        s, p = lot_by_id(single, lid), lot_by_id(split, lid)
        assert (s["qty"], s["status"]) == (p["qty"], p["status"])
    sps = [l for l in split if l["kind"] == KIND_SELL and l["status"] == ST_ACTIVE]
    assert len(sps) == 1 and sps[0]["qty"] == 10


def test_buy_qty_update_closes_sell_points():
    """An additional buy fill (qty_update) is still a new buy, so it closes sell reference points."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1")),
                    new(trade("2026-05-03", "매도", 105.0, 4, "2"))], lots)
    sp = next(l for l in lots if l["kind"] == KIND_SELL)
    assert sp["status"] == ST_ACTIVE
    upd = trade("2026-05-01", "매수", 100.0, 20, "1")
    process_trades([{"type": "qty_update", "trade": upd, "old_qty": 10}], lots)
    assert sp["status"] == ST_CLOSED and sp["closed_reason"] == "재매수됨"
    assert lot_by_id(lots, "TSLA-20260501-1")["qty"] == 16


def test_drop_ladder_skips_levels_and_reaches_30():
    """Dropping straight to -25% fires only the -20% step alert; reaching -30% later fires a new one."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1"))], lots)
    t = datetime(2026, 5, 2)
    assert [a["condition"] for a in ev(lots, 75.0, t)] == ["추가매수-20%"]
    assert ev(lots, 89.0, t + timedelta(hours=1)) == []  # re-entering a shallower step: no alert
    alerts = ev(lots, 70.0, t + timedelta(hours=2))
    assert [a["condition"] for a in alerts] == ["추가매수-30%"]


def test_alert_state_json_roundtrip():
    """alert_state keeps ladder and reminder behavior after a sheet round-trip (JSON string)."""
    import json

    def roundtrip(lots):
        for l in lots:
            l["alert_state"] = json.loads(json.dumps(l["alert_state"]))

    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1"))], lots)
    t = datetime(2026, 5, 2)
    ev(lots, 90.0, t)
    roundtrip(lots)
    assert ev(lots, 89.0, t + timedelta(hours=1)) == []  # drop_level preserved
    roundtrip(lots)
    alerts = ev(lots, 89.5, t + timedelta(hours=25))     # last_alert preserved → reminder
    assert [a["condition"] for a in alerts] == ["리마인드(추가매수-10%)"]


def test_lot_id_uses_max_seq_after_deletion():
    """Even if the user deletes lot rows in the sheet, new lot_ids never collide with existing ones."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1")),
                    new(trade("2026-05-01", "매수", 101.0, 10, "2"))], lots)
    assert [l["lot_id"] for l in lots] == ["TSLA-20260501-1", "TSLA-20260501-2"]
    del lots[0]
    process_trades([new(trade("2026-05-01", "매수", 102.0, 10, "3"))], lots)
    assert lots[-1]["lot_id"] == "TSLA-20260501-3"


def test_norm_order_no():
    """Orders match even when leading zeros differ (sheet numeric coercion)."""
    from src.state_cache import norm_order_no
    assert norm_order_no("0000117057") == norm_order_no("117057") == "117057"
    assert norm_order_no("0") == "0"
    assert norm_order_no("000") == "0"
    assert norm_order_no("") == ""
    assert norm_order_no(" 0001 ") == "1"
