# Purpose: CLI comparing legacy multipart vs signed-PUT+complete upload latency; writes upload_latency_report.md.

from __future__ import annotations

import argparse
import os
import statistics
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

DEFAULT_CLIENT_TIMEOUT_SEC = 600.0
DEFAULT_RUNS = 3
DEFAULT_SIZES_BYTES = (256 * 1024, 1024 * 1024, 5 * 1024 * 1024)


def _make_text_payload(size_bytes: int) -> bytes:
    line = b"benchmark line\n"
    out = bytearray()
    while len(out) < size_bytes:
        out.extend(line)
    return bytes(out[:size_bytes])


def _redacted_base(base_url: str) -> str:
    try:
        p = urlparse(base_url)
        host = p.hostname or ""
        return f"{p.scheme}://{host}/..."
    except Exception:
        return "<invalid>"


@dataclass
class SingleRunResult:
    legacy_ms: float | None
    legacy_error: str | None
    async_wall_ms: float | None
    async_init_ms: float | None
    async_put_ms: float | None
    async_complete_ms: float | None
    async_error: str | None


def _legacy_upload_ms(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    project_id: uuid.UUID,
    filename: str,
    content: bytes,
    content_type: str,
) -> tuple[float | None, str | None]:
    url = f"{base_url.rstrip('/')}/ingest/{project_id}/upload"
    headers = {"Authorization": f"Bearer {api_key}"}
    files = {"file": (filename, content, content_type)}
    t0 = time.perf_counter()
    try:
        resp = client.post(url, headers=headers, files=files)
    except httpx.RequestError as e:
        return None, f"{type(e).__name__}: {e}"
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if resp.status_code != 201:
        return None, f"HTTP {resp.status_code}"
    return elapsed_ms, None


def _async_upload_ms(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    project_id: uuid.UUID,
    filename: str,
    content: bytes,
    content_type: str,
) -> tuple[float | None, float | None, float | None, float | None, str | None]:
    base = base_url.rstrip("/")
    init_url = f"{base}/ingest/{project_id}/upload/init"
    headers_json = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    wall0 = time.perf_counter()
    try:
        t0 = time.perf_counter()
        r_init = client.post(
            init_url,
            headers=headers_json,
            json={"filename": filename, "content_type": content_type},
        )
        init_ms = (time.perf_counter() - t0) * 1000.0
        if r_init.status_code != 200:
            return None, None, None, None, f"init HTTP {r_init.status_code}"
        data = r_init.json()
        upload_url = data.get("upload_url")
        session_id = data.get("session_id")
        if not upload_url or not session_id:
            return None, None, None, None, "init response missing upload_url or session_id"

        t1 = time.perf_counter()
        r_put = client.put(
            upload_url,
            content=content,
            headers={"Content-Type": content_type},
        )
        put_ms = (time.perf_counter() - t1) * 1000.0
        if r_put.status_code not in (200, 201):
            return None, init_ms, put_ms, None, f"PUT HTTP {r_put.status_code}"

        complete_url = f"{base}/ingest/{project_id}/upload/{session_id}/complete"
        t2 = time.perf_counter()
        r_comp = client.post(complete_url, headers=headers_json)
        complete_ms = (time.perf_counter() - t2) * 1000.0
        wall_ms = (time.perf_counter() - wall0) * 1000.0
        if r_comp.status_code != 202:
            return None, init_ms, put_ms, complete_ms, f"complete HTTP {r_comp.status_code}"
        return wall_ms, init_ms, put_ms, complete_ms, None
    except httpx.RequestError as e:
        return None, None, None, None, f"{type(e).__name__}: {e}"


