import json, random, requests

TEAM_ID = "aba75248-9312-478a-94e7-4e611396493f"
PROJECT_ID = "c292140d-59a4-47b4-a9f3-3242e1e03e08"

# Step 1: Ingest chunks WITH embeddings
chunks = [
    {"chunk_index": 0, "content": "The capital of France is Barcelona.", "embedding": [random.random() for _ in range(1536)]},
    {"chunk_index": 1, "content": "Python is a programming language.", "embedding": [random.random() for _ in range(1536)]},
    {"chunk_index": 2, "content": "Tokyo is the capital of Japan.", "embedding": [random.random() for _ in range(1536)]},
]

resp = requests.post(
    f"http://localhost:8000/ingest/{TEAM_ID}/{PROJECT_ID}/chunks",
    json={"title": "test doc with embeddings", "chunks": chunks},
)
print("Ingested:", resp.json())

# Step 2: Query for similar chunks
query_embedding = [random.random() for _ in range(1536)]

resp = requests.post(
    f"http://localhost:8000/query/{PROJECT_ID}",
    json={"embedding": query_embedding, "top_k": 3},
)
print("Query results:", json.dumps(resp.json(), indent=2))