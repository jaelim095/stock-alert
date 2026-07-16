"""처리 완료 주문 로컬 캐시 (2차 dedupe) + 주문번호 정규화.

시트 append가 일시 실패해도 lot이 중복 반영되지 않도록, lot 반영이 끝난
주문의 수량·매칭 결과를 data/processed_orders.json에 남긴다.
시트가 source of truth 원칙은 유지 — 이 캐시는 멱등성 보조 장치이며,
지워져도 시트 거래내역 기준으로 대부분 복원된다(그 사이 주기의 부분체결만 놓칠 수 있음).
"""
import json
from datetime import timedelta
from pathlib import Path

RETENTION_DAYS = 14


def norm_order_no(v):
    """주문번호 비교용 정규화 — 선행 0 제거 (시트가 숫자로 저장해도 일치하도록)."""
    s = str(v).strip()
    if not s:
        return ""
    return s.lstrip("0") or "0"


class ProcessedOrders:
    def __init__(self, path):
        self.path = Path(path)
        self.data = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except (ValueError, OSError):
                self.data = {}

    def get(self, order_no):
        return self.data.get(norm_order_no(order_no))

    def record(self, trade, matched_lots, note, now):
        """lot 반영이 끝난 주문을 기록. row는 시트 append 재시도용 전체 행."""
        row = dict(trade)
        row["matched_lots"] = matched_lots
        row["note"] = note
        self.data[norm_order_no(trade["order_no"])] = {
            "qty": int(trade["qty"]),
            "matched_lots": matched_lots,
            "note": note,
            "row": row,
            "ts": now.isoformat(timespec="seconds"),
        }

    def pending_rows(self, sheet_order_nos):
        """lot 반영은 끝났지만 거래내역 탭에 없는 행 — append 실패 자가 복구용."""
        return [e["row"] for n, e in sorted(self.data.items())
                if n not in sheet_order_nos and e.get("row")]

    def save(self, now):
        cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
        self.data = {n: e for n, e in self.data.items() if e.get("ts", "") >= cutoff}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False))
