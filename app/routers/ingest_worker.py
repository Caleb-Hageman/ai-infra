# Purpose: POST /ingest-worker — Cloud Tasks invokes this to run process_uploaded_document.

import logging
import os

from fastapi import APIRouter, HTTPException, Request

from app.db import async_session
from app.schemas.ingest_worker import IngestWorkerRequest
from app.services.ingest_pipeline import process_uploaded_document

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingest-worker"])


def _require_cloud_tasks_or_dev(request: Request) -> None:
    if os.getenv("INGEST_WORKER_SKIP_AUTH", "").lower() in ("1", "true", "yes"):
        return
    if not request.headers.get("X-CloudTasks-TaskName"):
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/ingest-worker")
async def run_ingest_worker(body: IngestWorkerRequest, request: Request):
    _require_cloud_tasks_or_dev(request)
    async with async_session() as session:
        await process_uploaded_document(
            session,
            document_id=body.document_id,
            gcs_path=body.gcs_path,
            suffix=body.suffix,
            chunk_size=body.chunk_size,
            chunk_overlap=body.chunk_overlap,
        )
    return {"status": "ok", "document_id": str(body.document_id)}
