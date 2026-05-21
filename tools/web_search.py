import os
import re
import time
import json
import requests
from typing import List, Dict, Tuple
from urllib.parse import urlparse, urljoin
from loguru import logger
from tools.naukri_scraper import search_naukri_companies
from tools.indeed_scraper import search_indeed_companies
from core.config import get_settings as _get_settings

# ── Contact extraction helpers ─────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(
    r"(?:\+91[\s\-]?)?(?:\(?0?\d{2,4}\)?[\s\-]?)?\d{5}[\s\-]?\d{5}"
)
# Domains to skip for email extraction (generic providers aren't company contacts)
_SKIP_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "example.com"}


def extract_emails(text: str) -> List[str]:
    """Extract unique business email addresses from raw text."""
    found = _EMAIL_RE.findall(text)
    seen = []
    for e in found:
        e = e.lower().strip(".")
        domain = e.split("@")[-1]
        if domain not in _SKIP_EMAIL_DOMAINS and e not in seen:
            seen.append(e)
    return seen[:5]  # cap at 5


def extract_phone(text: str) -> str:
    """Extract first plausible Indian phone number from text."""
    match = _PHONE_RE.search(text)
    if match:
        # Normalise whitespace/dashes
        return re.sub(r"[\s\-]+", "-", match.group()).strip()
    return ""

SERPER_API_KEY = _get_settings().serper_api_key


def search_companies(keyword: str, max_results: int = 10) -> List[Dict]:
    """
    Search for companies using Serper.dev (Google results via API).
    Falls back to curated dataset if API key missing or request fails.
    """
    if SERPER_API_KEY:
        results = _search_serper(keyword, max_results)
        if results:
            return results
        logger.warning("[WebSearch] Serper returned no results, using fallback")
    else:
        logger.warning("[WebSearch] No SERPER_API_KEY set, using fallback dataset")

    return _get_fallback_companies(keyword)



# Domains to exclude — aggregators, lists, PDFs, social media, job boards
_BLOCKED_DOMAINS = {
    "wikipedia.org", "linkedin.com", "facebook.com", "twitter.com",
    "instagram.com", "youtube.com", "indiamart.com", "justdial.com",
    "companiesmarketcap.com", "dnb.co.in", "dnb.com", "ambitionbox.com",
    "glassdoor.com", "indeed.com", "naukri.com", "moneycontrol.com",
    "economictimes.com", "livemint.com", "businessstandard.com",
    "easyleadz.com", "crunchbase.com", "zaubacorp.com", "tofler.in",
}


def _is_company_url(url: str) -> bool:
    """Return True if the URL looks like an actual company website (not an aggregator)."""
    if not url:
        return False
    # Skip PDFs and known aggregator domains
    if url.lower().endswith(".pdf"):
        return False
    try:
        domain = urlparse(url).netloc.replace("www.", "").lower()
        # Check against block list (exact or subdomain match)
        for blocked in _BLOCKED_DOMAINS:
            if domain == blocked or domain.endswith("." + blocked):
                return False
    except Exception:
        pass
    return True


def _search_serper(keyword: str, max_results: int = 10) -> List[Dict]:
    """
    Query Serper.dev Google Search API.
    Returns results in the same format as the old DuckDuckGo function.
    Free tier: 2,500 queries. No credit card required.
    """
    # Build a buyer-targeted query.
    # We want companies that USE HRMS software, not ones that sell it.
    # Exclude known HRMS vendor terms so we don't surface competitors.
    kw_clean = keyword.strip()
    if "india" not in kw_clean.lower():
        kw_clean = f"{kw_clean} India"
    # Exclude aggregators and HRMS vendors from results
    exclusions = '-site:greythr.com -site:darwinbox.com -site:keka.com -site:zoho.com -site:sumhr.com -"HRMS software company" -"HR software provider"'
    query = f"{kw_clean} company official website {exclusions}"
    try:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": SERPER_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "q": query,
                "num": max_results + 5,  # fetch extra to compensate for filtered-out results
                "gl": "in",   # India
                "hl": "en",
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        results = []
        for r in data.get("organic", []):
            url = r.get("link", "")
            if not _is_company_url(url):
                logger.debug(f"[Serper] Skipping aggregator/list URL: {url}")
                continue
            results.append({
                "title": r.get("title", ""),
                "url": url,
                "snippet": r.get("snippet", ""),
                "source": "serper",
            })
            if len(results) >= max_results:
                break

        logger.info(f"[Serper] Got {len(results)} company results for: {query}")
        return results

    except Exception as e:
        logger.error(f"[Serper] Search failed: {e}")
        return []


