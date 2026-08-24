"""Snapshot of holdings, watch settings, and trades (read-only) — data source for the /checkup skill.

Prints the KIS balance plus Google Sheet data (활성감시/설정 tabs, recent trades) as markdown.
No order-family APIs are used.

Usage:
  .venv/bin/python scripts/portfolio_snapshot.py            # last 20 trades
  .venv/bin/python scripts/portfolio_snapshot.py --trades 50
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config, lot_engine  # noqa: E402
from src.kis_client import KISClient  # noqa: E402
from src.sheet_client import SheetClient  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades", type=int, default=20, help="최근 매매 표시 건수")
    args = ap.parse_args()

    now = datetime.now(ZoneInfo("Asia/Seoul"))
    print(f"# 포트폴리오 스냅샷 ({now.strftime('%Y-%m-%d %H:%M')} KST)\n")

    k = KISClient(config.KIS_APP_KEY, config.KIS_APP_SECRET,
                  config.KIS_ACCOUNT_NO, config.KIS_ENV, config.KIS_TOKEN_PATH)
    holdings = k.fetch_holdings()
    total = sum(h["value"] for h in holdings)

    print(f"## 보유 종목 (미국, {len(holdings)}개 · 평가 총액 ${total:,.0f})\n")
    print("| 종목 | 이름 | 수량 | 평단$ | 현재$ | 평가$ | 손익% | 비중% |")
    print("|---|---|---|---|---|---|---|---|")
    for h in holdings:
        w = h["value"] / total * 100 if total else 0
        print(f"| {h['ticker']} | {h['name']} | {h['qty']:.0f} | {h['avg']:.2f} "
              f"| {h['now']:.2f} | {h['value']:,.0f} | {h['pnl_pct']} | {w:.1f} |")

    try:
        sc = SheetClient(config.GOOGLE_SERVICE_ACCOUNT_JSON, config.SHEET_ID)
    except Exception as e:
        print(f"\n(시트 연결 실패 — lot/매매 생략: {e})")
        return

    settings = sc.read_settings()
    print("\n## 알림 감시 설정 (봇)\n")
    if settings:
        for t, s in settings.items():
            print(f"- {t}: 감시={'Y' if s['enabled'] else 'N'}, "
                  f"하락임계 {s['drop_pct'] or config.DEFAULT_DROP_PCT}%, "
                  f"상승임계 {s['rise_pct'] or config.DEFAULT_RISE_PCT}%")
    else:
        print("- (없음)")

    thesis = sc.read_thesis()
    print(f"\n## 투자논리 ({len(thesis)}건)\n")
    if thesis:
        for t in thesis:
            print(f"- {t['ticker']}: 이유={t['reason']} | 가정={t['assumption']} "
                  f"| 무효화={t['invalidation']} (점검 {t['last_checked'] or '-'})")
    else:
        print("- (미기록 — 투자논리 탭이 비어 있음)")

    lots = [l for l in sc.read_lots() if l["status"] == lot_engine.ST_ACTIVE]
    print(f"\n## 활성 감시 lot ({len(lots)}개)\n")
    for l in lots:
        print(f"- {l['lot_id']} [{l['kind']}] 기준 ${l['base_price']} × {l['qty']}주, "
              f"등락 {l['change_pct']}%")

    trades = sc.read_trades()
    recent = sorted(trades, key=lambda t: (t["trade_date"], t["recorded_at"]))[-args.trades:]
    print(f"\n## 최근 매매 (시트 기록 {len(recent)}건 / 전체 {len(trades)}건)\n")
    for t in recent:
        print(f"- {t['trade_date']} {t['side']} {t['ticker']} {t['qty']}주 @ ${t['price']}"
              + (f" ({t['note']})" if t["note"] else ""))


if __name__ == "__main__":
    main()
