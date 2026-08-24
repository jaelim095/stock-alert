# Research Findings — Korea Investment & Securities (KIS) Open API · Notification Channels · Open Source

Research date: 2026-07-15.
Method: three parallel web research tracks (KIS Open API / notification channels / open source & prior art). Official documentation and official GitHub repositories were given priority; blog and community sources are marked with lower confidence.
Confidence labels: confirmed (verified against official docs/repos) / likely (corroborated by multiple community/blog sources) / uncertain (conflicting or unverified).

Note: the project was later scoped to "US stocks only" (2026-07-16, `docs/02-design.md`).
This document is a research record, so the domestic (Korean) stock findings are preserved as-is. Reference them if we ever expand to domestic stocks.

---

## 1. KIS Open API (KIS Developers)

The primary evidence is the sample code in the official GitHub repository (koreainvestment/open-trading-api), maintained by the company itself (examples_llm folder).
The portal (apiportal.koreainvestment.com) is an SPA and resists crawling, so some figures were supplemented with community sources.

### 1.1 Core read-only APIs (all REST GET)

Domestic (Korean) stocks:

| Purpose | API name | Endpoint | TR ID (prod/paper) |
|---|---|---|---|
| Order/execution history by period | Daily stock order & execution inquiry [v1_국내주식-005] | `/uapi/domestic-stock/v1/trading/inquire-daily-ccld` | within 3 months `TTTC0081R`/`VTTC0081R`, older than 3 months `CTSC9215R`/`VTSC9215R` |
| Balance | Stock balance inquiry [v1_국내주식-006] | `/uapi/domestic-stock/v1/trading/inquire-balance` | `TTTC8434R`/`VTTC8434R` |
| Current price | Stock current price quote [v1_국내주식-008] | `/uapi/domestic-stock/v1/quotations/inquire-price` | `FHKST01010100` (shared by prod and paper) |

Domestic notes:

