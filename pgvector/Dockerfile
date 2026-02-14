FROM pgvector/pgvector:pg15

COPY postgres.conf /etc/postgresql/postgresql.conf
COPY init/001_extensions.sql /docker-entrypoint-initdb.d/

CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]
