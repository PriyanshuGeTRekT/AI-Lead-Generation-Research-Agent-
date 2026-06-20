"""
Accurate Contact + Employee Resolver
------------------------------------
Fixes the production tool's core defect: phones/employees were regex-scraped from
Google *snippets* of aggregator listing pages, so the number rarely belonged to
the named company (and landlines — hospitals/BPOs — were dropped entirely).

Here every must-be-correct field is resolved from the single most authoritative
source, ATTRIBUTED to one company:

  phone    → Google Places phoneNumber (verified, one business, keeps landlines)
             → fallback: the company's OWN /contact page (tel: links first)
             A number is accepted only if it came from the company's Places record
             or its own domain — never from a shared aggregator snippet.
             Landlines are kept; STD code is checked against the company's city.
  employees→ LinkedIn size BAND from the company's own linkedin.com/company page
             (e.g. "51-200 employees") — enough for the >50 / not-too-big gate.
  website  → official domain (Places, else firmographic search, aggregators filtered)

Everything is fail-safe and cheap (≤ a couple of Serper calls + one light fetch).
"""
import re
import json
from urllib.parse import urljoin, urlparse
from typing import Optional

import requests
from loguru import logger

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LeadGenBot/1.0)"}
_AGG = ("justdial", "indiamart", "sulekha", "linkedin", "facebook", "wikipedia",
        "crunchbase", "zaubacorp", "tofler", "glassdoor", "indeed", "naukri")

# Major Indian STD codes → city (landline area-code validation).
_STD_CITY = {
    "11": "delhi", "22": "mumbai", "33": "kolkata", "44": "chennai", "20": "pune",
    "40": "hyderabad", "80": "bengaluru", "79": "ahmedabad", "141": "jaipur",
    "522": "lucknow", "161": "ludhiana", "731": "indore", "422": "coimbatore",
    "484": "kochi", "712": "nagpur", "512": "kanpur", "532": "prayagraj",
    "183": "amritsar", "172": "chandigarh", "271": "surat", "265": "vadodara",
    "281": "rajkot", "452": "madurai", "413": "puducherry", "674": "bhubaneswar",
    "612": "patna", "751": "gwalior", "755": "bhopal", "120": "noida",
    "124": "gurugram", "0120": "noida", "0124": "gurugram",
}


