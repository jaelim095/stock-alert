# Design Document — stock-alert (US Stock Trade-Logging & Alert Bot)

Finalized 2026-07-16. This document is the canonical spec for the implementation.
If the code and this document diverge, either the document wins as-is, or the document is amended first and the code changed afterward.

## 1. Finalized Decisions

- Target market: US stocks only (NASDAQ NAS / NYSE NYS / AMEX AMS)
- Runtime: runs continuously on the user's Mac. A launchd LaunchAgent (`deploy/com.jaewon.stock-alert.plist`) starts it at boot and restarts it automatically on abnormal exit
- Data source: Korea Investment & Securities (KIS) Open API, read-only. Order/amend/cancel APIs are never used under any circumstances
- Record store: a single Google Sheets document with 4 tabs. The sheet is the sole state store (source of truth), and the user may edit it directly
- Alert channels: KakaoTalk self-message ("나에게 보내기") is the primary channel. Email is controlled by `ALERT_EMAIL_MODE` — always (always sent in parallel) / fallback (only when KakaoTalk fails) / off. Running with fallback as the default per the user's 2026-07-18 decision. The warning email sent when Kakao token refresh fails ("re-login required") goes out regardless of the mode
- Sell-to-lot matching: prefer a lot whose quantity matches exactly (most recent one if multiple) → otherwise deplete lots LIFO, splitting as needed
- Alert repetition: once per condition initially + a reminder every 24 hours while the condition remains unresolved. The downside direction is stepped at -10%/-20%/-30% (a new alert at each step)

## 2. Architecture

A single Python process. A 5-minute loop while the market is open:

1. Collect fills — query KIS overseas-stock order execution history → append new fills to the `거래내역` (trade log) tab
2. Update lots — new buy → create a BUY_LOT / new sell → match and deduct lots + create a SELL_POINT
3. Fetch quotes — get current prices for watched tickers that have active lots
4. Evaluate conditions — compute each lot's change rate → decide which alerts to send (pure logic, lot_engine)
5. Send & record — send Kakao + email → persist each lot's alert state → append to the `알림로그` (alert log) tab (a logging failure does not block state persistence — preventing duplicate sends takes priority)

