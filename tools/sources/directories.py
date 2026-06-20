"""
Unified directory harvester — sweeps every JS directory (IndiaMART, JustDial,
TradeIndia, Sulekha, ExportersIndia) for a city via the headless engine and banks
the businesses as enriched leads. One call covers all the IndiaMART-like sites.

Needs the headless engine (Playwright + Chromium). Fail-safe + background-friendly.
"""
import threading
import time
from typing import Optional

from loguru import logger

# HR-relevant categories to sweep per city (phrase → readable industry).
CATEGORIES = {
    "manufacturers": "manufacturing", "textile manufacturers": "textile",
    "pharmaceutical companies": "pharma", "hospitals": "hospital",
    "hotels": "hotel", "bpo companies": "BPO", "call centers": "BPO",
    "logistics companies": "logistics", "placement consultants": "staffing",
    "facility management services": "facility management",
    "schools": "education", "real estate builders": "real estate",
    "food processing companies": "food processing", "construction companies": "construction",
    "export companies": "exports", "it companies": "IT services",
}

DEFAULT_CITIES = ["Delhi", "Mumbai", "Pune", "Bengaluru", "Chennai", "Hyderabad",
                  "Ahmedabad", "Noida", "Gurugram", "Kolkata", "Jaipur", "Ludhiana"]

_state = {"running": False, "queries_done": 0, "queries_total": 0, "added": 0,
          "by_site": {}, "engine": ""}
_lock = threading.Lock()


def status() -> dict:
    return dict(_state)


def running() -> bool:
    return _state["running"]


def harvest_to_warehouse(cities: Optional[list[str]] = None,
                         categories: Optional[list[str]] = None,
                         sites: Optional[list[str]] = None,
                         delay: float = 0.5) -> dict:
    from tools.sources import headless
    if not headless.available():
        return {"status": "error", "message": headless.INSTALL_HINT}
    if not _lock.acquire(blocking=False):
        return {"status": "busy", **status()}
    try:
        from tools.sources import _directory_common as dc
        site_list = sites or list(headless.SITES.keys())
        cats = categories or list(CATEGORIES.keys())
        cl = cities or DEFAULT_CITIES
        _state.update(running=True, queries_done=0,
                      queries_total=len(site_list) * len(cats) * len(cl),
                      added=0, by_site={s: 0 for s in site_list}, engine="playwright-chromium")
        for city in cl:
            for cat in cats:
                ind = CATEGORIES.get(cat.lower(), cat)
                for site in site_list:
                    try:
                        rows = headless.harvest_site(site, cat, city, ind)
                        n = dc.bank(rows, region=city, source_label=site.title(),
                                    tag_source=site[:3])
                        _state["added"] += n
                        _state["by_site"][site] = _state["by_site"].get(site, 0) + n
                    except Exception as e:
                        logger.debug(f"[directories] {site} {cat}@{city} failed: {e}")
                    _state["queries_done"] += 1
                    if delay:
                        time.sleep(delay)
        from core import warehouse
        logger.info(f"[directories] banked {_state['added']} leads: {_state['by_site']}")
        return {"status": "ok", "added": _state["added"], "by_site": _state["by_site"],
                "pool": warehouse.stats()}
    except Exception as e:
        logger.warning(f"[directories] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _state["running"] = False
        _lock.release()
