"""
FastAPI Application
-------------------
Endpoints:
  GET  /                          Lead generation dashboard (UI)
  POST /generate-leads            Run pipeline (async via Celery if worker running, else sync)
  GET  /pipeline-status/{run_id}  Poll async pipeline job result
  GET  /leads                     Retrieve stored leads
  GET  /leads/pending-review      Leads awaiting human approval
  POST /leads/{id}/approve        Approve a pending_review lead
  POST /leads/{id}/reject         Reject a pending_review lead
  POST /ingest-knowledge          Build RAG knowledge base
  GET  /metrics                   Observability metrics summary
  GET  /health                    Detailed health check
"""
import csv
import io
import json
import os
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from core.config import get_settings
from core.exceptions import (
    PromptInjectionError, InputValidationError,
    RateLimitExceededError, LLMError
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
    Path("./data/logs").mkdir(parents=True, exist_ok=True)
    Path("./data").mkdir(parents=True, exist_ok=True)
    Path("./static").mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    lifespan=lifespan,
    title="AI Lead Generation API",
    description=(
        "Multi-agent HRMS lead generation, Supervisor pattern (LangGraph) "
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

# Serve static assets (dashboard HTML)
_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


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
    keyword: str = "manufacturing company India 200 employees"

    class Config:
        json_schema_extra = {
            "example": {"keyword": "logistics company India 500 employees"}
        }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def dashboard():
    """Serve the lead generation dashboard UI."""
    html_path = Path(__file__).parent.parent / "static" / "dashboard.html"
    if html_path.exists():
        return FileResponse(str(html_path), media_type="text/html")
    return JSONResponse({"message": "Dashboard not found. See /docs for API."})


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
    Safe to call multiple times, skips if already ingested.
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


def _try_celery_async(keyword: str, run_id: str) -> bool:
    """
    Attempt to dispatch the pipeline to a Celery worker.
    Returns True if the task was queued successfully, False if no worker is reachable.
    This allows the endpoint to fall back to synchronous execution gracefully.
    """
    try:
        from worker import run_pipeline_task
        run_pipeline_task.apply_async(
            kwargs={"keyword": keyword, "run_id": run_id},
            task_id=run_id,
        )
        return True
    except Exception:
        return False


@app.post("/generate-leads")
def generate_leads(request: LeadRequest, req: Request):
    """
    Run the full Supervisor multi-agent pipeline:
    Research Agent -> Qualification Agent -> Sales Agent

    Async mode (Celery worker running):
      Returns immediately with a run_id. Poll /pipeline-status/{run_id} for results.

    Sync mode (no worker, default):
      Runs inline, returns results directly. Behavior identical to previous versions.

    Rate limited: 10 requests/minute per IP.
    Input sanitized against prompt injection.
    """
    # Rate limiting
    client_ip = req.client.host
    if not check_rate_limit(client_ip):
        raise RateLimitExceededError("Rate limit exceeded")

    # Input validation + sanitization
    keyword = validate_keyword(request.keyword)
    run_id = str(uuid.uuid4())[:8]

    # Try async dispatch first; fall back to sync if no worker is available
    if _try_celery_async(keyword, run_id):
        return {
            "status": "queued",
            "run_id": run_id,
            "message": f"Pipeline queued. Poll /pipeline-status/{run_id} for results.",
        }

    # Synchronous fallback (default when no Celery worker is running)
    try:
        from graph.supervisor import run_pipeline
        from observability.langsmith_tracer import log_lead_quality

        state = run_pipeline(keyword)
        leads = state.get("leads", [])

        log_lead_quality(leads)

        # Atomic write to avoid corrupt file on concurrent requests or mid-write crash
        data_path = Path(settings.data_path)
        data_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = data_path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump(leads, f, indent=2)
        os.replace(tmp_path, data_path)

        qualified = [l for l in leads if l.get("status") in ("outreach_ready", "pending_review")]
        disqualified = [l for l in leads if l.get("status") == "disqualified"]
        pending = [l for l in leads if l.get("status") == "pending_review"]

        return {
            "status": "success",
            "run_id": run_id,
            "keyword": keyword,
            "summary": {
                "total": len(leads),
                "qualified": len(qualified),
                "pending_review": len(pending),
                "disqualified": len(disqualified),
            },
            "pipeline_log": state.get("messages", []),
            "leads": leads,
        }

    except LLMError as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e.message}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/pipeline-status/{run_id}")
def pipeline_status(run_id: str):
    """
    Poll the status of an async pipeline job dispatched via Celery.
    States: pending | started | success | failure

    If Celery is not running, this endpoint returns a 404 with a helpful message
    since sync runs do not produce a pollable job ID.
    """
    try:
        from celery.result import AsyncResult
        from worker import celery_app
        result = AsyncResult(run_id, app=celery_app)
        response = {"run_id": run_id, "status": result.state}
        if result.state == "SUCCESS":
            response["result"] = result.result
        elif result.state == "FAILURE":
            response["error"] = str(result.result)
        return response
    except ImportError:
        raise HTTPException(
            status_code=404,
            detail="Celery is not running. Pipeline executed synchronously; no job status to poll."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/flush-cache")
def flush_cache():
    """
    Flush the Redis deduplication cache so the next pipeline run can
    re-process companies that were previously seen.  Also clears the
    Celery result backend (DB 1) so stale job states are removed.
    """
    try:
        r = get_redis()
        if r:
            r.flushall()   # clears all Redis DBs (dedup + Celery results)
            return {"status": "ok", "message": "Redis flushed — next run starts fresh"}
        return {"status": "degraded", "message": "Redis not available"}
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

    try:
        with open(data_path) as f:
            leads = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(status_code=500, detail=f"Could not read leads file: {e}")

    if status:
        leads = [l for l in leads if l.get("status") == status]

    return {"total": len(leads), "leads": leads}


def _load_leads() -> list:
    """Load leads from disk. Returns [] if file missing or unreadable."""
    data_path = Path(settings.data_path)
    if not data_path.exists():
        return []
    try:
        with open(data_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_leads(leads: list) -> None:
    """Atomically save leads list to disk."""
    data_path = Path(settings.data_path)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = data_path.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(leads, f, indent=2)
    os.replace(tmp_path, data_path)


@app.get("/leads/pending-review")
def get_pending_review_leads():
    """
    Return all leads currently awaiting human review.
    These are leads where the Sales Agent generated an outreach email
    but SLACK_WEBHOOK_URL is configured, so they are held for approval
    before being marked outreach_ready.
    """
    leads = _load_leads()
    pending = [l for l in leads if l.get("status") == "pending_review"]
    return {"total": len(pending), "leads": pending}


@app.get("/leads/{lead_id}/approve")
def approve_lead_get(lead_id: str):
    """GET version for Slack button links — same logic as POST."""
    return approve_lead(lead_id)


@app.post("/leads/{lead_id}/approve")
def approve_lead(lead_id: str):
    """
    Approve a pending_review lead, marking it outreach_ready.
    Also triggers CRM push (webhook / Google Sheets) if configured.
    Called by a human reviewer after inspecting the Slack notification.
    The lead will then appear in GET /leads?status=outreach_ready.
    """
    leads = _load_leads()
    lead = next((l for l in leads if l.get("id") == lead_id), None)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    if lead.get("status") != "pending_review":
        raise HTTPException(
            status_code=400,
            detail=f"Lead is not pending review (current status: {lead.get('status')})"
        )
    lead["status"] = "outreach_ready"
    _save_leads(leads)

    # Push to CRM after approval (fire-and-forget, never blocks the response)
    try:
        from tools.crm_push import push_lead_to_crm
        push_lead_to_crm(lead)
    except Exception:
        pass  # CRM push failure must never break approval flow

    return {"message": f"Lead {lead_id} approved", "lead": lead}


@app.get("/leads/{lead_id}/reject")
def reject_lead_get(lead_id: str):
    """GET version for Slack button links — same logic as POST."""
    return reject_lead(lead_id)


@app.post("/leads/{lead_id}/reject")
def reject_lead(lead_id: str):
    """
    Reject a pending_review lead, marking it disqualified.
    Called by a human reviewer who decides the outreach email is not suitable.
    """
    leads = _load_leads()
    lead = next((l for l in leads if l.get("id") == lead_id), None)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    if lead.get("status") != "pending_review":
        raise HTTPException(
            status_code=400,
            detail=f"Lead is not pending review (current status: {lead.get('status')})"
        )
    lead["status"] = "disqualified"
    _save_leads(leads)
    return {"message": f"Lead {lead_id} rejected", "lead": lead}


@app.get("/leads/export/csv")
def export_leads_csv(status: Optional[str] = None):
    """
    Export leads as a CSV file for the sales team.
    Includes all contact fields: company, industry, size, location, address,
    phone, emails, decision makers, pain points, score, and outreach email.

    Optional ?status= filter: outreach_ready | qualified | disqualified | pending_review
    """
    leads = _load_leads()
    if status:
        leads = [l for l in leads if l.get("status") == status]

    fieldnames = [
        "company_name", "website", "industry", "size", "location",
        "address", "phone", "contact_emails", "decision_makers",
        "pain_points", "qualification_score", "status",
        "email_subject", "email_body",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for lead in leads:
        outreach = lead.get("outreach_draft") or {}
        writer.writerow({
            "company_name": lead.get("company_name", ""),
            "website": lead.get("website", ""),
            "industry": lead.get("industry", ""),
            "size": lead.get("size", ""),
            "location": lead.get("location", ""),
            "address": lead.get("address", ""),
            "phone": lead.get("phone", ""),
            "contact_emails": "; ".join(lead.get("contact_emails") or []),
            "decision_makers": "; ".join(lead.get("decision_makers") or []),
            "pain_points": "; ".join(lead.get("pain_points") or []),
            "qualification_score": lead.get("qualification_score", ""),
            "status": lead.get("status", ""),
            "email_subject": outreach.get("subject", ""),
            "email_body": outreach.get("email_body", ""),
        })

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@app.get("/leads/{lead_id}")
def get_lead(lead_id: str):
    """Retrieve a single lead by ID."""
    leads = _load_leads()
    lead = next((l for l in leads if l.get("id") == lead_id), None)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    return lead


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
