# Purpose: RAG chat completion via vLLM for POST /api/v1/chat.
# When project_id is set, retrieves relevant chunks and injects them as context.

import asyncio
import logging
import os
from uuid import UUID

import httpx

from app.config import DEFAULT_TOP_K, VLLM_BASE_URL, VLLM_MODEL, VLLM_TIMEOUT
from app.services import query as query_service
from app.services import gcs

logger = logging.getLogger(__name__)

VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://localhost:8001")
VLLM_MODEL = os.getenv("VLLM_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")
VLLM_TIMEOUT = float(os.getenv("VLLM_TIMEOUT", "300"))
CHAT_TOP_K = int(os.getenv("CHAT_TOP_K", "5"))
CHAT_MIN_SCORE_DEFAULT = float(os.getenv("CHAT_MIN_SCORE_DEFAULT", "0.4"))
VLLM_MAX_RETRIES = int(os.getenv("VLLM_MAX_RETRIES", "2"))
ABSTAIN_ANSWER = "I don't have enough relevant context in your indexed documents to answer confidently."


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


async def generate_response(
    session,
    team_id,
    project_id: UUID | None,
    question: str,
    system_prompt: str | None,
    min_score: float | None = None,
) -> tuple[str, list]:
    citations: list[dict] = []
    context_parts: list[str] = []
    effective_min_score = min_score if min_score is not None else CHAT_MIN_SCORE_DEFAULT
    retrieval_attempted = False

    if project_id:
        retrieval_attempted = True
        matches = await query_service.execute_similarity_search(
            session=session,
            project_id=project_id,
            query_text=question,
            top_k=CHAT_TOP_K,
        )
        relevant_matches = [m for m in matches if m.score >= effective_min_score]
        logger.info(
            "chat_retrieval_filter scope=project top_k=%s min_score=%.4f raw_matches=%s kept_matches=%s",
            CHAT_TOP_K,
            effective_min_score,
            len(matches),
            len(relevant_matches),
        )
        for m in relevant_matches:
            context_parts.append(m.content)
            signed_url = gcs.generate_signed_url(m.gcs_uri)
            citations.append({
                "source": m.source_file or "",
                "content": m.content[:200] + ("..." if len(m.content) > 200 else ""),
                "url": signed_url,
                "score": m.score,
            })
    elif team_id:
        retrieval_attempted = True
        matches = await query_service.execute_similarity_search_for_team(
            session=session,
            team_id=team_id,
            query_text=question,
            top_k=CHAT_TOP_K,
        )
        relevant_matches = [m for m in matches if m.score >= effective_min_score]
        logger.info(
            "chat_retrieval_filter scope=team top_k=%s min_score=%.4f raw_matches=%s kept_matches=%s",
            CHAT_TOP_K,
            effective_min_score,
            len(matches),
            len(relevant_matches),
        )
        for m in relevant_matches:
            context_parts.append(m.content)
            signed_url = gcs.generate_signed_url(m.gcs_uri)
            citations.append({
                "source": m.source_file or "",
                "content": m.content[:200] + ("..." if len(m.content) > 200 else ""),
                "url": signed_url,
                "score": m.score,
            })
    # else: no project_id, no team_id → no RAG, plain chat

    if retrieval_attempted and not context_parts:
        return (ABSTAIN_ANSWER, [])

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
        id_headers = await asyncio.to_thread(_get_id_token_headers)
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