def _get_fallback_companies(keyword: str) -> List[Dict]:
    """
    Curated list of real Indian companies that are strong HRMS prospects.
    Used as fallback when live search is rate-limited.

    Architectural Decision:
      Production systems should never hard-fail on third-party API unavailability.
      This fallback ensures the pipeline always has data to process for demos,
      integration tests, and degraded-mode operation.
    """
    all_companies = [
        {
            "title": "Tata Consultancy Services (TCS) - IT Services India",
            "url": "https://www.tcs.com",
            "snippet": (
                "TCS is India's largest IT services company with over 600,000 employees. "
                "Headquartered in Mumbai, Maharashtra. Major IT and consulting firm with "
                "global operations. Manages complex HR workflows across 50+ countries."
            ),
        },
        {
            "title": "Infosys - Global IT Consulting and Services",
            "url": "https://www.infosys.com",
            "snippet": (
                "Infosys is a global leader in IT services with 330,000+ employees. "
                "Bengaluru, Karnataka. Offers consulting, technology, and outsourcing. "
                "Complex payroll, compliance, and talent management needs across geographies."
            ),
        },
        {
            "title": "Wipro Technologies - IT and Software Company India",
            "url": "https://www.wipro.com",
            "snippet": (
                "Wipro is a leading global IT company based in Bengaluru. 250,000+ employees "
                "across 65 countries. Provides IT, consulting, and business process services. "
                "Large workforce requiring unified HRMS for compliance and performance tracking."
            ),
        },
        {
            "title": "Mahindra & Mahindra - Automotive and Farm Equipment",
            "url": "https://www.mahindra.com",
            "snippet": (
                "Mahindra & Mahindra is a multinational automotive manufacturing company based in Mumbai. "
                "Over 200,000 employees across manufacturing, auto, and IT divisions. "
                "Complex HR needs including factory workers, office staff, and international teams."
            ),
        },
        {
            "title": "Bajaj Auto - Two-Wheeler Manufacturer India",
            "url": "https://www.bajajauto.com",
            "snippet": (
                "Bajaj Auto is one of India's leading two-wheeler manufacturers, headquartered in Pune. "
                "Approximately 10,000 employees across multiple manufacturing plants. "
                "Manages attendance, shift scheduling, and compliance for blue-collar workforce."
            ),
        },
        {
            "title": "Zomato - Food Delivery and Restaurant Platform",
            "url": "https://www.zomato.com",
            "snippet": (
                "Zomato is India's leading food delivery platform with 5,000+ corporate employees "
                "and 300,000+ delivery partners. Bengaluru-based startup. Rapid growth means "
                "HR processes for gig workers, onboarding, and compliance are critical."
            ),
        },
        {
            "title": "Byju's - EdTech Company India",
            "url": "https://byjus.com",
            "snippet": (
                "BYJU'S is India's largest edtech company based in Bengaluru. 50,000+ employees "
                "across India with rapid hiring cycles. HR challenges include performance management, "
                "training tracking, and compliance across multiple states."
            ),
        },
        {
            "title": "Reliance Industries - Conglomerate India",
            "url": "https://www.ril.com",
            "snippet": (
                "Reliance Industries is India's largest private sector company by revenue. "
                "Over 236,000 employees across oil, retail, telecom, and media divisions. "
                "Multi-division workforce management and payroll across India is a core HR challenge."
            ),
        },
        {
            "title": "Myntra - Fashion E-commerce India",
            "url": "https://www.myntra.com",
            "snippet": (
                "Myntra is India's leading fashion e-commerce platform, part of Flipkart group. "
                "Bengaluru-based with 5,000+ employees and 500,000+ delivery staff. "
                "HRMS needed for talent acquisition, performance reviews, and workforce analytics."
            ),
        },
        {
            "title": "Ola Cabs - Ride-Sharing Platform India",
            "url": "https://www.olacabs.com",
            "snippet": (
                "Ola is India's largest ride-sharing company based in Bengaluru. 5,000+ corporate employees "
                "and 1.5 million driver-partners. HR challenges include onboarding at scale, "
                "benefits administration, and compliance for gig economy workforce."
            ),
        },
        {
            "title": "Tata Steel - Manufacturing and Steel Production India",
            "url": "https://www.tatasteel.com",
            "snippet": (
                "Tata Steel is one of India's largest steel manufacturers with 35,000+ employees. "
                "Jamshedpur, Jharkhand. Managing blue-collar and white-collar workforce across "
                "multiple plants. Shift scheduling, attendance, and statutory compliance are key HR needs."
            ),
        },
        {
            "title": "HCL Technologies - IT Services India",
            "url": "https://www.hcltech.com",
            "snippet": (
                "HCL Technologies is a global IT company based in Noida with 220,000+ employees. "
                "Rapid scaling across geographies. Complex payroll, multi-country compliance, "
                "and performance management across delivery centres are core HR challenges."
            ),
        },
        {
            "title": "Nykaa - Beauty and Fashion E-commerce India",
            "url": "https://www.nykaa.com",
            "snippet": (
                "Nykaa is India's leading beauty e-commerce company. Headquartered in Mumbai with "
                "12,000+ employees across retail, tech, and logistics. Fast-growing team requires "
                "automated onboarding, appraisal cycles, and leave management."
            ),
        },
        {
            "title": "Delhivery - Logistics and Supply Chain India",
            "url": "https://www.delhivery.com",
            "snippet": (
                "Delhivery is India's largest fully-integrated logistics company based in Gurugram. "
                "100,000+ delivery and warehouse staff. HR needs include mass onboarding, "
                "attendance tracking, and performance management for distributed workforce."
            ),
        },
        {
            "title": "Zepto - Quick Commerce Startup India",
            "url": "https://www.zeptonow.com",
            "snippet": (
                "Zepto is India's fastest-growing quick commerce company headquartered in Mumbai. "
                "10,000+ employees and delivery staff. Rapid hiring cycles, gig workforce management, "
                "and compliance for dark store operations are critical HR requirements."
            ),
        },
    ]

    # Filter slightly by keyword to make results feel relevant
    kw_lower = keyword.lower()
    relevant = [
        c for c in all_companies
        if any(w in c["snippet"].lower() for w in kw_lower.split()[:3])
    ] or all_companies

    return relevant[:8]


