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
# Only Python and the finished virtual environment: no uv, no source tree, no tests.
FROM python:3.14-slim
RUN useradd --create-home --uid 10001 fish
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
USER fish
EXPOSE 8000
# Render sets PORT; locally it defaults to 8000. Uvicorn pings every WebSocket every 15 s
# so idle connections are not dropped by proxies (T2.1 §17).
CMD ["sh", "-c", "exec uvicorn fish_server.app:app --host 0.0.0.0 --port ${PORT:-8000} --ws-ping-interval 15 --ws-ping-timeout 20 --proxy-headers --forwarded-allow-ips='*'"]
