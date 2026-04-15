# Purpose: POST /ingest-worker (Cloud Tasks target).

from unittest.mock import AsyncMock, patch
from uuid import uuid4

@patch("app.routers.ingest_worker.process_uploaded_document", new_callable=AsyncMock)
def test_ingest_worker_403_without_cloud_tasks_header(mock_proc, app_client):
    response = app_client.post(
        "/ingest-worker",
        json={
            "document_id": str(uuid4()),
            "gcs_path": "t/p/f.txt",
            "suffix": ".txt",
        },
    )
    assert response.status_code == 403
    mock_proc.assert_not_called()


@patch("app.routers.ingest_worker.process_uploaded_document", new_callable=AsyncMock)
def test_ingest_worker_200_with_dev_skip_and_body(mock_proc, app_client, monkeypatch):
    monkeypatch.setenv("INGEST_WORKER_SKIP_AUTH", "true")
    doc_id = uuid4()
    response = app_client.post(
        "/ingest-worker",
        json={
            "document_id": str(doc_id),
            "gcs_path": "team/proj/file.txt",
            "suffix": ".txt",
            "chunk_size": 256,
            "chunk_overlap": 50,
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["document_id"] == str(doc_id)
    mock_proc.assert_called_once()
    call_kw = mock_proc.call_args[1]
    assert call_kw["document_id"] == doc_id
    assert call_kw["gcs_path"] == "team/proj/file.txt"


@patch("app.routers.ingest_worker.process_uploaded_document", new_callable=AsyncMock)
def test_ingest_worker_200_with_cloud_tasks_header(mock_proc, app_client):
    doc_id = uuid4()
    response = app_client.post(
        "/ingest-worker",
        json={
            "document_id": str(doc_id),
            "gcs_path": "g",
            "suffix": ".pdf",
        },
        headers={"X-CloudTasks-TaskName": "projects/p/locations/l/queues/q/tasks/1"},
    )
    assert response.status_code == 200
    mock_proc.assert_called_once()
