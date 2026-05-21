# Demo Script & Walkthrough
## AI Lead Generation System — Razor Infotech Take-Home Assignment

> **This file is LOCAL ONLY. Do not commit to git.**
>
> This is a single combined file. The first section is your pre-recording checklist.
> The second section is the live script — every word to say, every action to take, and
> why each thing is happening so you can explain it confidently to the interviewer.

---

# PART 1: PRE-RECORDING CHECKLIST

Complete every item below before you hit record. Skipping any of these will cost you more time mid-recording than checking them now.

## System Setup

- [ ] **Docker Desktop is open** and not in a suspended state (whale icon in taskbar is steady, not animating)
- [ ] **Full stack is running**:
  ```bash
  docker compose --profile full up -d
  ```
  This starts 4 containers: `ai-lead-gen` (FastAPI API), `ai-lead-gen-redis` (Redis), `celery_worker` (Celery background worker), and `postgres` (pgvector). Wait for all to show as healthy:
  ```bash
  docker compose ps
  ```
  All four should show `Up` or `healthy`. The health check for the API container takes 30 seconds — wait for it before proceeding.

- [ ] **Flush old data for a clean demo**:
  ```bash
  # Delete old leads file so the dashboard starts empty
  del data\leads.json   (Windows CMD)
  # OR
  rm data/leads.json    (Git Bash / PowerShell)

  # Flush Redis dedup cache so old company domains aren't blocked
  curl -X POST http://localhost:8000/flush-cache
  ```

