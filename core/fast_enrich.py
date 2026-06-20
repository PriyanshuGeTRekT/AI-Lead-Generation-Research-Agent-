"""
Fast Enrich — high-throughput raw → quality lead conversion
-----------------------------------------------------------
The funnel's full per-candidate path makes several network calls (incl. dead-Serper
contact lookups). For LAKHS of leads that's too slow. This lean path does ONE HTTP
fetch per domain and extracts everything from that single page:
  • company name  (<title> / og:site_name)
  • mobile number (tel: / +91 / bare 10-digit, mobile-only)
  • industry guess (keyword map over the page)
  • HRMS absence  (reuse detect_hrms on the prefetched HTML — the killer "likely to
                   buy" signal: no HR-tech footprint = strong prospect)
then runs the ICP scorer (process_lead). Massively parallel (default 80 workers,
all I/O-bound) so tens of thousands convert per run. Dead/parked domains are skipped.
Fail-safe throughout.
"""
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from loguru import logger

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; RazorLeadBot/1.0)"}
_lock = threading.Lock()
_state = {"running": False, "done": 0, "total": 0, "converted": 0, "dead": 0}

_MOBILE_RE = re.compile(r"(?<!\d)(?:\+?91[\s\-]?)?([6-9]\d{9})(?!\d)")
_TITLE_RE = re.compile(r"<title[^>]*>([^<]{2,120})</title>", re.I)
_OG_RE = re.compile(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']{2,80})', re.I)

# Industry keyword map (first hit wins) — coarse but fast.
_IND_KW = [
    ("hospital", ["hospital", "multispeciality", "multi-speciality", "nursing home"]),
    ("healthcare", ["clinic", "diagnostic", "healthcare", "medical center", "pathology"]),
    ("pharmaceutical", ["pharma", "pharmaceutical", "drugs ", "lifesciences", "life sciences"]),
    ("manufacturing", ["manufacturer", "manufacturing", "industries", "factory", "engineering works", "pvt. ltd"]),
    ("textile", ["textile", "garment", "apparel", "fabrics", "spinning mill"]),
    ("logistics", ["logistics", "freight", "courier", "supply chain", "warehousing", "transport"]),
    ("IT services", ["software", "it services", "technologies", "infotech", "saas", "web development", "it solutions"]),
    ("education", ["school", "college", "university", "institute", "academy", "coaching", "education"]),
    ("hotel", ["hotel", "resort", "hospitality", "banquet"]),
    ("real estate", ["real estate", "builders", "developers", "properties", "realty"]),
    ("construction", ["construction", "infrastructure", "contractors", "engineers & contractors"]),
    ("automotive", ["automobile", "automotive", "motors", "auto parts", "auto components"]),
    ("retail", ["retail", "supermarket", "showroom", "store", "mart"]),
    ("financial services", ["finance", "nbfc", "loans", "investment", "capital", "insurance"]),
    ("consulting", ["consulting", "consultancy", "advisory", "consultants"]),
    ("food processing", ["food", "dairy", "beverages", "foods", "agro"]),
    ("chemical", ["chemical", "chemicals", "polymers", "plastics", "coatings"]),
    
]


def status() -> dict:
    return dict(_state)


def is_running() -> bool:
    return _state["running"]


def _guess_industry(text: str, fallback: str = "business") -> str:
    t = text.lower()
    for ind, kws in _IND_KW:
        if any(k in t for k in kws):
            return ind
    return fallback or "business"


def _clean_name(raw: str, domain: str) -> str:
    n = re.sub(r"\s*[\|\-–—:].*$", "", raw or "").strip()  # drop tagline after separator
    n = re.sub(r"\s+", " ", n)
    if len(n) < 2 or len(n) > 80 or n.lower() in ("home", "welcome", "index"):
        return domain.split(".")[0].replace("-", " ").title()
    return n


def _enrich_one(cand: dict) -> dict | None:
    import requests
    from tools.hrms_detector import detect_hrms
    from core.lead_processor import process_lead
    url = cand.get("url") or ""
    if not url:
        return None
    try:
        # Short timeout: dead/parked domains shouldn't stall a worker — fail fast and
        # move on. (connect 4s, read 5s.)
        r = requests.get(url, headers=_HEADERS, timeout=(4, 5), allow_redirects=True)
        html = r.text if r.status_code < 400 else ""
    except Exception:
        html = ""
    if not html or len(html) < 200:
        return None  # dead / parked / unreachable — not a usable lead
    dom = re.sub(r"^https?://", "", url).split("/")[0].replace("www.", "")
    m = _OG_RE.search(html) or _TITLE_RE.search(html)
    name = _clean_name(m.group(1) if m else "", dom)
    mob = ""
    mm = _MOBILE_RE.search(re.sub(r"<[^>]+>", " ", html[:20000]))
    if mm:
        mob = mm.group(1)
    industry = cand.get("industry") or _guess_industry(html[:30000], "business")
    hrms = detect_hrms(url, prefetched_html=html, company_name=name)
    lead = {
        "company_name": name,
        "website": url,
        "industry": industry,
        "location": cand.get("location") or "India",
        "phone": mob,
        "phone_type": "mobile" if mob else None,
        "phone_source": "company_website" if mob else None,
        "contact_emails": [],
        "source": cand.get("source") or "web",
        "hrms": {"has_hrms": hrms.get("has_hrms", False),
                 "no_hrms_confidence": hrms.get("no_hrms_confidence", 0.5),
                 "vendors": hrms.get("detected_vendors", []),
                 "pitch_angle": hrms.get("pitch_angle", "")},
    }
    try:
        lead = process_lead(lead)
    except Exception:
        pass
    # Companies that ALREADY run an HRMS are not prospects — drop confidence so
    # they tier low (we sell to the ones WITHOUT one).
    if lead.get("hrms", {}).get("has_hrms"):
        lead["icp_tier"] = "Cold"
        lead["qualification_score"] = min(lead.get("qualification_score", 5), 3.0)
    return lead


def fast_enrich(batch: int = 1000, workers: int = 80) -> dict:
    """Convert up to `batch` raw domains into quality leads, ~80 in flight at once."""
    if not _lock.acquire(blocking=False):
        return {"status": "busy", **status()}
    try:
        from core import warehouse
        cands = warehouse.take_raw(limit=batch)
        if not cands:
            return {"status": "empty", "message": "No raw leads to enrich."}
        _state.update(running=True, done=0, total=len(cands), converted=0, dead=0)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_enrich_one, c): c for c in cands}
            for fut in as_completed(futs):
                try:
                    lead = fut.result()
                except Exception:
                    lead = None
                if lead and (lead.get("website") or lead.get("phone")):
                    try:
                        warehouse.save_enriched(lead, region=lead.get("state") or "India")
                        _state["converted"] += 1
                    except Exception:
                        pass
                else:
                    _state["dead"] += 1
                    # Mark dead domains excluded so we don't re-try them forever.
                    try:
                        warehouse.mark_excluded(futs[fut].get("url", ""), "unreachable/parked")
                    except Exception:
                        pass
                _state["done"] += 1
        logger.info(f"[fast_enrich] {_state['converted']} converted, {_state['dead']} dead of {len(cands)}")
        return {"status": "ok", "converted": _state["converted"], "dead": _state["dead"],
                "pool": warehouse.stats()}
    except Exception as e:
        logger.warning(f"[fast_enrich] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _state["running"] = False
        _lock.release()
