# ── Stage 1: Build Frontend ──
FROM node:20-alpine AS frontend-builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY frontend/ ./frontend/
COPY vite.config.js ./ 2>/dev/null || true

# Override VITE_API_BASE for production — use empty so it calls same origin
ENV VITE_API_BASE=
RUN npm run build

# ── Stage 2: Backend + Serve Static ──
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY data/ ./data/
COPY --from=frontend-builder /app/dist ./dist

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
