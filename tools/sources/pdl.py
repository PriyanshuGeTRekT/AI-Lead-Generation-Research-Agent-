"""
People Data Labs (PDL) source — bulk company discovery + decision-maker enrichment.
------------------------------------------------------------------------------------
PDL (api.peopledatalabs.com) has a huge global company + person dataset. Two uses:
  • company_search(region, industry, size) → bulk-discover Indian companies by state +
    industry + headcount (name, website, size, location, industry, linkedin)
  • find_people(company, titles)           → the decision-maker (HR head/founder) with
    title + work email where available

Together: discover companies in Delhi/Maharashtra (the states the MCA mirror lacks)
AND attach the right person to pitch — contact-rich, unlike the registry data.

Auth header: `X-Api-Key: <pdl_api_key>` (set in Settings). v5 API. Fail-safe [].
Needs network to api.peopledatalabs.com (blocked from the dev sandbox; runs on the
user's machine with their key).
"""
from typing import Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

from loguru import logger

_BASE = "https://api.peopledatalabs.com/v5"

DECISION_TITLES = ["human resources", "hr", "chro", "founder", "co-founder", "ceo",
                   "managing director", "director", "proprietor", "partner", "operations"]


def _key() -> str:
    from core import runtime_config as rc
    return (rc.get("pdl_api_key") or "").strip()


def configured() -> bool:
    return bool(_key())


def _headers(key: str) -> dict:
    return {"X-Api-Key": key, "Content-Type": "application/json"}


def company_search(region: str = "", industry: str = "", min_size: int = 11,
                   limit: int = 100) -> list[dict]:
    """Bulk-discover companies in India (optionally a state/industry) via PDL company
    search. Returns candidate dicts {url,title,location,phone,industry,source}."""
    key = _key()
    if requests is None or not key:
        return []
    must = [{"term": {"location.country": "india"}}]
    if region:
        must.append({"match": {"location.region": region.lower()}})
    if industry:
        must.append({"match": {"industry": industry.lower()}})
    # employee_count gte filter to skip micro one-person shells.
    must.append({"range": {"employee_count": {"gte": min_size}}})
    body = {"query": {"bool": {"must": must}}, "size": min(limit, 100), "dataset": "all"}
    try:
        r = requests.post(f"{_BASE}/company/search", json=body, headers=_headers(key), timeout=40)
        if r.status_code != 200:
            logger.debug(f"[pdl] company_search -> HTTP {r.status_code}: {r.text[:160]}")
            return []
        recs = r.json().get("data", []) or []
    except Exception as e:
        logger.debug(f"[pdl] company_search failed: {e}")
        return []
    out = []
    for c in recs:
        name = c.get("display_name") or c.get("name") or ""
        if not name:
            continue
        loc = c.get("location") or {}
        locality = loc.get("locality") or loc.get("region") or ""
        out.append({
            "url": (c.get("website") or "").strip(),
            "title": name[:200],
            "location": f"{locality.title()}, India" if locality else (region + ", India" if region else "India"),
            "phone": "",  # PDL company records carry no phone; enrich later
            "industry": c.get("industry") or industry or "business",
            "employee_count": c.get("employee_count"),
            "linkedin": c.get("linkedin_url") or "",
            "source": "pdl",
        })
    return out


def find_people(company: str, titles: Optional[list[str]] = None, limit: int = 5) -> list[dict]:
    """Find decision-makers at a company → [{name, title, email, linkedin}]."""
    key = _key()
    if requests is None or not key or not company:
        return []
    title_terms = titles or DECISION_TITLES
    body = {
        "query": {"bool": {
            "must": [{"match": {"job_company_name": company}}],
            "should": [{"match": {"job_title_role": t}} for t in title_terms]
                      + [{"match_phrase": {"job_title": t}} for t in title_terms],
            "minimum_should_match": 1,
        }},
        "size": min(limit, 10),
        "dataset": "all",
    }
    try:
        r = requests.post(f"{_BASE}/person/search", json=body, headers=_headers(key), timeout=40)
        if r.status_code != 200:
            logger.debug(f"[pdl] person_search {company} -> HTTP {r.status_code}")
            return []
        recs = r.json().get("data", []) or []
    except Exception as e:
        logger.debug(f"[pdl] person_search {company} failed: {e}")
        return []
    out = []
    for p in recs[:limit]:
        email = p.get("work_email") or (p.get("emails") or [{}])[0].get("address") if p.get("emails") else p.get("work_email")
        out.append({
            "name": p.get("full_name") or "",
            "title": p.get("job_title") or "",
            "email": email or "",
            "linkedin": p.get("linkedin_url") or "",
        })
    return [o for o in out if o["name"]]
