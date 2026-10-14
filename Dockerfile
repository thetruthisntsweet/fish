# Fish game server image (T2.1 subtask 12). Built by Render (render.yaml) and by CI.
#   docker build -t fish-server .
#   docker run --rm -p 8000:8000 fish-server

# ---------------------------------------------------------------- build stage
# Installs fish-server and its dependencies (fish-rules, fish-agents, FastAPI, ...) into
# /app/.venv, exactly as uv.lock pins them. Nothing else from the repository is kept.
FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY . .
RUN uv sync --locked --no-dev --no-editable --package fish-server

# ---------------------------------------------------------------- runtime stage
# Only Python, the finished virtual environment and the migrations: no uv, no source tree,
# no tests.
FROM python:3.14-slim
# A non-root user with a login shell and a ~/.ssh folder: Render's Shell page and SSH
# need both for Docker services (used for the restore drill, docs/runbooks/restore-drill.md).
RUN useradd --create-home --uid 10001 --shell /bin/bash fish \
    && install -d -m 0700 -o fish -g fish /home/fish/.ssh
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
# Render's pre-deploy command runs `alembic upgrade head` from /app (render.yaml).
COPY --from=build /app/alembic.ini /app/alembic.ini
COPY --from=build /app/packages/fish-server/migrations /app/packages/fish-server/migrations
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
USER fish
EXPOSE 8000
# Render sets PORT; locally it defaults to 8000. Uvicorn pings every WebSocket every 15 s
# so idle connections are not dropped by proxies (T2.1 §17).
CMD ["sh", "-c", "exec uvicorn fish_server.app:app --host 0.0.0.0 --port ${PORT:-8000} --ws-ping-interval 15 --ws-ping-timeout 20 --proxy-headers --forwarded-allow-ips='*'"]
