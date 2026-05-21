# Demo Walkthrough Script
## AI Lead Generation System - Razor Infotech Take-Home Assignment

> This file is LOCAL ONLY. Do not commit to git.

---

## Pre-Recording Checklist

Complete all of these before hitting record:

- [ ] Docker Desktop is running
- [ ] `docker compose up -d` completed successfully (all containers green)
- [ ] RAG already ingested: `curl -X POST localhost:8000/ingest-knowledge` (run this before recording so it's instant on camera)
- [ ] `.env` file has `SLACK_WEBHOOK_URL` set (optional but impressive to show)
- [ ] `.env` file has `LANGCHAIN_API_KEY` set (optional but impressive to show)
- [ ] Browser tabs pre-opened:
  - `localhost:8000` (Dashboard)
  - `localhost:8000/docs` (Swagger UI)
  - `smith.langchain.com` (LangSmith, if key is set)
- [ ] Terminal window ready with large font (18pt or bigger)
- [ ] Window set to 1920x1080 (not fullscreen)
- [ ] Leads file cleared for a fresh run: delete `data/leads.json` if it exists
- [ ] Run `docker compose ps` and confirm all services are up
- [ ] Have a lead ID copied somewhere (run `GET /leads` in Swagger after the pipeline so you can paste it fast when approving)
- [ ] Do a practice run once before recording

---

## Recording Script

---

### [0:00 - 0:30] Opening

**SAY:**
"Hi, I'm [your name]. This is my submission for the Razor Infotech AI Architect take-home assignment. I built an AI-powered B2B lead generation system using LangGraph with a supervisor agent pattern, FastAPI, ChromaDB for RAG, and Groq for inference via LangChain's ChatGroq integration. Let me walk you through every layer of it."

**SHOW:** Your face or a title card. Then switch to the dashboard at `localhost:8000`.

**DO:** Nothing yet. Just introduce.

---

### [0:30 - 1:30] Architecture Overview

**SAY:**
"Let me start with the architecture so everything else makes sense. The system uses a supervisor pattern, which means one orchestrator agent decides which specialist agent runs next, rather than a fixed linear pipeline. This matters because it lets us discard a bad lead early, before wasting tokens on scoring or email generation."

"There are three specialist agents. The Research Agent pulls company data from multiple sources: DuckDuckGo, Naukri, and Indeed. The Qualification Agent scores each company using RAG context from ChromaDB and outputs a structured Pydantic schema. The Sales Agent writes personalized outreach emails and runs a hallucination guard before the email ever reaches a human reviewer."

"There's also a Celery async path for background processing, and a human-in-the-loop review step via Slack before any lead is marked outreach-ready."

**SHOW:** Open `AI_Lead_Gen_Architecture.pptx` and flip through the first two slides, OR point to the architecture diagram in the README.

**DO:** Walk through the diagram visually as you speak. Point to the supervisor node, the three agent boxes, the ChromaDB store, and the Slack review step.

---

### [1:30 - 2:00] One-Command Startup

**SAY:**
"The entire stack starts with one command. Let me show you the running services."

**SHOW:** Switch to the terminal.

**DO:** Run:
```bash
docker compose ps
```

**SAY:**
"You can see all the containers are up: the FastAPI app, ChromaDB, Redis, and the Celery worker. Now let me hit the health endpoint to confirm every dependency is green."

**DO:** Run:
```bash
curl localhost:8000/health
```

**SAY:**
"All green. ChromaDB connected, Redis connected, the LLM endpoint reachable. This is the first thing I'd check in production before routing any traffic."

---

### [2:00 - 2:30] RAG Knowledge Ingestion

**SAY:**
"Before running the pipeline, the system needs to know what a good lead looks like for our client. That's what the RAG ingestion step does."

**SHOW:** Switch to the dashboard at `localhost:8000`. Point to the "Re-ingest RAG Knowledge" button, OR switch to terminal.

**DO:** Either click the button on the dashboard, or run:
```bash
curl -X POST localhost:8000/ingest-knowledge
```

**SAY:**
"What just happened: the system scraped humanmaximizer.com, chunked the content into 500-token segments, embedded each chunk using the all-MiniLM-L6-v2 sentence transformer model, and stored everything in ChromaDB. This runs in seconds because I already ran it before recording. It's idempotent, so running it twice won't create duplicates. The Qualification Agent will query this vector store at runtime to retrieve the most relevant context for each lead it scores."

---

### [2:30 - 4:30] Live Pipeline Run

**SAY:**
"Now let's run the pipeline live. I'll switch to the dashboard."

**SHOW:** `localhost:8000` with the keyword field visible.

**DO:** Confirm the keyword field is pre-filled with something like "HR software" or "recruitment automation". Click "Generate Leads".

**SAY:**
"The pipeline is running. This takes about 15 to 25 seconds, so let me walk you through what's happening inside."

"First, the supervisor activates the Research Agent. It calls the `search_companies_multi_source` tool, which fires parallel requests to DuckDuckGo, Naukri, and Indeed. Naukri and Indeed are especially valuable because companies posting HR and recruitment jobs are signaling active buying intent, which is exactly the kind of lead our client wants."

"The Research Agent deduplicates results by domain so we don't score the same company twice. Then it scrapes each company's website to pull context: what they do, their tech stack signals, headcount indicators."

"That data goes to the Qualification Agent. It retrieves the top-k most relevant chunks from ChromaDB, builds a prompt, calls Llama 3.1 via ChatGroq with a `LeadExtraction` Pydantic schema using `.with_structured_output()`, and gets back a fully typed object. No JSON parsing, no regex, no failures from malformed strings."

"The supervisor sees the score. If the lead is below threshold, it routes to discard. If it passes, the Sales Agent runs: it writes a personalized outreach email and then runs a hallucination guard to make sure the email doesn't contain facts that weren't in the scraped content."

**SHOW:** Watch for results to appear on the dashboard.

**SAY:**
"Results are in. Let me walk through one of these lead cards."

**DO:** Point to the first lead card. Walk through:
- The score badge (e.g., "Score: 82/100")
- The pain points listed under the card
- The email preview section

**SAY:**
"This lead scored 82. The Qualification Agent identified three pain points: manual applicant tracking, no structured interview process, and scaling hiring without an HR team. The Sales Agent used those exact pain points to write the email, which is why it reads as specific rather than generic."

**DO:** Click to expand the email preview. Point to the copy button.

**SAY:**
"The copy button lets a sales rep grab the email in one click. Every piece of data you see here, score, pain points, email, came from a structured Pydantic model, not string parsing."

---

### [4:30 - 5:30] Human-in-the-Loop Review

**IF Slack is configured:**

**SAY:**
"Notice the lead status here is `pending_review`, not `outreach_ready`. That's intentional. No LLM-generated email should reach a real prospect without a human checkpoint."

**SHOW:** Switch to Slack.

**DO:** Show the Slack notification that was just sent. Point to the company name, score, pain points summary, and the email preview in the message.

**SAY:**
"When the Sales Agent finishes, it posts this notification to Slack with everything the reviewer needs to make a decision: company name, score, the pain points, and the first few lines of the email."

**DO:** Switch to `localhost:8000/docs` (Swagger UI).

**SAY:**
"To approve a lead, I'll use the Swagger UI. I'll call the POST /leads/{id}/approve endpoint."

**DO:** Expand `POST /leads/{id}/approve`. Click "Try it out". Paste the lead ID. Click Execute.

**SAY:**
"The lead status just changed to `outreach_ready`. That's the only way a lead moves forward: a human explicitly approves it via the API. You could also reject it with POST /leads/{id}/reject, which moves it to a rejected state and logs the decision."

---

**IF Slack is NOT configured:**

**SAY:**
"In this environment I don't have a Slack webhook set, so leads go straight to `outreach_ready`. But let me explain what the Slack flow looks like when `SLACK_WEBHOOK_URL` is configured."

"When the Sales Agent finishes, it posts a structured notification to Slack: company name, score, pain points, email preview. A reviewer reads it and decides. If they approve, they call POST /leads/{id}/approve via the API or a Slack action. Only then does the status change to `outreach_ready`. This is a deliberate design choice: LLM output should never reach customers without human review."

**DO:** Open `localhost:8000/docs` and briefly show the `/leads/{id}/approve` and `/leads/{id}/reject` endpoints to make them visible.

---

### [5:30 - 6:30] Observability

**SAY:**
"Let me show you what's happening under the hood."

**SHOW:** Switch to terminal.

**DO:** Run:
```bash
curl localhost:8000/metrics
```

**SAY:**
"This metrics endpoint returns a JSONL-backed summary: total runs, leads generated, leads approved, average score, pipeline latency. Lightweight, no Prometheus dependency needed for a demo environment."

**DO:** Run (replace `ai-lead-gen-app` with your actual container name):
```bash
docker logs ai-lead-gen-app --tail 20
```

**SAY:**
"Every log line is structured JSON with a correlation ID, so you can trace a single pipeline run across all log lines. In production you'd ship these to Datadog or CloudWatch."

**IF LangSmith is configured:**

**DO:** Switch to `smith.langchain.com`.

**SAY:**
"Because I'm using ChatGroq instead of the raw Groq SDK, LangSmith tracing is completely automatic. No manual instrumentation. I'll open the most recent trace."

**DO:** Click the latest trace. Click into a child span.

**SAY:**
"Every span shows the exact prompt that was sent, the model response, token counts, and latency. This is how you debug a hallucination or a bad score in production: you have the full chain of evidence."

---

### [6:30 - 7:30] API Reference

**SAY:**
"Let me do a quick tour of the API surface."

**SHOW:** Switch to `localhost:8000/docs`.

**DO:** Scroll through the endpoints and briefly highlight each group.

**SAY:**
"The new endpoints beyond the basics are: `/leads/pending-review` to list everything waiting for a human decision, `/leads/{id}/approve` and `/leads/{id}/reject` for the review workflow, and `/pipeline-status/{run_id}` to poll a background run if you're using the Celery async path."

**DO:** Switch to terminal and run:
```bash
curl "localhost:8000/leads?status=outreach_ready"
```

**SAY:**
"The leads endpoint supports status filtering, so your CRM integration can poll only the leads that are ready to act on."

---

### [7:30 - 8:30] Architectural Decisions

**SAY:**
"Let me speak to the five key architectural decisions, because these are the choices that matter in a real production system."

"First: why a supervisor pattern instead of a sequential pipeline. A sequential pipeline runs every step on every lead. The supervisor can inspect the result after the Research Agent and route bad leads directly to discard, before the Qualification Agent spends tokens on them. At scale, that's a meaningful cost difference."

"Second: why ChatGroq instead of the raw Groq SDK. ChatGroq is LangChain's wrapper, and it makes LangSmith tracing automatic. With the raw SDK you'd need manual span instrumentation for every call. One import change gives you full observability."

"Third: why Pydantic structured output with `.with_structured_output()`. Every LLM call that extracts data returns a typed Pydantic model. There's no JSON parsing, no regex, no try-except around `json.loads`. The schema is enforced at the LangChain layer. This eliminates an entire category of runtime failures."

"Fourth: why human review before outreach. LLMs are not reliable enough to send emails to real prospects without a checkpoint. The human-in-the-loop step is not a demo feature, it's a production requirement. The Slack notification gives a reviewer everything they need in under 30 seconds."

"Fifth: why multi-source search including Naukri and Indeed. Companies posting HR and recruitment jobs are signaling that they have a hiring problem right now. That's a much stronger buying intent signal than a company that just shows up in a general web search. Source diversity also reduces the impact of any single source being rate-limited."

---

### [8:30 - 9:00] Closing

**SAY:**
"You can find the full source code at [your GitHub repo URL here]. Everything I showed is in the repo: the LangGraph graph definition, the Pydantic schemas, the FastAPI routes, the Dockerfile and compose file."

"If I were taking this to production, the first three things I'd add are: swap ChromaDB for pgvector to consolidate the database layer, move the Celery worker to a proper task queue with retry logic and dead-letter queues, and after collecting 200 approved and rejected leads, fine-tune a smaller model with QLoRA so the qualification step runs faster and costs less per lead."

"Thanks for watching."

**DO:** End recording.

---

## Tips for a Clean Recording

- Keep your terminal font at 18pt or larger. Small text is unreadable in video.
- Record at 1920x1080 in a window, not fullscreen. It's easier to switch between apps without the transition looking jarring.
- Do not rush the 15-25 second pipeline run. That wait time is your best narration opportunity. Use it.
- Before going to Swagger UI to approve a lead, have the lead ID already copied. Run `GET /leads` first, grab the ID, then go back to the approve endpoint. Fumbling for an ID on camera wastes time.
- If the pipeline returns zero leads because DuckDuckGo is rate-limiting, just click Generate Leads again immediately. The system will fall back to the cached company dataset and return results.
- Practice the full walkthrough once end-to-end before you record. Aim for 8 minutes 30 seconds. If you're going over 10 minutes, trim the API reference section.
