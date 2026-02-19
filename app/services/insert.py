from typing import Iterable, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models import DocumentChunk


EMBEDDING_DIM = 1536


def insert_document_chunks(
    db: Session,
    *,
    document_id: UUID,
    chunks: Iterable[dict],
    commit: bool = True,
) -> List[UUID]:
    """
    Insert multiple document chunks with embeddings and metadata.

    Each chunk dict must contain:
        - chunk_index (int)
        - content (str)
        - embedding (List[float]) length 1536

    Optional metadata:
        - page_start
        - page_end
        - char_start
        - char_end
        - token_count

    Returns:
        List of inserted chunk IDs
    """

    chunk_objects = []

    for chunk in chunks:
        embedding = chunk["embedding"]

        if embedding is not None and len(embedding) != EMBEDDING_DIM:
            raise ValueError(
                f"Embedding must be length {EMBEDDING_DIM}, got {len(embedding)}"
            )

        chunk_obj = DocumentChunk(
            document_id=document_id,
            chunk_index=chunk["chunk_index"],
            content=chunk["content"],
            embedding=embedding,
            page_start=chunk.get("page_start"),
            page_end=chunk.get("page_end"),
            char_start=chunk.get("char_start"),
            char_end=chunk.get("char_end"),
            token_count=chunk.get("token_count"),
        )

        chunk_objects.append(chunk_obj)

    try:
        db.add_all(chunk_objects)
        db.flush()  # ensures IDs are generated
        if commit:
            db.commit()
    except IntegrityError:
        db.rollback()
        raise

    return [chunk.id for chunk in chunk_objects]
