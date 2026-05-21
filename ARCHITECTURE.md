# Architectural Decisions

This system is an autonomous HRMS lead generation pipeline built for a Razor Infotech take-home assignment. It finds companies online, scores them as potential buyers of HumanMaximizer.com's HR software using retrieval-augmented generation, drafts personalized cold outreach emails, and holds every email for human approval before it can reach a real prospect. The entire flow runs as a multi-agent LangGraph pipeline behind a FastAPI service, with Redis handling caching and deduplication and Celery handling async execution.

---

## Supervisor Pattern over Sequential Pipeline

The pipeline uses a LangGraph `StateGraph` with a central `route()` function that reads a `next` field from shared state to decide which agent runs next. The alternative was a plain sequential function chain: call `research_agent()`, then `qualification_agent()`, then `sales_agent()`, always.

The Supervisor earns its complexity through early exit. When the Qualification Agent scores a lead 3/10 and sets `next = "END"`, the Sales Agent never runs. No LLM call is made, no email is drafted, no API quota is spent. In a sequential pipeline you either generate emails for bad leads or scatter `if score >= threshold: call_next()` conditionals across multiple files. The Supervisor centralizes all routing in `supervisor.py`'s `route()` function: one place to read, one place to debug, one place to add a circuit breaker. The circuit breaker is already there, triggering a hard stop when `iteration` exceeds `max_iterations`.

The tradeoff is real. LangGraph's `StateGraph` has a learning curve, and the `add_conditional_edges` API is not immediately obvious. For a two-agent pipeline the overhead would not be worth it. With three agents and the real possibility of adding more, the centralized routing pays for itself.

---

## Groq + Llama 3.1 over OpenAI

