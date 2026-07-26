"""구글시트 연동 (gspread + 서비스 계정). 탭·헤더는 docs/02-design.md 4절 기준.

시트가 source of truth — 매 주기 전체를 다시 읽고, lot 탭은 통째로 다시 쓴다.
- 모든 쓰기는 RAW: 주문번호 선행 0, 날짜 문자열이 시트에서 변형되지 않게
- 열 위치는 1행 헤더를 실제로 읽어 매핑: 사용자가 열을 옮기거나 추가해도 안전
- 모든 호출 1회 재시도(2초 대기) — 설계 9절
"""
import json
import time

import gspread

from .state_cache import norm_order_no

TAB_TRADES = "거래내역"
TAB_LOTS = "활성감시"
TAB_ALERTS = "알림로그"
TAB_SETTINGS = "설정"

TRADE_COLS = [
    ("기록시각", "recorded_at"), ("체결일", "trade_date"), ("종목코드", "ticker"),
    ("종목명", "name"), ("구분", "side"), ("체결단가", "price"), ("체결수량", "qty"),
    ("체결금액", "amount"), ("주문번호", "order_no"), ("매칭lot", "matched_lots"),
    ("비고", "note"),
]
LOT_COLS = [
    ("lot_id", "lot_id"), ("종목코드", "ticker"), ("유형", "kind"),
    ("기준일", "base_date"), ("기준가", "base_price"), ("수량", "qty"),
    ("상태", "status"), ("현재가", "last_price"), ("등락률", "change_pct"),
    ("알림상태", "alert_state"), ("종료사유", "closed_reason"),
]
ALERT_COLS = [
    ("발송시각", "sent_at"), ("종목코드", "ticker"), ("lot_id", "lot_id"),
    ("조건", "condition"), ("기준가", "base_price"), ("현재가", "price"),
    ("등락률", "change_pct"), ("메시지", "message"), ("채널", "channel"),
    ("결과", "result"),
]
SETTING_COLS = [
    ("종목코드", "ticker"), ("거래소", "excd"), ("하락임계%", "drop_pct"),
    ("상승임계%", "rise_pct"), ("감시", "enabled"), ("메모", "memo"),
]
TAB_THESIS = "투자논리"
THESIS_COLS = [
    ("종목코드", "ticker"), ("매수 이유", "reason"), ("핵심 가정", "assumption"),
    ("무효화 조건", "invalidation"), ("작성일", "created_at"), ("최근점검일", "last_checked"),
]

HEADERS = {
    TAB_TRADES: [h for h, _ in TRADE_COLS],
    TAB_LOTS: [h for h, _ in LOT_COLS],
    TAB_ALERTS: [h for h, _ in ALERT_COLS],
    TAB_SETTINGS: [h for h, _ in SETTING_COLS],
    TAB_THESIS: [h for h, _ in THESIS_COLS],
}


