# Laptop Migration Checklist

What to carry over when replacing the Mac this bot runs on.
Everything not listed here either lives in the cloud (Google Sheets)
or regenerates itself.

## 1. Files to copy (never in git)

| Path | What it is |
|---|---|
| `.env` | all keys and settings |
| `secrets/service_account.json` | Google service account |
| `data/kakao_tokens.json` | Kakao refresh token — copying it avoids the OAuth re-login dance (guide §2 steps 8–11) |

Everything else under `data/` (kis_token.json, processed_orders.json,
heartbeat.json, marker files) regenerates on first run. `reports/` is
optional history — copy if you want the dashboard verdicts preserved.

## 2. Reinstall on the new machine

```
git clone https://github.com/jaelim095/stock-alert.git && cd stock-alert
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# restore the three files above, then:
cp deploy/com.jaewon.stock-alert.plist ~/Library/LaunchAgents/
cp deploy/com.jaewon.stock-alert-watchdog.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jaewon.stock-alert.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jaewon.stock-alert-watchdog.plist
```

Note: the plists hardcode `/Users/jaewon/stock-alert` — edit the paths
if the username or location changes.

## 3. Verify

1. `.venv/bin/python -m src.main --once` — one full cycle, check the sheet updates
2. `.venv/bin/python scripts/watchdog.py --dry-run` — heartbeat detection works
3. `.venv/bin/python scripts/reconcile.py` — balance vs lots consistent
4. `.venv/bin/streamlit run dashboard/app.py` — dashboard up on localhost:8501,
   bot liveness badge green
5. Old machine: `launchctl bootout gui/$(id -u)/com.jaewon.stock-alert` (and the
   watchdog) so two bots never run against one sheet
