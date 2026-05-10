# AIJu

AIJu 是面向“AI 全栈极速黑客松·学科知识整合智能体开发”赛题的工程仓库。系统目标是将多本教材解析为结构化章节，抽取知识点并构建可视化知识图谱，完成跨教材去重提纯和不超过 30% 的压缩整合，并基于整合知识库提供带原文引用的 RAG 问答。

赛题 PDF 和 7 本教材不放入本仓库。默认本地测试数据位于仓库外层：

```bash
/Users/eclipse/code/Hackathon/第一届AI全栈黑客松赛题.pdf
/Users/eclipse/code/Hackathon/textbooks/
```

## Tech Stack

- Backend: FastAPI, Pydantic, PyMuPDF, MarkItDown, Chroma, sentence-transformers/FlagEmbedding
- Frontend: React, Vite, Cytoscape.js
- AI: OpenAI-compatible chat model + local BGE Chinese embedding
- Deployment: Docker Compose friendly; local dev first

## Repository Layout

```text
AIJu/
├── backend/app/              # FastAPI API, schemas, services
├── frontend/src/             # React SPA scaffold
├── docs/                     # Required hackathon documents
├── report/                   # Integration report template
├── scripts/                  # Local utility scripts
├── data/                     # Local runtime data, ignored by git
├── requirements.txt
├── package.json
├── docker-compose.yml
└── .env.example
```

## Quick Start

### 1. Backend

```bash
cd /Users/eclipse/code/Hackathon/AIJu
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Optional local embedding/rerank stack:
# pip install -r requirements-ai.txt
cp .env.example .env
uvicorn app.main:app --reload --app-dir backend --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

### 2. Frontend

```bash
cd /Users/eclipse/code/Hackathon/AIJu
npm install
npm run dev:frontend
```

Open `http://localhost:5173`.

### 3. Optional Docker

```bash
docker compose up --build
```

## Environment

Create `.env` from `.env.example`:

```bash
OPENAI_API_KEY=your_key
OPENAI_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
TEXTBOOK_DATA_DIR=../textbooks
```

`TEXTBOOK_DATA_DIR` points to external local教材数据. Do not copy PDFs into this repository.

## Current State

This repository currently contains an executable scaffold:

- Fixed API route structure for textbook parsing, graph building, integration, RAG, and report summary.
- Shared Pydantic contracts that match the competition deliverables.
- React single-page three-column UI skeleton.
- Required docs and report templates.
- Ignore rules that prevent large textbook PDFs and generated vector stores from entering Git.
- Real PDF/Markdown/TXT parsing scaffold with chapter detection and local JSON registry.
- RAG index/query pipeline with 650-character chunking, local hash embedding, BM25 hybrid retrieval, citations, and optional OpenAI-compatible answer generation.

See [docs/总领文档.md](docs/总领文档.md) for the module-by-module implementation roadmap.
