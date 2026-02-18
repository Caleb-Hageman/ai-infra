# ai-infra
## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/)

## Setup

1. Clone the repository
```bash
git clone https://github.com/Caleb-Hageman/ai-infra.git
cd ai-infra
cd test
```

2. Install dependencies:
```bash
uv lock
uv sync
```

3. Start the database (see `pgvector/README.md` for Docker build/run):
```bash
docker compose up --build


## How the Project is Structured

```
ai-infra/
├── app/                          ← The Python API (FastAPI)
│   ├── main.py                   ← App entry point, registers routes
│   ├── __init__.py               ← Init files
│   ├── rag.py                    ← All database table definitions (source of truth)
├── Dockerfile
├── env.sh                    ← DB credentials (user, password, db name)
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

for future
### 3. Alembic (migrations)
Alembic tracks **changes to the database schema over time**. It answers the question:
"the models.py file says a column should exist, but the actual database doesn't have it yet
— how do we update the database?"

Every time you change `models.py`, you generate a **migration** — a small Python script
that tells Postgres exactly what to add/remove/change.