def run_matrix(
    *,
    base_url: str,
    api_key: str,
    project_id: uuid.UUID,
    sizes_bytes: list[int],
    runs: int,
    client_timeout_sec: float,
    content_type: str,
    http_client: httpx.Client | None = None,
) -> dict[int, list[SingleRunResult]]:
    own = http_client is None
    timeout = httpx.Timeout(client_timeout_sec)
    client = http_client or httpx.Client(timeout=timeout)
    out: dict[int, list[SingleRunResult]] = {}

    try:
        for size in sizes_bytes:
            row_runs: list[SingleRunResult] = []
            for run_idx in range(runs):
                fname = f"bench_{uuid.uuid4().hex[:10]}_{size}.txt"
                content = _make_text_payload(size)
                leg_ms, leg_err = _legacy_upload_ms(
                    client, base_url, api_key, project_id, fname, content, content_type
                )
                aw, ai, ap, ac, aerr = _async_upload_ms(
                    client, base_url, api_key, project_id, fname, content, content_type
                )
                row_runs.append(
                    SingleRunResult(
                        legacy_ms=leg_ms,
                        legacy_error=leg_err,
                        async_wall_ms=aw,
                        async_init_ms=ai,
                        async_put_ms=ap,
                        async_complete_ms=ac,
                        async_error=aerr,
                    )
                )
            out[size] = row_runs
    finally:
        if own:
            client.close()

    return out


def _median_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return float(statistics.median(values))


