#!/bin/bash
# PreToolUse(Write|Edit|Bash) 훅: 주문 계열 KIS API의 작성·호출 시도를 차단한다.
# CLAUDE.md 최상위 안전 규칙("주문 API는 코드 자체를 만들지 않는다")의 기계적 강제.
# 걸리면 exit 2 → 도구 호출 차단. docs/·.claude/ 는 설명 문서라 검사에서 제외.

input=$(cat)
payload=$(printf '%s' "$input" | python3 -c '
import json, sys
d = json.load(sys.stdin)
ti = d.get("tool_input", {})
path = ti.get("file_path", "")
text = " ".join(str(ti.get(k, "")) for k in ("content", "new_string", "command"))
print(path)
print(text.replace("\n", " ")[:4000])' 2>/dev/null)
path=$(printf '%s' "$payload" | head -1)
text=$(printf '%s' "$payload" | tail -n +2)

case "$path" in
  *".claude/"*|*"docs/"*) exit 0 ;;  # 훅 자신·문서는 패턴 언급이 정당
esac

# 주문/정정/취소 TR ID(U 접미) 및 주문 엔드포인트 경로
PAT="trading/order|order-rvsecncl|order-resv|TTT[A-Z][0-9]{4}U|JTTT[0-9]{4}U|VTT[A-Z][0-9]{4}U|TTTC08[0-9]{2}U"
if printf '%s' "$text" | grep -qE "$PAT"; then
  {
    echo "차단: 주문 계열 API 패턴이 감지되었습니다."
    echo "이 프로젝트는 조회 전용입니다 (CLAUDE.md 안전 규칙). 주문/정정/취소 API는"
    echo "어떤 이유로도 구현·호출하지 않습니다."
  } >&2
  exit 2
fi
exit 0
