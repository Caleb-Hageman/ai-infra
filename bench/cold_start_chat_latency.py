# Purpose: CLI to measure POST /api/v1/chat cold-start latency with retry summation; writes cold_start_report.md.

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_COOLDOWN_COLD_SEC = 906
DEFAULT_COOLDOWN_WARM_SEC = 5
DEFAULT_CLIENT_TIMEOUT_SEC = 120.0
DEFAULT_MAX_ATTEMPTS = 20
DEFAULT_QUESTION = "Reply with one word: ping."

RETRYABLE_STATUS = frozenset({408, 499, 500, 502, 503, 504})


@dataclass
class AttemptRecord:
    elapsed_ms: float
    outcome: str
    http_status: int | None = None


@dataclass
class TrialRecord:
    trial_index: int
    success: bool
    total_ms: float
    attempts: int
    attempt_details: list[AttemptRecord] = field(default_factory=list)
    error: str | None = None


def _chat_url(base: str) -> str:
    b = base.rstrip("/")
    return f"{b}/api/v1/chat"


def _build_body(
    question: str,
    project_id: uuid.UUID | None,
    system_prompt: str | None,
    min_score: float | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"question": question}
    if project_id is not None:
        body["project_id"] = str(project_id)
    if system_prompt is not None:
        body["system_prompt"] = system_prompt
    if min_score is not None:
        body["min_score"] = min_score
    return body


def run_cold_trial(
    *,
    base_url: str,
    api_key: str,
    body: dict[str, Any],
    client_timeout_sec: float,
    max_attempts: int,
    http_client: httpx.Client | None = None,
) -> TrialRecord:
    url = _chat_url(base_url)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    timeout = httpx.Timeout(client_timeout_sec)
    own_client = http_client is None
    client = http_client or httpx.Client(timeout=timeout)

    total_ms = 0.0
    details: list[AttemptRecord] = []

    try:
        for _ in range(max_attempts):
            t0 = time.perf_counter()
            try:
                resp = client.post(url, headers=headers, json=body)
            except httpx.TimeoutException:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                total_ms += elapsed_ms
                details.append(
                    AttemptRecord(elapsed_ms=elapsed_ms, outcome="client_timeout", http_status=None)
                )
                continue
            except httpx.RequestError as e:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                total_ms += elapsed_ms
                details.append(
                    AttemptRecord(
                        elapsed_ms=elapsed_ms,
                        outcome=f"request_error:{type(e).__name__}",
                        http_status=None,
                    )
                )
                continue

            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            total_ms += elapsed_ms

            if resp.status_code == 200:
                try:
                    data = resp.json()
                except json.JSONDecodeError:
                    return TrialRecord(
                        trial_index=0,
                        success=False,
                        total_ms=total_ms,
                        attempts=len(details) + 1,
                        attempt_details=details
                        + [
                            AttemptRecord(
                                elapsed_ms=elapsed_ms,
                                outcome="invalid_json_200",
                                http_status=200,
                            )
                        ],
                        error="200 response was not valid JSON",
                    )
                if data.get("status") == "success":
                    details.append(
                        AttemptRecord(elapsed_ms=elapsed_ms, outcome="ok", http_status=200)
                    )
                    return TrialRecord(
                        trial_index=0,
                        success=True,
                        total_ms=total_ms,
                        attempts=len(details),
                        attempt_details=details,
                    )
                details.append(
                    AttemptRecord(elapsed_ms=elapsed_ms, outcome="unexpected_body", http_status=200)
                )
                return TrialRecord(
                    trial_index=0,
                    success=False,
                    total_ms=total_ms,
                    attempts=len(details),
                    attempt_details=details,
                    error='JSON missing status=="success"',
                )

            if resp.status_code in RETRYABLE_STATUS:
                details.append(
                    AttemptRecord(
                        elapsed_ms=elapsed_ms,
                        outcome=f"http_{resp.status_code}",
                        http_status=resp.status_code,
                    )
                )
                continue

            details.append(
                AttemptRecord(
                    elapsed_ms=elapsed_ms,
                    outcome=f"http_{resp.status_code}",
                    http_status=resp.status_code,
                )
            )
            return TrialRecord(
                trial_index=0,
                success=False,
                total_ms=total_ms,
                attempts=len(details),
                attempt_details=details,
                error=f"non-retryable HTTP {resp.status_code}",
            )

        return TrialRecord(
            trial_index=0,
            success=False,
            total_ms=total_ms,
            attempts=len(details),
            attempt_details=details,
            error=f"exhausted {max_attempts} attempts",
        )
    finally:
        if own_client:
            client.close()


