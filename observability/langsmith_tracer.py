"""
Observability: LangSmith + Custom Metrics
-------------------------------------------
Two-tier observability strategy:

Tier 1: LangSmith (Agent-level tracing)
  - Full trace of every LLM call: prompt, response, latency, token usage
  - Agent decision visualization (which nodes ran, in what order)
  - Prompt regression testing (compare outputs across model versions)
  - Hallucination flagging in traces

Tier 2: Custom Metrics (Business-level)
  - Lead quality score distribution
  - Qualification pass/fail rate
  - Pipeline latency per stage
  - LLM cache hit rate
  - Error rate by exception type

Architectural Decision:
  LangSmith answers "what did the agent decide and why?"
  Custom metrics answer "is the business outcome improving?"
  Both are needed. One without the other gives incomplete visibility.

  For production, custom metrics would feed into:
  - Datadog / Prometheus for dashboards
  - PagerDuty for alerting on error rate spikes
  - Weekly lead quality reports for the sales team

Monitoring Strategy for the 5 required dimensions:

  1. Hallucinations     → HallucinationGuard logs warnings + LangSmith tags
  2. Latency           → stage_timer() decorator on each agent
  3. API failures      → LLMError exceptions logged with error type + count
  4. Agent failures    → PipelineError exceptions tracked per agent name
  5. Lead quality      → qualification_score distribution logged to file
"""
import os
import time
import json
from pathlib import Path
from datetime import datetime
from typing import Callable
from functools import wraps
from loguru import logger
from core.config import get_settings

settings = get_settings()

# ── LangSmith Setup ──────────────────────────────────────────────────────────

def setup_langsmith():
    """
    Enable LangSmith tracing if API key is configured.
    All LangChain/LangGraph calls are automatically traced when enabled.
    """
    if settings.langchain_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        logger.info(f"LangSmith tracing enabled → project: {settings.langchain_project}")
    else:
        logger.info("LangSmith tracing disabled (no LANGCHAIN_API_KEY set)")


# ── Latency Tracking ─────────────────────────────────────────────────────────

def stage_timer(stage_name: str):
    """
    Decorator that logs execution time for any pipeline stage.
    Use on agent run() methods to track per-stage latency.

    Usage:
        @stage_timer("research_agent")
        def research_agent(state): ...
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                logger.bind(agent=stage_name, correlation_id="sys").info(
                    f"Stage completed in {elapsed:.2f}s",
                    extra={"stage": stage_name, "latency_ms": int(elapsed * 1000)}
                )
                # Log to metrics file
                _append_metric("latency", {
                    "stage": stage_name,
                    "latency_ms": int(elapsed * 1000),
                    "timestamp": datetime.utcnow().isoformat(),
                })
                return result
            except Exception as e:
                elapsed = time.time() - start
                logger.bind(agent=stage_name, correlation_id="sys").error(
                    f"Stage FAILED after {elapsed:.2f}s: {e}"
                )
                _append_metric("agent_failure", {
                    "stage": stage_name,
                    "error": type(e).__name__,
                    "message": str(e),
                    "timestamp": datetime.utcnow().isoformat(),
                })
                raise
        return wrapper
    return decorator


# ── Lead Quality Metrics ─────────────────────────────────────────────────────

def log_lead_quality(leads: list):
    """
    Log qualification score distribution for long-term quality tracking.
    Enables data-driven tuning of the qualification prompt and threshold.

    Sales team can use this to identify if the agent is being too strict/lenient.
    """
    if not leads:
        return

    scores = [
        l.get("qualification_score", 0)
        for l in leads
        if l.get("qualification_score") is not None
    ]

    if not scores:
        return

    qualified = sum(1 for s in scores if s >= settings.qualification_threshold)
    metrics = {
        "timestamp": datetime.utcnow().isoformat(),
        "total_leads": len(leads),
        "qualified": qualified,
        "disqualified": len(scores) - qualified,
        "avg_score": round(sum(scores) / len(scores), 2),
        "min_score": min(scores),
        "max_score": max(scores),
        "pass_rate": round(qualified / len(scores), 3) if scores else 0,
    }

    logger.info(f"Lead quality metrics: {metrics}")
    _append_metric("lead_quality", metrics)


# ── Hallucination Tracking ───────────────────────────────────────────────────

def log_hallucination_event(agent: str, guard_result: dict, correlation_id: str):
    """Log hallucination guard outcomes for monitoring."""
    if not guard_result.get("passed"):
        logger.warning(
            f"Hallucination warning in {agent}: {guard_result.get('warnings')}",
        )
        _append_metric("hallucination_warning", {
            "agent": agent,
            "confidence": guard_result.get("confidence"),
            "warnings": guard_result.get("warnings"),
            "action": guard_result.get("action"),
            "correlation_id": correlation_id,
            "timestamp": datetime.utcnow().isoformat(),
        })


# ── Metrics File ─────────────────────────────────────────────────────────────

METRICS_PATH = Path("./data/metrics.jsonl")


def _append_metric(event_type: str, data: dict):
    """Append a metric event to JSONL file (one JSON object per line)."""
    try:
        METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(METRICS_PATH, "a") as f:
            f.write(json.dumps({"event": event_type, **data}) + "\n")
    except Exception:
        pass  # Never let metric logging break the pipeline


def get_metrics_summary() -> dict:
    """Read and summarize all metrics from the JSONL file."""
    if not METRICS_PATH.exists():
        return {"message": "No metrics recorded yet"}

    events = []
    with open(METRICS_PATH) as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except Exception:
                continue

    by_type = {}
    for e in events:
        t = e.get("event", "unknown")
        by_type.setdefault(t, []).append(e)

    return {
        "total_events": len(events),
        "latency_avg_ms": _avg([e.get("latency_ms", 0) for e in by_type.get("latency", [])]),
        "agent_failures": len(by_type.get("agent_failure", [])),
        "hallucination_warnings": len(by_type.get("hallucination_warning", [])),
        "lead_quality_runs": len(by_type.get("lead_quality", [])),
        "last_quality_metrics": by_type.get("lead_quality", [{}])[-1],
    }


def _avg(lst: list) -> float:
    return round(sum(lst) / len(lst), 2) if lst else 0
