#!/usr/bin/env bash
# Multipart upload + optional chat timings (POST /ingest/{project_id}/upload → 201).
#
# FastAPI Query() reads chunk_* from the URL only — we omit ?chunk_size= by default (see USE_QUERY_PARAMS).
#
# Upload tests:
#   Default: for each size in UPLOAD_SIZES, build a temp .txt of that many bytes using
#   repetitive text (yes | head -c) so extract/chunk/embed sees real text, not NUL padding.
#   Optional: UPLOAD_SINGLE_FILE=/path/to/foo.txt — skip generated sizes; upload that file once
#   (or UPLOAD_REPEAT times).
#
# Required: API_BASE_URL  API_KEY  PROJECT_ID
# Optional: UPLOAD_SIZES  UPLOAD_SINGLE_FILE  UPLOAD_REPEAT  USE_QUERY_PARAMS  SKIP_CHAT  CHAT_*
# Upload/chat errors log to stderr and the script continues (no exit on failed request).
# Chat: bench_chat.inc.sh must sit next to this script (shared with testNew; POST body matches ChatRequest).

set -euo pipefail

API_BASE_URL="${API_BASE_URL:-}"
API_KEY="${API_KEY:-}"
PROJECT_ID="${PROJECT_ID:-}"
UPLOAD_SIZES="${UPLOAD_SIZES:-10240 524288 2097152}"
UPLOAD_SINGLE_FILE="${UPLOAD_SINGLE_FILE:-}"
CHUNK_SIZE="${CHUNK_SIZE:-1000}"
CHUNK_OVERLAP="${CHUNK_OVERLAP:-100}"
USE_QUERY_PARAMS="${USE_QUERY_PARAMS:-0}"
UPLOAD_REPEAT="${UPLOAD_REPEAT:-1}"
SKIP_CHAT="${SKIP_CHAT:-0}"
CHAT_REPEATS="${CHAT_REPEATS:-15}"
CHAT_DISCARD_FIRST="${CHAT_DISCARD_FIRST:-2}"

die() { echo "error: $*" >&2; exit 1; }

command -v curl >/dev/null || die "curl not found"
command -v jq >/dev/null || die "jq not found"

[[ -n "$API_BASE_URL" ]] || die "set API_BASE_URL (e.g. http://10.0.1.5)"
[[ -n "$API_KEY" ]] || die "set API_KEY"
[[ -n "$PROJECT_ID" ]] || die "set PROJECT_ID"

if [[ -n "$UPLOAD_SINGLE_FILE" ]]; then
  [[ -f "$UPLOAD_SINGLE_FILE" ]] || die "UPLOAD_SINGLE_FILE not found: $UPLOAD_SINGLE_FILE"
fi

BASE="${API_BASE_URL%/}"
if [[ "$USE_QUERY_PARAMS" == "1" ]]; then
  UPLOAD_URL="${BASE}/ingest/${PROJECT_ID}/upload?chunk_size=${CHUNK_SIZE}&chunk_overlap=${CHUNK_OVERLAP}"
else
  UPLOAD_URL="${BASE}/ingest/${PROJECT_ID}/upload"
fi

run_id="baseline-$(date -u +%Y%m%dT%H%M%SZ)"
echo "# testOld run_id=$run_id"
echo "# API_BASE_URL=$BASE PROJECT_ID=$PROJECT_ID USE_QUERY_PARAMS=$USE_QUERY_PARAMS"
if [[ -n "$UPLOAD_SINGLE_FILE" ]]; then
  echo "# upload mode: single file $UPLOAD_SINGLE_FILE x${UPLOAD_REPEAT}"
else
  echo "# upload mode: generated text files UPLOAD_SIZES=$UPLOAD_SIZES"
fi
echo ""

sec_to_ms() {
  awk -v s="$1" 'BEGIN { printf "%.0f", s * 1000 }'
}

# Repetitive lines from yes(1) — valid UTF-8 text for extract_text; not NUL-filled.
# With pipefail, yes exits 141 (SIGPIPE) after head finishes; that non-zero would trip set -e.
write_generated_txt() {
  local path="$1" size="$2"
  local actual
  [[ "$size" =~ ^[0-9]+$ ]] && (( size >= 1 )) || die "UPLOAD_SIZES must be positive integers"
  yes | head -c "$size" >"$path" || true
  actual=$(wc -c <"$path")
  [[ "$actual" -eq "$size" ]] || die "generated file size mismatch: expected $size bytes, got $actual"
}

do_upload() {
  local path="$1"
  local form_filename="$2"
  local label="$3"
  local meta http t total_ms
  if ! meta=$(curl -sS -X POST \
    -H "Authorization: Bearer ${API_KEY}" \
    -F "file=@${path};filename=${form_filename}" \
    -F "chunk_size=${CHUNK_SIZE}" \
    -F "chunk_overlap=${CHUNK_OVERLAP}" \
    -o /tmp/testold_upload.json -w "%{http_code}|%{time_total}" \
    "$UPLOAD_URL"); then
    echo "upload curl error ($label)" >&2
    echo -e "upload\t${label}\tFAIL\tcurl\t-\t-"
    return 1
  fi
  http="${meta%%|*}"
  t="${meta##*|}"

  if [[ "$http" != "201" ]]; then
    echo "upload HTTP $http ($label):" >&2
    cat /tmp/testold_upload.json >&2
    echo -e "upload\t${label}\tFAIL\t${http}\t-\t-"
    return 1
  fi

  total_ms=$(sec_to_ms "$t")
  echo -e "upload\t${label}\t${total_ms}\t0\t0\t${total_ms}"
  return 0
}

echo "# --- uploads (TSV: success: t_* ms; FAIL rows: t_init_ms=FAIL, t_put_ms=http or curl)"
if [[ -n "$UPLOAD_SINGLE_FILE" ]]; then
  for ((i = 1; i <= UPLOAD_REPEAT; i++)); do
    do_upload "$UPLOAD_SINGLE_FILE" "$(basename "$UPLOAD_SINGLE_FILE")" "single:${i}" || true
  done
else
  for sz in $UPLOAD_SIZES; do
    f=$(mktemp)
    write_generated_txt "$f" "$sz"
    do_upload "$f" "bench_${sz}.txt" "${sz}" || true
    rm -f "$f"
  done
fi
echo ""

if [[ "$SKIP_CHAT" == "1" ]]; then
  echo "# SKIP_CHAT=1 — done run_id=$run_id"
  exit 0
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$SCRIPT_DIR/bench_chat.inc.sh" ]] || die "missing bench_chat.inc.sh next to this script"
# shellcheck source=bench_chat.inc.sh
source "$SCRIPT_DIR/bench_chat.inc.sh"
export CHAT_JSON_FILE=/tmp/testold_chat.json
bench_chat_run

echo ""
echo "# done run_id=$run_id"