def _trial_note(tr: TrialRecord) -> str:
    if tr.error and not tr.success:
        outs = [a.outcome for a in tr.attempt_details]
        if outs:
            return f"{tr.error}; attempts={','.join(outs)}"
        return tr.error
    if tr.success:
        retries = tr.attempts - 1
        if retries <= 0:
            return "ok"
        kinds = [a.outcome for a in tr.attempt_details[:-1]]
        return f"ok after retries ({','.join(kinds)})"
    return tr.error or "failed"


def format_report_md(
    *,
    trials: list[TrialRecord],
    base_url: str,
    context_lines: list[str],
    client_timeout_sec: float,
    server_timeout_label: str,
    started_at_utc: datetime,
    finished_at_utc: datetime,
    report_title: str = "Cold-start chat latency",
    trial_mode: str = "cold",
) -> str:
    lines: list[str] = []
    lines.append(f"# {report_title}")
    lines.append("")
    lines.append("## Context")
    lines.append("")
    for cl in context_lines:
        lines.append(cl)
    lines.append("")
    lines.append(f"- API base (path redacted): `{_redacted_base(base_url)}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    ok_ms = [t.total_ms for t in trials if t.success]
    if ok_ms:
        mean_ms = statistics.mean(ok_ms)
        med_ms = statistics.median(ok_ms)
        headline = (
            f"**Mean total latency (successful trials):** `{mean_ms:,.1f}` ms  \n"
            f"**Median:** `{med_ms:,.1f}` ms  \n"
            f"*(Total per trial = sum of all attempt durations until HTTP 200.)*"
        )
    else:
        headline = "**Mean total latency:** n/a (no successful trials)"

    lines.append("## Headline")
    lines.append("")
    lines.append(headline)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Trials")
    lines.append("")
    lines.append("| Trial | Total ms | Attempts | Note |")
    lines.append("|------:|---------:|---------:|------|")
    for i, tr in enumerate(trials, start=1):
        note = _trial_note(tr).replace("|", "\\|")
        st = "FAILED" if not tr.success else f"{tr.total_ms:,.1f}"
        lines.append(f"| {i} | {st} | {tr.attempts} | {note} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Definitions")
    lines.append("")
    lines.append(
        f"- **Client timeout:** `{client_timeout_sec:g}` s per attempt (httpx read/connect)."
    )
    lines.append(
        f"- **Server / platform timeout (documented):** {server_timeout_label}"
    )
    lines.append(
        f"- **Run window (UTC):** {started_at_utc.isoformat()} -> {finished_at_utc.isoformat()}"
    )
    lines.append(
        "- **Retries:** client timeout and HTTP "
        + ", ".join(str(x) for x in sorted(RETRYABLE_STATUS))
        + " count toward the same trial total; each attempt is summed."
    )
    if trial_mode == "warm":
        lines.append(
            "- **Warmup:** warm-path trials use short cooldown between requests; "
            "not a scale-to-zero cold measurement."
        )
    else:
        lines.append(
            "- **Warmup:** do not call `GET /warmup` before a cold trial "
            "(defeats cold start)."
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
        description="Measure cold-start POST /api/v1/chat latency (summed retries); write Markdown report.",
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
        help="Optional UUID for RAG (env PROJECT_ID)",
    )
    parser.add_argument(
        "--question",
        default=os.environ.get("CHAT_QUESTION", DEFAULT_QUESTION),
        help="Chat question JSON field",
    )
    parser.add_argument(
        "--system-prompt",
        default=os.environ.get("CHAT_SYSTEM_PROMPT"),
        help="Optional system_prompt",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=None,
        help="Optional min_score for retrieval",
    )
    parser.add_argument("--trials", type=int, default=1, help="Number of cold trials")
    parser.add_argument(
        "--cooldown-seconds",
        type=float,
        default=None,
        help="Sleep between trials (default: 906 cold, 5 warm)",
    )
    parser.add_argument(
        "--warm",
        action="store_true",
        help="Short cooldown between trials (sanity / warm path)",
    )
    parser.add_argument(
        "--sleep-before-first",
        type=float,
        default=0.0,
        help="Optional seconds to sleep before trial 1 (e.g. after manual scale-to-zero)",
    )
    parser.add_argument(
        "--client-timeout",
        type=float,
        default=float(os.environ.get("CLIENT_TIMEOUT_SEC", DEFAULT_CLIENT_TIMEOUT_SEC)),
        help="Per-attempt client timeout seconds",
    )
    parser.add_argument(
        "--server-timeout-label",
        default=os.environ.get(
            "SERVER_TIMEOUT_LABEL",
            "set SERVER_TIMEOUT_LABEL (e.g. Cloud Run request timeout 300s)",
        ),
        help="Footer text describing platform timeout",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
        help="Max POST attempts per trial",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Report path (default: demo_artifacts/<timestamp>/cold_start_report.md "
            "or warm_start_report.md when --warm)"
        ),
    )
    parser.add_argument(
        "--vm-label",
        default=os.environ.get("VM_LABEL", ""),
        help="Optional VM identifier for context (env VM_LABEL)",
    )
    args = parser.parse_args()

    if not args.base_url or not args.api_key:
        parser.error("Provide --base-url and --api-key (or BASE and API_KEY)")

    pid: uuid.UUID | None = None
    if args.project_id:
        pid = uuid.UUID(args.project_id)

    if args.min_score is not None and not (0.0 <= args.min_score <= 1.0):
        parser.error("--min-score must be between 0 and 1")

    cooldown = args.cooldown_seconds
    if cooldown is None:
        cooldown = DEFAULT_COOLDOWN_WARM_SEC if args.warm else DEFAULT_COOLDOWN_COLD_SEC

    body = _build_body(
        args.question,
        pid,
        args.system_prompt,
        args.min_score,
    )

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
    context_lines.append(
        f"- **Mode:** {'warm (short cooldown)' if args.warm else 'cold (long cooldown between trials)'}"
    )

    started = datetime.now(timezone.utc)
    records: list[TrialRecord] = []

    if args.sleep_before_first > 0:
        print(f"Sleeping {args.sleep_before_first:.0f}s before trial 1...", flush=True)
        time.sleep(args.sleep_before_first)

    for trial_num in range(1, args.trials + 1):
        if trial_num > 1:
            print(f"Cooling down {cooldown:.0f}s before trial {trial_num}...", flush=True)
            time.sleep(cooldown)

        print(f"Trial {trial_num}/{args.trials} ...", flush=True)
        tr = run_cold_trial(
            base_url=args.base_url,
            api_key=args.api_key,
            body=body,
            client_timeout_sec=args.client_timeout,
            max_attempts=args.max_attempts,
        )
        tr.trial_index = trial_num
        records.append(tr)
        print(
            f"  -> success={tr.success} total_ms={tr.total_ms:.1f} attempts={tr.attempts}",
            flush=True,
        )

    finished = datetime.now(timezone.utc)

    out_path: str
    if args.output:
        out_path = args.output
    else:
        stamp = started.strftime("%Y-%m-%dT%H-%M-%SZ")
        out_dir = os.path.join("demo_artifacts", stamp)
        os.makedirs(out_dir, exist_ok=True)
        fname = "warm_start_report.md" if args.warm else "cold_start_report.md"
        out_path = os.path.join(out_dir, fname)

    report_title = "Warm-start chat latency" if args.warm else "Cold-start chat latency"
    trial_mode = "warm" if args.warm else "cold"

    report = format_report_md(
        trials=records,
        base_url=args.base_url,
        context_lines=context_lines,
        client_timeout_sec=args.client_timeout,
        server_timeout_label=args.server_timeout_label,
        started_at_utc=started,
        finished_at_utc=finished,
        report_title=report_title,
        trial_mode=trial_mode,
    )
    out_parent = os.path.dirname(os.path.abspath(out_path))
    if out_parent:
        os.makedirs(out_parent, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
