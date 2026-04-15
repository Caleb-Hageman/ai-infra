# Purpose: Unit tests for bench.upload_latency (payload, mocked HTTP, report).

import uuid
from datetime import datetime, timezone

import httpx

from bench.upload_latency import (
    SingleRunResult,
    _make_text_payload,
    format_upload_report_md,
    run_matrix,
)


def test_make_text_payload_len():
    b = _make_text_payload(100)
    assert len(b) == 100


def test_format_upload_report_md_headline():
    pid = uuid.uuid4()
    matrix = {
        100: [
            SingleRunResult(10.0, None, 50.0, 1.0, 40.0, 5.0, None),
            SingleRunResult(12.0, None, 48.0, 1.0, 38.0, 5.0, None),
        ]
    }
    md = format_upload_report_md(
        matrix=matrix,
        base_url="https://x.example.com",
        project_id=pid,
        runs=2,
        discard_first=False,
        context_lines=["- **Test:** unit"],
        done_definition="test def",
        started_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        finished_utc=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
    )
    assert "# Upload latency" in md
    assert "legacy median **faster**" in md or "faster**" in md
    assert "| 100 |" in md


def test_run_matrix_mock_transport():
    sid = str(uuid.uuid4())

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path.endswith("/upload/init"):
            return httpx.Response(
                200,
                json={
                    "upload_url": "https://fake-gcs.example/put",
                    "session_id": sid,
                    "expires_in_seconds": 3600,
                    "gcs_path": "g/p",
                },
            )
        if request.method == "PUT" and request.url.host == "fake-gcs.example":
            return httpx.Response(200)
        if request.method == "POST" and path.endswith("/complete"):
            return httpx.Response(
                202,
                json={
                    "id": str(uuid.uuid4()),
                    "team_id": str(uuid.uuid4()),
                    "project_id": str(uuid.uuid4()),
                    "title": None,
                    "source_type": "upload",
                    "gcs_uri": None,
                    "status": "processing",
                    "ingestion_progress_percent": 0,
                    "chunk_count": 0,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                },
            )
        if request.method == "POST" and path.endswith("/upload"):
            return httpx.Response(
                201,
                json={
                    "id": str(uuid.uuid4()),
                    "team_id": str(uuid.uuid4()),
                    "project_id": str(uuid.uuid4()),
                    "title": None,
                    "source_type": "upload",
                    "gcs_uri": None,
                    "status": "ready",
                    "ingestion_progress_percent": 100,
                    "chunk_count": 1,
                    "created_at": "2026-01-01T00:00:00",
                    "updated_at": "2026-01-01T00:00:00",
                },
            )
        return httpx.Response(404, text=f"unhandled {request.method} {path}")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=httpx.Timeout(30.0)) as client:
        m = run_matrix(
            base_url="http://example.test",
            api_key="k",
            project_id=uuid.uuid4(),
            sizes_bytes=[64],
            runs=1,
            client_timeout_sec=30.0,
            content_type="text/plain",
            http_client=client,
        )
    assert 64 in m
    assert len(m[64]) == 1
    r = m[64][0]
    assert r.legacy_error is None
    assert r.async_error is None
    assert r.legacy_ms is not None
    assert r.async_wall_ms is not None
