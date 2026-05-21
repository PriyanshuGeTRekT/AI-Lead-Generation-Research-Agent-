"""
Instantly.ai Lead Finder Client
---------------------------------
Searches Instantly.ai's B2B contact database (160M+ contacts) for HR
decision makers at companies matching the user's keyword.

Unlike Serper (which returns web pages we have to scrape), Instantly returns
structured contact data directly:
  - Company name, website
  - Contact: first/last name, business email, job title, LinkedIn URL
  - Company: industry, headcount, location

This makes Instantly leads MORE valuable because:
  1. No web scraping needed — we already have contact info
  2. Email is already verified (Instantly verifies before returning)
  3. Decision maker identity is known immediately

Free tier: 1,000 lead credits/month

Authentication: The API key is the full base64 string as provided.
Instantly v1 API uses ?api_key=<key> as query param.
"""
import re
import requests
from typing import List, Dict, Optional
from loguru import logger


def _get_api_key() -> str:
    from core.config import get_settings
    return get_settings().instantly_api_key


# ── Industry/size parsing ──────────────────────────────────────────────────────

_INDUSTRY_MAP = {
    "manufactur":     "Manufacturing",
    "factory":        "Manufacturing",
    "industrial":     "Manufacturing",
    "automotive":     "Automotive",
    "automobile":     "Automotive",
    "auto parts":     "Automotive",
    "pharma":         "Pharmaceuticals",
    "pharmaceutical": "Pharmaceuticals",
    "biotech":        "Biotechnology",
    "logistic":       "Logistics and Supply Chain",
    "transport":      "Transportation",
    "freight":        "Logistics and Supply Chain",
    "warehousing":    "Logistics and Supply Chain",
    "delivery":       "Logistics and Supply Chain",
    "software":       "Computer Software",
    "it ":            "Information Technology and Services",
    "tech":           "Information Technology and Services",
    "fintech":        "Financial Services",
    "bpo":            "Outsourcing/Offshoring",
    "healthcare":     "Hospital & Health Care",
    "hospital":       "Hospital & Health Care",
    "medical":        "Medical Devices",
    "retail":         "Retail",
    "ecommerce":      "Internet",
    "e-commerce":     "Internet",
    "fmcg":           "Consumer Goods",
    "food":           "Food & Beverages",
    "textile":        "Textiles",
    "garment":        "Apparel & Fashion",
    "fashion":        "Apparel & Fashion",
    "chemical":       "Chemicals",
    "education":      "Education Management",
    "school":         "Education Management",
    "hotel":          "Hospitality",
    "construction":   "Construction",
    "real estate":    "Real Estate",
    "banking":        "Banking",
    "finance":        "Financial Services",
    "insurance":      "Insurance",
    "media":          "Media Production",
    "steel":          "Mining & Metals",
    "energy":         "Oil & Energy",
    "power":          "Utilities",
}

# Job titles to search for — we want HR decision makers
_DM_TITLES = [
    "HR Manager",
    "CHRO",
    "HR Director",
    "Head of HR",
    "VP HR",
    "VP Human Resources",
    "Human Resources Manager",
]


def _keyword_to_industry(keyword: str) -> str:
    kw = keyword.lower()
    for k, v in _INDUSTRY_MAP.items():
        if k in kw:
            return v
    return "Manufacturing"   # default for India B2B


def _keyword_to_min_size(keyword: str) -> int:
    m = re.search(r"(\d+)", keyword)
    if m:
        n = int(m.group(1))
        return n if n >= 50 else 200   # ignore years like "2024"
    return 200


# ── API call ──────────────────────────────────────────────────────────────────

def _call_instantly(
    title: str,
    industry: str,
    country: str,
    min_employees: int,
    limit: int,
    api_key: str,
) -> List[Dict]:
    """
    Call Instantly.ai Lead Finder API for one job title.
    Tries v1 endpoint with api_key query param first, then v2 with Bearer auth.
    Returns raw contact records on success, [] on any error.
    """
    payload_v1 = {
        "filter": {
            "industry": industry,
            "country": country,
            "job_title": title,
            "company_headcount": [str(min_employees) + "+"],
        },
        "limit": limit,
        "page": 1,
    }

    endpoints = [
        # v1 style — api_key as query param
        {
            "url": f"https://api.instantly.ai/api/v1/leadfinder/search?api_key={api_key}",
            "headers": {"Content-Type": "application/json"},
            "json": payload_v1,
        },
        # v2 style — Bearer token
        {
            "url": "https://api.instantly.ai/api/v2/lead-finder/search",
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            "json": {
                "query": {
                    "job_title": title,
                    "industry": industry,
                    "country": "India",
                    "employees_range": f"{min_employees}-100000",
                },
                "page": 1,
                "limit": limit,
            },
        },
        # Alternative v1 path
        {
            "url": f"https://api.instantly.ai/api/v1/lead/search?api_key={api_key}",
            "headers": {"Content-Type": "application/json"},
            "json": payload_v1,
        },
    ]

    for ep in endpoints:
        try:
            resp = requests.post(
                ep["url"],
                headers=ep["headers"],
                json=ep["json"],
                timeout=15,
            )
            if resp.status_code == 401:
                logger.warning("[Instantly] Auth failed — check INSTANTLY_API_KEY in .env")
                return []
            if resp.status_code == 403:
                logger.warning("[Instantly] Forbidden — Lead Finder may not be enabled on your plan")
                return []
            if resp.status_code == 404:
                logger.debug(f"[Instantly] 404 at {ep['url'][:60]}, trying next…")
                continue
            if resp.status_code == 429:
                logger.warning("[Instantly] Rate limited — monthly credits may be exhausted")
                return []
            resp.raise_for_status()
            data = resp.json()
            contacts = (
                data.get("leads")
                or data.get("contacts")
                or data.get("data")
                or data.get("results")
                or []
            )
            if isinstance(contacts, list):
                logger.info(f"[Instantly] '{title}' → {len(contacts)} contacts via {ep['url'][:50]}")
                return contacts
        except requests.exceptions.Timeout:
            logger.debug(f"[Instantly] Timeout at {ep['url'][:60]}")
            continue
        except requests.exceptions.ConnectionError:
            logger.debug(f"[Instantly] Connection error at {ep['url'][:60]}")
            continue
        except Exception as e:
            logger.debug(f"[Instantly] Error at {ep['url'][:60]}: {e}")
            continue

    return []


