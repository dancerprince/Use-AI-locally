# --- build UI ---------------------------------------------------------------
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- runtime ----------------------------------------------------------------
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
# Node is included so stdio MCP servers launched via `npx` work inside the container.
RUN apt-get update && apt-get install -y --no-install-recommends nodejs npm && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 app
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --no-dev
COPY --from=ui /ui/dist /app/frontend/dist
RUN mkdir -p /data && chown app /data
USER app
ENV OAI_DATA_DIR=/data OAI_HOST=0.0.0.0 OAI_FRONTEND_DIST=/app/frontend/dist
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uv", "run", "--no-dev", "python", "-m", "app.main"]
