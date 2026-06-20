"""
Common Crawl source (FREE, keyless, LAKHS-scale firehose)
---------------------------------------------------------
Common Crawl indexes the whole web for free. India's commercial web (*.co.in,
*.firm.in, *.ind.in + company *.in) holds lakhs of registered businesses. We pull
unique registered domains, filter HARD to business-like sites (dropping govt /
edu / parked / spam / blog hosts), and bank them as RAW leads. The enrichment
worker + ICP scorer then promote only the genuine, HR-relevant ones to the shown
pool — so volume comes from here, quality from the funnel.

Keyless. Fail-safe. Returns candidate dicts {url, title, source}.
"""
import json
import re
import threading
from typing import Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

from loguru import logger

# Recent Common Crawl monthly index (CDX). Updated periodically; any valid one works.
_CC_INDEX = "https://index.commoncrawl.org/CC-MAIN-2024-33-index"
_UA = "RazorInfotech-Leads/1.0 (razorinfotechpvtltd@gmail.com)"

# India web patterns. co.in/firm.in/ind.in are highest business density; *.in is
# the broad firehose (blocklist strips govt/edu/personal). Multiple CC indexes add
# coverage since each monthly crawl sees different domains.
_PATTERNS = ["*.co.in", "*.firm.in", "*.ind.in", "*.net.in", "*.org.in",
             "*.gen.in", "*.in"]
_CC_INDEXES = [
    "https://index.commoncrawl.org/CC-MAIN-2024-33-index",
    "https://index.commoncrawl.org/CC-MAIN-2024-10-index",
]

# Hosts that are NOT sales prospects — drop hard for quality.
_BLOCK = re.compile(
    r"(gov\.in|nic\.in|ac\.in|edu\.in|res\.in|mil\.in|"
    r"blogspot|wordpress\.com|\.blogspot\.|tumblr|medium\.com|"
    r"facebook|instagram|youtube|twitter|linkedin|pinterest|"
    r"movierulz|betting|casino|satta|porn|xxx|escort|lottery|"
    r"\.000webhost|\.100mb|godaddysites|wixsite|weebly|"
    r"amazonaws|cloudfront|sharepoint|google|appspot)", re.I)

_lock = threading.Lock()
_state = {"running": False, "pages_done": 0, "pages_total": 0, "added": 0, "seen": 0}


def status() -> dict:
    return dict(_state)


def is_running() -> bool:
    return _state["running"]


def _registered_domain(url: str) -> str:
    h = re.sub(r"^https?://", "", url or "").split("/")[0].lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def _name_from_domain(dom: str) -> str:
    core = dom.split(".")[0].replace("-", " ").replace("_", " ")
    return core.title()


def _fetch_page(pattern: str, page: int, page_size: int = 5000, index: str = _CC_INDEX) -> list[str]:
    if requests is None:
        return []
    try:
        # Server-side filters: only live (HTTP 200) HTML pages → kills the dead/parked
        # domain waste that otherwise burns ~2/3 of enrichment time.
        r = requests.get(index, params={"url": pattern, "output": "json", "fl": "url",
                                        "filter": ["status:200", "mime:text/html"],
                                        "page": page, "pageSize": page_size},
                         headers={"User-Agent": _UA}, timeout=60)
        if r.status_code != 200:
            return []
        return [l for l in r.text.splitlines() if l.strip()]
    except Exception as e:
        logger.debug(f"[cc] page {page} {pattern} failed: {e}")
        return []


def harvest(max_pages_per_pattern: int = 8, page_size: int = 5000) -> dict:
    """Page Common Crawl for Indian business domains and bank them as RAW leads.
    Volume firehose — the enrichment funnel turns these into quality leads."""
    if not _lock.acquire(blocking=False):
        return {"status": "busy", **status()}
    try:
        from core import warehouse
        seen: set = set()
        total_pages = max_pages_per_pattern * len(_PATTERNS) * len(_CC_INDEXES)
        _state.update(running=True, pages_done=0, pages_total=total_pages, added=0, seen=0)
        combos = [(idx, pat) for idx in _CC_INDEXES for pat in _PATTERNS]
        for index, pattern in combos:
            for page in range(max_pages_per_pattern):
                lines = _fetch_page(pattern, page, page_size, index)
                batch = []
                for ln in lines:
                    try:
                        url = json.loads(ln).get("url", "")
                    except Exception:
                        continue
                    dom = _registered_domain(url)
                    if not dom or dom in seen or _BLOCK.search(dom):
                        continue
                    seen.add(dom)
                    batch.append({"url": f"https://{dom}", "title": _name_from_domain(dom),
                                  "source": "commoncrawl"})
                if batch:
                    _state["added"] += warehouse.upsert_raw(batch, region="India")
                _state["seen"] = len(seen)
                _state["pages_done"] += 1
                if lines and len(lines) < page_size:
                    break  # last page for this pattern
        logger.info(f"[cc] +{_state['added']} raw domains ({len(seen)} unique seen); pool={warehouse.stats()}")
        return {"status": "ok", "added": _state["added"], "unique": len(seen), "pool": warehouse.stats()}
    except Exception as e:
        logger.warning(f"[cc] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _state["running"] = False
        _lock.release()