def _retry(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        time.sleep(2)
        return fn(*args, **kwargs)


def _f(v, default=0.0):
    try:
        return float(str(v).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        return default


def _i(v, default=0):
    return int(_f(v, default))


class SheetClient:
    def __init__(self, sa_json_path, sheet_id):
        self.gc = gspread.service_account(filename=sa_json_path)
        # 타임아웃 없으면 소켓이 매달릴 때 루프가 영원히 멈춘다 (2026-07-20 실제 6일 정지)
        self.gc.set_timeout((10, 30))
        self.doc = _retry(self.gc.open_by_key, sheet_id)

    def _ws(self, tab):
        return _retry(self.doc.worksheet, tab)

    def _read(self, tab, cols):
        """(values, keys) — values[0]=실제 헤더, keys[i]=i열의 내부 키(모르는 헤더는 None)."""
        values = _retry(self._ws(tab).get_all_values)
        if not values or not any(h.strip() for h in values[0]):
            raise ValueError(f"'{tab}' 탭에 헤더가 없습니다 — scripts/init_sheet.py 실행 필요")
        by_name = dict(cols)
        header = [h.strip() for h in values[0]]
        keys = [by_name.get(h) for h in header]
        missing = [h for h, _ in cols if h not in header]
        if missing:
            raise ValueError(f"'{tab}' 탭 필수 헤더 누락: {missing} — 열 이름을 되돌리거나 "
                             "scripts/init_sheet.py 헤더로 맞춰야 합니다")
        return values, keys

    def _rows(self, tab, cols):
        values, keys = self._read(tab, cols)
        rows = []
        for raw in values[1:]:
            if not any(cell.strip() for cell in raw):
                continue
            row = {k: "" for _, k in cols}
            extra = {}
            for i, key in enumerate(keys):
                cell = raw[i].strip() if i < len(raw) else ""
                if key:
                    row[key] = cell
                elif values[0][i].strip():
                    extra[values[0][i].strip()] = cell
            if extra:
                row["_extra"] = extra  # 사용자 추가 열 보존용
            rows.append(row)
        return rows

    def _append(self, tab, cols, dicts):
        _, keys = self._read(tab, cols)
        rows = [[("" if k is None else d.get(k, "")) for k in keys] for d in dicts]
        _retry(self._ws(tab).append_rows, rows, value_input_option="RAW")

    # ── 거래내역 ──────────────────────────────────────────

    def read_trades(self):
        rows = self._rows(TAB_TRADES, TRADE_COLS)
        for r in rows:
            r["price"] = _f(r["price"])
            r["qty"] = _i(r["qty"])
            r["amount"] = _f(r["amount"])
        return rows

    def append_trades(self, trades):
        self._append(TAB_TRADES, TRADE_COLS, trades)

    def update_trade(self, order_no, qty, amount, matched_lots=None, note=None):
        """부분 체결 반영: 주문번호(정규화 비교)로 행을 찾아 수량·금액·매칭 갱신."""
        values, keys = self._read(TAB_TRADES, TRADE_COLS)
        oc = keys.index("order_no")
        target = norm_order_no(order_no)
        row_idx = None
        for i, raw in enumerate(values[1:], start=2):
            if oc < len(raw) and norm_order_no(raw[oc]) == target:
                row_idx = i
                break
        if row_idx is None:
            return False
        updates = {"qty": qty, "amount": amount}
        if matched_lots is not None:
            updates["matched_lots"] = matched_lots
        if note:
            updates["note"] = note
        data = [{"range": gspread.utils.rowcol_to_a1(row_idx, keys.index(k) + 1),
                 "values": [[v]]} for k, v in updates.items()]
        _retry(self._ws(TAB_TRADES).batch_update, data, value_input_option="RAW")
        return True

    # ── 활성감시 (lot) ────────────────────────────────────

    def read_lots(self):
        rows = self._rows(TAB_LOTS, LOT_COLS)
        for r in rows:
            r["base_price"] = _f(r["base_price"])
            r["qty"] = _i(r["qty"])
            r["last_price"] = _f(r["last_price"]) if r["last_price"] else ""
            r["change_pct"] = _f(r["change_pct"]) if r["change_pct"] else ""
            try:
                r["alert_state"] = json.loads(r["alert_state"]) if r["alert_state"] else {}
            except ValueError:
                r["alert_state"] = {}
        return rows

    def write_lots(self, lots):
        """활성감시 탭 전체 재작성 — clear 없이 단일 update 호출.

        clear 후 update의 2단계는 중간 실패 시 유일한 상태 저장소가 통째로
        비는 사고가 나므로 금지. 이전 데이터가 더 길었던 만큼 빈 행을 같은
        페이로드에 포함해 한 번에 덮는다.
        """
        values, keys = self._read(TAB_LOTS, LOT_COLS)
        header = values[0]
        rows = [header]
        for lot in lots:
            d = dict(lot)
            d["alert_state"] = json.dumps(lot.get("alert_state") or {}, ensure_ascii=False)
            extra = lot.get("_extra") or {}
            rows.append([d.get(k, "") if k else extra.get(header[i].strip(), "")
                         for i, k in enumerate(keys)])
        while len(rows) < len(values):
            rows.append([""] * len(header))
        _retry(self._ws(TAB_LOTS).update,
               values=rows, range_name="A1", value_input_option="RAW")

    # ── 알림로그 / 설정 ───────────────────────────────────

    def append_alerts(self, alerts):
        self._append(TAB_ALERTS, ALERT_COLS, alerts)

    def read_alerts(self):
        return self._rows(TAB_ALERTS, ALERT_COLS)

    def read_settings(self):
        """{ticker: {excd, drop_pct|None, rise_pct|None, enabled, memo}}"""
        out = {}
        for r in self._rows(TAB_SETTINGS, SETTING_COLS):
            if not r["ticker"]:
                continue
            out[r["ticker"].upper()] = {
                "excd": (r["excd"] or "NAS").upper(),
                "drop_pct": _f(r["drop_pct"]) or None,
                "rise_pct": _f(r["rise_pct"]) or None,
                "enabled": r["enabled"].strip().upper() == "Y",
                "memo": r["memo"],
            }
        return out

    # ── 투자논리 ─────────────────────────────────────────

    def read_thesis(self):
        """투자논리 행 목록. 탭이 아직 없으면 빈 목록 (init_sheet 전 호환)."""
        try:
            return self._rows(TAB_THESIS, THESIS_COLS)
        except gspread.exceptions.WorksheetNotFound:
            return []

    def append_thesis(self, rows):
        self._append(TAB_THESIS, THESIS_COLS, rows)

    def update_thesis_checked(self, ticker, date_str):
        """해당 종목 행의 최근점검일 갱신. 행이 없으면 False."""
        values, keys = self._read(TAB_THESIS, THESIS_COLS)
        tc = keys.index("ticker")
        for i, raw in enumerate(values[1:], start=2):
            if tc < len(raw) and raw[tc].strip().upper() == str(ticker).upper():
                _retry(self._ws(TAB_THESIS).update_cell,
                       i, keys.index("last_checked") + 1, date_str)
                return True
        return False
