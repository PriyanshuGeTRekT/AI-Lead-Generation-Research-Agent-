# AI Lead Generation & Research Agent

An AI-powered lead generation system for HRMS software sales, built with a **Supervisor multi-agent architecture** using LangGraph, Groq (open-source LLMs), and RAG.

**Live dashboard** at `http://localhost:8000` (no curl required).

![Dashboard showing 5 lead cards with score badges, pain points, and outreach emails](https://img.shields.io/badge/UI-Dashboard-teal) ![API](https://img.shields.io/badge/API-FastAPI-green) ![LLM](https://img.shields.io/badge/LLM-Llama%203.1-blue) ![Redis](https://img.shields.io/badge/Cache-Redis-red)

## Architecture

```
                    ┌─────────────────┐
                    │   Supervisor    │  ← LangGraph StateGraph
                    │  (Orchestrator) │
                    └────────┬────────┘
                             │ routes based on state
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
     ┌────────────────┐  ┌──────────┐  ┌─────────┐
     │ Research Agent │  │  Qualify │  │  Sales  │
     │ Web search +   │  │  Agent   │  │  Agent  │
     │ LLM extraction │  │ RAG+LLM  │  │ RAG+LLM │
     └────────────────┘  └──────────┘  └─────────┘
              │                │              │
              ▼                ▼              ▼
     Find companies      Score 0-10     Draft outreach
     Extract info        ≥5 → Sales     emails
                         <5 → Discard
```

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Agent Orchestration | LangGraph | Conditional routing, shared state |
| LLM | Llama 3.1 8B via Groq | Open-source model, fast LPU inference |
| LLM Client | langchain-groq (ChatGroq) | LangChain wrapper enables full LangSmith tracing |
| Vector Store | ChromaDB | Persistent, local, no infra needed |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Open-source, HuggingFace |
| Web Search | DuckDuckGo Search | Free, no API key |
| API | FastAPI | Async, auto-docs |
| Observability | LangSmith + custom JSONL metrics | LLM-level + business-level tracing |
| Containerization | Docker | Portable deployment |

## Quick Start

### 1. Prerequisites
- Docker & Docker Compose installed
- Free Groq API key from [console.groq.com](https://console.groq.com)

### 2. Setup
```bash
git clone <repo>
cd ai-lead-gen
cp .env.example .env
# Edit .env and add your GROQ_API_KEY
```

### 3. Run
```bash
docker compose up --build
```

### 4. Build Knowledge Base (Run Once)
```bash
curl -X POST http://localhost:8000/ingest-knowledge
```
This scrapes humanmaximizer.com and builds the RAG vector store.

### 5. Generate Leads
```bash
curl -X POST http://localhost:8000/generate-leads \
  -H "Content-Type: application/json" \
  -d '{"keyword": "manufacturing company India 200 employees"}'
```

### 6. View Results
```bash
# All leads
curl http://localhost:8000/leads

# Only outreach-ready leads
curl http://localhost:8000/leads?status=outreach_ready
```

### Dashboard UI
Open **http://localhost:8000** in your browser for a full lead generation dashboard with:
- Live pipeline execution with animated step indicators (Research -> Qualify -> Sales)
- Lead cards with score badges, pain point tags, and qualification reasoning
- Expandable outreach emails with one-click copy
- Filter by status: Outreach Ready / Qualified / Disqualified / Researched
- Real-time metrics: latency, lead counts, avg score
- Sidebar pipeline log showing agent decisions as they happen

### API Docs
Visit: http://localhost:8000/docs (Swagger UI auto-generated)

## Agent Flow

1. **Research Agent**: takes a keyword, searches DuckDuckGo, scrapes company websites, and uses Llama 3 to extract structured lead info (company, size, decision makers, pain points)

2. **Qualification Agent**: scores each lead 0 to 10 using RAG-grounded LLM reasoning. It retrieves relevant HRMS product context from ChromaDB to match prospect needs against product capabilities. Leads scoring 5 or above move forward, the rest get discarded.

3. **Sales Agent**: generates personalized outreach emails for qualified leads. Uses RAG to make sure product claims are grounded in actual HumanMaximizer features, not made up.

## RAG Pipeline

```
humanmaximizer.com → Scrape → Chunk (500 tokens, 50 overlap)
                                  ↓
                    HuggingFace Embeddings (all-MiniLM-L6-v2)
                                  ↓
                    ChromaDB (cosine similarity index)
                                  ↓
                    Semantic retrieval at qualification & outreach
```

## Model Selection

Using **Llama 3 8B** (open-source, Meta) via **Groq** for inference:
- Open-source model (satisfies the requirement fully)
- Groq is just the inference engine (LPU hardware), not the model provider
- 8192 context window (enough for lead + RAG context)
- Fast inference via Groq's LPU (under 1s response)
- Free tier: 14,400 requests/day
- Upgrade path: `llama3-70b-8192` for higher quality, `mixtral-8x7b-32768` for longer context

### Why Llama 3 over other open-source models?

| Model | RAM | JSON | Reasoning | Verdict |
|-------|-----|------|-----------|---------|
| **Llama 3 8B** ✅ | ~6GB | ✅ Very good | ✅ Best in class | **Our choice** |
| Mistral 7B | ~5GB | ✅ Excellent | ⚠️ Good | Best if RAM < 8GB |
| Phi-3 Mini 3.8B | ~3GB | ⚠️ Struggles | ❌ Weak | Too small for pipeline |
| Mixtral 8x7B | ~26GB | ✅ Best | ✅ Best | Needs GPU workstation |
| Gemma 2 9B | ~7GB | ⚠️ OK | ⚠️ Good | Weaker JSON reliability |

Llama 3 8B hits the right balance of **JSON extraction** (Research Agent), **multi-criteria reasoning** (Qualification Agent), and **creative writing** (Sales Agent).

### Running Locally with Ollama (Groq swap-out)

To run fully offline without Groq, swap to Ollama in 3 steps:

**Step 1: Install Ollama & pull the model**
```bash
# Install: https://ollama.com
ollama pull llama3       # ~4.7GB (same model, local inference)
# or for RAM-constrained machines:
ollama pull mistral      # ~4.1GB
```

**Step 2: Swap the LLM client in `agents/base.py`**
```python
# Before (ChatGroq via Groq API):
from langchain_groq import ChatGroq
llm = ChatGroq(api_key=settings.groq_api_key, model=settings.groq_model, ...)

# After (ChatOllama via local Ollama):
from langchain_ollama import ChatOllama
llm = ChatOllama(model="llama3", temperature=temperature)
```
Everything else (retry logic, caching, LangSmith tracing) stays the same since
both are LangChain Runnables.

**Step 3: Update .env**
```bash
GROQ_MODEL=llama3   # used as a label only; ChatOllama ignores GROQ_API_KEY
```

Minimum hardware for local run:
- **8GB RAM**: Mistral 7B (quantized)
- **16GB RAM**: Llama 3 8B (recommended)
- **GPU (8GB VRAM)**: Llama 3 8B at full speed

## Fine-Tuning Strategy

Fine-tuning is not needed for v1. Few-shot prompting with RAG handles qualification well enough for this use case.

When fine-tuning would actually help:
- After collecting 500+ human-labeled lead qualification examples
- Dataset format: `{"prompt": "<lead_info>", "completion": "<score + reason>"}`
- Method: QLoRA with Unsloth (4-bit quantization, ~10GB VRAM)
- Base model: Llama 3 8B, fine-tuned on internal sales qualification history

## Observability

Two-tier observability strategy:

**LangSmith (LLM-level tracing)** (set `LANGCHAIN_API_KEY` in `.env` to enable):
- Every LLM call traced automatically (prompt, response, token count, latency)
- Agents use `langchain_groq.ChatGroq`, a LangChain Runnable, so tracing is zero-config
- Full LangGraph pipeline run visible as a parent trace with per-agent child spans
- Hallucination warnings surfaced as events on the trace

**Custom metrics (business-level)**:
- **Dashboard** at `GET /`: pipeline log, latency, lead quality, live run status
- **Metrics API** at `GET /metrics`: JSONL-backed aggregated pipeline stats
- Structured JSON logs in `data/logs/app.log` with 8-char correlation IDs per run
- Each agent logs decisions to `state["messages"]` (visible in dashboard log panel)
- Hallucination prevention via RAG grounding on all product claims
- Lead quality tracked via `qualification_score` distribution

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | **Dashboard UI** (lead cards, pipeline runner, metrics) |
| `/generate-leads` | POST | Run full multi-agent pipeline |
| `/leads` | GET | Retrieve stored leads (`?status=outreach_ready`) |
| `/ingest-knowledge` | POST | Build RAG from humanmaximizer.com |
| `/metrics` | GET | Pipeline observability summary |
| `/health` | GET | Dependency health check (Redis, model, embeddings) |
| `/docs` | GET | Swagger UI (interactive API docs) |

## Scaling

- Each agent is stateless, so horizontal scaling is straightforward
- ChromaDB can be swapped for pgvector (PostgreSQL) at scale
- Redis queue for async lead processing
- Dashboard is a single static HTML file (can be deployed to any CDN)
- Docker Compose today, Kubernetes when needed
