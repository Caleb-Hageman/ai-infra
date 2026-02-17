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

3. Start the database (see `pgvector/README.md` for Docker build/run):
```bash
cd pgvector
docker build -f Dockerfile -t ai-infra-db:1.0 .
docker run --name postgres-db --env-file env.sh -p 5432:5432 -v postgres_data:/var/lib/postgresql/data ai-infra-db:1.0
```

4. Apply database migrations:
```bash
uv run alembic upgrade head
```

5. Run the dev server:
```bash
uv run fastapi dev
```

## How the Project is Structured

```
ai-infra/
├── app/                          ← The Python API (FastAPI)
│   ├── main.py                   ← App entry point, registers routes
│   ├── db.py                     ← Database connection config
│   ├── models.py                 ← All database table definitions (source of truth)
│   └── routers/
│       ├── ingest.py             ← Endpoints for uploading documents
│       └── query.py              ← Endpoint for asking questions
│
├── alembic/                      ← Database migration tool
│   ├── env.py                    ← Tells Alembic how to connect to the DB
│   ├── script.py.mako            ← Template for new migrations
│   └── versions/                 ← Generated migration files live here
│       └── 78098b94ff86_initial_schema.py
│
├── pgvector/                     ← Docker setup for Postgres + pgvector
│   ├── Dockerfile
│   ├── env.sh                    ← DB credentials (user, password, db name)
│   ├── init/001_extensions.sql   ← Installs pgvector extension
│   └── postgres.conf             ← Postgres performance settings
│
├── alembic.ini                   ← Alembic config file
├── pyproject.toml                ← Python dependencies (like package.json)
└── uv.lock                       ← Lockfile (like package-lock.json)
```

## How the Database Works

We use **three tools** together. Here's what each one does:

### 1. Postgres + pgvector (the database)
This is a regular Postgres database running in Docker, with the **pgvector** extension
added so it can store and search AI embeddings (vectors). Think of it as a normal SQL
database that also knows how to do "find me the most similar text" queries.

### 2. SQLAlchemy (the ORM)
Instead of writing raw SQL to interact with the database, we define our tables as
**Python classes** in `app/models.py`. For example, a `teams` table looks like this:

```python
class Team(Base):
    __tablename__ = "teams"

    id = Column(UUID, primary_key=True, ...)
    name = Column(Text, nullable=False)
    created_at = Column(DateTime, ...)
```

This means in our code we can do things like `team.name` instead of writing
`SELECT name FROM teams WHERE id = ...`. SQLAlchemy translates Python to SQL for us.

### 3. Alembic (migrations)
Alembic tracks **changes to the database schema over time**. It answers the question:
"the models.py file says a column should exist, but the actual database doesn't have it yet
— how do we update the database?"

Every time you change `models.py`, you generate a **migration** — a small Python script
that tells Postgres exactly what to add/remove/change.

## Common Tasks

### "I just cloned the repo, how do I set up?"
```bash
uv sync                              # install Python dependencies
cd pgvector
docker build -f Dockerfile -t ai-infra-db:1.0 .   # build the DB image
docker run --name postgres-db --env-file env.sh -p 5432:5432 -v postgres_data:/var/lib/postgresql/data ai-infra-db:1.0   # start DB
cd ..
uv run alembic upgrade head           # create all tables
uv run fastapi dev                    # start the API server
```

### "Someone else changed the database schema"
After pulling their changes:
```bash
uv run alembic upgrade head
```
This applies any new migration files they added. Same as running a SQL script,
but automatic.

### "I need to add a column or table"
1. Edit `app/models.py` — add your column/table as a Python class
2. Run: `uv run alembic revision --autogenerate -m "describe what you changed"`
3. Check the generated file in `alembic/versions/` (quick sanity check)
4. Run: `uv run alembic upgrade head` (applies it to your local DB)
5. Commit both `models.py` AND the new migration file

### "I want to completely reset my database"
```bash
uv run alembic downgrade base        # undo all migrations (empty DB)
uv run alembic upgrade head          # re-apply everything fresh
```

Or the nuclear option — delete the Docker volume and rebuild:
```bash
docker rm -f postgres-db
docker volume rm postgres_data
docker run --name postgres-db --env-file env.sh -p 5432:5432 -v postgres_data:/var/lib/postgresql/data ai-infra-db:1.0
uv run alembic upgrade head
```

### "I want to look at the database directly"
```bash
psql -h localhost -p 5432 -U rag_user -d rag_db
```
Then you can run normal SQL: `SELECT * FROM teams;`, `\dt` (list tables), etc.

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
Stores chunk text, embedding, and positional metadata. With pgvector everything lives in Postgres — no external vector DB needed.

| Column         | Type         | Notes                                  |
|----------------|--------------|----------------------------------------|
| `id`           | uuid         | PK                                     |
| `document_id`  | uuid         | FK → `documents.id`                    |
| `chunk_index`  | int          | 0…n ordering within the document       |
| `content`      | text         | Full chunk text (used for LLM context) |
| `embedding`    | vector(1536) | pgvector column — dimensions match your embedding model |
| `page_start`   | int          | Nullable                               |
| `page_end`     | int          | Nullable                               |
| `char_start`   | int          | Nullable                               |
| `char_end`     | int          | Nullable                               |
| `token_count`  | int          | Nullable — useful for context-window budgeting |
| `created_at`   | timestamp    |                                        |

> **Index:** HNSW on `embedding` with `vector_cosine_ops` for fast approximate nearest-neighbor search.

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