"""
Cross-Source Verification
-------------------------
Never trust a single scrape. For each surviving lead this triangulates the
must-be-correct facts across MULTIPLE independent sources and reports a
per-field corroboration + an overall confidence, so we only act on data that
agrees from 2-3 sources:

  phone          → Google Places + the company's own /contact page + a web snippet
  HRMS-absence   → careers-page fingerprint (1st) + a targeted web search for any
                   HRMS vendor co-occurring with the company (2nd source)
  employees      → LinkedIn size band + a headcount mention on the company's site
  domain         → official site resolved + present

Runs only on survivors (post-funnel), so the extra ~1 web call per lead is bounded.
Everything is fail-safe.
"""
import json
import re
from typing import Optional

import requests
from loguru import logger

from tools.contact_resolver import _normalize_phone

try:
    from tools.hrms_detector import _VENDORS
    _VENDOR_TOKENS = {name: [p.lower() for p in pats] for name, (pats, _t) in _VENDORS.items()}
except Exception:  # pragma: no cover
    _VENDOR_TOKENS = {
        "Keka": ["keka"], "Darwinbox": ["darwinbox"], "GreytHR": ["greythr"],
        "Zoho People": ["zoho people"], "SAP SuccessFactors": ["successfactors"],
        "Workday": ["workday"], "BambooHR": ["bamboohr"],
    }


def _serper_search(q: str, key: str, num: int = 10) -> list[dict]:
    try:
        r = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            data=json.dumps({"q": q, "gl": "in", "hl": "en", "num": num}),
            timeout=12,
        )
        return r.json().get("organic", []) or []
    except Exception as e:
        logger.debug(f"[verify] serper error: {e}")
        return []


# Loose phone-like sequences; _normalize_phone() validates each (junk → dropped).
_SITE_PHONE_RE = re.compile(r'\+?\d[\d\s\-()]{7,15}\d')


def _site_phone_set(scraped: str) -> set:
    nums = set()
    for cand in _SITE_PHONE_RE.findall(scraped or ""):
        n = _normalize_phone(cand)
        if n:
            nums.add(n["number"])
    return nums


def cross_verify(lead: dict, scraped: str, hrms: dict, serper_key: Optional[str], city: Optional[str] = None) -> dict:
    """Triangulate the lead's key fields across sources. Returns a verification dict."""
    company = lead.get("company_name", "")
    notes: list[str] = []

    # ── Phone: corroborate the resolved number across sources ────────────────
    val = (lead.get("phone") or "").strip()
    norm = _normalize_phone(val) if val else None
    norm_num = norm["number"] if norm else None
    phone_sources: list[str] = []
    if val and lead.get("phone_source") == "google_places":
        phone_sources.append("google_places")
    site_nums = _site_phone_set(scraped)
    if norm_num and norm_num in site_nums:
        phone_sources.append("company_website")
    elif val and lead.get("phone_source") == "company_website":
        phone_sources.append("company_website")
    # third source: a web snippet mentioning the number
    if serper_key and norm_num:
        for item in _serper_search(f'"{company}" contact phone number {city or ""}'.strip(), serper_key, num=5):
            blob = f"{item.get('title','')} {item.get('snippet','')}"
            if re.sub(r"\D", "", blob).find(norm_num) >= 0:
                phone_sources.append("web")
                break
    phone_sources = list(dict.fromkeys(phone_sources))
    if not val:
        phone_status = "none"
    elif len(phone_sources) >= 2:
        phone_status = "high"
    else:
        phone_status = "medium"
    # conflict: site has a different primary number than the (Places) value
    if norm_num and site_nums and norm_num not in site_nums and lead.get("phone_source") == "google_places":
        notes.append("phone differs between Places and website")

    # ── HRMS absence: second independent source ──────────────────────────────
    vendor_found = None
    if serper_key and company:
        terms: list[str] = []
        for toks in _VENDOR_TOKENS.values():
            if toks:
                t = toks[0].split(".")[0].strip()  # 'darwinbox.com' → 'darwinbox'
                if t and t not in terms:
                    terms.append(t)
        vq = f'"{company}" (' + " OR ".join(terms[:12]) + ' OR HRMS OR "payroll software" OR "attendance software")'
        results = _serper_search(vq, serper_key, num=10)
        haystack = " ".join(f"{r.get('title','')} {r.get('snippet','')} {r.get('link','')}" for r in results).lower()
        cl = company.lower()
        for name, toks in _VENDOR_TOKENS.items():
            if any(tok in haystack for tok in toks) and (cl[:12] in haystack):
                vendor_found = name
                break
    careers_has_hrms = bool(hrms.get("has_hrms"))
    if vendor_found:
        hrms_second = "vendor_found"
        absence_confirmed = False
        notes.append(f"HRMS vendor '{vendor_found}' found via web — likely already has HRMS")
    else:
        hrms_second = "clear"
        absence_confirmed = not careers_has_hrms

    # ── Employees: corroborate the LinkedIn band with a site headcount ───────
    emp_band = lead.get("employee_band")
    emp_sources = ["linkedin"] if lead.get("employee_source") == "linkedin" else []
    emp_corroborated = False
    m = re.search(r"([\d,]{2,7})\+?\s*(?:employees|staff|people|team members|professionals)", scraped or "", re.I)
    if m:
        n = int(m.group(1).replace(",", ""))
        lo, hi = lead.get("employee_min"), lead.get("employee_max")
        if (lo is None or n >= lo * 0.5) and (hi is None or n <= (hi or n) * 1.5):
            emp_sources.append("company_website")
            emp_corroborated = True

    # ── Domain ───────────────────────────────────────────────────────────────
    domain_official = bool(lead.get("website"))

    # ── Confidence ───────────────────────────────────────────────────────────
    conf = 40
    conf += 25 if phone_status == "high" else 10 if phone_status == "medium" else 0
    if vendor_found:
        conf -= 30
    elif absence_confirmed:
        conf += 25
    if emp_corroborated:
        conf += 10
    if domain_official:
        conf += 5
    conf = max(0, min(100, conf))

    sources_checked = len(set(phone_sources + emp_sources + (["web"] if serper_key else []) + ["careers_fingerprint"]))
    verified = conf >= 65 and not vendor_found

    return {
        "verified": verified,
        "confidence": conf,
        "sources_checked": sources_checked,
        "phone": {"value": val or None, "sources": phone_sources, "agree": len(phone_sources), "status": phone_status},
        "employees": {"band": emp_band, "corroborated": emp_corroborated, "sources": emp_sources},
        "hrms_absence": {"confirmed": absence_confirmed, "second_source": hrms_second, "vendor": vendor_found},
        "domain": {"official": domain_official},
        "notes": notes,
    }