The pipeline uses Meta's Llama 3.1 8B model served via Groq's LPU inference hardware (`llama-3.1-8b-instant` in Groq's API). The alternatives were GPT-4o via the OpenAI API, Claude 3 Haiku via Anthropic's API, and local inference via Ollama.

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

**Critical lesson from development**: the field names in the prompt template JSON example must exactly match the Pydantic schema field names. During development, the prompt showed `qualification_score`, `qualification_reason`, `pain_points_identified`, `recommended_approach` while the `QualificationResult` schema expected `score`, `reasoning`, `key_signals`, `recommended_action`. The model returned the prompt's field names, `.with_structured_output()` could not map them to the schema, and the fallback JSON parser found mismatched keys. Both the prompt and schema now use the same names: `score`, `reasoning`, `key_signals`, `recommended_action`.

---

## Serper.dev over DuckDuckGo for Web Search

The primary web search source was changed from DuckDuckGo (via `duckduckgo-search`) to Serper.dev's Google Search API. The alternatives were DuckDuckGo (free, no key), SerpAPI (paid), and scraping Google directly.

DuckDuckGo's unofficial Python library is rate-limited heavily in cloud and Docker environments — it frequently returns 0 results after the first few calls, forcing fallback to the curated company dataset for every pipeline run. Serper.dev provides real Google Search results via an official API, with 2,500 free queries per account and no credit card required. The free tier is sufficient for development and demos. The `gl=in` parameter geo-targets results to India, which dramatically improves relevance for HRMS prospects.

The domain blocklist was added alongside Serper because Google search returns high-quality results but still includes aggregator pages (Wikipedia, LinkedIn, IndiaMART, Crunchbase, DNB, MoneyControl, etc.) that are not actual company websites. The `_is_company_url()` filter in `tools/web_search.py` checks every returned URL against `_BLOCKED_DOMAINS` before passing it to the pipeline. Fetching 5 extra results per query (`max_results + 5`) compensates for URLs that get filtered out. The query format changed from `"{keyword} company India"` to `"{keyword} India official website"` to bias Google toward returning company homepages rather than list pages or directories.

The fallback to the curated 15-company dataset remains: if `SERPER_API_KEY` is not set or if the API returns no usable results, the pipeline continues on the curated dataset rather than failing. Naukri.com and Indeed.in scrapers remain as supplementary sources since they provide buying-signal data (companies actively hiring HR roles) that Google search does not surface.

---

## Domain Blocklist for Serper Results

Alongside switching to Serper, a domain blocklist was introduced in `tools/web_search.py`. Any URL whose domain matches an entry in `_BLOCKED_DOMAINS` is silently discarded before being passed to the pipeline.

Blocked domain categories:
- **Aggregator directories**: IndiaMART, JustDial, DNB, Zaubacorp, Tofler, EasyLeadz, Crunchbase
- **Social/professional networks**: LinkedIn, Facebook, Twitter, Instagram, YouTube
- **Job boards**: Indeed, Naukri, Glassdoor, AmbitionBox (already scraped directly)
- **News/financial media**: MoneyControl, EconomicTimes, LiveMint, BusinessStandard
- **General reference**: Wikipedia, CompaniesMarketCap

Without this filter, Serper would return URLs like `linkedin.com/company/xyz`, `crunchbase.com/organization/xyz`, or `companiesmarketcap.com/india/largest-companies` — none of which are the company's actual website and all of which break the downstream scraping step. The blocklist is checked by exact domain match and subdomain match (e.g., `sub.linkedin.com` is also blocked).

The `_is_company_url()` function also rejects PDF URLs (`url.lower().endswith(".pdf")`) because PDFs are annual reports and regulatory filings, not company websites.

---

## RAG over Fine-Tuning

The Qualification and Sales Agents retrieve product context from a vector store before each LLM call rather than relying on a fine-tuned model. ChromaDB with `all-MiniLM-L6-v2` embeddings (384 dimensions, cosine similarity) is the default store. The alternative was fine-tuning Llama 3 on HumanMaximizer product content.

Fine-tuning encodes knowledge into model weights. When the product changes, the weights are stale and another fine-tuning run is required. For a v1 system with no training data and no labeled leads, RAG is the only viable option anyway. The ingest endpoint re-scrapes humanmaximizer.com and rebuilds the vector store, so updating the product corpus is a single API call. The hallucination guard in both agents checks word overlap between LLM output and retrieved chunks, catching cases where the model fabricates product features not present in what was retrieved.

RAG quality depends on chunking strategy and embedding model. The current configuration uses 500-word chunks with 50-word overlap. A badly tuned chunk size or a weak embedding model causes irrelevant retrieval, which causes the LLM to reason without real product context. That is the main failure mode to watch. On the fine-tuning roadmap: once 200+ human-approved or human-rejected leads accumulate from the Slack approval flow, QLoRA fine-tuning on Llama 3.1 8B via Unsloth (4-bit quantization) is the right next step. The dataset format for Unsloth and Llama 3 is the chat template format, not raw prompt/completion strings.

---

## Multi-Source Lead Discovery

Lead discovery fans out across three sources: Serper.dev (Google Search API), a Naukri.com scraper, and an Indeed.in scraper. Results are deduplicated by root domain before being handed to the Research Agent. The alternative was a single search source.

Companies posting for HR Manager, HRIS Analyst, or Payroll Manager roles are actively spending on HR infrastructure. That is a stronger buying signal than appearing in a keyword search result. The job board scrapers surface companies in an active HR hiring cycle, which means a budget exists and a decision maker is already thinking about HR tooling. Keyword search alone returns companies that happen to mention HRMS in their web presence, which is a weaker signal.

Both job board scrapers fail safe. They catch `403`, `429`, and all other exceptions, log a warning, and return an empty list. The `search_companies_multi_source()` function merges whatever sources did return data, so a blocked scraper degrades gracefully rather than failing the whole run. Serper has its own rate limit handling and falls back to a curated list of Indian HRMS prospects when the API key is not set.

---

## Celery for Async Pipeline Execution

The lead generation pipeline runs as a Celery task (`tasks.run_pipeline`) rather than blocking the FastAPI request thread. The Celery worker runs as a separate Docker service behind `profiles: [full]`. The alternatives were FastAPI `BackgroundTasks` or a synchronous endpoint.

The pipeline takes 2–3 minutes per run. A synchronous endpoint holds the thread for that duration and blocks other requests. FastAPI `BackgroundTasks` runs in the same process, so a process restart or crash loses the task with no retry mechanism. Celery gives retries (max 2 attempts, 10-second countdown between them), task state tracking queryable via `/pipeline-status/{run_id}`, and worker scaling independent of the API. The client calls `/generate-leads`, gets a `run_id` back immediately, and polls for completion.

The tradeoff is operational complexity: three processes to run instead of one (API, Redis, Celery worker). The `profiles: [full]` gate on the `celery_worker` Docker service means `docker compose up` without that profile works exactly as before. The `/generate-leads` endpoint checks for a reachable Celery broker at request time and falls back to synchronous execution if none is available, so the development experience is unchanged.

**Critical Docker networking lesson**: the Celery worker's environment must specify `redis://redis:6379` (Docker service hostname), not `redis://localhost:6379`. When `env_file: .env` is used and `.env` contains `CELERY_BROKER_URL=redis://localhost:6379/1`, this localhost URL is inherited by the container. Inside Docker's network, there is no `localhost` Redis — the Redis container is only reachable at the service name `redis`. The fix is to add explicit `environment:` overrides in the `celery_worker` service definition that take precedence over `env_file`. Similarly, `PYTHONPATH=/app` must be set in the Celery worker's environment because forked worker processes do not inherit the Python path set in the Dockerfile's `WORKDIR` configuration, causing `ModuleNotFoundError: No module named 'graph'` at task execution time.

---

## Dashboard Async Polling Design

The dashboard (`static/dashboard.html`) was redesigned to support both the async Celery path and the synchronous fallback path from a single UI.

When `/generate-leads` returns `{"status": "queued", "run_id": "..."}` (async path), the dashboard shows a progress panel with three stages — Research, Qualify, Sales — and an elapsed timer. It polls `GET /pipeline-status/{run_id}` every 3 seconds. Stage progression is inferred from elapsed time rather than actual agent callbacks (Research: 0–45s, Qualify: 45–130s, Sales: 130s+) because the pipeline does not push incremental state updates during execution. When the poll returns `SUCCESS`, the result is rendered as lead cards automatically.

When `/generate-leads` returns `{"status": "success", ...}` directly (sync path), the dashboard detects `status !== "queued"` on the initial response and renders lead cards immediately without starting the polling loop.

The polling interval is 3 seconds. Shorter intervals waste Serper queries and Redis cache lookups with no user benefit. Longer intervals make the progress feel stuck. 3 seconds is the practical minimum for a task that takes 2–3 minutes.

Stage timing is an estimate, not a guarantee. If the pipeline is faster or slower on a given run, the stage indicators may not align perfectly. This is an acceptable UX tradeoff versus the complexity of implementing WebSocket push updates, which would require restructuring the FastAPI application to use an async event system.

---

## Redis for Caching, Rate Limiting, and Deduplication

Redis serves three distinct functions: LLM response caching and lead deduplication on DB 0, and Celery broker plus result backend on DB 1. The alternative was in-memory Python dicts for caching and deduplication with no async queue.

In-memory state breaks under horizontal scaling. Two API replicas would have separate caches and separate dedup sets, so the same company could be processed simultaneously by both. Redis atomic `INCR` for rate limiting has no race conditions regardless of how many replicas are running. The cache key is a SHA-256 hash of the full prompt (not a prefix), because the first 200 characters of every agent prompt are the same static preamble. The 24-hour deduplication window means a lead generation run on Monday and one on Tuesday do not double-process the same companies. A cache hit returns in roughly 5ms versus the 2-second LLM call it replaces.

The tradeoff is a service dependency. `get_redis()` pings the connection before every use and returns `None` if Redis is unavailable. Every function that uses Redis checks for `None` and either returns `False`, returns the uncached result, or fails open on rate limiting. The core pipeline continues to work without Redis, just without caching, deduplication, or rate limiting.

A `POST /flush-cache` endpoint was added to clear all Redis databases (dedup cache on DB 0, Celery results on DB 1) so consecutive demo runs start fresh. Without flushing, the dedup cache blocks re-processing companies seen in the previous run, which makes consecutive same-keyword runs return zero new leads.

---

## Human-in-the-Loop Before Outreach

Every generated email lands in `pending_review` status and triggers a Slack notification with Approve and Reject buttons. A human reviewer reads the lead summary and email draft before the lead's status can move to `outreach_ready`. The alternative was marking emails `outreach_ready` immediately after the Sales Agent generates them.

An LLM can write a confident-sounding email that claims a feature the product does not have, uses a tone inappropriate for the prospect, or targets a company that is actually a poor fit despite passing the qualification score threshold. Sending that email damages the company's reputation. The hallucination guard reduces bad product claims by checking overlap between the email body and retrieved product chunks, but it does not catch tone, judgment, or relevance. The human review step is the only check that catches all of those.

Slack's Incoming Webhooks API uses HTTP GET when a user clicks a button URL — the links in the Slack Block Kit message are plain anchor tags, not form POST requests. This means the approve/reject endpoints in FastAPI must support both `GET /leads/{id}/approve` and `POST /leads/{id}/approve`. The GET versions were added as wrappers that call the same logic as the POST versions. Without this, clicking the Approve button in Slack returns `405 Method Not Allowed`.

The dashboard also exposes Approve/Reject buttons directly on `pending_review` lead cards, allowing review without Slack in development environments. These buttons call `POST /leads/{id}/approve` and `POST /leads/{id}/reject` directly from the browser.

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

## Pydantic Settings and Docker Environment Variable Precedence

The `core/config.py` Settings class uses Pydantic Settings with `env_file = ".env"`. When the Celery worker container is started with `env_file: .env` in Docker Compose, every variable in `.env` is injected as an environment variable into the container — including any keys that are not defined fields in the Settings class.

If `extra = "allow"` or the default `extra = "ignore"` is not set on the Pydantic Config, any unknown environment variable causes a `ValidationError: Extra inputs are not permitted` at startup. Setting `extra = "ignore"` on the `Config` inner class silently skips unknown variables, which is the right behavior for a container that inherits a broad `.env` file. All required fields are still validated; only unexpected extras are dropped.

Field names in Settings must match the environment variable names case-insensitively. Adding `SERPER_API_KEY` to `.env` without a corresponding `serper_api_key: str = ""` field in Settings causes the same validation error because Pydantic Settings sees it as an unknown field.

---

## What I Would Do Differently at Production Scale

The JSONL metrics file works fine for a single instance but does not compose. At scale, the right answer is Prometheus metrics exposed on a `/metrics` endpoint with a Grafana dashboard. Latency per agent, LLM token counts, qualification pass rates, and hallucination warning frequency all belong as time-series metrics, not log lines to grep.

Redis as a Celery broker is fine for low-to-medium volume. At higher volume, SQS or Kafka provides durability guarantees Redis does not: messages survive a Redis restart, dead-letter queues are built in, and consumer group semantics on Kafka enable multiple worker types processing the same events at different speeds.

The Slack approval flow is pragmatic but limited. A reviewer cannot edit the email, add a comment explaining a rejection, or see the full RAG context that grounded the email. A proper review UI — a simple web page with the lead summary, the retrieved product chunks, the generated email in an editable field, and an approve/reject button with a comment box — would make the human review step meaningfully more useful rather than just a binary gate.

LangSmith's experiment framework would let you A/B test outreach email prompts against each other using human approval rate as the metric. That is the right feedback loop for improving email quality over time, and the infrastructure for it is already present since LangSmith tracing is active.

pgvector should become the default once PostgreSQL is already the system of record for lead data. Maintaining two storage systems (PostgreSQL for leads, ChromaDB for embeddings) when one can do both is unnecessary operational overhead.

The Qualification Agent's scoring is currently zero-shot. Once 200 or more human-approved and human-rejected leads accumulate from the Slack review flow, those examples become a labeled dataset. QLoRA fine-tuning on Llama 3.1 8B using Unsloth with 4-bit quantization is the right next step: the qualification agent learns from actual reviewer decisions rather than from a generic prompt. The dataset format for Unsloth and Llama 3 chat template fine-tuning is the instruct format, not raw prompt/completion pairs.

The dashboard stage timing (Research: 0–45s, Qualify: 45–130s, Sales: 130s+) is hard-coded based on observed pipeline latency. A proper implementation would stream agent completion events via WebSocket or Server-Sent Events, so the stage indicators advance based on actual progress rather than elapsed time estimates.
