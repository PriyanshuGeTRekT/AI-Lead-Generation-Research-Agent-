"""
IndiaMART source (FREE) — B2B supplier directory.
-------------------------------------------------
IndiaMART is India's largest B2B marketplace: manufacturers, suppliers, exporters,
wholesalers — exactly the labour-heavy SMEs that employ people and rarely run a
real HRMS. Listings are indexed by KEYWORD + CITY, so geo targeting (incl. Delhi /
Maharashtra, which the MCA mirror lacks) is just a query parameter, and each card
already carries company name + city + category — leads land enriched, not empty.

Best-effort + fail-safe: IndiaMART rate-limits and changes markup, and phone
numbers usually sit behind a "View Number" action (not in the static HTML). We
extract what is reliably present — company name, city, category, listing URL, and
any plain-text phone — then the deep-verify pipeline fills the decision-maker and
contact details on demand. Returns candidate dicts {url,title,location,phone,
industry,source}. Never raises.

NOTE: must run on the user's machine — the dev sandbox is network-restricted.
"""
import json
import re
import threading
import time
from typing import Optional
from urllib.parse import quote_plus

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

from loguru import logger

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_SEARCH = "https://dir.indiamart.com/search.mp?ss={kw}&cq={city}"

# HR-relevant B2B categories on IndiaMART — sectors that employ workforce and are
# strong HRMS prospects. (keyword -> readable industry label)
CATEGORIES = {
    "manufacturers": "manufacturing", "industrial machinery": "manufacturing",
    "textile manufacturers": "textile", "garment manufacturers": "textile",
    "pharmaceutical manufacturers": "pharma", "food processing": "food processing",
    "auto components": "auto components", "plastic manufacturers": "manufacturing",
    "chemical manufacturers": "chemical", "packaging manufacturers": "manufacturing",
    "electrical equipment": "manufacturing", "steel fabrication": "steel",
    "logistics services": "logistics", "exporters": "exports",
    "construction company": "construction", "facility management services": "facility management",
    "manpower recruitment": "staffing", "call center services": "BPO",
    "hospital equipment": "healthcare", "hotel supplies": "hotel",
}

DEFAULT_CITIES = ["Delhi", "Mumbai", "Pune", "Bengaluru", "Chennai", "Hyderabad",
                  "Ahmedabad", "Surat", "Noida", "Gurugram", "Faridabad", "Thane",
                  "Nagpur", "Kolkata", "Jaipur", "Indore", "Coimbatore", "Ludhiana"]

_state = {"running": False, "queries_done": 0, "queries_total": 0, "added": 0}
_lock = threading.Lock()


def status() -> dict:
    return dict(_state)


def running() -> bool:
    return _state["running"]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _parse(html: str, city: str, industry: str) -> list[dict]:
    """Pull supplier cards out of an IndiaMART search results page."""
    out: list[dict] = []
    seen: set[str] = set()

    # 1) Preferred: embedded JSON-LD / data blobs with company info.
    for m in re.finditer(r'"companyname"\s*:\s*"([^"]{2,120})"', html, re.I):
        name = _clean(m.group(1))
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append({"title": name, "city": city})
    # 2) Fallback: anchor cards linking to supplier microsites.
    if not out:
        for m in re.finditer(r'<a[^>]+class="[^"]*\b(?:cardlinks|lcname|companyname)\b[^"]*"[^>]*>(.*?)</a>',
                             html, re.I | re.S):
            name = _clean(re.sub(r"<[^>]+>", "", m.group(1)))
            if name and name.lower() not in seen and len(name) > 2:
                seen.add(name.lower())
                out.append({"title": name, "city": city})

    # Attach any plain-text phone that appears near each name (best-effort).
    leads = []
    for c in out:
        phone = ""
        idx = html.find(c["title"])
        if idx != -1:
            window = html[idx: idx + 600]
            pm = re.search(r'(?:\+?91[\-\s]?)?[6-9]\d{9}', window)
            if pm:
                phone = pm.group(0)
        leads.append({
            "url": "", "title": c["title"], "location": f"{city}, India",
            "phone": phone, "industry": industry, "source": "indiamart",
        })
    return leads


def probe(keyword: str = "manufacturers", city: str = "Delhi") -> dict:
    """Diagnostic: fetch one query and report what the site actually returned, so we
    can tell a block/captcha from a markup change without guessing."""
    if requests is None:
        return {"ok": False, "error": "requests not installed"}
    url = _SEARCH.format(kw=quote_plus(keyword), city=quote_plus(city))
    try:
        r = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "en-IN,en;q=0.9"},
                         timeout=20)
        body = r.text or ""
        low = body.lower()
        parsed = _parse(body, city, keyword)
        return {
            "ok": True, "url": url, "http_status": r.status_code,
            "content_length": len(body),
            "looks_blocked": any(s in low for s in ("captcha", "access denied", "are you a human",
                                                    "unusual traffic", "/recaptcha", "cf-browser-verification")),
            "has_companyname_key": '"companyname"' in low,
            "has_jsonld": "application/ld+json" in low,
            "parsed_count": len(parsed),
            "snippet": body[:1200],
        }
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)}


def search_one(keyword: str, city: str, industry: str) -> list[dict]:
    # IndiaMART is a JS SPA — listings only exist after render. Prefer the headless
    # browser; fall back to a static parse (works only if markup is ever server-side).
    from tools.sources import headless
    if headless.available():
        rows = headless.fetch_indiamart(keyword, city, industry)
        if rows:
            return rows
    if requests is None:
        return []
    url = _SEARCH.format(kw=quote_plus(keyword), city=quote_plus(city))
    try:
        r = requests.get(url, headers={"User-Agent": _UA, "Accept-Language": "en-IN,en;q=0.9"},
                         timeout=20)
        if r.status_code != 200 or not r.text:
            logger.debug(f"[indiamart] {keyword}@{city} -> HTTP {r.status_code}")
            return []
        return _parse(r.text, city, industry)
    except Exception as e:
        logger.debug(f"[indiamart] {keyword}@{city} failed: {e}")
        return []


# Generic source interface (web_search multi-source).
def search_companies(keyword: str, region: Optional[str] = None, max_results: int = 50) -> list[dict]:
    city = region or "India"
    ind = CATEGORIES.get(keyword.lower(), keyword)
    return search_one(keyword, city, ind)[:max_results]


def harvest_to_warehouse(cities: Optional[list[str]] = None,
                         categories: Optional[list[str]] = None,
                         delay: float = 1.0) -> dict:
    """Sweep (category x city), banking listings as enriched leads. Polite delay
    between requests to avoid rate-limiting. Returns a summary."""
    if not _lock.acquire(blocking=False):
        return {"status": "busy", **status()}
    try:
        from tools.sources import _directory_common as dc
        cats = categories or list(CATEGORIES.keys())
        cl = cities or DEFAULT_CITIES
        _state.update(running=True, queries_done=0, queries_total=len(cats) * len(cl), added=0)
        for city in cl:
            for kw in cats:
                ind = CATEGORIES.get(kw.lower(), kw)
                cands = search_one(kw, city, ind)
                _state["added"] += dc.bank(cands, region=city, source_label="IndiaMART", tag_source="im")
                _state["queries_done"] += 1
                if delay:
                    time.sleep(delay)
        from core import warehouse
        logger.info(f"[indiamart] banked {_state['added']} leads")
        return {"status": "ok", "added": _state["added"], "pool": warehouse.stats()}
    except Exception as e:
        logger.warning(f"[indiamart] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _state["running"] = False
        _lock.release()
