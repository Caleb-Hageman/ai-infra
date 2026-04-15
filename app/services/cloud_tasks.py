# Purpose: Enqueue HTTP targets on Google Cloud Tasks for async ingest (Cloud Run worker + OIDC).

from __future__ import annotations

import json
import os
from typing import Any

from google.cloud import tasks_v2

_client: tasks_v2.CloudTasksClient | None = None


def _get_client() -> tasks_v2.CloudTasksClient:
    global _client
    if _client is None:
        _client = tasks_v2.CloudTasksClient()
    return _client


def _oidc_service_account_email() -> str:
    return (
        os.getenv("CLOUD_TASKS_OIDC_SA_EMAIL")
        or os.getenv("SERVICE_ACCOUNT_EMAIL")
        or ""
    )


def enqueue_ingest(payload: dict[str, Any]) -> str:
    """POST JSON to INGEST_WORKER_URL via Cloud Tasks; uses OIDC so Cloud Run can verify the caller."""
    project = os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT") or ""
    if not project:
        raise RuntimeError("Set GCP_PROJECT or GOOGLE_CLOUD_PROJECT for Cloud Tasks.")

    worker_url = os.getenv("INGEST_WORKER_URL") or ""
    if not worker_url:
        raise RuntimeError("Set INGEST_WORKER_URL to the ingest worker HTTPS URL.")

    sa_email = _oidc_service_account_email()
    if not sa_email:
        raise RuntimeError(
            "Set CLOUD_TASKS_OIDC_SA_EMAIL or SERVICE_ACCOUNT_EMAIL for the task OIDC token.",
        )

    location = os.getenv("CLOUD_TASKS_LOCATION", "us-east1")
    queue_id = os.getenv("CLOUD_TASKS_QUEUE", "ingest-queue")
    audience = os.getenv("CLOUD_TASKS_OIDC_AUDIENCE") or worker_url

    client = _get_client()
    parent = client.queue_path(project, location, queue_id)

    body = json.dumps(payload, default=str).encode("utf-8")
    task: dict[str, Any] = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": worker_url,
            "headers": {"Content-Type": "application/json"},
            "body": body,
            "oidc_token": {
                "service_account_email": sa_email,
                "audience": audience,
            },
        }
    }

    response = client.create_task(request={"parent": parent, "task": task})
    return response.name


def try_enqueue_ingest(payload: dict[str, Any]) -> bool:
    """
    Enqueue a Cloud Task immediately when configuration is present.
    Returns False if Cloud Tasks is disabled or env is incomplete (caller runs in-process ingest).
    """
    if os.getenv("INGEST_USE_CLOUD_TASKS", "true").lower() not in ("1", "true", "yes"):
        return False
    try:
        enqueue_ingest(payload)
        return True
    except RuntimeError:
        return False
