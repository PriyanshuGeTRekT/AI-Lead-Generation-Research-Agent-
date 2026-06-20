"""
Background Enrichment Worker
----------------------------
Drains the warehouse's RAW pool (cheaply-harvested candidates) and runs each one
through the full research funnel — fetch site, detect HRMS, resolve contact, score,
verify — then banks the result with warehouse.save_enriched().

This is the half of the "instant search" architecture that does the expensive work
OFF the search path: searches stay an instant SQL filter, while the pool quietly
fills with qualified leads in the background. The candidate funnel is I/O-bound, so
it's fanned out across a thread pool; any LLM work inside it rides the multi-endpoint
LLM pool (agents/llm_pool.py) for parallel throughput + failover.

Fail-safe: any error enriching one candidate is logged and skipped — the worker
never raises. A module-level lock prevents two enrichment passes from overlapping.
"""
import threading

from loguru import logger

_LOCK = threading.Lock()
_running = False


def is_running() -> bool:
    return _running


def enrich_pool(batch: int = 25, fast: bool = True, region: str | None = None,
                industry: str | None = None) -> dict:
    """Enrich up to `batch` raw candidates from the pool. Returns a summary.

    fast=True  → deterministic funnel (Places + LinkedIn, no per-company LLM): best
                 for volume. fast=False → deep LLM extraction via the endpoint pool.
    Skips cleanly (running=True) if a pass is already in progress.
    """
    global _running
    if not _LOCK.acquire(blocking=False):
        return {"status": "busy", "message": "An enrichment pass is already running."}
    _running = True
    try:
        from core import warehouse
        from agents.research_agent import ResearchAgent

        candidates = warehouse.take_raw(limit=batch, industry=industry, region=region)
        if not candidates:
            return {"status": "empty", "enriched": 0, "remaining_raw": 0,
                    "message": "No raw candidates in the pool — harvest first."}

        agent = ResearchAgent()
        ctx = {
            "run_id": None,
            "correlation_id": agent.correlation_id,
            "fast": fast,
            "keyword": industry or "",
            "target_country": "India",
            "target_size": 0,
            "geo_country": "India",
            "geo_region": region,
            "region": region,
            "explicit_geo": bool(region),
            "exclude_with_hrms": True,
            "company_mode": False,
        }

        enriched: list[dict] = []
        # run_cap is set high so _process_batch enriches the WHOLE batch (it stops
        # at run_cap; we want all of them banked, not a capped sample).
        agent._process_batch(candidates, ctx, run_cap=len(candidates) + 1,
                             new_leads=enriched, run_id=None)
        # _process_candidate already calls warehouse.save_enriched on each hot lead.

        stats = warehouse.stats()
        logger.info(f"[enrich] processed {len(candidates)} raw -> {len(enriched)} qualified; pool={stats}")
        return {
            "status": "ok",
            "processed": len(candidates),
            "enriched": len(enriched),
            "pool": stats,
        }
    except Exception as e:
        logger.warning(f"[enrich] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _running = False
        _LOCK.release()
