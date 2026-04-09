# Purpose: Chat service unit tests (generate_response request shape, retry logic).

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx

from app.services.chat import ABSTAIN_ANSWER, generate_response


@patch("app.services.chat.asyncio.sleep", new_callable=AsyncMock)
@patch("app.services.chat.httpx.AsyncClient")
async def test_generate_response_sends_correct_request_url_body_headers(mock_client_cls, mock_sleep):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": "answer"}}]}

    captured_url = []
    captured_json = []
    captured_headers = []

    async def capture_post(url, json=None, headers=None, **kwargs):
        captured_url.append(url)
        captured_json.append(json or {})
        captured_headers.append(headers if headers is not None else {})
        return mock_resp

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=capture_post)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client_cls.return_value = mock_client

    session = MagicMock()
    await generate_response(
        session=session,
        team_id=None,
        project_id=None,
        question="test question",
        system_prompt=None,
    )

    assert len(captured_url) == 1
    assert "/v1/chat/completions" in captured_url[0]
    assert captured_json[0]["model"]
    assert captured_json[0]["messages"] == [{"role": "user", "content": "test question"}]
    assert isinstance(captured_headers[0], dict)


@patch("app.services.chat.asyncio.sleep", new_callable=AsyncMock)
@patch("app.services.chat.httpx.AsyncClient")
async def test_generate_response_retries_on_read_timeout(mock_client_cls, mock_sleep):
    call_count = 0

    async def fail_then_succeed(url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise httpx.ReadTimeout("timeout")
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        return resp

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=fail_then_succeed)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client_cls.return_value = mock_client

    session = MagicMock()
    answer, _ = await generate_response(
        session=session,
        team_id=None,
        project_id=None,
        question="q",
        system_prompt=None,
    )

    assert answer == "ok"
    assert call_count == 3


@patch("app.services.chat.gcs.generate_signed_url", return_value="https://signed.example/url")
@patch("app.services.chat.asyncio.sleep", new_callable=AsyncMock)
@patch("app.services.chat.httpx.AsyncClient")
@patch("app.services.chat.gcs.generate_signed_url", return_value="https://example/signed")
@patch("app.services.chat.query_service.execute_similarity_search", new_callable=AsyncMock)
async def test_generate_response_with_rag_context_and_system_prompt(
    mock_search, _mock_signed, mock_client_cls, mock_sleep
):
    mock_search.return_value = [
        type(
            "M",
            (),
            {
                "content": "ctx",
                "source_file": "f.pdf",
                "score": 0.9,
                "gcs_uri": "gs://bucket/obj",
            },
        )(),
    ]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": "answer"}}]}

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client_cls.return_value = mock_client

    session = MagicMock()
    answer, citations = await generate_response(
        session=session,
        team_id=None,
        project_id=uuid4(),
        question="q",
        system_prompt="Be concise.",
    )

    assert answer == "answer"
    assert len(citations) == 1
    call_json = mock_client.post.call_args[1]["json"]
    assert "Be concise." in call_json["messages"][0]["content"]
    assert "Context:" in call_json["messages"][0]["content"]
    mock_search.assert_called_once()


@patch("app.services.chat.query_service.execute_similarity_search", new_callable=AsyncMock)
async def test_generate_response_abstains_when_scores_below_threshold(mock_search):
    mock_search.return_value = [
        type(
            "M",
            (),
            {
                "content": "weak ctx",
                "source_file": "f.pdf",
                "score": 0.2,
                "gcs_uri": "gs://bucket/f.pdf",
            },
        )(),
    ]
    session = MagicMock()
    answer, citations = await generate_response(
        session=session,
        team_id=None,
        project_id=uuid4(),
        question="q",
        system_prompt=None,
        min_score=None,
    )
    assert answer == ABSTAIN_ANSWER
    assert citations == []
    mock_search.assert_called_once()


@patch("app.services.chat.gcs.generate_signed_url", return_value="https://signed.example/url")
@patch("app.services.chat.query_service.execute_similarity_search", new_callable=AsyncMock)
async def test_generate_response_min_score_override_filters_chunks(mock_search, _mock_signed_url):
    mock_search.return_value = [
        type(
            "M",
            (),
            {
                "content": "a",
                "source_file": "a.pdf",
                "score": 0.5,
                "gcs_uri": "gs://bucket/a.pdf",
            },
        )(),
        type(
            "M",
            (),
            {
                "content": "b",
                "source_file": "b.pdf",
                "score": 0.85,
                "gcs_uri": "gs://bucket/b.pdf",
            },
        )(),
    ]
    session = MagicMock()
    with patch("app.services.chat.httpx.AsyncClient") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        mock_client = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        answer, citations = await generate_response(
            session=session,
            team_id=None,
            project_id=uuid4(),
            question="q",
            system_prompt=None,
            min_score=0.7,
        )
    assert answer == "ok"
    assert len(citations) == 1
    assert citations[0]["content"].startswith("b")
    assert citations[0]["score"] == 0.85


@patch("app.services.chat.asyncio.sleep", new_callable=AsyncMock)
@patch("app.services.chat.httpx.AsyncClient")
async def test_generate_response_404_fallback_to_completions(mock_client_cls, mock_sleep):
    resp_404 = MagicMock()
    resp_404.status_code = 404
    resp_ok = MagicMock()
    resp_ok.status_code = 200
    resp_ok.raise_for_status = MagicMock()
    resp_ok.json.return_value = {"choices": [{"text": " completion answer "}]}

    mock_client = MagicMock()
    mock_client.post = AsyncMock(side_effect=[resp_404, resp_ok])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client_cls.return_value = mock_client

    session = MagicMock()
    answer, _ = await generate_response(
        session=session, team_id=None, project_id=None, question="q", system_prompt=None
    )
    assert answer == "completion answer"
    assert mock_client.post.call_count == 2
