# ai-infra
## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- [Docker](https://docs.docker.com/get-docker/) (for the Postgres + pgvector image, and optionally for the API and vLLM)
- A running [Redis](https://redis.io/) instance (default: `localhost:6379`) for app features that use it
- A vLLM (or OpenAI-compatible) HTTP server for chat features; the app defaults to `VLLM_BASE_URL=http://localhost:8001` (see [Configuration](#configuration))

There are **no Makefiles** in this repository. Builds use **uv** and **Docker** only.

## Build

| Component | How to build |
|-----------|----------------|
| Python dependencies | From the repo root: `uv sync` (uses `pyproject.toml` and `uv.lock`). |
| Postgres + pgvector | `cd pgvector && docker build -f Dockerfile -t ai-infra-db:1.0 .` |
| API (container) | From the repo root: `docker build -f Dockerfile.dev -t ai-infra-api:dev .` (hot-reload) or `docker build -f Dockerfile.prod -t ai-infra-api:prod .` (production-style `fastapi run` on port 8080 inside the image). |
| vLLM (optional container) | `docker build -f Dockerfile.vllm -t ai-infra-vllm:local .` — sets `MODEL_NAME` (default `meta-llama/Meta-Llama-3-8B-Instruct`) and serves OpenAI-compatible HTTP on port 8080 **inside** the container; map a host port as needed and point `VLLM_BASE_URL` at it. |

**Resource note:** The API loads embedding models via PyTorch / `sentence-transformers` at runtime (`EMBEDDING_MODEL` in `app/config.py`). On small or edge devices, expect significant RAM and CPU; use a machine with enough memory for your chosen embedding model, or run the API on a larger host and keep only clients on the target device.

## Configuration

Set these as **environment variables** in your shell, systemd unit, container definition, or orchestrator (this project does not ship a single `.env` file for the app).

### Database

The API and Alembic must reach the **same** Postgres instance and database as the credentials used when you start the database container.

- **`DATABASE_URL`** (optional): full async URL, e.g. `postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME`.
- If `DATABASE_URL` is unset, the URL is built from **`POSTGRES_USER`**, **`POSTGRES_PASSWORD`**, **`POSTGRES_HOST`** (default `localhost`), **`POSTGRES_PORT`** (default `5432`), and **`POSTGRES_DB`**.

The Postgres Docker image also expects `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` in `pgvector/env.sh` (see [Setup](#setup)). **Keep the app’s variables aligned with `env.sh`** so migrations and the API connect successfully.

### LLM and RAG

| Variable | Default | Purpose |
|----------|---------|---------|
| `VLLM_BASE_URL` | `http://localhost:8001` | OpenAI-compatible API base URL for chat. |
| `VLLM_MODEL` | `meta-llama/Meta-Llama-3-8B-Instruct` | Model name sent to the LLM server. |
| `VLLM_TIMEOUT` | `300` | Request timeout (seconds). |
| `CHAT_TOP_K` | `5` | RAG retrieval top-k. |
| `CHAT_MIN_SCORE_DEFAULT` | `0.4` | Minimum similarity for chunks. |
| `VLLM_MAX_RETRIES` | `2` | Retries for LLM calls. |

### Redis

| Variable | Default |
|----------|---------|
| `REDIS_HOST` | `localhost` |
| `REDIS_PORT` | `6379` |

### Auth and admin

| Variable | Default | Notes |
|----------|---------|--------|
| `ADMIN_TEAM_ID` | `00000000-0000-0000-0000-000000000000` | Admin team UUID in auth logic. |

### Google Cloud (uploads, optional async ingest)

| Variable | Purpose |
|----------|---------|
| `GCS_BUCKET_NAME` | Bucket for document storage. |
| `SERVICE_ACCOUNT_EMAIL` | Service account used with GCS and related flows. |
| `INGEST_USE_CLOUD_TASKS` | Set to `false` / `0` / `no` to avoid Cloud Tasks and use in-process ingest when GCP is not configured (typical for local dev). |
| `GCP_PROJECT` or `GOOGLE_CLOUD_PROJECT` | GCP project when using Cloud Tasks. |
| `INGEST_WORKER_URL` | HTTPS URL of the ingest worker (e.g. Cloud Run) when using Cloud Tasks. |
| `CLOUD_TASKS_OIDC_SA_EMAIL` | OIDC caller SA for Cloud Tasks (falls back to `SERVICE_ACCOUNT_EMAIL`). |
| `CLOUD_TASKS_LOCATION` | Default `us-east1`. |
| `CLOUD_TASKS_QUEUE` | Default `ingest-queue`. |
| `CLOUD_TASKS_OIDC_AUDIENCE` | Defaults to `INGEST_WORKER_URL` if unset. |

### Ingest worker (server-side)

| Variable | Purpose |
|----------|---------|
| `INGEST_WORKER_SKIP_AUTH` | If `1` / `true` / `yes`, skips auth on the worker route (use only in controlled environments). |

Initial migration seed values can be overridden with `ADMIN_API_KEY`, `ADMIN_API_KEY_ID`, and `ADMIN_TEAM_ID` when running Alembic (see `alembic/versions/`).

## Install and run on a target host

1. **Install** Python 3.13+, uv, and Docker (if you run Postgres or containerized services on that host).
2. **Clone** the repository and run `uv sync` on the target (or build and run the API image as below).
3. **Start Postgres** using the `pgvector` image and an `env.sh` that matches your chosen DB user, password, and database name.
4. **Set environment variables** for the API so database (and optional Redis, vLLM, GCS) match your deployment.
5. **Apply migrations** from the repo root: `uv run alembic upgrade head`.
6. **Run the API**
   - **Development:** `uv run fastapi dev` (binds to localhost by default; use `--host 0.0.0.0` to listen on all interfaces).
   - **Production-style (bare metal / VM):** `uv run fastapi run --host 0.0.0.0 --port 8080` (or your chosen port). Put this behind a reverse proxy (nginx, Caddy, etc.) if you need TLS and rate limiting.
   - **Container:** after building with `Dockerfile.prod`, run the image and pass the same env vars (e.g. `--env-file`). If Postgres runs on the same machine as Docker, you may need `host.docker.internal` or the host’s LAN IP in `POSTGRES_HOST`, and ensure the DB port is published or reachable.

7. **Start vLLM** (or another OpenAI-compatible server) somewhere reachable from the API and set `VLLM_BASE_URL` accordingly.
8. **Start Redis** before traffic if your deployment relies on it.

Use `GET /warmup` to verify database connectivity, embedding load, and vLLM kickoff before taking production traffic.

HTTP endpoint details are in `API_DOCUMENTATION.md`.

## Features (this release)

### FR-01: Multi-Tenant Ingestion

- The API must provide a **POST /ingest** endpoint that accepts a document and a **team_id**. The infra must index the document into a namespace unique to that **team_id**.
- The API must accept a **PDF** or **TXT** file and return a success/failure JSON response.
- The API must provide a **DELETE /documents** endpoint scoped to a **team_id** to allow teams to clear their specific vector namespace without affecting others.

### FR-02: Isolated Retrieval

- The **POST /query** endpoint must require a **team_id** and strictly filter the vector search so that results only contain chunks belonging to that specific team.
- The infra must return a JSON object containing the **answer** and a **sources** array.
- If the retrieved context exceeds the LLM's token limit, the system must automatically prioritize the top **N** most relevant chunks.

### FR-03: System Prompt Injection

- The API must allow a **system_prompt** parameter per request, allowing teams to "skin" the LLM without modifying the base infrastructure or affecting other teams.
- The API must allow teams to pass optional parameters (e.g., **temperature**, **max_tokens**) to the **POST /query** endpoint to control the "creativity" or length of the response.
- The system must provide a **Global Default** system prompt for teams that do not provide their own.

### FR-04: Observability & Logging

- The system must generate a unique **Request ID** for every API call, returned in the header.
- The system must log the number of **input/output tokens** used per **team_id** to a persistent database.

### Additional capabilities

- **Authentication:** `Authorization: Bearer <api_key>`; **team_id** is derived from the key for authorized operations.
- **Projects:** teams have multiple **projects**; routes use **`/ingest/{project_id}/...`** and **`/query/{project_id}`** for project-scoped work.
- **File types:** **Markdown** (`.md` / `.markdown`) is supported on upload in addition to PDF and TXT.
- **Upload modes:** multipart upload and **signed direct-to-GCS** upload (`/upload/init` and complete).
- **Async ingest:** optional **Google Cloud Tasks** delivery to **`POST /ingest-worker`** when GCP is configured; otherwise ingest can run in-process.
- **Delete by source:** **`DELETE /query/{project_id}/document?source=<filename>`** removes a document and its chunks for the caller’s team and project.
- **Chat RAG:** **`POST /api/v1/chat`** returns **`answer`** and **`citations`** (sources) with optional **project_id** for scoped retrieval, or team-wide retrieval when appropriate.
- **Vector search:** **`POST /query/{project_id}`** returns similarity **results** (JSON); retrieval tuning via **`top_k`**, **`CHAT_TOP_K`**, **`min_score`**, and chunking options.
- **Usage data:** per-team rows in **`api_usage`** in Postgres (request counts by route category, latency, last path).
- **Rate limiting:** Redis-backed **per-team** limits on **`POST /api/v1/chat`**.
- **Admin and lifecycle:** team creation, **API key** issue/revoke, and admin-only operations as documented in `API_DOCUMENTATION.md`.
- **Maintenance:** **`POST /ingest/{project_id}/repair-embeddings`** to re-embed missing vectors.
- **Stats and listing:** **`GET /query/{project_id}/stats`**, document and chunk listing endpoints, GCS signed URL helpers and test routes.
- **Health / warmup:** **`GET /warmup`** checks database, embedding model, and kicks vLLM warm-up.

## Known issues

- **First chat after startup can be slow.** Cold embedding model load, vLLM startup, and the first end-to-end RAG call can take noticeable time before answers return. Call **`GET /warmup`** after deploy; some latency on the first real user request may still occur.


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

3. Create `pgvector/env.sh` (it is not committed; Docker injects standard Postgres variables). Use the **same** user, password, and database name in your shell or in `POSTGRES_*` / `DATABASE_URL` when you run the API and Alembic:
```bash
# pgvector/env.sh — example only; choose your own secrets
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=your-secure-password
POSTGRES_DB=rag_db
```

4. Start the database (see `pgvector/README.md` for details):
```bash
cd pgvector
docker build -f Dockerfile -t ai-infra-db:1.0 .
docker run --name postgres-db --env-file env.sh -p 5432:5432 -v postgres_data:/var/lib/postgresql/data ai-infra-db:1.0
cd ..
```

5. In the same shell (or your env file), point the app at that database, for example:
```bash
export POSTGRES_USER=rag_user
export POSTGRES_PASSWORD=your-secure-password
export POSTGRES_DB=rag_db
# POSTGRES_HOST / POSTGRES_PORT only if not localhost / 5432
```

6. Apply database migrations:
```bash
uv run alembic upgrade head
```

7. Run the dev server:
```bash
uv run fastapi dev
```

For local use without Google Cloud async ingest, set `INGEST_USE_CLOUD_TASKS=false` unless you have Cloud Tasks configured.

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
│   ├── env.sh                    ← Create locally: POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
│   ├── init/001_extensions.sql   ← Installs pgvector extension
│   └── postgres.conf             ← Postgres performance settings
│
├── Dockerfile.dev                ← API image (fastapi dev, all interfaces)
├── Dockerfile.prod               ← API image (fastapi run on :8080)
├── Dockerfile.vllm               ← Optional vLLM OpenAI-compatible server
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
# Create pgvector/env.sh with POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
export POSTGRES_USER=...           # same user as in env.sh
export POSTGRES_PASSWORD=...         # same password
export POSTGRES_DB=...              # same database name
export INGEST_USE_CLOUD_TASKS=false # for local dev without GCP
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
