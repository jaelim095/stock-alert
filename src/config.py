"""환경설정 로드. 모든 비밀값은 .env에서 읽는다."""
import os

from dotenv import load_dotenv

load_dotenv()

# 한국투자증권
KIS_APP_KEY = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
KIS_ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO", "")  # "12345678-01"
KIS_ENV = os.getenv("KIS_ENV", "vps")  # vps=모의, prod=실전

# 구글시트
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "./secrets/service_account.json")
SHEET_ID = os.getenv("SHEET_ID", "")

# 카카오톡
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET", "")  # Client Secret 사용 시에만
KAKAO_TOKENS_PATH = os.getenv("KAKAO_TOKENS_PATH", "./data/kakao_tokens.json")

# 이메일
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")  # 앱 비밀번호는 공백 없이
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
# always=카톡과 항상 병행 / fallback=카톡 실패 시에만 / off=이메일 알림 안 씀
ALERT_EMAIL_MODE = os.getenv("ALERT_EMAIL_MODE", "always").strip().lower()

# 동작 설정
POLL_INTERVAL_MIN = int(os.getenv("POLL_INTERVAL_MIN", "5"))
DEFAULT_DROP_PCT = float(os.getenv("DEFAULT_DROP_PCT", "10"))
DEFAULT_RISE_PCT = float(os.getenv("DEFAULT_RISE_PCT", "10"))
REMIND_INTERVAL_HOURS = float(os.getenv("REMIND_INTERVAL_HOURS", "24"))
ENABLE_DAY_MARKET = os.getenv("ENABLE_DAY_MARKET", "false").lower() == "true"

KIS_TOKEN_PATH = "./data/kis_token.json"
PROCESSED_ORDERS_PATH = "./data/processed_orders.json"  # lot 반영 완료 주문 캐시 (2차 dedupe)

def account_parts():
    """계좌번호를 (앞 8자리, 뒤 2자리)로 분리."""
    cano, _, prdt = KIS_ACCOUNT_NO.partition("-")
    return cano, prdt or "01"
