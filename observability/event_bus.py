"""
Theater Event Bus
-----------------
Backs the Live Agent Theater. Agents emit lightweight events keyed by run_id;
the FastAPI /stream/{run_id} endpoint replays them to the browser over SSE.

Transport:
  - Redis list `theater:{run_id}` (RPUSH + EXPIRE) when Redis is available.
    A list (not pub/sub) is used so late subscribers still get the full backlog
    and so the API process can read events produced by a separate Celery worker.
  - In-process dict fallback when Redis is down (covers single-process sync runs).

Every function is fail-safe: emitting or reading must never raise into the
pipeline or the request handler.
"""
import json
import time
from typing import Any, Optional

try:
    from cache.redis_client import get_redis
except Exception:  # pragma: no cover - defensive
    def get_redis():  # type: ignore
        return None

_TTL = 3600
_MEM: dict[str, list[str]] = {}

# Lead fields worth shipping to the map / stream (keep payloads tiny).
_LEAD_KEYS = (
    "id",
    "company_name",
    "location",
    "address",
    "industry",
    "qualification_score",
    "status",
    "decision_maker_full_name",
)


def _key(run_id: str) -> str:
    return f"theater:{run_id}"


def _slim_lead(lead: dict) -> dict:
    return {k: lead.get(k) for k in _LEAD_KEYS if lead.get(k) is not None}


def emit(
    run_id: Optional[str],
    type: str,
    agent: str = "",
    stage: str = "",
    message: str = "",
    lead: Optional[dict] = None,
    meta: Optional[dict[str, Any]] = None,
) -> None:
    """Append one event to the run's stream. No-op if run_id is falsy."""
    if not run_id:
        return
    evt: dict[str, Any] = {
        "ts": int(time.time() * 1000),
        "type": type,
        "agent": agent,
        "stage": stage,
        "message": message,
    }
    if lead is not None:
        evt["lead"] = _slim_lead(lead)
    if meta:
        evt["meta"] = meta
    payload = json.dumps(evt, default=str)

    try:
        r = get_redis()
        if r is not None:
            k = _key(run_id)
            r.rpush(k, payload)
            r.expire(k, _TTL)
            return
    except Exception:
        pass
    _MEM.setdefault(run_id, []).append(payload)


def read(run_id: str, start: int = 0) -> list[dict]:
    """Return events from index `start` onward."""
    try:
        r = get_redis()
        if r is not None:
            items = r.lrange(_key(run_id), start, -1)
            return [_decode(i) for i in items]
    except Exception:
        pass
    return [json.loads(p) for p in _MEM.get(run_id, [])[start:]]


def _decode(item: Any) -> dict:
    if isinstance(item, (bytes, bytearray)):
        item = item.decode("utf-8", "replace")
    return json.loads(item)
