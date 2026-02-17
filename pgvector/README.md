# PgVector Container

## File Tree

```
pgvector/
├── Dockerfile
├── env.sh
├── init/
│   └── 001_extensions.sql   ← only pgvector + pgcrypto extensions
├── postgres.conf
└── README.md
```

> **Note:** All tables, enums, and indexes are managed by **Alembic** migrations
> (see `alembic/` at the project root). The Docker init script only installs
> Postgres extensions that require superuser privileges.

## Build

```bash
docker build -f Dockerfile -t ai-infra-db:1.0 .
```

## Run

```bash
docker run --name postgres-db --env-file env.sh -p 5432:5432 -v postgres_data:/var/lib/postgresql/data ai-infra-db:1.0
```

## Apply Migrations

From the **project root** (not this directory):

```bash
uv run alembic upgrade head
```

## Connect

```bash
psql -h localhost -p 5432 -U rag_user -d rag_db
```
