"""
Centralized Configuration Management
-------------------------------------
Uses Pydantic Settings for type-safe config with env var support.
All magic strings and constants live here, no hardcoding across the codebase.

Architectural Decision:
  Centralizing config via Pydantic Settings means:
  - Type validation at startup (fail fast if GROQ_API_KEY is missing)
  - Single source of truth for all tuneable parameters
  - Easy swap between environments (dev/staging/prod) via .env files
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── LLM ───────────────────────────────────────────────────────────────────
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    # LLM generation parameters
    # temperature=0.1 for structured extraction (deterministic)
    # temperature=0.4 for email writing (some creativity needed)
    llm_temperature_extract: float = 0.1
    llm_temperature_creative: float = 0.4
    llm_max_tokens_extract: int = 1000
    llm_max_tokens_creative: int = 500

    # ── RAG ───────────────────────────────────────────────────────────────────
    chroma_path: str = "./data/chroma_db"
    collection_name: str = "hrms_knowledge"
    embed_model: str = "all-MiniLM-L6-v2"
    chunk_size: int = 500       # tokens per chunk
    chunk_overlap: int = 50     # overlap to avoid context loss at boundaries
    rag_top_k: int = 4          # number of chunks retrieved per query
    rag_distance_threshold: float = 0.8  # cosine distance cutoff (< = relevant)

    # ── Qualification ─────────────────────────────────────────────────────────
    qualification_threshold: float = 5.0  # leads scoring below this are discarded

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://redis:6379"
    redis_cache_ttl: int = 3600          # 1 hour TTL for LLM response cache
    redis_pipeline_ttl: int = 86400      # 24 hour TTL for pipeline state

    # ── Pipeline ──────────────────────────────────────────────────────────────
    max_leads_per_run: int = 50         # increase via MAX_LEADS_PER_RUN env var
    max_iterations: int = 10
    web_search_results: int = 100
    request_timeout: int = 5             # seconds for web scraping (fail fast on dead/slow sites)

    # ── Observability ─────────────────────────────────────────────────────────
    langchain_api_key: str = ""          # LangSmith (optional)
    langchain_tracing_v2: str = "false"
    langchain_project: str = "ai-lead-gen"
    log_level: str = "INFO"

    # ── Security ──────────────────────────────────────────────────────────────
    rate_limit_per_minute: int = 10      # max /generate-leads calls per minute
    max_keyword_length: int = 200        # prevent prompt injection via long inputs
    data_path: str = "./data/leads.json"
    cors_allowed_origins: str = "http://localhost:8000,http://127.0.0.1:8000"
    api_admin_key: str = ""              # if set, required for API mutations/read lead data
    review_action_token: str = ""        # if set, required on Slack approve/reject GET links

    # ── Web Search ────────────────────────────────────────────────────────────
    serper_api_key: str = ""             # Serper.dev Google Search API key (optional)
    serper_api_keys: str = ""            # extra Serper keys (comma-separated) — stack free 2,500-credit accounts
    instantly_api_key: str = ""          # Instantly.ai Lead Finder API key (optional, 1k free credits)
    google_places_api_key: str = ""      # Google Places API key (city×category business harvest; $200/mo free credit)
    crustdata_api_key: str = ""          # Crustdata API token (company + people search/enrichment, real contacts)
    pdl_api_key: str = ""                # People Data Labs API key (company search + person/decision-maker enrichment)

    # ── DeepSeek LLM (preferred over Groq — higher rate limits) ──────────────
    deepseek_api_key: str = ""           # DeepSeek API key (OpenAI-compatible)
    deepseek_model: str = "deepseek-chat"  # deepseek-chat = DeepSeek-V3

    # ── Human-in-the-Loop (Slack) ─────────────────────────────────────────────
    slack_webhook_url: str = ""          # Slack Incoming Webhook URL (optional)
    base_url: str = "http://localhost:8000"  # used in Slack approve/reject links
    sender_name: str = "Priyanshu"       # Name used in outreach email sign-offs

    # ── Async Pipeline (Celery) ───────────────────────────────────────────────
    celery_broker_url: str = "redis://redis:6379/1"    # Redis DB 1 for Celery
    celery_result_backend: str = "redis://redis:6379/1"

    # ── Vector Store ──────────────────────────────────────────────────────────
    use_pgvector: bool = False           # set True to use pgvector instead of ChromaDB
    postgres_url: str = "postgresql://leadgen:leadgen@postgres:5432/leadgen"

    # ── CRM Integration ───────────────────────────────────────────────────────
    crm_webhook_url: str = ""            # Webhook URL (HubSpot/Zapier/Make/custom)
    google_sheets_id: str = ""           # Google Sheet ID for CRM push (optional)
    google_service_account_json: str = "" # Service account JSON string (optional)

    # ── Scheduled Runs (Celery Beat) ─────────────────────────────────────────
    schedule_enabled: bool = False       # Set True to enable daily scheduled runs
    schedule_hour: int = 8               # Hour to run (24h, IST)
    schedule_minute: int = 0             # Minute to run
    schedule_keyword: str = "manufacturing company India 200 employees"  # Daily keyword

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"          # unknown env vars are silently skipped


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance, loaded once at startup."""
    return Settings()
