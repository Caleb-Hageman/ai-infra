import json

from app.config import EMBEDDING_DIM

embedding = [0.001, 0.002, 0.003] + [0.0] * (EMBEDDING_DIM - 3)

data = {
    "title": "Quick Demo Document",
    "chunks": [
        {
            "chunk_index": 0,
            "content": "This is a test chunk.",
            "embedding": embedding,
            "page_start": 1,
            "page_end": 1,
            "token_count": 5
        }
    ]
}

with open("demo_chunks.json", "w") as f:
    json.dump(data, f)
