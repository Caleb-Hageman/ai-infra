# Bench

Run from the **repo root** (where `pyproject.toml` is).

```bash
cd /path/to/ai-infra
```

```bash
export BASE="https://YOUR_API_HOST"
export API_KEY="YOUR_KEY"
export PROJECT_ID="YOUR_PROJECT_UUID"
```

Optional: `export SERVER_TIMEOUT_LABEL="Cloud Run 300s"` (cold start footer).

---

**1. Cold start chat**

```bash
uv run python -m bench.cold_start_chat_latency
```

**1b. Warm start chat** (short cooldown between trials; report `warm_start_report.md`)

```bash
./scripts/warm_start_chat_latency.sh --trials 20
# or: uv run python -m bench.cold_start_chat_latency --warm --trials 20
```

---

**2. MRR**

MODE=`live` only: samples real chunks from the query API, builds queries from chunk text, scores RR vs gold chunk id.

```bash
uv run python -m bench.mrr_retrieval
```

---

**3. Upload latency**

```bash
uv run python -m bench.upload_latency
```

---

**4. Query retrieval latency** (`POST /query/{project_id}` — embeddings + vector search only, no LLM chat)

```bash
./scripts/query_retrieval_latency.sh --trials 30
# or: uv run python -m bench.query_retrieval_latency --trials 30
```

Uses `BASE`, `API_KEY`, and `PROJECT_ID`. Optional: `QUERY_TEXT`, `TOP_K`, `QUERY_SOURCE` (exact source filename filter).

---

Reports go under `demo_artifacts/<timestamp>/` unless you pass `--output`.
