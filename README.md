# Multimodal RAG Chatbot — Phase 1

Local-first RAG chatbot for industrial/machinery support. Phase 1 covers text ingestion (Excel, PDF, CSV, plain text), hybrid retrieval (dense + BM25 + reranking), and a FastAPI + Proper UI/UX

## Prerequisites

- **macOS Apple Silicon, 16 GB RAM** (POC target)
- [Homebrew](https://brew.sh)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Python 3.11 or 3.12. Python 3.14 is not supported by all compiled NLP dependencies yet.

## Setup

### 1. Install and start Ollama (native — not in Docker)

Ollama must run natively on Mac to use Metal GPU acceleration.

```bash
brew install ollama
ollama pull qwen2.5vl:7b
ollama pull nomic-embed-text
ollama serve   # keep running in a terminal
```

If RAM is tight, use `phi3.5-vision` instead and set `LLM_MODEL=phi3.5-vision` in `.env`.

### 2. Start infrastructure (Qdrant + Redis)

```bash
docker compose -f docker-compose.mac-poc.yml up -d
```

- Qdrant: http://localhost:6333
- Redis: localhost:6379 (reserved for Phase 3)

### 3. Python environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m spacy download en_core_web_sm
cp .env.example .env
```

Generate sample fixtures (optional):

```bash
python tests/fixtures/generate_fixtures.py
```

Run offline smoke tests:

```bash
PYTHONPATH=. python tests/test_smoke.py
```

### 4. Start the API

```bash
uvicorn api.main:app --reload --port 8000
```

Health check: http://localhost:8000/health — confirm `"llm_ready": true`

### 5. Start Gradio UI

```bash
python ui/gradio_app.py
```

Open http://localhost:7860

## Usage

### Ingest documents

**Gradio:** Use the **Ingest** tab to upload PDF, XLSX, CSV, or TXT files.

**curl:**

```bash
curl -X POST http://localhost:8000/api/v1/ingest \
  -F "tenant_id=default" \
  -F "tags=machinery,motor" \
  -F "files=@tests/fixtures/maintenance_log.xlsx"
```

### Chat

**curl:**

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "default", "query": "What caused motor overheating on machine M-42?"}'
```

### Evaluate the system

Run the repeatable offline evaluation for classification, parsing, chunking,
feedback persistence, and regression tests:

```bash
.venv/bin/python scripts/evaluate_system.py
```

Include live Ollama/Qdrant checks and a PDF preflight when those services are running:

```bash
.venv/bin/python scripts/evaluate_system.py --live --pdf /path/to/document.pdf
```

### Collection stats

```bash
curl http://localhost:8000/api/v1/collections/default/stats
```

### Delete a document

```bash
curl -X DELETE "http://localhost:8000/api/v1/collections/default/document/maintenance_log.xlsx"
```

## Architecture (Phase 1)

```
Upload → Docling/CSV/Excel parser → Chunker → nomic-embed-text → Qdrant
Query  → Classifier → Agent tool selection → Hybrid search/graph tools → Rerank → Qwen2.5-VL
```

The retrieval agent has explicit tools for semantic/keyword knowledge-base
search, targeted error-code search, and diagnostic-graph search. It can choose
additional tool calls when the first result is weak, then stops and answers from
the collected evidence.

## Phase 1 Limitations

- Text documents only (no image ingestion or OCR)
- No LangGraph agent or tool calling
- No Redis session memory or semantic cache
- No tenant YAML config (hardcoded defaults in `config/settings.py`)
- Synchronous ingestion (no background worker)

## Project Structure

```
api/           FastAPI app and routers
agent/         (Phase 3)
rag/           Retrieval, embedding, context assembly
ingestion/     Parsing and chunking pipeline
models/        Ollama client and Pydantic schemas
storage/       Qdrant and local file store
ui/            Gradio demo
config/        Settings
tests/fixtures Sample documents
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Ollama not reachable | Run `ollama serve` natively |
| Qdrant connection refused | `docker compose -f docker-compose.mac-poc.yml up -d` |
| spaCy model missing | `python -m spacy download en_core_web_sm` |
| Slow first query | Cross-encoder and Docling models download on first use |
| Out of memory | Switch to `phi3.5-vision` or close other apps |
