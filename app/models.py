import enum
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from .db import Base


# ── Enums ────────────────────────────────────────────────────────────────────


class DocumentSourceType(str, enum.Enum):
    upload = "upload"
    url = "url"
    manual = "manual"


class DocumentStatus(str, enum.Enum):
    uploaded = "uploaded"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class IngestionStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ApiKeyStatus(str, enum.Enum):
    active = "active"
    revoked = "revoked"


# ── Tables ───────────────────────────────────────────────────────────────────


class Team(Base):
    __tablename__ = "teams"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))

    projects = relationship("Project", back_populates="team", cascade="all, delete-orphan")
    api_keys = relationship("ApiKey", back_populates="team", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="team", cascade="all, delete-orphan")


class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))

    team = relationship("Team", back_populates="projects")
    documents = relationship("Document", back_populates="project", cascade="all, delete-orphan")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    key_hash = Column(Text, nullable=False)
    status = Column(
        Enum(ApiKeyStatus, name="api_key_status", create_type=True),
        nullable=False,
        server_default=text("'active'"),
    )
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))
    revoked_at = Column(DateTime, nullable=True)

    team = relationship("Team", back_populates="api_keys")


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(Text, nullable=True)
    source_type = Column(
        Enum(DocumentSourceType, name="document_source_type", create_type=True),
        nullable=False,
    )
    gcs_uri = Column(Text, nullable=True)
    mime_type = Column(Text, nullable=True)
    status = Column(
        Enum(DocumentStatus, name="document_status", create_type=True),
        nullable=False,
        server_default=text("'uploaded'"),
    )
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime, nullable=False, server_default=text("now()"))

    team = relationship("Team", back_populates="documents")
    project = relationship("Project", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")
    ingestion_jobs = relationship("IngestionJob", back_populates="document", cascade="all, delete-orphan")


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    status = Column(
        Enum(IngestionStatus, name="ingestion_status", create_type=True),
        nullable=False,
        server_default=text("'queued'"),
    )
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    chunks_created = Column(Integer, nullable=True)
    embedding_model = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))

    document = relationship("Document", back_populates="ingestion_jobs")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1536))
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    char_start = Column(Integer, nullable=True)
    char_end = Column(Integer, nullable=True)
    token_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))

    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_order"),
        Index(
            "idx_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )


class QueryLog(Base):
    __tablename__ = "query_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams.id"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id"), nullable=False)
    api_key_id = Column(UUID(as_uuid=True), ForeignKey("api_keys.id"), nullable=True)
    question_hash = Column(Text, nullable=False)
    used_rag = Column(Boolean, nullable=False)
    top_k = Column(Integer, nullable=True)
    model = Column(Text, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=text("now()"))

    citations = relationship("QueryCitation", back_populates="query", cascade="all, delete-orphan")


class QueryCitation(Base):
    __tablename__ = "query_citations"

    query_id = Column(UUID(as_uuid=True), ForeignKey("query_logs.id", ondelete="CASCADE"), primary_key=True)
    chunk_id = Column(UUID(as_uuid=True), ForeignKey("document_chunks.id"), primary_key=True)
    rank = Column(Integer, nullable=False)
    score = Column(Float, nullable=True)

    query = relationship("QueryLog", back_populates="citations")
    chunk = relationship("DocumentChunk")

