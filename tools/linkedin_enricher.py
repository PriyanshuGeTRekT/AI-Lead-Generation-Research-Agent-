"""
LinkedIn Decision Maker Enricher
----------------------------------
Uses Serper (Google Search) to find the actual HR/People decision maker at a
company without requiring a LinkedIn API key. Google indexes LinkedIn profiles
and surfaces name + title in search snippets — we extract those.

Why not LinkedIn API?
  LinkedIn's official API is enterprise-only and expensive. Scraping LinkedIn
  directly gets your IP blocked instantly. But Google search results include
  LinkedIn profile titles and snippets publicly — so we use Serper to search
  "company HR Manager site:linkedin.com" and parse the snippet.

Returns:
  {
    "name": "Priya Sharma",          # First name found, or ""
    "full_name": "Priya Sharma",     # Full name if extractable
    "title": "HR Manager",           # Title from LinkedIn snippet
    "linkedin_url": "https://...",   # LinkedIn profile URL if in results
    "email_guesses": ["p.sharma@company.com", "priya@company.com"],
  }
"""
import re
import requests
from typing import Dict, List
from loguru import logger
from core.config import get_settings

settings = get_settings()

# Decision-maker titles to search for, in priority order
_DM_TITLES = [
    "CHRO", "Chief People Officer", "Chief HR Officer",
    "VP HR", "VP People", "Head of HR", "Head of People",
    "HR Director", "People Director", "HR Manager",
]

# Regex to extract a plausible full name from LinkedIn snippet titles
# LinkedIn snippet format: "Name - Title at Company | LinkedIn"
_NAME_FROM_TITLE_RE = re.compile(
    r"^([A-Z][a-z]+(?: [A-Z][a-z.]+){1,3})\s*[-–|]"
)
# Remove noise words that aren't names
_NON_NAME_WORDS = {"linkedin", "view", "profile", "connect", "follow", "hr", "the"}


def _infer_email_guesses(name: str, domain: str) -> List[str]:
    """
    Generate common corporate email patterns from a name and domain.
    e.g. Priya Sharma → priya@domain.com, p.sharma@domain.com, etc.
    """
    if not name or not domain:
        return []
    parts = name.lower().split()
    if len(parts) < 2:
        return [f"{parts[0]}@{domain}"] if parts else []
    first, last = parts[0], parts[-1]
    return [
        f"{first}@{domain}",
        f"{first}.{last}@{domain}",
        f"{first[0]}.{last}@{domain}",
        f"{first}{last[0]}@{domain}",
        f"{first}_{last}@{domain}",
    ]


def enrich_decision_maker(company_name: str, domain: str) -> Dict:
    """
    Search for the HR/People decision maker at a company via Google/Serper.
    Falls back gracefully if Serper key is missing or search fails.
    """
    empty = {"name": "", "full_name": "", "title": "", "linkedin_url": "", "email_guesses": []}

    if not settings.serper_api_key:
        logger.debug(f"[LinkedIn] No Serper key — skipping enrichment for {company_name}")
        return empty

    # Try each title in priority order, stop at first hit
    for title in _DM_TITLES:
        query = f'"{company_name}" "{title}" site:linkedin.com/in India'
        try:
            resp = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": settings.serper_api_key, "Content-Type": "application/json"},
                json={"q": query, "num": 3, "gl": "in"},
                timeout=8,
            )
            resp.raise_for_status()
            results = resp.json().get("organic", [])

            for r in results:
                url = r.get("link", "")
                if "linkedin.com/in/" not in url:
                    continue

                # Extract name from the result title
                raw_title = r.get("title", "")
                name_match = _NAME_FROM_TITLE_RE.match(raw_title)
                full_name = name_match.group(1).strip() if name_match else ""

                # Sanity check: reject if any part looks like a non-name word
                if full_name:
                    parts = full_name.lower().split()
                    if any(p in _NON_NAME_WORDS for p in parts):
                        full_name = ""

                # Extract title from snippet
                snippet = r.get("snippet", "")
                found_title = title  # default to what we searched for

                # Try to get a more specific title from the snippet
                for t in _DM_TITLES:
                    if t.lower() in snippet.lower():
                        found_title = t
                        break

                email_domain = domain.replace("www.", "").split("/")[0]
                guesses = _infer_email_guesses(full_name, email_domain)

                result = {
                    "name": full_name.split()[0] if full_name else "",
                    "full_name": full_name,
                    "title": found_title,
                    "linkedin_url": url,
                    "email_guesses": guesses,
                }
                logger.info(f"[LinkedIn] Found: {full_name} ({found_title}) at {company_name}")
                return result

        except Exception as e:
            logger.debug(f"[LinkedIn] Search failed for {company_name} / {title}: {e}")
            continue

    logger.debug(f"[LinkedIn] No decision maker found for {company_name}")
    return empty
