# Setup Guide — Preparation Steps the User Must Do Manually

Before running the bot, work through steps 1-4 (issuing keys for external services) and 5-9 (local install and launch) in order.
Expect the whole process to take about 1.5-2 hours the first time through.

Table of contents
1. Korea Investment & Securities (KIS) Open API application (30 min; extra time if you have no account)
2. KakaoTalk send-to-myself setup (20 min)
3. Google Sheets + service account (20 min)
4. Gmail app password (5 min)
5. Local install and .env setup (10 min)
6. Sheet initialization (1 min)
7. Single-run test (5 min)
8. Always-on registration — launchd (5 min)
9. Preventing Mac sleep (5 min)
10. Troubleshooting

---

## 1. Korea Investment & Securities (KIS) Open API Application (about 30 min)

If you already have an account, you only need to apply for API access. If not, start with remote account opening (about 20 minutes in the app).

1. Log in to the KIS website → in the menu, go to `트레이딩 > Open API > KIS Developers` (Trading > Open API > KIS Developers)
2. Apply for the Open API service → get a production (live trading) App Key / App Secret issued
3. Also apply for paper trading. Sign up for the paper trading service first, then get a separate paper-trading App Key / App Secret. This is required, because you will test with the paper keys first.
4. Store all four keys (production key/secret, paper key/secret) somewhere safe. In some cases the secret cannot be viewed again after you leave the screen, so copy it on the spot.

Note: on the KIS Developers portal (apiportal.koreainvestment.com), be sure to read the notice posted 2026-03-20 titled "[중요] 신규 고객 초당 호출 제한 안내" (Important: per-second call limit notice for new customers).
New sign-ups may be subject to a lower call limit. This bot makes only a small number of calls on a 5-minute cycle, so it is usually fine, but it is worth checking the actual limit numbers.

The issued keys go into `KIS_APP_KEY` and `KIS_APP_SECRET` in `.env` in step 5.
The account number (first 8 digits - last 2 digits) goes into `KIS_ACCOUNT_NO`. Example: `12345678-01`

## 2. KakaoTalk Send-to-Myself Setup (about 20 min)

This setup lets the bot send alerts to your own KakaoTalk. It works as a personal app with no review process.

1. Go to https://developers.kakao.com and log in with your Kakao account
2. `내 애플리케이션 > 애플리케이션 추가하기` (My Applications > Add Application) → app name e.g. `stock-alert` (anything works)
3. Select the new app → copy the REST API key from the `앱 키` (App Keys) menu → use it as `KAKAO_REST_API_KEY` in `.env`
4. `제품 설정 > 카카오 로그인` (Product Settings > Kakao Login) → toggle it ON
5. Register `http://localhost:8080` as a Redirect URI — after the console redesign, this lives in the `리다이렉트 URI` (Redirect URI) area inside the REST API key section under `앱 > 플랫폼 키` (App > Platform Keys). (Do not append a trailing `/` — that causes KOE006.)
6. `제품 설정 > 카카오 로그인 > 동의항목` (Product Settings > Kakao Login > Consent Items) → set `카카오톡 메시지 전송 (talk_message)` (send KakaoTalk message) to optional consent.
   Be sure to finish this before step 8 (browser login) — if you log in before configuring the consent item, the app gets linked without the message permission, and sending fails with 403 (-402 insufficient scopes). In that case, log in again and grant the additional consent.
7. If you enabled Client Secret under `제품 설정 > 카카오 로그인 > 보안` (Product Settings > Kakao Login > Security), put that value into `KAKAO_CLIENT_SECRET` in `.env` (requesting a token without this value while it is enabled causes a KOE010 error)

Now issue the initial tokens, one time only. This is the only part that needs a browser; after this the bot refreshes tokens automatically.

8. Paste the URL below into the browser address bar (replace the REST_API_KEY part):

```
https://kauth.kakao.com/oauth/authorize?client_id=REST_API_KEY&redirect_uri=http://localhost:8080&response_type=code&scope=talk_message
```

   On the consent screen, confirm that the `카카오톡 메시지 전송` (send KakaoTalk message) checkbox is shown, then agree.
