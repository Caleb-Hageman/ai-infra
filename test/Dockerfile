FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

# ── Non-root user ─────────────────────────────────────────────────────────────
RUN groupadd --system --gid 999 nonroot \
 && useradd  --system --gid 999 --uid 999 --create-home nonroot

WORKDIR /app

# ── uv settings ───────────────────────────────────────────────────────────────
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
ENV UV_NO_DEV=1

# ── Install dependencies (cached layer — rebuilds only if lock file changes) ──
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# ── Copy app source with correct ownership ────────────────────────────────────
COPY --chown=nonroot:nonroot . /app

# ── Install the project itself ────────────────────────────────────────────────
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

ENV PATH="/app/.venv/bin:$PATH"

# ── Runtime ───────────────────────────────────────────────────────────────────
EXPOSE 8000
ENTRYPOINT []
USER nonroot

# Use `fastapi dev` locally (hot reload), `fastapi run` in production
CMD ["fastapi", "run", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]
