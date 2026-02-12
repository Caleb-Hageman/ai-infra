from pgvector.sqlalchemy import Vector
from sqlalchemy import Index

EMBEDDING_DIM = 3072  # adjust to your embedding model

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)

    chunk_index: Mapped[int] = mapped_column(Integer)
    
    # 🔥 The embedding column
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))

    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    text_preview: Mapped[str | None] = mapped_column(Text)
    token_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP, default=datetime.utcnow)

    document = relationship("Document", back_populates="chunks")


# 🔥 Vector index for ANN search (HNSW recommended)
Index(
    "ix_document_chunks_embedding",
    DocumentChunk.embedding,
    postgresql_using="hnsw",
    postgresql_with={"m": 16, "ef_construction": 64},
)


def insert_chunk(session, document_id, text, embedding_vector):
    chunk = DocumentChunk(
        document_id=document_id,
        chunk_index=0,
        embedding=embedding_vector,  # list[float]
        text_preview=text[:200],
        token_count=150,
    )

    session.add(chunk)
    session.commit()
