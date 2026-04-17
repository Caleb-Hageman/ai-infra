# Purpose: MRR over live indexed chunks: fetch chunks via query API, query = chunk text prefix, gold = chunk id; writes mrr_report.md.

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_TOP_K = 5
DEFAULT_THRESHOLD = 0.7
DEFAULT_CLIENT_TIMEOUT_SEC = 120.0
DEFAULT_LIVE_MAX_CHUNKS = 20
DEFAULT_LIVE_QUERY_CHARS = 240
DEFAULT_LIVE_COLLECT_CAP = 5000
DEFAULT_MRR_SKIP_DOC_SUBSTRING = "audit_results.txt"

MODE_LIVE = "live"


@dataclass
class EvalItem:
    id: str
    label: str
    query: str
    gold_chunk_id: uuid.UUID


def _auth_headers_json(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }


def _query_from_chunk_text(content: str, max_chars: int) -> str:
    q = " ".join(content.split())
    if len(q) > max_chars:
        q = q[:max_chars].rstrip()
    return q if q else "."


def _skip_audit_doc_title(title: str) -> bool:
    return DEFAULT_MRR_SKIP_DOC_SUBSTRING.lower() in title.lower()


def collect_chunks_live_from_api(
    *,
    base_url: str,
    api_key: str,
    project_id: uuid.UUID,
    max_documents: int | None,
    collect_cap: int,
    http_client: httpx.Client,
) -> list[dict[str, Any]]:
    base = base_url.rstrip("/")
    headers = _auth_headers_json(api_key)
    doc_url = f"{base}/query/{project_id}/documents"
    r = http_client.get(doc_url, headers=headers)
    r.raise_for_status()
    docs = r.json()
    if not isinstance(docs, list):
        raise ValueError("documents response must be a JSON array")

    out: list[dict[str, Any]] = []
    for i, doc in enumerate(docs):
        if max_documents is not None and i >= max_documents:
            break
        did = doc.get("id")
        if did is None:
            continue
        title = doc.get("title") or str(did)
        if _skip_audit_doc_title(title):
            continue
        ch_url = f"{base}/query/documents/{did}/chunks"
        rc = http_client.get(ch_url, headers=headers)
        rc.raise_for_status()
        chunks = rc.json()
        if not isinstance(chunks, list):
            raise ValueError(f"chunks for document {did} must be a JSON array")
        for ch in chunks:
            content = (ch.get("content") or "").strip()
            if not content:
                continue
            out.append(
                {
                    "id": ch["id"],
                    "content": content,
                    "document_id": ch.get("document_id", did),
                    "doc_title": title,
                }
            )
            if len(out) >= collect_cap:
                return out
    return out


def build_eval_items(
    flat_chunks: list[dict[str, Any]],
    *,
    max_chunks: int,
    query_chars: int,
    seed: int | None,
) -> list[EvalItem]:
    if not flat_chunks:
        raise ValueError("no non-empty chunks in project; ingest and index first")
    pool = list(flat_chunks)
    if seed is not None:
        random.seed(seed)
        random.shuffle(pool)
    pool = pool[:max_chunks]
    items: list[EvalItem] = []
    for i, ch in enumerate(pool):
        cid = uuid.UUID(str(ch["id"]))
        q = _query_from_chunk_text(ch.get("content") or "", query_chars)
        label = str(ch.get("doc_title") or ch.get("document_id"))[:120]
        items.append(
            EvalItem(
                id=f"live-{i + 1}",
                label=label,
                query=q,
                gold_chunk_id=cid,
            )
        )
    return items


def dump_audit_json(items: list[EvalItem], path: str) -> None:
    rows = [
        {
            "id": it.id,
            "label": it.label,
            "query": it.query,
            "gold_chunk_id": str(it.gold_chunk_id),
        }
        for it in items
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"mode": MODE_LIVE, "items": rows}, f, indent=2)


def rank_and_rr(results: list[dict[str, Any]], gold: uuid.UUID) -> tuple[int | None, float]:
    for i, row in enumerate(results, start=1):
        cid = row.get("chunk_id")
        if cid is None:
            continue
        if uuid.UUID(str(cid)) == gold:
            rank = i
            return rank, 1.0 / float(rank)
    return None, 0.0


def _query_url(base: str, project_id: uuid.UUID) -> str:
    return f"{base.rstrip('/')}/query/{project_id}"


@dataclass
class RowOutcome:
    item_id: str
    label: str
    rank_display: str
    rr: float
    note: str


