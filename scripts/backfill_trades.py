#!/usr/bin/env python
"""Backfill past executions — one-off, read-only, writes only to the 거래내역 tab.

The bot only looks at a 2-day window, so executions from periods when the bot
was down are never collected (real case: a 230-share TSLL buy was missed during
the 2026-07-20~30 outage). This script walks backwards through the past in
30-day chunks and fills in executions missing from the sheet.

Principles:
- No lots are created. Creating lots from past executions would fire the
  -10/-20/-30 ladder alerts all at once. Only "백필" is written to the note
  field (same treatment as pre-seed executions). The user adjusts watched-lot
  quantities directly in the sheet's 활성감시 tab.
- KIS execution inquiries may have an upper bound on how far back they reach —
  when a chunk fails to fetch, stop there and report the range actually reached.

Usage: backfill_trades.py [--days 90] [--dry-run]
"""
import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import os  # noqa: E402
os.chdir(ROOT)

from src import config  # noqa: E402
from src.kis_client import KISClient, US_EASTERN  # noqa: E402
from src.sheet_client import SheetClient  # noqa: E402
from src.state_cache import norm_order_no  # noqa: E402

CHUNK_DAYS = 30


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90,
                        help="오늘부터 며칠 전까지 거슬러 조회할지 (기본 90)")
    parser.add_argument("--dry-run", action="store_true",
                        help="시트에 쓰지 않고 찾은 체결만 출력")
    args = parser.parse_args()

    kis = KISClient(config.KIS_APP_KEY, config.KIS_APP_SECRET,
                    config.KIS_ACCOUNT_NO, config.KIS_ENV, config.KIS_TOKEN_PATH)
    sheets = SheetClient(config.GOOGLE_SERVICE_ACCOUNT_JSON, config.SHEET_ID)

    existing = set()
    for t in sheets.read_trades():
        n = norm_order_no(t["order_no"])
        if n:
            existing.add(n)
    print(f"시트 기존 거래 {len(existing)}건")

    today = datetime.now(US_EASTERN).date()
    # Exclude yesterday and today: ranges containing unsettled executions raise
    # SYDB0050 (measured: D-1 fails, D-2 works). The bot's 2-day window covers those two days — no gap.
    end = today - timedelta(days=2)
    new_rows, reached = [], end
    while end > today - timedelta(days=args.days):
        start = max(end - timedelta(days=CHUNK_DAYS - 1),
                    today - timedelta(days=args.days))
        fetched = None
        for attempt in (1, 2, 3):  # retry transient errors such as SYDB0050 (data changed during inquiry)
            try:
                fetched = kis.fetch_executions(start=start, end=end)
                break
            except Exception as e:
                if attempt == 3:
                    print(f"{start}~{end} 조회 3회 실패 — 여기서 중단"
                          f" (KIS 기간 상한 또는 지속 오류): {e}")
                else:
                    time.sleep(3)
        if fetched is None:
            break
        fresh = [t for t in fetched
                 if norm_order_no(t["order_no"])
                 and norm_order_no(t["order_no"]) not in existing]
        for t in fresh:
            t["note"] = "백필"
            existing.add(norm_order_no(t["order_no"]))
        new_rows.extend(fresh)
        print(f"{start}~{end}: 조회 {len(fetched)}건, 신규 {len(fresh)}건")
        reached = start
        end = start - timedelta(days=1)

    new_rows.sort(key=lambda t: (t["trade_date"], t["order_no"]))
    print(f"\n조회 도달 범위: {reached} ~ {today}")
    if not new_rows:
        print("추가할 체결 없음")
        return
    print(f"신규 체결 {len(new_rows)}건:")
    for t in new_rows:
        print(f"- {t['trade_date']} {t['side']} {t['ticker']} "
              f"{t['qty']}주 @ ${t['price']} (주문 {t['order_no']})")
    if args.dry_run:
        print("\n[dry-run] 시트에 쓰지 않음")
        return
    sheets.append_trades(new_rows)
    print(f"\n거래내역 탭에 {len(new_rows)}건 기록 완료 (비고=백필, lot 미생성)")
    print("감시 lot 수량이 어긋나 있으면 시트 활성감시 탭에서 직접 보정하세요"
          " (scripts/reconcile.py 리포트 참고)")


if __name__ == "__main__":
    main()
