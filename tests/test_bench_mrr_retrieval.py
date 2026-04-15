# Purpose: Unit tests for bench.mrr_retrieval (live chunk eval).

import uuid
from datetime import datetime, timezone

import httpx

from bench.mrr_retrieval import (
    EvalItem,
    RowOutcome,
    build_eval_items,
    collect_chunks_live_from_api,
    format_report_md,
    rank_and_rr,
    run_eval,
)


def test_rank_and_rr():
    a = uuid.uuid4()
    b = uuid.uuid4()
    results = [
        {"chunk_id": str(a), "content": ""},
        {"chunk_id": str(b), "content": ""},
    ]
    rank, rr = rank_and_rr(results, b)
    assert rank == 2
    assert rr == 0.5


def test_build_eval_items():
    cid = uuid.uuid4()
    did = uuid.uuid4()
    flat = [
        {
            "id": cid,
            "content": "alpha beta gamma delta",
            "document_id": did,
            "doc_title": "doc",
        }
    ]
    items = build_eval_items(flat, max_chunks=1, query_chars=10, seed=None)
    assert len(items) == 1
    assert items[0].gold_chunk_id == cid
    assert "alpha beta" in items[0].query


def test_collect_chunks_live_from_api_mock():
    doc_id = uuid.uuid4()
    ch_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.path
        if p.endswith("/chunks"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": str(ch_id),
                        "content": "hello from indexed chunk",
                        "document_id": str(doc_id),
                        "chunk_index": 0,
                    }
                ],
            )
        return httpx.Response(200, json=[{"id": str(doc_id), "title": "Doc A"}])

    transport = httpx.MockTransport(handler)
    pid = uuid.uuid4()
    with httpx.Client(transport=transport, timeout=httpx.Timeout(10.0)) as client:
        flat = collect_chunks_live_from_api(
            base_url="http://example.test",
            api_key="k",
            project_id=pid,
            max_documents=None,
            collect_cap=100,
            http_client=client,
        )
    assert len(flat) == 1
    assert uuid.UUID(str(flat[0]["id"])) == ch_id


def test_run_eval_mock():
    hit_id = uuid.uuid4()
    items = [EvalItem(id="1", label="A", query="q1", gold_chunk_id=hit_id)]

    def handler(request: httpx.Request) -> httpx.Response:
        body = {
            "project_id": str(uuid.uuid4()),
            "query": "q1",
            "results": [
                {
                    "chunk_id": str(hit_id),
                    "document_id": str(uuid.uuid4()),
                    "chunk_index": 0,
                    "content": "c",
                    "score": 0.9,
                    "source_file": "f",
                    "gcs_uri": "gs://x",
                    "chunk_length": 1,
                }
            ],
            "total": 1,
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, timeout=httpx.Timeout(10.0)) as client:
        rows, errs = run_eval(
            base_url="http://example.test",
            api_key="k",
            project_id=uuid.uuid4(),
            items=items,
            top_k=5,
            client_timeout_sec=10.0,
            http_client=client,
        )
    assert not errs
    assert len(rows) == 1
    assert rows[0].rank_display == "1"
    assert rows[0].rr == 1.0


def test_format_report_md():
    rows = [
        RowOutcome(item_id="1", label="L", rank_display="1", rr=1.0, note="hit"),
        RowOutcome(item_id="2", label="M", rank_display="—", rr=0.0, note="miss"),
    ]
    pid = uuid.uuid4()
    md = format_report_md(
        rows=rows,
        base_url="https://api.example.com",
        project_id=pid,
        top_k=5,
        threshold=0.7,
        context_lines=["- **Test:** unit"],
        embedding_note="test-embed",
        run_started_utc=datetime(2026, 1, 1, tzinfo=timezone.utc),
        run_finished_utc=datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc),
    )
    assert "# MRR" in md
    assert "**MODE:**" in md
    assert "`live`" in md
    assert "| Id | Label |" in md
    assert "`0.500`" in md
    assert "Embedding / chunking note" in md
