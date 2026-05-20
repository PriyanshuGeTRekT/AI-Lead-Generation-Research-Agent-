# Demo Video Script: AI Lead Generation & Research Assistant
**Total runtime: ~8 minutes | Razor Infotech Take-Home Assignment**

---

## [0:00 - 0:45] Opening: What We Built

**Say:**
> "Hi, I'm Priyanshu. I'll walk you through the AI-powered Lead Generation and Research Assistant
> I built for this assignment. The system autonomously finds, qualifies, and drafts personalized
> outreach emails for HRMS software prospects, using a multi-agent pipeline powered by
> Llama 3.1 running through Groq, grounded in real HumanMaximizer.com product content via RAG."

**Show:** GitHub repo at `github.com/PriyanshuGeTRekT/AI-Lead-Generation-Research-Agent-`

**Say:**
> "Everything runs in Docker, one command to start. Let me show you the architecture first,
> then run the live pipeline."

---

## [0:45 - 2:30] Architecture Overview

**Show:** Open `AI_Lead_Gen_Architecture.pptx`, slide 3 (Multi-Agent Architecture)

**Say:**
> "The core pattern is a **Supervisor Graph** using LangGraph's StateGraph. I chose this over
> a simple sequential pipeline because it gives us conditional routing. If a lead doesn't
> qualify, we stop processing it right there instead of wasting LLM calls generating emails
> for bad leads. The Supervisor reads a `next` field from shared state to decide: qualify,
> pitch, or end."

**Point to the 3 agents:**
> "Three specialized agents:
> - **Research Agent**: searches the web using DuckDuckGo, scrapes company websites,
>   and extracts structured lead data via Llama 3.1
> - **Qualification Agent**: scores each lead 0-10 using RAG-grounded criteria. It retrieves
>   real HumanMaximizer product info from ChromaDB before scoring, so the LLM can't hallucinate
>   features we don't have
> - **Sales Agent**: writes a personalized outreach email per lead, also grounded in RAG
>   context, with a 3-layer hallucination guard"

**Show:** Slide 4 (RAG Pipeline)

**Say:**
> "The RAG pipeline scraped humanmaximizer.com, chunked it into 500-token segments with
> 50-token overlap, embedded it using all-MiniLM-L6-v2 (a lightweight but effective model),
> and stored it in ChromaDB with cosine similarity search. Each agent queries this before
> generating any product claims."

---

## [2:30 - 3:15] Security & Production Features

**Show:** Slide 8 (Security & Edge Cases), briefly

**Say:**
> "A few production concerns I addressed:
> - **Prompt injection protection**: keyword inputs are scanned for regex patterns like
>   'ignore instructions' or 'DROP TABLE', then filtered through an allowlist of safe characters
> - **Rate limiting**: Redis atomic INCR ensures 10 requests/minute per IP, with no race
>   conditions even under horizontal scaling
> - **Lead deduplication**: Redis 24-hour window prevents the same company being processed
>   twice and burning LLM quota
> - **LLM caching**: identical company queries return cached results in ~5ms instead of ~2s,
>   saving Groq API calls"

---

## [3:15 - 3:45] Starting the System

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

## [3:45 - 4:15] RAG Knowledge Ingestion

**Show:** Dashboard, click **"Re-ingest RAG Knowledge"** button in the sidebar.

**Say:**
> "Before generating leads, we build the RAG knowledge base by scraping HumanMaximizer.com.
> The button is idempotent. If the vector store already exists, it skips and shows a message.
> The scraper fetches each page, chunks it into 500-token segments, embeds with all-MiniLM-L6-v2,
> and stores in ChromaDB. We do this once. Every subsequent pipeline run queries this store."

---

## [4:15 - 6:30] Live Pipeline Run

**Show:** Dashboard at `http://localhost:8000`

**Say:**
> "This is the lead generation dashboard, a single-page app built into the system.
> No Swagger, no JSON scrolling. The keyword is pre-filled. Let me hit Generate Leads."

**Click the teal "Generate Leads" button.**

**While the animated loading overlay shows (~25 seconds), say:**
> "The loading overlay shows all three agents progressing in sequence. You can watch
> the Research Agent step light up first, then Qualification, then Sales.
>
> What's happening under the hood:
> 1. Research Agent searches DuckDuckGo for Indian manufacturing companies
> 2. For each result, it scrapes the website and calls Llama 3.1 to extract structured data
> 3. Redis deduplication makes sure we don't process the same company twice
> 4. Each extracted lead flows to the Qualification Agent, which retrieves HumanMaximizer
>    product context from ChromaDB and scores the lead
> 5. Leads scoring 5.0 or above go to the Sales Agent for outreach generation"

**When the overlay closes, point to the dashboard and say:**
> "Five unique leads, all five qualified with a score of 8.5 out of 10. Zero disqualified.
> Five personalized outreach emails generated. The pipeline log on the left shows every
> agent's decision. The metrics strip shows average latency, about 17 seconds end-to-end."

**Click "View Outreach Email" on any card.**
> "Here's the generated outreach for Zomato. It opens with something specific to their
> gig worker pain points, connects it to HumanMaximizer's HRMS capabilities using only
> content retrieved from our RAG store, and ends with a low-friction demo CTA.
> The hallucination confidence score tells you how grounded this email is in actual
> product knowledge. There's also a copy button, one click to grab the email."

**Show the filter chips.**
> "I can filter by status. Outreach Ready shows only the leads ready to contact.
> Qualified shows leads that scored well but where email generation failed.
> This maps directly to a real sales workflow."

---

## [6:30 - 7:15] Observability & Monitoring

**Show:**

```bash
curl http://localhost:8000/metrics
```

**Say:**
> "The metrics endpoint aggregates all pipeline events logged to a JSONL file.
> You can see average latency per stage, hallucination warning count, and lead quality
> statistics across all runs. Each log line carries a correlation ID that links every
> agent's action in a single run, end to end.
>
> For production, you'd pipe this to Datadog or CloudWatch since logs are JSON-structured.
> I also integrated optional LangSmith tracing. If you set a LANGCHAIN_API_KEY,
> every LangGraph invocation appears in the LangSmith dashboard with full agent trace,
> token counts, and latency breakdown per node."

**Show:** `docker logs ai-lead-gen --tail 20`

> "Structured logs: timestamp, correlation ID, agent name, message. Every agent in the
> same pipeline run shares the same 8-character correlation ID. You can grep a single ID
> to see the full trace."

---

## [7:15 - 8:00] Closing: Architectural Decisions & Trade-offs

**Show:** Slide 9 (Architectural Decisions) or just speak

**Say:**
> "A few key decisions I want to call out:
>
> **Why Supervisor pattern over Sequential?** Flexibility. A sequential pipeline wastes
> compute generating emails for leads that score 2 out of 10. The Supervisor routes
> directly to END for low-quality leads.
>
> **Why Groq for inference?** The assignment needs an open-source model. Llama 3.1 is
> Meta's open-source LLM. Groq is just the inference engine that runs it 10x faster than
> a local setup, which helps hit the deadline. The Ollama swap-out is documented in the
> README, one environment variable change.
>
> **Why Redis over in-memory for rate limiting?** Atomic INCR operations mean no race
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
