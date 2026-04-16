# Purpose: Unit tests for bench.query_retrieval_latency (POST /query timing and report).

import uuid
from datetime import datetime, timezone

import httpx

from bench.query_retrieval_latency import (
    QueryTrialRecord,
    format_report_md,
    run_query_trial,
)


def test_run_query_trial_200():
    pid = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/query/{pid}"
        assert "Bearer k" in request.headers.get("authorization", "")
        body = request.read().decode()
        assert "summarize" in body.lower() or "query" in body
        return httpx.Response(
            200,
            json={
                "project_id": str(pid),
                "query": "x",
                "results": [{"chunk_id": str(uuid.uuid4())}],
                "total": 1,
            },
        )

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=httpx.Timeout(10.0)) as client:
        tr = run_query_trial(
            base_url="http://example.test",
            project_id=pid,
            api_key="k",
            query_text="Summarize indexed docs.",
            top_k=5,
            source=None,
            client_timeout_sec=10.0,
            http_client=client,
        )
    assert tr.success is True
    assert tr.http_status == 200
    assert tr.total_results == 1
    assert tr.elapsed_ms >= 0.0


def test_format_report_md_contains_table():
    pid = uuid.uuid4()
    t1 = QueryTrialRecord(
        trial_index=1,
        success=True,
        elapsed_ms=42.0,
        http_status=200,
        total_results=3,
    )
    started = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 3, 31, 12, 1, 0, tzinfo=timezone.utc)
    md = format_report_md(
        trials=[t1],
        base_url="https://api.example.com",
        project_id=pid,
        query_text="hello world",
        top_k=5,
        context_lines=["- **Test:** unit"],
        client_timeout_sec=60.0,
        started_at_utc=started,
        finished_at_utc=finished,
    )
    assert "# Query retrieval latency (no chat)" in md
    assert "| Trial | Latency ms |" in md
    assert "42.0" in md
    assert "no chat" in md.lower() or "no LLM" in md.lower()


def test_format_report_md_title_includes_no_chat():
    pid = uuid.uuid4()
    tr = QueryTrialRecord(
        trial_index=1,
        success=False,
        elapsed_ms=0.0,
        http_status=401,
        total_results=None,
        error="HTTP 401",
    )
    md = format_report_md(
        trials=[tr],
        base_url="https://x.com",
        project_id=pid,
        query_text="q",
        top_k=5,
        context_lines=[],
        client_timeout_sec=30.0,
        started_at_utc=datetime.now(timezone.utc),
        finished_at_utc=datetime.now(timezone.utc),
    )
    assert "no chat" in md.lower()
