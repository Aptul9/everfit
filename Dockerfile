FROM node:24-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
RUN uv sync --frozen --no-dev && rm /usr/local/bin/uv
COPY --from=web /web/dist /app/web

# The book corpus and the owner's story are not in this public repository: the deploy brings them from the private
# one into /private (read-only mount). Without them the coach still works, only the book tools answer "not found".
ENV PATH=/app/backend/.venv/bin:$PATH \
    NUTRI_DATA_DIR=/data \
    NUTRI_WEB_DIR=/app/web \
    NUTRI_PRIVATE_DIR=/private \
    NUTRI_HOST=127.0.0.1 \
    NUTRI_PORT=8097 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN install -d -o 10001 -g 10001 -m 700 /data
USER 10001:10001
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=4 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['NUTRI_PORT'] + '/api/health', timeout=4)"]
CMD ["sh", "-c", "exec nutri serve --host \"$NUTRI_HOST\" --port \"$NUTRI_PORT\""]