# ── Contact → lead conversion ─────────────────────────────────────────────────

def _contact_to_lead_candidate(contact: Dict, industry: str, title: str) -> Optional[Dict]:
    """
    Convert an Instantly contact record to our standard search result format.
    Returns None if the record is too incomplete to be useful.
    """
    # Normalize field names across API response variations
    company_name = (
        contact.get("organization_name")
        or contact.get("company_name")
        or contact.get("company")
        or ""
    ).strip()

    website = (
        contact.get("company_website")
        or contact.get("website")
        or contact.get("company_domain")
        or ""
    ).strip()

    if not company_name:
        return None

    # Normalize website URL
    if website and not website.startswith("http"):
        website = f"https://{website}"

    first = contact.get("first_name", "").strip()
    last  = contact.get("last_name", "").strip()
    name  = f"{first} {last}".strip()
    email = (contact.get("email") or contact.get("work_email") or "").strip()
    linkedin = (
        contact.get("linkedin_url")
        or contact.get("linkedin")
        or contact.get("li_url")
        or ""
    ).strip()

    location_parts = [
        contact.get("city", ""),
        contact.get("state", ""),
        contact.get("country", "India"),
    ]
    location = ", ".join(p for p in location_parts if p)

    headcount = (
        contact.get("company_headcount")
        or contact.get("employees")
        or contact.get("headcount")
        or ""
    )
    size_str = f"{headcount} employees" if headcount else ""

    snippet = (
        f"{company_name} is a {industry} company located in {location}. "
        f"{size_str}. "
        f"Contact: {name}, {title}."
        + (f" Email: {email}." if email else "")
    )

    return {
        "title":            f"{company_name} — {industry} India",
        "url":              website,
        "snippet":          snippet.strip(),
        "source":           "instantly",
        # Pre-filled enrichment — skip LinkedIn lookup for these leads
        "dm_name":          name,
        "dm_title":         title,
        "dm_email":         email,
        "dm_linkedin":      linkedin,
        "company_location": location,
        "company_size":     size_str,
    }


# ── Public entry point ────────────────────────────────────────────────────────

def search_instantly_leads(keyword: str, max_results: int = 30) -> List[Dict]:
    """
    Search Instantly.ai Lead Finder for companies matching `keyword`.

    Strategy:
      - Detect industry and company size from the keyword
      - Search for HR decision makers (CHRO, HR Manager, HR Director…) at matching companies
      - Deduplicate by company domain so each company appears only once
      - Return up to max_results company lead candidates

    Each result includes pre-extracted contact data (name, email, LinkedIn)
    which avoids redundant LinkedIn enrichment calls for these leads.

    Returns [] if the API key is not configured or the endpoint is unavailable.
    """
    api_key = _get_api_key()
    if not api_key:
        logger.debug("[Instantly] INSTANTLY_API_KEY not set, skipping")
        return []

    industry    = _keyword_to_industry(keyword)
    min_size    = _keyword_to_min_size(keyword)
    per_title   = max(5, max_results // len(_DM_TITLES))

    seen_companies: set = set()
    results: List[Dict] = []

    for title in _DM_TITLES:
        if len(results) >= max_results:
            break
        contacts = _call_instantly(
            title=title,
            industry=industry,
            country="India",
            min_employees=min_size,
            limit=per_title,
            api_key=api_key,
        )
        for c in contacts:
            if len(results) >= max_results:
                break
            candidate = _contact_to_lead_candidate(c, industry, title)
            if not candidate:
                continue
            # Deduplicate by lowercased company name
            key = candidate["title"].lower()
            if key in seen_companies:
                continue
            seen_companies.add(key)
            results.append(candidate)

    logger.info(f"[Instantly] Total: {len(results)} unique companies for '{keyword}'")
    return results
