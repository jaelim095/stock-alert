"""lot_engine 순수 로직 테스트. 설계 문서의 예시 시나리오를 그대로 재현한다."""
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
    """5/1 매수 → 물타기 2회 → 6/15 매도 → 7/1 매도 알림 → 재매수 알림."""
    lots = []
    # 5/1: $100 × 10주 매수
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1"))], lots)
    assert lots[0]["lot_id"] == "TSLA-20260501-1"

    # 5/5: $90 → $100 lot 추가매수 알림
    alerts = ev(lots, 90.0, datetime(2026, 5, 5))
    assert [(a["lot_id"], a["condition"]) for a in alerts] == \
        [("TSLA-20260501-1", "추가매수-10%")]

    # 5/5: $90 × 15주 매수
    process_trades([new(trade("2026-05-05", "매수", 90.0, 15, "2"))], lots)

    # 5/15: $81 → $90 lot 신규 알림 (+$100 lot은 10일 지나 리마인드)
    alerts = ev(lots, 81.0, datetime(2026, 5, 15))
    got = {(a["lot_id"], a["condition"]) for a in alerts}
    assert ("TSLA-20260505-1", "추가매수-10%") in got
    assert ("TSLA-20260501-1", "리마인드(추가매수-10%)") in got

    # 5/15: $81 × 5주 매수
    process_trades([new(trade("2026-05-15", "매수", 81.0, 5, "3"))], lots)

    # 6/15: $89.1 → $81 lot 매도 알림 (81 × 1.1 = 89.1)
    alerts = ev(lots, 89.1, datetime(2026, 6, 15))
    rise = [a for a in alerts if a["condition"] == "매도+10%"]
    assert [a["lot_id"] for a in rise] == ["TSLA-20260515-1"]

    # 6/15: $89.1 × 5주 매도 → 수량 일치로 $81 lot 종료 + 매도기준점 생성
    ann = process_trades([new(trade("2026-06-15", "매도", 89.1, 5, "4"))], lots)
    closed = lot_by_id(lots, "TSLA-20260515-1")
    assert closed["status"] == ST_CLOSED and closed["closed_reason"] == "전량매도"
    assert ann["4"]["matched_lots"] == "TSLA-20260515-1:5"
    sp = next(l for l in lots if l["kind"] == KIND_SELL)
    assert sp["status"] == ST_ACTIVE and sp["base_price"] == 89.1 and sp["qty"] == 5

    # 7/1: $99 → $90 lot 매도 알림 (90 × 1.1 = 99)
    alerts = ev(lots, 99.0, datetime(2026, 7, 1))
    rise = [a for a in alerts if a["condition"] == "매도+10%"]
    assert [a["lot_id"] for a in rise] == ["TSLA-20260505-1"]

    # 이후 $80.19 → 매도기준점(89.1) 대비 -10% 재매수 알림
    alerts = ev(lots, 80.19, datetime(2026, 7, 2))
    rebuy = [a for a in alerts if a["condition"] == "재매수-10%"]
    assert [a["lot_id"] for a in rebuy] == [sp["lot_id"]]


def test_partial_sell_lifo():
    """수량 불일치 매도는 최신 lot부터(LIFO) 분할 소진."""
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
    """감시 lot 합계보다 큰 매도는 초과분을 비고에 남긴다."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1"))], lots)
    ann = process_trades([new(trade("2026-05-10", "매도", 95.0, 13, "2"))], lots)
    assert "초과 매도 3주" in ann["2"]["note"]
    assert lot_by_id(lots, "TSLA-20260501-1")["status"] == ST_CLOSED


def test_drop_ladder():
    """-10% 알림 후 -20%에서 새 알림, -10% 재진입 시 재알림 없음."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1"))], lots)
    t = datetime(2026, 5, 2)
    assert [a["condition"] for a in ev(lots, 90.0, t)] == ["추가매수-10%"]
    assert ev(lots, 89.0, t + timedelta(hours=1)) == []
    assert [a["condition"] for a in ev(lots, 80.0, t + timedelta(hours=2))] == ["추가매수-20%"]
    assert ev(lots, 89.0, t + timedelta(hours=3)) == []  # -10% 재진입
    assert ev(lots, 95.0, t + timedelta(hours=4)) == []  # 조건 해소


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
    """같은 주문번호의 수량 증가(부분 체결)는 lot 수량으로 보정."""
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
    """감시=N 이어도 lot 기록은 유지되고 알림만 안 나간다."""
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
    """설정 탭의 종목별 임계값(15%)이 기본값(10%) 대신 적용된다."""
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
    """같은 주기에 여러 lot이 걸리면 한 메시지로 묶인다."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1")),
                    new(trade("2026-05-05", "매수", 98.0, 10, "2"))], lots)
    alerts = ev(lots, 88.0, datetime(2026, 5, 6))
    assert len(alerts) == 2
    msgs = build_messages(alerts, lots, {"TSLA": 88.0})
    assert len(msgs) == 1
    assert msgs[0]["text"].count("- ") == 2


def test_exact_match_prefers_latest_lot():
    """수량 정확 일치 lot이 여러 개면 가장 최근 lot이 종료된다."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1")),
                    new(trade("2026-05-05", "매수", 90.0, 10, "2"))], lots)
    ann = process_trades([new(trade("2026-05-10", "매도", 95.0, 10, "3"))], lots)
    assert ann["3"]["matched_lots"] == "TSLA-20260505-1:10"
    assert lot_by_id(lots, "TSLA-20260505-1")["status"] == ST_CLOSED
    assert lot_by_id(lots, "TSLA-20260501-1")["status"] == ST_ACTIVE


