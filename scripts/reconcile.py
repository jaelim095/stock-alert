#!/usr/bin/env python
"""잔고 대 lot 정합성 대조 (조회 전용).

시트가 source of truth라 사용자가 직접 고칠 수 있고, 봇이 죽어 있는 동안의
체결은 2일 조회창을 벗어나면 영영 수집되지 않는다 — 그래서 어긋남은 예외가
아니라 상시 위험이다. 어긋나면 알림 문구의 "보유 N주·평단 $X" 요약도 틀린
값을 말하게 되므로 매일 한 번 기계적으로 대조한다.

검사:
1) 감시 종목별: KIS 실제 보유수량 vs 활성 매수lot 수량 합 (1주 이상 차이 = 위반)
2) 설정 탭 감시=Y 인데 활성 lot이 하나도 없음
3) 거래내역 order_no 중복 (선행 0 정규화 후)

종료 코드: 0=정합 / 1=위반 발견 / 2=실행 오류
사용: reconcile.py [--email-on-violation]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import os  # noqa: E402
os.chdir(ROOT)

from src import config, lot_engine  # noqa: E402
from src.kis_client import KISClient  # noqa: E402
from src.notifier import Notifier  # noqa: E402
from src.sheet_client import SheetClient  # noqa: E402
from src.state_cache import norm_order_no  # noqa: E402


def main():
    email = "--email-on-violation" in sys.argv
    try:
        kis = KISClient(config.KIS_APP_KEY, config.KIS_APP_SECRET,
                        config.KIS_ACCOUNT_NO, config.KIS_ENV, config.KIS_TOKEN_PATH)
        sheets = SheetClient(config.GOOGLE_SERVICE_ACCOUNT_JSON, config.SHEET_ID)
        holdings = {h["ticker"]: int(h["qty"]) for h in kis.fetch_holdings()}
        lots = sheets.read_lots()
        settings = sheets.read_settings()
        trades = sheets.read_trades()
    except Exception as e:
        print(f"실행 오류: {e}")
        sys.exit(2)

    violations = []
    watch = sorted(t for t, s in settings.items() if s.get("enabled"))
    for t in watch:
        lot_qty = sum(int(l["qty"]) for l in lots
                      if l["ticker"] == t and l["kind"] == lot_engine.KIND_BUY
                      and l["status"] == lot_engine.ST_ACTIVE)
        real = holdings.get(t, 0)
        if abs(real - lot_qty) >= 1:
            violations.append(
                f"{t}: 실제 보유 {real}주 vs 활성 매수lot 합 {lot_qty}주"
                f" (차이 {real - lot_qty:+d}주)")
        if not any(l["ticker"] == t and l["status"] == lot_engine.ST_ACTIVE
                   for l in lots):
            violations.append(f"{t}: 감시=Y 인데 활성 lot 없음 — 봇이 볼 게 없음")

    seen, dup = set(), set()
    for tr in trades:
        n = norm_order_no(tr["order_no"])
        if not n:
            continue
        if n in seen:
            dup.add(n)
        seen.add(n)
    if dup:
        sample = ", ".join(sorted(dup)[:5])
        violations.append(f"거래내역 order_no 중복 {len(dup)}건: {sample}"
                          + (" 외" if len(dup) > 5 else ""))

    if not violations:
        print(f"정합 OK — 감시 종목 {', '.join(watch) or '없음'}")
        sys.exit(0)

    report = (
        "시트 lot과 실제 잔고가 어긋났습니다. 시트가 source of truth이므로\n"
        "구글시트 활성감시 탭에서 직접 수정해야 합니다 (봇은 자동 수정하지 않음).\n\n"
        + "\n".join(f"- {v}" for v in violations)
        + "\n\n주의: lot이 실제보다 적으면 그 수량만큼 감시·알림이 빠지고,\n"
          "알림 문구의 보유/평단 요약도 어긋난 값을 표시합니다.")
    print(report)
    if email:
        Notifier()._send_email("[stock-alert] 잔고-lot 정합성 위반", report)
    sys.exit(1)


if __name__ == "__main__":
    main()
