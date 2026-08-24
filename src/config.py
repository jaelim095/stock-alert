"""Load configuration. All secrets are read from .env."""
import os

from dotenv import load_dotenv

load_dotenv()

# Korea Investment & Securities
KIS_APP_KEY = os.getenv("KIS_APP_KEY", "")
KIS_APP_SECRET = os.getenv("KIS_APP_SECRET", "")
KIS_ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO", "")  # "12345678-01"
KIS_ENV = os.getenv("KIS_ENV", "vps")  # vps=paper trading, prod=live

# Google Sheets
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "./secrets/service_account.json")
SHEET_ID = os.getenv("SHEET_ID", "")

# KakaoTalk
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "")
KAKAO_CLIENT_SECRET = os.getenv("KAKAO_CLIENT_SECRET", "")  # only when a Client Secret is in use
KAKAO_TOKENS_PATH = os.getenv("KAKAO_TOKENS_PATH", "./data/kakao_tokens.json")

# Email
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "")  # app password must contain no spaces
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO", "")
# always=always alongside KakaoTalk / fallback=only when KakaoTalk fails / off=no email alerts
ALERT_EMAIL_MODE = os.getenv("ALERT_EMAIL_MODE", "always").strip().lower()

# Behavior settings
POLL_INTERVAL_MIN = int(os.getenv("POLL_INTERVAL_MIN", "5"))
DEFAULT_DROP_PCT = float(os.getenv("DEFAULT_DROP_PCT", "10"))
DEFAULT_RISE_PCT = float(os.getenv("DEFAULT_RISE_PCT", "10"))
REMIND_INTERVAL_HOURS = float(os.getenv("REMIND_INTERVAL_HOURS", "24"))
ENABLE_DAY_MARKET = os.getenv("ENABLE_DAY_MARKET", "false").lower() == "true"

KIS_TOKEN_PATH = "./data/kis_token.json"
PROCESSED_ORDERS_PATH = "./data/processed_orders.json"  # cache of orders already applied to lots (second-stage dedupe)
HEARTBEAT_PATH = "./data/heartbeat.json"  # cycle liveness signal — read by the watchdog and dashboard

# leveraged ETF → underlying asset (for effective-exposure totals and underlying analysis)
UNDERLYING_MAP = {"TSLL": "TSLA", "METU": "META", "IRE": "IREN"}

def account_parts():
    """Split the account number into (first 8 digits, last 2 digits)."""
    cano, _, prdt = KIS_ACCOUNT_NO.partition("-")
    return cano, prdt or "01"