- [ ] **RAG knowledge base is ready** (run this now so it's instant on camera):
  ```bash
  curl -X POST http://localhost:8000/ingest-knowledge
  ```
  Expected response: `{"status": "skipped", ...}` (already built) OR `{"status": "success", "pages_scraped": ..., "chunks_stored": ...}` (first time). Either is fine.

- [ ] **Health check passes**:
  ```bash
  curl http://localhost:8000/health
  ```
  Should return: `{"status": "ok", "dependencies": {"redis": "connected", ...}}`

## Browser Tabs (open these before recording)

- [ ] Tab 1: `http://localhost:8000` — Dashboard (this is your main demo view)
- [ ] Tab 2: `http://localhost:8000/docs` — Swagger UI (for API walkthrough)
- [ ] Tab 3: `https://smith.langchain.com` — LangSmith traces (log in and have it ready)
- [ ] Tab 4: Your Slack workspace — The `#lead-gen-approvals` channel or wherever notifications appear

## Recording Setup

- [ ] Terminal font size: **18pt or larger** (small text is unreadable in video)
- [ ] Screen resolution: **1920×1080** in a window, not fullscreen (easier to switch apps on camera)
- [ ] Close unnecessary apps and notifications (turn on Do Not Disturb)
- [ ] Have your GitHub repo URL ready to say at the end
- [ ] **Do one practice run** end-to-end before recording. The pipeline takes 2–3 minutes, and you want to know exactly what to say during the wait.

---

# PART 2: DEMO SCRIPT

Read the **SAY** blocks aloud. Do the **DO** actions as you speak or right after the sentence ends. The **WHY** blocks are your mental notes — you don't read these verbatim, but they tell you *why* something is happening so you can answer follow-up questions confidently.

---

## [0:00 – 0:30] Opening

**SAY:**
"Hi. This is my submission for the Razor Infotech AI Architect take-home assignment. I built an AI-powered B2B lead generation system using a supervisor multi-agent architecture with LangGraph, FastAPI, Redis, Celery, ChromaDB for RAG, and Groq for running Llama 3.1 — an open-source model. Let me walk you through every layer of it."

**DO:** Start with your face or a title screen, then cut to the dashboard at `http://localhost:8000`.

---

## [0:30 – 1:30] Architecture Overview

**SAY:**
"Let me start with the architecture, because everything else will make more sense once you understand how the pieces connect."

"At the center is a LangGraph `StateGraph` with a Supervisor pattern. One orchestrator reads shared state and decides which specialist agent runs next. This is not a fixed linear pipeline — it is a dynamic routing system. That matters because a bad lead gets rejected early, before we waste LLM calls on it."

"There are three specialist agents. The **Research Agent** finds companies using Google Search via Serper.dev, plus scrapers for Naukri and Indeed. The **Qualification Agent** scores each company 0–10 using RAG context from ChromaDB. The **Sales Agent** writes personalized outreach emails and runs a hallucination guard before anything reaches a human."

"On top of that, there's a **Celery async queue** backed by Redis. When the pipeline runs, it does not block the API — the dashboard polls for results every 3 seconds while you watch the stages progress. And there's a **human-in-the-loop review** via Slack before any lead is marked ready for outreach."

**DO:** Point to the architecture diagram in the README (open `README.md` in the browser or show the architecture block in the GitHub repo), OR quickly sketch or describe it verbally.

**WHY:**
The Supervisor pattern is the core architectural decision. A sequential pipeline — `research → qualify → sales` always — wastes API quota on bad leads. The Supervisor lets the Qualification Agent short-circuit the Sales Agent when a lead scores below 5/10. LangGraph's `StateGraph` and `add_conditional_edges` implement this with a single `route()` function that reads the `next` field in shared state. One function to read, debug, or extend.

---

## [1:30 – 2:00] Docker Stack — One Command to Run Everything

**SAY:**
"The entire system runs with one Docker Compose command. Let me show you what's running."

**DO:** Switch to the terminal. Run:
```bash
docker compose ps
```

**SAY:**
"You can see four containers: the FastAPI API server, Redis, the Celery worker, and PostgreSQL with pgvector. Let me hit the health endpoint to confirm every dependency is reachable."

**DO:** Run:
```bash
curl http://localhost:8000/health
```

**SAY:**
"All green. Redis is connected on two separate databases — DB 0 for LLM caching and deduplication, DB 1 for Celery job queuing. The model is Llama 3.1 via Groq. This is the first check I'd do in production before routing any traffic."

**WHY:**
The two Redis databases are a deliberate separation. DB 0 is the LLM response cache (1-hour TTL, keyed by SHA-256 hash of the full prompt) and lead deduplication (24-hour TTL per domain). DB 1 is Celery's broker and result backend. Mixing them would mean a `flushall` for cache invalidation also kills all in-flight Celery job states. Keeping them on separate DBs means you can flush the cache independently. The Postgres container runs `pgvector/pgvector:pg16` — it is there if `USE_PGVECTOR=true` is set in `.env`, but ChromaDB is the default for this demo.

---

## [2:00 – 2:30] RAG Knowledge Ingestion — Building the Vector Store

**SAY:**
"Before the pipeline can qualify any leads, it needs to know what HumanMaximizer actually does. That's what the RAG ingestion step is for."

**DO:** Switch to the dashboard at `http://localhost:8000`. Point to the **"Re-ingest RAG Knowledge"** button and click it. OR run in terminal:
```bash
curl -X POST http://localhost:8000/ingest-knowledge
```

**SAY:**
"What just happened: the system scraped humanmaximizer.com — the client's product website — chunked the content into 500-token segments with 50-token overlap, embedded each chunk using the `all-MiniLM-L6-v2` sentence transformer from HuggingFace, and stored everything in ChromaDB as a local vector database."

"This is what RAG means: Retrieval-Augmented Generation. Instead of the LLM relying on what it learned during pretraining about HRMS software generically, every qualifying decision and every outreach email is grounded in actual product documentation retrieved at runtime. The ingest step runs once — or whenever the product content changes."

**WHY:**
RAG is the right approach here for two reasons. First, we have no training data yet, so fine-tuning the model is not an option. Second, product content changes — features get added, pricing changes, messaging evolves. With RAG, re-running the ingest endpoint updates the knowledge base in seconds. With fine-tuning, you'd need a full training run. The `is_knowledge_base_ready()` check makes this idempotent — calling it twice is safe, it skips if already built. The chunk size (500 tokens, 50 overlap) is tuned so each chunk is semantically coherent but small enough that the top-k retrieval returns focused, relevant context rather than sprawling passages.

---

## [2:30 – 4:30] Live Pipeline Run — Watching All Three Agents Work

**SAY:**
"Now let's run the pipeline live. I'll use the dashboard."

**DO:** Make sure you're on `http://localhost:8000`. The keyword input field should be visible. Type:
```
HRMS software company India
```
Then click **"Generate Leads"**.

**SAY:**
"The API returned a `run_id` immediately — the pipeline is running as a background Celery task. You can see the dashboard switched to a progress panel. There are three stages: Research, Qualify, Sales. Let me walk you through what's happening inside each one while we wait."

**WHY (Celery async path):**
POST `/generate-leads` dispatches a Celery task via Redis (DB 1) and returns `{"status": "queued", "run_id": "abc123"}` in milliseconds. The dashboard receives this, stores the `run_id`, and starts calling `GET /pipeline-status/{run_id}` every 3 seconds. Celery's result backend (also Redis DB 1) stores the job state — PENDING, STARTED, SUCCESS, FAILURE. The stage progress bar is time-estimated (Research: 0–45s, Qualify: 45–130s, Sales: 130s+) because the pipeline does not push incremental updates. This is an acceptable tradeoff versus the complexity of WebSocket streaming.

**SAY (while pipeline runs — Research stage):**
"The Research Agent just activated. It's calling three data sources in parallel."

"First: **Serper.dev**, which is Google's search API. It sends the keyword with `gl=in` — India geo-targeting — and the query appended with 'official website' to get company homepages, not directory pages. Every result URL goes through a domain blocklist that filters out Wikipedia, LinkedIn, IndiaMART, Crunchbase, Glassdoor — any page that's a list or aggregator rather than an actual company website."

"Second and third: **Naukri.com and Indeed.in scrapers**. These are job board scrapers that find companies actively posting HR Manager, HRIS, or Payroll roles. The signal is: a company hiring for HR is in an active HR spending cycle. They have a payroll problem. That's a much stronger buying signal than just appearing in a search result."

"All three sources are merged and deduplicated by root domain using Python's `urllib.parse`. If Serper and Naukri both return `acmecorp.com`, only one lead goes downstream. Then for each company, it scrapes the homepage — the first 3000 characters — and passes that raw text plus the search snippet to Llama 3.1."

**WHY (Serper vs DuckDuckGo):**
The original implementation used DuckDuckGo's unofficial Python library. In Docker and cloud environments, DuckDuckGo rate-limits heavily — often returning 0 results after the first call, forcing fallback to the curated dataset every time. Serper.dev is an official API providing real Google search results with 2,500 free queries per account. No credit card required. The India geo-targeting and "official website" query suffix were added specifically to get company homepages instead of aggregator pages, which was the main failure mode with DuckDuckGo.

**SAY (while pipeline runs — Qualify stage indicator appears):**
"Research is done. The Qualification Agent is now running on each company."

"For each lead, it retrieves the top 4 most semantically similar chunks from ChromaDB — the product knowledge we ingested earlier — using cosine similarity on 384-dimensional embeddings. It injects those chunks into the qualification prompt alongside the lead's company info and pain points, then calls Llama 3.1 via `ChatGroq`."

"The response comes back as a fully typed `QualificationResult` Pydantic object — not a string to parse, not JSON to regex out of markdown fences. LangChain's `.with_structured_output()` tells the model to return data matching the schema, and Groq implements this via tool-calling under the hood. The fields are: `score` (0–10 float), `reasoning` (string), `key_signals` (list), and `recommended_action`."

"Leads scoring below 5 are marked disqualified. The Supervisor sees the score and routes them to END — no Sales Agent call, no API quota spent."

"It also generates a visual summary with a score bar — like `Score: 8.5/10  ████████░░` — that shows up in Slack and on the dashboard."

**WHY (.with_structured_output):**
LLMs fail at JSON reliably. They add markdown fences, wrap JSON in prose, use inconsistent field names. The old approach called the LLM, got a string, and parsed it with a regex plus `json.loads` — fragile. `.with_structured_output(QualificationResult)` passes the Pydantic schema as a JSON Schema tool definition to the model. Groq's Llama 3.1 implementation returns structured data via tool calling. The result is a typed Python object before it reaches application code. There is still a fallback: if `.with_structured_output()` raises, it falls back to the old parsing path. But in practice, the structured path succeeds ~95% of the time, eliminating a whole category of runtime errors. **Critical**: the field names in the prompt's JSON template must exactly match the Pydantic schema's field names. During development, a mismatch (`qualification_score` vs `score`) caused every call to fall back to the parser, which then found mismatched keys. Both are now `score`, `reasoning`, `key_signals`, `recommended_action`.

**SAY (while pipeline runs — Sales stage indicator appears):**
"Qualification is done. The Sales Agent is running on every lead that passed the 5.0 threshold."

"For each qualified lead, it queries ChromaDB again — same retrieval process — to get the most relevant product context. It builds a prompt that gives the LLM the lead's pain points, the retrieved product features, and a five-point checklist: open with something specific about the company, mention a specific pain point, connect the solution to that pain point using only retrieved features, add a clear low-friction CTA, keep it under 150 words."

"After the email is generated, it goes through a hallucination guard before anything is saved. The guard checks three things: fabricated numbers like revenue figures or founding years, product claims that weren't in the retrieved chunks, and retrieval confidence — if the cosine distance was too high, the whole email is flagged as low-confidence. If the guard rejects it, the email is not saved. If it warns, the warning is logged to LangSmith."

"Because we have a Slack webhook configured, the Sales Agent sets status to `pending_review` instead of `outreach_ready`. That means a human has to approve every email before it can move forward."

**WHY (hallucination guard + human review):**
The hallucination guard is not optional. LLMs are confident writers. Without checking, the Sales Agent would write emails claiming features the product doesn't have, using precise-sounding but fabricated numbers. The guard catches this before it reaches a reviewer. But the guard only catches content issues — it cannot catch tone problems, judgment errors, or leads that scored 6.0 but are actually bad fits. That's what the human review step is for. The combination — automated guard + human gate — means the only emails that reach `outreach_ready` have passed both automated checks and a human judgment call.

---

## [4:30 – 5:30] Pipeline Results — Reading the Lead Cards

**SAY:**
"Results are in. Let me walk through what we're seeing."

**DO:** The lead cards should have appeared on the dashboard. Point to the first card.

**SAY:**
"Each lead card shows: the company name and website, the qualification score as a badge — let's say this one scored 8.2 out of 10 — the industry, location, and employee count, the key signals the Qualification Agent identified, the pain points inferred by the Research Agent from the scraped homepage, and a preview of the outreach email."

**DO:** Click to expand the outreach email on a card.

**SAY:**
"This email was generated by the Sales Agent with temperature 0.4 — higher than the 0.1 used for extraction and scoring, because email writing benefits from some stylistic variation. The email opens with something specific about the company, connects to a pain point that was pulled from their actual website, and makes a product claim that was verified against the RAG context."

"The copy button lets a sales rep grab the email in one click. Everything you see — the score, the pain points, the email — came from structured Pydantic models, not string parsing."

**DO:** Scroll through a few more cards. Point out the `pending_review` status badge.

**SAY:**
"Notice the status on each card: `pending_review`. No lead is `outreach_ready` until a human approves it. I can approve directly from the dashboard — or from Slack, which I'll show you next."

**WHY (status flow):**
The lead status field drives the entire routing logic. `researched` → `qualified` (by Qualification Agent) → `pending_review` (by Sales Agent when Slack is configured) → `outreach_ready` (human approval) OR `disqualified` (rejection or below threshold). Each status is a machine-readable signal. The `/leads?status=outreach_ready` endpoint is what a CRM integration would poll. The status field also persists to `data/leads.json` via atomic write (`os.replace()` after writing to a `.tmp` file) so a crash mid-write can never corrupt the file.

---

## [5:30 – 6:30] Human-in-the-Loop Review — Slack + Dashboard

**SAY:**
"Let me switch to Slack to show you the notification that was just sent."

**DO:** Switch to Slack. Find the notification in the channel.

**SAY:**
"When the Sales Agent finishes for each lead, it posts this message. You can see: the company name and score, the industry and location, the identified pain points, and the first 250 characters of the outreach email. There are two buttons: Approve and Reject."

**DO:** Point to the Approve button. Do NOT click it yet — explain it first.

**SAY:**
"When I click Approve, Slack sends an HTTP GET request to `{BASE_URL}/leads/{lead_id}/approve`. It's a GET, not a POST, because Slack's Block Kit buttons open URLs as links — they don't submit forms. So we added both GET and POST versions of the approve and reject endpoints. The GET versions call the same logic as the POST versions. Without this, clicking Approve in Slack returned a 405 Method Not Allowed."

**DO:** Click **Approve** on one lead in Slack.

**SAY:**
"Done. That lead's status just changed from `pending_review` to `outreach_ready`. Let me switch to the dashboard to confirm."

**DO:** Switch back to `http://localhost:8000`. The approved lead's card should now show `outreach_ready`.

**SAY:**
"Confirmed. You can also approve and reject directly from the dashboard cards without going to Slack — both paths call the same API endpoints. The dashboard approve button calls `POST /leads/{id}/approve`, the Slack link calls `GET /leads/{id}/approve`. Same result."

**WHY (approve/reject design):**
The Slack notification sends four pieces of information: company info, pain points, email preview, and the LLM's `follow_up_note` — an internal field that captures why the Sales Agent chose the angle it did. This gives the reviewer enough context to make a decision in under 30 seconds. The reviewer never needs to open the dashboard to approve a lead — they can do it entirely from Slack. But the dashboard provides an alternative for environments where Slack isn't configured.

---

## [6:30 – 7:30] Observability — LangSmith + Metrics + Logs

**SAY:**
"Let me show you the observability layer."

**DO:** Switch to `https://smith.langchain.com`. Log in and navigate to the `ai-lead-gen` project.

**SAY:**
"LangSmith is showing every LLM call from this pipeline run as a trace. I'm using `langchain_groq.ChatGroq` — a LangChain Runnable — instead of the raw Groq SDK. That single import choice means every call is automatically traced here with zero manual instrumentation: the exact prompt sent, the model's full response, token counts, and per-call latency."

**DO:** Click the most recent trace. Then click into a child span — pick the Qualification Agent's call.

**SAY:**
"You can see the full input prompt, the retrieved RAG context, and the structured output that came back. If a lead scored unexpectedly low or high, this is where you debug it — you have the complete chain of evidence. The parent trace is the full pipeline run. Each agent's LLM call is a child span under it."

**DO:** Go back to the terminal. Run:
```bash
curl http://localhost:8000/metrics
```

**SAY:**
"The metrics endpoint returns a business-level summary: total pipeline runs, leads generated, average score, pipeline latency. This is separate from LangSmith — LangSmith is LLM-level tracing, metrics is pipeline-level business analytics."

**DO:** Run:
```bash
docker logs ai-lead-gen --tail 20
```

**SAY:**
"Every log line is structured JSON with a correlation ID per run. In production you'd ship these to Datadog, CloudWatch, or an ELK stack. For a demo, they're written to `data/logs/app.log`."

**WHY (ChatGroq vs raw SDK):**
The raw Groq Python SDK (`groq.Groq().chat.completions.create()`) is invisible to LangSmith. LangSmith only auto-traces LangChain Runnable objects. By using `ChatGroq`, every call appears in LangSmith as a fully attributed child span under the parent LangGraph run. The tradeoff is an extra `langchain-groq` dependency — but the observability is worth it. Error handling is unchanged: `groq.RateLimitError` and `groq.APIError` propagate through the wrapper identically.

---

## [7:30 – 8:00] API Tour — Swagger UI

**SAY:**
"Let me do a quick tour of the full API surface."

**DO:** Switch to `http://localhost:8000/docs` (Swagger UI).

**SAY:**
"FastAPI auto-generates this Swagger UI from the endpoint definitions. Every endpoint is documented and testable here."

**DO:** Scroll through and point to each group:

- `/generate-leads` — "This is the main entry point. POST with a keyword, get a run_id back immediately if Celery is running, or leads directly in sync mode."
- `/pipeline-status/{run_id}` — "Poll this every 3 seconds for PENDING, STARTED, SUCCESS, or FAILURE state."
- `/leads` — "Retrieve stored leads, filterable by status. `?status=outreach_ready` is what your CRM integration would call."
- `/leads/pending-review` — "All leads waiting for a human decision."
- `/leads/{id}/approve` and `/leads/{id}/reject` — "Both have GET and POST versions. GET is for Slack button links."
- `/ingest-knowledge` — "Build or rebuild the RAG vector store."
- `/flush-cache` — "Clear Redis dedup cache and Celery results for a clean run."
- `/metrics` — "Business-level pipeline stats."
- `/health` — "Dependency health check."

**SAY:**
"Rate limiting is enforced on `/generate-leads`: 10 requests per minute per IP, using Redis atomic `INCR` counters. Input is sanitized against prompt injection — keywords over 200 characters or containing script patterns are rejected before they reach any LLM call."

---

## [8:00 – 9:00] Architectural Decisions — The Choices That Matter

**SAY:**
"Let me walk through the key architectural decisions, because these are the choices a production system architect would care about."

**Decision 1: Supervisor Pattern**
"A sequential pipeline runs every step on every lead. The Supervisor can route a 3/10 lead directly to discard after the Qualification Agent runs, skipping the Sales Agent entirely. At scale — thousands of leads per day — that's a significant reduction in LLM API costs. One routing function in `supervisor.py`, zero scattered conditionals."

**Decision 2: ChatGroq over raw Groq SDK**
"Using ChatGroq instead of `groq.Groq()` gives automatic LangSmith tracing with zero instrumentation code. One import swap, full observability."

**Decision 3: Pydantic Structured Output**
"`.with_structured_output(QualificationResult)` eliminates an entire category of runtime failures. No regex, no JSON parsing, no try-except around `json.loads`. The model returns a typed Python object or falls back gracefully."

**Decision 4: Serper.dev + Domain Blocklist**
"Switched from DuckDuckGo (rate-limited in Docker) to Serper.dev's Google Search API. 2,500 free queries, India geo-targeting, official website query bias. The domain blocklist filters out aggregators so only actual company URLs reach the scraper."

**Decision 5: Human Review Before Outreach**
"Every generated email is held in `pending_review`. The hallucination guard catches fabricated content. The Slack review catches everything else: wrong tone, wrong audience, edge cases the LLM got confident about but shouldn't have. An LLM should never send emails to real prospects without a human checkpoint."

**Decision 6: Celery Async + Redis**
"A 2–3 minute pipeline in a synchronous endpoint blocks the API for every concurrent user. Celery dispatches it to a background worker, returning a run_id instantly. Redis DB 0 for LLM cache and dedup, Redis DB 1 for Celery. Separate databases so you can flush the cache without killing in-flight jobs."

**Decision 7: ChromaDB as Default, pgvector as Scale Path**
"ChromaDB is zero-infrastructure for demos and single-instance setups. pgvector on PostgreSQL is the right choice when lead data already lives in Postgres — same transaction boundary, same backup, same monitoring. Switch with `USE_PGVECTOR=true` in `.env`, no code changes needed."

---

## [9:00 – 9:30] Docs Overview — Everything is Documented

**SAY:**
"Everything in this system is documented. Let me show you quickly."

**DO:** If you have the repo open in a browser or IDE, flip to the file list briefly.

**SAY:**
"The `README.md` covers the full tech stack, quick start, agent flow, and API reference. `ARCHITECTURE.md` documents every architectural decision with the rationale and the tradeoff — not just what was built but why. `PROMPTS.md` is the full prompt reference: the exact text of each agent's prompt, the variables injected, why each temperature was chosen, and example inputs and outputs. `FINE_TUNING.md` covers the path from this RAG-based system to a fine-tuned qualification model once we have 200+ labeled examples from the Slack approval flow."

**WHY (docs matter):**
Documentation at this level demonstrates that the decisions were intentional, not accidental. Any engineer joining this project can understand not just what was built, but the tradeoffs considered — which makes the system maintainable and extensible. The `ARCHITECTURE.md` in particular captures decisions that are otherwise invisible: why we switched to Serper, why we added GET wrappers for Slack endpoints, why PYTHONPATH had to be set in the Celery worker environment.

---

## [9:30 – 10:00] Closing

**SAY:**
"You can find the full source code at [your GitHub repo URL]. Everything I showed is in the repo: the LangGraph supervisor, the three agent implementations, the Pydantic schemas, the FastAPI routes, the RAG pipeline, and the Docker Compose configuration for all four containers."

"If I were taking this to production, the three things I'd do next are: one — swap ChromaDB for pgvector to consolidate the storage layer; two — add Prometheus metrics and a Grafana dashboard so pipeline health is visible without curling `/metrics`; and three — after collecting 200+ approved and rejected leads from the Slack flow, run QLoRA fine-tuning on Llama 3.1 8B with Unsloth so the Qualification Agent learns from actual reviewer decisions rather than generic prompt engineering."

"Thanks for watching."

**DO:** End recording.

---

# PART 3: TIPS FOR A CLEAN RECORDING

## Timing Guide

| Section | Target Time |
|---------|------------|
| Opening | 0:30 |
| Architecture Overview | 1:00 |
| Docker Stack | 0:30 |
| RAG Ingestion | 0:30 |
| Live Pipeline (including wait) | 2:00 |
| Results / Lead Cards | 1:00 |
| Human Review (Slack + Dashboard) | 1:00 |
| Observability | 1:00 |
| API Tour | 0:30 |
| Architectural Decisions | 1:00 |
| Docs | 0:30 |
| Closing | 0:30 |
| **Total** | **~10:00** |

## Common Problems and Fixes

**Pipeline returns 0 leads:**
- Serper quota may be exhausted. The system falls back to the 15-company curated dataset — you'll still get leads, just not live Google results. Mention "the system's built-in fallback dataset" and move on.
- Redis dedup cache has all companies blocked from the last run. Run `curl -X POST localhost:8000/flush-cache` and try again.

**Dashboard shows "sync mode" (no Celery progress panel):**
- The Celery worker is not running. Check `docker compose ps` — the `celery_worker` container may have exited. Run `docker compose --profile full up -d celery_worker` to restart it.
- In sync mode the dashboard still works — it just shows results directly after a 2–3 minute wait instead of showing the progress panel. You can still demo this, just narrate the wait.

**Slack notification not appearing:**
- Check `SLACK_WEBHOOK_URL` is set in `.env`. The celery_worker container reads from `env_file: .env`, but the override `environment:` block in docker-compose.yml does not include SLACK_WEBHOOK_URL — it's read from the env_file directly. If `.env` has a wrong URL, restart the containers after fixing it.

**LangSmith shows no traces:**
- `LANGCHAIN_TRACING_V2=true` and a valid `LANGCHAIN_API_KEY` must be set in `.env`. The API container reads these. If both are set and traces still don't appear, wait 30 seconds and refresh — LangSmith has a few seconds of ingestion delay.

**"Method Not Allowed" on Slack Approve button:**
- This was fixed by adding GET versions of the approve/reject endpoints. If you're seeing this, make sure you're running the latest version of `api/main.py` which includes `@app.get("/leads/{lead_id}/approve")`.

## Narration During the Pipeline Wait

The 2–3 minute pipeline run is your best narration window, not dead air. Use the time to explain:
- Serper search query design (the "official website" suffix, India geo-targeting)
- The domain blocklist and why it's needed
- `.with_structured_output()` and why it replaced JSON parsing
- The temperature split (0.1 for extraction/scoring, 0.4 for email writing)
- The Redis dedup cache and why 24-hour TTL matters
- The hallucination guard's three checks

You have more than enough material to fill the wait without ever seeming like you're stalling.

## What the Interviewer Is Looking For

- **System design**: Can you explain why each component was chosen, not just what it does?
- **Trade-offs**: Do you understand the downside of each decision? (Serper quota limit, Celery operational complexity, ChromaDB scale ceiling)
- **Production thinking**: What would you change at scale? (Prometheus, SQS/Kafka, pgvector as default)
- **Code quality**: Is it documented, modular, fail-safe? (All three yes — point to the docs, the fallback paths, the atomic file writes)
- **Open-source compliance**: Llama 3.1 is Meta's openly licensed model. Groq is just inference hardware. This fully satisfies the open-source requirement.
