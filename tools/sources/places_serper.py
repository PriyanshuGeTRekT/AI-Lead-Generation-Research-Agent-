"""
Google Maps (via Serper Places) harvester — PHONE-FIRST leads.
--------------------------------------------------------------
Phone is the only outreach channel, so we need leads that come WITH an accurate
phone. Google Maps is the best free source: every Places result carries a
Google-verified phone, and for an Indian SME the listed number is the owner's /
front-desk line — i.e. the relevant person. One Serper /places call returns ~15-20
such businesses, so this is far more credit-efficient than per-company lookups.

Harvests (HR-relevant category × NCR city) → businesses with name + VERIFIED phone +
website, banked as enriched leads (phone trusted=True). Fail-safe.
"""
import re
import threading
import time
from typing import Optional

from loguru import logger

# HR-relevant categories that employ people and are HRMS prospects.
CATEGORIES = [
    "manufacturers", "factories", "BPO companies", "call centers", "hospitals",
    "hotels", "logistics companies", "staffing agencies", "placement consultants",
    "pharmaceutical companies", "textile manufacturers", "engineering companies",
    "IT companies", "schools", "construction companies", "export houses",
    "food processing companies", "facility management services",
]
NCR_CITIES = ["Delhi", "Gurgaon", "Noida", "Faridabad", "Ghaziabad"]

_state = {"running": False, "queries_done": 0, "queries_total": 0, "added": 0, "with_phone": 0}
_lock = threading.Lock()


def status() -> dict:
    return dict(_state)


def running() -> bool:
    return _state["running"]


def _industry_for(cat: str) -> str:
    c = cat.lower()
    if "bpo" in c or "call cent" in c or "customer support" in c or "outsourc" in c: return "BPO"
    if "consult" in c: return "consulting"
    if "it compan" in c or "software" in c or "it services" in c or "tech" in c: return "IT services"
    if "staffing" in c or "placement" in c: return "staffing"
    if "hospital" in c: return "hospital"
    if "hotel" in c: return "hotel"
    if "logistic" in c: return "logistics"
    if "pharma" in c: return "pharma"
    if "textile" in c: return "textile"
    if "school" in c: return "education"
    if "construction" in c: return "construction"
    if "facility" in c: return "facility management"
    if "it compan" in c: return "IT services"
    if "export" in c: return "exports"
    if "food" in c: return "food processing"
    return "manufacturing"


def search_places(category: str, city: str) -> list[dict]:
    """One Serper /places call → businesses with Google-verified phone."""
    from core import signals
    industry = _industry_for(category)
    d = signals._serper(f"{category} in {city}", kind="places")
    out = []
    for p in (d.get("places") or []):
        phone = (p.get("phoneNumber") or "").strip()
        name = (p.get("title") or "").strip()
        if not name:
            continue
        out.append({
            "url": (p.get("website") or "").strip(),
            "title": name[:200],
            "location": f"{city}, India",
            "phone": phone,
            "industry": industry,
            "source": "google_maps",
        })
    return out


def lookup_company(name: str, city: str = "") -> dict:
    """Live single-company lookup via Google Maps (Serper Places). Returns the best
    matching business {title, phone, website, address, rating} or {}. For verification."""
    from core import signals
    if not name:
        return {}
    d = signals._serper(f"{name} {city}".strip(), kind="places")
    places = d.get("places") or []
    if not places:
        return {}
    p = places[0]
    return {
        "title": p.get("title", ""), "phone": (p.get("phoneNumber") or "").strip(),
        "website": (p.get("website") or "").strip(), "address": p.get("address", ""),
        "rating": p.get("rating"), "ratingCount": p.get("ratingCount"),
        "category": p.get("category", ""),
    }


def harvest_to_warehouse(cities: Optional[list[str]] = None,
                         categories: Optional[list[str]] = None) -> dict:
    """Sweep (category × NCR city) via Serper Places, banking phone-bearing businesses.
    Phones are Google-verified → trusted. Returns a summary."""
    from core import signals
    if not signals._serper_keys():
        return {"status": "error", "message": "No Serper key configured."}
    if not _lock.acquire(blocking=False):
        return {"status": "busy", **status()}
    try:
        from tools.sources import _directory_common as dc
        cl = cities or NCR_CITIES
        cats = categories or CATEGORIES
        _state.update(running=True, queries_done=0, queries_total=len(cl) * len(cats), added=0, with_phone=0)
        for city in cl:
            for cat in cats:
                cands = search_places(cat, city)
                # Bank with Google-verified phones (trusted=True).
                n = dc.bank(cands, region=city, source_label="Google Maps", tag_source="gmap", trusted=True)
                _state["added"] += n
                _state["with_phone"] += sum(1 for c in cands if c["phone"])
                _state["queries_done"] += 1
        from core import warehouse
        warehouse.tag_delhi_ncr()      # fold NCR cities into the Delhi NCR segment
        logger.info(f"[places_serper] banked {_state['added']} ({_state['with_phone']} w/ phone)")
        return {"status": "ok", "added": _state["added"], "with_phone": _state["with_phone"],
                "pool": warehouse.stats()}
    except Exception as e:
        logger.warning(f"[places_serper] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _state["running"] = False
        _lock.release()
