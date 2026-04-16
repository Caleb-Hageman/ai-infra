# Purpose: Measure POST /query/{project_id} latency (embedding + vector retrieval only; no LLM chat).

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_CLIENT_TIMEOUT_SEC = 120.0
DEFAULT_QUERY_TEXT = "Summarize the main topics in the indexed documents."
DEFAULT_TOP_K = 5


@dataclass
class QueryTrialRecord:
    trial_index: int
    success: bool
    elapsed_ms: float
    http_status: int | None
    total_results: int | None
    error: str | None = None


def _query_url(base: str, project_id: str) -> str:
    b = base.rstrip("/")
    return f"{b}/query/{project_id}"


def _redacted_base(base_url: str) -> str:
    try:
        p = urlparse(base_url)
        host = p.hostname or ""
        return f"{p.scheme}://{host}/..."
    except Exception:
        return "<invalid>"


def run_query_trial(
    *,
    base_url: str,
    project_id: uuid.UUID,
    api_key: str,
    query_text: str,
    top_k: int,
    source: str | None,
    client_timeout_sec: float,
    http_client: httpx.Client | None = None,
) -> QueryTrialRecord:
    url = _query_url(base_url, str(project_id))
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body: dict[str, Any] = {"query": query_text, "top_k": top_k}
    if source:
        body["source"] = source

    timeout = httpx.Timeout(client_timeout_sec)
    own_client = http_client is None
    client = http_client or httpx.Client(timeout=timeout)

    try:
        t0 = time.perf_counter()
        try:
            resp = client.post(url, headers=headers, json=body)
        except httpx.TimeoutException:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return QueryTrialRecord(
                trial_index=0,
                success=False,
                elapsed_ms=elapsed_ms,
                http_status=None,
                total_results=None,
                error="client_timeout",
            )
        except httpx.RequestError as e:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            return QueryTrialRecord(
                trial_index=0,
                success=False,
                elapsed_ms=elapsed_ms,
                http_status=None,
                total_results=None,
                error=f"request_error:{type(e).__name__}",
            )

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        if resp.status_code != 200:
            return QueryTrialRecord(
                trial_index=0,
                success=False,
                elapsed_ms=elapsed_ms,
                http_status=resp.status_code,
                total_results=None,
                error=f"HTTP {resp.status_code}",
            )

        try:
            data = resp.json()
        except json.JSONDecodeError:
            return QueryTrialRecord(
                trial_index=0,
                success=False,
                elapsed_ms=elapsed_ms,
                http_status=200,
                total_results=None,
                error="invalid_json_200",
            )

        total = data.get("total")
        if isinstance(total, int):
            n = total
        elif isinstance(data.get("results"), list):
            n = len(data["results"])
        else:
            n = None

        return QueryTrialRecord(
            trial_index=0,
            success=True,
            elapsed_ms=elapsed_ms,
            http_status=200,
            total_results=n,
            error=None,
        )
    finally:
        if own_client:
            client.close()


