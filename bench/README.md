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

Reports go under `demo_artifacts/<timestamp>/` unless you pass `--output`.