9. After you agree and continue, the browser is redirected to `http://localhost:8080/?code=XXXX...` and shows a "can't connect" page. This is expected. Copy the value after `code=` from the address bar.
   (Misreading a character while copying the code by hand causes KOE320. To avoid mistakes, you can also run a temporary listener on port 8080 to capture the code automatically — that is how the initial setup was done.)
10. In the terminal, exchange the authorization code for tokens (the code is single-use and expires within a few minutes of issuance; if Client Secret is enabled, add the `-d client_secret=...` line):

```
curl -X POST https://kauth.kakao.com/oauth/token \
  -d grant_type=authorization_code \
  -d client_id=REST_API_KEY \
  -d client_secret=CLIENT_SECRET값_활성화시에만 \
  -d redirect_uri=http://localhost:8080 \
  -d code=복사한_코드
```

    (In the command above, `CLIENT_SECRET값_활성화시에만` is a placeholder for "your Client Secret — only when enabled", and `복사한_코드` for "the code you copied in step 9".)

11. Save the access_token and refresh_token from the JSON response into the file `data/kakao_tokens.json`:

```
{
  "access_token": "access_token value from the response",
  "refresh_token": "refresh_token value from the response"
}
```

```
mkdir -p data && vi data/kakao_tokens.json   # paste the content above
```

Note: the access token is valid for 12 hours, the refresh token for 60 days.
While the bot is running, it refreshes them automatically and overwrites the file on its own.
However, if the bot has been off for 2+ months, the refresh token expires — just redo steps 8-11.
In that case the bot sends a warning email titled "[stock-alert] 카카오 재로그인 필요" (Kakao re-login required).

## 3. Google Sheets + Service Account (about 20 min)

A service account is required so the bot can write to the sheet without a human login.

1. Go to https://console.cloud.google.com → create a new project (name e.g. stock-alert)
2. In `API 및 서비스 > 라이브러리` (APIs & Services > Library), search for Google Sheets API → enable it. Enable the Google Drive API the same way
3. `API 및 서비스 > 사용자 인증 정보 > 사용자 인증 정보 만들기 > 서비스 계정` (APIs & Services > Credentials > Create Credentials > Service Account) → enter a name and create it (the role can be left empty)
4. Click the created service account → `키` (Keys) tab → `키 추가 > 새 키 만들기 > JSON` (Add Key > Create New Key > JSON) → download
5. Move the downloaded file into the project:

```
mkdir -p secrets
mv ~/Downloads/stock-alert-*.json secrets/service_account.json
```

6. Create a new spreadsheet at https://sheets.google.com (name e.g. `주식 매매기록`, "stock trade log")
7. Click `공유` (Share) at the top right of the sheet → add the service account email (`xxx@PROJECT_ID.iam.gserviceaccount.com`, the client_email value inside the JSON file) with editor permission

Skipping the share in step 7 is the most common mistake. Without it, the bot cannot find the sheet.

8. Copy the SHEET_ID from the sheet URL. It is the string between `/d/` and `/edit`:

```
https://docs.google.com/spreadsheets/d/1AbCdEfGh.../edit   ← the 1AbCdEfGh... part
```

## 4. Gmail App Password (about 5 min)

1. https://myaccount.google.com → `보안` (Security) → turn on 2-Step Verification if it is off
2. Go to https://myaccount.google.com/apppasswords → enter an app name (e.g. stock-alert) → create
3. Copy the 16-character password shown → use it as `GMAIL_APP_PASSWORD` in `.env` (remove the spaces)

## 5. Local Install and .env Setup (about 10 min)

