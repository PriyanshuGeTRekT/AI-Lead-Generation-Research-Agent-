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
    groq_api_key: str
    groq_model: str = "llama3-8b-8192"

    # LLM generation parameters
    # temperature=0.1 for structured extraction (deterministic)
    # temperature=0.4 for email writing (some creativity needed)
    llm_temperature_extract: float = 0.1
    llm_temperature_creative: float = 0.4
    llm_max_tokens_extract: int = 600
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
    max_leads_per_run: int = 5
    max_iterations: int = 10
    web_search_results: int = 8
    request_timeout: int = 10            # seconds for web scraping

    # ── Observability ─────────────────────────────────────────────────────────
    langchain_api_key: str = ""          # LangSmith (optional)
    langchain_tracing_v2: str = "false"
    langchain_project: str = "ai-lead-gen"
    log_level: str = "INFO"

    # ── Security ──────────────────────────────────────────────────────────────
    rate_limit_per_minute: int = 10      # max /generate-leads calls per minute
    max_keyword_length: int = 200        # prevent prompt injection via long inputs
    data_path: str = "./data/leads.json"

    # ── Human-in-the-Loop (Slack) ─────────────────────────────────────────────
    slack_webhook_url: str = ""          # Slack Incoming Webhook URL (optional)
    base_url: str = "http://localhost:8000"  # used in Slack approve/reject links

    # ── Async Pipeline (Celery) ───────────────────────────────────────────────
    celery_broker_url: str = "redis://redis:6379/1"    # Redis DB 1 for Celery
    celery_result_backend: str = "redis://redis:6379/1"

    # ── Vector Store ──────────────────────────────────────────────────────────
    use_pgvector: bool = False           # set True to use pgvector instead of ChromaDB
    postgres_url: str = "postgresql://leadgen:leadgen@postgres:5432/leadgen"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance, loaded once at startup."""
    return Settings()
