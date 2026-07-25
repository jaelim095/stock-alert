#!/bin/bash
# PreToolUse(Bash) 훅: git commit 시 스테이징된 변경에서 비밀 패턴을 검사한다.
# 걸리면 exit 2 → 커밋 명령 자체가 차단되고 stderr 메시지가 클로드에게 전달된다.

input=$(cat)
cmd=$(printf '%s' "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' 2>/dev/null)

case "$cmd" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" || exit 0

# 1) 커밋 금지 경로가 스테이징됐는지 (.gitignore가 뚫려도 여기서 한 번 더 막는다)
banned=$(git diff --cached --name-only | grep -E '^\.env$|^secrets/|^data/|^logs/|^reports/|kis_token|kakao_tokens' || true)
if [ -n "$banned" ]; then
  {
    echo "커밋 차단: 비밀 경로가 스테이징되어 있습니다."
    echo "$banned"
    echo "git restore --staged <파일> 로 내린 뒤 다시 커밋하세요."
  } >&2
  exit 2
fi

# 2) 새로 추가되는 라인에서 비밀 패턴 검사 (키 이름=값, 개인키 블록, JWT, 리터럴 앱키)
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
