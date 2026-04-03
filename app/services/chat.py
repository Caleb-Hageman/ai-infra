# Purpose: RAG chat completion via vLLM for POST /api/v1/chat.
# When project_id is set, retrieves relevant chunks and injects them as context.

import asyncio
import logging
import os
import time
from functools import lru_cache
from uuid import UUID

import httpx

from app.config import DEFAULT_TOP_K, VLLM_BASE_URL, VLLM_MODEL, VLLM_TIMEOUT
from app.services import query as query_service
from app.services import gcs

logger = logging.getLogger(__name__)

CHAT_TOP_K = int(os.getenv("CHAT_TOP_K", str(DEFAULT_TOP_K)))
VLLM_MAX_RETRIES = int(os.getenv("VLLM_MAX_RETRIES", "2"))

# Cache vLLM ID token headers briefly to avoid redundant metadata server / token fetches on hot path.
_ID_TOKEN_CACHE_TTL_S = float(os.getenv("ID_TOKEN_CACHE_TTL_S", "300"))
_id_token_cache_mono: float = 0.0
_id_token_cache_value: dict[str, str] | None = None

def _get_id_token_headers() -> dict[str, str]:
    """Fetch GCP identity token for Cloud Run service-to-service auth. Returns empty dict if not applicable."""
    base = VLLM_BASE_URL.rstrip("/")
    if "run.app" not in base:
        return {}
    try:
        import google.auth.transport.requests
        import google.oauth2.id_token

        request = google.auth.transport.requests.Request()
        token = google.oauth2.id_token.fetch_id_token(request, base)
        return {"Authorization": f"Bearer {token}"}
    except Exception as e:
        logger.warning("Could not fetch identity token for vLLM: %s", e)
        return {}


def _cached_get_id_token_headers() -> dict[str, str]:
    """Same as _get_id_token_headers, with a short process-local TTL."""
    global _id_token_cache_mono, _id_token_cache_value
    now = time.monotonic()
    if (
        _id_token_cache_value is not None
        and now - _id_token_cache_mono < _ID_TOKEN_CACHE_TTL_S
    ):
        return _id_token_cache_value
    h = _get_id_token_headers()
    _id_token_cache_mono = now
    _id_token_cache_value = h if h else None
    return h if h else {}


@lru_cache(maxsize=128)
def _signed_url_for_citation(gcs_uri: str) -> str | None:
    """Process-local cache for citation GET URLs (same chunk may repeat across turns)."""
    return gcs.generate_signed_url(gcs_uri)

async def warmup_vllm() -> None:
    """Minimal completion to wake cold vLLM; awaited from a background task during /warmup."""
    id_headers = await asyncio.to_thread(_cached_get_id_token_headers)
    base = VLLM_BASE_URL.rstrip("/")
    chat_payload = {
        "model": VLLM_MODEL,
        "messages": [{"role": "user", "content": "."}],
        "max_tokens": 1,
    }
    for attempt in range(VLLM_MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{base}/v1/chat/completions",
                    json=chat_payload,
                    headers=id_headers,
                    timeout=VLLM_TIMEOUT,
                )
                if resp.status_code == 404:
                    resp = await client.post(
                        f"{base}/v1/completions",
                        json={
                            "model": VLLM_MODEL,
                            "prompt": ".",
                            "max_tokens": 1,
                        },
                        headers=id_headers,
                        timeout=VLLM_TIMEOUT,
                    )
                resp.raise_for_status()
                return
        except httpx.ReadTimeout:
            if attempt < VLLM_MAX_RETRIES:
                wait = 10 * (attempt + 1)
                logger.warning(
                    "vLLM warmup ReadTimeout (attempt %s/%s), retrying in %ss",
                    attempt + 1,
                    VLLM_MAX_RETRIES + 1,
                    wait,
                )
                await asyncio.sleep(wait)
            else:
                raise

async def generate_response(
    session,
    team_id,
    project_id: UUID | None,
    question: str,
    system_prompt: str | None,
) -> tuple[str, list]:
    citations: list[dict] = []
    context_parts: list[str] = []
    id_headers: dict[str, str] = {}
    matches: list = []

    if project_id:
        token_task = asyncio.create_task(asyncio.to_thread(_cached_get_id_token_headers))
        search_task = asyncio.create_task(
            query_service.execute_similarity_search(
                session=session,
                project_id=project_id,
                query_text=question,
                top_k=CHAT_TOP_K,
            )
        )
        matches, id_headers = await asyncio.gather(search_task, token_task)
    elif team_id:
        token_task = asyncio.create_task(asyncio.to_thread(_cached_get_id_token_headers))
        search_task = asyncio.create_task(
            query_service.execute_similarity_search_for_team(
                session=session,
                team_id=team_id,
                query_text=question,
                top_k=CHAT_TOP_K,
            )
        )
        matches, id_headers = await asyncio.gather(search_task, token_task)

    if matches:
        signed_urls = await asyncio.gather(
            *[asyncio.to_thread(_signed_url_for_citation, m.gcs_uri) for m in matches]
        )
        for m, signed_url in zip(matches, signed_urls):
            context_parts.append(m.content)
            citations.append({
                "source": m.source_file or "",
                "content": m.content[:200] + ("..." if len(m.content) > 200 else ""),
                "url": signed_url,
                "score": m.score,
            })

    context = "\n\n---\n\n".join(context_parts) if context_parts else ""
    if context:
        prompt = (
            "Use the following context to answer the question. "
            "Base your answer only on the context. If the context does not contain relevant information, say so.\n\n"
            f"Context:\n{context}\n\nQuestion: {question}"
        )
    else:
        prompt = question

    if system_prompt:
        prompt = f"{system_prompt}\n\n{prompt}"

    try:
        if not id_headers:
            id_headers = await asyncio.to_thread(_cached_get_id_token_headers)
        if id_headers:
            logger.info("Using identity token for vLLM auth")
        else:
            logger.warning("No identity token for vLLM; request may be rejected (403)")

        base = VLLM_BASE_URL.rstrip("/")
        for attempt in range(VLLM_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        f"{base}/v1/chat/completions",
                        json={
                            "model": VLLM_MODEL,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                        headers=id_headers,
                        timeout=VLLM_TIMEOUT,
                    )
                    if resp.status_code == 404:
                        logger.info("vLLM /v1/chat/completions not found, falling back to /v1/completions")
                        resp = await client.post(
                            f"{base}/v1/completions",
                            json={
                                "model": VLLM_MODEL,
                                "prompt": prompt,
                                "max_tokens": 512,
                            },
                            headers=id_headers,
                            timeout=VLLM_TIMEOUT,
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        answer = data["choices"][0]["text"]
                        return (answer.strip(), citations)
                    resp.raise_for_status()
                    data = resp.json()
                    answer = data["choices"][0]["message"]["content"]
                    return (answer, citations)
            except httpx.ReadTimeout:
                if attempt < VLLM_MAX_RETRIES:
                    wait = 10 * (attempt + 1)
                    logger.warning("vLLM ReadTimeout (attempt %s/%s), retrying in %ss", attempt + 1, VLLM_MAX_RETRIES + 1, wait)
                    await asyncio.sleep(wait)
                else:
                    raise
    except httpx.HTTPStatusError as e:
        logger.error(
            "vLLM HTTP %s: %s",
            e.response.status_code,
            e.response.text[:500] if e.response.text else "(no body)",
        )
        raise RuntimeError(f"vLLM request failed: {e}") from e
    except (httpx.HTTPError, KeyError) as e:
        logger.exception("vLLM request failed")
        raise RuntimeError(f"vLLM request failed: {e}") from e
