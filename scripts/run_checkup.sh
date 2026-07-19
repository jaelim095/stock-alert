#!/bin/bash
# 대시보드 "분석 갱신" 버튼이 호출하는 스크립트 — /checkup을 헤드리스로 재실행한다.
# 로컬 전용. 중복 실행은 lock 파일로 방지. 결과는 reports/에 새 리포트로 생성됨.
cd "$(dirname "$0")/.." || exit 1
mkdir -p data logs
LOCK=data/checkup_run.lock
STATUS=data/checkup_run.status

if [ -f "$LOCK" ]; then
  pid=$(cut -d: -f1 "$LOCK" 2>/dev/null)
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    exit 3  # 이미 실행 중
  fi
fi

TICKERS="$*"                       # 인자로 종목 지정 시 그 종목만 갱신 (예: TSLA PLTR)
PROMPT="/checkup${TICKERS:+ $TICKERS}"

echo "$$:$(date +%s)" > "$LOCK"
echo "{\"state\":\"running\",\"started_at\":\"$(date '+%Y-%m-%d %H:%M')\",\"tickers\":\"$TICKERS\"}" > "$STATUS"

# bypassPermissions: 무인 실행이라 도구 허용 프롬프트에 답할 수 없음.
# 이 저장소는 조회 전용 설계이고 스크립트는 로컬에서만 호출된다.
claude -p "$PROMPT" --permission-mode bypassPermissions > logs/checkup_run.log 2>&1
rc=$?

echo "{\"state\":\"done\",\"exit\":$rc,\"finished_at\":\"$(date '+%Y-%m-%d %H:%M')\"}" > "$STATUS"
rm -f "$LOCK"
exit $rc
