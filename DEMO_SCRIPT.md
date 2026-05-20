# Demo Video Script — AI Lead Generation & Research Assistant
**Total runtime: ~8 minutes | Razor Infotech Take-Home Assignment**

---

## [0:00 – 0:45] Opening — What We Built

**Say:**
> "Hi, I'm Priyanshu. I'll walk you through the AI-powered Lead Generation and Research Assistant
> I built for this assignment. The system autonomously finds, qualifies, and drafts personalized
> outreach emails for HRMS software prospects — using a multi-agent pipeline powered by
> Llama 3.1 running through Groq, grounded in real HumanMaximizer.com product content via RAG."

**Show:** GitHub repo — `github.com/PriyanshuGeTRekT/AI-Lead-Generation-Research-Agent-`

**Say:**
> "Everything runs in Docker — one command to start. Let me show you the architecture first,
> then run the live pipeline."

---

## [0:45 – 2:30] Architecture Overview

**Show:** Open `AI_Lead_Gen_Architecture.pptx`, slide 3 (Multi-Agent Architecture)

**Say:**
> "The core pattern is a **Supervisor Graph** using LangGraph's StateGraph. I chose this over
> a simple sequential pipeline because it gives us conditional routing — if a lead doesn't
> qualify, we stop processing it immediately instead of wasting LLM calls generating emails
> for bad leads. The Supervisor reads a `next` field from shared state to decide: qualify,
> pitch, or end."

**Point to the 3 agents:**
> "Three specialized agents:
> - **Research Agent** — searches the web using DuckDuckGo, scrapes company websites,
>   extracts structured lead data via Llama 3.1
> - **Qualification Agent** — scores each lead 0-10 using RAG-grounded criteria. It retrieves
>   real HumanMaximizer product info from ChromaDB before scoring, so the LLM can't hallucinate
>   features we don't have
> - **Sales Agent** — writes a personalized outreach email per lead, again grounded in RAG
>   context, with a 3-layer hallucination guard"

**Show:** Slide 4 (RAG Pipeline)

**Say:**
> "The RAG pipeline scraped humanmaximizer.com, chunked it into 500-token segments with
> 50-token overlap, embedded it using all-MiniLM-L6-v2 — a lightweight but effective model —
> stored in ChromaDB with cosine similarity search. Each agent queries this before generating
> any product claims."

---

## [2:30 – 3:15] Security & Production Features

**Show:** Slide 8 (Security & Edge Cases), briefly

**Say:**
> "A few production concerns I addressed:
> - **Prompt injection protection** — keyword inputs are scanned for regex patterns like
>   'ignore instructions' or 'DROP TABLE', then filtered through an allowlist of safe characters
> - **Rate limiting** — Redis atomic INCR ensures 10 requests/minute per IP, with no race
>   conditions even under horizontal scaling
> - **Lead deduplication** — Redis 24-hour window prevents the same company being processed
>   twice and burning LLM quota
> - **LLM caching** — identical company queries return cached results in ~5ms instead of ~2s,
>   saving Groq API calls"

---

## [3:15 – 3:45] Starting the System

**Show:** Terminal

```bash
cd ai-lead-gen
docker compose up -d
```

**Say:**
> "One command. Docker pulls Redis 7 Alpine, builds the FastAPI app with all dependencies.
> Redis starts first, and the API waits for the Redis health check before accepting traffic.
> Let's hit the health endpoint."

```bash
curl http://localhost:8000/health
```

**Show the response:**
```json
{
  "status": "ok",
  "dependencies": {
    "redis": "connected",
    "groq_model": "llama-3.1-8b-instant",
    "embed_model": "all-MiniLM-L6-v2"
  }
}
```

**Say:** "Redis connected, model loaded, RAG model ready."

---

## [3:45 – 4:15] RAG Knowledge Ingestion

**Show:** Terminal

```bash
curl -X POST http://localhost:8000/ingest-knowledge
```

**Say:**
> "Before generating leads, we build the RAG knowledge base by scraping HumanMaximizer.com.
> This endpoint is idempotent — if the vector store already exists, it skips re-ingestion.
> The scraper fetches each page, chunks it, embeds it, and stores in ChromaDB.
> We do this once at startup."

---

## [4:15 – 6:30] Live Pipeline Run

**Show:** Open Swagger UI at `http://localhost:8000/docs`

**Say:**
> "The main endpoint — POST /generate-leads — takes a keyword describing the target market.
> Let me run it with 'manufacturing company India 500 employees HRMS'."

