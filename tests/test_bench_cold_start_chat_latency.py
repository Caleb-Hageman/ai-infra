# Purpose: Unit tests for bench.cold_start_chat_latency (trial loop and Markdown report).

import httpx

from bench.cold_start_chat_latency import (
    format_report_md,
    run_cold_trial,
)


def test_run_cold_trial_200_first_attempt():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/chat"
        assert "Bearer k" in request.headers.get("authorization", "")
        return httpx.Response(
            200,
            json={"status": "success", "answer": "pong", "citations": []},
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=httpx.Timeout(10.0)) as client:
        tr = run_cold_trial(
            base_url="http://example.test",
            api_key="k",
            body={"question": "ping"},
            client_timeout_sec=10.0,
            max_attempts=5,
            http_client=client,
        )
    assert tr.success is True
    assert tr.attempts == 1
    assert tr.total_ms >= 0.0


def test_run_cold_trial_retries_503_then_200():
    n = {"c": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        n["c"] += 1
        if n["c"] == 1:
            return httpx.Response(503)
        return httpx.Response(
            200,
            json={"status": "success", "answer": "ok", "citations": []},
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=httpx.Timeout(10.0)) as client:
        tr = run_cold_trial(
            base_url="http://example.test",
            api_key="k",
            body={"question": "ping"},
            client_timeout_sec=10.0,
            max_attempts=5,
            http_client=client,
        )
    assert tr.success is True
    assert tr.attempts == 2
    assert len(tr.attempt_details) == 2


def test_run_cold_trial_non_retryable_401():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=httpx.Timeout(10.0)) as client:
        tr = run_cold_trial(
            base_url="http://example.test",
            api_key="k",
            body={"question": "ping"},
            client_timeout_sec=10.0,
            max_attempts=5,
            http_client=client,
        )
    assert tr.success is False
    assert "401" in (tr.error or "")


def test_format_report_md_contains_table_and_definitions():
    from bench.cold_start_chat_latency import TrialRecord

    from datetime import datetime, timezone

    t1 = TrialRecord(
        trial_index=1,
        success=True,
        total_ms=1500.0,
        attempts=1,
        attempt_details=[],
    )
    t2 = TrialRecord(
        trial_index=2,
        success=True,
        total_ms=3200.0,
        attempts=2,
        attempt_details=[],
    )
    started = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 3, 31, 12, 30, 0, tzinfo=timezone.utc)
    md = format_report_md(
        trials=[t1, t2],
        base_url="https://api.example.com",
        context_lines=["- **Test:** unit"],
        client_timeout_sec=60.0,
        server_timeout_label="Cloud Run 300s",
        started_at_utc=started,
        finished_at_utc=finished,
    )
    assert "# Cold-start chat latency" in md
    assert "**Mean total latency" in md
    assert "| Trial | Total ms |" in md
    assert "| 1 | 1,500.0 |" in md
    assert "## Definitions" in md
    assert "60" in md
    assert "---" in md


def test_build_body_project_id_string_in_json():
    import uuid

    from bench.cold_start_chat_latency import _build_body

    pid = uuid.uuid4()
    b = _build_body("q", pid, None, None)
    assert b["question"] == "q"
    assert b["project_id"] == str(pid)
