"""Local cache of processed orders (second-stage dedupe) + order-number normalization.

So that lots are never applied twice even if a sheet append fails transiently, the
quantity and match result of each lot-applied order are kept in data/processed_orders.json.
The sheet-as-source-of-truth principle stands — this cache is an idempotency aid;
if deleted, it is mostly rebuilt from the sheet's 거래내역 tab (only partial fills from the gap cycles may be missed).
"""
import json
from datetime import timedelta
from pathlib import Path

RETENTION_DAYS = 14


def norm_order_no(v):
    """Normalize an order number for comparison — strip leading zeros (so it matches even if the sheet stores it as a number)."""
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
        """Record an order whose lot application finished. row is the full row for retrying the sheet append."""
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
        """Rows lot-applied but absent from the 거래내역 tab — self-recovery for failed appends."""
        return [e["row"] for n, e in sorted(self.data.items())
                if n not in sheet_order_nos and e.get("row")]

    def save(self, now):
        cutoff = (now - timedelta(days=RETENTION_DAYS)).isoformat(timespec="seconds")
        self.data = {n: e for n, e in self.data.items() if e.get("ts", "") >= cutoff}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False))
