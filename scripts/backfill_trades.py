#!/usr/bin/env python
"""과거 체결 백필 — 일회성, 조회 전용, 거래내역 탭에만 기록.

봇은 2일 조회창만 보므로 봇이 죽어 있던 기간의 체결은 영영 수집되지 않는다
(실사례: 2026-07-20~30 정지 중 TSLL 230주 매수 누락). 이 스크립트가 과거
구간을 30일 조각으로 걸어가며 시트에 없는 체결을 채운다.

원칙:
- lot은 만들지 않는다. 과거 체결로 lot을 만들면 -10/-20/-30 계단 알림이
  한꺼번에 터진다. 비고에 "백필"만 남긴다 (seed 이전 체결과 같은 취급).
  감시 lot 수량 보정은 사용자가 시트 활성감시 탭에서 직접 한다.
- KIS 체결내역 조회는 과거 기간 상한이 있을 수 있다 — 조회가 실패하는
  조각을 만나면 거기서 멈추고 실제 도달 범위를 보고한다.

사용: backfill_trades.py [--days 90] [--dry-run]
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
    # 어제·오늘 제외: 미정산 체결이 섞인 구간은 SYDB0050(조회 이후 자료 변경)을
    # 낸다 (실측: D-1 실패, D-2 성공). 그 이틀은 봇의 2일 창이 담당 — 공백 없음.
    end = today - timedelta(days=2)
    new_rows, reached = [], end
    while end > today - timedelta(days=args.days):
        start = max(end - timedelta(days=CHUNK_DAYS - 1),
                    today - timedelta(days=args.days))
        fetched = None
        for attempt in (1, 2, 3):  # SYDB0050(조회 중 자료 변경) 등 일시 오류 재시도
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
