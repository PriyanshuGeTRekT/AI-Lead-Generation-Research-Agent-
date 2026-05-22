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
    "email_guesses": ["p.sharma@company.com", "priya.sharma@company.com"],
  }
"""
import re
import requests
from typing import Dict, List, Optional
from loguru import logger
from core.config import get_settings

settings = get_settings()

# Fix 3: Reduced from 10 titles to 3, searched in priority order.
# Only the most senior/common HR titles to save Serper API credits.
_DM_TITLES = [
    "CHRO",
    "HR Director",
    "HR Manager",
]

# Fix 5: Improved name regex — handles:
#   - Names with middle initials: "Rakesh K. Kumar"
#   - Honorifics: "Dr. Priya Sharma", "Mr. Amit Roy"
#   - Non-Western formats common in India (single-word surnames with dots)
# Pattern: optional honorific, then 2–4 capitalised name tokens, then a separator
_NAME_FROM_TITLE_RE = re.compile(
    r"^(?:Dr\.|Mr\.|Ms\.|Mrs\.|Prof\.)?\s*"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z.]+){1,3})"
    r"\s*[-–|]"
)

# Fix 5: Extended non-name reject list
_NON_NAME_WORDS = {
    "linkedin", "view", "profile", "connect", "follow",
    "hr", "the", "and", "jobs", "people", "director",
    "manager", "officer", "head", "chief", "india",
}

# Fix 4: Patterns to extract title from LinkedIn snippet
# Format A: "Name - Title at Company | LinkedIn"
# Format B: "Name | Title | Company | LinkedIn"
_TITLE_FROM_SNIPPET_RE = re.compile(
    r"[-–|]\s*([^|–\-]+?)\s*(?:at\s+.+?)?(?:\s*[|]|\s*$)",
    re.IGNORECASE,
)


def _extract_title_from_snippet(raw_title: str, snippet: str, fallback: str) -> str:
    """
    Fix 4: Parse the actual role title from the LinkedIn result title string.

    LinkedIn formats seen in practice:
      "Priya Sharma - HR Director at Infosys | LinkedIn"
      "Rakesh Kumar | CHRO | Tata Consultancy | LinkedIn"
      "Dr. Amit Roy – Head of People | LinkedIn"
    """
    # Try "Name - Title at Company" or "Name – Title" format
    after_sep = re.split(r"\s*[-–]\s*", raw_title, maxsplit=1)
    if len(after_sep) == 2:
        # Second part: "Title at Company | LinkedIn" or "Title | LinkedIn"
        rest = after_sep[1]
        # Strip trailing "| LinkedIn" / "| LinkedIn Profile"
        rest = re.sub(r"\s*\|\s*LinkedIn.*$", "", rest, flags=re.IGNORECASE).strip()
        # Strip "at Company..." suffix
        rest = re.sub(r"\s+at\s+.+$", "", rest, flags=re.IGNORECASE).strip()
        if rest and len(rest) < 80:
            return rest

    # Try pipe-separated format: "Name | Title | Company | LinkedIn"
    parts = [p.strip() for p in raw_title.split("|")]
    if len(parts) >= 3:
        # parts[0]=Name, parts[1]=Title, parts[2]=Company/LinkedIn
        candidate = parts[1]
        if candidate and candidate.lower() not in ("linkedin", ""):
            return candidate

    # Fall back to scanning snippet for known title keywords
    for t in _DM_TITLES:
        if t.lower() in snippet.lower():
            return t

    return fallback


def _company_verified(company_name: str, url: str, snippet: str) -> bool:
    """
    Fix 1: Verify the found person actually works at the target company.

    Returns True if either:
      - The snippet text contains the company name (case-insensitive), OR
      - The LinkedIn profile URL slug contains a keyword derived from the
        company name (e.g. linkedin.com/in/rakesh-kumar-boeing).

    Rejects results where neither condition holds — these are people with the
    same title at different companies whose profiles happened to rank.
    """
    company_lower = company_name.lower()
    snippet_lower = snippet.lower()

    # Condition 1: company name appears in snippet
    if company_lower in snippet_lower:
        return True

    # Condition 2: a meaningful keyword from the company name appears in URL slug
    # Build keywords: split on spaces/punctuation, keep tokens ≥4 chars
    url_lower = url.lower()
    keywords = re.split(r"[\s\-_&.,/()]+", company_lower)
    # Filter out generic short words
    stop_words = {"the", "and", "of", "ltd", "pvt", "inc", "llc", "co", "corp", "india"}
    keywords = [k for k in keywords if len(k) >= 4 and k not in stop_words]

    for kw in keywords:
        if kw in url_lower:
            return True

    return False


def _infer_email_guesses(name: str, domain: str) -> List[str]:
    """
    Fix 2: Only generate 2 guesses (not 5), only when domain is confirmed.
    Guesses are returned as email_guesses (not contact_emails) — the research
    agent already keeps these separate (research_agent.py line 161).
    """
    if not name or not domain:
        return []
    parts = name.lower().split()
    if len(parts) < 2:
        return []
    first, last = parts[0], parts[-1]
    # Keep only the two most common corporate patterns
    return [
        f"{first}.{last}@{domain}",
        f"{first[0]}.{last}@{domain}",
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

    # Fix 3: Only 3 titles, stop at first confident (verified) hit
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

                raw_title = r.get("title", "")
                snippet = r.get("snippet", "")

                # Fix 5: Improved name extraction
                name_match = _NAME_FROM_TITLE_RE.match(raw_title)
                full_name = name_match.group(1).strip() if name_match else ""

                # Fix 5: Reject extracted "names" that contain non-name words
                if full_name:
                    name_parts = full_name.lower().split()
                    if any(p in _NON_NAME_WORDS for p in name_parts):
                        full_name = ""

                # Fix 1: Verify the person actually works at the target company
                if not _company_verified(company_name, url, snippet):
                    logger.debug(
                        f"[LinkedIn] Rejected unverified result for {company_name}: "
                        f"{full_name!r} at {url}"
                    )
                    continue

                # Fix 4: Extract the actual title from the snippet/title string
                found_title = _extract_title_from_snippet(raw_title, snippet, title)

                # Fix 2: Only generate guesses when we have a confirmed domain;
                # limit to 2 patterns, stored as email_guesses not contact_emails
                email_domain = domain.replace("www.", "").split("/")[0] if domain else ""
                guesses = _infer_email_guesses(full_name, email_domain) if email_domain else []

                result = {
                    "name": full_name.split()[0] if full_name else "",
                    "full_name": full_name,
                    "title": found_title,
                    "linkedin_url": url,
                    "email_guesses": guesses,
                }
                logger.info(
                    f"[LinkedIn] Found: {full_name} ({found_title}) at {company_name} "
                    f"[verified via snippet/URL]"
                )
                return result

        except Exception as e:
            logger.debug(f"[LinkedIn] Search failed for {company_name} / {title}: {e}")
            continue

    logger.debug(f"[LinkedIn] No verified decision maker found for {company_name}")
    return empty
