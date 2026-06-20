"""
Crustdata source — company enrichment + decision-maker (people) search.
-----------------------------------------------------------------------
Crustdata (api.crustdata.com) is a real-time B2B data API: enrich a company by
domain, and — crucially for us — find the RIGHT PERSON to pitch (HR head / founder /
director) at a company, with title + LinkedIn + (where available) email. This is the
fix for "half-baked leads with no decision-maker".

Two capabilities:
  • enrich_company(domain)          → firmographics (headcount, industry, HQ, website)
  • find_people(company, titles)    → decision-makers {name, title, email, linkedin}

Auth: `Authorization: Token <crustdata_api_key>` (set in Settings). Fail-safe [].
Needs network to api.crustdata.com (blocked from the dev sandbox; runs on the user's
machine with their key).
"""
from typing import Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

from loguru import logger

_BASE = "https://api.crustdata.com"

# Titles that identify the HRMS buyer / decision-maker at an Indian SME.
DECISION_TITLES = [
    "HR Head", "Head of HR", "HR Manager", "Human Resources", "CHRO", "VP HR",
    "Director HR", "Founder", "Co-Founder", "CEO", "Managing Director", "Director",
    "Proprietor", "Partner", "Operations Head", "Admin Head",
]


def _token() -> str:
    from core import runtime_config as rc
    return (rc.get("crustdata_api_key") or "").strip()


def _headers(token: str) -> dict:
    return {"Authorization": f"Token {token}", "Content-Type": "application/json", "Accept": "application/json"}


def enrich_company(domain: str) -> dict:
    """Firmographics for one company domain (headcount, industry, HQ, website)."""
    token = _token()
    if requests is None or not token or not domain:
        return {}
    try:
        r = requests.get(f"{_BASE}/screener/company",
                         params={"company_domain": domain},
                         headers=_headers(token), timeout=25)
        if r.status_code != 200:
            logger.debug(f"[crustdata] company {domain} -> HTTP {r.status_code}")
            return {}
        data = r.json()
        rec = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
        return {
            "company_name": rec.get("company_name") or rec.get("name") or "",
            "website": rec.get("company_website") or rec.get("website") or domain,
            "industry": rec.get("linkedin_industry") or rec.get("industry") or "",
            "employee_count": rec.get("headcount") or rec.get("estimated_num_employees")
                              or rec.get("linkedin_headcount") or None,
            "location": rec.get("hq_location") or rec.get("headquarters") or "",
            "linkedin": rec.get("linkedin_profile_url") or rec.get("linkedin_url") or "",
        }
    except Exception as e:
        logger.debug(f"[crustdata] enrich {domain} failed: {e}")
        return {}


def find_people(company: str, titles: Optional[list[str]] = None, limit: int = 5) -> list[dict]:
    """Find decision-makers at a company → [{name, title, email, linkedin}]."""
    token = _token()
    if requests is None or not token or not company:
        return []
    body = {
        "filters": [
            {"filter_type": "CURRENT_COMPANY", "type": "in", "value": [company]},
            {"filter_type": "CURRENT_TITLE", "type": "in", "value": titles or DECISION_TITLES},
        ],
        "page": 1,
    }
    try:
        r = requests.post(f"{_BASE}/screener/person/search", json=body,
                          headers=_headers(token), timeout=30)
        if r.status_code != 200:
            logger.debug(f"[crustdata] people {company} -> HTTP {r.status_code}")
            return []
        data = r.json()
        rows = data.get("profiles") or data.get("persons") or data.get("data") or (data if isinstance(data, list) else [])
        out = []
        for p in rows[:limit]:
            if not isinstance(p, dict):
                continue
            emails = p.get("business_email") or p.get("email") or (p.get("emails") or [None])[0]
            out.append({
                "name": p.get("name") or p.get("full_name") or "",
                "title": p.get("title") or p.get("current_title") or "",
                "email": emails if isinstance(emails, str) else "",
                "linkedin": p.get("linkedin_profile_url") or p.get("linkedin_url") or "",
            })
        return [o for o in out if o["name"]]
    except Exception as e:
        logger.debug(f"[crustdata] find_people {company} failed: {e}")
        return []


def configured() -> bool:
    return bool(_token())
