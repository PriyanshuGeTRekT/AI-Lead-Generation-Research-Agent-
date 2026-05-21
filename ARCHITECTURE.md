# Architectural Decisions

This system is an autonomous HRMS lead generation pipeline built for a Razor Infotech take-home assignment. It finds companies online, scores them as potential buyers of HumanMaximizer.com's HR software using retrieval-augmented generation, drafts personalized cold outreach emails, and holds every email for human approval before it can reach a real prospect. The entire flow runs as a multi-agent LangGraph pipeline behind a FastAPI service, with Redis handling caching and deduplication and Celery handling async execution.

---

## Supervisor Pattern over Sequential Pipeline

The pipeline uses a LangGraph `StateGraph` with a central `route()` function that reads a `next` field from shared state to decide which agent runs next. The alternative was a plain sequential function chain: call `research_agent()`, then `qualification_agent()`, then `sales_agent()`, always.

The Supervisor earns its complexity through early exit. When the Qualification Agent scores a lead 3/10 and sets `next = "END"`, the Sales Agent never runs. No LLM call is made, no email is drafted, no API quota is spent. In a sequential pipeline you either generate emails for bad leads or scatter `if score >= threshold: call_next()` conditionals across multiple files. The Supervisor centralizes all routing in `supervisor.py`'s `route()` function: one place to read, one place to debug, one place to add a circuit breaker. The circuit breaker is already there, triggering a hard stop when `iteration` exceeds `max_iterations`.

The tradeoff is real. LangGraph's `StateGraph` has a learning curve, and the `add_conditional_edges` API is not immediately obvious. For a two-agent pipeline the overhead would not be worth it. With three agents and the real possibility of adding more, the centralized routing pays for itself.

---

## Groq + Llama 3.1 over OpenAI

