#!/usr/bin/env bash
# Baseline (prod / old revision) benchmark: no warmup, then upload + chat timings.
# This revision uses multipart POST /ingest/{project_id}/upload (single request per file;
# GCS + chunk + embed happen in that handler). There is no GET /warmup on this API.
#
# TSV columns match testNew for spreadsheets: t_init_ms holds full multipart time;
# t_put_ms and t_complete_ms are 0 (not applicable). t_total_ms equals t_init_ms.
#
# Requires: curl, jq. truncate or dd for test files.
#
# Usage:
#   export API_BASE_URL="https://your-prod-host"   # no trailing slash
#   export API_KEY="..."                          # Bearer token
#   export PROJECT_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
#   ./testOld.sh
#
# Optional:
#   UPLOAD_SIZES        space-separated byte sizes (default: 10240 524288 2097152)
#   CHAT_REPEATS        per scenario (default: 15)
#   CHAT_DISCARD_FIRST  burn-in drops per scenario (default: 2)

set -euo pipefail

API_BASE_URL="${API_BASE_URL:-}"
API_KEY="${API_KEY:-}"
PROJECT_ID="${PROJECT_ID:-}"
UPLOAD_SIZES="${UPLOAD_SIZES:-10240 524288 2097152}"
CHAT_REPEATS="${CHAT_REPEATS:-15}"
CHAT_DISCARD_FIRST="${CHAT_DISCARD_FIRST:-2}"

die() { echo "error: $*" >&2; exit 1; }

command -v curl >/dev/null || die "curl not found"
command -v jq >/dev/null || die "jq not found"

[[ -n "$API_BASE_URL" ]] || die "set API_BASE_URL (e.g. https://api.example.com)"
[[ -n "$API_KEY" ]] || die "set API_KEY"
[[ -n "$PROJECT_ID" ]] || die "set PROJECT_ID"

BASE="${API_BASE_URL%/}"

run_id="baseline-$(date -u +%Y%m%dT%H%M%SZ)"
echo "# testOld run_id=$run_id"
echo "# revision=old (multipart upload) API_BASE_URL=$BASE PROJECT_ID=$PROJECT_ID"
echo "# no GET /warmup; first request is cold per testing.txt"
echo ""

sec_to_ms() {
  awk -v s="$1" 'BEGIN { printf "%.0f", s * 1000 }'
}

do_upload_one() {
  local size_bytes="$1"
  local name="bench_${size_bytes}.txt"
  local f
  f=$(mktemp)
  if command -v truncate >/dev/null 2>&1; then
    : >"$f"
    truncate -s "$size_bytes" "$f"
  else
    dd if=/dev/zero of="$f" bs=1 count=0 seek="$size_bytes" 2>/dev/null
  fi

  local meta http t
  meta=$(curl -sS -X POST \
    -H "Authorization: Bearer ${API_KEY}" \
    -F "file=@${f};filename=${name};type=text/plain" \
    -o /tmp/testold_upload.json -w "%{http_code}|%{time_total}" \
    "$BASE/ingest/${PROJECT_ID}/upload") || die "multipart upload failed"
  http="${meta%%|*}"
  t="${meta##*|}"
  rm -f "$f"

  [[ "$http" == "201" ]] || {
    echo "upload HTTP $http:" >&2
    cat /tmp/testold_upload.json >&2
    die "multipart upload expected 201"
  }

  local total_ms
  total_ms=$(sec_to_ms "$t")
  echo -e "upload\t${size_bytes}\t${total_ms}\t0\t0\t${total_ms}"
}

echo "# --- uploads (TSV: phase size_bytes t_init_ms t_put_ms t_complete_ms t_total_ms)"
echo "# old revision: t_init_ms = full multipart POST; put/complete columns unused (0)"
for sz in $UPLOAD_SIZES; do
  do_upload_one "$sz"
done
echo ""

chat_series() {
  local label="$1"
  local body_json="$2"
  local k
  for ((k = 1; k <= CHAT_REPEATS; k++)); do
    local chat_meta chat_http t
    chat_meta=$(curl -sS -X POST \
      -H "Authorization: Bearer ${API_KEY}" \
      -H "Content-Type: application/json" \
      -d "$body_json" \
      -o /tmp/testold_chat.json -w "%{http_code}|%{time_total}" \
      "$BASE/api/v1/chat") || die "chat failed"
    chat_http="${chat_meta%%|*}"
    t="${chat_meta##*|}"
    [[ "$chat_http" == "200" ]] || {
      echo "chat HTTP $chat_http:" >&2
      cat /tmp/testold_chat.json >&2
      die "chat expected 200"
    }
    local ms
    ms=$(sec_to_ms "$t")
    if [[ "$k" -le "$CHAT_DISCARD_FIRST" ]]; then
      echo "# chat burn-in $label #$k ${ms}ms (discarded)" >&2
      continue
    fi
    echo -e "chat\t${label}\t${k}\t${ms}"
  done
}

plain_json=$(jq -n --arg q "Reply with one word: ping." '{question:$q}')
rag_json=$(jq -n --arg q "What information is in the uploaded documents?" --arg pid "$PROJECT_ID" \
  '{question:$q, project_id:$pid}')

echo "# --- chat (TSV: phase scenario repeat_index t_ms; burn-in discarded)"
chat_series "plain" "$plain_json"
chat_series "rag" "$rag_json"

echo ""
echo "# done run_id=$run_id"
echo "# Paste TSV lines into a spreadsheet; filter lines starting with #"
