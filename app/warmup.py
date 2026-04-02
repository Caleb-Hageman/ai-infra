import asyncio
import logging
from typing import Any

from sqlalchemy import text

from app.config import EMBEDDING_DIM
from app.db import engine
from app.services.chat import warmup_vllm
from app.services.rag import rag_service

logger = logging.getLogger(__name__)


async def _vllm_warmup_background() -> None:
    try:
        await warmup_vllm()
    except Exception:
        logger.exception("Background vLLM warmup failed")


async def warmup_dependencies() -> dict[str, Any]:
    """Ping DB, load embedding model, kick off vLLM request without waiting for it."""
    out: dict[str, Any] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        out["database"] = {"ok": True}
    except Exception as e:
        logger.exception("Warmup: database check failed")
        out["database"] = {"ok": False, "error": str(e)}

    try:
        await rag_service.ensure_dimension(EMBEDDING_DIM)
        out["embeddings"] = {
            "ok": True,
            "model_dim": rag_service.embedding_dim,
            "expected_dim": EMBEDDING_DIM,
        }
    except Exception as e:
        logger.exception("Warmup: embedding model init failed")
        out["embeddings"] = {"ok": False, "error": str(e)}

    try:
        asyncio.create_task(_vllm_warmup_background())
        out["vllm"] = {"ok": True, "kickstarted": True}
    except Exception as e:
        logger.exception("Warmup: could not schedule vLLM kickoff")
        out["vllm"] = {"ok": False, "error": str(e)}

    return out


def warmup_all_ok(status: dict[str, Any]) -> bool:
    """True when DB and embeddings are ready and vLLM kickoff was scheduled."""
    return bool(
        status.get("database", {}).get("ok")
        and status.get("embeddings", {}).get("ok")
        and status.get("vllm", {}).get("ok")
    )
