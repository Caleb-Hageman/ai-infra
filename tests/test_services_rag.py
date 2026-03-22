# Purpose: RAG service unit tests (chunk_text, _normalize_vector, extract_text, embed_documents).

import tempfile
from pathlib import Path

from app.services.rag import rag_service


def test_chunk_text_returns_chunks_with_expected_structure():
    text = "First paragraph.\n\nSecond paragraph. More text here."
    chunks = rag_service.chunk_text(
        text,
        chunk_size=50,
        chunk_overlap=10,
    )

    assert len(chunks) >= 1
    for chunk in chunks:
        assert "chunk_index" in chunk
        assert "content" in chunk
        assert "char_start" in chunk
        assert "char_end" in chunk
        assert "token_count" in chunk
        assert isinstance(chunk["content"], str)
        assert len(chunk["content"]) > 0


def test_chunk_text_respects_chunk_size():
    text = "A " * 100
    chunks = rag_service.chunk_text(
        text,
        chunk_size=20,
        chunk_overlap=0,
    )

    for chunk in chunks:
        assert len(chunk["content"]) <= 25


def test_normalize_vector_truncates_when_too_long():
    vec = [1.0] * 2000
    result = rag_service._normalize_vector(vec, 1536)
    assert len(result) == 1536
    assert result == [1.0] * 1536


def test_normalize_vector_pads_when_too_short():
    vec = [1.0] * 100
    result = rag_service._normalize_vector(vec, 1536)
    assert len(result) == 1536
    assert result[:100] == [1.0] * 100
    assert result[100:] == [0.0] * 1436


def test_normalize_vector_unchanged_when_exact_dim():
    vec = [0.5] * 1536
    result = rag_service._normalize_vector(vec, 1536)
    assert result == vec


def test_extract_text_txt():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Hello from text file.")
        path = f.name
    try:
        text = rag_service.extract_text(path)
        assert text == "Hello from text file."
    finally:
        Path(path).unlink(missing_ok=True)


async def test_embed_documents_empty_returns_empty():
    result = await rag_service.embed_documents([])
    assert result == []
