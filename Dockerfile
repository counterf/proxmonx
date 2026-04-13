# Stage 1: Build frontend
FROM node:24-alpine AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

# Stage 2: Backend + static frontend
FROM python:3-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl gosu && rm -rf /var/lib/apt/lists/*

RUN useradd -r -u 1001 -m appuser

COPY --from=ghcr.io/astral-sh/uv:0.6 /uv /usr/local/bin/uv

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY backend/app/ app/
COPY --from=frontend /app/dist /app/static

RUN chown -R appuser:appuser /app

EXPOSE 3000

# Start as root to fix data dir ownership (handles volume mounts), then drop to appuser
CMD ["sh", "-c", "mkdir -p /app/data && chown appuser:appuser /app/data && exec gosu appuser uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-3000}"]
