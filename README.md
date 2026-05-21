# AI Lead Generation & Research Agent

An AI-powered lead generation system for HRMS software sales, built with a **Supervisor multi-agent architecture** using LangGraph, Groq (open-source LLMs), and RAG. The pipeline discovers leads from multiple sources, scores them with structured LLM output, and routes high-quality leads through a human review step before outreach.

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
     ┌────────────────┐  ┌──────────┐  ┌─────────────────────┐
     │ Research Agent │  │  Qualify │  │    Sales Agent      │
     │ Multi-source   │  │  Agent   │  │    RAG + LLM        │
     │ search + LLM   │  │ RAG+LLM  │  │ Pydantic structured │
     └──────┬─────────┘  └──────────┘  └────────┬────────────┘
            │                │                   │
            ▼                ▼                   ▼
   ┌─────────────────┐  Score 0-10       ┌──────────────────┐
   │ DuckDuckGo      │  ≥5 → Sales       │  Human Review    │
   │ Naukri.com      │  <5 → Discard     │  (Slack, opt-in) │
   │ Indeed.in       │                   └────────┬─────────┘
   └─────────────────┘                            │
   dedup by domain                    approve → outreach_ready
                                      reject  → disqualified

   Optional async path:
   ┌──────┐   Celery task    ┌────────────────┐
   │ API  │ ─────────────── ▶│  Celery Worker │
   └──────┘  (sync fallback  └────────────────┘
              if no worker)

   Vector stores:
   ChromaDB (default)  or  pgvector on PostgreSQL (USE_PGVECTOR=true)
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
| Multi-source Search | DuckDuckGo + Naukri.com + Indeed.in | Buying-signal lead discovery |
| Structured Output | LangChain `.with_structured_output()` + Pydantic | Schema-enforced LLM responses |
| Human Review | Slack Incoming Webhooks | Approve/reject leads before outreach |
| Async Queue | Celery + Redis (DB 1) | Non-blocking pipeline execution |
| Vector Store (scale) | pgvector on PostgreSQL | Production-grade at high lead volume |
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

Two startup modes depending on which features you need:

**Minimal (default): API + Redis + ChromaDB**
```bash
docker compose up --build
```

**Full stack: adds Celery worker + PostgreSQL/pgvector**
```bash
docker compose --profile full up --build
```

The default mode works exactly as before. The full stack enables async pipeline execution and pgvector as the vector store (set `USE_PGVECTOR=true` in `.env` when using the full profile).

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

If a Celery worker is running, this returns immediately with a `run_id`. Otherwise it executes synchronously and returns leads directly, with no configuration change needed.

