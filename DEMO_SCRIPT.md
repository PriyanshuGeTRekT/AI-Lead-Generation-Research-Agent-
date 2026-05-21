# Demo Video Script: AI Lead Generation & Research Assistant
**Total runtime: ~10 minutes | Razor Infotech Take-Home Assignment**

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
> - **Research Agent**: this one is doing something smarter than a single DuckDuckGo search.
>   It fans out to three sources simultaneously: DuckDuckGo for general web coverage,
>   Naukri.com for companies posting HR Manager or Payroll job listings, and Indeed.in
>   for the same signal. The insight here is that a company actively hiring HR staff is
>   in an active HR spending cycle. They have headcount pressure, which means they have
>   a payroll and compliance problem, which makes them a direct prospect for HRMS software.
>   Results are deduplicated by domain so the same company never hits the pipeline twice
>   from two different sources.
> - **Qualification Agent**: scores each lead 0-10 using RAG-grounded criteria with structured
>   Pydantic output. The LLM response is schema-validated at the API call level via
>   LangChain's `.with_structured_output()`, so there are no JSON parsing failures in
>   production. It retrieves real HumanMaximizer product info from ChromaDB before scoring,
>   so the LLM cannot hallucinate features we do not have.
> - **Sales Agent**: writes a personalized outreach email per lead, also grounded in RAG
>   context, with a 3-layer hallucination guard. If a Slack webhook is configured, the
>   lead goes to a human review step before it ever touches a prospect's inbox."

**Say:**
> "In production, the `/generate-leads` endpoint dispatches the pipeline to a Celery worker
> over Redis and returns a run ID instantly. The caller polls `/pipeline-status/{run_id}`
> for completion. Without a worker running, it falls back silently to synchronous execution.
> The API contract is identical either way, so the demo dashboard works the same."

**Show:** Slide 4 (RAG Pipeline)

**Say:**
> "The RAG pipeline scraped humanmaximizer.com, chunked it into 500-token segments with
> 50-token overlap, embedded it using all-MiniLM-L6-v2 (a lightweight but effective model),
> and stored it in ChromaDB with cosine similarity search. Each agent queries this before
> generating any product claims. At scale, you swap ChromaDB for pgvector on PostgreSQL
> with one environment variable."

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
> 1. Research Agent fans out to DuckDuckGo, Naukri.com, and Indeed.in for Indian manufacturing companies
> 2. Results are deduplicated by domain, so a company appearing on both Naukri and DuckDuckGo is only processed once
> 3. For each unique company, the agent scrapes the website and calls Llama 3.1 to extract structured data
> 4. Redis deduplication makes sure we do not process the same company twice across pipeline runs
> 5. Each extracted lead flows to the Qualification Agent, which retrieves HumanMaximizer
>    product context from ChromaDB and scores the lead using structured Pydantic output
> 6. Leads scoring 5.0 or above go to the Sales Agent for outreach generation"

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

## [6:30 - 7:15] Human-in-the-Loop Review

**Show:** Terminal and Slack, side by side if possible

**Say:**
> "Now let me show the human review step. This is off by default. To enable it, set
> `SLACK_WEBHOOK_URL` in `.env`. With that set, leads after email generation land
> at `pending_review` instead of `outreach_ready`."

```bash
curl http://localhost:8000/leads/pending-review
```

**Say:**
> "These leads are waiting for a human to approve or reject them before anything
> is sent to a prospect.
>
> When a lead hits `pending_review`, the system sends a Slack Block Kit message.
> It has five blocks: a header with the company name and pipeline run ID, a details
> block showing the qualification score, industry, and location, a pain points block
> listing what the Research Agent extracted, an email preview block with the first
> 250 characters of the generated outreach, and two action buttons: Approve and Reject.
>
> Approve links to `POST /leads/{id}/approve`. Reject links to `POST /leads/{id}/reject`."

**Show:** Approve a lead via curl

```bash
curl -X POST http://localhost:8000/leads/{id}/approve
```

**Say:**
> "Approved. That lead is now `outreach_ready`. A rejected lead moves to `disqualified`
> and will not be processed again within the 24-hour deduplication window.
>
> Without `SLACK_WEBHOOK_URL` set, the Sales Agent writes `outreach_ready` directly
> and no Slack call is made. Behavior is identical to v1. Zero-config default."

---

