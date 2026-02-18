"""
RAG Service — async wrapper around the chunker, embedder, and pgvector store.
All blocking CPU/IO work runs in a thread pool so FastAPI stays non-blocking.
"""

import asyncio
import logging
import os
from functools import partial
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2.extras import execute_values
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

logger = logging.getLogger(__name__)

# ── Config (override via environment variables) ───────────────────────────────
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "rag_db")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "ai_infra2026")
DB_TABLE = os.getenv("DB_TABLE", "document_embeddings")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "mixedbread-ai/mxbai-embed-large-v1")
DEVICE = os.getenv("DEVICE", "cpu")


class RAGService:
    """Async-friendly service that orchestrates chunking, embedding, and storage."""

    def __init__(self):
        self.model: HuggingFaceEmbeddings | None = None
        self.conn: psycopg2.extensions.connection | None = None
        self.embedding_dim: int = 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def setup(self):
        """Load model and connect to database (runs at startup)."""
        loop = asyncio.get_event_loop()

        # Load embedding model in thread pool (it's CPU-bound)
        logger.info("Loading embedding model: %s", EMBEDDING_MODEL)
        self.model = await loop.run_in_executor(None, self._load_model)

        # Probe embedding dimension
        sample = await loop.run_in_executor(
            None, self.model.embed_query, "dimension probe"
        )
        self.embedding_dim = len(sample)
        logger.info("Embedding dimension: %d", self.embedding_dim)

        # Connect to PostgreSQL
        logger.info("Connecting to PostgreSQL at %s:%d/%s", DB_HOST, DB_PORT, DB_NAME)
        self.conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
        logger.info("Connected to PostgreSQL")

        # Ensure extension + table exist
        self._setup_db()

    def close(self):
        if self.conn:
            self.conn.close()

    # ── Public async API ──────────────────────────────────────────────────────

    async def ingest(
        self,
        file_path: str,
        original_name: str,
        chunk_size: int = 2000,
        chunk_overlap: int = 200,
    ) -> tuple[int, int]:
        """
        Load → chunk → embed → store.
        Returns (chunks_created, embedding_dimension).
        """
        loop = asyncio.get_event_loop()

        fn = partial(
            self._ingest_sync,
            file_path=file_path,
            original_name=original_name,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return await loop.run_in_executor(None, fn)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        source_filter: Optional[str] = None,
    ) -> list[dict]:
        """Embed the query and return top_k similar chunks."""
        loop = asyncio.get_event_loop()
        fn = partial(self._search_sync, query=query, top_k=top_k, source_filter=source_filter)
        return await loop.run_in_executor(None, fn)

    async def stats(self) -> dict:
        """Return database statistics."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._stats_sync)

    async def delete(self, source_file: str) -> int:
        """Delete all chunks for a source file. Returns number of rows deleted."""
        loop = asyncio.get_event_loop()
        fn = partial(self._delete_sync, source_file=source_file)
        return await loop.run_in_executor(None, fn)

    # ── Private sync implementations (run in thread pool) ────────────────────

    def _load_model(self) -> HuggingFaceEmbeddings:
        return HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": DEVICE},
            encode_kwargs={"normalize_embeddings": True},
        )

    def _setup_db(self):
        """Create pgvector extension and table if they don't exist."""
        with self.conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {DB_TABLE} (
                    id           SERIAL PRIMARY KEY,
                    chunk_id     INTEGER,
                    text         TEXT NOT NULL,
                    embedding    vector({self.embedding_dim}) NOT NULL,
                    source_file  TEXT,
                    chunk_length INTEGER,
                    start_index  INTEGER,
                    total_chunks INTEGER,
                    metadata     JSONB,
                    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # HNSW index for fast cosine similarity search
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS {DB_TABLE}_embedding_idx
                ON {DB_TABLE}
                USING hnsw (embedding vector_cosine_ops);
            """)
            cur.execute(f"""
                CREATE INDEX IF NOT EXISTS {DB_TABLE}_source_idx
                ON {DB_TABLE} (source_file);
            """)
        self.conn.commit()
        logger.info("Database table '%s' is ready", DB_TABLE)

    def _extract_text(self, file_path: str, original_name: str) -> str:
        """Extract raw text from PDF or plain-text file."""
        with open(file_path, "rb") as f:
            is_pdf = f.read(8).startswith(b"%PDF-")

        if is_pdf:
            reader = PdfReader(file_path)
            return "\n\n".join(p.extract_text() or "" for p in reader.pages)

        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    def _chunk_text(
        self,
        text: str,
        original_name: str,
        chunk_size: int,
        chunk_overlap: int,
    ):
        """Split text into overlapping chunks, respecting markdown structure."""
        
        separators = ["\n\n", "\n", ". ", " ", ""]

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=separators,
            is_separator_regex=False,
            add_start_index=True,
        )
        return splitter.create_documents([text])

    def _ingest_sync(
        self,
        file_path: str,
        original_name: str,
        chunk_size: int,
        chunk_overlap: int,
    ) -> tuple[int, int]:
        logger.info("Ingesting '%s'", original_name)

        text = self._extract_text(file_path, original_name)
        docs = self._chunk_text(text, original_name, chunk_size, chunk_overlap)
        total = len(docs)
        logger.info("Created %d chunks", total)

        texts = [d.page_content for d in docs]
        vectors = self.model.embed_documents(texts)
        logger.info("Embedded %d chunks", total)

        rows = [
            (
                i,                              # chunk_id
                doc.page_content,               # text
                vector,                         # embedding
                original_name,                  # source_file
                len(doc.page_content),          # chunk_length
                doc.metadata.get("start_index"),# start_index
                total,                          # total_chunks
                None,                           # metadata (extend as needed)
            )
            for i, (doc, vector) in enumerate(zip(docs, vectors))
        ]

        with self.conn.cursor() as cur:
            execute_values(
                cur,
                f"""
                INSERT INTO {DB_TABLE}
                    (chunk_id, text, embedding, source_file,
                     chunk_length, start_index, total_chunks, metadata)
                VALUES %s
                """,
                rows,
                page_size=100,
            )
        self.conn.commit()
        logger.info("Stored %d chunks for '%s'", total, original_name)

        return total, self.embedding_dim

    def _search_sync(
        self,
        query: str,
        top_k: int,
        source_filter: Optional[str],
    ) -> list[dict]:
        query_vec = self.model.embed_query(query)

        where = "WHERE source_file = %s" if source_filter else ""
        params: list = []
        if source_filter:
            params.append(source_filter)
        params += [query_vec, query_vec, top_k]

        sql = f"""
            SELECT
                chunk_id,
                text,
                source_file,
                chunk_length,
                1 - (embedding <=> %s::vector) AS similarity
            FROM {DB_TABLE}
            {where}
            ORDER BY embedding <=> %s::vector
            LIMIT %s;
        """

        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        return [
            {
                "chunk_id":    row[0],
                "text":        row[1],
                "source_file": row[2],
                "chunk_length":row[3],
                "similarity":  float(row[4]),
            }
            for row in rows
        ]

    def _stats_sync(self) -> dict:
        sql = f"""
            SELECT
                COUNT(*)            AS total_chunks,
                COUNT(DISTINCT source_file) AS total_sources,
                AVG(chunk_length)   AS avg_chunk_length,
                MIN(chunk_length)   AS min_chunk_length,
                MAX(chunk_length)   AS max_chunk_length
            FROM {DB_TABLE};
        """
        with self.conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()

        return {
            "total_chunks":     row[0],
            "total_sources":    row[1],
            "avg_chunk_length": float(row[2]) if row[2] else 0.0,
            "min_chunk_length": row[3] or 0,
            "max_chunk_length": row[4] or 0,
        }

    def _delete_sync(self, source_file: str) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {DB_TABLE} WHERE source_file = %s;",
                (source_file,),
            )
            deleted = cur.rowcount
        self.conn.commit()
        return deleted
