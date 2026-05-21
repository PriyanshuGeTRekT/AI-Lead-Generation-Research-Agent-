# AI Lead Generation & Research Agent

An AI-powered lead generation system for HRMS software sales, built with a **Supervisor multi-agent architecture** using LangGraph, DeepSeek V3 (primary) / Groq Llama 3.1 (fallback), RAG, and real B2B contact databases. The pipeline discovers leads from multiple sources, scores them with structured LLM output, enriches them with decision-maker contacts, and routes high-quality leads through a human review step before outreach.

**Live dashboard** at `http://localhost:8000` (no curl required).

![Dashboard](https://img.shields.io/badge/UI-Dashboard-teal) ![API](https://img.shields.io/badge/API-FastAPI-green) ![LLM](https://img.shields.io/badge/LLM-DeepSeek%20V3-blue) ![Redis](https://img.shields.io/badge/Cache-Redis-red) ![Celery](https://img.shields.io/badge/Queue-Celery-brightgreen) ![Instantly](https://img.shields.io/badge/B2B-Instantly.ai-purple)

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
     │ search + LLM   │  │ RAG+LLM  │  │ 4-touch sequence   │
     └──────┬─────────┘  └──────────┘  └────────┬────────────┘
            │                │                   │
            ▼                ▼                   ▼
   ┌─────────────────┐  Score 0-10       ┌──────────────────┐
   │ Instantly.ai    │  ≥5 → Sales       │  Human Review    │
   │ (160M contacts) │  <5 → Discard     │  (Slack, opt-in) │
   │ Serper.dev      │                   └────────┬─────────┘
   │ (Google Search) │                            │
   └─────────────────┘               approve → outreach_ready
   + LinkedIn enrichment             reject  → disqualified
   + tech stack detection
   dedup by domain + Redis 24h cache

   LLM Priority:
   DeepSeek V3 (primary, 500 req/min) → Groq Llama 3.1 (fallback)

   Async path (Celery worker):
   ┌──────┐  POST /generate-leads   ┌────────────────┐
   │ API  │ ──── run_id returned ──▶│ Celery Worker  │
   │      │◀─ poll /pipeline-status─│ (background)   │
   └──────┘                         └────────────────┘
   Dashboard polls every 3s, shows live stage progress

   Sync fallback (no Celery worker):
   /generate-leads blocks and returns leads directly

   Vector stores:
   ChromaDB (default)  or  pgvector on PostgreSQL (USE_PGVECTOR=true)
```

## Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Agent Orchestration | LangGraph | Conditional routing, shared state, early exit |
| LLM (Primary) | DeepSeek V3 (`deepseek-chat`) | 500 req/min, OpenAI-compatible, much faster than free-tier Groq |
| LLM (Fallback) | Llama 3.1 8B via Groq | Open-source model, sub-second LPU inference |
| LLM Client | langchain-openai + langchain-groq | LangChain Runnables — automatic LangSmith tracing on both |
| Vector Store | ChromaDB | Persistent, local, no infra needed |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Open-source, HuggingFace |
| B2B Contact Database | Instantly.ai (160M+ contacts) | Pre-enriched leads: DM name, email, LinkedIn, title |
| Web Search | Serper.dev (Google Search API) | Real Google results, multi-query with 12 city/industry variants |
| LinkedIn Enrichment | Serper.dev → LinkedIn scrape | Decision maker name, title, LinkedIn URL per company |
| Tech Stack Detection | `tools/tech_stack_detector.py` | Identifies current HR tools → personalizes pitch angle |
| Structured Output | LangChain `.with_structured_output()` + Pydantic | Schema-enforced LLM responses |
| Human Review | Slack Incoming Webhooks + Block Kit | Approve/reject leads before outreach |
| Async Queue | Celery + Redis (DB 1) | Non-blocking pipeline, retries, job status |
| Caching & Dedup | Redis (DB 0) | LLM response cache + 24h lead dedup |
| Vector Store (scale) | pgvector on PostgreSQL | Production-grade at high lead volume |
| API | FastAPI | Async, auto-docs at /docs |
| Observability | LangSmith + custom JSONL metrics | LLM-level + business-level tracing |
| Containerization | Docker Compose | 5 containers: api, redis, celery_worker, celery_beat, postgres |

## Quick Start

### 1. Prerequisites
- Docker & Docker Compose installed
- API key for at least one LLM provider:
  - **DeepSeek** (recommended): [platform.deepseek.com](https://platform.deepseek.com) — higher rate limits, very fast
  - **Groq** (free fallback): [console.groq.com](https://console.groq.com)
- (Optional) Serper.dev API key from [serper.dev](https://serper.dev) — 2,500 free queries/month
- (Optional) Instantly.ai API key from [instantly.ai](https://instantly.ai) — 1,000 free lead-finder credits/month
- (Optional) LangSmith API key from [smith.langchain.com](https://smith.langchain.com)
- (Optional) Slack Incoming Webhook URL for human-in-the-loop review

### 2. Setup
```bash
git clone <repo>
cd ai-lead-gen
cp .env.example .env
# Edit .env — add DEEPSEEK_API_KEY (or GROQ_API_KEY as fallback)
```

Key `.env` variables:
```
# Primary LLM — DeepSeek (higher rate limits, faster pipelines)
DEEPSEEK_API_KEY=your_deepseek_key
DEEPSEEK_MODEL=deepseek-chat

# Fallback LLM — Groq (used if DEEPSEEK_API_KEY is empty)
GROQ_API_KEY=your_groq_key
GROQ_MODEL=llama-3.1-8b-instant

# Lead sources (both optional — pipeline works without them)
SERPER_API_KEY=your_serper_key       # Google Search results
INSTANTLY_API_KEY=your_instantly_key # B2B contact database (1k free credits)

# Observability & notifications (all optional)
LANGCHAIN_API_KEY=your_ls_key        # LangSmith tracing
SLACK_WEBHOOK_URL=https://hooks...   # Human review via Slack
BASE_URL=http://localhost:8000        # Used in Slack approve/reject links
```

### 3. Run

**Minimal (default): API + Redis only**
```bash
docker compose up --build
```

**Full stack: adds Celery async worker + PostgreSQL/pgvector**
```bash
docker compose --profile full up --build
```

The default mode works perfectly for demos. The full stack enables async pipeline execution (non-blocking API) and pgvector as the vector store (`USE_PGVECTOR=true`).

### 4. Build Knowledge Base (Run Once)

From the dashboard at `http://localhost:8000`, click **"Re-ingest RAG Knowledge"**, or via API:
```bash
curl -X POST http://localhost:8000/ingest-knowledge
```
This scrapes humanmaximizer.com, chunks the content, embeds it with `all-MiniLM-L6-v2`, and stores it in ChromaDB. Safe to call multiple times — skips if already built.

### 5. Generate Leads

**Via Dashboard** (recommended):
Open `http://localhost:8000`, enter a keyword, set the **max leads slider** (1 for a quick demo, up to 100 for a full run), and click **"Generate Leads"**.

If the Celery worker is running (full stack), the dashboard shows a live progress panel with three stages (Research → Qualify → Sales), an elapsed timer, and estimated completion time. It polls the `/pipeline-status/{run_id}` endpoint every 3 seconds automatically.

New leads are prepended to the front of the results (newest first) and numbered `#1 / N`. Running the pipeline a second time only shows new leads — duplicates from the previous run are hidden automatically.

**Via API:**
```bash
curl -X POST http://localhost:8000/generate-leads \
  -H "Content-Type: application/json" \
  -d '{"keyword": "manufacturing company India 200 employees"}'
```

If a Celery worker is running, returns immediately with `{"status": "queued", "run_id": "abc123"}`.
If no worker, runs synchronously and returns leads directly.

### 6. View Results

```bash
# All leads
curl http://localhost:8000/leads

# Only outreach-ready leads
curl http://localhost:8000/leads?status=outreach_ready

# Leads waiting for human review
curl http://localhost:8000/leads/pending-review
```

### 7. Flush Cache (for a fresh run)

```bash
curl -X POST http://localhost:8000/flush-cache
```

Clears the Redis deduplication cache and Celery result backend so the next run processes companies fresh. Useful between demo runs.

### Dashboard UI

Open **http://localhost:8000** in your browser:

- **Keyword input** with "Generate Leads" button
- **Max leads slider** (1–100): drag to 1 for a fast single-lead demo, 50 for a standard run
- **Live progress panel** (async mode): animated Research → Qualify → Sales stage tracker with elapsed timer and lead count live-updating
- **Lead cards** numbered `#N / total`, with score badges, pain point tags, decision maker info, tech stack tags, and generated outreach emails
- **Cross-run deduplication**: leads seen in a previous run in the same browser session are hidden — only genuinely new leads appear each time
- **Newest-first ordering**: new leads prepend to the top of the grid
- **Approve/Reject buttons** directly on each lead card (when status is `pending_review`)
- **Expandable outreach emails** with one-click copy — full 4-touch sequence (Day 1, 3, 7, 14)
- **Filter by status**: All / Outreach Ready / Pending Review / Disqualified / Researched
- **Export CSV**: download all leads as a spreadsheet
- **Metrics panel**: pipeline latency, lead counts, average score
- **Pipeline log sidebar**: agent decisions as they happen

### API Docs
Visit `http://localhost:8000/docs` for Swagger UI (auto-generated from FastAPI).

---

## Agent Flow

### 1. Research Agent
Takes a keyword and a `max_leads` target. Queries **Instantly.ai** (160M-contact B2B database) first — results arrive pre-enriched with decision maker name, email, LinkedIn URL, and job title, so no scraping is needed for those leads. Falls back to **Serper.dev** (Google Search API with India geo-targeting, 12 city/industry query variants for diversity) for any remaining slots. Serper results are filtered through a domain blocklist that removes aggregators (Wikipedia, LinkedIn, IndiaMART, Crunchbase, etc.) so only actual company websites reach the pipeline. Scrapes company homepages + contact pages, then uses DeepSeek V3 to extract structured lead info: company name, size, industry, location, decision makers, pain points. Stops the moment `max_leads` valid leads are collected — no fixed URL trial cap.

For each Serper-sourced lead (not pre-enriched by Instantly):
- **LinkedIn enrichment** (`tools/linkedin_enricher.py`): Serper-searches for `"[company] HR Manager LinkedIn"` to find decision maker name, title, and LinkedIn URL
- **Tech stack detection** (`tools/tech_stack_detector.py`): identifies current HR tools in use (SAP SuccessFactors, BambooHR, Darwinbox, manual Excel, etc.) to generate a personalized pitch angle
- **Address validation**: regex + token blacklist rejects scraped nav text, form labels, and UI strings — only real office addresses pass through
- **Email extraction**: regex extracts all `@domain` patterns from raw HTML, merged with LLM-extracted emails and de-duplicated

Results are deduplicated by root domain and checked against a Redis 24-hour seen-cache before being added to the pipeline.

### 2. Qualification Agent
Scores each lead 0–10 using RAG-grounded LLM reasoning with `QualificationResult` Pydantic schema via `.with_structured_output()`. Retrieves top-4 product context chunks from ChromaDB to match prospect needs against HumanMaximizer capabilities. Leads scoring ≥5.0 move forward; below threshold gets `status: disqualified`. Also generates a lead summary with a visual score bar (█░░░) and key signals for the dashboard.

### 3. Sales Agent
Generates personalized 4-touch outreach sequences for the top 5 qualified leads (by score). Each sequence includes:
- **Day 1**: Cold intro — opens with a company-specific insight, references their tech stack, single low-friction CTA
- **Day 3**: Short follow-up — adds one new value point (stat, result, or question)
- **Day 7**: Value email — industry insight, no ask, soft question to keep conversation alive
- **Day 14**: Break-up email — honest, brief, leaves the door open

Uses RAG to ground all product claims in actual HumanMaximizer feature documentation. Runs email verification (MX DNS lookup) on all extracted emails before the sequence is written. If `SLACK_WEBHOOK_URL` is set, sends a Slack Block Kit message with the Day 1 draft preview and Approve/Reject links. Without Slack, leads go directly to `outreach_ready`.

---

## Multi-Source Lead Discovery

The Research Agent searches three sources and deduplicates by domain:

- **Serper.dev** (`tools/web_search.py`): Real Google Search results via API (`gl=in` India geo-targeting). A domain blocklist filters out aggregators, job boards, and list pages so only actual company websites pass through. Falls back to a curated 15-company Indian dataset if no API key is set.
- **Naukri.com** (`tools/naukri_scraper.py`): Scrapes companies posting HR Manager, HRIS, or Payroll job listings — a strong buying signal.
- **Indeed.in** (`tools/indeed_scraper.py`): Same buying-signal logic from India's Indeed.

The buying signal logic: a company actively hiring HR staff is in an active HR spending cycle. They have headcount for HR, which means they have a payroll and compliance problem to solve, making them a direct prospect for HRMS software.

`tools/web_search.py` exposes `search_companies_multi_source(keyword)` which fans out to all three sources. The scrapers are fail-safe — any network error returns an empty list so the pipeline keeps running on whatever the other sources returned.

---

## Structured LLM Output

The qualification agent uses LangChain's `.with_structured_output()` bound to a Pydantic schema. Groq's Llama 3.1 implements this via tool calling, so the response is always schema-valid before it reaches application code.

Two Pydantic models in `models/schemas.py`:
- `LeadExtraction`: company info fields (name, size, industry, location, decision makers, pain points)
- `QualificationResult`: `score` (float 0-10), `reasoning` (str), `key_signals` (list), `recommended_action` (str)

`agents/base.py` adds `call_llm_structured(prompt, schema)`. Fallback: if `.with_structured_output()` raises, falls back to raw `call_llm()` + JSON parsing + `schema(**parsed)`. The pipeline never hard-fails on structured output issues.

---

## Human-in-the-Loop Review

When `SLACK_WEBHOOK_URL` is set in `.env`:

1. Sales Agent sets status to `pending_review`
2. `notifications/slack.py` sends a Slack Block Kit message: header, lead details (score, industry, location), pain points, email preview (first 250 chars), and Approve/Reject buttons
3. Approve button links to `{BASE_URL}/leads/{id}/approve` (GET + POST both supported for Slack compatibility)
4. Human clicks → API endpoint → status changes
5. Approved → `outreach_ready`, rejected → `disqualified`

Without `SLACK_WEBHOOK_URL`, the Sales Agent sets status directly to `outreach_ready`.

**Approve/Reject directly from the dashboard**: Lead cards with `pending_review` status show inline Approve and Reject buttons — no Slack required for approval via the UI.

**Setup:**
1. Create a Slack app at api.slack.com/apps
2. Enable Incoming Webhooks for your workspace
3. Copy the webhook URL to `.env` as `SLACK_WEBHOOK_URL`
4. Set `BASE_URL=http://your-server:8000` so the approve/reject links in Slack point to your server

---

## Async Pipeline (Celery)

Without Celery, `/generate-leads` blocks for 2–3 minutes while the pipeline runs. With a Celery worker running, the API dispatches the pipeline as a background task and returns `{"status": "queued", "run_id": "..."}` instantly.

**How the dashboard handles this:**
1. Clicks "Generate Leads" → POST `/generate-leads` → gets `run_id` back immediately
2. Shows a progress panel with 3 stages: Research (0–45s), Qualify (45–130s), Sales (130s+)
3. Polls `GET /pipeline-status/{run_id}` every 3 seconds
4. When status becomes `SUCCESS`, lead cards appear automatically

**The fallback is automatic**: if no Celery worker is reachable, `/generate-leads` runs synchronously and returns leads directly. The dashboard detects this (`status: success` on the first response) and skips polling entirely. No config change needed.

`worker.py` defines the Celery app. Redis DB 1 is used as both broker and result backend, separate from LLM cache on DB 0.

**Start the worker (without Docker):**
```bash
celery -A worker worker --loglevel=info --concurrency=2
```

**Via Docker (full stack):**
```bash
docker compose --profile full up --build
```

**Poll status manually:**
```bash
curl http://localhost:8000/pipeline-status/{run_id}
# Returns: {"run_id": "...", "status": "PENDING|STARTED|SUCCESS|FAILURE"}
```

---

## Scaling: pgvector

ChromaDB works well for a single instance. For production, pgvector gives ACID transactions, SQL tooling, and the same cosine similarity search ChromaDB provides.

**Activate:**
```
USE_PGVECTOR=true   # in .env
```

`rag/pgvector_store.py` connects via psycopg2, auto-creates a `lead_embeddings` table with a `vector(384)` column and an HNSW index (`vector_cosine_ops`). Same `all-MiniLM-L6-v2` embeddings as ChromaDB — switching is one flag with no code changes.

---

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

---

## Observability

**LangSmith (LLM-level tracing)** — set `LANGCHAIN_API_KEY` in `.env`:
- Every LLM call traced automatically: prompt, response, token count, latency
- Using ChatGroq (LangChain Runnable) means zero manual instrumentation
- Full LangGraph pipeline run visible as parent trace with per-agent child spans
- Hallucination warnings surfaced as events on the trace

**Custom metrics (business-level)**:
- `GET /metrics`: JSONL-backed pipeline stats (latency, lead counts, scores)
- Structured JSON logs in `data/logs/app.log` with correlation IDs per run
- Each agent logs decisions to `state["messages"]` (visible in dashboard log panel)

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard UI |
| `/generate-leads` | POST | Run full pipeline (async if worker running, sync fallback) |
| `/pipeline-status/{run_id}` | GET | Poll Celery task: PENDING / STARTED / SUCCESS / FAILURE |
| `/leads` | GET | Retrieve stored leads (`?status=outreach_ready`) |
| `/leads/pending-review` | GET | Leads awaiting human approval |
| `/leads/{id}/approve` | GET + POST | Approve a lead → `outreach_ready` |
| `/leads/{id}/reject` | GET + POST | Reject a lead → `disqualified` |
| `/ingest-knowledge` | POST | Build RAG knowledge base from humanmaximizer.com |
| `/flush-cache` | POST | Clear Redis dedup cache + Celery results for a fresh run |
| `/metrics` | GET | Pipeline observability summary |
| `/health` | GET | Dependency health check (Redis, model config) |
| `/docs` | GET | Swagger UI |

---

## Model Selection

Using **Llama 3.1 8B** (Meta, open-source) via **Groq** (LPU inference hardware):
- Open-source model — satisfies the assignment requirement
- Groq is the inference engine, not the model provider
- 8192 token context window
- Sub-second response time via Groq's LPU
- Free tier: 14,400 requests/day

| Model | JSON | Reasoning | Verdict |
|-------|------|-----------|---------|
| **Llama 3.1 8B** ✅ | ✅ Very good | ✅ Best in class | **Our choice** |
| Mistral 7B | ✅ Excellent | ⚠️ Good | Best if RAM < 8GB |
| Phi-3 Mini 3.8B | ⚠️ Struggles | ❌ Weak | Too small |
| Mixtral 8x7B | ✅ Best | ✅ Best | Needs GPU workstation |

### Running Locally with Ollama (no Groq)

```python
# agents/base.py
from langchain_ollama import ChatOllama
llm = ChatOllama(model="llama3", temperature=temperature)
```

Everything else (retry logic, caching, LangSmith tracing) stays the same since both are LangChain Runnables.

---

## Fine-Tuning Roadmap

The Slack approval workflow is the data collection mechanism. Every Approve/Reject click is a labeled training example. When 200+ labeled leads accumulate:

- Dataset format: Llama 3 chat template format (not raw prompt/completion strings)
- Method: QLoRA on Llama 3.1 8B via Unsloth (4-bit quantization, ~16GB VRAM)
- Benefit: qualification scores grounded in your specific customer profile

See `FINE_TUNING.md` for the complete training setup and evaluation guide.

---

## Scaling Notes

- Each agent is stateless → horizontal scaling straightforward
- ChromaDB → pgvector at scale via `USE_PGVECTOR=true`
- Celery + Redis for async processing under concurrent load
- Dashboard is a single static HTML file → deployable to any CDN
- Docker Compose today, Kubernetes when needed
- At Prometheus scale: expose `/metrics` as Prometheus endpoint, add Grafana dashboards for latency per agent, token counts, qualification pass rates