def search_companies_multi_source(keyword: str) -> List[Dict]:
    """
    Fan-out search across DuckDuckGo, Naukri.com, and Indeed India.
    Merges results and deduplicates by root domain.
    Returns a unified list of company lead dicts.
    """
    # --- Serper (Google Search) ---
    serper_raw = search_companies(keyword)
    serper_results = []
    for r in serper_raw:
        if "source" not in r:
            r["source"] = "serper"
        serper_results.append(r)

    # --- Naukri ---
    naukri_results = search_naukri_companies()

    # --- Indeed ---
    indeed_results = search_indeed_companies()

    serper_count = len(serper_results)
    naukri_count = len(naukri_results)
    indeed_count = len(indeed_results)

    all_results = serper_results + naukri_results + indeed_results

    # Deduplicate by root domain (strip www.)
    seen_domains: set = set()
    deduped: List[Dict] = []
    for item in all_results:
        url = item.get("url", "")
        if not url:
            deduped.append(item)
            continue
        try:
            domain = urlparse(url).netloc.replace("www.", "").lower()
        except Exception:
            domain = url.lower()

        if domain and domain not in seen_domains:
            seen_domains.add(domain)
            deduped.append(item)

    deduped_count = len(deduped)
    logger.info(
        f"Multi-source search: {serper_count} serper, "
        f"{naukri_count} naukri, {indeed_count} indeed, "
        f"{deduped_count} after dedup"
    )
    return deduped


def _fetch_text(url: str, timeout: int = 8) -> Tuple[str, str]:
    """
    Fetch a URL and return (raw_html, clean_text).
    Keeps footer in the text so emails/phones in footer are captured.
    """
    headers = {"User-Agent": "Mozilla/5.0 (compatible; LeadGenBot/1.0)"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    raw_html = resp.text
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(raw_html, "html.parser")
    # Remove only scripts and styles — keep footer (it has contact info)
    for tag in soup(["script", "style", "nav"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    return raw_html, text


def scrape_company_info(url: str) -> str:
    """
    Scrape homepage + contact page of a company website.
    Returns combined clean text (up to 4000 chars) for LLM consumption.
    """
    combined_text = ""
    try:
        _, homepage_text = _fetch_text(url)
        combined_text += homepage_text
    except Exception as e:
        combined_text += f"Could not scrape {url}: {e}"

    # Also try common contact page paths
    for path in ["/contact", "/contact-us", "/about", "/about-us"]:
        try:
            contact_url = urljoin(url.rstrip("/"), path)
            _, contact_text = _fetch_text(contact_url, timeout=6)
            combined_text += "\n" + contact_text
            break  # stop after first successful contact page
        except Exception:
            continue

    return combined_text[:4000]


def scrape_company_contacts(url: str) -> Dict:
    """
    Extract emails, phone numbers, and address from a company website.
    Scans homepage + contact page raw HTML before BeautifulSoup strips anything.
    Returns dict: {emails, phone, address_hint}
    """
    all_emails: List[str] = []
    all_phones: List[str] = []
    address_hint = ""

    for path in ["", "/contact", "/contact-us", "/about", "/about-us"]:
        target = urljoin(url.rstrip("/"), path) if path else url
        try:
            raw_html, clean_text = _fetch_text(target, timeout=6)
            # Extract from raw HTML (catches mailto: links too)
            all_emails += extract_emails(raw_html)
            phone = extract_phone(clean_text)
            if phone and not all_phones:
                all_phones.append(phone)
            # Simple address hint: look for "Address:" or pin code patterns
            if not address_hint:
                addr_match = re.search(
                    r"(?:Address|Office|Location)[:\s]+([^\n<]{10,120})", clean_text, re.I
                )
                if addr_match:
                    address_hint = addr_match.group(1).strip()
        except Exception:
            continue

    # Deduplicate emails
    seen = []
    for e in all_emails:
        if e not in seen:
            seen.append(e)

    return {
        "emails": seen[:5],
        "phone": all_phones[0] if all_phones else "",
        "address": address_hint,
    }