def run_eval(
    *,
    base_url: str,
    api_key: str,
    project_id: uuid.UUID,
    items: list[EvalItem],
    top_k: int,
    client_timeout_sec: float,
    http_client: httpx.Client | None = None,
) -> tuple[list[RowOutcome], list[str]]:
    url = _query_url(base_url, project_id)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    timeout = httpx.Timeout(client_timeout_sec)
    own = http_client is None
    client = http_client or httpx.Client(timeout=timeout)
    errors: list[str] = []
    rows: list[RowOutcome] = []

    def append_err(it: EvalItem, msg: str) -> None:
        errors.append(f"{it.id}: {msg}")
        rows.append(
            RowOutcome(
                item_id=it.id,
                label=it.label,
                rank_display="ERR",
                rr=0.0,
                note=msg[:80],
            )
        )

    try:
        for it in items:
            body = {"query": it.query, "top_k": top_k}
            try:
                resp = client.post(url, headers=headers, json=body)
            except httpx.RequestError as e:
                append_err(it, f"{type(e).__name__}: {e}")
                continue

            if resp.status_code != 200:
                append_err(it, f"HTTP {resp.status_code}")
                continue

            try:
                data = resp.json()
            except json.JSONDecodeError:
                append_err(it, "invalid JSON")
                continue

            raw_results = data.get("results")
            if not isinstance(raw_results, list):
                append_err(it, "missing results array")
                continue

            rank, rr = rank_and_rr(raw_results, it.gold_chunk_id)
            if rank is None:
                rows.append(
                    RowOutcome(
                        item_id=it.id,
                        label=it.label,
                        rank_display="—",
                        rr=0.0,
                        note="miss",
                    )
                )
            else:
                rows.append(
                    RowOutcome(
                        item_id=it.id,
                        label=it.label,
                        rank_display=str(rank),
                        rr=rr,
                        note="hit",
                    )
                )
    finally:
        if own:
            client.close()

    return rows, errors


