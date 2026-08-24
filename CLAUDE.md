# stock-alert — US-stock trade-logging & alert bot (personal project)

Automatically records US-stock executions from a Korea Investment & Securities
(KIS) account into Google Sheets and sends per-lot ±10% condition alerts
(KakaoTalk + email). Research 2026-07-15 → design finalized and skeleton built
07-16. This CLAUDE.md is the session-to-session handover document.

## Architecture (4 layers)

1. Machine layer (src/, the bot): auto trade logging + per-lot ±10% alerts. Deterministic, no LLM
2. Judgment-support layer (4 skills, run on request only): `/checkup` (4-lens review of
   holdings + portfolio diagnosis), `/earnings` (close-read earnings → judge thesis
   assumptions), `/dividends` (ex-dividend timeline → dashboard dividend tab),
   `/research` (deep-dive on a prospective ticker → portfolio fit → thesis draft).
   Reports go to `reports/` (git-ignored); data is injected via
   `scripts/portfolio_snapshot.py` (read-only). Shared rules: forced verdicts,
   mandatory counter-argument, no timing/price-target predictions. Fact-gathering and
   rebuttal are handled by shared subagents (`.claude/agents/`: fact-researcher =
   A/B/C source grading + dual-source verification built in, skeptic = attacks draft
   verdicts. Introduced 2026-07-25 — applied across all skills)
3. Decision layer: the human. Orders are always placed by the user, manually
4. Display layer (`dashboard/app.py`, Streamlit): local web UI over the layers above.
   Run `.venv/bin/streamlit run dashboard/app.py` (from repo root) → http://localhost:8501
   localhost-only (.streamlit/config.toml) — shows the whole account, never deploy externally

## Required reading

- `docs/02-design.md` — finalized design (sheet schema · lot state machine · KIS API usage). The implementation baseline.
- `docs/01-research.md` — prior research (KIS API TR IDs, alert channels, library comparison, with sources/reliability)
- `docs/03-setup-guide.md` — manual prep the user must do (KIS app keys, Kakao, GCP, launchd)

## Locked decisions (2026-07-16, user-confirmed)

- Scope: US stocks only
- Runtime: always-on on the user's Mac (launchd, `deploy/com.jaewon.stock-alert.plist`)
- Google Sheets is the source of truth — if the user edits the sheet directly, the bot follows
- Sell-lot matching: exact quantity match first (newest), else LIFO split
- Alert cadence: once per condition + 24h reminder while unresolved + stepped -10/-20/-30% on drops
- Channels: KakaoTalk primary, email as fallback (only when Kakao fails — `.env ALERT_EMAIL_MODE`,
  changed 2026-07-18). Kakao-token-failure warning emails are always sent

## Repository

- GitHub: https://github.com/jaelim095/stock-alert (public since 2026-08-24, default branch main)
- Commit identity is repo-local (`Jaewon <jaelim095@gmail.com>`). Global git config untouched.
- Commit messages are written in English (user directive 2026-07-20; earlier Korean commits left as-is).

## Safety rules (absolute)

- Never implement or call KIS order/amend/cancel APIs for any reason. This project is read-only.
- Never commit `.env`, `secrets/`, `data/`, `logs/`, `.omc/` (gitignored). Never put app keys or tokens in code or docs.
- Run `git status` before committing to check no secret files slipped in. Even in a private repo, a pushed key lives in history forever.
- Extra nets: a PreToolUse hook (`.claude/hooks/check-secrets.sh`) scans staged changes on git commit
  for secret patterns and banned paths and blocks the commit (2026-07-25); another hook
  (`.claude/hooks/block-order-api.sh`) blocks any Write/Edit/Bash containing order-API patterns
  (2026-08-24). If a hook blocks you, fix the cause — never bypass it.
- Verify against the paper-trading env (`KIS_ENV=vps`) before touching the real account.

## Current state (as of 2026-07-18: live in production)

- Done: design docs, setup guide, code (src/), 21 unit tests, 17 defects fixed from multi-agent review
- Done: production API verification — token/quotes/executions/balance all confirmed live.
  Buy/sell mapping confirmed empirically (01=sell, 02=buy, name field takes priority)
- Done: Google Sheet "매매 기록" connected with 4 tabs, watch tickers IRE/TSLL/METU seeded
  (at average cost), Gmail + KakaoTalk delivery verified
- Done: launchd always-on (with caffeinate sleep prevention). Verified end-to-end: a real
  execution (IRE buy) hit the sheet within the 5-minute cycle and alerts fired
- Kakao: REST key + Client Secret, talk_message consent done, data/kakao_tokens.json
  (refresh 60 days, bot auto-renews). If the bot is down for 2+ months, re-login is needed (guide §2, steps 8–11)
- Watchdog net (2026-07-30): the bot writes `data/heartbeat.json` every cycle → a launchd
  watchdog (`com.jaewon.stock-alert-watchdog`, 15 min) auto-restarts + emails after 90 min of
  silence. Daily balance-vs-lot reconciliation (`scripts/reconcile.py`, emails on violations).
  Background: the 07-20 gspread socket hang caused 6 silent days
- Ops commands & cautions: see project memory (project-status.md). Watch-ticker changes go in the sheet's 설정 tab

## About the user

- The user is a data engineer. Prefers concise explanations; respond in Korean.
- Avoid bold overuse, minimal emoji, short sentences.
