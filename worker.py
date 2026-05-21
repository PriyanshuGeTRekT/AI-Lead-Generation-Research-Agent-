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


@celery_app.task(bind=True, name="tasks.run_pipeline", max_retries=2)
def run_pipeline_task(self, keyword: str, run_id: str) -> dict:
    """
    Execute the full multi-agent lead generation pipeline as a background task.

    Args:
        keyword: Search keyword for lead discovery
        run_id: Correlation ID for this pipeline run (passed through to logs)

    Returns:
        dict with keys: status, run_id, lead_count, leads
    """
    try:
        from graph.supervisor import run_pipeline

        result = run_pipeline(keyword)

        return {
            "status": "completed",
            "run_id": run_id,
            "lead_count": len(result.get("leads", [])),
            "leads": result.get("leads", []),
        }
    except Exception as exc:
        raise self.retry(exc=exc, countdown=10)