The pipeline uses Meta's Llama 3.1 8B model served via Groq's LPU inference hardware (`llama3-8b-8192` in Groq's API). The alternatives were GPT-4o via the OpenAI API, Claude 3 Haiku via Anthropic's API, and local inference via Ollama.

The assignment requires an open-source model. Llama 3.1 is Meta's openly licensed model. Groq is just inference hardware, not the model provider, so using Groq satisfies the open-source requirement while getting sub-second latency on the 8B model. That latency matters here because the pipeline makes at least three LLM calls per lead: one in the Research Agent for extraction, one in the Qualification Agent for scoring, and one in the Sales Agent for email drafting. GPT-4o would have been easier to integrate but violates the open-source constraint. Local Ollama is documented in the project as a swap-out option but requires 16GB RAM and runs roughly 10x slower, making it impractical for a pipeline with live web scraping in the same loop.

Groq's free tier caps at 14,400 requests per day with rate limits, which is fine for the scale this assignment targets. The `BaseAgent.call_llm()` method handles `RateLimitError` with exponential backoff (up to 3 retries, doubling delay each time), so transient rate limit hits don't kill the pipeline.

---

## ChatGroq over the Raw Groq SDK

Each agent instantiates `langchain_groq.ChatGroq` rather than `groq.Groq` from the raw Groq Python SDK. Both can call the same underlying API. The difference is entirely about observability.

LangSmith only auto-traces LangChain Runnable objects. A call through `groq.Groq().chat.completions.create()` is invisible to LangSmith. A call through `ChatGroq.invoke()` appears in LangSmith as a fully attributed trace under the parent LangGraph run, showing the exact prompt, the full response, token counts, and per-call latency, all without adding a single line of instrumentation code anywhere in the agents. The same wrapper also unlocks `.with_structured_output()` for schema enforcement, which is used in the Qualification Agent.

The tradeoff is a `langchain-groq` dependency on top of the raw SDK. Error handling needed no changes: `groq.RateLimitError` and `groq.APIError` propagate through the LangChain wrapper unchanged, so `BaseAgent.call_llm()`'s except clauses catch them exactly as written.

---

## Structured Output via .with_structured_output()

The Qualification Agent uses `llm.with_structured_output(QualificationResult)` to get a validated Pydantic object back from the model instead of a raw string. The alternative was calling the LLM, getting a string, and parsing JSON manually every time.

LLMs are not reliable JSON emitters. They add markdown code fences, put commentary before the opening brace, or emit literal newlines inside string values. The `parse_json_response()` method in `BaseAgent` handles most of these cases with a two-pass parser, but it is inherently brittle. `.with_structured_output()` passes the `QualificationResult` Pydantic schema as a JSON Schema tool definition to the model, which uses Groq's tool-calling implementation to return validated JSON. The result comes back as a proper `QualificationResult` instance, not a string to parse.

The structured call can still fail if the model does not cooperate, so `call_llm_structured()` falls back to `call_llm() + parse_json_response() + schema(**parsed)` on any exception. This makes schema enforcement "best effort" rather than guaranteed, but in practice it dramatically reduces parse failures. The Research Agent and Sales Agent use the raw `call_llm()` path because their outputs are less rigidly structured.

---

## RAG over Fine-Tuning

The Qualification and Sales Agents retrieve product context from a vector store before each LLM call rather than relying on a fine-tuned model. ChromaDB with `all-MiniLM-L6-v2` embeddings (384 dimensions, cosine similarity) is the default store. The alternative was fine-tuning Llama 3 on HumanMaximizer product content.

Fine-tuning encodes knowledge into model weights. When the product changes, the weights are stale and another fine-tuning run is required. For a v1 system with no training data and no labeled leads, RAG is the only viable option anyway. The ingest endpoint re-scrapes humanmaximizer.com and rebuilds the vector store, so updating the product corpus is a single API call. The hallucination guard in both agents checks word overlap between LLM output and retrieved chunks, catching cases where the model fabricates product features not present in what was retrieved.

RAG quality depends on chunking strategy and embedding model. The current configuration uses 500-word chunks with 50-word overlap. A badly tuned chunk size or a weak embedding model causes irrelevant retrieval, which causes the LLM to reason without real product context. That is the main failure mode to watch. On the fine-tuning roadmap: once 200+ human-approved or human-rejected leads accumulate from the Slack approval flow, QLoRA fine-tuning on Llama 3.1 8B via Unsloth (4-bit quantization) is the right next step. The dataset format for Unsloth and Llama 3 is the chat template format, not raw prompt/completion strings.

---

## Multi-Source Lead Discovery

Lead discovery fans out across three sources: DuckDuckGo keyword search, a Naukri.com scraper, and an Indeed.in scraper. Results are deduplicated by root domain before being handed to the Research Agent. The alternative was DuckDuckGo only.

Companies posting for HR Manager, HRIS Analyst, or Payroll Manager roles are actively spending on HR infrastructure. That is a stronger buying signal than appearing in a keyword search result. The job board scrapers surface companies in an active HR hiring cycle, which means a budget exists and a decision maker is already thinking about HR tooling. Keyword search alone returns companies that happen to mention HRMS in their web presence, which is a weaker signal.

Both job board scrapers fail safe. They catch `403`, `429`, and all other exceptions, log a warning, and return an empty list. The `search_companies_multi_source()` function merges whatever sources did return data, so a blocked scraper degrades gracefully rather than failing the whole run. DuckDuckGo has its own retry logic with exponential backoff and falls back to a curated list of Indian HRMS prospects when rate-limited, which is common in Docker and cloud environments.

---

## Redis for Caching, Rate Limiting, and Deduplication

Redis serves three distinct functions: LLM response caching and lead deduplication on DB 0, and Celery broker plus result backend on DB 1. The alternative was in-memory Python dicts for caching and deduplication with no async queue.

In-memory state breaks under horizontal scaling. Two API replicas would have separate caches and separate dedup sets, so the same company could be processed simultaneously by both. Redis atomic `INCR` for rate limiting has no race conditions regardless of how many replicas are running. The cache key is a SHA-256 hash of the full prompt (not a prefix), because the first 200 characters of every agent prompt are the same static preamble. The 24-hour deduplication window means a lead generation run on Monday and one on Tuesday do not double-process the same companies. A cache hit returns in roughly 5ms versus the 2-second LLM call it replaces.

The tradeoff is a service dependency. `get_redis()` pings the connection before every use and returns `None` if Redis is unavailable. Every function that uses Redis checks for `None` and either returns `False`, returns the uncached result, or fails open on rate limiting. The core pipeline continues to work without Redis, just without caching, deduplication, or rate limiting.

---

## Human-in-the-Loop Before Outreach

Every generated email lands in `pending_review` status and triggers a Slack notification with Approve and Reject buttons. A human reviewer reads the lead summary and email draft before the lead's status can move to `outreach_ready`. The alternative was marking emails `outreach_ready` immediately after the Sales Agent generates them.

An LLM can write a confident-sounding email that claims a feature the product does not have, uses a tone inappropriate for the prospect, or targets a company that is actually a poor fit despite passing the qualification score threshold. Sending that email damages the company's reputation. The hallucination guard reduces bad product claims by checking overlap between the email body and retrieved product chunks, but it does not catch tone, judgment, or relevance. The human review step is the only check that catches all of those.

The review step slows the pipeline. Leads sit in `pending_review` until someone acts. This is intentional: speed of outreach is not the priority, quality of outreach is. For development and testing environments where Slack is not configured (`SLACK_WEBHOOK_URL` is empty), the Sales Agent skips the review gate and marks leads `outreach_ready` directly, so the default experience is unchanged.

---

## Celery for Async Pipeline Execution

The lead generation pipeline runs as a Celery task (`tasks.run_pipeline`) rather than blocking the FastAPI request thread. The Celery worker runs as a separate Docker service behind `profiles: [full]`. The alternatives were FastAPI `BackgroundTasks` or a synchronous endpoint.

The pipeline takes 15 to 30 seconds per run. A synchronous endpoint holds the thread for that duration and blocks other requests. FastAPI `BackgroundTasks` runs in the same process, so a process restart or crash loses the task with no retry mechanism. Celery gives retries (max 2 attempts, 10-second countdown between them), task state tracking queryable via `/pipeline-status/{run_id}`, and worker scaling independent of the API. The client calls `/generate-leads`, gets a `run_id` back immediately, and polls for completion.

The tradeoff is operational complexity: three processes to run instead of one (API, Redis, Celery worker). The `profiles: [full]` gate on the `celery_worker` Docker service means `docker compose up` without that profile works exactly as before. The `/generate-leads` endpoint checks for a reachable Celery broker at request time and falls back to synchronous execution if none is available, so the development experience is unchanged.

---

## pgvector as Production Vector Store

pgvector on PostgreSQL is available as a drop-in replacement for ChromaDB, activated by setting `USE_PGVECTOR=true`. ChromaDB remains the default. The `PgVectorStore` class mirrors the ChromaDB collection interface: `add_documents()`, `similarity_search()`, `count()`. Switching stores requires only a config flag, no code changes.

ChromaDB is excellent for local development and demos. In production, a dedicated vector store service means one more thing to monitor, back up, and scale independently. If lead data lives in PostgreSQL, keeping embeddings there too means the vector store and the lead records share a transaction boundary. An embedding write and a lead record write either both succeed or both fail. `pg_dump` backs up both. Standard Postgres monitoring covers both. The HNSW index (`vector_cosine_ops`) provides approximate nearest-neighbor search performance comparable to ChromaDB.

The tradeoff is that pgvector requires a PostgreSQL service, which adds friction for a single-developer setup or a demo. ChromaDB requires no external service and is lower friction in those cases. That is why ChromaDB remains the default and pgvector is opt-in.

---

## Atomic File Writes for leads.json

Lead data is written to a `.tmp` file first, then moved into place with `os.replace()`. The alternative was opening `leads.json` and writing directly.

`os.replace()` is atomic at the OS level. The file either has the old content or the new content, never a half-written state. If two requests call `/generate-leads` concurrently, or if the process crashes mid-write, a direct write can leave partially written JSON that corrupts the entire lead store. The atomic swap prevents that. This is a standard pattern for any write that must not be interrupted, and the cost is zero: one extra file handle, one syscall.

---

## What I Would Do Differently at Production Scale

The JSONL metrics file works fine for a single instance but does not compose. At scale, the right answer is Prometheus metrics exposed on a `/metrics` endpoint with a Grafana dashboard. Latency per agent, LLM token counts, qualification pass rates, and hallucination warning frequency all belong as time-series metrics, not log lines to grep.

Redis as a Celery broker is fine for low-to-medium volume. At higher volume, SQS or Kafka provides durability guarantees Redis does not: messages survive a Redis restart, dead-letter queues are built in, and consumer group semantics on Kafka enable multiple worker types processing the same events at different speeds.

The Slack approval flow is pragmatic but limited. A reviewer cannot edit the email, add a comment explaining a rejection, or see the full RAG context that grounded the email. A proper review UI, a simple web page with the lead summary, the retrieved product chunks, the generated email in an editable field, and an approve/reject button with a comment box, would make the human review step meaningfully more useful rather than just a binary gate.

LangSmith's experiment framework would let you A/B test outreach email prompts against each other using human approval rate as the metric. That is the right feedback loop for improving email quality over time, and the infrastructure for it is already present since LangSmith tracing is active.

pgvector should become the default once PostgreSQL is already the system of record for lead data. Maintaining two storage systems (PostgreSQL for leads, ChromaDB for embeddings) when one can do both is unnecessary operational overhead.

The Qualification Agent's scoring is currently zero-shot. Once 200 or more human-approved and human-rejected leads accumulate from the Slack review flow, those examples become a labeled dataset. QLoRA fine-tuning on Llama 3.1 8B using Unsloth with 4-bit quantization is the right next step: the qualification agent learns from actual reviewer decisions rather than from a generic prompt. The dataset format for Unsloth and Llama 3 chat template fine-tuning is the instruct format, not raw prompt/completion pairs.
