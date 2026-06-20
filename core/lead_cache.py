"""
Company Verdict Cache  (persistent, positive + negative)
--------------------------------------------------------
Every company we evaluate — whether it became a HOT lead or was EXCLUDED (already
has HRMS, wrong geo, competitor, too big) — is remembered by root domain with its
verdict and reason. The next run checks this cache FIRST and skips re-scraping /
re-LLM'ing known companies. The negative cache is the real token-saver: we never
pay twice to discover the same dead end.

Storage:
  - Redis hash `leadcache` (field=domain, value=JSON), 30-day TTL, when available.
  - JSON file ./data/lead_cache.json fallback so caching works without Redis.

All operations are fail-safe.
"""
import json
import os
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

try:
    from cache.redis_client import get_redis
except Exception:  # pragma: no cover
    def get_redis():  # type: ignore
        return None

_HKEY = "leadcache"
_TTL = 30 * 24 * 3600  # 30 days
_FILE = Path(os.getenv("LEAD_CACHE_PATH", "./data/lead_cache.json"))
_AGGREGATORS = {
    "linkedin.com", "indiamart.com", "wikipedia.org", "crunchbase.com",
    "naukri.com", "facebook.com", "instagram.com", "youtube.com", "glassdoor.com",
}


def domain_of(url_or_domain: str) -> str:
    """Normalize a URL/domain to a bare root domain (drops www, path, scheme)."""
    s = (url_or_domain or "").strip().lower()
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    host = urlparse(s).netloc or ""
    if host.startswith("www."):
        host = host[4:]
    return host


def is_aggregator(url_or_domain: str) -> bool:
    d = domain_of(url_or_domain)
    return any(d == a or d.endswith("." + a) for a in _AGGREGATORS)


# ── file fallback ─────────────────────────────────────────────────────────────
def _file_load() -> dict:
    if not _FILE.exists():
        return {}
    try:
        with open(_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _file_save(d: dict) -> None:
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, _FILE)
    except Exception:
        pass


# ── public API ────────────────────────────────────────────────────────────────
def get_verdict(url_or_domain: str) -> Optional[dict]:
    """Return the stored verdict dict for a domain, or None if unseen."""
    d = domain_of(url_or_domain)
    if not d:
        return None
    try:
        r = get_redis()
        if r is not None:
            raw = r.hget(_HKEY, d)
            if raw:
                return json.loads(raw)
            return None
    except Exception:
        pass
    return _file_load().get(d)


def set_verdict(
    url_or_domain: str,
    status: str,            # 'hot' | 'excluded'
    reason: str = "",
    company_name: str = "",
    no_hrms_confidence: Optional[float] = None,
    score: Optional[float] = None,
) -> None:
    """Record a verdict for a domain (positive or negative)."""
    d = domain_of(url_or_domain)
    if not d:
        return
    verdict = {
        "domain": d,
        "status": status,
        "reason": reason,
        "company_name": company_name,
        "no_hrms_confidence": no_hrms_confidence,
        "score": score,
        "ts": int(time.time()),
    }
    payload = json.dumps(verdict)
    try:
        r = get_redis()
        if r is not None:
            r.hset(_HKEY, d, payload)
            r.expire(_HKEY, _TTL)
            return
    except Exception:
        pass
    data = _file_load()
    data[d] = verdict
    _file_save(data)


def is_excluded(url_or_domain: str) -> bool:
    """True if this domain was previously evaluated and ruled out."""
    v = get_verdict(url_or_domain)
    return bool(v and v.get("status") == "excluded")


def is_seen(url_or_domain: str) -> bool:
    """True if this domain was evaluated before — HOT or excluded. Used to skip
    re-searching any company we've already processed (persists across restarts,
    independent of Redis), so we never re-spend tokens on the same lead."""
    return get_verdict(url_or_domain) is not None


def flush() -> dict:
    """Clear the verdict cache (Redis hash + file) so companies re-process. Fail-safe."""
    n = 0
    try:
        r = get_redis()
        if r is not None:
            n = r.hlen(_HKEY) or 0
            r.delete(_HKEY)
    except Exception:
        pass
    try:
        if _FILE.exists():
            n = n or len(_file_load())
            _file_save({})
    except Exception:
        pass
    return {"cleared": n}


def stats() -> dict:
    """Counts for observability/dashboard."""
    try:
        r = get_redis()
        if r is not None:
            items = r.hgetall(_HKEY) or {}
            verdicts = [json.loads(v) for v in items.values()]
        else:
            verdicts = list(_file_load().values())
    except Exception:
        verdicts = list(_file_load().values())
    hot = sum(1 for v in verdicts if v.get("status") == "hot")
    excluded = sum(1 for v in verdicts if v.get("status") == "excluded")
    return {"total": len(verdicts), "hot": hot, "excluded": excluded}