## [7:15 - 8:00] Observability & Monitoring

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
>
> And here's something worth showing. All three agents use LangChain's ChatGroq wrapper
> instead of the raw Groq SDK. That one decision means LangSmith gets full visibility
> into every single LLM call automatically. Set LANGCHAIN_API_KEY in the env and you get
> the full LangGraph run as a parent trace, with each agent as a child span, and inside
> each span every prompt we sent, every response we got back, token counts, and latency.
> No extra instrumentation code needed anywhere."

**Show:** `docker logs ai-lead-gen --tail 20`

> "Structured logs: timestamp, correlation ID, agent name, message. Every agent in the
> same pipeline run shares the same 8-character correlation ID. You can grep a single ID
> to see the full trace."

---

## [8:00 - 9:00] Closing: Architectural Decisions & Trade-offs

**Show:** Slide 9 (Architectural Decisions) or just speak

**Say:**
> "A few key decisions I want to call out:
>
> **Why Supervisor pattern over Sequential?** Flexibility. A sequential pipeline wastes
> compute generating emails for leads that score 2 out of 10. The Supervisor routes
> directly to END for low-quality leads.
>
> **Why multi-source search?** DuckDuckGo alone finds companies by keyword. Naukri and
> Indeed find companies by behavior: actively hiring HR staff means an active HR budget.
> That is a stronger buying signal than company size or industry alone.
>
> **Why Celery over synchronous execution?** The synchronous path blocks for 20-30 seconds
> per pipeline run. Under concurrent load that saturates the FastAPI worker pool. Celery
> dispatches each run as a background task, returns a run ID instantly, and lets the caller
> poll for completion. The sync fallback means the API still works without a worker running,
> so development and demos are unaffected.
>
> **Why pgvector at scale?** ChromaDB is great for a single instance. When lead volume
> grows or your data already lives in PostgreSQL, pgvector gives you cosine similarity
> search inside the same database, with ACID transactions and SQL tooling. You activate
> it with one environment variable and nothing else changes.
>
> **Why Groq for inference?** The assignment needs an open-source model. Llama 3.1 is
> Meta's open-source LLM. Groq is just the inference engine that runs it 10x faster than
> a local setup, which helps hit the deadline. The Ollama swap-out is documented in the
> README, one environment variable change.
>
> **Why Redis over in-memory for rate limiting?** Atomic INCR operations mean no race
> conditions under multiple API replicas. In-memory counters break horizontally.
>
> **What I'd build next?** Once 200+ leads have been approved or rejected through the
> Slack review flow, that dataset is enough to run QLoRA fine-tuning on Llama 3 8B
> with Unsloth. The qualification scores would be grounded in your actual customer
> profile instead of general LLM reasoning."

**Final shot:** Show the architecture deck slide 10 (Tech Stack Requirements Checklist)

> "All assignment requirements met. Repository is at the link I shared. Thank you."

---

## Quick Reference for Interviewers

| Endpoint | Purpose |
|----------|---------|
| `POST /ingest-knowledge` | Build RAG from humanmaximizer.com |
| `POST /generate-leads` | Run full multi-agent pipeline (async if Celery worker running, sync fallback) |
| `GET /pipeline-status/{run_id}` | Poll Celery task: PENDING / STARTED / SUCCESS / FAILURE |
| `GET /leads?status=outreach_ready` | Retrieve qualified leads |
| `GET /leads/pending-review` | List leads waiting for human approval |
| `POST /leads/{id}/approve` | Approve a lead, moves to `outreach_ready` |
| `POST /leads/{id}/reject` | Reject a lead, moves to `disqualified` |
| `GET /metrics` | Pipeline observability summary |
| `GET /health` | Dependency health check |
| `GET /docs` | Swagger UI |

| Component | Technology |
|-----------|-----------|
| LLM | Llama 3.1 8B via Groq API |
| LLM Client | langchain-groq (ChatGroq) |
| Orchestration | LangGraph StateGraph |
| Lead Discovery | DuckDuckGo + Naukri.com + Indeed.in |
| Structured Output | LangChain `.with_structured_output()` + Pydantic |
| RAG Vector Store | ChromaDB (default) / pgvector on PostgreSQL (USE_PGVECTOR=true) |
| Embeddings | all-MiniLM-L6-v2 (HuggingFace) |
| Async Queue | Celery + Redis DB 1 |
| Human Review | Slack Incoming Webhooks |
| Caching / Rate Limiting | Redis 7 Alpine |
| API Framework | FastAPI |
| Logging | Loguru (structured JSON) |
| LLM Tracing | LangSmith (auto via ChatGroq) |
| Pipeline Metrics | Custom JSONL + /metrics API |
| Containerization | Docker Compose |
