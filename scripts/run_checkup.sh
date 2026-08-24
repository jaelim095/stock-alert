#!/bin/bash
# Script invoked by the dashboard's "분석 갱신" button — reruns /checkup headless.
# Local only. Duplicate runs are prevented via a lock file. Output lands in reports/ as a new report.
cd "$(dirname "$0")/.." || exit 1
mkdir -p data logs
LOCK=data/checkup_run.lock
STATUS=data/checkup_run.status

if [ -f "$LOCK" ]; then
  pid=$(cut -d: -f1 "$LOCK" 2>/dev/null)
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    exit 3  # already running
  fi
fi

TICKERS="$*"                       # if tickers are passed as arguments, refresh only those (e.g. TSLA PLTR)
PROMPT="/checkup${TICKERS:+ $TICKERS}"

echo "$$:$(date +%s)" > "$LOCK"
echo "{\"state\":\"running\",\"started_at\":\"$(date '+%Y-%m-%d %H:%M')\",\"tickers\":\"$TICKERS\"}" > "$STATUS"

# bypassPermissions: unattended run, so nobody can answer tool permission prompts.
# This repo is read-only by design and the script is only invoked locally.
claude -p "$PROMPT" --permission-mode bypassPermissions > logs/checkup_run.log 2>&1
rc=$?

echo "{\"state\":\"done\",\"exit\":$rc,\"finished_at\":\"$(date '+%Y-%m-%d %H:%M')\"}" > "$STATUS"
rm -f "$LOCK"
exit $rc
