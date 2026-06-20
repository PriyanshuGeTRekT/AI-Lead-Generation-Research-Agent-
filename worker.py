"""
Celery Worker
--------------
Async pipeline execution worker. Decouples the FastAPI request/response cycle
from the blocking LangGraph pipeline run (which takes 15-30s).

Start the worker with:
    celery -A worker worker --loglevel=info --concurrency=2

Architecture:
    FastAPI (/generate-leads) --> Redis queue (DB 1) --> Celery worker --> leads.json
    Client polls /pipeline-status/{run_id} until status == "completed"

Redis DB separation:
    DB 0: LLM response cache and lead deduplication (existing)
    DB 1: Celery broker + result backend (new, isolated)

Without a running worker, /generate-leads falls back to synchronous execution.
This means the default docker compose up (no worker) keeps working exactly as before.
"""
import os
from celery import Celery
from celery.schedules import crontab

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
CELERY_BROKER = os.getenv("CELERY_BROKER_URL", f"{REDIS_URL}/1")
CELERY_BACKEND = os.getenv("CELERY_RESULT_BACKEND", f"{REDIS_URL}/1")

celery_app = Celery(
    "lead_gen",
    broker=CELERY_BROKER,
    backend=CELERY_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    task_track_started=True,
)

# ── Celery Beat: Scheduled Daily Lead Generation ───────────────────────────────
# Reads settings at import time so beat respects SCHEDULE_* env vars.
# To enable: set SCHEDULE_ENABLED=true in .env, then start the beat scheduler:
#   celery -A worker beat --loglevel=info
# Or combined: celery -A worker worker --beat --loglevel=info
def _setup_beat_schedule():
    try:
        from core.config import get_settings
        s = get_settings()
        if not s.schedule_enabled:
            return
        celery_app.conf.beat_schedule = {
            "daily-lead-generation": {
                "task": "tasks.run_pipeline",
                "schedule": crontab(hour=s.schedule_hour, minute=s.schedule_minute),
                "kwargs": {
                    "keyword": s.schedule_keyword,
                    "run_id": "scheduled-daily",
                },
            },
        }
        celery_app.conf.timezone = "Asia/Kolkata"
        import logging
        logging.getLogger("celery").info(
            f"Celery Beat scheduled: daily at {s.schedule_hour:02d}:{s.schedule_minute:02d} IST "
            f"| keyword='{s.schedule_keyword}'"
        )
    except Exception:
        pass  # Beat schedule is optional — don't crash worker startup

_setup_beat_schedule()


@celery_app.task(bind=True, name="tasks.run_pipeline", max_retries=2)
def run_pipeline_task(
    self,
    keyword: str,
    run_id: str,
    max_leads: int = None,
    country: str = None,
    region: str = None,
    exclude_with_hrms: bool = True,
    mode: str = "discover",
    fast: bool = True,
) -> dict:
    """
    Execute the full multi-agent lead generation pipeline as a background task.

    Args:
        keyword: Search keyword for lead discovery
        run_id: Correlation ID for this pipeline run (passed through to logs)

    Returns:
        dict with keys: status, run_id, lead_count, leads

    Bug fix: async path must persist leads to disk the same way the sync path does.
    Without this, GET /leads always returns empty after a Celery run because the
    sync path's os.replace() write in api/main.py never executes in this code path.
    """
    try:
        import json
        import os as _os
        from pathlib import Path
        from graph.supervisor import run_pipeline
        from observability.langsmith_tracer import log_lead_quality

        result = run_pipeline(
            keyword, max_leads=max_leads, run_id=run_id,
            country=country, region=region, exclude_with_hrms=exclude_with_hrms, mode=mode, fast=fast,
        )
        leads = result.get("leads", [])

        log_lead_quality(leads)

        # Merge new leads with all previously saved leads so every run accumulates.
        # Never overwrite with empty — if this run found 0 leads keep existing data.
        data_path = Path(_os.getenv("DATA_PATH", "./data/leads.json"))
        data_path.parent.mkdir(parents=True, exist_ok=True)
        if leads:
            existing = []
            if data_path.exists():
                try:
                    with open(data_path) as f:
                        existing = json.load(f)
                except Exception:
                    existing = []
            existing_keys = {l.get("id") or l.get("company_name") for l in existing}
            truly_new = [l for l in leads if (l.get("id") or l.get("company_name")) not in existing_keys]
            all_leads = existing + truly_new
            tmp_path = data_path.with_suffix(".tmp")
            with open(tmp_path, "w") as f:
                json.dump(all_leads, f, indent=2)
            _os.replace(tmp_path, data_path)
            leads = all_leads  # return full accumulated list in task result

        qualified = [l for l in leads if l.get("status") in ("outreach_ready", "pending_review")]
        disqualified = [l for l in leads if l.get("status") == "disqualified"]
        pending = [l for l in leads if l.get("status") == "pending_review"]

        return {
            "status": "completed",
            "run_id": run_id,
            "lead_count": len(leads),
            "leads": leads,
            "summary": {
                "total": len(leads),
                "qualified": len(qualified),
                "pending_review": len(pending),
                "disqualified": len(disqualified),
            },
            "pipeline_log": result.get("messages", []),
        }
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10)