def test_lifo_spans_multiple_lots():
    """수량 불일치 매도가 여러 lot에 걸치면 최신부터 소진하고 매칭을 전부 기록한다."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1")),
                    new(trade("2026-05-05", "매수", 90.0, 15, "2"))], lots)
    ann = process_trades([new(trade("2026-05-10", "매도", 95.0, 20, "3"))], lots)
    assert ann["3"]["matched_lots"] == "TSLA-20260505-1:15,TSLA-20260501-1:5"
    assert lot_by_id(lots, "TSLA-20260505-1")["status"] == ST_CLOSED
    old = lot_by_id(lots, "TSLA-20260501-1")
    assert old["qty"] == 5 and old["status"] == ST_ACTIVE


def test_sell_qty_update_rematches_by_total():
    """매도 주문이 5+5로 나뉘어 체결돼도 단일 10주 체결과 같은 최종 상태가 된다."""
    def base_lots():
        lots = []
        process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1")),
                        new(trade("2026-05-05", "매수", 90.0, 5, "2"))], lots)
        return lots

    single = base_lots()
    process_trades([new(trade("2026-05-10", "매도", 95.0, 10, "3"))], single)

    split = base_lots()
    ann1 = process_trades([new(trade("2026-05-10", "매도", 95.0, 5, "3"))], split)
    assert ann1["3"]["matched_lots"] == "TSLA-20260505-1:5"  # 청크 기준 정확 일치
    upd = trade("2026-05-10", "매도", 95.0, 10, "3")
    ann2 = process_trades([{"type": "qty_update", "trade": upd, "old_qty": 5,
                            "prev_matched": ann1["3"]["matched_lots"]}], split)
    assert ann2["3"]["matched_lots"] == "TSLA-20260501-1:10"  # 총수량 기준 재매칭
    for lid in ("TSLA-20260501-1", "TSLA-20260505-1"):
        s, p = lot_by_id(single, lid), lot_by_id(split, lid)
        assert (s["qty"], s["status"]) == (p["qty"], p["status"])
    sps = [l for l in split if l["kind"] == KIND_SELL and l["status"] == ST_ACTIVE]
    assert len(sps) == 1 and sps[0]["qty"] == 10


def test_buy_qty_update_closes_sell_points():
    """매수 추가 체결(qty_update)도 새 매수이므로 매도기준점을 닫는다."""
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
    """-25% 직행 시 -20% 단계 알림 1건만, 이후 -30% 도달 시 새 알림."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1"))], lots)
    t = datetime(2026, 5, 2)
    assert [a["condition"] for a in ev(lots, 75.0, t)] == ["추가매수-20%"]
    assert ev(lots, 89.0, t + timedelta(hours=1)) == []  # 얕은 단계 재진입 무알림
    alerts = ev(lots, 70.0, t + timedelta(hours=2))
    assert [a["condition"] for a in alerts] == ["추가매수-30%"]


def test_alert_state_json_roundtrip():
    """alert_state가 시트 저장(JSON 문자열) 왕복 후에도 계단·리마인드를 유지한다."""
    import json

    def roundtrip(lots):
        for l in lots:
            l["alert_state"] = json.loads(json.dumps(l["alert_state"]))

    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1"))], lots)
    t = datetime(2026, 5, 2)
    ev(lots, 90.0, t)
    roundtrip(lots)
    assert ev(lots, 89.0, t + timedelta(hours=1)) == []  # drop_level 유지
    roundtrip(lots)
    alerts = ev(lots, 89.5, t + timedelta(hours=25))     # last_alert 유지 → 리마인드
    assert [a["condition"] for a in alerts] == ["리마인드(추가매수-10%)"]


def test_lot_id_uses_max_seq_after_deletion():
    """사용자가 시트에서 lot 행을 지워도 새 lot_id가 기존 id와 중복되지 않는다."""
    lots = []
    process_trades([new(trade("2026-05-01", "매수", 100.0, 10, "1")),
                    new(trade("2026-05-01", "매수", 101.0, 10, "2"))], lots)
    assert [l["lot_id"] for l in lots] == ["TSLA-20260501-1", "TSLA-20260501-2"]
    del lots[0]
    process_trades([new(trade("2026-05-01", "매수", 102.0, 10, "3"))], lots)
    assert lots[-1]["lot_id"] == "TSLA-20260501-3"


def test_norm_order_no():
    """선행 0 유무가 달라도(시트 숫자 변환) 같은 주문으로 판정된다."""
    from src.state_cache import norm_order_no
    assert norm_order_no("0000117057") == norm_order_no("117057") == "117057"
    assert norm_order_no("0") == "0"
    assert norm_order_no("000") == "0"
    assert norm_order_no("") == ""
    assert norm_order_no(" 0001 ") == "1"
