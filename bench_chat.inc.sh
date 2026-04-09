# Purpose: Shared POST /api/v1/chat benchmark (sourced by testOld.sh and testNew).
# Keep this file in sync with app/routers/chat.py and app/schemas/chat.py (ChatRequest).

# Before sourcing: sec_to_ms, API_KEY, BASE, CHAT_REPEATS, CHAT_DISCARD_FIRST, PROJECT_ID
# Optional: CHAT_JSON_FILE (response body temp path)

bench_chat_plain_json() {
  jq -n --arg q "Reply with one word: ping." '{question:$q}'
}

bench_chat_rag_json() {
  jq -n --arg q "What information is in the uploaded documents?" --arg pid "$PROJECT_ID" \
    '{question:$q, project_id:$pid}'
}

bench_chat_series() {
  local label="$1"
  local body_json="$2"
  local k
  local out="${CHAT_JSON_FILE:-/tmp/bench_chat_response.json}"
  for ((k = 1; k <= CHAT_REPEATS; k++)); do
    local chat_meta chat_http t ms
    if ! chat_meta=$(curl -sS -X POST \
      -H "Authorization: Bearer ${API_KEY}" \
      -H "Accept: application/json" \
      -H "Content-Type: application/json" \
      -d "$body_json" \
      -o "$out" -w "%{http_code}|%{time_total}" \
      "$BASE/api/v1/chat"); then
      echo "chat curl error ($label #$k)" >&2
      echo -e "chat\t${label}\t${k}\tFAIL"
      continue
    fi
    chat_http="${chat_meta%%|*}"
    t="${chat_meta##*|}"
    if [[ "$chat_http" != "200" ]]; then
      echo "chat HTTP $chat_http ($label #$k):" >&2
      cat "$out" >&2
      echo -e "chat\t${label}\t${k}\tFAIL"
      continue
    fi
    ms=$(sec_to_ms "$t")
    if [[ "$k" -le "$CHAT_DISCARD_FIRST" ]]; then
      echo "# chat burn-in $label #$k ${ms}ms (discarded)" >&2
      continue
    fi
    echo -e "chat\t${label}\t${k}\t${ms}"
  done
}

bench_chat_run() {
  local plain_json rag_json
  plain_json=$(bench_chat_plain_json)
  rag_json=$(bench_chat_rag_json)
  echo "# --- chat (TSV: phase scenario repeat_index t_ms; burn-in to stderr)"
  bench_chat_series "plain" "$plain_json"
  bench_chat_series "rag" "$rag_json"
}