State is re-read from the sheet every cycle (the user's manual edits take effect immediately). Only token caches are kept locally.

## 3. Polling Schedule

Time calculations are based on `zoneinfo("America/New_York")` (DST handled automatically).

- Regular session, ET 09:30–16:00 (KST 22:30–05:00 during DST / 23:30–06:00 standard time): full loop every 5 minutes
- Right after the close, ET 16:05–16:35: one final fill-collection pass
- Off-hours: collect fills only, every 30 minutes (to catch pre-/after-market fills). No quote evaluation
- Watching the US daytime trading session (KST 10:00–16:00) only when `ENABLE_DAY_MARKET=true` (off by default)

## 4. Google Sheets Schema

One document, 4 tabs. Headers are in Korean (for the user to read); the internal keys used in code are English.
`scripts/init_sheet.py` creates the tabs and headers automatically.

### Tab 1: 거래내역 — every fill recorded automatically (all tickers)

| Header | Internal key | Description |
|---|---|---|
| 기록시각 (recorded time) | recorded_at | Time the bot wrote the row (KST, ISO) |
| 체결일 (trade date) | trade_date | US local date, YYYY-MM-DD |
| 종목코드 (ticker) | ticker | e.g. TSLA |
| 종목명 (name) | name | Product name from the API response |
| 구분 (side) | side | 매수 (buy) / 매도 (sell) |
| 체결단가 (fill price) | price | USD |
| 체결수량 (fill quantity) | qty | |
| 체결금액 (fill amount) | amount | USD |
| 주문번호 (order number) | order_no | Key for preventing duplicate collection. Stored RAW in the sheet (leading zeros preserved); leading zeros normalized for comparison |
| 매칭lot (matched lots) | matched_lots | Depletion detail on sells. Comma-separated list of `lot_id:qty` (used for re-matching on partial fills) |
| 비고 (note) | note | |

### Tab 2: 활성감시 (active watch) — lot state (the alert engine's state store)

| Header | Internal key | Description |
|---|---|---|
| lot_id | lot_id | `{ticker}-{YYYYMMDD}-{seq}`, e.g. TSLA-20260501-1 |
| 종목코드 | ticker | |
| 유형 (kind) | kind | 매수lot (buy lot) / 매도기준점 (sell reference point) |
| 기준일 (base date) | base_date | US local date |
| 기준가 (base price) | base_price | USD |
| 수량 (quantity) | qty | For a 매수lot: remaining quantity; for a 매도기준점: sold quantity |
| 상태 (status) | status | 감시중 (watching) / 종료 (closed) |
| 현재가 (current price) | last_price | Last fetched price |
| 등락률 (change %) | change_pct | % versus the base price |
| 알림상태 (alert state) | alert_state | JSON. `{"drop_level": 1, "rise_alerted": true, "last_alert": {"drop": "<ISO>", "rise": "<ISO>"}}` |
| 종료사유 (close reason) | closed_reason | 전량매도 (fully sold) / 재매수됨 (re-bought) / 수동 (manual) |

### Tab 3: 알림로그

발송시각 (sent time) / 종목코드 / lot_id / 조건 (condition) / 기준가 / 현재가 / 등락률 / 메시지 (message) / 채널 (channel) / 결과 (result)

Condition values follow the format `추가매수-10%` (add-on buy -10%), `추가매수-20%`, `추가매수-30%`, `매도+10%` (sell +10%), `재매수-10%` (re-buy -10%), `리마인드(원조건)` (reminder, original condition).

### Tab 4: 설정 (settings) — watched tickers

| Header | Internal key | Description |
|---|---|---|
| 종목코드 | ticker | |
| 거래소 (exchange) | excd | NAS / NYS / AMS (needed for quote queries) |
| 하락임계% (drop threshold %) | drop_pct | If empty, the default applies (.env DEFAULT_DROP_PCT) |
| 상승임계% (rise threshold %) | rise_pct | If empty, the default applies |
| 감시 (watch) | enabled | Y / N |
| 메모 (memo) | memo | |

Trade logging covers all tickers; alert evaluation covers only tickers with 감시=Y.

## 5. Lot State Machine

- Buy fill → create a BUY_LOT (base price = fill price, quantity = fill quantity)
- BUY_LOT (감시중):
  - Current price ≤ base price × (1 − n × drop threshold/100) → "추가매수" alert. n = 1, 2, 3… stepped, once per step. The highest step already alerted is recorded in `alert_state.drop_level`
  - Current price ≥ base price × (1 + rise threshold/100) → one "매도" alert (`rise_alerted`)
  - If the condition holds at evaluation time and 24 hours have passed since the last alert for that condition → resend as a reminder (this includes the case where the condition briefly cleared and then re-entered — the point is to signal that the opportunity has come around again)
- Sell fill → lot matching (against that ticker's 감시중 BUY_LOTs):
  1. If a lot with an exactly matching quantity exists (the most recent one if multiple), close that lot in full
  2. Otherwise deduct starting from the most recent lot (LIFO). A lot reaching 0 is closed (전량매도); a lot with a remainder keeps being watched at its remaining quantity
  3. If the sell quantity exceeds the total of 감시중 lots, ignore the excess and record it in the trade log's 비고 column
  - At the same time, create a SELL_POINT (base price = sell price, quantity = sell quantity)
- SELL_POINT (감시중):
  - Current price ≤ base price × (1 − n × drop threshold/100) → "재매수" alert (same stepping and reminder rules)
  - A new buy fill for that ticker → close all of that ticker's 감시중 SELL_POINTs (close reason = 재매수됨)
- If the user edits a lot row directly in the sheet or flips its status to 종료, the change is honored from the next cycle onward

## 6. Alerts

### Message format (reproduces the user's example)

```
[추가매수] TSLA
5/1 매수 $100.00 × 10주 대비 -10.2% (현재 $89.80)
추가 매수 타이밍입니다.
보유 25주 · 평단 $95.20 · 평가손익 -5.6%
```

Messages are sent in Korean, verbatim as above. Roughly: "[Add-on buy] TSLA / -10.2% versus the 5/1 buy at $100.00 × 10 shares (now $89.80) / Time to consider adding. / Holding 25 shares · avg cost $95.20 · unrealized P/L -5.6%".

- [매도] / [재매수] use the same format. Re-buy is measured against the sell, e.g. "6/15 매도 $89.10 × 5주 대비 -10.1%" (-10.1% versus the 6/15 sell at $89.10 × 5 shares).
- The holdings / average cost / unrealized P/L on the last line are computed over all of that ticker's 감시중 buy lots.
- If multiple lots trigger in the same cycle, they are bundled into one message per ticker (to avoid alert storms).

### Channels

- KakaoTalk: `POST https://kapi.kakao.com/v2/api/talk/memo/default/send` (text template). Access token valid 12 hours / refresh token 60 days — check expiry before sending; if the refresh response includes a new refresh_token, replace the file at `KAKAO_TOKENS_PATH`
- Email: Gmail SMTP (app password). Sent according to `ALERT_EMAIL_MODE` — currently fallback (skipped when KakaoTalk succeeds, sent only on failure)
- Kakao token refresh failure → send a warning email with the subject "[stock-alert] 카카오 재로그인 필요" (Kakao re-login required)

## 7. KIS API Usage

- Auth: `POST /oauth2/tokenP`. Token valid for 24 hours, re-issuance limited to once per minute → cached in `data/kis_token.json`, refreshed only within 10 minutes of expiry
- Domains: production `https://openapi.koreainvestment.com:9443` / paper trading `https://openapivts.koreainvestment.com:29443` (KIS_ENV=prod/vps)
- Fill history: `GET /uapi/overseas-stock/v1/trading/inquire-ccnl` (TR: production `TTTS3035R` / paper `VTTS3035R`)
  - `ORD_STRT_DT`/`ORD_END_DT` are US local dates. To avoid date-boundary issues, always query a 2-day range of [yesterday, today] (local) and dedupe by order number
  - `OVRS_EXCG_CD=NASD` (all US markets), `SLL_BUY_DVSN=00`, `CCLD_NCCS_DVSN=01` (fills only), pagination via `CTX_AREA_FK200/NK200`
  - Duplicate prevention: two layers keyed on order number — (1) existing order numbers in the sheet's 거래내역 tab, (2) the local cache `data/processed_orders.json` (retained 14 days; prevents double application when the sheet write and the lot update partially fail). Order numbers are stored RAW in the sheet, with leading zeros normalized for comparison
  - Partial fills: if the filled quantity for an existing order number has increased, update that row's quantity and amount. For buys, adjust the lot quantity (and apply the same SELL_POINT-closing rule for that ticker); for sells, restore the previous matching from matched_lots (`lot_id:qty`) and re-match using the order's cumulative total quantity — so a split fill ends up with the same result as a single fill
- Current price: `GET /uapi/overseas-price/v1/quotations/price` (TR `HHDFS00000300`, `AUTH=""`, `EXCD` = exchange from the 설정 tab, `SYMB` = ticker). Free US quotes with 0-minute delay
- Rate limits: production caps at 20 calls per second. With a 5-minute cycle and only a few tickers there is ample headroom, but sleep 0.2 s between calls anyway
- Note: KIS notice dated 2026-03-20 on "per-second call limits for new customers" — read the notice body on the portal when issuing app keys

## 8. Code Layout

```
src/config.py        loads .env, constants
src/state_cache.py   local cache of processed orders (2nd-layer dedupe) + order-number normalization
src/kis_client.py    token caching, fill-history and current-price queries (read-only)
src/sheet_client.py  gspread wrapper (read tabs / append / update rows)
src/lot_engine.py    pure logic (no I/O): fills → lot updates, quotes → alert decisions. Unit-test target
src/notifier.py      Kakao (including automatic token refresh) + Gmail
src/main.py          scheduling loop. --once flag runs a single pass (for testing)
scripts/init_sheet.py  initializes sheet tabs/headers
tests/test_lot_engine.py  includes a reproduction of the user's example scenario (5/1–7/1)
```

## 9. Edge Cases

- Partial fills: same order number with an increased quantity → update the row/lot (section 7)
- Partial sells / LIFO splitting: matching rules in section 5
- Around (local) midnight: 2-day query range + order-number dedupe
- Pre-/after-market fills: covered by the 30-minute off-hours collection cycle
- Quote fetch failure or a zero value: skip that ticker's evaluation for the cycle (prevents false alerts)
- Transient Kakao/Sheets API errors: retry once, then carry over to the next cycle and log the error
- Trade-log append failure: orders whose lot updates already completed remain in the local cache (`data/processed_orders.json`) and are automatically re-recorded next cycle (the cache also blocks duplicate lot application)
- Sheet write safety: the 활성감시 tab is overwritten with a single update, without a clear (prevents a mid-operation failure from leaving the state store empty). Order within a cycle: lot writes → trade writes → alert sends → alert_state writes → alert log (an alert-log failure does not block alert_state persistence → preventing duplicate sends takes priority)
- Sheet connection failure at startup: retry every 60 seconds (covers no network right after boot)
- Kakao token-refresh-failure warning email: throttled to once per 6 hours
- Bot restart: all state lives in the sheet, so simply restarting resumes where it left off

## 10. Security

- Secrets live in `.env`, `secrets/`, `data/` — all gitignored
- Order-family APIs are not present in the code at all (read-only)
- The Google Sheet is shared only with the service-account email
