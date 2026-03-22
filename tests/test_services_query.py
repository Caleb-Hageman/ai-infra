# Purpose: Query service unit tests (execute_similarity_search with mocked session).

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.query import (
    execute_similarity_search,
    execute_similarity_search_for_source,
    execute_similarity_search_for_team,
)


def _fake_chunk_row(content: str = "chunk content", score: float = 0.95):
    chunk = MagicMock()
    chunk.id = uuid4()
    chunk.document_id = uuid4()
    chunk.chunk_index = 0
    chunk.content = content
    return chunk, "doc.pdf", 1 - score


@patch("app.services.query.rag_service.embed_query", new_callable=AsyncMock)
@patch("app.services.query.rag_service.ensure_dimension", new_callable=AsyncMock)
async def test_execute_similarity_search_returns_chunk_matches(mock_ensure, mock_embed):
    mock_embed.return_value = [0.1] * 1536

    project_id = uuid4()
    chunk, source_file, dist = _fake_chunk_row("hello world", 0.92)
    mock_result = MagicMock()
    mock_result.all.return_value = [(chunk, source_file, dist)]

    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    matches = await execute_similarity_search(session, project_id, "query", top_k=5)

    assert len(matches) == 1
    assert matches[0].content == "hello world"
    assert matches[0].score == 0.92
    assert matches[0].source_file == "doc.pdf"
    assert matches[0].chunk_length == 11
    mock_ensure.assert_called_once_with(1536)
    mock_embed.assert_called_once_with("query")
    session.execute.assert_called_once()


@patch("app.services.query.rag_service.embed_query", new_callable=AsyncMock)
@patch("app.services.query.rag_service.ensure_dimension", new_callable=AsyncMock)
async def test_execute_similarity_search_for_team_returns_matches(mock_ensure, mock_embed):
    mock_embed.return_value = [0.1] * 1536
    team_id = uuid4()
    chunk, source_file, dist = _fake_chunk_row("team chunk", 0.88)
    mock_result = MagicMock()
    mock_result.all.return_value = [(chunk, source_file, dist)]

    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    matches = await execute_similarity_search_for_team(
        session, team_id, "query", top_k=3
    )

    assert len(matches) == 1
    assert matches[0].content == "team chunk"
    assert matches[0].score == 0.88
    session.execute.assert_called_once()


@patch("app.services.query.rag_service.embed_query", new_callable=AsyncMock)
@patch("app.services.query.rag_service.ensure_dimension", new_callable=AsyncMock)
async def test_execute_similarity_search_for_source_returns_matches(mock_ensure, mock_embed):
    mock_embed.return_value = [0.1] * 1536
    project_id = uuid4()
    chunk, source_file, dist = _fake_chunk_row("source chunk", 0.91)
    mock_result = MagicMock()
    mock_result.all.return_value = [(chunk, source_file, dist)]

    session = MagicMock()
    session.execute = AsyncMock(return_value=mock_result)

    matches = await execute_similarity_search_for_source(
        session, project_id, "query", top_k=5, source_filter="doc.pdf"
    )

    assert len(matches) == 1
    assert matches[0].content == "source chunk"
    session.execute.assert_called_once()