def format_upload_report_md(
    *,
    matrix: dict[int, list[SingleRunResult]],
    base_url: str,
    project_id: uuid.UUID,
    runs: int,
    discard_first: bool,
    context_lines: list[str],
    done_definition: str,
    started_utc: datetime,
    finished_utc: datetime,
) -> str:
    lines: list[str] = []
    lines.append("# Upload latency (legacy vs async)")
    lines.append("")
    lines.append("## Context")
    lines.append("")
    for cl in context_lines:
        lines.append(cl)
    lines.append("")
    lines.append(f"- API base (path redacted): `{_redacted_base(base_url)}`")
    lines.append(f"- **project_id:** `{project_id}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    sizes_sorted = sorted(matrix.keys())
    headline = ""
    if sizes_sorted:
        largest = sizes_sorted[-1]
        rows = matrix[largest]
        leg_ok = [r.legacy_ms for r in rows if r.legacy_ms is not None]
        asy_ok = [r.async_wall_ms for r in rows if r.async_wall_ms is not None]
        lm = _median_or_none(leg_ok)
        am = _median_or_none(asy_ok)
        if lm is not None and am is not None:
            if lm < am:
                headline = (
                    f"**At largest size ({largest} B):** legacy median **faster** "
                    f"(`{lm:,.1f}` ms vs `{am:,.1f}` ms async wall time)."
                )
            elif am < lm:
                headline = (
                    f"**At largest size ({largest} B):** async median **faster** "
                    f"(`{am:,.1f}` ms vs `{lm:,.1f}` ms legacy)."
                )
            else:
                headline = f"**At largest size ({largest} B):** medians **tie** (~`{lm:,.1f}` ms)."
        else:
            headline = "**Headline:** incomplete data at largest size (check errors below)."
    else:
        headline = "**Headline:** no sizes measured."

    lines.append("## Headline")
    lines.append("")
    lines.append(headline)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Matrix (medians per column; raw runs aggregated)")
    lines.append("")
    lines.append(
        "| Size (B) | Legacy ms (med) | Async wall ms (med) | init / put / complete (med) | n |"
    )
    lines.append("|----------|----------------:|--------------------:|----------------------------:|--:|")

    for size in sizes_sorted:
        rs = matrix[size]
        if discard_first and len(rs) > 1:
            rs = rs[1:]
        n = len(rs)
        legs = [r.legacy_ms for r in rs if r.legacy_ms is not None]
        walls = [r.async_wall_ms for r in rs if r.async_wall_ms is not None]
        inits = [r.async_init_ms for r in rs if r.async_init_ms is not None]
        puts = [r.async_put_ms for r in rs if r.async_put_ms is not None]
        comps = [r.async_complete_ms for r in rs if r.async_complete_ms is not None]
        lm = _median_or_none(legs)
        wm = _median_or_none(walls)
        im = _median_or_none(inits)
        pm = _median_or_none(puts)
        cm = _median_or_none(comps)
        leg_s = f"{lm:,.1f}" if lm is not None else "—"
        wall_s = f"{wm:,.1f}" if wm is not None else "—"
        if im is not None and pm is not None and cm is not None:
            triple = f"{im:,.0f} / {pm:,.0f} / {cm:,.0f}"
        else:
            triple = "—"
        lines.append(f"| {size} | {leg_s} | {wall_s} | {triple} | {n} |")

    err_lines = []
    for size, rs in sorted(matrix.items()):
        for i, r in enumerate(rs):
            if r.legacy_error:
                err_lines.append(f"- size={size} run={i + 1} legacy: {r.legacy_error}")
            if r.async_error:
                err_lines.append(f"- size={size} run={i + 1} async: {r.async_error}")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Definitions")
    lines.append("")
    lines.append(
        "- **Legacy:** multipart `POST /ingest/{project_id}/upload` until **201** (sync chunk+embed completes in-process)."
    )
    lines.append(
        "- **Async wall:** time from `upload/init` request start through **`complete`** response (**202**); "
        "background embedding may still run."
    )
    lines.append(f"- **Done (this report):** {done_definition}")
    lines.append(
        f"- **Runs per size:** {runs}; **discard first run:** {discard_first} (per size, both methods)."
    )
    lines.append(
        f"- **Run window (UTC):** {started_utc.isoformat()} → {finished_utc.isoformat()}"
    )
    if err_lines:
        lines.append("")
        lines.append("## Errors")
        lines.append("")
        for el in err_lines:
            lines.append(el)
    lines.append("")
    return "\n".join(lines)


def _parse_sizes(s: str) -> list[int]:
    parts = [p.strip() for p in s.split(",") if p.strip()]
    return [int(p, 10) for p in parts]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare legacy multipart vs async upload latency; write upload_latency_report.md.",
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
    parser.add_argument(
        "--sizes-bytes",
        default=",".join(str(x) for x in DEFAULT_SIZES_BYTES),
        help="Comma-separated sizes in bytes (default: 256Ki,1Mi,5Mi)",
    )
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS, help="Runs per size")
    parser.add_argument(
        "--discard-first",
        action="store_true",
        help="Drop first run per size when computing medians (both methods)",
    )
    parser.add_argument(
        "--content-type",
        default="text/plain",
        help="Content-Type for upload (must match allowed types, e.g. text/plain)",
    )
    parser.add_argument(
        "--client-timeout",
        type=float,
        default=float(os.environ.get("CLIENT_TIMEOUT_SEC", str(DEFAULT_CLIENT_TIMEOUT_SEC))),
        help="HTTP timeout seconds (large uploads need headroom)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Report path (default: demo_artifacts/<timestamp>/upload_latency_report.md)",
    )
    parser.add_argument(
        "--vm-label",
        default=os.environ.get("VM_LABEL", ""),
        help="Optional VM identifier (env VM_LABEL)",
    )
    args = parser.parse_args()

    if not args.base_url or not args.api_key or not args.project_id:
        parser.error("Provide --base-url, --api-key, and --project-id (or env equivalents)")

    pid = uuid.UUID(args.project_id)
    sizes = _parse_sizes(args.sizes_bytes)

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
    matrix = run_matrix(
        base_url=args.base_url,
        api_key=args.api_key,
        project_id=pid,
        sizes_bytes=sizes,
        runs=args.runs,
        client_timeout_sec=args.client_timeout,
        content_type=args.content_type,
    )
    finished = datetime.now(timezone.utc)

    done_definition = (
        "Legacy = 201 after full inline ingest; async wall = 202 from complete (document row + background task queued)."
    )

    report = format_upload_report_md(
        matrix=matrix,
        base_url=args.base_url,
        project_id=pid,
        runs=args.runs,
        discard_first=args.discard_first,
        context_lines=context_lines,
        done_definition=done_definition,
        started_utc=started,
        finished_utc=finished,
    )

    out_path: str
    if args.output:
        out_path = args.output
    else:
        stamp = started.strftime("%Y-%m-%dT%H-%M-%SZ")
        out_dir = os.path.join("demo_artifacts", stamp)
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "upload_latency_report.md")

    out_parent = os.path.dirname(os.path.abspath(out_path))
    if out_parent:
        os.makedirs(out_parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
