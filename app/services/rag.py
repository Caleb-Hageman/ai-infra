"""
RAG helper service for extraction, chunking, and embeddings.

This module keeps heavy operations off the event loop by running model calls
inside a thread pool via asyncio.run_in_executor.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.config import EMBEDDING_DIM, EMBEDDING_DEVICE, EMBEDDING_MODEL

logger = logging.getLogger(__name__)


class RAGService:
    def __init__(self) -> None:
        self._model: HuggingFaceEmbeddings | None = None
        self._model_lock = asyncio.Lock()
        self.embedding_dim: int | None = None

    async def _get_model(self) -> HuggingFaceEmbeddings:
        if self._model is not None:
            return self._model

        async with self._model_lock:
            if self._model is None:
                loop = asyncio.get_running_loop()
                self._model = await loop.run_in_executor(None, self._load_model)
                probe = await loop.run_in_executor(
                    None, self._model.embed_query, "dimension probe"
                )
                self.embedding_dim = len(probe)
        return self._model

    def _load_model(self) -> HuggingFaceEmbeddings:
        return HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={"device": EMBEDDING_DEVICE},
            encode_kwargs={"normalize_embeddings": True},
        )

    def _normalize_vector(self, vector: list[float], expected_dim: int) -> list[float]:
        current_dim = len(vector)
        if current_dim == expected_dim:
            return vector
        if current_dim > expected_dim:
            return vector[:expected_dim]
        return vector + [0.0] * (expected_dim - current_dim)

    async def embed_query(self, text: str) -> list[float]:
        model = await self._get_model()
        loop = asyncio.get_running_loop()
        vector = await loop.run_in_executor(None, model.embed_query, text)
        return self._normalize_vector(list(vector), EMBEDDING_DIM)

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = await self._get_model()
        loop = asyncio.get_running_loop()
        vectors = await loop.run_in_executor(None, model.embed_documents, texts)
        return [
            self._normalize_vector(list(v), EMBEDDING_DIM)
            for v in vectors
        ]

    async def ensure_dimension(self, expected_dim: int) -> None:
        await self._get_model()
        if self.embedding_dim != expected_dim:
            logger.warning(
                "Embedding dimension mismatch: model=%s expected=%s. "
                "Using temporary pad/truncate compatibility mode.",
                self.embedding_dim,
                expected_dim,
            )

    def extract_text(self, file_path: str) -> str:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            reader = PdfReader(file_path)
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        return path.read_text(encoding="utf-8")

    def chunk_text(
        self,
        text: str,
        *,
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[dict[str, Any]]:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=["\n\n", "\n", ". ", " ", ""],
            is_separator_regex=False,
            add_start_index=True,
        )
        docs = splitter.create_documents([text])
        chunks: list[dict[str, Any]] = []
        for idx, doc in enumerate(docs):
            content = doc.page_content
            char_start = doc.metadata.get("start_index")
            char_end = (char_start + len(content)) if isinstance(char_start, int) else None
            chunks.append(
                {
                    "chunk_index": idx,
                    "content": content,
                    "char_start": char_start,
                    "char_end": char_end,
                    "token_count": None,
                }
            )
        return chunks


rag_service = RAGService()