**Navigate to POST /generate-leads, click Try It Out, enter keyword, Execute.**

**While waiting (~25 seconds), say:**
> "What's happening right now:
> 1. Research Agent searches DuckDuckGo for Indian manufacturing companies
> 2. For each result, it scrapes the website and calls Llama 3.1 to extract structured data
> 3. Redis deduplication ensures we don't process the same company twice
> 4. Each extracted lead flows to the Qualification Agent, which retrieves HumanMaximizer
>    product context from ChromaDB and scores the lead
> 5. Leads scoring ≥5.0 go to the Sales Agent for outreach generation"

**Show the response and highlight:**

```json
{
  "summary": {
    "total": 5,
    "qualified": 4,
    "disqualified": 0
  },
  "pipeline_log": [
    "Research Agent: Found 5 leads",
    "Qualification Agent: 5 qualified, 0 disqualified",
    "Sales Agent: 4 outreach drafts generated"
  ]
}
```

**Say:** "Five unique leads found, five qualified with an average score of 8.5 out of 10,
four personalized outreach emails generated."

**Scroll to a lead and show the outreach email:**
> "Look at this email — it opens with something specific to the company's pain point,
> connects it to HumanMaximizer's capabilities using only content from our RAG store,
> and ends with a low-friction CTA. The `follow_up_note` is an internal note the agent
> generated explaining why it chose that angle. The `hallucination_confidence` score
> tells you how grounded this email is in our actual product knowledge."

---

## [6:30 – 7:15] Observability & Monitoring

**Show:**

```bash
curl http://localhost:8000/metrics
```

**Say:**
> "The metrics endpoint aggregates all pipeline events logged to a JSONL file.
> You can see average latency per stage, hallucination warning count, and lead quality
> statistics across all runs. Each log line in the file carries a correlation ID that
> links every agent's action in a single run end-to-end.
>
> For production, you'd pipe this to Datadog or CloudWatch since logs are JSON-structured.
> I also integrated optional LangSmith tracing — if you set a LANGCHAIN_API_KEY,
> every LangGraph invocation appears in the LangSmith dashboard with full agent trace,
> token counts, and latency breakdown per node."

**Show:** `docker logs ai-lead-gen --tail 20`

> "Structured logs: timestamp, correlation ID, agent name, message. Every agent in the
> same pipeline run shares the same 8-character correlation ID. You can grep a single ID
> to see the full trace."

---

## [7:15 – 8:00] Closing — Architectural Decisions & Trade-offs

**Show:** Slide 9 (Architectural Decisions) or just speak

**Say:**
> "A few key decisions I want to call out:
>
> **Why Supervisor pattern over Sequential?** Flexibility. A sequential pipeline wastes
> compute generating emails for leads that score 2 out of 10. The Supervisor routes
> directly to END for low-quality leads.
>
> **Why Groq for inference?** The assignment needs an open-source model — Llama 3.1 is
> Meta's open-source LLM. Groq is just the inference engine that runs it 10x faster than
> a local setup, meeting the deadline. The Ollama swap-out is documented in the README —
> one environment variable change.
>
> **Why Redis over in-memory for rate limiting?** Atomic INCR operations — no race
> conditions under multiple API replicas. In-memory counters break horizontally.
>
> **What I'd do differently at production scale?** Add a proper message queue like
> Celery + SQS for async pipeline execution, replace the JSONL metrics file with Prometheus,
> and add a human-in-the-loop review step before outreach emails are sent."

**Final shot:** Show the architecture deck slide 10 (Tech Stack Requirements Checklist)

> "All assignment requirements met. Repository is at the link I shared. Thank you."

---

## Quick Reference for Interviewers

| Endpoint | Purpose |
|----------|---------|
| `POST /ingest-knowledge` | Build RAG from humanmaximizer.com |
| `POST /generate-leads` | Run full multi-agent pipeline |
| `GET /leads?status=outreach_ready` | Retrieve qualified leads |
| `GET /metrics` | Pipeline observability summary |
| `GET /health` | Dependency health check |
| `GET /docs` | Swagger UI |

| Component | Technology |
|-----------|-----------|
| LLM | Llama 3.1 8B via Groq API |
| Orchestration | LangGraph StateGraph |
| RAG Vector Store | ChromaDB |
| Embeddings | all-MiniLM-L6-v2 (HuggingFace) |
| Caching / Rate Limiting | Redis 7 Alpine |
| API Framework | FastAPI |
| Logging | Loguru (structured JSON) |
| Observability | LangSmith + custom JSONL metrics |
| Containerization | Docker Compose |
