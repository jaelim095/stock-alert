#!/bin/bash
# PreToolUse(Write|Edit|Bash) hook: blocks attempts to write or call order-family KIS APIs.
# Mechanical enforcement of the top CLAUDE.md safety rule ("never even write order API code").
# On a hit, exit 2 → the tool call is blocked. docs/ and .claude/ are exempt as explanatory material.

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
  *".claude/"*|*"docs/"*) exit 0 ;;  # the hook itself and docs legitimately mention the patterns
esac

# Order/amend/cancel TR IDs (U suffix) and order endpoint paths
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