### 6. View Results
```bash
# All leads
curl http://localhost:8000/leads

# Only outreach-ready leads
curl http://localhost:8000/leads?status=outreach_ready

# Leads waiting for human review (if SLACK_WEBHOOK_URL is set)
curl http://localhost:8000/leads/pending-review
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

1. **Research Agent**: takes a keyword, fans out to DuckDuckGo, Naukri.com, and Indeed.in, scrapes company websites, and uses Llama 3 to extract structured lead info (company, size, decision makers, pain points). Results are deduplicated by domain before passing downstream.

2. **Qualification Agent**: scores each lead 0 to 10 using RAG-grounded LLM reasoning with structured Pydantic output. It retrieves relevant HRMS product context from ChromaDB (or pgvector) to match prospect needs against product capabilities. Leads scoring 5 or above move forward, the rest get discarded.

3. **Sales Agent**: generates personalized outreach emails for qualified leads. Uses RAG to make sure product claims are grounded in actual HumanMaximizer features, not made up. If `SLACK_WEBHOOK_URL` is set, the lead goes to `pending_review` and a Slack message is sent for human approval before outreach.

## Multi-Source Lead Discovery

The Research Agent searches three sources in parallel and deduplicates by domain using `urllib.parse`:

- **DuckDuckGo**: broad web coverage, general company discovery
- **Naukri.com** (`tools/naukri_scraper.py`): scrapes companies posting HR Manager, HRIS, or Payroll job listings on naukri.com/hr-jobs-in-india
- **Indeed.in** (`tools/indeed_scraper.py`): scrapes the same signal from in.indeed.com

The buying signal logic: a company actively hiring HR staff is in an active HR spending cycle. They have headcount for HR, which means they have a payroll and compliance problem to solve, which makes them a direct prospect for HRMS software. This is a stronger signal than generic industry or company size.

Deduplication works at the domain level. If DuckDuckGo finds `acmecorp.com` and Naukri also returns `acmecorp.com`, only one lead is passed to the qualification pipeline. The scrapers are fail-safe: any network error or parsing failure returns an empty list so the pipeline keeps running on whatever results the other sources returned.

`tools/web_search.py` exposes `search_companies_multi_source(keyword)` which fans out to all three sources. `agents/research_agent.py` calls this instead of the original `search_companies()`.

## Structured LLM Output

The qualification agent previously called `call_llm()` and then parsed the JSON string from the response manually, which failed whenever the model returned prose instead of JSON.

The new approach uses LangChain's `.with_structured_output()` bound to a Pydantic schema. Groq's Llama 3.1 implements this via tool calling internally, so the response is always schema-valid before it reaches application code.

Two new Pydantic models in `models/schemas.py`:
- `LeadExtraction`: company info fields (name, size, industry, location, decision makers, pain points)
- `QualificationResult`: `score` (float 0-10), `reasoning` (str), `key_signals` (list), `recommended_action` (str)

`agents/base.py` adds `call_llm_structured(prompt, schema)` which calls `.with_structured_output(schema)`. `agents/qualification_agent.py` calls this method instead of `call_llm() + parse_json_response()`.

Fallback path: if `.with_structured_output()` raises (model or provider does not support it), the method falls back to raw `call_llm()` + JSON parsing + `schema(**parsed)`. The pipeline never hard-fails on structured output issues.

## Human-in-the-Loop Review

When `SLACK_WEBHOOK_URL` is set in `.env`, leads do not go directly to `outreach_ready` after email generation. Instead:

1. Sales Agent sets status to `pending_review`
2. `notifications/slack.py` sends a Slack Block Kit message with 5 blocks: a header, lead details (score, industry, location), pain points, an email preview (first 250 characters), and Approve/Reject buttons
3. Approve button links to `{BASE_URL}/leads/{id}/approve`, Reject links to `{BASE_URL}/leads/{id}/reject`
4. A human clicks Approve or Reject in Slack, which hits the API endpoint
5. Approved leads move to `outreach_ready`, rejected leads move to `disqualified`

Without `SLACK_WEBHOOK_URL` set, the Sales Agent sets status directly to `outreach_ready` and no Slack call is made. Behavior is identical to v1.

**Setup:**
1. Create a Slack app at api.slack.com/apps
2. Enable Incoming Webhooks for your workspace
3. Copy the webhook URL to `.env` as `SLACK_WEBHOOK_URL`

**New API endpoints:**
- `GET /leads/pending-review`: list all leads awaiting human approval
- `POST /leads/{id}/approve`: set lead status to `outreach_ready`
- `POST /leads/{id}/reject`: set lead status to `disqualified`

## Async Pipeline (Celery)

Without Celery, `/generate-leads` blocks for 20-30 seconds while the pipeline runs. That is fine for demos and single-user setups, but breaks under concurrent load.

With a Celery worker running, the API dispatches the pipeline as a background task and returns `{"status": "queued", "run_id": "..."}` instantly. The caller polls `GET /pipeline-status/{run_id}` for state (PENDING, STARTED, SUCCESS, FAILURE) and the result when done.

The fallback is automatic: if the worker is not reachable (import error or connection refused), `/generate-leads` silently runs synchronously and returns leads directly. No config change, no error.

`worker.py` at the project root defines the Celery app. It uses Redis DB 1 as both broker and result backend, keeping it separate from the LLM cache on Redis DB 0.

**Start the worker:**
```bash
celery -A worker worker --loglevel=info --concurrency=2
```

Or use the full Docker Compose profile which starts it automatically:
```bash
docker compose --profile full up --build
```

**Poll status:**
```bash
curl http://localhost:8000/pipeline-status/{run_id}
```

## Scaling: pgvector

ChromaDB works well for a single instance with a few thousand documents. When you have multiple concurrent users or your lead data already lives in PostgreSQL, pgvector is the better choice.

pgvector gives you: ACID transactions, SQL tooling (joins, filtering, backups), fewer infrastructure services to operate, and the same cosine similarity search ChromaDB provides.

**How to activate:**
```
USE_PGVECTOR=true   # in .env
```

`rag/pgvector_store.py` defines `PgVectorStore`. It connects via psycopg2, auto-creates a `lead_embeddings` table with a `vector(384)` column and an HNSW index (`vector_cosine_ops`). It uses the same `all-MiniLM-L6-v2` embeddings as ChromaDB, so switching is one flag with no embedding changes.

The full Docker Compose profile starts a `pgvector/pgvector:pg16` container with a named volume for persistence and a health check. ChromaDB remains the default when `USE_PGVECTOR` is not set.

**Migration path:** export ChromaDB documents, import into pgvector via `PgVectorStore.add_documents()`. The interface is identical so no agent code changes.

## RAG Pipeline

```
humanmaximizer.com → Scrape → Chunk (500 tokens, 50 overlap)
                                  ↓
                    HuggingFace Embeddings (all-MiniLM-L6-v2)
                                  ↓
                    ChromaDB or pgvector (cosine similarity index)
                                  ↓
                    Semantic retrieval at qualification & outreach