```
cd ~/stock-alert
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and fill in the values prepared in steps 1-4.
Starting with `KIS_ENV=vps` (paper trading) plus the paper-trading app key is recommended.
Buy one or two US stocks in the paper account, confirm the bot records them correctly, then switch to production.

To change the watch thresholds (default 10%), edit `DEFAULT_DROP_PCT` and `DEFAULT_RISE_PCT`.
For per-ticker thresholds, adjust them later in the sheet's 설정 (Settings) tab.

## 6. Sheet Initialization (1 min)

```
.venv/bin/python scripts/init_sheet.py
```

This creates four tabs with headers in the sheet: 거래내역 (trade history) / 활성감시 (active watches) / 알림로그 (alert log) / 설정 (settings).
When it finishes, open the sheet and enter the tickers to watch in the 설정 (Settings) tab. Example:

| 종목코드 (Ticker) | 거래소 (Exchange) | 하락임계% (Drop threshold %) | 상승임계% (Rise threshold %) | 감시 (Watch) | 메모 (Memo) |
|---|---|---|---|---|---|
| TSLA | NAS | | | Y | |
| PLTR | NYS | 15 | 10 | Y | Volatile ticker, so 15% |

Exchanges: NAS (Nasdaq) / NYS (NYSE) / AMS (AMEX). Leave a threshold empty to use the `.env` default.

## 7. Single-Run Test (about 5 min)

```
.venv/bin/python -m src.main --once
```

What to check:
- The cycle completes without errors
- If there are recent fills, rows appear in the 거래내역 (trade history) tab and lots appear in the 활성감시 (active watches) tab
- If any lot already meets an alert condition, the KakaoTalk message and email actually arrive

At this stage, errors may occur because KIS response field names differ from what the code expects (the code was drafted without access to a real account).
If that happens, show the error message to Claude and it can be corrected right away.

## 8. Always-On Registration — launchd (about 5 min)

Register the bot so it starts automatically after a Mac reboot and restarts automatically if it dies.

```
cp deploy/com.jaewon.stock-alert.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jaewon.stock-alert.plist
```

Status check / logs:

```
launchctl list | grep stock-alert
tail -f logs/stdout.log
```

Stop and restart:

```
launchctl bootout gui/$(id -u)/com.jaewon.stock-alert      # stop (unregister)
launchctl kickstart -k gui/$(id -u)/com.jaewon.stock-alert  # force restart
```

## 9. Preventing Mac Sleep (about 5 min)

US regular trading hours are 22:30-05:00 Korea time (during daylight saving; 23:30-06:00 in winter).
If the Mac sleeps, the bot stops with it, so without this setup no alerts will arrive.

In this project, the launchd plist runs the bot under `caffeinate -i`. Idle sleep is blocked only while the bot is running; stop the bot and the original sleep settings take over again. No sudo required.
To verify:

```
pmset -g assertions | grep caffeinate
```

(If you see "asserting on behalf of ... python", sleep prevention is active.)

Caveats:
- Keep the power adapter connected at all times (on battery alone, macOS may still sleep).
- Closing the laptop lid puts the Mac to sleep even with caffeinate. To run overnight, leave the lid open, or use clamshell mode with an external monitor connected. The display may turn off — only the system needs to stay awake.

(If you prefer disabling system-wide sleep instead of the caffeinate approach: `sudo pmset -c sleep 0 disksleep 0`)

## 10. Troubleshooting

- `EGW00133` (token issuance failed): access-token reissuance is limited to once per minute. Wait a minute and run again. The bot caches the token in data/kis_token.json, so this normally does not occur. Beware that multiple programs sharing the same app key will conflict.
- `EGW00201` (per-second call limit exceeded): possible with a very large watch list. Increase POLL_INTERVAL_MIN or reduce the number of tickers. Also check the new-customer limit (the notice in section 1).
- `SpreadsheetNotFound` or `PERMISSION_DENIED` (gspread): almost always the missing sheet share from step 3-7. Check that the sheet is shared with the service account email as editor, and that SHEET_ID is correct.
- Kakao 401 error: the access token expired and the refresh also failed. Check that data/kakao_tokens.json exists and that the bot has not been off for 2+ months. If expired, redo steps 7-10 of section 2.
- Prices show as 0: outside market hours, or the exchange code (NAS/NYS/AMS) is wrong. Check the exchange value in the 설정 (Settings) tab.