def format_report_md(
    *,
    trials: list[QueryTrialRecord],
    base_url: str,
    project_id: uuid.UUID,
    query_text: str,
    top_k: int,
    context_lines: list[str],
    client_timeout_sec: float,
    started_at_utc: datetime,
    finished_at_utc: datetime,
) -> str:
    lines: list[str] = []
    lines.append("# Query retrieval latency (no chat)")
    lines.append("")
    lines.append("## Context")
    lines.append("")
    for cl in context_lines:
        lines.append(cl)
    lines.append("")
    lines.append(f"- API base (path redacted): `{_redacted_base(base_url)}`")
    lines.append(f"- **Endpoint:** `POST /query/{{project_id}}` (similarity search only).")
    lines.append(f"- **project_id:** `{project_id}`")
    lines.append(f"- **top_k:** `{top_k}`")
    lines.append(f"- **Query text (truncated):** `{query_text[:120]}{'…' if len(query_text) > 120 else ''}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    ok_ms = [t.elapsed_ms for t in trials if t.success]
    if ok_ms:
        mean_ms = statistics.mean(ok_ms)
        med_ms = statistics.median(ok_ms)
        headline = (
            f"**Mean latency (successful trials):** `{mean_ms:,.1f}` ms  \n"
            f"**Median:** `{med_ms:,.1f}` ms  \n"
            f"*(Single POST per trial: query embedding + pgvector retrieval + JSON response.)*"
        )
    else:
        headline = "**Mean latency:** n/a (no successful trials)"

    lines.append("## Headline")
    lines.append("")
    lines.append(headline)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Trials")
    lines.append("")
    lines.append("| Trial | Latency ms | HTTP | Chunks returned | Note |")
    lines.append("|------:|-----------:|-----:|----------------:|------|")
    for i, tr in enumerate(trials, start=1):
        note = (tr.error or "ok").replace("|", "\\|")
        http_s = str(tr.http_status) if tr.http_status is not None else "—"
        ch = str(tr.total_results) if tr.total_results is not None else "—"
        lat = f"{tr.elapsed_ms:,.1f}" if tr.success else "FAILED"
        lines.append(f"| {i} | {lat} | {http_s} | {ch} | {note} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Definitions")
    lines.append("")
    lines.append(
        f"- **Client timeout:** `{client_timeout_sec:g}` s per request (httpx read/connect)."
    )
    lines.append(
        f"- **Run window (UTC):** {started_at_utc.isoformat()} -> {finished_at_utc.isoformat()}"
    )
    lines.append(
        "- **Scope:** This measures retrieval only (`POST /query/...`), not `POST /api/v1/chat`."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Measure POST /query/{project_id} latency (vector retrieval; no LLM chat); "
            "write Markdown report."
        ),
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
        required=False,
        help="Project UUID (required; or env PROJECT_ID)",
    )
    parser.add_argument(
        "--query",
        default=os.environ.get("QUERY_TEXT", DEFAULT_QUERY_TEXT),
        help="Search query string (env QUERY_TEXT)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=int(os.environ.get("TOP_K", DEFAULT_TOP_K)),
        help=f"top_k (default {DEFAULT_TOP_K})",
    )
    parser.add_argument(
        "--source",
        default=os.environ.get("QUERY_SOURCE") or None,
        help="Optional exact source filename filter (env QUERY_SOURCE)",
    )
    parser.add_argument("--trials", type=int, default=10, help="Number of trials")
    parser.add_argument(
        "--sleep-between",
        type=float,
        default=float(os.environ.get("SLEEP_BETWEEN_SEC", "0")),
        help="Seconds to sleep between trials (default 0)",
    )
    parser.add_argument(
        "--client-timeout",
        type=float,
        default=float(os.environ.get("CLIENT_TIMEOUT_SEC", DEFAULT_CLIENT_TIMEOUT_SEC)),
        help="Per-request client timeout seconds",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Report path (default: demo_artifacts/<timestamp>/query_retrieval_report.md)",
    )
    parser.add_argument(
        "--vm-label",
        default=os.environ.get("VM_LABEL", ""),
        help="Optional VM identifier for context (env VM_LABEL)",
    )
    args = parser.parse_args()

    if not args.base_url or not args.api_key:
        parser.error("Provide --base-url and --api-key (or BASE and API_KEY)")
    if not args.project_id:
        parser.error("Provide --project-id (or PROJECT_ID)")

    pid = uuid.UUID(args.project_id)
    if not (1 <= args.top_k <= 50):
        parser.error("--top-k must be between 1 and 50")

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
    records: list[QueryTrialRecord] = []

    for trial_num in range(1, args.trials + 1):
        if trial_num > 1 and args.sleep_between > 0:
            print(f"Sleeping {args.sleep_between:.1f}s before trial {trial_num}...", flush=True)
            time.sleep(args.sleep_between)

        print(f"Trial {trial_num}/{args.trials} ...", flush=True)
        tr = run_query_trial(
            base_url=args.base_url,
            project_id=pid,
            api_key=args.api_key,
            query_text=args.query,
            top_k=args.top_k,
            source=args.source,
            client_timeout_sec=args.client_timeout,
        )
        tr.trial_index = trial_num
        records.append(tr)
        print(
            f"  -> success={tr.success} ms={tr.elapsed_ms:.1f} http={tr.http_status} "
            f"total={tr.total_results}",
            flush=True,
        )

    finished = datetime.now(timezone.utc)

    if args.output:
        out_path = args.output
    else:
        stamp = started.strftime("%Y-%m-%dT%H-%M-%SZ")
        out_dir = os.path.join("demo_artifacts", stamp)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "query_retrieval_report.md")

    report = format_report_md(
        trials=records,
        base_url=args.base_url,
        project_id=pid,
        query_text=args.query,
        top_k=args.top_k,
        context_lines=context_lines,
        client_timeout_sec=args.client_timeout,
        started_at_utc=started,
        finished_at_utc=finished,
    )
    out_parent = os.path.dirname(os.path.abspath(out_path))
    if out_parent:
        os.makedirs(out_parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
