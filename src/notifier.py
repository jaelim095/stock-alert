"""Alert delivery: KakaoTalk send-to-self plus Gmail (docs/02-design.md §6).

Kakao access token lasts 12 hours / refresh token 60 days —
when a refresh response carries a new refresh_token, it must be saved back
to the file, or the bot cannot keep running without a re-login.
"""
import json
import smtplib
import time
from email.mime.text import MIMEText
from pathlib import Path

import requests

from . import config

KAKAO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_TEXT_LIMIT = 200  # text template length limit — full text goes by email
WARN_THROTTLE_SEC = 6 * 3600  # minimum interval between re-login warning emails


class Notifier:
    def __init__(self):
        self.tokens_path = Path(config.KAKAO_TOKENS_PATH)

    def send(self, subject, text):
        """Send an alert. Returns: {"kakao": result, "email": result}

        Email follows ALERT_EMAIL_MODE: always=always alongside,
        fallback=only when KakaoTalk fails (prevents silent gaps), off=never.
        """
        res = {"kakao": self._send_kakao(text)}
        mode = config.ALERT_EMAIL_MODE
        kakao_ok = res["kakao"] == "성공"
        if mode == "always" or (mode == "fallback" and not kakao_ok):
            res["email"] = self._send_email(subject, text)
        elif mode == "fallback":
            res["email"] = "생략(카톡 성공)"
        else:
            res["email"] = "꺼짐"
        return res

    def _load_tokens(self):
        return json.loads(self.tokens_path.read_text())

    def _kakao_access_token(self):
        tok = self._load_tokens()
        if tok.get("expires_at", 0) > time.time() + 60:
            return tok["access_token"]
        payload = {
            "grant_type": "refresh_token",
            "client_id": config.KAKAO_REST_API_KEY,
            "refresh_token": tok["refresh_token"],
        }
        if config.KAKAO_CLIENT_SECRET:  # required when the app has Client Secret enabled
            payload["client_secret"] = config.KAKAO_CLIENT_SECRET
        r = requests.post(KAKAO_TOKEN_URL, data=payload, timeout=10)
        r.raise_for_status()
        d = r.json()
        tok["access_token"] = d["access_token"]
        tok["expires_at"] = time.time() + int(d.get("expires_in", 21600))
        if d.get("refresh_token"):  # only sent when expiry is under a month away — must be saved back
            tok["refresh_token"] = d["refresh_token"]
        self.tokens_path.write_text(json.dumps(tok, ensure_ascii=False))
        return tok["access_token"]

    def _warn_relogin(self, err):
        """Re-login warning email — throttled to 6 hours so it does not repeat for every alert."""
        marker = self.tokens_path.with_name("kakao_warn_last.txt")
        try:
            last = float(marker.read_text())
        except (OSError, ValueError):
            last = 0.0
        if time.time() - last < WARN_THROTTLE_SEC:
            return
        self._send_email(
            "[stock-alert] 카카오 재로그인 필요",
            f"카카오 토큰 갱신에 실패했습니다: {err}\n"
            "docs/03-setup-guide.md 카카오 절을 따라 토큰을 재발급하세요.\n"
            "재발급 전까지 알림은 이메일로만 발송됩니다.")
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(str(time.time()))
        except OSError:
            pass

    def _send_kakao(self, text):
        if not config.KAKAO_REST_API_KEY:
            return "미설정"
        try:
            token = self._kakao_access_token()
        except Exception as e:  # token refresh failed → warn by email, then run email-only
            self._warn_relogin(e)
            return f"실패(토큰): {e}"
        template = {
            "object_type": "text",
            "text": text[:KAKAO_TEXT_LIMIT],
            "link": {"web_url": "https://m.stock.naver.com"},
        }
        try:
            r = requests.post(
                KAKAO_SEND_URL,
                headers={"Authorization": f"Bearer {token}"},
                data={"template_object": json.dumps(template, ensure_ascii=False)},
                timeout=10)
            r.raise_for_status()
            return "성공"
        except Exception as e:
            return f"실패: {e}"

    def _send_email(self, subject, text):
        if not config.GMAIL_ADDRESS:
            return "미설정"
        try:
            msg = MIMEText(text, _charset="utf-8")
            msg["Subject"] = subject
            msg["From"] = config.GMAIL_ADDRESS
            msg["To"] = config.ALERT_EMAIL_TO or config.GMAIL_ADDRESS
            with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15) as s:
                s.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
                s.send_message(msg)
            return "성공"
        except Exception as e:
            return f"실패: {e}"
