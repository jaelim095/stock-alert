"""구글시트에 4개 탭과 헤더를 생성한다 (이미 있으면 건너뜀).

사용: .venv/bin/python scripts/init_sheet.py
사전 조건: .env의 SHEET_ID, GOOGLE_SERVICE_ACCOUNT_JSON,
          시트를 서비스 계정 이메일에 편집자로 공유해둘 것.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gspread

from src import config
from src.sheet_client import HEADERS


def main():
    if not config.SHEET_ID:
        sys.exit("SHEET_ID가 .env에 없습니다. docs/03-setup-guide.md 참고.")
    gc = gspread.service_account(filename=config.GOOGLE_SERVICE_ACCOUNT_JSON)
    doc = gc.open_by_key(config.SHEET_ID)
    existing = {ws.title for ws in doc.worksheets()}
    for tab, headers in HEADERS.items():
        if tab in existing:
            print(f"스킵(이미 존재): {tab}")
            continue
        ws = doc.add_worksheet(title=tab, rows=1000, cols=len(headers))
        ws.update(values=[headers], range_name="A1")
        print(f"생성: {tab}")
    print("완료. 설정 탭에 감시 종목을 입력하세요. 예: TSLA | NAS | 10 | 10 | Y")


if __name__ == "__main__":
    main()
