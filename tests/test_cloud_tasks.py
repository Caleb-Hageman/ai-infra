# Purpose: Cloud Tasks enqueue helper (mocked client).

from unittest.mock import MagicMock, patch

import pytest


def test_enqueue_ingest_requires_project(monkeypatch):
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("INGEST_WORKER_URL", "https://example/worker")
    monkeypatch.setenv("SERVICE_ACCOUNT_EMAIL", "sa@x.iam.gserviceaccount.com")

    from app.services import cloud_tasks as ct

    ct._client = None
    with pytest.raises(RuntimeError, match="GCP_PROJECT"):
        ct.enqueue_ingest({"document_id": "a"})


def test_enqueue_ingest_requires_worker_url(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT", "my-project")
    monkeypatch.delenv("INGEST_WORKER_URL", raising=False)
    monkeypatch.setenv("SERVICE_ACCOUNT_EMAIL", "sa@x.iam.gserviceaccount.com")

    from app.services import cloud_tasks as ct

    ct._client = None
    with pytest.raises(RuntimeError, match="INGEST_WORKER_URL"):
        ct.enqueue_ingest({"document_id": "a"})


def test_enqueue_ingest_requires_oidc_email(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT", "my-project")
    monkeypatch.setenv("INGEST_WORKER_URL", "https://example/worker")
    monkeypatch.delenv("CLOUD_TASKS_OIDC_SA_EMAIL", raising=False)
    monkeypatch.delenv("SERVICE_ACCOUNT_EMAIL", raising=False)

    from app.services import cloud_tasks as ct

    ct._client = None
    with pytest.raises(RuntimeError, match="OIDC"):
        ct.enqueue_ingest({"document_id": "a"})


def test_enqueue_ingest_calls_create_task(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT", "indigo-bedrock-487015-g2")
    monkeypatch.setenv("CLOUD_TASKS_LOCATION", "us-east1")
    monkeypatch.setenv("CLOUD_TASKS_QUEUE", "ingest-queue")
    monkeypatch.setenv("INGEST_WORKER_URL", "https://ingest-worker-xxxxx.run.app/ingest-worker")
    monkeypatch.setenv("SERVICE_ACCOUNT_EMAIL", "tasks-invoker@indigo-bedrock-487015-g2.iam.gserviceaccount.com")

    mock_client = MagicMock()
    mock_client.queue_path.return_value = (
        "projects/indigo-bedrock-487015-g2/locations/us-east1/queues/ingest-queue"
    )
    mock_resp = MagicMock()
    mock_resp.name = "projects/p/locations/l/queues/q/tasks/created"
    mock_client.create_task.return_value = mock_resp

    from app.services import cloud_tasks as ct

    ct._client = None
    with patch.object(ct, "_get_client", return_value=mock_client):
        name = ct.enqueue_ingest({"document_id": "550e8400-e29b-41d4-a716-446655440000"})

    assert name == mock_resp.name
    mock_client.queue_path.assert_called_once_with(
        "indigo-bedrock-487015-g2",
        "us-east1",
        "ingest-queue",
    )
    call_kw = mock_client.create_task.call_args[1]["request"]
    assert call_kw["parent"] == mock_client.queue_path.return_value
    task = call_kw["task"]
    assert task["http_request"]["url"] == "https://ingest-worker-xxxxx.run.app/ingest-worker"
    assert task["http_request"]["oidc_token"]["audience"] == task["http_request"]["url"]


def test_enqueue_ingest_uses_custom_oidc_audience_when_set(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT", "p")
    monkeypatch.setenv("INGEST_WORKER_URL", "https://worker.run.app/internal/ingest")
    monkeypatch.setenv("SERVICE_ACCOUNT_EMAIL", "sa@p.iam.gserviceaccount.com")
    monkeypatch.setenv("CLOUD_TASKS_OIDC_AUDIENCE", "https://worker.run.app")

    mock_client = MagicMock()
    mock_client.queue_path.return_value = "parent"
    mock_client.create_task.return_value = MagicMock(name="task-name")

    from app.services import cloud_tasks as ct

    ct._client = None
    with patch.object(ct, "_get_client", return_value=mock_client):
        ct.enqueue_ingest({})

    task = mock_client.create_task.call_args[1]["request"]["task"]
    assert task["http_request"]["oidc_token"]["audience"] == "https://worker.run.app"


def test_try_enqueue_ingest_false_when_disabled(monkeypatch):
    monkeypatch.setenv("INGEST_USE_CLOUD_TASKS", "false")

    from app.services import cloud_tasks as ct

    assert ct.try_enqueue_ingest({"document_id": "x"}) is False


def test_try_enqueue_ingest_false_when_env_incomplete(monkeypatch):
    monkeypatch.setenv("INGEST_USE_CLOUD_TASKS", "true")
    monkeypatch.delenv("GCP_PROJECT", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)

    from app.services import cloud_tasks as ct

    assert ct.try_enqueue_ingest({"document_id": "x"}) is False


def test_try_enqueue_ingest_true_when_enqueue_succeeds(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT", "p")
    monkeypatch.setenv("INGEST_WORKER_URL", "https://w/worker")
    monkeypatch.setenv("SERVICE_ACCOUNT_EMAIL", "sa@x.iam.gserviceaccount.com")

    mock_client = MagicMock()
    mock_client.queue_path.return_value = "parent"
    mock_client.create_task.return_value = MagicMock(name="t")

    from app.services import cloud_tasks as ct

    ct._client = None
    with patch.object(ct, "_get_client", return_value=mock_client):
        assert ct.try_enqueue_ingest({"document_id": "a"}) is True