def format_report_md(
    *,
    rows: list[RowOutcome],
    base_url: str,
    project_id: uuid.UUID,
    top_k: int,
    threshold: float,
    context_lines: list[str],
    embedding_note: str,
    run_started_utc: datetime,
    run_finished_utc: datetime,
) -> str:
    rrs = [r.rr for r in rows]
    mrr = statistics.mean(rrs) if rrs else 0.0
    misses = sum(1 for r in rows if r.rank_display == "—")
    passed = mrr >= threshold
    pass_label = "PASS" if passed else "FAIL"

    lines: list[str] = []
    lines.append("# MRR (live indexed chunks)")
    lines.append("")
    lines.append("## Context")
    lines.append("")
    for cl in context_lines:
        lines.append(cl)
    lines.append("")
    lines.append(f"- **MODE:** `{MODE_LIVE}`")
    lines.append(f"- API base (path redacted): `{_redacted_base(base_url)}`")
    lines.append(f"- **project_id:** `{project_id}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append(f"**MRR:** `{mrr:.3f}`  ")
    lines.append(f"**Threshold:** `{threshold:.2f}` → **{pass_label}**")
    lines.append(f"**Misses (not in top {top_k}):** `{misses}` / `{len(rows)}`")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Per-chunk")
    lines.append("")
    lines.append("| Id | Label | Rank | RR | Note |")
    lines.append("|----|-------|-----:|---:|------|")
    for r in rows:
        lab = r.label.replace("|", "\\|")
        note = r.note.replace("|", "\\|")
        lines.append(f"| {r.item_id} | {lab} | {r.rank_display} | {r.rr:.4f} | {note} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Definitions")
    lines.append("")
    lines.append(f"- **top_k:** `{top_k}`.")
    lines.append(
        f"- Golds from indexed chunks except titles containing `{DEFAULT_MRR_SKIP_DOC_SUBSTRING}`."
    )
    lines.append("- **RR:** 1/rank of the gold chunk in `POST /query/{project_id}` results; 0 if missing.")
    lines.append("- **MRR:** mean(RR) over sampled chunks.")
    if embedding_note.strip():
        lines.append(f"- **Embedding / chunking note:** {embedding_note.strip()}")
    lines.append(
        f"- **Run window (UTC):** {run_started_utc.isoformat()} → {run_finished_utc.isoformat()}"
    )
    lines.append("")
    return "\n".join(lines)


def _redacted_base(base_url: str) -> str:
    try:
        p = urlparse(base_url)
        host = p.hostname or ""
        return f"{p.scheme}://{host}/..."
    except Exception:
        return "<invalid>"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MRR from live indexed chunks only (MODE=live).",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BASE") or os.environ.get("BASE_URL"),
        help="API base URL (or env BASE / BASE_URL)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("API_KEY"),
        help="Bearer token (or env API_KEY)",
    )
    parser.add_argument(
        "--project-id",
        default=os.environ.get("PROJECT_ID"),
        help="Project UUID (env PROJECT_ID)",
    )
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K, help="default 5")
    parser.add_argument(
        "--threshold",
        type=float,
        default=float(os.environ.get("MRR_THRESHOLD", str(DEFAULT_THRESHOLD))),
        help="default 0.7",
    )
    parser.add_argument(
        "--client-timeout",
        type=float,
        default=float(os.environ.get("CLIENT_TIMEOUT_SEC", str(DEFAULT_CLIENT_TIMEOUT_SEC))),
        help="HTTP timeout seconds",
    )
    parser.add_argument(
        "--embedding-note",
        default=os.environ.get("EMBEDDING_NOTE", ""),
        help="Footer line for model/chunking provenance",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Report path (default: demo_artifacts/<timestamp>/mrr_report.md)",
    )
    parser.add_argument(
        "--vm-label",
        default=os.environ.get("VM_LABEL", ""),
        help="Optional VM identifier (env VM_LABEL)",
    )
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=int(os.environ.get("LIVE_MAX_CHUNKS", str(DEFAULT_LIVE_MAX_CHUNKS))),
        help="How many chunks to sample (default 20)",
    )
    parser.add_argument(
        "--query-chars",
        type=int,
        default=int(os.environ.get("LIVE_QUERY_CHARS", str(DEFAULT_LIVE_QUERY_CHARS))),
        help="Query = first N chars of chunk text (default 240)",
    )
    parser.add_argument(
        "--max-documents",
        type=int,
        default=None,
        help="Cap documents to walk (default: all)",
    )
    parser.add_argument(
        "--collect-cap",
        type=int,
        default=DEFAULT_LIVE_COLLECT_CAP,
        help="Max chunks to collect before sampling (default 5000)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for which chunks to keep",
    )
    parser.add_argument(
        "--write-audit-json",
        default=None,
        help="Optional path to write sampled items (audit)",
    )
    args = parser.parse_args()

    if not args.base_url or not args.api_key or not args.project_id:
        parser.error("Provide --base-url, --api-key, and --project-id (or env equivalents)")

    pid = uuid.UUID(args.project_id)

    hostname = os.environ.get("HOSTNAME", "")
    gcp_project = os.environ.get("GOOGLE_CLOUD_PROJECT", os.environ.get("GCP_PROJECT", ""))

    context_lines = [
        f"- **When (UTC):** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} run start",
    ]
    if args.vm_label:
        context_lines.append(f"- **VM / host:** {args.vm_label}")
    elif hostname:
        context_lines.append(f"- **VM / host:** {hostname}")
    if gcp_project:
        context_lines.append(f"- **GCP project:** {gcp_project}")

    started = datetime.now(timezone.utc)
    timeout = httpx.Timeout(args.client_timeout)
    with httpx.Client(timeout=timeout) as client:
        flat = collect_chunks_live_from_api(
            base_url=args.base_url,
            api_key=args.api_key,
            project_id=pid,
            max_documents=args.max_documents,
            collect_cap=args.collect_cap,
            http_client=client,
        )
        items = build_eval_items(
            flat,
            max_chunks=args.max_chunks,
            query_chars=args.query_chars,
            seed=args.seed,
        )
        if args.write_audit_json:
            dump_audit_json(items, args.write_audit_json)
        rows, errs = run_eval(
            base_url=args.base_url,
            api_key=args.api_key,
            project_id=pid,
            items=items,
            top_k=args.top_k,
            client_timeout_sec=args.client_timeout,
            http_client=client,
        )
    finished = datetime.now(timezone.utc)

    if errs:
        for e in errs:
            print(f"warning: {e}", flush=True)

    if args.output:
        out_path = args.output
    else:
        stamp = started.strftime("%Y-%m-%dT%H-%M-%SZ")
        out_dir = os.path.join("demo_artifacts", stamp)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "mrr_report.md")

    report = format_report_md(
        rows=rows,
        base_url=args.base_url,
        project_id=pid,
        top_k=args.top_k,
        threshold=args.threshold,
        context_lines=context_lines,
        embedding_note=args.embedding_note,
        run_started_utc=started,
        run_finished_utc=finished,
    )
    out_parent = os.path.dirname(os.path.abspath(out_path))
    if out_parent:
        os.makedirs(out_parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
