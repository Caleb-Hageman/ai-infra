# Purpose: Insert service unit tests (insert_document_chunks).

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.insert import insert_document_chunks


def _valid_chunk(content: str = "chunk text", idx: int = 0, **meta) -> dict:
    return {
        "chunk_index": idx,
        "content": content,
        "embedding": [0.1] * 1536,
        **meta,
    }


async def test_insert_document_chunks_returns_ids():
    doc_id = uuid4()
    chunk_ids = [uuid4(), uuid4()]

    session = MagicMock()
    session.add_all = MagicMock()
    session.flush = AsyncMock()

    def _flush():
        for i, obj in enumerate(session.add_all.call_args[0][0]):
            if getattr(obj, "id", None) is None:
                obj.id = chunk_ids[i]

    session.flush.side_effect = lambda: _flush() or None
    session.commit = AsyncMock(return_value=None)

    chunks = [
        _valid_chunk("first", 0),
        _valid_chunk("second", 1),
    ]
    result = await insert_document_chunks(session, document_id=doc_id, chunks=chunks)

    assert result == chunk_ids
    session.add_all.assert_called_once()
    session.flush.assert_called_once()
    session.commit.assert_called_once()


async def test_insert_document_chunks_commit_false():
    doc_id = uuid4()
    cid = uuid4()

    session = MagicMock()
    session.add_all = MagicMock()
    session.flush = AsyncMock(
        side_effect=lambda: setattr(
            session.add_all.call_args[0][0][0], "id", cid
        ) or None
    )
    session.commit = AsyncMock()

    result = await insert_document_chunks(
        session, document_id=doc_id, chunks=[_valid_chunk()], commit=False
    )

    assert result == [cid]
    session.commit.assert_not_called()


async def test_insert_document_chunks_with_optional_metadata():
    doc_id = uuid4()
    cid = uuid4()

    session = MagicMock()
    session.add_all = MagicMock()
    session.flush = AsyncMock(
        side_effect=lambda: setattr(
            session.add_all.call_args[0][0][0], "id", cid
        ) or None
    )
    session.commit = AsyncMock(return_value=None)

    chunks = [
        _valid_chunk(
            "page 1",
            0,
            page_start=1,
            page_end=2,
            char_start=0,
            char_end=100,
            token_count=25,
        ),
    ]
    await insert_document_chunks(session, document_id=doc_id, chunks=chunks)

    added = session.add_all.call_args[0][0]
    assert len(added) == 1
    c = added[0]
    assert c.document_id == doc_id
    assert c.chunk_index == 0
    assert c.content == "page 1"
    assert c.page_start == 1
    assert c.page_end == 2
    assert c.char_start == 0
    assert c.char_end == 100
    assert c.token_count == 25


async def test_insert_document_chunks_accepts_none_embedding():
    doc_id = uuid4()
    cid = uuid4()

    session = MagicMock()
    session.add_all = MagicMock()
    session.flush = AsyncMock(
        side_effect=lambda: setattr(
            session.add_all.call_args[0][0][0], "id", cid
        ) or None
    )
    session.commit = AsyncMock(return_value=None)

    chunks = [{"chunk_index": 0, "content": "no emb", "embedding": None}]
    result = await insert_document_chunks(session, document_id=doc_id, chunks=chunks)

    assert result == [cid]
    added = session.add_all.call_args[0][0]
    assert added[0].embedding is None


async def test_insert_document_chunks_rejects_wrong_embedding_dim():
    session = MagicMock()

    chunks = [
        {"chunk_index": 0, "content": "bad", "embedding": [0.1] * 512},
    ]

    with pytest.raises(ValueError, match="Embedding must be length 1536, got 512"):
        await insert_document_chunks(session, document_id=uuid4(), chunks=chunks)

    session.add_all.assert_not_called()


async def test_insert_document_chunks_integrity_error_rollbacks_and_reraises():
    doc_id = uuid4()

    session = MagicMock()
    session.add_all = MagicMock()
    session.flush = AsyncMock(side_effect=IntegrityError("x", "y", "z"))
    session.rollback = AsyncMock(return_value=None)

    with pytest.raises(IntegrityError):
        await insert_document_chunks(
            session, document_id=doc_id, chunks=[_valid_chunk()]
        )

    session.rollback.assert_called_once()
