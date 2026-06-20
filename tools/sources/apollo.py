"""
Apollo.io source adapter (plug-in)
----------------------------------
Apollo is the single strongest lever for our ICP because it natively filters
companies that **do NOT use** a given technology — i.e. "no HRMS installed" —
plus verified firmographics + contacts. This adapter activates the moment an
`apollo_api_key` is set in Settings; until then it returns [] and the pipeline
falls back to Serper/Places discovery.

Returns candidate dicts compatible with the research agent:
  {url, title, source, location, employee_min, employee_max, dm_name, dm_title,
   dm_linkedin, dm_email}

NOTE: Apollo's exact request/response fields vary by plan. The mapping below is
the documented org-search shape; if your plan differs, only `_to_candidate` and
the payload keys need adjustment. Everything is fail-safe.
"""
import json
from typing import Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

# Apollo technology UIDs for HRMS/payroll vendors → "currently NOT using any of".
_HRMS_TECH_UIDS = [
    "keka", "darwinbox", "greythr", "zoho_people", "workday", "sap_successfactors",
    "bamboohr", "rippling", "gusto", "adp", "ukg", "ceridian", "paycom",
    "hibob", "personio", "zenefits", "namely", "peoplestrong",
]

_SIZE_RANGES = ["51,100", "101,200", "201,500", "501,1000"]  # SME band


def _to_candidate(org: dict) -> Optional[dict]:
    website = org.get("website_url") or org.get("primary_domain") or ""
    name = org.get("name") or ""
    if not name:
        return None
    n = org.get("estimated_num_employees")
    return {
        "url": website if website.startswith("http") else (f"https://{website}" if website else ""),
        "title": name,
        "source": "apollo",
        "location": ", ".join(filter(None, [org.get("city"), org.get("state"), org.get("country")])),
        "employee_min": n,
        "employee_max": n,
    }


def configured() -> bool:
    try:
        from core import runtime_config as rc
        return bool((rc.get("apollo_api_key") or "").strip())
    except Exception:
        return False


# Titles that identify the HRMS decision-maker at an Indian SME.
DM_TITLES = ["HR Head", "Head of HR", "HR Manager", "CHRO", "VP HR", "Director HR",
             "Human Resources", "Founder", "Co-Founder", "CEO", "Managing Director",
             "Director", "Proprietor", "Partner"]


def find_people(company: str, domain: str = "", titles: Optional[list[str]] = None,
                limit: int = 3, reveal_phone: bool = True) -> list[dict]:
    """Find the decision-maker(s) at a company via Apollo People Search, returning
    {name, title, email, phone, linkedin}. Apollo is THE source for a named person's
    verified DIRECT DIAL (free tier gives emails freely; mobile numbers consume
    'mobile credits' and may be gated). Fail-safe []."""
    if requests is None or not company:
        return []
    from core import runtime_config as rc
    key = (rc.get("apollo_api_key") or "").strip()
    if not key:
        return []
    payload = {
        "page": 1, "per_page": min(limit, 10),
        "person_titles": titles or DM_TITLES,
        "q_organization_name": company,
        # ask Apollo to reveal personal/work phone + email (uses credits on paid; free is limited)
        "reveal_personal_emails": True,
    }
    if domain:
        payload["q_organization_domains"] = [domain]
    try:
        resp = requests.post(
            "https://api.apollo.io/v1/mixed_people/search",
            headers={"Content-Type": "application/json", "Cache-Control": "no-cache", "X-Api-Key": key},
            data=json.dumps(payload), timeout=25,
        )
        if resp.status_code != 200:
            return []
        people = resp.json().get("people") or resp.json().get("contacts") or []
    except Exception:
        return []
    out = []
    for p in people[:limit]:
        if not isinstance(p, dict):
            continue
        phones = p.get("phone_numbers") or []
        phone = ""
        # Prefer a mobile/direct number if Apollo revealed one.
        for ph in phones:
            num = (ph.get("sanitized_number") or ph.get("raw_number") or "").strip()
            if num:
                phone = num
                if (ph.get("type") or "").lower() in ("mobile", "direct"):
                    break
        if not phone:
            phone = (p.get("mobile_phone") or p.get("sanitized_phone") or "").strip()
        out.append({
            "name": (p.get("name") or f"{p.get('first_name','')} {p.get('last_name','')}").strip(),
            "title": p.get("title") or "",
            "email": p.get("email") or (p.get("personal_emails") or [""])[0] or "",
            "phone": phone,
            "linkedin": p.get("linkedin_url") or "",
        })
    return [o for o in out if o["name"]]


def search_companies(
    keyword: str,
    country: str = "India",
    region: Optional[str] = None,
    exclude_with_hrms: bool = True,
    max_results: int = 25,
    api_key: Optional[str] = None,
) -> list[dict]:
    """Query Apollo org search. Returns [] if no key / any error (fail-safe)."""
    if requests is None:
        return []
    key = api_key
    if not key:
        try:
            from core import runtime_config as rc
            key = rc.get("apollo_api_key")
        except Exception:
            key = None
    if not key:
        return []

    locations = [region] if region else []
    locations.append(country or "India")
    payload = {
        "page": 1,
        "per_page": min(max_results, 100),
        "organization_num_employees_ranges": _SIZE_RANGES,
        "organization_locations": [loc for loc in locations if loc],
        "q_organization_keyword_tags": [keyword],
    }
    if exclude_with_hrms:
        payload["currently_not_using_any_of_technology_uids"] = _HRMS_TECH_UIDS

    try:
        resp = requests.post(
            "https://api.apollo.io/v1/mixed_companies/search",
            headers={"Content-Type": "application/json", "Cache-Control": "no-cache", "X-Api-Key": key},
            data=json.dumps(payload),
            timeout=20,
        )
        data = resp.json()
        orgs = data.get("organizations") or data.get("accounts") or []
        out = [c for c in (_to_candidate(o) for o in orgs) if c]
        return out[:max_results]
    except Exception:
        return []
