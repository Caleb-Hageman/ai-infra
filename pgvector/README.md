# PgVector Container

Hi! I'm your first Markdown file in **StackEdit**. If you want to learn about StackEdit, you can read me. If you want to play with Markdown, you can edit me. Once you have finished with me, you can create new files by opening the **file explorer** on the left corner of the navigation bar.

# Project File Tree

pgvector/
├── Dockerfile
├── env.sh
├── init
│   ├── 001_extensions.sql
│   ├── 002_enums.sql
│   ├── 003_core_tables.sql
│   ├── 004_vector_tables.sql
│   ├── 005_indexes.sql
│   └── 006_seed.sql
├── postgres.conf
└── README.md



## Build

``` sudo docker build -f Dockerfile -t ai-infra-db:1.0 . ```

## Run

```
sudo docker run --name postgres-db \
				  --env-file env.sh  \
				  -p 5432:5432   \
				  -v postgres_data:/var/lib/postgresql/data \ 
				  ai-infra-db:1.0
```

## Connect

``` psql -h localhost -p 5432 -U rag_user -d rag_db ```