# ── Phone helpers ─────────────────────────────────────────────────────────────
def _normalize_phone(raw: str, trusted: bool = False) -> Optional[dict]:
    """Return {number, type, std} for a valid Indian number, else None.

    Keeps BOTH mobiles and landlines (the old tool wrongly dropped landlines).
    `trusted=True` (Google Places — one verified business) accepts any plausibly
    formed 10-digit landline. `trusted=False` (scraped off a web page, where bare
    digit runs are often CINs / GSTINs / PINs / dates) is STRICT: it accepts only
    a valid mobile, a KNOWN-STD landline, or a toll-free number — so junk like
    `3921568627` or `13038930552` is rejected."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("91") and len(digits) > 10:
        digits = digits[2:]
    digits = digits.lstrip("0")
    if not digits:
        return None
    # Toll-free (1800 / 1860 + 6-7 digits) — common for B2B / support lines.
    if re.match(r"^(?:1800|1860)\d{6,7}$", digits):
        return {"number": digits, "type": "tollfree", "std": None}
    # Mobile: exactly 10 digits starting 6-9.
    if len(digits) == 10 and digits[0] in "6789":
        return {"number": digits, "type": "mobile", "std": None}
    # Landline: STD (2-4 digits) + subscriber (6-8 digits), 10-11 total.
    if 10 <= len(digits) <= 11 and digits[0] in "123456789":
        for code_len in (4, 3, 2):
            std = digits[:code_len]
            if std in _STD_CITY and 6 <= len(digits) - code_len <= 8:
                return {"number": digits, "type": "landline", "std": std}
        # Unknown STD: accept ONLY for trusted (Places) sources, and never for
        # year/date-looking runs. Scraped unknown-STD numbers are rejected.
        if trusted and not re.match(r"^(?:19|20)\d{6,9}$", digits):
            return {"number": digits, "type": "landline", "std": None}
    # Anything else (8-9 digit fragments, IDs, unknown-STD scraped runs) is NOT a phone.
    return None


def _phone_matches_city(norm: dict, city: Optional[str]) -> bool:
    """A landline's STD code should match the company's city; mobiles always pass."""
    if not norm or norm["type"] == "mobile" or not norm.get("std") or not city:
        return True
    return _STD_CITY.get(norm["std"], "") in city.lower()


# ── Serper Places (primary, verified, single-business) ────────────────────────
def _places(query: str, location: Optional[str], key: str) -> list[dict]:
    try:
        payload = {"q": query}
        if location:
            payload["location"] = location
        r = requests.post(
            "https://google.serper.dev/places",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=12,
        )
        return r.json().get("places", []) or []
    except Exception as e:
        logger.debug(f"[contact] places error: {e}")
        return []


def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _best_place(places: list[dict], company_name: str) -> Optional[dict]:
    """Pick the Places result whose title best matches the company name."""
    target = _norm_name(company_name)
    if not target:
        return places[0] if places else None
    best, best_score = None, 0.0
    for p in places:
        t = _norm_name(p.get("title", ""))
        if not t:
            continue
        if t == target:
            return p
        # containment / overlap score
        score = 0.0
        if target in t or t in target:
            score = 0.8
        else:
            common = sum(1 for w in set(company_name.lower().split()) if w in p.get("title", "").lower())
            score = common / max(1, len(company_name.split()))
        if score > best_score:
            best, best_score = p, score
    return best if best_score >= 0.5 else None


# ── Own-site contact scrape (authoritative fallback) ──────────────────────────
def _scrape_site_phone(website: str, city: Optional[str]) -> Optional[dict]:
    if not website:
        return None
    base = website if "://" in website else "http://" + website
    pages = [base]
    for path in ("/contact", "/contact-us", "/contactus", "/reach-us", "/about"):
        pages.append(urljoin(base.rstrip("/") + "/", path.lstrip("/")))
    for url in pages:
        try:
            html = requests.get(url, headers=_HEADERS, timeout=7).text
        except Exception:
            continue
        # tel: links are the most authoritative.
        tels = re.findall(r'tel:\+?([\d\s\-()]{7,16})', html)
        # Visible numbers ONLY in a phone context — well-formed Indian numbers, not
        # bare digit runs (which are usually CIN/GSTIN/PIN/registration numbers).
        ctx = [
            # +91 mobile / landline with separators
            r'\+91[\s\-]?\d{2,5}[\s\-]?\d{3,4}[\s\-]?\d{3,4}',
            # toll-free 1800 / 1860 with separators
            r'\b1(?:800|860)[\s\-]?\d{2,4}[\s\-]?\d{3,4}\b',
            # landline (0XX)-XXXXXXX or 0XX-XXXXXXX with separators
            r'\b0\d{2,4}[\s\-]\d{6,8}\b',
            # bare 10-digit mobile (word-bounded so it isn't part of a longer run)
            r'(?<!\d)[6-9]\d{9}(?!\d)',
        ]
        text_nums = []
        for pat in ctx:
            text_nums += re.findall(pat, html)
        # tel: links are trusted; visible numbers must pass strict validation.
        for cand in tels:
            norm = _normalize_phone(cand, trusted=True)
            if norm and _phone_matches_city(norm, city):
                return {**norm, "source": "company_website"}
        for cand in text_nums:
            norm = _normalize_phone(cand, trusted=False)
            if norm and _phone_matches_city(norm, city):
                return {**norm, "source": "company_website"}
    return None


# ── LinkedIn employee band ────────────────────────────────────────────────────
_BAND_RE = re.compile(r"([\d,]+)\s*(?:-|–|to)\s*([\d,]+)\s*employees", re.I)
_PLUS_RE = re.compile(r"([\d,]+)\+?\s*employees", re.I)


def _employee_band(company_name: str, key: str) -> Optional[dict]:
    """Parse the LinkedIn size band from the company's OWN linkedin page snippet."""
    try:
        r = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": key, "Content-Type": "application/json"},
            data=json.dumps({"q": f'site:linkedin.com/company "{company_name}" employees', "gl": "in"}),
            timeout=12,
        )
        organic = r.json().get("organic", []) or []
    except Exception:
        return None
    target = _norm_name(company_name)
    for item in organic[:5]:
        title = item.get("title", "")
        if target and target not in _norm_name(title):
            continue  # ensure it's THIS company's page, not a "top companies" list
        text = f"{title} {item.get('snippet', '')}"
        m = _BAND_RE.search(text)
        if m:
            lo = int(m.group(1).replace(",", ""))
            hi = int(m.group(2).replace(",", ""))
            return {"band": f"{lo:,}-{hi:,} employees", "min": lo, "max": hi, "source": "linkedin"}
        m = _PLUS_RE.search(text)
        if m:
            lo = int(m.group(1).replace(",", ""))
            return {"band": f"{lo:,}+ employees", "min": lo, "max": None, "source": "linkedin"}
    return None


