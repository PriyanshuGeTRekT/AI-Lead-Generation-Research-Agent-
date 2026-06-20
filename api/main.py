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
import re
import uuid
import ipaddress
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, Query, BackgroundTasks
from loguru import logger
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


def _cors_origins() -> list[str]:
    origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
    return origins or ["http://localhost:8000", "http://127.0.0.1:8000"]


def _is_local_client(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_loopback or ip.is_private
    except ValueError:
        return host in {"localhost"}


def _require_admin(request: Request) -> None:
    """
    Protect lead data and state-changing endpoints.
    Local/dev access works without a key; remote deployments should set API_ADMIN_KEY.
    """
    expected = settings.api_admin_key
    provided = request.headers.get("x-api-key") or request.query_params.get("api_key")

    if expected:
        if provided != expected:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return

    if not _is_local_client(request):
        raise HTTPException(
            status_code=403,
            detail="Remote access requires API_ADMIN_KEY to be configured",
        )


def _require_review_action(request: Request, token: Optional[str]) -> None:
    if settings.review_action_token:
        if token != settings.review_action_token:
            raise HTTPException(status_code=401, detail="Invalid review action token")
        return
    _require_admin(request)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: ensure required directories exist before accepting requests."""
    Path("./data/logs").mkdir(parents=True, exist_ok=True)
    Path("./data").mkdir(parents=True, exist_ok=True)
    Path("./static").mkdir(parents=True, exist_ok=True)
    # Warm the CRM aggregate cache in the background so the first CRM open is instant.
    import threading
    def _warm():
        try:
            from core import warehouse
            warehouse.warm_crm_cache()
            logger.info("[startup] CRM aggregate cache warmed")
        except Exception as e:
            logger.debug(f"[startup] CRM warm failed: {e}")
    threading.Thread(target=_warm, daemon=True).start()
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
    allow_origins=_cors_origins(),
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
    max_leads: Optional[int] = None   # override MAX_LEADS_PER_RUN for this run (max 100)
    country: Optional[str] = None     # geo filter: restrict to a country (e.g. "India")
    region: Optional[str] = None      # geo filter: restrict to a state/region (e.g. "Maharashtra")
    exclude_with_hrms: bool = True    # drop companies that already run an HRMS
    mode: str = "discover"            # 'discover' (ICP search) | 'company' (find a named company)
    fast: bool = True                 # fast mode: deterministic, no per-candidate LLM (much quicker)
    run_id: Optional[str] = None      # client-supplied stream id so the UI can open /stream/{id}
                                      # BEFORE the (sync) run finishes — enables live Agent Theater

    class Config:
        json_schema_extra = {
            "example": {
                "keyword": "logistics company 500 employees",
                "max_leads": 25,
                "country": "India",
                "region": "Maharashtra",
                "exclude_with_hrms": True,
            }
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
def ingest_knowledge(req: Request):
    """
    Scrape humanmaximizer.com and build the RAG vector store.
    Must be called once before /generate-leads.
    Safe to call multiple times, skips if already ingested.
    """
    _require_admin(req)

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


def _try_celery_async(keyword: str, run_id: str, max_leads: int, geo: dict) -> bool:
    """
    Attempt to dispatch the pipeline to a Celery worker.
    Returns True if the task was queued successfully, False if no worker is reachable.
    """
    try:
        from worker import celery_app, run_pipeline_task
        workers = celery_app.control.ping(timeout=0.5)
        if not workers:
            return False
        run_pipeline_task.apply_async(
            kwargs={
                "keyword": keyword,
                "run_id": run_id,
                "max_leads": max_leads,
                "country": geo.get("country"),
                "region": geo.get("region"),
                "exclude_with_hrms": geo.get("exclude_with_hrms", True),
                "mode": geo.get("mode", "discover"),
                "fast": geo.get("fast", True),
            },
            task_id=run_id,
        )
        return True
    except Exception:
        return False


@app.post("/generate-leads")
def generate_leads(request: LeadRequest, req: Request, background: BackgroundTasks):
    """
    Run the full Supervisor multi-agent pipeline:
    Research Agent -> Qualification Agent -> Sales Agent

    Async mode (Celery worker running):
      Returns immediately with a run_id. Poll /pipeline-status/{run_id} for results.

    Sync mode (no worker, default):
      Runs inline, returns results directly.

    max_leads: override the default 50-lead cap (max 100). Larger values take longer.
    Rate limited: 10 requests/minute per IP.
    Input sanitized against prompt injection.
    """
    _require_admin(req)

    # Rate limiting
    client_ip = req.client.host
    if not check_rate_limit(client_ip):
        raise RateLimitExceededError("Rate limit exceeded")

    # Input validation + sanitization
    keyword = validate_keyword(request.keyword)
    # Honor a client-supplied run_id (sanitized) so the UI can subscribe to the
    # live event stream immediately; otherwise mint one.
    _rid = re.sub(r"[^a-zA-Z0-9\-]", "", request.run_id or "")[:32]
    run_id = _rid or str(uuid.uuid4())[:8]

    # Resolve max_leads: request override → config default (capped at 100)
    max_leads = min(request.max_leads or settings.max_leads_per_run, 100)
    if max_leads < 1:
        raise InputValidationError("max_leads must be between 1 and 100")

    geo = {
        "country": request.country,
        "region": request.region,
        "exclude_with_hrms": request.exclude_with_hrms,
        "mode": request.mode,
        "fast": request.fast,
    }

    # ── Warehouse-first (discover mode) ───────────────────────────────────────
    # Search = filter the pre-harvested pool. Serve matching enriched leads
    # INSTANTLY (no crawl, no tokens) — even if fewer than requested — and quietly
    # top up the pool in the background so next time is fuller. We only fall through
    # to a live crawl when the pool has NOTHING for this query (cold bootstrap).
    if request.mode != "find_company":
        try:
            from core import warehouse
            pooled = warehouse.query(industry=keyword, region=request.region, limit=max_leads)
            if len(pooled) < max_leads:  # broaden: any enriched lead in-region
                extra = warehouse.query(region=request.region, limit=max_leads)
                seen = {l.get("website") or l.get("company_name") for l in pooled}
                pooled += [l for l in extra if (l.get("website") or l.get("company_name")) not in seen]
                pooled = pooled[:max_leads]
            if pooled:
                existing = _load_leads()
                ex_keys = {l.get("id") or l.get("company_name") for l in existing}
                merged = existing + [l for l in pooled if (l.get("id") or l.get("company_name")) not in ex_keys]
                _save_leads(merged)
                # Short of the ask? Fill the pool in the background for next time.
                if len(pooled) < max_leads:
                    def _topup(kw, reg, mode):
                        try:
                            from core import warehouse as wh
                            from tools.web_search import search_companies_multi_source
                            from agents import enrichment_worker
                            cands = search_companies_multi_source(kw, max_results=80)
                            wh.upsert_raw(cands, region=reg, industry=kw)
                            enrichment_worker.enrich_pool(batch=40, fast=True, region=reg, industry=kw)
                        except Exception as e:
                            logger.debug(f"[topup] {e}")
                    background.add_task(_topup, keyword, request.region, request.mode)
                q = [l for l in pooled if l.get("status") in ("outreach_ready", "pending_review", "qualified", "enriched")]
                return {
                    "status": "success", "run_id": run_id, "keyword": keyword,
                    "served_from": "warehouse",
                    "summary": {"total": len(pooled), "qualified": len(q), "pending_review": 0, "disqualified": 0},
                    "pipeline_log": [
                        f"Served {len(pooled)} leads instantly from the pool (no crawl, no tokens)."
                        + ("" if len(pooled) >= max_leads else " Topping up the pool in the background.")
                    ],
                    "leads": merged,
                }
        except Exception:
            pass

    # Try async dispatch first; fall back to sync if no worker is available
    if _try_celery_async(keyword, run_id, max_leads, geo):
        return {
            "status": "queued",
            "run_id": run_id,
            "max_leads": max_leads,
            "message": f"Pipeline queued (up to {max_leads} leads). Poll /pipeline-status/{run_id} for results.",
        }

    # Synchronous fallback (default when no Celery worker is running)
    try:
        from graph.supervisor import run_pipeline
        from observability.langsmith_tracer import log_lead_quality

        state = run_pipeline(
            keyword, max_leads=max_leads, run_id=run_id,
            country=request.country, region=request.region,
            exclude_with_hrms=request.exclude_with_hrms, mode=request.mode, fast=request.fast,
        )
        leads = state.get("leads", [])

        log_lead_quality(leads)

        # Merge new leads with all previously saved leads, then save
        # This ensures all runs accumulate — /leads always returns full history
        if leads:
            existing = _load_leads()
            existing_keys = {l.get("id") or l.get("company_name") for l in existing}
            truly_new = [l for l in leads if (l.get("id") or l.get("company_name")) not in existing_keys]
            all_leads = existing + truly_new
            _save_leads(all_leads)
            leads = all_leads  # return full list in response

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


@app.get("/stream/{run_id}")
def stream_theater(run_id: str, req: Request):
    """
    Server-Sent Events stream for the Live Agent Theater. Replays the full
    backlog of theater events for a run, then tails new ones until the pipeline
    emits 'done' (or a 5-minute safety timeout). Backed by observability.event_bus.
    """
    _require_admin(req)
    from observability.event_bus import read as _read_events
    import time as _time

    def gen():
        sent = 0
        deadline = _time.time() + 300
        yield ": connected\n\n"  # open the stream immediately
        while _time.time() < deadline:
            try:
                events = _read_events(run_id, sent)
            except Exception:
                events = []
            for e in events:
                yield f"data: {json.dumps(e)}\n\n"
                sent += 1
                if e.get("type") == "done":
                    return
            _time.sleep(0.4)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/track/pixel")
@app.get("/track/pixel.gif")
def track_pixel(req: Request, page: str = "", ref: str = ""):
    """Website-visitor pixel. Embed on your site; resolves visitor IP → company."""
    from fastapi import Response
    from tools.tracking import record_visit, PIXEL
    ip = (req.headers.get("x-forwarded-for", "").split(",")[0].strip() or (req.client.host if req.client else ""))
    try:
        record_visit(ip, page=page, ref=ref)
    except Exception:
        pass
    return Response(content=PIXEL, media_type="image/gif", headers={"Cache-Control": "no-store"})


@app.get("/visitors")
def visitors(req: Request, limit: int = 200):
    """Identified website visitors (companies), newest first."""
    _require_admin(req)
    from tools.tracking import list_visitors
    v = list_visitors(limit=limit)
    return {"total": len(v), "visitors": v}


@app.get("/track/open/{lead_id}/{variant}.gif")
@app.get("/track/open/{lead_id}/{variant}")
def track_open(lead_id: str, variant: str):
    """Email open pixel (live A/B)."""
    from fastapi import Response
    from tools.tracking import record_email_event, PIXEL
    try:
        record_email_event(lead_id, variant, "open")
    except Exception:
        pass
    return Response(content=PIXEL, media_type="image/gif", headers={"Cache-Control": "no-store"})


@app.get("/track/click/{lead_id}/{variant}")
def track_click(lead_id: str, variant: str, u: str = "/"):
    """Email click tracker (live A/B) → 302 redirect to the real target."""
    from fastapi.responses import RedirectResponse
    from tools.tracking import record_email_event
    try:
        record_email_event(lead_id, variant, "click")
    except Exception:
        pass
    target = u if u.startswith("http") else "https://humanmaximizer.com"
    return RedirectResponse(url=target, status_code=302)


@app.get("/track/ab-stats")
def track_ab_stats(req: Request):
    """Per-variant open/click rates + the live A/B winner."""
    _require_admin(req)
    from tools.tracking import ab_stats
    return ab_stats()


@app.post("/track/register-send")
async def track_register_send(req: Request):
    """Record that variant X was sent to lead Y (so A/B rates have a denominator)."""
    _require_admin(req)
    from tools.tracking import record_send
    try:
        body = await req.json()
    except Exception:
        body = {}
    lead_id, variant = str(body.get("lead_id", "")), str(body.get("variant", "A"))
    if lead_id:
        record_send(lead_id, variant)
    return {"ok": True}


@app.post("/chat")
async def chat(req: Request):
    """24/7 inbound chatbot (Maxi). Public — qualifies website visitors via the LLM."""
    try:
        body = await req.json()
    except Exception:
        body = {}
    messages = body.get("messages") if isinstance(body, dict) else None
    if not isinstance(messages, list):
        messages = []
    from agents.chat_agent import chat_reply
    return {"reply": chat_reply(messages)}


@app.get("/debug/explorium")
def debug_explorium(req: Request, keyword: str = "manufacturing", region: str = ""):
    """Probe the live Explorium API and return the raw response shape, so the
    candidate mapping can be locked to your account. Secrets are not returned."""
    _require_admin(req)
    from tools.sources.explorium import probe
    return probe(keyword=keyword, region=region or None)


@app.get("/config")
def get_config(req: Request):
    """Masked runtime config (API keys / LLM provider set via the Settings panel)."""
    _require_admin(req)
    from core import runtime_config as rc
    return rc.public_config()


@app.post("/config")
async def set_config(req: Request):
    """Update runtime config from the Settings panel. Secrets persisted server-side, never echoed raw."""
    _require_admin(req)
    from core import runtime_config as rc
    try:
        body = await req.json()
    except Exception:
        body = {}
    return rc.update(body if isinstance(body, dict) else {})


@app.get("/cache/stats")
def cache_stats(req: Request):
    """Company verdict cache stats — how many companies are remembered (hot/excluded)."""
    _require_admin(req)
    try:
        from core.lead_cache import stats
        return stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/warehouse/stats")
def warehouse_stats(req: Request):
    """Lead pool size — raw (harvested), enriched, qualified, excluded."""
    _require_admin(req)
    from core import warehouse
    return warehouse.stats()


@app.get("/warehouse/leads")
def warehouse_leads(req: Request, industry: str = "", region: str = "", min_score: float = 0.0, limit: int = 50):
    """Instant filtered retrieval from the enriched pool (no API crawl)."""
    _require_admin(req)
    from core import warehouse
    leads = warehouse.query(
        industry=industry or None, region=region or None,
        min_score=min_score, limit=min(limit, 200),
    )
    return {"leads": leads, "total": len(leads)}


@app.post("/harvest")
def harvest(request: LeadRequest, req: Request, background: BackgroundTasks):
    """
    Cheaply grow the lead pool: crawl the sources for raw candidates and bank them
    as 'raw' in the warehouse. No scraping, no AI, no tokens — just discovery.
    Runs in the background so the call returns immediately.
    """
    _require_admin(req)
    keyword = validate_keyword(request.keyword)
    region = request.region

    def _do_harvest(kw: str, reg: Optional[str], mode: str):
        try:
            from core import warehouse
            from tools.web_search import search_companies_multi_source, find_company
            if mode == "find_company":
                cands = find_company(kw, reg or "", max_results=20)
            else:
                cands = search_companies_multi_source(kw, max_results=200)
            added = warehouse.upsert_raw(cands, region=reg)
            logger.info(f"[harvest] '{kw}' -> {len(cands)} candidates, {added} new in pool")
        except Exception as e:
            logger.warning(f"[harvest] failed: {e}")

    background.add_task(_do_harvest, keyword, region, request.mode)
    return {"status": "harvesting", "keyword": keyword, "message": "Harvest started — pool will grow in the background. Poll /warehouse/stats."}


@app.post("/warehouse/enrich")
def warehouse_enrich(request: LeadRequest, req: Request, background: BackgroundTasks):
    """
    Background enrichment: drain raw pool candidates through the full funnel and
    bank them as enriched/qualified. Fans I/O across a thread pool; LLM work rides
    the multi-endpoint pool. Returns immediately — poll /warehouse/stats.
    """
    _require_admin(req)
    from agents import enrichment_worker
    if enrichment_worker.is_running():
        return {"status": "busy", "message": "An enrichment pass is already running."}

    batch = min(request.max_leads or 25, 100)
    region = request.region

    def _do_enrich(n: int, fast: bool, reg):
        try:
            res = enrichment_worker.enrich_pool(batch=n, fast=fast, region=reg)
            logger.info(f"[enrich] background pass done: {res.get('status')} "
                        f"({res.get('enriched', 0)}/{res.get('processed', 0)})")
        except Exception as e:
            logger.warning(f"[enrich] background pass failed: {e}")

    background.add_task(_do_enrich, batch, request.fast, region)
    return {"status": "enriching", "batch": batch,
            "message": f"Enriching up to {batch} pooled candidates in the background. Poll /warehouse/stats."}


@app.post("/warehouse/reset")
def warehouse_reset(req: Request):
    """Wipe the lead pool (rebuild from scratch). Also flushes the verdict cache."""
    _require_admin(req)
    from core import warehouse
    out = warehouse.reset()
    try:
        from core.lead_cache import flush as _flush
        _flush()
    except Exception:
        pass
    return out


@app.get("/crm/leads")
def crm_leads(req: Request, stage: str = "all", tier: str = "", state: str = "",
              industry: str = "", q: str = "", sort: str = "score", dir: str = "desc",
              page: int = 1, page_size: int = 50, min_signal: float = 0.0,
              has_phone: bool = False, has_contact: bool = False, enriched_recently: bool = False,
              industries: str = ""):
    """Server-side paginated/filtered/sorted leads — the browser only ever holds one
    page, so this scales to lakhs of rows with ease."""
    _require_admin(req)
    from core import warehouse
    return warehouse.crm_query(stage=stage or None, tier=tier or None, state=state or None,
                               industry=industry or None, q=q or None, sort=sort, direction=dir,
                               page=page, page_size=page_size, min_signal=min_signal,
                               has_phone=has_phone, has_contact=has_contact,
                               enriched_recently=enriched_recently, industries=industries or None)


@app.post("/enrich/contacts")
def enrich_contacts(req: Request, background: BackgroundTasks, state: str = "",
                    limit: int = 3000, only_missing_phone: bool = True, min_signal: float = 0.0):
    """Find the decision-maker (founder/director/owner) + a phone for leads via Serper
    (1 call/lead, PRIME-first), and stamp contact_enriched_at. Needs a Serper key.
    Background; poll /enrich/contacts/status."""
    _require_admin(req)
    from core import warehouse, signals
    if not signals._serper_keys():
        return {"status": "error", "message": "No Serper key configured."}

    def _do(st, lim, omp, ms):
        try:
            res = warehouse.enrich_contacts(state=st or None, limit=lim, only_missing_phone=omp, min_signal=ms)
            logger.info(f"[contacts] done: {res}")
        except Exception as e:
            logger.warning(f"[contacts] failed: {e}")

    background.add_task(_do, state, limit, only_missing_phone, min_signal)
    return {"status": "started", "state": state or "all",
            "message": "Contact enrichment started. Poll /enrich/contacts/status."}


@app.get("/enrich/contacts/status")
def enrich_contacts_status(req: Request):
    """Progress of decision-maker + phone enrichment."""
    _require_admin(req)
    from core import warehouse
    return warehouse.contact_enrich_status()


@app.post("/enrich/crawl")
def enrich_crawl(req: Request, background: BackgroundTasks, state: str = "", limit: int = 1000, only_missing_phone: bool = True):
    """Crawl leads' OWN websites (crawl4ai) to extract a published phone + decision-maker
    (name/role/email). Targets leads with a real website. Background; poll /enrich/crawl/status."""
    _require_admin(req)
    from core import warehouse
    from tools import crawl4ai_contacts
    if not crawl4ai_contacts.available():
        return {"status": "error", "message": "crawl4ai not installed. Run: pip install crawl4ai && crawl4ai-setup"}

    def _do(st, lim, omp):
        try:
            res = warehouse.crawl_enrich_contacts(state=st or None, limit=lim, only_missing_phone=omp)
            logger.info(f"[crawl4ai] done: {res}")
        except Exception as e:
            logger.warning(f"[crawl4ai] failed: {e}")

    background.add_task(_do, state, limit, only_missing_phone)
    return {"status": "started", "state": state or "all", "message": "Website crawl enrichment started. Poll /enrich/crawl/status."}


@app.get("/verify/company")
def verify_company(req: Request, name: str, city: str = ""):
    """Live verification: look up ANY company by name → Google-Maps phone + website +
    (crawl/Serper) decision-maker. Lets the user test the pipeline on companies they
    know. Also reports whether it's already in our warehouse. Needs a Serper key."""
    _require_admin(req)
    from core import warehouse, signals
    out = {"query": name, "in_warehouse": False, "places": {}, "decision_maker": {}}
    # already in pool?
    db = warehouse._db()
    if db:
        try:
            with warehouse._LOCK:
                r = db.execute("SELECT company_name, state, industry, phone FROM leads "
                               "WHERE LOWER(company_name) LIKE ? LIMIT 1", ("%" + name.lower() + "%",)).fetchone()
            if r:
                out["in_warehouse"] = True
                out["warehouse_row"] = {"company": r["company_name"], "state": r["state"],
                                        "industry": r["industry"], "phone": r["phone"]}
        except Exception:
            pass
    if not signals._serper_keys():
        out["error"] = "No Serper key configured — cannot do a live lookup."
        return out
    try:
        from tools.sources import places_serper
        out["places"] = places_serper.lookup_company(name, city) or {}
    except Exception as e:
        out["places_error"] = str(e)
    # decision-maker: crawl the site if we found one, else Serper
    try:
        site = (out["places"].get("website") or "").strip()
        if site:
            from tools import crawl4ai_contacts
            res = (crawl4ai_contacts.crawl_contacts([site]) or {}).get(site, {})
            if res.get("name") or res.get("phone"):
                out["decision_maker"] = res
        if not out["decision_maker"]:
            from core import contact_finder
            out["decision_maker"] = contact_finder.find_contact(name, city) or {}
    except Exception as e:
        out["dm_error"] = str(e)
    return out


@app.post("/segment/right-size")
def segment_right_size(req: Request, background: BackgroundTasks, state: str = "Delhi NCR",
                       industries: str = "IT services,BPO,consulting", min_emp: int = 10,
                       max_emp: int = 800, do_headcount: bool = True):
    """Tighten a segment to the HRMS sweet spot: exclude enterprise/MNC/outlet names,
    scrub invalid phones, and (Serper headcount) drop >max_emp + <min_emp. Background;
    poll /segment/right-size/status."""
    _require_admin(req)
    from core import warehouse

    def _do(st, inds, lo, hi, hc):
        try:
            res = warehouse.right_size_segment(state=st or None, industries=inds or None,
                                               min_emp=lo, max_emp=hi, do_headcount=hc)
            logger.info(f"[right_size] done: {res}")
        except Exception as e:
            logger.warning(f"[right_size] failed: {e}")

    background.add_task(_do, state, industries, min_emp, max_emp, do_headcount)
    return {"status": "started", "message": "Right-sizing started. Poll /segment/right-size/status."}


@app.get("/segment/right-size/status")
def segment_right_size_status(req: Request):
    _require_admin(req)
    from core import warehouse
    return warehouse.right_size_status()


@app.get("/enrich/crawl/status")
def enrich_crawl_status(req: Request):
    """Progress of the crawl4ai website enrichment."""
    _require_admin(req)
    from core import warehouse
    return warehouse.crawl_enrich_status()


@app.post("/harvest/places-serper")
def harvest_places_serper(req: Request, background: BackgroundTasks, cities: str = "", categories: str = ""):
    """PHONE-FIRST harvest from Google Maps (Serper Places) for Delhi-NCR — businesses
    with Google-verified phone + name + website. ~15-20 phone leads per search call.
    Needs a Serper key. Background; poll /harvest/places-serper/status."""
    _require_admin(req)
    from tools.sources import places_serper
    from core import signals
    if not signals._serper_keys():
        return {"status": "error", "message": "No Serper key configured."}
    cl = [c.strip() for c in cities.split(",") if c.strip()] or None
    cats = [c.strip() for c in categories.split(",") if c.strip()] or None

    def _do(cl, cats):
        try:
            res = places_serper.harvest_to_warehouse(cities=cl, categories=cats)
            logger.info(f"[places_serper] done: {res}")
        except Exception as e:
            logger.warning(f"[places_serper] failed: {e}")

    background.add_task(_do, cl, cats)
    return {"status": "started", "message": "Google Maps (Places) phone-first harvest started. Poll /harvest/places-serper/status."}


@app.get("/harvest/places-serper/status")
def harvest_places_serper_status(req: Request):
    """Progress of the Google Maps phone-first harvest."""
    _require_admin(req)
    from tools.sources import places_serper
    return places_serper.status()


@app.post("/startups/harvest")
def startups_harvest(req: Request, background: BackgroundTasks, dpiit: bool = False,
                     states: str = "", industries: str = "", max_pages: int = 0,
                     restart: bool = False):
    """Scrape the Startup India government registry (454k startups, or 146k DPIIT-
    recognized with dpiit=true) into the `startups` table. Captures name, state, city,
    industry, sector, stage, DPIIT status + registration date. RESUMABLE per filter —
    re-calling continues where it left off (restart=true to start over). Long-running
    (9 records/page → ~50k pages for all); background, poll /startups/harvest/status."""
    _require_admin(req)
    from core import startup_india as si

    def _do():
        try:
            res = si.harvest(dpiit=dpiit, states=states or None, industries=industries or None,
                             max_pages=(max_pages or None), restart=restart)
            logger.info(f"[startupindia] harvest done: {res}")
        except Exception as e:
            logger.warning(f"[startupindia] harvest failed: {e}")

    background.add_task(_do)
    scope = "DPIIT-recognized (~146k)" if dpiit else "all startups (~454k)"
    return {"status": "started", "scope": scope,
            "message": "Startup India harvest started (resumable). Poll /startups/harvest/status."}


@app.get("/startups/harvest/status")
def startups_harvest_status(req: Request):
    """Progress of the Startup India registry scrape."""
    _require_admin(req)
    from core import startup_india as si
    return si.status()


@app.post("/startups/harvest/stop")
def startups_harvest_stop(req: Request):
    """Pause the running harvest cleanly (resume point is saved; click Resume later)."""
    _require_admin(req)
    from core import startup_india as si
    return si.stop()


@app.get("/startups")
def startups_list(req: Request, state: str = "", industry: str = "", q: str = "",
                  limit: int = 100, offset: int = 0, has_contact: bool = False,
                  sort: str = "registered_on", direction: str = "desc",
                  ncr: bool = False, dpiit: bool = False, stage: str = ""):
    """Paginated, filtered list of harvested startups. `ncr`=Delhi-NCR region,
    `dpiit`=DPIIT-recognized only, `stage`=lifecycle stage (e.g. Scaling)."""
    _require_admin(req)
    from core import startup_india as si
    return si.query(state=state, industry=industry, q=q, limit=min(limit, 500),
                    offset=offset, has_contact=has_contact, sort=sort, direction=direction,
                    ncr=ncr, dpiit=dpiit, stage=stage)


@app.get("/startups/counts")
def startups_counts(req: Request):
    """Totals + by-state / by-industry breakdown of harvested startups."""
    _require_admin(req)
    from core import startup_india as si
    return si.counts()


@app.get("/startups/options")
def startups_options(req: Request):
    """Distinct states + industries present in the startups table (filter dropdowns)."""
    _require_admin(req)
    from core import startup_india as si
    return si.filter_options()


@app.post("/startups/enrich")
def startups_enrich(req: Request, background: BackgroundTasks, ncr: bool = True,
                    dpiit: bool = True, stage: str = "Scaling", limit: int = 100):
    """Enrich the filtered startup slice via Apify: Google Maps (phone + website,
    name-verified) → Apollo (decision-maker + LinkedIn + email) → free site-LLM
    fallback for the founder name. Background; poll /startups/enrich/status. Skips
    already-enriched rows. Needs apify_api_token."""
    _require_admin(req)
    from core import startup_enrich as se

    def _do():
        try:
            res = se.enrich(ncr=ncr, dpiit=dpiit, stage=stage, limit=limit)
            logger.info(f"[startup_enrich] done: {res}")
        except Exception as e:
            logger.warning(f"[startup_enrich] failed: {e}")

    background.add_task(_do)
    return {"status": "started", "message": f"Enriching up to {limit} startups. Poll /startups/enrich/status."}


@app.get("/startups/enrich/status")
def startups_enrich_status(req: Request):
    """Progress + running cost of the Apify enrichment."""
    _require_admin(req)
    from core import startup_enrich as se
    return se.enrich_status()


@app.post("/startups/enrich/registry")
def startups_enrich_registry(req: Request, background: BackgroundTasks, ncr: bool = True,
                             dpiit: bool = True, stage: str = "Scaling", limit: int = 2000):
    """Fill DIRECTORS (relevant person) + registered email + CIN + address from the
    MCA/Tofler registry for the filtered slice — ~100% coverage since all are
    registered companies. Background; poll /startups/enrich/registry/status."""
    _require_admin(req)
    from core import startup_enrich as se

    def _do():
        try:
            res = se.enrich_registry(ncr=ncr, dpiit=dpiit, stage=stage, limit=limit)
            logger.info(f"[reg_enrich] done: {res}")
        except Exception as e:
            logger.warning(f"[reg_enrich] failed: {e}")

    background.add_task(_do)
    return {"status": "started", "message": "Registry enrichment started. Poll /startups/enrich/registry/status."}


@app.get("/startups/enrich/registry/status")
def startups_enrich_registry_status(req: Request):
    """Progress + cost of the MCA/Tofler registry enrichment."""
    _require_admin(req)
    from core import startup_enrich as se
    return se.reg_enrich_status()


@app.post("/startups/enrich/deep")
def startups_enrich_deep(req: Request, background: BackgroundTasks, ncr: bool = True,
                         dpiit: bool = True, stage: str = "Scaling", limit: int = 2000):
    """Deep contact discovery: Google-search each company → official website +
    LinkedIn, then scrape the site's PUBLISHED phone. Fills empty fields only.
    Background; poll /startups/enrich/deep/status."""
    _require_admin(req)
    from core import startup_enrich as se

    def _do():
        try:
            res = se.enrich_deep(ncr=ncr, dpiit=dpiit, stage=stage, limit=limit)
            logger.info(f"[deep_enrich] done: {res}")
        except Exception as e:
            logger.warning(f"[deep_enrich] failed: {e}")

    background.add_task(_do)
    return {"status": "started", "message": "Deep contact discovery started. Poll /startups/enrich/deep/status."}


@app.get("/startups/enrich/deep/status")
def startups_enrich_deep_status(req: Request):
    """Progress + cost of the deep contact discovery (website/phone/LinkedIn)."""
    _require_admin(req)
    from core import startup_enrich as se
    return se.deep_enrich_status()


@app.get("/startups/export")
def startups_export(req: Request, state: str = "", industry: str = "", q: str = "",
                    ncr: bool = False, dpiit: bool = False, stage: str = ""):
    """CSV of the current filtered startup view (honors ncr/dpiit/stage filters)."""
    _require_admin(req)
    from core import startup_india as si
    rows = si.export_rows(state=state, industry=industry, q=q, ncr=ncr, dpiit=dpiit, stage=stage)
    buf = io.StringIO()
    cols = ["name", "state", "city", "industry", "sector", "stage", "dpiit_certified",
            "dipp_number", "registered_on", "website", "phone", "dm_name", "dm_role",
            "linkedin", "email", "company_linkedin", "contact_status"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=startup_india.csv"})


@app.post("/signals/scan")
def signals_scan(req: Request, background: BackgroundTasks, state: str = "", industry: str = "",
                 limit: int = 50000, live: bool = False, min_signal: float = 0.0):
    """Score buy-likelihood (signal_score 0–100) across CRM-eligible leads → ranks the
    Hot List. OFFLINE by default (HR-intensity + reachability + no-HRMS + entity, no
    network); live=true adds Serper/Crustdata intent boosts (hiring/funding, concurrent,
    needs keys). `min_signal` restricts a live scan to already-PRIME leads so API budget
    hits the best prospects. Background; poll /signals/status."""
    _require_admin(req)
    from core import warehouse

    def _do(st, ind, lim, lv, ms):
        try:
            res = warehouse.scan_signals(state=st or None, industry=ind or None, limit=lim,
                                         live=lv, min_signal=ms)
            logger.info(f"[signals] scan done: {res}")
        except Exception as e:
            logger.warning(f"[signals] scan failed: {e}")

    background.add_task(_do, state, industry, limit, live, min_signal)
    return {"status": "started", "state": state or "all", "live": live,
            "message": "Signal scan started. Poll /signals/status, then sort CRM by signal_score."}


@app.get("/signals/status")
def signals_status(req: Request):
    """Progress of the signal scan."""
    _require_admin(req)
    from core import warehouse
    return warehouse.signal_scan_status()


@app.get("/crm/counts")
def crm_counts(req: Request, tier: str = "", state: str = "", industry: str = "",
               industries: str = "", has_phone: bool = False):
    """Per-stage counts for the CRM panel badges (honors active filters)."""
    _require_admin(req)
    from core import warehouse
    return warehouse.crm_counts(tier=tier or None, state=state or None, industry=industry or None,
                                industries=industries or None, has_phone=has_phone)


@app.get("/crm/dashboard")
def crm_dashboard(req: Request):
    """KPIs + distributions for the CRM overview."""
    _require_admin(req)
    from core import warehouse
    return warehouse.crm_dashboard()


@app.get("/crm/export")
def crm_export(req: Request, stage: str = "all", tier: str = "", state: str = "",
               industry: str = "", q: str = "", sort: str = "score", min_signal: float = 0.0):
    """CSV of the current filtered CRM view (capped at 50k rows). With sort=signal_score
    + min_signal it exports the ranked Hot List (signal score + 'why now' included)."""
    _require_admin(req)
    from core import warehouse
    rows = list(warehouse.crm_export_rows(stage=stage or None, tier=tier or None,
                                          state=state or None, industry=industry or None, q=q or None,
                                          sort=sort, min_signal=min_signal))
    buf = io.StringIO()
    cols = ["signal_score", "why_now", "company_name", "contact_person", "role", "phone", "phone_source",
            "email", "industry", "state", "tier", "hrms_fit_score", "crm_stage", "website", "cin", "company_status"]
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=crm_leads.csv"})


@app.get("/crm/options")
def crm_options(req: Request):
    """Distinct states + industries for the filter dropdowns."""
    _require_admin(req)
    from core import warehouse
    return warehouse.crm_filter_options()


@app.post("/crm/leads/{lead_id}/stage")
async def crm_update_stage(lead_id: str, req: Request):
    """Move a lead to a CRM stage; body: {stage, method?, note?}."""
    _require_admin(req)
    from core import warehouse
    try:
        body = await req.json()
    except Exception:
        body = {}
    return warehouse.crm_update_stage(lead_id, body.get("stage", ""),
                                      method=body.get("method"), note=body.get("note"))


@app.post("/crm/backfill")
def crm_backfill(req: Request, background: BackgroundTasks):
    """One-time: populate icp_tier/state columns + default crm_stage from payloads."""
    _require_admin(req)
    from core import warehouse
    background.add_task(warehouse.backfill_crm_columns)
    return {"status": "started", "message": "Backfilling CRM columns in background."}


@app.post("/crm/tag-ncr")
def crm_tag_ncr(req: Request):
    """Group the Delhi MARKET (Delhi + Gurgaon/Noida/Faridabad/Ghaziabad, already in
    the pool but tagged by registered state) into one 'Delhi NCR' segment so the CRM
    surfaces the real ~30k Delhi pipeline instead of just NCT-Delhi-proper."""
    _require_admin(req)
    from core import warehouse
    return warehouse.tag_delhi_ncr()


@app.post("/warehouse/deep-verify")
def warehouse_deep_verify(req: Request, background: BackgroundTasks,
                          batch: int = 50, workers: int = 20, state: str = "", industry: str = ""):
    """
    Step 2+3 on PRIME leads: gather the best contact (own-site scrape for named
    people/role-emails/mobiles + registry email + best-effort directories), then an
    LLM reasons over it all to pick the right person, score confidence, and write a
    pitch angle. Background; poll /warehouse/deep-verify/status.
    """
    _require_admin(req)
    from core import deep_verify as dv
    if dv.is_running():
        return {"status": "busy", **dv.status()}

    def _do(b, w, s, i):
        try:
            res = dv.deep_verify(batch=b, workers=w, state=s or None, industry=i or None)
            from core import warehouse
            pooled = warehouse.query(statuses=("outreach_ready",), limit=8000)
            _save_leads(pooled)
            logger.info(f"[deep_verify] done: {res}")
        except Exception as e:
            logger.warning(f"[deep_verify] bg failed: {e}")

    background.add_task(_do, batch, workers, state, industry)
    return {"status": "verifying", "message": f"Deep-verifying {batch} prime leads. Poll /warehouse/deep-verify/status."}


@app.get("/warehouse/deep-verify/status")
def warehouse_deep_verify_status(req: Request):
    _require_admin(req)
    from core import deep_verify as dv
    return dv.status()


@app.post("/warehouse/refine")
def warehouse_refine(req: Request, background: BackgroundTasks):
    """
    Sharpen the pool for HRMS buy-likelihood: disqualify dead companies (struck-off/
    dormant), score by industry HR-intensity + reachability + company age/type, and
    re-tier Hot/Warm/Cold. Runs in background, then refreshes the leads list.
    """
    _require_admin(req)
    from core import warehouse

    def _do():
        try:
            res = warehouse.refine_icp()
            pooled = warehouse.query(statuses=("outreach_ready", "qualified"), min_score=0.0, limit=5000)
            _save_leads(pooled)
            logger.info(f"[refine] done: {res} | reloaded {len(pooled)} prospects")
        except Exception as e:
            logger.warning(f"[refine] failed: {e}")

    background.add_task(_do)
    return {"status": "refining", "message": "Refining the pool to prime HRMS prospects. Poll /warehouse/stats."}


@app.post("/warehouse/revalidate")
def warehouse_revalidate(req: Request):
    """Scrub invalid phones from stored leads (run after tightening phone rules)."""
    _require_admin(req)
    from core import warehouse
    return warehouse.revalidate_phones()


@app.post("/leads/process")
def process_leads(req: Request, background: BackgroundTasks, scrape_fallback: bool = True):
    """
    Turn pooled business data into pitch-ready leads: mobile-first contact (landlines
    demoted to office line; website-scrape fallback finds mobiles), state, A/B/C
    grade + pain points. Runs in background, then refreshes the leads list.
    """
    _require_admin(req)
    from core import lead_processor
    if lead_processor.status().get("running"):
        return {"status": "busy", **lead_processor.status()}

    def _do(scrape):
        try:
            res = lead_processor.reprocess_all(scrape_fallback=scrape, max_scrape=500)
            # Refresh the active leads list from the reprocessed pool.
            from core import warehouse
            pooled = warehouse.query(min_score=0.0, limit=10000)
            _save_leads(pooled)
            logger.info(f"[leadproc] done: {res} | leads reloaded: {len(pooled)}")
        except Exception as e:
            logger.warning(f"[leadproc] background failed: {e}")

    background.add_task(_do, scrape_fallback)
    return {"status": "processing",
            "message": "Processing leads (mobile-first + grade + state). Poll /leads/process/status."}


@app.get("/leads/process/status")
def process_leads_status(req: Request):
    _require_admin(req)
    from core import lead_processor
    return lead_processor.status()


@app.get("/warehouse/export/csv")
def warehouse_export_csv(req: Request, industry: str = "", region: str = "", min_score: float = 0.0, limit: int = 1000000):
    """Stream the WHOLE pool (or a filtered slice) as CSV — for exporting lakhs of
    leads without loading them into the browser. Reads straight from SQLite."""
    _require_admin(req)
    from core import warehouse
    import csv as _csv

    def _gen():
        buf = io.StringIO()
        w = _csv.writer(buf)
        cols = ["company_name", "industry", "state", "location", "email", "phone",
                "icp_tier", "score", "status", "website", "address", "source"]
        w.writerow(cols)
        yield buf.getvalue(); buf.seek(0); buf.truncate(0)
        db = warehouse._db()
        if not db:
            return
        where, params = ["payload IS NOT NULL"], []
        if min_score:
            where.append("score >= ?"); params.append(min_score)
        if industry:
            where.append("LOWER(industry) LIKE ?"); params.append(f"%{industry.lower()}%")
        if region:
            where.append("(LOWER(region) LIKE ? OR LOWER(location) LIKE ?)"); params += [f"%{region.lower()}%", f"%{region.lower()}%"]
        sql = f"SELECT payload FROM leads WHERE {' AND '.join(where)} ORDER BY score DESC LIMIT ?"
        params.append(limit)
        cur = db.execute(sql, params)
        n = 0
        for (payload,) in cur:
            try:
                l = json.loads(payload)
            except Exception:
                continue
            w.writerow([
                l.get("company_name", ""), l.get("industry", ""), l.get("state", ""),
                l.get("location", ""), (l.get("contact_emails") or [l.get("dm_email", "")])[0] or "",
                l.get("mobile") or l.get("phone", ""), l.get("icp_tier", ""),
                (l.get("lead_score") or {}).get("predicted_score", ""), l.get("status", ""),
                l.get("website", ""), l.get("address", ""), l.get("source", ""),
            ])
            n += 1
            if n % 500 == 0:
                yield buf.getvalue(); buf.seek(0); buf.truncate(0)
        yield buf.getvalue()

    headers = {"Content-Disposition": "attachment; filename=razorinfotech_leads.csv"}
    return StreamingResponse(_gen(), media_type="text/csv", headers=headers)


@app.post("/leads/load-pool")
def load_pool(req: Request, limit: int = 5000, min_score: float = 0.0):
    """Load the warehouse pool into the active leads list so the dashboard + CSV
    export show every harvested lead. For demos / bulk export."""
    _require_admin(req)
    from core import warehouse
    pooled = warehouse.query(min_score=min_score, limit=min(limit, 10000))
    existing = _load_leads()
    ex_keys = {l.get("id") or l.get("company_name") for l in existing}
    merged = existing + [l for l in pooled if (l.get("id") or l.get("company_name")) not in ex_keys]
    _save_leads(merged)
    return {"status": "ok", "loaded": len(pooled), "total_leads": len(merged)}


@app.post("/harvest/matrix")
def harvest_matrix(req: Request, background: BackgroundTasks,
                   max_queries: int = 200, per_query: int = 60):
    """
    Volume engine: sweep (industry x city) across the India SME belt, harvesting
    raw candidates into the pool. Cheap (no AI) — fills the warehouse toward
    hundreds of thousands of leads. Runs in background; poll /harvest/matrix/status.
    """
    _require_admin(req)
    from core import harvest_matrix as hm
    if hm.is_running():
        return {"status": "busy", **hm.status()}

    def _do(mq, pq):
        try:
            res = hm.run_matrix(max_queries=mq, per_query=pq)
            logger.info(f"[matrix] background sweep done: {res.get('status')} (+{res.get('added', 0)})")
        except Exception as e:
            logger.warning(f"[matrix] background sweep failed: {e}")

    background.add_task(_do, max_queries, per_query)
    return {"status": "started", "max_queries": max_queries,
            "message": f"Matrix harvest started ({max_queries} queries). Poll /harvest/matrix/status."}


@app.post("/harvest/osm")
def harvest_osm(req: Request, background: BackgroundTasks, per_city: int = 300, cities: str = ""):
    """
    FREE high-volume harvest from OpenStreetMap (Overpass) — real businesses with
    name + website + phone + city, banked DIRECTLY as enriched leads (no scraping,
    no LLM, no API key). Optional `cities` = comma-separated subset (e.g. one metro).
    Runs in background; poll /harvest/osm/status.
    """
    _require_admin(req)
    from tools.sources import overpass
    if overpass.osm_running():
        return {"status": "busy", **overpass.osm_status()}
    city_list = [c.strip() for c in cities.split(",") if c.strip()] or None

    def _do(pc, cl):
        try:
            res = overpass.harvest_all_to_warehouse(per_city=pc, cities=cl)
            logger.info(f"[osm] background harvest done: +{res.get('added', 0)} leads")
        except Exception as e:
            logger.warning(f"[osm] background harvest failed: {e}")

    background.add_task(_do, per_city, city_list)
    return {"status": "started", "per_city": per_city, "cities": city_list or "all",
            "message": "OSM harvest started. Poll /harvest/osm/status."}


@app.post("/harvest/mca")
def harvest_mca(req: Request, background: BackgroundTasks, max_states: int = 40, max_rows_per_state: int = 100000):
    """
    LAKHS-scale, FREE, ACCURATE: ingest MCA company master data (state-wise XLSX —
    name, registered state/address, EMAIL, NIC industry, status) directly. Filters
    to ACTIVE companies, ICP-scores, banks as quality leads. No fetching, no dead
    domains. Runs in background; poll /harvest/mca/status.
    """
    _require_admin(req)
    from tools.sources import mca
    if mca.is_running():
        return {"status": "busy", **mca.status()}

    def _do(ms, mr):
        try:
            res = mca.ingest_all(max_states=ms, max_rows_per_state=mr)
            logger.info(f"[mca] background ingest done: +{res.get('added', 0)} company leads")
        except Exception as e:
            logger.warning(f"[mca] background ingest failed: {e}")

    background.add_task(_do, max_states, max_rows_per_state)
    return {"status": "started", "message": "MCA registry ingest started. Poll /harvest/mca/status."}


@app.post("/harvest/pdl")
def harvest_pdl(req: Request, background: BackgroundTasks, region: str = "", industry: str = "", limit: int = 100, min_size: int = 11):
    """
    Bulk-discover companies via People Data Labs (name, website, size, industry,
    LinkedIn) — great for Delhi/Maharashtra. Banks as enriched leads. Needs
    `pdl_api_key` in Settings. Background; poll /harvest/pdl/status.
    """
    _require_admin(req)
    from tools.sources import pdl
    if not pdl.configured():
        return {"status": "error", "message": "No PDL API key. Add pdl_api_key in Settings."}

    def _do(region, industry, limit, min_size):
        try:
            from tools.sources import _directory_common as dc
            cands = pdl.company_search(region=region, industry=industry, min_size=min_size, limit=limit)
            n = dc.bank(cands, region=region or "India", source_label="PDL", tag_source="pdl")
            from core import warehouse
            warehouse.warm_crm_cache()
            logger.info(f"[pdl] harvest done: +{n} leads")
        except Exception as e:
            logger.warning(f"[pdl] harvest failed: {e}")

    background.add_task(_do, region, industry, limit, min_size)
    return {"status": "started", "region": region or "India", "message": "PDL discovery started."}


@app.post("/enrich/people")
def enrich_people(req: Request, background: BackgroundTasks, state: str = "", limit: int = 200):
    """
    Attach the decision-maker (HR head/founder + email) to pooled leads via Crustdata
    (preferred) or PDL. Fixes leads with no person to contact. Needs a crustdata_api_key
    or pdl_api_key in Settings. Background; poll /enrich/people/status.
    """
    _require_admin(req)
    from tools.sources import contact_enrich
    if not contact_enrich._provider()[1]:
        return {"status": "error", "message": "No Apollo / Crustdata / PDL key. Add one in Settings (Apollo gives decision-maker direct dials)."}
    if contact_enrich.is_running():
        return {"status": "busy", **contact_enrich.status()}

    def _do(state, limit):
        try:
            res = contact_enrich.enrich(state=state, limit=limit)
            logger.info(f"[contact_enrich] done: {res}")
        except Exception as e:
            logger.warning(f"[contact_enrich] failed: {e}")

    background.add_task(_do, state, limit)
    return {"status": "started", "state": state or "all", "message": "Decision-maker enrichment started. Poll /enrich/people/status."}


@app.get("/enrich/people/status")
def enrich_people_status(req: Request):
    """Progress of decision-maker enrichment."""
    _require_admin(req)
    from tools.sources import contact_enrich
    return contact_enrich.status()


@app.get("/harvest/pdl/status")
def harvest_pdl_status(req: Request):
    """Whether PDL/Crustdata data keys are configured (for the UI)."""
    _require_admin(req)
    from tools.sources import pdl, crustdata
    return {"pdl": pdl.configured(), "crustdata": crustdata.configured()}


@app.post("/harvest/mca-live")
def harvest_mca_live(req: Request, background: BackgroundTasks, states: str = "Delhi,Maharashtra", max_rows: int = 80000):
    """
    Ingest MCA Company Master Data from data.gov.in for states the free GitHub mirror
    LACKS (Delhi, Maharashtra) — same email+name+industry quality as the rest of the
    pool, tens of thousands per state. Needs a FREE `datagovin_api_key` in Settings.
    Background; poll /harvest/mca-live/status. (Runs on your machine — api.data.gov.in
    is blocked from the dev sandbox.)
    """
    _require_admin(req)
    from tools.sources import mca_live
    if not mca_live._key():
        return {"status": "error", "message": "No data.gov.in API key. Add datagovin_api_key in Settings (free at data.gov.in)."}
    if mca_live.is_running():
        return {"status": "busy", **mca_live.status()}
    st = [s.strip() for s in states.split(",") if s.strip()] or None

    def _do(st, mr):
        try:
            res = mca_live.ingest(states=st, max_rows_per_state=mr)
            from core import warehouse
            warehouse.warm_crm_cache()  # refresh aggregates so new leads show immediately
            logger.info(f"[mca_live] background ingest done: +{res.get('added', 0)} leads")
        except Exception as e:
            logger.warning(f"[mca_live] background ingest failed: {e}")

    background.add_task(_do, st, max_rows)
    return {"status": "started", "states": st or ["Delhi", "Maharashtra"],
            "message": "MCA (data.gov.in) ingest started. Poll /harvest/mca-live/status."}


@app.get("/harvest/mca-live/status")
def harvest_mca_live_status(req: Request):
    """Progress of the data.gov.in MCA ingest."""
    _require_admin(req)
    from tools.sources import mca_live
    return mca_live.status()


@app.get("/harvest/mca/status")
def harvest_mca_status(req: Request):
    _require_admin(req)
    from tools.sources import mca
    return mca.status()


@app.post("/harvest/commoncrawl")
def harvest_commoncrawl(req: Request, background: BackgroundTasks, pages: int = 8, page_size: int = 5000):
    """
    FREE lakhs-scale firehose: pull Indian business domains (*.co.in etc) from
    Common Crawl into the RAW tier (business-filtered). The enrichment funnel +
    ICP scorer then promote the genuine HR-relevant ones. Poll /harvest/commoncrawl/status.
    """
    _require_admin(req)
    from tools.sources import commoncrawl
    if commoncrawl.is_running():
        return {"status": "busy", **commoncrawl.status()}

    def _do(p, ps):
        try:
            res = commoncrawl.harvest(max_pages_per_pattern=p, page_size=ps)
            logger.info(f"[cc] background harvest done: +{res.get('added', 0)} raw domains")
        except Exception as e:
            logger.warning(f"[cc] background harvest failed: {e}")

    background.add_task(_do, pages, page_size)
    return {"status": "started", "message": "Common Crawl harvest started. Poll /harvest/commoncrawl/status."}


@app.get("/harvest/commoncrawl/status")
def harvest_commoncrawl_status(req: Request):
    _require_admin(req)
    from tools.sources import commoncrawl
    return commoncrawl.status()


@app.post("/harvest/grid")
def harvest_grid(req: Request, background: BackgroundTasks, max_tiles: int = 120, per_tile: int = 800):
    """
    FREE volume engine at scale: tile all of India and sweep every cell for
    HR-relevant businesses (offices/factories/hospitals/hotels/colleges) straight
    into the pool. Cursor-persisted — call repeatedly to cover the whole country
    (the path to lakhs of leads). Runs in background; poll /harvest/grid/status.
    """
    _require_admin(req)
    from tools.sources import overpass
    if overpass.grid_running():
        return {"status": "busy", **overpass.grid_status()}

    def _do(mt, pt):
        try:
            res = overpass.harvest_grid(max_tiles=mt, per_tile=pt)
            logger.info(f"[grid] background sweep done: +{res.get('added', 0)} ({res.get('cursor')})")
        except Exception as e:
            logger.warning(f"[grid] background sweep failed: {e}")

    background.add_task(_do, max_tiles, per_tile)
    return {"status": "started", "max_tiles": max_tiles,
            "message": f"Grid sweep started ({max_tiles} tiles). Poll /harvest/grid/status."}


@app.get("/harvest/grid/status")
def harvest_grid_status(req: Request):
    """Progress of the India grid sweep."""
    _require_admin(req)
    from tools.sources import overpass
    return overpass.grid_status()


@app.get("/harvest/osm/status")
def harvest_osm_status(req: Request):
    """Progress of the OpenStreetMap bulk harvest."""
    _require_admin(req)
    from tools.sources import overpass
    return overpass.osm_status()


@app.post("/harvest/indiamart")
def harvest_indiamart(req: Request, background: BackgroundTasks, cities: str = "", categories: str = "", delay: float = 1.0):
    """
    FREE harvest from IndiaMART (B2B supplier directory) — manufacturers, exporters,
    wholesalers etc., banked as enriched leads (name + city + category, + phone when
    present). `cities`/`categories` = optional comma-separated subsets. Geo-targets
    Delhi/Maharashtra that the MCA mirror lacks. Runs in background; poll
    /harvest/indiamart/status. NOTE: run on your own machine (sandbox is network-blocked).
    """
    _require_admin(req)
    from tools.sources import indiamart
    if indiamart.running():
        return {"status": "busy", **indiamart.status()}
    cl = [c.strip() for c in cities.split(",") if c.strip()] or None
    cats = [c.strip() for c in categories.split(",") if c.strip()] or None

    def _do(cl, cats, delay):
        try:
            res = indiamart.harvest_to_warehouse(cities=cl, categories=cats, delay=delay)
            logger.info(f"[indiamart] background harvest done: +{res.get('added', 0)} leads")
        except Exception as e:
            logger.warning(f"[indiamart] background harvest failed: {e}")

    background.add_task(_do, cl, cats, delay)
    return {"status": "started", "cities": cl or "default", "categories": cats or "all",
            "message": "IndiaMART harvest started. Poll /harvest/indiamart/status."}


@app.get("/harvest/indiamart/status")
def harvest_indiamart_status(req: Request):
    """Progress of the IndiaMART harvest."""
    _require_admin(req)
    from tools.sources import indiamart
    return indiamart.status()


@app.post("/harvest/justdial")
def harvest_justdial(req: Request, background: BackgroundTasks, cities: str = "", categories: str = "", delay: float = 1.5):
    """
    FREE harvest from JustDial (local business directory) — clinics, hotels, factories,
    BPOs, schools, logistics etc., banked as enriched leads (name + locality + category;
    phone when exposed). `cities`/`categories` = optional comma-separated subsets.
    Runs in background; poll /harvest/justdial/status. NOTE: run on your own machine.
    """
    _require_admin(req)
    from tools.sources import justdial
    if justdial.running():
        return {"status": "busy", **justdial.status()}
    cl = [c.strip() for c in cities.split(",") if c.strip()] or None
    cats = [c.strip() for c in categories.split(",") if c.strip()] or None

    def _do(cl, cats, delay):
        try:
            res = justdial.harvest_to_warehouse(cities=cl, categories=cats, delay=delay)
            logger.info(f"[justdial] background harvest done: +{res.get('added', 0)} leads")
        except Exception as e:
            logger.warning(f"[justdial] background harvest failed: {e}")

    background.add_task(_do, cl, cats, delay)
    return {"status": "started", "cities": cl or "default", "categories": cats or "all",
            "message": "JustDial harvest started. Poll /harvest/justdial/status."}


@app.get("/harvest/justdial/status")
def harvest_justdial_status(req: Request):
    """Progress of the JustDial harvest."""
    _require_admin(req)
    from tools.sources import justdial
    return justdial.status()


@app.post("/harvest/places")
def harvest_places(req: Request, background: BackgroundTasks, cities: str = "", categories: str = "", delay: float = 0.3):
    """
    Harvest from Google Places (city × HR-relevant category) — the most RELIABLE
    contact-bearing source: real businesses with Google-verified name + address +
    phone + website, banked as enriched leads. Needs `google_places_api_key` in
    Settings ($200/mo free credit). Runs in background; poll /harvest/places/status.
    """
    _require_admin(req)
    from tools.sources import places
    if not places._key():
        return {"status": "error", "message": "No Google Places API key. Add google_places_api_key in Settings."}
    if places.running():
        return {"status": "busy", **places.status()}
    cl = [c.strip() for c in cities.split(",") if c.strip()] or None
    cats = [c.strip() for c in categories.split(",") if c.strip()] or None

    def _do(cl, cats, delay):
        try:
            res = places.harvest_to_warehouse(cities=cl, categories=cats, delay=delay)
            logger.info(f"[places] background harvest done: +{res.get('added', 0)} leads")
        except Exception as e:
            logger.warning(f"[places] background harvest failed: {e}")

    background.add_task(_do, cl, cats, delay)
    return {"status": "started", "cities": cl or "default", "categories": cats or "all",
            "message": "Google Places harvest started. Poll /harvest/places/status."}


@app.get("/harvest/places/status")
def harvest_places_status(req: Request):
    """Progress of the Google Places harvest."""
    _require_admin(req)
    from tools.sources import places
    return places.status()


@app.post("/harvest/directories")
def harvest_directories(req: Request, background: BackgroundTasks, cities: str = "", categories: str = "", sites: str = "", delay: float = 0.5):
    """
    Sweep EVERY JS directory (IndiaMART, JustDial, TradeIndia, Sulekha, ExportersIndia)
    for the given cities via the headless browser, banking businesses as enriched
    leads. `sites`/`cities`/`categories` = optional comma-separated subsets. Needs the
    headless engine. Background; poll /harvest/directories/status.
    """
    _require_admin(req)
    from tools.sources import directories, headless
    if not headless.available():
        return {"status": "error", "message": headless.INSTALL_HINT}
    if directories.running():
        return {"status": "busy", **directories.status()}
    cl = [c.strip() for c in cities.split(",") if c.strip()] or None
    cats = [c.strip() for c in categories.split(",") if c.strip()] or None
    sl = [s.strip() for s in sites.split(",") if s.strip()] or None

    def _do(cl, cats, sl, delay):
        try:
            res = directories.harvest_to_warehouse(cities=cl, categories=cats, sites=sl, delay=delay)
            logger.info(f"[directories] background harvest done: +{res.get('added', 0)} leads")
        except Exception as e:
            logger.warning(f"[directories] background harvest failed: {e}")

    background.add_task(_do, cl, cats, sl, delay)
    return {"status": "started", "sites": sl or list(headless.SITES.keys()),
            "cities": cl or "default", "message": "Directory sweep started. Poll /harvest/directories/status."}


@app.get("/harvest/directories/status")
def harvest_directories_status(req: Request):
    """Progress of the unified directory sweep."""
    _require_admin(req)
    from tools.sources import directories
    return directories.status()


@app.get("/harvest/directories/probe")
def harvest_directories_probe(req: Request, site: str = "indiamart", city: str = "Delhi", category: str = "manufacturers"):
    """DIAGNOSTIC: render ONE directory site for a city/category and report yield +
    a sample (no banking). site = indiamart|justdial|tradeindia|sulekha|exportersindia."""
    _require_admin(req)
    from tools.sources import headless
    return headless.probe_site(site, category, city)


@app.get("/harvest/directory/engine")
def harvest_directory_engine(req: Request):
    """Report whether the headless-browser engine (needed to render JustDial/IndiaMART
    JS pages) is installed, with a one-line setup hint if not."""
    _require_admin(req)
    from tools.sources import headless
    ok = headless.available()
    return {"headless_available": ok,
            "engine": "playwright-chromium" if ok else None,
            "hint": None if ok else headless.INSTALL_HINT}


@app.get("/harvest/directory/debug")
def harvest_directory_debug(req: Request, source: str = "indiamart", city: str = "Delhi", category: str = ""):
    """
    DIAGNOSTIC: fetch ONE directory query and report exactly what the site returned
    (HTTP status, size, whether it looks blocked/captcha'd, whether expected markup
    is present, parsed count, + a snippet). Use this to tell a block from a markup
    change so the parser can be tuned. source = indiamart | justdial.
    """
    _require_admin(req)
    if source == "justdial":
        from tools.sources import justdial
        return justdial.probe(category or "Manufacturers", city)
    from tools.sources import indiamart
    return indiamart.probe(category or "manufacturers", city)


@app.get("/harvest/matrix/status")
def harvest_matrix_status(req: Request):
    """Progress of the running (industry x city) sweep."""
    _require_admin(req)
    from core import harvest_matrix as hm
    return hm.status()


@app.post("/warehouse/fast-enrich")
def warehouse_fast_enrich(req: Request, background: BackgroundTasks, batch: int = 1500, workers: int = 80):
    """
    HIGH-THROUGHPUT raw → quality conversion: one fetch per domain (name, mobile,
    industry, HRMS-absence), ICP-scored, ~80 in parallel. Built for lakhs-scale.
    Runs in background; poll /warehouse/fast-enrich/status.
    """
    _require_admin(req)
    from core import fast_enrich
    if fast_enrich.is_running():
        return {"status": "busy", **fast_enrich.status()}

    def _do(b, w):
        try:
            res = fast_enrich.fast_enrich(batch=b, workers=w)
            logger.info(f"[fast_enrich] background done: {res.get('converted', 0)} converted")
        except Exception as e:
            logger.warning(f"[fast_enrich] background failed: {e}")

    background.add_task(_do, batch, workers)
    return {"status": "started", "batch": batch, "workers": workers,
            "message": "Fast-enrich started. Poll /warehouse/fast-enrich/status."}


@app.get("/warehouse/fast-enrich/status")
def warehouse_fast_enrich_status(req: Request):
    _require_admin(req)
    from core import fast_enrich
    return fast_enrich.status()


@app.get("/llm/pool")
def llm_pool_stats(req: Request):
    """Live view of the LLM endpoint pool — configured endpoints, tiers, cooldowns."""
    _require_admin(req)
    from agents import llm_pool
    return llm_pool.stats()


@app.get("/flywheel/stats")
def flywheel_stats(req: Request):
    """Self-Learning ICP Flywheel: approval-derived precision + learned signals."""
    _require_admin(req)
    try:
        from rag.icp_flywheel import stats
        return stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/leads/{lead_id}/simulate")
def simulate_lead(lead_id: str, req: Request):
    """
    Run the Buyer Simulation & Email Arena for a stored lead on demand.
    Returns (and caches) the BuyerSimulation payload.
    """
    _require_admin(req)
    leads = _load_leads()
    lead = next((l for l in leads if l.get("id") == lead_id), None)
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead {lead_id} not found")
    if lead.get("simulation"):
        return lead["simulation"]
    try:
        from agents.sales_agent import SalesAgent
        from agents.buyer_simulator import simulate_arena
        agent = SalesAgent()
        draft = lead.get("outreach_draft") or {}
        sim = simulate_arena(agent, lead, draft.get("subject", ""), draft.get("email_body", ""))
        if not sim:
            raise HTTPException(status_code=502, detail="Simulation unavailable (LLM not configured)")
        lead["simulation"] = sim
        _save_leads(leads)
        return sim
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/flush-cache")
def flush_cache(req: Request):
    """
    Flush the Redis deduplication cache so the next pipeline run can
    re-process companies that were previously seen.  Also clears the
    Celery result backend (DB 1) so stale job states are removed.
    """
    _require_admin(req)

    try:
        r = get_redis()
        if r:
            r.flushall()   # clears all Redis DBs (dedup + Celery results)
            return {"status": "ok", "message": "Redis flushed — next run starts fresh"}
        return {"status": "degraded", "message": "Redis not available"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/leads")
def get_leads(req: Request, status: Optional[str] = None):
    """
    Retrieve stored leads filtered by status.
    Status options: outreach_ready | qualified | disqualified | researched
    """
    _require_admin(req)

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
def get_pending_review_leads(req: Request):
    """
    Return all leads currently awaiting human review.
    These are leads where the Sales Agent generated an outreach email
    but SLACK_WEBHOOK_URL is configured, so they are held for approval
    before being marked outreach_ready.
    """
    _require_admin(req)

    leads = _load_leads()
    pending = [l for l in leads if l.get("status") == "pending_review"]
    return {"total": len(pending), "leads": pending}


@app.post("/leads/{lead_id}/generate-email")
def generate_email(lead_id: str, req: Request):
    """
    Generate the 4-touch outreach sequence for ONE lead, ON DEMAND.
    Outreach is no longer drafted during the pipeline (that wasted time on every
    lead) — the operator generates it only for the leads they choose to pursue.
    Saves the draft to the lead and returns it.
    """
    _require_admin(req)
    leads = _load_leads()
    lead = next((l for l in leads if l.get("id") == lead_id), None)
    if lead is None:
        return {"error": "Lead not found", "id": lead_id}
    try:
        from agents.sales_agent import SalesAgent
        from rag.retriever import retrieve_hrms_context
        agent = SalesAgent()
        # MX-verify contact emails first (same as the old pipeline did) — fail-safe.
        try:
            from tools.email_verifier import verify_emails
            all_emails = list(dict.fromkeys((lead.get("contact_emails") or []) + (lead.get("email_guesses") or [])))
            if all_emails:
                verified = verify_emails(all_emails)
                lead["verified_emails"] = verified
                good = [r["email"] for r in verified if r.get("valid") and r.get("quality") in ("high", "medium")]
                if good:
                    lead["contact_emails"] = good[:5]
        except Exception:
            pass
        desc = (lead.get("description") or "") + " " + " ".join(lead.get("pain_points") or [])
        rag_context = retrieve_hrms_context(desc)
        outreach_draft, follow_up_sequence = agent._generate_sequence(lead, rag_context)
        outreach_draft.setdefault("hallucination_confidence", 0.9)
        lead["outreach_draft"] = outreach_draft
        lead["follow_up_sequence"] = follow_up_sequence
        if lead.get("status") in ("researched", "qualified"):
            lead["status"] = "outreach_ready"
        _save_leads(leads)
        return {
            "id": lead_id,
            "status": lead["status"],
            "outreach_draft": outreach_draft,
            "follow_up_sequence": follow_up_sequence,
        }
    except Exception as e:
        logger.error(f"generate-email failed for {lead_id}: {e}")
        return {"error": f"Generation failed: {e}", "id": lead_id}


@app.get("/leads/{lead_id}/approve")
def approve_lead_get(lead_id: str, req: Request, token: Optional[str] = Query(default=None)):
    """GET version for Slack button links — same logic as POST."""
    _require_review_action(req, token)
    return _approve_lead(lead_id)


@app.post("/leads/{lead_id}/approve")
def approve_lead(lead_id: str, req: Request):
    """
    Approve a pending_review lead, marking it outreach_ready.
    Also triggers CRM push (webhook / Google Sheets) if configured.
    Called by a human reviewer after inspecting the Slack notification.
    The lead will then appear in GET /leads?status=outreach_ready.
    """
    _require_admin(req)
    return _approve_lead(lead_id)


def _approve_lead(lead_id: str):
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

    # Feed the Self-Learning ICP Flywheel (fire-and-forget).
    try:
        from rag.icp_flywheel import record
        record(lead, "approved")
    except Exception:
        pass

    # Push to CRM after approval (fire-and-forget, never blocks the response)
    try:
        from tools.crm_push import push_lead_to_crm
        push_lead_to_crm(lead)
    except Exception:
        pass  # CRM push failure must never break approval flow

    return {"message": f"Lead {lead_id} approved", "lead": lead}


@app.get("/leads/{lead_id}/reject")
def reject_lead_get(lead_id: str, req: Request, token: Optional[str] = Query(default=None)):
    """GET version for Slack button links — same logic as POST."""
    _require_review_action(req, token)
    return _reject_lead(lead_id)


@app.post("/leads/{lead_id}/reject")
def reject_lead(lead_id: str, req: Request):
    """
    Reject a pending_review lead, marking it disqualified.
    Called by a human reviewer who decides the outreach email is not suitable.
    """
    _require_admin(req)
    return _reject_lead(lead_id)


def _reject_lead(lead_id: str):
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

    # Feed the Self-Learning ICP Flywheel (fire-and-forget).
    try:
        from rag.icp_flywheel import record
        record(lead, "rejected")
    except Exception:
        pass

    return {"message": f"Lead {lead_id} rejected", "lead": lead}


@app.get("/leads/export/csv")
def export_leads_csv(req: Request, status: Optional[str] = None):
    """
    Export leads as a CSV file for the sales team.
    Includes all contact fields: company, industry, size, location, address,
    phone, emails, decision makers, pain points, score, and outreach email.

    Optional ?status= filter: outreach_ready | qualified | disqualified | pending_review
    """
    _require_admin(req)

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
def get_lead(lead_id: str, req: Request):
    """Retrieve a single lead by ID."""
    _require_admin(req)

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
