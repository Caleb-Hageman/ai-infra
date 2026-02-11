FROM pgvector/pgvector:pg15

COPY postgres.conf /etc/postgresql/postgresql.conf
COPY init/ /docker-entrypoint-initdb.d/

CMD ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]
