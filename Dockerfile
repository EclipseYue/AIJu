# ── Stage 1: Build Frontend ──
# If dist/ already exists locally, skip npm build (low-memory platforms).
# Otherwise, install deps with memory limit and build.
FROM node:20-alpine AS frontend-builder

WORKDIR /app

# Limit Node heap to avoid OOM kill on free-tier platforms (512 MB)
ENV NODE_OPTIONS="--max-old-space-size=512"

COPY package.json package-lock.json ./
RUN npm install --prefer-offline --no-audit --no-fund
COPY frontend/ ./frontend/
COPY vite.config.js ./ 2>/dev/null || true

ENV VITE_API_BASE=
RUN npm run build

# ── Stage 2: Backend + Serve Static ──
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    || true \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY data/ ./data/

# Copy pre-built dist if it exists; otherwise build from Stage 1
COPY --from=frontend-builder /app/dist ./dist

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
