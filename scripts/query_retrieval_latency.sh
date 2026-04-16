#!/usr/bin/env bash
# Purpose: Run POST /query/{project_id} latency bench (retrieval only; no LLM chat).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec uv run python -m bench.query_retrieval_latency "$@"
