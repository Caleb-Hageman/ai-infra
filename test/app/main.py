import os
import tempfile
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from app.rag import RAGService

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
rag: RAGService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global rag
    logger.info("Starting up — loading embedding model & connecting to DB...")
    rag = RAGService()
    await rag.setup()
    logger.info("Ready.")
    yield
    logger.info("Shutting down...")
    rag.close()


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="RAG API",
    description="Ingest documents and search them with semantic similarity via pgvector.",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Schemas ───────────────────────────────────────────────────────────────────
class SearchResult(BaseModel):
    chunk_id: int
    text: str
    similarity: float
    source_file: str
    chunk_length: int


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    total: int


class IngestResponse(BaseModel):
    message: str
    source_file: str
    chunks_created: int
    embedding_dimension: int


class StatsResponse(BaseModel):
    total_chunks: int
    total_sources: int
    avg_chunk_length: float
    min_chunk_length: int
    max_chunk_length: int


class DeleteResponse(BaseModel):
    message: str
    source_file: str
    chunks_deleted: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Liveness check."""
    return {"status": "ok"}


@app.post("/ingest", response_model=IngestResponse, status_code=201)
async def ingest(
    file: UploadFile = File(..., description="PDF or text/markdown file to ingest"),
    chunk_size: int = Query(2000, ge=100, le=8000, description="Characters per chunk"),
    chunk_overlap: int = Query(200, ge=0, le=1000, description="Overlap between chunks"),
):
    """
    Upload a document (PDF or text), chunk it, embed it, and store in pgvector.
    Supported formats: .pdf, .txt, .md, .markdown
    """
    allowed = {".pdf", ".txt", ".md", ".markdown"}
    suffix = Path(file.filename).suffix.lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{suffix}'. Allowed: {allowed}",
        )

    # Save upload to a temp file so the pipeline can read it
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        chunks_created, dim = await rag.ingest(
            file_path=tmp_path,
            original_name=file.filename,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    finally:
        os.unlink(tmp_path)

    return IngestResponse(
        message="Document ingested successfully.",
        source_file=file.filename,
        chunks_created=chunks_created,
        embedding_dimension=dim,
    )


@app.get("/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, description="Natural language search query"),
    top_k: int = Query(5, ge=1, le=50, description="Number of results to return"),
    source: Optional[str] = Query(None, description="Filter by source filename"),
):
    """
    Semantic search across all ingested documents.
    Returns the most relevant chunks ranked by cosine similarity.
    """
    results = await rag.search(query=q, top_k=top_k, source_filter=source)

    return SearchResponse(
        query=q,
        results=[
            SearchResult(
                chunk_id=r["chunk_id"],
                text=r["text"],
                similarity=round(r["similarity"], 4),
                source_file=r["source_file"],
                chunk_length=r["chunk_length"],
            )
            for r in results
        ],
        total=len(results),
    )


@app.get("/stats", response_model=StatsResponse)
async def stats():
    """Return statistics about the vector store."""
    s = await rag.stats()
    return StatsResponse(**s)


@app.delete("/document", response_model=DeleteResponse)
async def delete_document(
    source: str = Query(..., description="Exact source filename to delete"),
):
    """
    Delete all chunks belonging to a given source file.
    Use the same filename you uploaded (e.g. diabetes-clean.md).
    """
    deleted = await rag.delete(source_file=source)
    if deleted == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No chunks found for source '{source}'.",
        )

    return DeleteResponse(
        message="Document deleted successfully.",
        source_file=source,
        chunks_deleted=deleted,
    )
