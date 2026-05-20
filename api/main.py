"""
FastAPI Application
-------------------
Endpoints:
  POST /generate-leads    → Run full multi-agent pipeline
  GET  /leads             → Retrieve stored leads
  POST /ingest-knowledge  → Build RAG knowledge base
  GET  /metrics           → Observability metrics summary
  GET  /health            → Detailed health check
"""
import json
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from core.config import get_settings
from core.exceptions import (
    PromptInjectionError, InputValidationError,
    RateLimitExceededError, RAGNotReadyError, LLMError
)
from core.security import validate_keyword
from core.logging import setup_logging
from cache.redis_client import check_rate_limit, get_redis
from observability.langsmith_tracer import setup_langsmith, get_metrics_summary

settings = get_settings()
setup_logging()
setup_langsmith()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: ensure required directories exist before accepting requests."""
    from pathlib import Path
    Path("./data/logs").mkdir(parents=True, exist_ok=True)
    Path("./data").mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    lifespan=lifespan,
    title="AI Lead Generation API",
    description=(
        "Multi-agent HRMS lead generation — Supervisor pattern (LangGraph) "
        "+ RAG (ChromaDB + HuggingFace) + Groq (Llama 3)"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Global Exception Handlers ─────────────────────────────────────────────────

@app.exception_handler(PromptInjectionError)
async def injection_handler(request: Request, exc: PromptInjectionError):
    return JSONResponse(status_code=400, content={
        "error": "invalid_input",
        "message": "Keyword contains disallowed content",
    })

@app.exception_handler(RateLimitExceededError)
async def rate_limit_handler(request: Request, exc: RateLimitExceededError):
    return JSONResponse(status_code=429, content={
        "error": "rate_limit_exceeded",
        "message": f"Max {settings.rate_limit_per_minute} requests/minute",
    })

@app.exception_handler(InputValidationError)
async def validation_handler(request: Request, exc: InputValidationError):
    return JSONResponse(status_code=422, content={
        "error": "validation_error",
        "message": exc.message,
    })


# ── Models ────────────────────────────────────────────────────────────────────

class LeadRequest(BaseModel):
    keyword: str = "HRMS software company India"

    class Config:
        json_schema_extra = {
            "example": {"keyword": "manufacturing company India 200 employees"}
        }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Detailed health check including dependency status."""
    redis_ok = False
    try:
        r = get_redis()
        redis_ok = r is not None and r.ping()
    except Exception:
        pass

    return {
        "status": "ok",
        "service": "AI Lead Generation API",
        "dependencies": {
            "redis": "connected" if redis_ok else "unavailable (degraded mode)",
            "groq_model": settings.groq_model,
            "embed_model": settings.embed_model,
        }
    }


@app.post("/ingest-knowledge")
def ingest_knowledge():
    """
    Scrape humanmaximizer.com and build the RAG vector store.
    Must be called once before /generate-leads.
    Safe to call multiple times — skips if already ingested.
    """
    try:
        from rag.scraper import build_corpus
        from rag.embeddings import ingest_documents, is_knowledge_base_ready

        if is_knowledge_base_ready():
            return {
                "status": "skipped",
                "message": "Knowledge base already built. Delete ./data/chroma_db to re-ingest."
            }

        corpus = build_corpus()
        chunks = ingest_documents(corpus)

        return {
            "status": "success",
            "pages_scraped": len(corpus),
            "chunks_stored": chunks,
            "embed_model": settings.embed_model,
            "vector_store": "ChromaDB",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-leads")
def generate_leads(request: LeadRequest, req: Request):
    """
    Run the full Supervisor multi-agent pipeline:
    Research Agent → Qualification Agent → Sales Agent

    Rate limited: 10 requests/minute per IP.
    Input sanitized against prompt injection.
    """
    # Rate limiting
    client_ip = req.client.host
    if not check_rate_limit(client_ip):
        raise RateLimitExceededError("Rate limit exceeded")

    # Input validation + sanitization
    keyword = validate_keyword(request.keyword)

    try:
        from graph.supervisor import run_pipeline
        from observability.langsmith_tracer import log_lead_quality

        state = run_pipeline(keyword)
        leads = state.get("leads", [])

        # Log quality metrics for observability
        log_lead_quality(leads)

        # Persist results
        data_path = Path(settings.data_path)
        data_path.parent.mkdir(parents=True, exist_ok=True)
        with open(data_path, "w") as f:
            json.dump(leads, f, indent=2)

        qualified = [l for l in leads if l.get("status") == "outreach_ready"]
        disqualified = [l for l in leads if l.get("status") == "disqualified"]

        return {
            "status": "success",
            "keyword": keyword,
            "summary": {
                "total": len(leads),
                "qualified": len(qualified),
                "disqualified": len(disqualified),
            },
            "pipeline_log": state.get("messages", []),
            "leads": leads,
        }

    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/leads")
def get_leads(status: Optional[str] = None):
    """
    Retrieve stored leads filtered by status.
    Status options: outreach_ready | qualified | disqualified | researched
    """
    data_path = Path(settings.data_path)
    if not data_path.exists():
        return {"leads": [], "message": "No leads yet. Call POST /generate-leads first."}

    with open(data_path) as f:
        leads = json.load(f)

    if status:
        leads = [l for l in leads if l.get("status") == status]

    return {"total": len(leads), "leads": leads}


@app.get("/metrics")
def get_metrics():
    """
    Observability metrics summary:
    - Pipeline latency per stage
    - Agent failure count
    - Hallucination warning count
    - Lead quality scores
    """
    return get_metrics_summary()