- Older docs and blogs list the daily order/execution TR as `TTTC8001R`/`CTSC9115R`, but the current official GitHub samples use `TTTC0081R`/`CTSC9215R`. This looks like a transition period with both in circulation, so verify against the latest portal docs when implementing. (likely, https://wikidocs.net/239689)
- The daily order/execution inquiry supports period queries including today (start date = end date = today). Production: up to 100 records per call plus continued-query pagination (CTX_AREA_FK100/NK100); paper trading: up to 15 records per call. (confirmed)
- The TR for records older than 3 months has an intraday DB lag issue; the official comment recommends querying "after market close (15:30), over short date ranges". (confirmed)
- Balance inquiry returns up to 50 records per call in production / 20 in paper trading, with continued queries. Parameters exist to distinguish KRX / NXT (alternative exchange) / SOR. (confirmed)

Overseas stocks (US):

| Purpose | API name | Endpoint | TR ID (prod/paper) |
|---|---|---|---|
| Order/execution history | Overseas stock order & execution history [v1_해외주식-007] | `/uapi/overseas-stock/v1/trading/inquire-ccnl` | `TTTS3035R`/`VTTS3035R` |
| Open (unfilled) orders | Overseas stock open orders | `/uapi/overseas-stock/v1/trading/inquire-nccs` | `TTTS3018R` (for reference) |
| Balance | Overseas stock balance [v1_해외주식-006] | `/uapi/overseas-stock/v1/trading/inquire-balance` | `TTTS3012R`/`VTTS3012R` |
| Current price | Overseas stock current execution price [v1_해외주식-009] | `/uapi/overseas-price/v1/quotations/price` | `HHDFS00000300` (shared) |
| Price detail | Overseas stock price detail [v1_해외주식-029] | `/uapi/overseas-price/v1/quotations/price-detail` | `HHDFS76200200` |

Overseas notes:

- The execution-history parameters `ORD_STRT_DT`/`ORD_END_DT` are YYYYMMDD in US local time (stated in the official sample docstring). Exchange code `NASD` = all US markets (NASDAQ + NYSE + AMEX). Supports period queries plus continued queries (FK200/NK200). (confirmed, https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/overseas_stock/inquire_ccnl/inquire_ccnl.py)
- Paper-account constraints: overseas execution history can only be queried for all symbols / all types (`PDNO=""`, `SLL_BUY_DVSN="00"`, `CCLD_NCCS_DVSN="00"`), and sort order cannot be specified. (confirmed)

### 1.2 Real-time vs delayed US quotes

- Official sample comment (updated 2024-11-29): US quotes are free and real-time (0-minute delay); Hong Kong, Vietnam, China, and Japan are delayed 15 minutes. (confirmed, https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/overseas_stock/delayed_ccnl/delayed_ccnl.py)
- However, an official comment notes that the free US feed is aggregated from the NASDAQ market center, so the intraday session open can differ and is shown corrected the next day. If consolidated (SIP) exchange quotes are needed, paid real-time quotes can be requested via the HTS [7781] quote subscription menu and then received over the API. (confirmed)
- Quotes for the US daytime session (10:00-16:00 KST) are available under separate market codes (NASDAQ BAQ, NYSE BAY, AMEX BAA). (confirmed)

### 1.3 Real-time execution-notice WebSocket

- Existence confirmed (official sample code): domestic `H0STCNI0` (prod) / `H0STCNI9` (paper), overseas `H0GSCNI0` (prod) / `H0GSCNI9` (paper). Available to individuals (custtype=P). (confirmed, https://github.com/koreainvestment/open-trading-api/blob/main/legacy/websocket/python/ws_domestic%2Boverseas_stock.py)
- The registration key (tr_key) is the HTS ID (customer ID), not a ticker symbol. Execution-notice payloads arrive AES256-encrypted, so decryption (key/iv) must be implemented. (confirmed)
- Connection URLs: production `ws://ops.koreainvestment.com:21000`, paper `:31000`. A separate WebSocket approval key must be issued (`/oauth2/Approval`). (confirmed)
- Notices include order/amend/cancel/reject acceptance notices as well as execution notices (CNTG_YN field: 2 = execution, 1 = acceptance). (confirmed)
- The per-session real-time registration limit is reportedly 41 entries. (likely, https://hky035.github.io/web/refact-kis-websocket/)
- Verdict: for collecting your own account's trade history plus price monitoring, REST polling is the practical choice. WebSocket carries a heavy operational burden — keeping the connection alive, reconnection, AES decryption, session limits. Only worth adding if instant execution notice becomes a hard requirement.

### 1.4 Access-token policy and rate limits

- The access token (`/oauth2/tokenP`) is valid for 24 hours (1 day). Per the official kis_auth.py comments: re-requesting within 6 hours returns the same token value, and issuance triggers a KakaoTalk notification message. Caching the token to a file and reusing it is the officially recommended pattern. (confirmed, https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/kis_auth.py)
- Issuance frequency limit: once per minute (error `EGW00133` when exceeded). (likely, https://velog.io/@seon7129/JAVA-한국투자증권-OpenAPI-사용-정리-Rest)
- REST call volume: 20 calls per second in production (error `EGW00201` when exceeded). (likely, https://hky035.github.io/web/kis-api-throttling/)
- Paper-trading call limit: commonly reported as 2 calls/second, but some sources say 5 — conflicting. Re-check the portal FAQ. (uncertain, https://tgparkk.github.io/robotrader/2025/10/09/robotrader-1-70stocks-problem.html)
- Important: the portal posted a notice titled "[중요] 한국투자증권 Open API 신규 고객 초당 호출 제한 안내" ([Important] Notice on per-second call limits for new Open API customers) on 2026-03-20. Newer signups may be subject to lower limits. The notice body could not be accessed at research time — be sure to read it on the portal before applying. (likely, https://apiportal.koreainvestment.com/intro)

### 1.5 Paper trading

- Officially supported. Assumes switching between production (`prod`) and paper (`vps`) environments, with a separate app key/secret issued for paper trading. Most read APIs have paper TR IDs (V-prefix). (confirmed, https://github.com/koreainvestment/open-trading-api/blob/main/README.md)
- Paper trading also requires opening a KIS account and enrolling in the paper-trading service before app keys can be issued (impossible with no real account at all). The paper environment has record-count and parameter constraints. The portal has a testbed menu. (confirmed)

### 1.6 Application process and cost

1. Open a KIS brokerage account (possible remotely via the app) and register a website/app ID
2. Apply for the Open API service on the website or app (path: Trading > Open API > KIS Developers)
3. Get an App Key / App Secret issued — for production
4. For paper trading, enroll in paper trading and get a separate paper app key/secret

- Cost: the service itself is free. Only paid overseas real-time quotes can incur charges, if requested. (likely, https://apiportal.koreainvestment.com/about-howto)

### 1.7 Caveats when querying US execution history

- Date basis: query parameters use US local time. An execution in the early KST morning (e.g., the small hours of 7/15 KST) must be queried under the local date (7/14). Running a "today's executions" batch on the Korean date shifts everything by a day. A safe design is a morning batch that queries the previous (local) date after the US regular session closes (05:00/06:00 KST). (confirmed)
- Daytime session: a separate US daytime ("day market") session exists from 10:00 to 16:00 KST. How daytime-session executions appear in the execution-history API (whether they are merged into the same TR) could not be confirmed from official docs. Measure empirically if you use it. (uncertain)
- Pre/after market: KIS supports orders outside US regular hours, so those executions should naturally appear in the account execution history, but no explicit official statement was found. (uncertain)
- Open-price correction: on the free feed, today's open may be corrected the next day (official comment). Keep this in mind when cross-checking execution prices against quotes. (confirmed)
- For overseas balances, besides `inquire-balance` there are also a settlement-basis balance (`inquire_paymt_stdr_balance`) and an execution-basis present balance (`inquire_present_balance`); figures can differ due to settlement timing (T+1). (confirmed)

### 1.8 Key sources

- https://github.com/koreainvestment/open-trading-api — examples_llm/domestic_stock/{inquire_daily_ccld, inquire_balance, inquire_price, ccnl_notice}, examples_llm/overseas_stock/{inquire_ccnl, inquire_balance, price, price_detail, ccnl_notice, delayed_ccnl}, examples_llm/kis_auth.py, legacy/websocket/python/ws_domestic+overseas_stock.py

---

## 2. Notification channel comparison (sending "to myself")

### 2.1 KakaoTalk "send to me"

Feasibility / review:

- API: `POST https://kapi.kakao.com/v2/api/talk/memo/default/send` (default template). Possible with a personal developer app. (confirmed, https://developers.kakao.com/docs/ko/kakaotalk-message/rest-api)
- "Send to me" requires no separate permission (review) application. Prerequisites: (1) create an app in Kakao Developers, (2) enable Kakao Login, (3) enable the `talk_message` consent scope, (4) log in once via OAuth with your own account (browser authorization code) and obtain tokens. (confirmed)
- Quota: 30,000 KakaoTalk messages per day per app, 100 per day per sender. Ample for personal stock alerts. (confirmed, https://developers.kakao.com/docs/ko/getting-started/quota)

Token lifetime / unattended operation:

- Access token lasts about 12 hours (official example `expires_in: 43199` seconds), refresh token about 2 months (60 days, `refresh_token_expires_in: 5184000` seconds). (confirmed, https://developers.kakao.com/docs/ko/kakaologin/rest-api)
- Renewal: `POST /oauth/token` with `grant_type=refresh_token`. A new refresh token is included in the response only when the current one has less than 1 month remaining — when a new one arrives, the stored value must be replaced. (confirmed)
- If the script runs at least monthly and implements renewal logic (including persisting new refresh tokens), it can run indefinitely without re-login. But if the script is down for 2+ months, the refresh token expires and a manual browser re-login is required. Not "fully unattended" — more like "effectively unattended if you manage the token file well". (likely, https://devtalk.kakao.com/t/rest-api/136443)

Why "send to friends" is impractical:

- (1) separate permission review plus conversion to a business app (requires business registration info), (2) each recipient friend must also log into the same app with Kakao Login and consent to sharing their friend list, (3) max 5 recipients per call and a 20 messages/day quota per sender-recipient pair. Effectively unrealistic for a personal project. (confirmed, https://developers.kakao.com/docs/ko/kakaotalk-message/common)

### 2.2 Telegram bot

- `/newbot` to @BotFather → token issued instantly (no review, no account registration). Sending is a single HTTP line: `https://api.telegram.org/bot<TOKEN>/sendMessage?chat_id=<ID>&text=...`
- Token valid indefinitely (never expires), completely free. Roughly 1 message/second limit per chat — irrelevant for personal alerts. (confirmed, https://core.telegram.org/bots/faq)
- Entry barrier: install the Telegram app and message the bot once to obtain a chat_id.

### 2.3 Email (Gmail SMTP app password)

- Enable 2-step verification on the Google account → issue a 16-character app password → send via `smtplib`. About 10 minutes of setup, free. (confirmed, https://support.google.com/mail/answer/185833?hl=ko)
- App passwords never expire (invalidated on account password change or security events). Low unattended-operation burden.
- Downsides: immediacy depends on the mail app's push settings; spam-folder risk. Community reports say issuance can be awkward on passkey-only accounts.

### 2.4 SMS — paid

- Aligo: SMS 8.4 KRW per message, LMS 25 KRW, MMS 60 KRW (prepaid). (confirmed, https://smartsms.aligo.in/smsapi.html)
- Solapi: SMS from 13 KRW per message, LMS 29 KRW (no monthly fee, free API; volume discounts up to about 58%).
- Shared burdens: sender-number pre-registration (identity verification), balance top-ups. At 10 messages/day, roughly 2,500-4,000 KRW per month. No advantage over free channels for personal alerts.

### 2.5 Others

- Discord webhook: create a webhook URL in channel settings → send with a single POST. No auth, free, no expiry. (confirmed, https://discord.com/developers/docs/resources/webhook)
- Slack incoming webhook: possible with a free workspace, but you would need a dedicated personal workspace (personal stock alerts on a company Slack are not recommended), and the free plan limits message retention.
- ntfy.sh: push to your phone with one line — `curl -d "message" ntfy.sh/mytopic` — no account or API key. Requires the app. It is a public instance, so the topic name must be a hard-to-guess random string. Free, open source, self-hostable. (confirmed, https://docs.ntfy.sh/)

### 2.6 Recommended ranking (least unattended-maintenance burden first)

1. Telegram bot — no token expiry, free, three lines of code. Essentially zero maintenance
2. ntfy — no account needed at all. Predicated on public-topic security and installing the app
3. Discord webhook — one non-expiring URL. On par with #1 if you already use Discord
4. Email (Gmail app password) — no expiry, easy setup. Only immediacy is lacking
5. KakaoTalk send-to-me — free with no review, but token-renewal logic plus token-file management are mandatory, and a 2-month gap forces a manual re-login
6. SMS (Aligo/Solapi) — paid plus sender registration. Not recommended

(The ranking itself is the research agent's overall judgment, uncertain)

Practical suggestion: make KakaoTalk the main channel with logic that renews and persists the refresh token, and on renewal failure send a "Kakao re-login required" warning over a fallback channel — a dual-channel structure. If you want minimum maintenance from the start, use Telegram alone.

→ Final project decision (02-design.md): Kakao as the main channel with Gmail always running alongside, plus an email warning when Kakao fails.

---

## 3. Open-source libraries and prior art

### 3.1 Python library comparison (measured on GitHub, as of 2026-07-15)

| Item | mojito (sharebook-kr) | python-kis / PyKis (Soju06) | korea-investment-stock (kenshin579) |
|---|---|---|---|
| Install | `pip install mojito2` (v0.1.6) | `pip install python-kis` (v2.1.6) | `pip install korea-investment-stock` (v0.19.0, discontinued) |
| Stars | 91 | 283 | few (started as a mojito fork) |
| Last commit | 2024-02-20 | release v2.1.6 (2025-10-13), repo push 2026-02-21 | only the Go version is active (v1.28.0, 2026-06-13) |
| Last PyPI upload | 2023-02-23 | 2025-10 | Python ended at v0.19.0 |
| US stock quotes | Yes (`fetch_oversea_price`) | Yes (`kis.stock("NVDA").quote()`) | Yes (Go version, quotes only) |
| US stock balance | Yes (`fetch_balance_oversea`, `fetch_present_balance`) | Yes (`account.balance()`, unified domestic/overseas) | No (out of scope) |
| US execution history | No — TTTS3035R not implemented (verified by grepping the entire source) | Yes — `account.daily_orders()` calls TTTS3035R/VTTS3035R | No (out of scope) |
| Docs | wikidocs book (https://wikidocs.net/book/7845), thin on overseas details | detailed GitHub Wiki, full typing on every function | detailed README, but for Go |
| Requirements | few constraints | Python >= 3.10 | - |
| License | MIT | MIT | - |

Key judgments:

- korea-investment-stock switched from Python to Go as of 2026-05-03. Python is preserved at the `python-final` tag, security fixes only. Unsuitable for new Python projects. (confirmed, https://github.com/kenshin579/korea-investment-stock)
- pjueon/pykis (a separate project — beware the name collision) has had no commits since 2022-09. Effectively abandoned.
- mojito is unmaintained and lacks overseas execution-history inquiry, so it falls short of this project's requirements. (confirmed, https://github.com/sharebook-kr/mojito)
- If using a library, python-kis is the only realistic option: overseas execution history, balance, and quotes are all covered, and it is the best maintained. That said, the latest release is 9 months old, so it is not hyper-active. (confirmed, https://github.com/Soju06/python-kis/blob/main/pykis/api/account/daily_order.py)
- The official koreainvestment/open-trading-api (1,519 stars) is a collection of examples rather than a library, but it is the most active by far (commits as recent as 2026-07-09). It provides kis_auth.py (a shared token-management module), examples_llm (one API = one file, LLM-friendly), and an MCP directory. The best reference source when developing with Claude. (confirmed, https://github.com/koreainvestment/open-trading-api)

### 3.2 Direct requests calls vs a library

What you must handle yourself with direct calls (libraries have these built in):

- Token caching (24-hour validity, reissue limited to once per minute → file caching is a must; the official kis_auth.py implements this pattern)
- Rate limiting (EGW00201), hashkey for order POSTs (not applicable — this project is read-only), continued-query pagination, exchange-code/TR-ID mapping, response parsing

Advantages of direct calls: zero dependencies, official examples can be copy-pasted (the first source to get updated), no abandoned-library risk. A read-only bot needs only 3-5 APIs, so the code stays small.
Advantages of a library (python-kis): token/rate-limit/parsing built in, identical interface for domestic and overseas, typed autocompletion, WebSocket auto-reconnect. Downsides: the abstraction makes debugging harder, and you wait for updates when the API changes.

Recommendation: for a small read-focused bot, either is fine. The official examples_llm plus direct requests calls gives the most control.
→ Final project decision: direct requests calls (`src/kis_client.py`).

### 3.3 Google Sheets logging: gspread + service account

- gspread is the de facto standard for Google Sheets in Python. For bot automation, a service account is the standard approach (user OAuth requires browser consent → unfit for unattended use). (confirmed, https://github.com/burnash/gspread)
- Procedure (15-30 min): create a GCP project → enable the Sheets API (+ Drive API) → create a service account → download the JSON key → share the sheet with the service account email (xxx@yyy.iam.gserviceaccount.com) → `gspread.service_account(filename="key.json")`. Forgetting to share the sheet is the most common mistake.
- Caveat: the gspread repo carries a notice about lacking maintainers, and the latest release is v6.2.1 (2025-05). Functionally stable, so no problem in practice. The alternative is the official google-api-python-client (more verbose).

### 3.4 Similar personal projects

1. geongi-im/kis-us-auto-trading (https://github.com/geongi-im/kis-us-auto-trading) — a US-stock auto-trading bot on the KIS API. Direct requests wrappers (kis_base/kis_order/kis_account/kis_price.py) plus websockets. Runs as a single always-on process, 1-minute polling by default, auto-shutdown at 16:30 US time. Telegram alerts for market open/close, executions, stop-losses, and errors. (confirmed)
2. tofulim/auto_trade (https://github.com/tofulim/auto_trade) — dollar-cost-averaging (split-buy) auto trading. FastAPI + Airflow, run on an EC2 t2.micro. Slack alerts plus an "actual trade at least 12 hours after the alert" rule to prevent mis-trades. Direct API calls. (confirmed)
3. Malchooni's blog, trader-malchooni (https://malchooni.name/entry/한국투자증권-텔레그램-API-활용-잔고-조회) — KIS API + Telegram balance alerts. Calls the balance TR directly after each market close and sends to Telegram. Lightweight once-a-day batch. (likely)
4. TG's RoboTrader blog (https://tgparkk.github.io/robotrader/2025/10/09/robotrader-1-70stocks-problem.html) — a case where polling 70 symbols failed against the 20 calls/second limit; solved by computing batch sizes and delays dynamically (asyncio). Shows the need for rate management when polling many symbols. (operational reference)

- No well-known public project literally named "물타기 알림" (averaging-down alert) was found. No complete public repo for "KIS execution history → gspread trade journal" was found either, but every component is commonplace, so assembly difficulty is low. (uncertain)

---

## 4. Overall assessment

- Entirely feasible as a read-only (no ordering) personal project. With a real account and free app keys, all domestic/overseas execution-history, balance, and quote REST queries become available, and US quotes are free with 0-minute delay.
- The KakaoTalk message-parsing approach is ruled out: there is no official API for reading messages received on a personal KakaoTalk account, and it is device-dependent and fragile to wording changes.
- REST polling is the practical architecture. Add the WebSocket execution notice only if a real-time requirement emerges.
- Implementation: reference the official examples_llm and call requests directly (or use python-kis). Sheets via gspread + service account.
- Alerts: KakaoTalk send-to-me (main) with a fallback channel for redundancy.
- Must verify before starting: the body of the 2026-03-20 notice on per-second call limits for new customers, the exact paper-trading per-second limit, and — if using the daytime session — how those executions land in the execution history (empirical check).
