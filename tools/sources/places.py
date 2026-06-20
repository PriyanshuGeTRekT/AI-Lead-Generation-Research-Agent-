"""
Google Places source — reliable city × category business harvest.
------------------------------------------------------------------
The most reliable contact-bearing source: Google Places Text Search returns real
businesses for a "category in city" query (name, address, phone, website), the
same data JustDial surfaces but via a stable JSON API instead of a scraped SPA.
Needs a Google Places API key (free $200/mo credit covers tens of thousands of
calls). Geo-targets any city — Delhi/Maharashtra included.

Uses Places API v1 (places.googleapis.com) Text Search with a field mask so each
result already carries displayName + formattedAddress + nationalPhoneNumber +
websiteUri — no follow-up Details call needed. Paginates via nextPageToken.
Returns candidate dicts {url,title,location,phone,industry,source}. Fail-safe.
"""
import threading
import time
from typing import Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

from loguru import logger

_ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
_FIELDS = ("places.displayName,places.formattedAddress,places.nationalPhoneNumber,"
           "places.internationalPhoneNumber,places.websiteUri,places.primaryType,"
           "places.businessStatus,nextPageToken")

# HR-relevant search phrases → readable industry. Each is run as "<phrase> in <city>".
CATEGORIES = {
    "manufacturers": "manufacturing", "textile manufacturers": "textile",
    "pharmaceutical company": "pharma", "hospital": "hospital",
    "hotel": "hotel", "call center": "BPO", "bpo company": "BPO",
    "logistics company": "logistics", "staffing agency": "staffing",
    "facility management company": "facility management",
    "school": "education", "college": "education",
    "real estate builder": "real estate", "food processing company": "food processing",
    "auto parts manufacturer": "auto components", "construction company": "construction",
    "export company": "exports", "software company": "IT services",
    "wholesale distributor": "wholesale", "printing press": "manufacturing",
}

DEFAULT_CITIES = ["Delhi", "Mumbai", "Pune", "Bengaluru", "Chennai", "Hyderabad",
                  "Ahmedabad", "Surat", "Noida", "Gurugram", "Faridabad", "Thane",
                  "Nagpur", "Kolkata", "Jaipur", "Indore", "Coimbatore", "Ludhiana"]

_state = {"running": False, "queries_done": 0, "queries_total": 0, "added": 0, "error": ""}
_lock = threading.Lock()


def status() -> dict:
    return dict(_state)


def running() -> bool:
    return _state["running"]


def _key() -> str:
    from core import runtime_config as rc
    return (rc.get("google_places_api_key") or "").strip()


def _search_page(query: str, key: str, page_token: str = "") -> dict:
    body = {"textQuery": query, "pageSize": 20, "regionCode": "IN"}
    if page_token:
        body["pageToken"] = page_token
    r = requests.post(
        _ENDPOINT,
        headers={"Content-Type": "application/json", "X-Goog-Api-Key": key,
                 "X-Goog-FieldMask": _FIELDS},
        json=body, timeout=20,
    )
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]}")
    return r.json()


def search_one(phrase: str, city: str, industry: str, max_pages: int = 3) -> list[dict]:
    """Run '<phrase> in <city>' and page through results."""
    key = _key()
    if requests is None or not key:
        return []
    out: list[dict] = []
    token = ""
    for _ in range(max_pages):
        try:
            data = _search_page(f"{phrase} in {city}", key, token)
        except Exception as e:
            logger.debug(f"[places] {phrase}@{city} failed: {e}")
            break
        for p in data.get("places", []) or []:
            if p.get("businessStatus") and p["businessStatus"] != "OPERATIONAL":
                continue
            name = (p.get("displayName") or {}).get("text", "")
            if not name:
                continue
            phone = p.get("nationalPhoneNumber") or p.get("internationalPhoneNumber") or ""
            addr = p.get("formattedAddress") or f"{city}, India"
            out.append({
                "url": (p.get("websiteUri") or "").strip(),
                "title": name[:200],
                "location": addr,
                "phone": phone,
                "industry": industry,
                "source": "google_places",
            })
        token = data.get("nextPageToken") or ""
        if not token:
            break
        time.sleep(2)  # token needs a moment to become valid
    return out


# Generic source interface (web_search multi-source).
def search_companies(keyword: str, region: Optional[str] = None, max_results: int = 40) -> list[dict]:
    if not _key():
        return []
    ind = CATEGORIES.get(keyword.lower(), keyword)
    return search_one(keyword, region or "India", ind)[:max_results]


def harvest_to_warehouse(cities: Optional[list[str]] = None,
                         categories: Optional[list[str]] = None,
                         delay: float = 0.3) -> dict:
    """Sweep (category × city) via Places, banking results as enriched leads (phones
    are Google-verified → trusted). Returns a summary."""
    if not _key():
        return {"status": "error", "message": "No google_places_api_key configured (add it in Settings)."}
    if not _lock.acquire(blocking=False):
        return {"status": "busy", **status()}
    try:
        from tools.sources import _directory_common as dc
        cats = categories or list(CATEGORIES.keys())
        cl = cities or DEFAULT_CITIES
        _state.update(running=True, queries_done=0, queries_total=len(cats) * len(cl), added=0, error="")
        for city in cl:
            for kw in cats:
                ind = CATEGORIES.get(kw.lower(), kw)
                cands = search_one(kw, city, ind)
                # Places phones are verified → bank as trusted via a tiny shim.
                _state["added"] += dc.bank(cands, region=city, source_label="Google Places",
                                           tag_source="gp", trusted=True)
                _state["queries_done"] += 1
                if delay:
                    time.sleep(delay)
        from core import warehouse
        logger.info(f"[places] banked {_state['added']} leads")
        return {"status": "ok", "added": _state["added"], "pool": warehouse.stats()}
    except Exception as e:
        _state["error"] = str(e)
        logger.warning(f"[places] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _state["running"] = False
        _lock.release()
