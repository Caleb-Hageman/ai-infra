# ai-infra
## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)

## Setup

1. Clone the repository
```bash
git clone https://github.com/Caleb-Hageman/ai-infra.git
cd ai-infra
```

2. Install dependencies:
```bash
uv sync
```

3. Run the dev server:
```bash
uv run fastapi dev
```

## Proposed Database Schema (MVP)

### `teams`
| Column       | Type      | Notes          |
|--------------|-----------|----------------|
| `id`         | uuid      | PK             |
| `name`       | text      |                |
| `created_at` | timestamp |                |

### `projects`
| Column       | Type      | Notes              |
|--------------|-----------|--------------------|
| `id`         | uuid      | PK                 |
| `team_id`    | uuid      | FK → `teams.id`    |
| `name`       | text      |                    |
| `created_at` | timestamp |                    |

### `api_keys`
| Column       | Type      | Notes                              |
|--------------|-----------|------------------------------------|
| `id`         | uuid      | PK                                 |
| `team_id`    | uuid      | FK → `teams.id`                    |
| `key_hash`   | text      | Store hash, never the raw key      |
| `status`     | text      | `active` \| `revoked`              |
| `created_at` | timestamp |                                    |
| `revoked_at` | timestamp | Nullable                           |

### `documents`
Represents a logical document entry.

| Column        | Type      | Notes                                         |
|---------------|-----------|-----------------------------------------------|
| `id`          | uuid      | PK                                            |
| `team_id`     | uuid      | FK → `teams.id`                               |
| `project_id`  | uuid      | FK → `projects.id`                            |
| `title`       | text      |                                                |
| `source_type` | enum      | `upload` \| `url` \| `manual`                 |
| `gcs_uri`     | text      | Where the raw file lives in Cloud Storage      |
| `mime_type`   | text      |                                                |
| `status`      | enum      | `uploaded` \| `processing` \| `ready` \| `failed` |
| `created_at`  | timestamp |                                                |
| `updated_at`  | timestamp |                                                |

### `ingestion_jobs`
One job per upload (or per reprocess).

| Column            | Type      | Notes                                               |
|-------------------|-----------|-----------------------------------------------------|
| `id`              | uuid      | PK                                                  |
| `document_id`     | uuid      | FK → `documents.id`                                 |
| `status`          | enum      | `queued` \| `running` \| `succeeded` \| `failed`    |
| `error_message`   | text      | Nullable                                            |
| `started_at`      | timestamp | Nullable                                            |
| `finished_at`     | timestamp | Nullable                                            |
| `chunks_created`  | int       |                                                      |
| `embedding_model` | text      | Track which model was used                           |
| `created_at`      | timestamp |                                                      |

### `document_chunks`
Stores chunk metadata and the key that links to the vector DB (citation backbone).

| Column         | Type      | Notes                            |
|----------------|-----------|----------------------------------|
| `id`           | uuid      | PK                               |
| `document_id`  | uuid      | FK → `documents.id`              |
| `chunk_index`  | int       | 0…n ordering within the document |
| `vector_id`    | text      | ID stored in the vector DB       |
| `page_start`   | int       | Nullable                         |
| `page_end`     | int       | Nullable                         |
| `char_start`   | int       | Nullable                         |
| `char_end`     | int       | Nullable                         |
| `text_preview` | text      | Nullable — short snippet for debugging |
| `token_count`  | int       | Nullable — useful for context-window budgeting |
| `created_at`   | timestamp |                                  |

### `query_logs`
Audit + metrics logging. 

| Column              | Type      | Notes                                   |
|---------------------|-----------|-----------------------------------------|
| `id`                | uuid      | PK                                      |
| `team_id`           | uuid      | FK → `teams.id`                         |
| `project_id`        | uuid      | FK → `projects.id`                      |
| `api_key_id`        | uuid      | FK → `api_keys.id` — Nullable           |
| `question_hash`     | text      | Hash of the question (privacy-safe)     |
| `used_rag`          | bool      |                                          |
| `top_k`             | int       |                                          |
| `model`             | text      | Which LLM was used for the response     |
| `latency_ms`        | int       |                                          |
| `prompt_tokens`     | int       | Nullable                                |
| `completion_tokens` | int       | Nullable                                |
| `created_at`        | timestamp |                                          |

### `query_citations`
Links a query to the chunks that were cited in the response.

| Column     | Type  | Notes                        |
|------------|-------|------------------------------|
| `query_id` | uuid  | FK → `query_logs.id`         |
| `chunk_id` | uuid  | FK → `document_chunks.id`    |
| `rank`     | int   | 1…k                         |
| `score`    | float | Nullable — similarity score  |

> Composite PK: (`query_id`, `chunk_id`)