"""
Harvest Matrix
--------------
The volume engine. A single keyword harvest yields ~50-95 companies; to fill the
warehouse toward hundreds of thousands of leads we systematically sweep the
cartesian product of (industry x city) across the India SME belt, harvesting each
combination's raw candidates into the pool (deduped by domain).

Discovery is CHEAP (no AI, no scraping) so this can run broad and long in the
background; the expensive enrichment then drains the raw pool separately
(agents/enrichment_worker). Fully fail-safe.
"""
import json
import os
import threading
import time
from pathlib import Path

from loguru import logger

# Persistent cursor so each sweep continues where the last left off (repeated
# "Build pool" runs cover FRESH combos instead of re-hitting the same ones).
_CURSOR = Path(os.getenv("MATRIX_CURSOR_PATH", "./data/matrix_cursor.json"))


def _load_cursor() -> int:
    try:
        return int(json.loads(_CURSOR.read_text()).get("pos", 0))
    except Exception:
        return 0


def _save_cursor(pos: int) -> None:
    try:
        _CURSOR.parent.mkdir(parents=True, exist_ok=True)
        _CURSOR.write_text(json.dumps({"pos": pos}))
    except Exception:
        pass

# ANY company with a workforce is a potential HRMS lead — so cast the net across
# EVERY sector, not just manufacturing/SME. (Factories, services, professional,
# institutional… all of it.)
INDUSTRIES = [
    # Manufacturing & industrial / factories
    "manufacturing", "factory", "textile", "garment", "apparel", "pharmaceutical",
    "chemical", "petrochemical", "fertilizer", "paint", "rubber", "plastics",
    "steel", "metal", "foundry", "cement", "glass", "ceramics", "paper", "pulp",
    "packaging", "printing", "machinery", "industrial equipment", "tools",
    "automotive", "auto components", "auto ancillary", "electronics", "electrical",
    "semiconductor", "appliances", "engineering", "fabrication", "heavy industry",
    "aerospace", "defence", "shipbuilding", "battery", "solar", "renewable energy",
    "oil and gas", "mining", "power", "wire and cable",
    # Logistics, supply chain, trade
    "logistics", "freight forwarding", "warehousing", "transport", "courier",
    "supply chain", "shipping", "ports", "cold chain", "exports", "import export",
    "trading", "distribution", "wholesale",
    # Tech & services
    "IT services", "software", "SaaS", "IT consulting", "data center", "BPO",
    "KPO", "call center", "ITES", "fintech", "edtech", "healthtech", "agritech",
    "cybersecurity", "cloud", "analytics", "gaming", "animation",
    # Healthcare & life sciences
    "hospital", "clinic", "diagnostic", "healthcare", "medical devices",
    "biotechnology", "nursing home", "pharmacy chain",
    # Consumer, retail, food
    "retail", "e-commerce", "FMCG", "food processing", "dairy", "beverages",
    "restaurant chain", "QSR", "supermarket", "apparel retail", "jewellery",
    "consumer durables", "cosmetics", "agro", "agriculture", "seeds",
    # Real estate, infra, construction
    "real estate", "construction", "infrastructure", "EPC", "architecture",
    "interior", "building materials", "cement dealer",
    # Financial & professional services
    "NBFC", "insurance", "banking", "broking", "microfinance", "accounting",
    "audit firm", "law firm", "consulting", "staffing", "recruitment",
    "facility management", "security services", "advertising", "marketing agency",
    "media", "publishing", "events",
    # Hospitality, travel, education, institutional
    "hospitality", "hotel", "resort", "travel", "tourism", "airline",
    "education", "university", "school", "college", "coaching", "training",
    "NGO", "cooperative", "telecom", "broadcasting", "utilities",
]

# India SME belt — Hindi + English speaking metros + tier-2 hubs.
CITIES = [
    "Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Pune", "Kolkata",
    "Ahmedabad", "Noida", "Gurugram", "Jaipur", "Indore", "Coimbatore", "Surat",
    "Nagpur", "Lucknow", "Chandigarh", "Kochi", "Vadodara", "Nashik", "Rajkot",
    "Ludhiana", "Bhopal", "Visakhapatnam", "Faridabad", "Thane", "Vijayawada",
    "Madurai", "Bhubaneswar", "Mysuru",
]

_LOCK = threading.Lock()
_state = {"running": False, "done": 0, "total": 0, "added": 0, "started_at": 0.0}


def status() -> dict:
    return dict(_state)


def is_running() -> bool:
    return _state["running"]


def run_matrix(max_queries: int = 200, per_query: int = 60,
               industries: list[str] | None = None, cities: list[str] | None = None) -> dict:
    """Sweep (industry x city) harvesting raw candidates into the warehouse.

    max_queries caps the sweep so it stays bounded; ordering interleaves cities so
    an early stop still gives broad geographic coverage. Returns a summary.
    """
    if not _LOCK.acquire(blocking=False):
        return {"status": "busy", "message": "A matrix harvest is already running."}
    try:
        from core import warehouse
        from tools.web_search import search_companies_multi_source

        inds = industries or INDUSTRIES
        cits = cities or CITIES
        # City-major so CONSECUTIVE queries hit DIFFERENT industries (each industry
        # yields a fresh result set; the city term barely changes a Wikidata query).
        # The rotating cursor then walks new industries each run.
        full = [(ind, city) for city in cits for ind in inds]
        start = _load_cursor() % len(full)
        # Take max_queries combos from the cursor, wrapping around the end.
        combos = [full[(start + i) % len(full)] for i in range(min(max_queries, len(full)))]
        _save_cursor((start + len(combos)) % len(full))
        _state.update(running=True, done=0, total=len(combos), added=0, started_at=time.time())
        logger.info(f"[matrix] sweeping {len(combos)} combos from cursor {start}/{len(full)}")

        for ind, city in combos:
            kw = f"{ind} company {city} India"
            try:
                cands = search_companies_multi_source(kw, max_results=per_query)
                added = warehouse.upsert_raw(cands, region=city, industry=ind)
                _state["added"] += added
            except Exception as e:
                logger.debug(f"[matrix] '{kw}' failed: {e}")
            _state["done"] += 1

        stats = warehouse.stats()
        logger.info(f"[matrix] done: {_state['added']} new raw; pool={stats}")
        return {"status": "ok", "queries": _state["done"], "added": _state["added"], "pool": stats}
    except Exception as e:
        logger.warning(f"[matrix] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _state["running"] = False
        _LOCK.release()
