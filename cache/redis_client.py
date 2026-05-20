"""
Redis Client: Caching & Pipeline State
-----------------------------------------
Redis serves two roles in this system:

1. LLM Response Cache
   - Same company searched twice? Return cached result instantly
   - Saves Groq API quota, reduces latency from ~2s to ~5ms
   - TTL: 1 hour (leads go stale after that)

2. Pipeline State Persistence
   - Store intermediate pipeline state between stages
   - If container restarts mid-pipeline, state survives
   - Enables future async/distributed pipeline execution

Architectural Decision:
  Without Redis, every API call re-runs the full pipeline.
  At scale (100s of leads/day), this wastes LLM API budget and
  creates duplicate leads. Redis is the right tool for:
    - Ephemeral but fast key-value storage
    - Built-in TTL (auto-expiry of stale data)
    - Pub/Sub for future real-time lead dashboard
    - Rate limiting via atomic INCR + EXPIRE

Graceful Degradation:
  If Redis is unavailable, the system falls back to no-cache mode
  rather than crashing. This is critical for reliability.
"""
import json
import hashlib
import redis
from typing import Optional, Any
from core.config import get_settings

settings = get_settings()
_client: Optional[redis.Redis] = None


def get_redis() -> Optional[redis.Redis]:
    """
    Returns Redis client with connection pooling.
    Returns None if Redis is unavailable (graceful degradation).

    Bug fix: Always attempt ping to detect stale connections.
    If ping fails, reset and allow reconnection on next call.
    """
    global _client
    try:
        if _client is not None:
            _client.ping()  # Verify connection is still alive
            return _client
        # No client yet, try to connect
        _client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        _client.ping()
        return _client
    except Exception:
        _client = None  # Reset so next call retries
        return None


def cache_key(prefix: str, *args) -> str:
    """
    Generate a consistent cache key from prefix + arguments.
    Hashes long strings to keep keys short and safe.
    """
    raw = f"{prefix}:{'|'.join(str(a) for a in args)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def get_cached(key: str) -> Optional[Any]:
    """Retrieve a cached value. Returns None on miss or Redis unavailable."""
    client = get_redis()
    if not client:
        return None
    try:
        value = client.get(key)
        return json.loads(value) if value else None
    except Exception:
        return None


def set_cached(key: str, value: Any, ttl: int = None) -> bool:
    """Cache a value with TTL. Returns False if Redis unavailable."""
    client = get_redis()
    if not client:
        return False
    try:
        ttl = ttl or settings.redis_cache_ttl
        client.setex(key, ttl, json.dumps(value))
        return True
    except Exception:
        return False


def get_pipeline_state(pipeline_id: str) -> Optional[dict]:
    """Retrieve persisted pipeline state by ID."""
    return get_cached(f"pipeline:{pipeline_id}")


def set_pipeline_state(pipeline_id: str, state: dict) -> bool:
    """Persist pipeline state (survives container restarts)."""
    return set_cached(f"pipeline:{pipeline_id}", state, ttl=settings.redis_pipeline_ttl)


def check_rate_limit(client_ip: str, limit: int = None, window: int = 60) -> bool:
    """
    Redis-based rate limiting using atomic INCR + EXPIRE.
    Returns True if request is allowed, False if rate limited.

    Architectural Decision:
      Using Redis INCR is atomic, so there are no race conditions vs in-memory counters
      when running multiple API server replicas.
    """
    client = get_redis()
    if not client:
        return True  # Fail open if Redis is down

    limit = limit or settings.rate_limit_per_minute
    key = f"rate:{client_ip}"

    try:
        count = client.incr(key)
        if count == 1:
            client.expire(key, window)
        return count <= limit
    except Exception:
        return True  # Fail open


def is_duplicate_lead(company_name: str) -> bool:
    """
    Check if a company has already been processed in the last 24 hours.
    Prevents reprocessing the same lead and wasting LLM API quota.
    """
    client = get_redis()
    if not client:
        return False
    key = cache_key("seen_lead", company_name.lower().strip())
    return bool(client.get(key))


def mark_lead_seen(company_name: str):
    """Mark a company as processed to prevent duplicates."""
    client = get_redis()
    if not client:
        return
    key = cache_key("seen_lead", company_name.lower().strip())
    client.setex(key, 86400, "1")  # 24h dedup window
