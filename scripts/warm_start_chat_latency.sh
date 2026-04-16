#!/usr/bin/env bash
# Purpose: Run warm-path chat latency bench (short cooldown); writes warm_start_report.md by default.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec uv run python -m bench.cold_start_chat_latency --warm "$@"