def in_target_band(emp: Optional[dict], floor: int = 50, ceil: int = 1000) -> Optional[bool]:
    """True if headcount is in [floor, ceil], False if clearly outside, None if unknown.
    Targets companies big enough to need an HRMS but not so big they already have one."""
    if not emp:
        return None
    lo, hi = emp.get("min"), emp.get("max")
    if hi is not None and hi < floor:
        return False
    if lo is not None and lo > ceil:
        return False
    return True


# ── Public entry point ────────────────────────────────────────────────────────
def resolve_contact(
    company_name: str,
    website: Optional[str] = None,
    city: Optional[str] = None,
    pincode: Optional[str] = None,
    serper_key: Optional[str] = None,
) -> dict:
    """Resolve verified phone + employee band + website for ONE company.
    Returns a dict; missing fields are None. Never raises."""
    out: dict = {
        "phone": None, "phone_type": None, "phone_source": None,
        "website": website, "address": None,
        "employee_band": None, "employee_min": None, "employee_max": None,
        "employee_source": None, "contact_confidence": "low",
    }
    location = f"{pincode}, India" if pincode else (city or "India")

    # 1) Google Places — verified, single business, attributed by name match
    if serper_key:
        q = f"{company_name} {city or pincode or ''}".strip()
        place = _best_place(_places(q, location, serper_key), company_name)
        if place:
            out["address"] = place.get("address")
            if place.get("website") and not any(a in place["website"] for a in _AGG):
                out["website"] = place["website"]
            norm = _normalize_phone(place.get("phoneNumber") or "", trusted=True)
            if norm and _phone_matches_city(norm, city):
                out.update(phone=norm["number"], phone_type=norm["type"], phone_source="google_places")
                out["contact_confidence"] = "high"

    # 2) Fallback: scrape the company's own contact page
    if not out["phone"] and out["website"] and not any(a in (out["website"] or "") for a in _AGG):
        site_phone = _scrape_site_phone(out["website"], city)
        if site_phone:
            out.update(phone=site_phone["number"], phone_type=site_phone["type"], phone_source="company_website")
            out["contact_confidence"] = "medium"

    # 3) Employee band from LinkedIn (company's own page)
    if serper_key:
        emp = _employee_band(company_name, serper_key)
        if emp:
            out.update(
                employee_band=emp["band"], employee_min=emp["min"],
                employee_max=emp["max"], employee_source=emp["source"],
            )

    logger.info(
        f"[contact] {company_name}: phone={out['phone']}({out['phone_type']}/{out['phone_source']}) "
        f"emp={out['employee_band']}"
    )
    return out


def domain_from_url(url: str) -> str:
    s = (url or "").strip()
    if not s:
        return ""
    if "://" not in s:
        s = "http://" + s
    host = urlparse(s).netloc.lower()
    return host[4:] if host.startswith("www.") else host
