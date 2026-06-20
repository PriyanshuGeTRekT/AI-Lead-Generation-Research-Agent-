"""
JustDial source (FREE) — local business directory.
---------------------------------------------------
JustDial indexes crores of Indian businesses by CITY + CATEGORY — clinics, hotels,
factories, BPOs, schools, logistics, manufacturers — most being SMEs with no HRMS.
Geo targeting (incl. Delhi / Maharashtra) is just a path segment, and each listing
carries name + locality + category, so leads land enriched rather than empty.

Best-effort + fail-safe: JustDial aggressively rate-limits and obfuscates phone
numbers (rendered as image/icon fonts, not text), so we do NOT promise phones here
— we reliably capture company name, locality and category, then deep-verify fills
contact on demand. Returns candidate dicts {url,title,location,phone,industry,
source}. Never raises.

NOTE: must run on the user's machine — the dev sandbox is network-restricted.
"""
import json
import re
import threading
import time
from typing import Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

from loguru import logger

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
# JustDial city-scoped category search, e.g. https://www.justdial.com/Delhi/Manufacturers
_URL = "https://www.justdial.com/{city}/{cat}"

# HR-relevant categories → readable industry label. JustDial slugifies the path.
CATEGORIES = {
    "Manufacturers": "manufacturing", "Textile-Manufacturers": "textile",
    "Pharmaceutical-Companies": "pharma", "Hospitals": "hospital",
    "Hotels": "hotel", "Call-Centre": "BPO", "BPO-Companies": "BPO",
    "Logistics-Companies": "logistics", "Placement-Services": "staffing",
    "Facility-Management-Services": "facility management",
    "Schools": "education", "Colleges": "education",
    "Real-Estate-Builders-Developers": "real estate",
    "Food-Processing-Companies": "food processing",
    "Auto-Components": "auto components", "Construction-Companies": "construction",
    "Export-Companies": "exports", "IT-Companies": "IT services",
}

DEFAULT_CITIES = ["Delhi", "Mumbai", "Pune", "Bangalore", "Chennai", "Hyderabad",
                  "Ahmedabad", "Surat", "Noida", "Gurgaon", "Faridabad", "Nagpur",
                  "Kolkata", "Jaipur", "Indore", "Coimbatore", "Ludhiana", "Thane"]

_state = {"running": False, "queries_done": 0, "queries_total": 0, "added": 0}
_lock = threading.Lock()


def status() -> dict:
    return dict(_state)


def running() -> bool:
    return _state["running"]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _parse(html: str, city: str, industry: str) -> list[dict]:
    """Extract business listings from a JustDial category page."""
    out: list[dict] = []
    seen: set[str] = set()

    # 1) Preferred: schema.org JSON-LD LocalBusiness blocks (name + address + phone).
    for m in re.finditer(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
                         html, re.I | re.S):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for it in items:
            if not isinstance(it, dict):
                continue
            name = _clean(str(it.get("name", "")))
            if not name or name.lower() in seen:
                continue
            tel = _clean(str(it.get("telephone", "")))
            addr = it.get("address") or {}
            locality = ""
            if isinstance(addr, dict):
                locality = _clean(str(addr.get("addressLocality") or addr.get("addressRegion") or ""))
            seen.add(name.lower())
            loc = f"{locality}, {city}" if locality and locality.lower() != city.lower() else f"{city}, India"
            out.append({"url": "", "title": name, "location": loc, "phone": tel,
                        "industry": industry, "source": "justdial"})

    # 2) Fallback: listing-card name spans (no phone — JD hides those as fonts).
    if not out:
        for m in re.finditer(r'class="[^"]*\b(?:lng_cont_name|resultbox_title_anchor|jcn)\b[^"]*"[^>]*>(.*?)<',
                             html, re.I | re.S):
            name = _clean(re.sub(r"<[^>]+>", "", m.group(1)))
            if name and name.lower() not in seen and len(name) > 2:
                seen.add(name.lower())
                out.append({"url": "", "title": name, "location": f"{city}, India",
                            "phone": "", "industry": industry, "source": "justdial"})
    return out


def probe(category: str = "Manufacturers", city: str = "Delhi") -> dict:
    """Diagnostic: fetch one query and report what the site actually returned."""
    if requests is None:
        return {"ok": False, "error": "requests not installed"}
    url = _URL.format(city=city.replace(" ", "-"), cat=category)
    try:
        r = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "en-IN,en;q=0.9"},
                         timeout=20)
        body = r.text or ""
        low = body.lower()
        parsed = _parse(body, city, category)
        return {
            "ok": True, "url": url, "http_status": r.status_code,
            "content_length": len(body),
            "looks_blocked": any(s in low for s in ("captcha", "access denied", "are you a human",
                                                    "unusual traffic", "/recaptcha", "cf-browser-verification")),
            "has_jsonld": "application/ld+json" in low,
            "has_localbusiness": "localbusiness" in low,
            "parsed_count": len(parsed),
            "snippet": body[:1200],
        }
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)}


def search_one(category: str, city: str, industry: str) -> list[dict]:
    # JustDial is a JS SPA — prefer the headless browser; fall back to static parse.
    from tools.sources import headless
    if headless.available():
        rows = headless.fetch_justdial(category, city, industry)
        if rows:
            return rows
    if requests is None:
        return []
    url = _URL.format(city=city.replace(" ", "-"), cat=category)
    try:
        r = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "en-IN,en;q=0.9"},
                         timeout=20)
        if r.status_code != 200 or not r.text:
            logger.debug(f"[justdial] {category}@{city} -> HTTP {r.status_code}")
            return []
        return _parse(r.text, city, industry)
    except Exception as e:
        logger.debug(f"[justdial] {category}@{city} failed: {e}")
        return []


# Generic source interface (web_search multi-source).
def search_companies(keyword: str, region: Optional[str] = None, max_results: int = 50) -> list[dict]:
    city = region or "Delhi"
    cat = keyword.replace(" ", "-").title()
    ind = CATEGORIES.get(cat, keyword)
    return search_one(cat, city, ind)[:max_results]


def harvest_to_warehouse(cities: Optional[list[str]] = None,
                         categories: Optional[list[str]] = None,
                         delay: float = 1.5) -> dict:
    """Sweep (category x city), banking listings as enriched leads. Polite delay
    between requests. Returns a summary."""
    if not _lock.acquire(blocking=False):
        return {"status": "busy", **status()}
    try:
        from tools.sources import _directory_common as dc
        cats = categories or list(CATEGORIES.keys())
        cl = cities or DEFAULT_CITIES
        _state.update(running=True, queries_done=0, queries_total=len(cats) * len(cl), added=0)
        for city in cl:
            for cat in cats:
                ind = CATEGORIES.get(cat, cat.replace("-", " "))
                cands = search_one(cat, city, ind)
                _state["added"] += dc.bank(cands, region=city, source_label="JustDial", tag_source="jd")
                _state["queries_done"] += 1
                if delay:
                    time.sleep(delay)
        from core import warehouse
        logger.info(f"[justdial] banked {_state['added']} leads")
        return {"status": "ok", "added": _state["added"], "pool": warehouse.stats()}
    except Exception as e:
        logger.warning(f"[justdial] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _state["running"] = False
        _lock.release()