```

## Fine-Tuning Roadmap

Few-shot prompting with RAG handles qualification well enough for v1. Fine-tuning becomes valuable once you have enough human-labeled examples to train on.

The Slack approval workflow is the data collection mechanism. Every time a human clicks Approve or Reject on a lead, that decision is a labeled training example: the lead info is the prompt, and the human decision plus the LLM's score and reasoning is the completion.

When to fine-tune: after 200+ human-approved and rejected leads accumulate from the Slack review flow.

- Dataset format: `{"prompt": "<lead_info>", "completion": "<score + reasoning>"}` sourced from human-approved leads
- Method: QLoRA on Llama 3 8B using Unsloth (4-bit quantization, approximately 10GB VRAM)
- Benefit: qualification scores grounded in your specific customer profile, not general LLM reasoning about what makes a good HRMS prospect

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
| `/generate-leads` | POST | Run full multi-agent pipeline (async if worker running, sync fallback) |
| `/pipeline-status/{run_id}` | GET | Poll Celery task state: PENDING / STARTED / SUCCESS / FAILURE |
| `/leads` | GET | Retrieve stored leads (`?status=outreach_ready`) |
| `/leads/pending-review` | GET | List leads awaiting human approval via Slack |
| `/leads/{id}/approve` | POST | Approve a lead, moves status to `outreach_ready` |
| `/leads/{id}/reject` | POST | Reject a lead, moves status to `disqualified` |
| `/ingest-knowledge` | POST | Build RAG from humanmaximizer.com |
| `/metrics` | GET | Pipeline observability summary |
| `/health` | GET | Dependency health check (Redis, model, embeddings) |
| `/docs` | GET | Swagger UI (interactive API docs) |

## Scaling

- Each agent is stateless, so horizontal scaling is straightforward
- ChromaDB can be swapped for pgvector (PostgreSQL) at scale via `USE_PGVECTOR=true`
- Celery + Redis for async lead processing under concurrent load
- Dashboard is a single static HTML file (can be deployed to any CDN)
- Docker Compose today, Kubernetes when needed
