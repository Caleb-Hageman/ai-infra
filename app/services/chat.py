# Purpose: Chat completion via vLLM for POST /api/v1/chat.

import httpx

from app.config import VLLM_BASE_URL, VLLM_MODEL, VLLM_TIMEOUT


async def generate_response(
    session,
    team_id,
    project_id,
    question: str,
    system_prompt: str | None,
) -> tuple[str, list]:
    prompt = question
    if system_prompt:
        prompt = f"{system_prompt}\n\n{question}"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{VLLM_BASE_URL.rstrip('/')}/v1/chat/completions",
                json={
                    "model": VLLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=VLLM_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data["choices"][0]["message"]["content"]
            return (answer, [])
    except (httpx.HTTPError, KeyError) as e:
        raise RuntimeError(f"vLLM request failed: {e}") from e
