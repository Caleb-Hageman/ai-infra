import os

EMBEDDING_MODEL: str = "mixedbread-ai/mxbai-embed-large-v1"
EMBEDDING_DIM: int = 1024
EMBEDDING_DEVICE: str = "cpu"

VLLM_BASE_URL: str = os.getenv("VLLM_BASE_URL", "http://localhost:8001")
VLLM_MODEL: str = os.getenv("VLLM_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")
VLLM_TIMEOUT: float = float(os.getenv("VLLM_TIMEOUT", "300"))

DEFAULT_CHUNK_SIZE: int = 256
DEFAULT_CHUNK_OVERLAP: int = 50

DEFAULT_TOP_K: int = 5
