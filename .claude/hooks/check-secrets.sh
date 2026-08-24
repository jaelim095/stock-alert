#!/bin/bash
# PreToolUse(Bash) hook: on git commit, scans the staged changes for secret patterns.
# On a hit, exit 2 → the commit command itself is blocked and the stderr message is passed to Claude.

input=$(cat)
cmd=$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)

case "$cmd" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" || exit 0

# 1) Check whether any banned paths are staged (blocks once more even if .gitignore is bypassed)
banned=$(git diff --cached --name-only | grep -E '^\.env$|^secrets/|^data/|^logs/|^reports/|kis_token|kakao_tokens' || true)
if [ -n "$banned" ]; then
  {
    echo "커밋 차단: 비밀 경로가 스테이징되어 있습니다."
    echo "$banned"
    echo "git restore --staged <파일> 로 내린 뒤 다시 커밋하세요."
  } >&2
  exit 2
fi

# 2) Scan newly added lines for secret patterns (key name=value, private key blocks, JWT, literal app keys)
PAT="-----BEGIN[A-Z ]*PRIVATE KEY-----|(KIS_APP_KEY|KIS_APP_SECRET|KAKAO_REST_API_KEY|KAKAO_CLIENT_SECRET|GMAIL_APP_PASSWORD|SHEET_ID)=[A-Za-z0-9+/_-]{8,}|eyJ[A-Za-z0-9_-]{30,}\.[A-Za-z0-9_.-]{10,}|(appkey|appsecret)[\"': ]{1,4}[A-Za-z0-9+/=]{25,}"
hits=$(git diff --cached -U0 | grep -E '^\+' | grep -vE '^\+\+\+' | grep -nE -e "$PAT" || true)
if [ -n "$hits" ]; then
  {
    echo "커밋 차단: 비밀로 보이는 패턴이 diff에 포함되어 있습니다."
    echo "$hits" | head -5
    echo "실제 키라면 스테이징에서 내리세요. 오탐이면 사용자에게 확인받은 뒤 진행하세요."
  } >&2
  exit 2
fi

exit 0
