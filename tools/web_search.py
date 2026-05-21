"""
Web Search Tools
----------------
Serper.dev (Google Search API) with multi-query diversification.

Key design:
  _search_serper_broad() runs 10-12 city/industry query variants, each with
  up to 2 pages, so a single pipeline call can surface 80-100 unique companies
  instead of the same 10 top-SEO results every time.

  _get_fallback_companies() holds 90+ real Indian companies across diverse
  industries, shuffled randomly on every call so offline/no-key runs also
  get fresh results.
"""
import re
import random
import requests
from typing import List, Dict, Tuple
from urllib.parse import urlparse, urljoin
from loguru import logger
from core.config import get_settings as _get_settings

# ── Contact extraction helpers ─────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(
    r"(?:\+91[\s\-]?)?(?:\(?0?\d{2,4}\)?[\s\-]?)?\d{5}[\s\-]?\d{5}"
)
_SKIP_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "example.com", "test.com",
}

# Words that indicate the scraped text is NOT an address (UI text, instructions, etc.)
_BAD_ADDRESS_TOKENS = [
    "driving license", "helmet", "gloves", "choose your profile",
    "select one from", "associated with this mobile", "sign in", "log in",
    "subscribe", "newsletter", "cookie", "privacy policy", "terms of",
    "whatsapp", "follow us", "get in touch", "reach us", "call us",
    "write to us", "click here", "download", "read more", "view all",
    "learn more", "find out", "date :", "× loca", "for any further",
]


def _validate_address(text: str) -> str:
    """
    Return the address text only if it looks like a real physical address.
    Discards UI text, navigation copy, and other scraping artifacts.
    """
    if not text:
        return ""
    text = text.strip()
    # Length sanity check
    if len(text) < 8 or len(text) > 180:
        return ""
    lower = text.lower()
    # Reject if it contains known non-address phrases
    for token in _BAD_ADDRESS_TOKENS:
        if token in lower:
            return ""
    # Must contain at least one digit (floor number, plot number, pincode, etc.)
    if not re.search(r'\d', text):
        return ""
    # Must have enough alphabetic content to be a real address
    alpha_count = sum(1 for c in text if c.isalpha())
    if alpha_count < 8:
        return ""
    # Reject if it's mostly non-alphanumeric (symbols / encoded junk)
    alnum_count = sum(1 for c in text if c.isalnum())
    if alnum_count < len(text) * 0.4:
        return ""
    return text


def extract_emails(text: str) -> List[str]:
    """Extract unique business email addresses from raw text."""
    found = _EMAIL_RE.findall(text)
    seen = []
    for e in found:
        e = e.lower().strip(".")
        domain = e.split("@")[-1]
        if domain not in _SKIP_EMAIL_DOMAINS and e not in seen:
            seen.append(e)
    return seen[:5]


def extract_phone(text: str) -> str:
    """Extract first plausible Indian phone number from text."""
    match = _PHONE_RE.search(text)
    if match:
        return re.sub(r"[\s\-]+", "-", match.group()).strip()
    return ""


SERPER_API_KEY = _get_settings().serper_api_key


# ── Query diversification ─────────────────────────────────────────────────────

_INDIA_CITIES = [
    "Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai",
    "Pune", "Ahmedabad", "Kolkata", "Jaipur", "Surat",
    "Coimbatore", "Vadodara", "Nagpur", "Ludhiana", "Kochi",
    "Bhopal", "Indore", "Visakhapatnam", "Nashik", "Gurugram",
    "Noida", "Faridabad", "Patna", "Lucknow", "Chandigarh",
]

_SIZE_SIGNALS = [
    "500 employees", "1000 employees", "2000 employees",
    "300 employees", "5000 employees", "800 employees",
]

# Industry-specific sub-query terms so we don't always search the same broad phrase
_INDUSTRY_VARIANTS: Dict[str, List[str]] = {
    "manufacturing": [
        "automobile parts manufacturer",
        "pharmaceutical manufacturer",
        "textile company",
        "chemical manufacturer",
        "FMCG company",
        "food processing company",
        "electronics manufacturer",
        "steel manufacturer",
        "plastic manufacturer",
        "garment exporter",
        "engineering company",
        "agri-equipment manufacturer",
        "packaging company",
        "rubber manufacturer",
        "ceramics manufacturer",
    ],
    "logistics": [
        "logistics company",
        "supply chain company",
        "warehousing company",
        "freight forwarding company",
        "courier company",
        "cold chain logistics",
        "last-mile delivery company",
        "trucking company",
        "3PL company",
    ],
    "it": [
        "software company",
        "IT services company",
        "BPO company",
        "fintech company",
        "tech startup",
        "software development company",
        "cloud services company",
        "IT consulting company",
        "data analytics company",
    ],
    "healthcare": [
        "hospital",
        "healthcare company",
        "pharmaceutical company",
        "diagnostic centre chain",
        "medical devices company",
        "nursing home chain",
        "health insurance company",
    ],
    "retail": [
        "retail company",
        "fashion brand India",
        "supermarket chain India",
        "consumer goods company India",
        "jewellery company India",
        "footwear company India",
    ],
}


def _detect_industry(keyword: str) -> str:
    """Map a keyword to one of the known industry buckets."""
    kw = keyword.lower()
    if any(w in kw for w in ["manufactur", "factory", "plant", "industrial", "steel", "textile", "pharma"]):
        return "manufacturing"
    if any(w in kw for w in ["logistic", "transport", "freight", "delivery", "warehouse"]):
        return "logistics"
    if any(w in kw for w in ["software", " it ", "tech", "digital", "fintech", "bpo"]):
        return "it"
    if any(w in kw for w in ["hospital", "clinic", "health", "pharma", "medical"]):
        return "healthcare"
    if any(w in kw for w in ["retail", "shop", "store", "commerce", "fashion"]):
        return "retail"
    return "manufacturing"


def _generate_query_variants(keyword: str, count: int = 12) -> List[str]:
    """
    Generate diverse Serper query variants from a base keyword.

    Strategy:
      - Rotate through Indian cities so each query targets a different metro/Tier-2 city.
      - Rotate through industry sub-sectors so queries hit auto parts, pharma, FMCG, etc.
      - Shuffled so repeated runs produce different orderings.

    A single run with count=12 generates queries like:
      "manufacturing company India 200 employees"   (original, always first)
      "automobile parts manufacturer Pune India 500 employees"
      "pharmaceutical manufacturer Chennai India 300 employees"
      "textile company Surat India 1000 employees"
      ...etc.
    """
    industry = _detect_industry(keyword)
    sub_industries = list(_INDUSTRY_VARIANTS.get(industry, [keyword.strip()]))

    # Strip location / size noise to get the core concept
    core = re.sub(
        r"\b(india|company|official|website|employees?|staff|workers?|over|approximately|\d+[+k]?)\b",
        "",
        keyword,
        flags=re.I,
    ).strip()
    core = re.sub(r"\s+", " ", core).strip() or keyword.split()[0]

    variants: List[str] = [keyword]  # Original always first

    cities = random.sample(_INDIA_CITIES, min(len(_INDIA_CITIES), count + 5))
    subs = random.sample(sub_industries, min(len(sub_industries), count))

    pool: List[str] = []
    for i, city in enumerate(cities):
        sub = subs[i % len(subs)] if subs else core
        size = _SIZE_SIGNALS[i % len(_SIZE_SIGNALS)]
        pool.append(f"{sub} {city} India {size} official website")

    # Pure industry-sub variants (no city) to catch national-level results
    for sub in subs[:4]:
        pool.append(f"{sub} India 500 employees HR")

    # General mid-size signal
    pool.append(f"mid-size {core} company India 200-1000 employees")

    random.shuffle(pool)

    for v in pool:
        if len(variants) >= count:
            break
        if v not in variants:
            variants.append(v)

    return variants[:count]


# ── URL helpers ───────────────────────────────────────────────────────────────

def _get_domain(url: str) -> str:
    """Return root domain (without www.) for deduplication."""
    try:
        return urlparse(url).netloc.replace("www.", "").lower()
    except Exception:
        return ""


# Domains to exclude — aggregators, lists, PDFs, social media, job boards
_BLOCKED_DOMAINS = {
    "wikipedia.org", "linkedin.com", "facebook.com", "twitter.com",
    "instagram.com", "youtube.com", "indiamart.com", "justdial.com",
    "companiesmarketcap.com", "dnb.co.in", "dnb.com", "ambitionbox.com",
    "glassdoor.com", "indeed.com", "naukri.com", "moneycontrol.com",
    "economictimes.com", "livemint.com", "businessstandard.com",
    "easyleadz.com", "crunchbase.com", "zaubacorp.com", "tofler.in",
    "tracxn.com", "startupindia.gov.in", "ibef.org", "statista.com",
}


def _is_company_url(url: str) -> bool:
    """Return True if the URL looks like an actual company website."""
    if not url or url.lower().endswith(".pdf"):
        return False
    try:
        domain = urlparse(url).netloc.replace("www.", "").lower()
        for blocked in _BLOCKED_DOMAINS:
            if domain == blocked or domain.endswith("." + blocked):
                return False
    except Exception:
        pass
    return True


# ── Serper API calls ──────────────────────────────────────────────────────────

# Exclude known HRMS vendor sites so they don't surface as prospects
_SERPER_EXCLUSIONS = (
    "-site:greythr.com -site:darwinbox.com -site:keka.com "
    "-site:zoho.com -site:sumhr.com -site:bamboohr.com "
    '-"HRMS software company" -"HR software provider" -"payroll software"'
)


def _search_serper_page(query: str, page: int = 1, num: int = 10) -> List[Dict]:
    """
    Make a single Serper API call for one page of results.
    Returns filtered company-URL results.
    """
    full_query = f"{query} {_SERPER_EXCLUSIONS}"
    try:
        resp = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": full_query, "num": num, "gl": "in", "hl": "en", "page": page},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for r in data.get("organic", []):
            url = r.get("link", "")
            if _is_company_url(url):
                results.append({
                    "title": r.get("title", ""),
                    "url": url,
                    "snippet": r.get("snippet", ""),
                    "source": "serper",
                })
        return results

    except Exception as e:
        logger.warning(f"[Serper] page={page} failed for '{query[:60]}': {e}")
        return []


def _search_serper_broad(keyword: str, total: int = 80) -> List[Dict]:
    """
    Run multiple diversified Serper queries with pagination to collect
    up to `total` unique company URLs.

    Strategy:
      - Generate 10-12 query variants (city + industry rotations)
      - First 3 variants get page 1 + page 2  (20 results each)
      - Remaining variants get only page 1    (10 results each)
      - Deduplicate by root domain throughout
    This gives ~80-100 unique candidates in ~13 Serper API calls.
    """
    variants = _generate_query_variants(keyword, count=10)
    seen_domains: set = set()
    all_results: List[Dict] = []

    for i, variant in enumerate(variants):
        if len(all_results) >= total:
            break
        pages = [1, 2] if i < 3 else [1]
        for page in pages:
            if len(all_results) >= total:
                break
            results = _search_serper_page(variant, page=page)
            added = 0
            for r in results:
                domain = _get_domain(r.get("url", ""))
                if domain and domain not in seen_domains:
                    seen_domains.add(domain)
                    all_results.append(r)
                    added += 1
            logger.debug(f"[Serper] variant={i+1} page={page}: +{added} new (total {len(all_results)})")

    logger.info(
        f"[Serper] Broad search complete: {len(all_results)} unique companies "
        f"from {len(variants)} query variants for: '{keyword}'"
    )
    return all_results[:total]


# ── Public search entry point ─────────────────────────────────────────────────

def search_companies(keyword: str, max_results: int = 80) -> List[Dict]:
    """
    Search for companies using Serper.dev (multi-query, multi-page).
    Falls back to a large shuffled curated dataset if API key is missing.
    """
    if SERPER_API_KEY:
        results = _search_serper_broad(keyword, total=max_results)
        if results:
            return results
        logger.warning("[WebSearch] Serper returned no results, using fallback")
    else:
        logger.warning("[WebSearch] No SERPER_API_KEY set — using fallback dataset (set key for live Google results)")

    return _get_fallback_companies(keyword, max_results=max_results)


def search_companies_multi_source(keyword: str, max_results: int = 80) -> List[Dict]:
    """
    Fan-out search: Serper (broad multi-query) + Instantly.ai (B2B contact DB).
    Merges and deduplicates by root domain / company name.

    Instantly leads are placed FIRST because they come with pre-verified contact
    data (DM name, email, LinkedIn) so the research agent can skip redundant
    LinkedIn enrichment for those leads.
    """
    # --- Instantly.ai Lead Finder (structured B2B contact data) ---
    try:
        from tools.instantly_client import search_instantly_leads
        instantly_results = search_instantly_leads(keyword, max_results=min(30, max_results // 2))
    except Exception as e:
        logger.warning(f"[MultiSource] Instantly search failed: {e}")
        instantly_results = []

    # --- Serper (Google Search, diversified queries) ---
    serper_results = search_companies(keyword, max_results=max_results)

    instantly_count = len(instantly_results)
    serper_count    = len(serper_results)

    # Instantly first (richer data), then Serper
    all_results = instantly_results + serper_results

    seen_domains: set = set()
    deduped: List[Dict] = []
    for item in all_results:
        url = item.get("url", "")
        if not url:
            # No URL — include if it has at least a title (Instantly company-only results)
            if item.get("title"):
                deduped.append(item)
            continue
        domain = _get_domain(url)
        if domain and domain not in seen_domains:
            seen_domains.add(domain)
            deduped.append(item)
        elif not domain:
            deduped.append(item)

    logger.info(
        f"[MultiSource] {instantly_count} instantly + {serper_count} serper "
        f"= {len(deduped)} unique candidates for '{keyword}'"
    )
    return deduped


# ── Expanded fallback: 90+ real Indian companies ─────────────────────────────
# Shuffled randomly on every call so offline runs get different companies each time.

_ALL_FALLBACK_COMPANIES: List[Dict] = [

    # ── Automobile & Auto Parts ────────────────────────────────────────────────
    {
        "title": "Ashok Leyland - Commercial Vehicles Manufacturer India",
        "url": "https://www.ashokleyland.com",
        "snippet": "Ashok Leyland is India's second-largest commercial vehicle manufacturer, headquartered in Chennai. 15,000+ employees across plants in Hosur, Pantnagar, and Ennore. Complex shop-floor workforce, shift scheduling, and multi-plant payroll compliance.",
    },
    {
        "title": "TVS Motor Company - Two-Wheeler Manufacturer India",
        "url": "https://www.tvsmotor.com",
        "snippet": "TVS Motor Company is one of India's top two-wheeler manufacturers, headquartered in Chennai. 7,000+ employees across plants in Hosur, Mysuru, and Himachal Pradesh. Factory HR, shift scheduling, and dealer network workforce management.",
    },
    {
        "title": "Minda Industries - Auto Components Manufacturer India",
        "url": "https://www.mindasystems.com",
        "snippet": "Minda Industries is a leading auto components manufacturer with 23,000+ employees across 70+ plants. Headquartered in Gurugram. Large blue-collar workforce requiring attendance management and statutory compliance.",
    },
    {
        "title": "Endurance Technologies - Auto Components Aurangabad India",
        "url": "https://www.enduranceindia.com",
        "snippet": "Endurance Technologies manufactures aluminum die-casting and braking products. 8,000+ employees across Aurangabad and Pune. Multi-location workforce and payroll compliance for manufacturing.",
    },
    {
        "title": "Bharat Forge - Advanced Manufacturing Pune India",
        "url": "https://www.bharatforge.com",
        "snippet": "Bharat Forge is a global leader in forgings with 13,000+ employees globally. Headquartered in Pune. Multi-country payroll, engineering workforce management, and performance tracking.",
    },
    {
        "title": "Sundaram-Clayton - Die Casting Company Chennai India",
        "url": "https://www.sundaramclayton.com",
        "snippet": "Sundaram-Clayton manufactures aluminum die castings for automotive OEMs. Headquartered in Chennai with 3,000+ employees. Factory attendance, skills matrix, and multi-shift HR operations.",
    },
    {
        "title": "Motherson Sumi Systems - Auto Wiring India",
        "url": "https://www.mothersonsumi.com",
        "snippet": "Motherson Sumi Systems is one of India's largest auto component manufacturers with 160,000+ employees globally. Workforce management across plants in India, Europe, and Americas — payroll, compliance, and onboarding at scale.",
    },
    {
        "title": "Balkrishna Industries - BKT Tyres Manufacturer India",
        "url": "https://www.bkt-tires.com",
        "snippet": "Balkrishna Industries (BKT) is a global leader in off-highway tyres, headquartered in Mumbai. 11,000+ employees across plants in Rajkot and Bhuj. Large factory workforce requiring shift scheduling and compliance.",
    },
    {
        "title": "CEAT Tyres - Tyre Manufacturer Mumbai India",
        "url": "https://www.ceat.com",
        "snippet": "CEAT is a leading tyre manufacturer, part of RPG Group. Headquartered in Mumbai. 10,000+ employees across plants in Nashik, Bhandup, and Halol. Multi-plant HR operations and workforce compliance.",
    },
    {
        "title": "Apollo Tyres - Tyre Manufacturer India",
        "url": "https://www.apollotyres.com",
        "snippet": "Apollo Tyres is one of India's largest tyre companies with operations globally. 16,000+ employees. Managing factory workers, global payroll, and multi-country HR compliance.",
    },

    # ── Pharmaceutical / Biotech ───────────────────────────────────────────────
    {
        "title": "Cipla Limited - Pharmaceutical Company Mumbai India",
        "url": "https://www.cipla.com",
        "snippet": "Cipla is a global pharmaceutical company headquartered in Mumbai with 25,000+ employees. Manufacturing plants across India and international markets. GMP compliance, shift management, and multi-site HR operations.",
    },
    {
        "title": "Aurobindo Pharma - Pharmaceutical Manufacturer Hyderabad",
        "url": "https://www.aurobindo.com",
        "snippet": "Aurobindo Pharma is one of India's largest generic pharma companies with 25,000+ employees. Based in Hyderabad with multiple API and formulation plants. Large workforce requiring shift management and statutory compliance.",
    },
    {
        "title": "Torrent Pharmaceuticals - Pharma Company Ahmedabad India",
        "url": "https://www.torrentpharma.com",
        "snippet": "Torrent Pharmaceuticals is a leading pharma company headquartered in Ahmedabad with 14,000+ employees. Multi-site HR operations, appraisals, and pharmaceutical compliance.",
    },
    {
        "title": "Alkem Laboratories - Pharmaceutical Company Mumbai India",
        "url": "https://www.alkemlab.com",
        "snippet": "Alkem Laboratories is a leading Indian pharma company headquartered in Mumbai. 16,000+ employees including a large field sales force. HR challenges include field force management, appraisals, and incentive tracking.",
    },
    {
        "title": "IPCA Laboratories - Pharma Manufacturer India",
        "url": "https://www.ipca.com",
        "snippet": "IPCA Laboratories manufactures pharmaceutical formulations and APIs with 10,000+ employees across Mumbai and Ratlam plants. Managing large pharmaceutical workforce with compliance and shift management.",
    },
    {
        "title": "Gland Pharma - Injectables Manufacturer Hyderabad India",
        "url": "https://www.glandpharma.com",
        "snippet": "Gland Pharma is a leading manufacturer of injectables based in Hyderabad. 5,000+ employees. Managing pharma manufacturing workforce, quality compliance staff, and R&D teams.",
    },

    # ── FMCG / Food / Consumer Goods ───────────────────────────────────────────
    {
        "title": "Marico Limited - FMCG Company Mumbai India",
        "url": "https://marico.com",
        "snippet": "Marico is a leading consumer goods company with brands like Parachute and Saffola. 5,000+ employees. Sales force management, manufacturing workforce, and performance management.",
    },
    {
        "title": "Dabur India - FMCG Company Ghaziabad India",
        "url": "https://www.dabur.com",
        "snippet": "Dabur India is a leading FMCG company with 9,000+ employees. Headquartered in Ghaziabad with plants across India. Managing large sales force, factory workforce, and compliance across states.",
    },
    {
        "title": "Emami Limited - FMCG Company Kolkata India",
        "url": "https://www.emamigroup.com",
        "snippet": "Emami Limited is a leading FMCG company based in Kolkata with brands like Zandu. 6,500+ employees. Sales force HR, incentive tracking, and multi-location operations.",
    },
    {
        "title": "Britannia Industries - Food Company Bengaluru India",
        "url": "https://www.britannia.co.in",
        "snippet": "Britannia Industries is one of India's largest food companies with 4,000+ employees. Manufacturing plants across India. Managing factory workforce, payroll, and distribution HR.",
    },
    {
        "title": "Haldiram's - Snack Food Manufacturer India",
        "url": "https://www.haldirams.com",
        "snippet": "Haldiram's is India's largest snack food manufacturer with operations in Delhi and Nagpur. 10,000+ employees. Large workforce management for factory and retail staff.",
    },
    {
        "title": "Godrej Consumer Products - FMCG Mumbai India",
        "url": "https://www.godrejconsumerproducts.com",
        "snippet": "Godrej Consumer Products is a leading FMCG company with 11,000+ employees. Mumbai-based with India and Africa operations. Sales force management, multi-country payroll, and performance tracking.",
    },
    {
        "title": "Parle Products - Biscuit and Food Company India",
        "url": "https://www.parleproducts.com",
        "snippet": "Parle Products is one of India's largest FMCG companies making biscuits and confectionery. 10,000+ employees across plants in Mumbai, Bengaluru, and other cities. Factory workforce management and compliance.",
    },
    {
        "title": "MTR Foods - Food Company Bengaluru India",
        "url": "https://www.mtrfoods.com",
        "snippet": "MTR Foods is a leading packaged food brand based in Bengaluru. 3,000+ employees. Managing food processing plant workers, quality compliance, and sales workforce.",
    },
    {
        "title": "Amul (GCMMF) - Dairy Cooperative Gujarat India",
        "url": "https://www.amul.com",
        "snippet": "GCMMF (Amul) is India's largest dairy cooperative based in Anand, Gujarat. 5,000+ direct employees and a massive distribution network. HR management for processing plants, logistics, and admin staff.",
    },

    # ── Logistics / Supply Chain ───────────────────────────────────────────────
    {
        "title": "Blue Dart Express - Courier and Logistics India",
        "url": "https://www.bluedart.com",
        "snippet": "Blue Dart is India's leading express air and integrated transportation company. 12,000+ employees. Large delivery workforce management, attendance tracking, and performance management.",
    },
    {
        "title": "VRL Logistics - Road Transport Hubballi India",
        "url": "https://www.vrlgroup.in",
        "snippet": "VRL Logistics is one of India's largest road transport companies based in Hubballi. 22,000+ employees including truck drivers. Managing driver payroll, attendance, compliance, and multi-state operations.",
    },
    {
        "title": "Allcargo Logistics - Integrated Logistics India",
        "url": "https://www.allcargo.com",
        "snippet": "Allcargo Logistics is India's largest integrated logistics company with 15,000+ employees. HR challenges include managing workforce at 300+ locations across logistics, warehousing, and CFS.",
    },
    {
        "title": "Gati Limited - Express Logistics India",
        "url": "https://www.gati.com",
        "snippet": "Gati is a pioneer in express distribution and supply chain in India. 7,000+ employees across Pan-India network. Managing delivery workforce, payroll, and state-wise compliance.",
    },
    {
        "title": "Transport Corporation of India (TCI) - Logistics India",
        "url": "https://www.tcil.com",
        "snippet": "TCI is one of India's largest integrated supply chain and logistics companies with 13,000+ employees. Managing truck drivers, warehouse staff across 1,400+ offices.",
    },
    {
        "title": "Safexpress - Logistics and Supply Chain Gurugram India",
        "url": "https://www.safexpress.com",
        "snippet": "Safexpress is a leading logistics company based in Gurugram with 10,000+ employees. HR challenges include field workforce, drivers, and warehouse staff management across India.",
    },
    {
        "title": "Ecom Express - E-Commerce Logistics India",
        "url": "https://www.ecomexpress.in",
        "snippet": "Ecom Express is a pure-play e-commerce logistics company with 35,000+ employees. Managing large delivery workforce, attendance, payroll, and compliance across 2700+ pin codes.",
    },
    {
        "title": "Rivigo - Digital Trucking Company Gurugram India",
        "url": "https://www.rivigo.com",
        "snippet": "Rivigo is a digital-first logistics company with 4,000+ employees and relay truckers. HR challenges include driver management, relay model compliance, and tech-enabled workforce tracking.",
    },

    # ── Healthcare / Hospitals ─────────────────────────────────────────────────
    {
        "title": "Narayana Health - Hospital Chain Bengaluru India",
        "url": "https://www.narayanahealth.org",
        "snippet": "Narayana Health is one of India's largest hospital chains with 32 hospitals and 15,000+ employees. Clinical staff scheduling, compliance, and payroll across hospitals and clinics.",
    },
    {
        "title": "Aster DM Healthcare - Hospital Group India",
        "url": "https://www.asterdmhealthcare.com",
        "snippet": "Aster DM Healthcare operates hospitals, clinics, and pharmacies across India and GCC. 18,000+ employees. Complex multi-country HR operations and clinical staff management.",
    },
    {
        "title": "HCG Hospitals - Oncology Hospital Bengaluru India",
        "url": "https://www.hcgoncology.com",
        "snippet": "HCG is India's largest cancer care specialist with 22 cancer centres. 5,000+ employees including oncologists and nurses. Clinical workforce management and credentials tracking.",
    },
    {
        "title": "Manipal Hospitals - Multi-Specialty Hospital India",
        "url": "https://www.manipalhospitals.com",
        "snippet": "Manipal Hospitals is a leading multi-specialty hospital chain with 15,000+ employees. HR challenges include clinical staff scheduling, credential management, and payroll compliance.",
    },
    {
        "title": "Yashoda Hospitals - Multi-Specialty Hospital Hyderabad",
        "url": "https://www.yashodahospitals.com",
        "snippet": "Yashoda Hospitals is a leading multi-specialty hospital chain in Hyderabad with 5,000+ employees. Nursing staff management, doctor scheduling, and compliance for healthcare workforce.",
    },
    {
        "title": "Care Hospitals - Multi-Specialty Hospital Group India",
        "url": "https://www.carehospitals.com",
        "snippet": "Care Hospitals is a leading multi-specialty hospital group with 8,000+ employees across Hyderabad and India. HR challenges include clinical workforce management and compliance.",
    },
    {
        "title": "Global Hospitals - Multi-Specialty Hospital India",
        "url": "https://www.globalhospitalsindia.com",
        "snippet": "Global Hospitals is a leading multi-specialty hospital chain with 4,000+ employees. Managing clinical and administrative staff across hospitals in Chennai, Mumbai, and Hyderabad.",
    },

    # ── IT Services (mid-size) ─────────────────────────────────────────────────
    {
        "title": "Mphasis - IT Services Company Bengaluru India",
        "url": "https://www.mphasis.com",
        "snippet": "Mphasis is a global IT company specializing in cloud and cognitive services with 35,000+ employees. Multi-geography payroll, talent management, and high attrition management.",
    },
    {
        "title": "Hexaware Technologies - IT and BPO Mumbai India",
        "url": "https://hexaware.com",
        "snippet": "Hexaware Technologies is a global IT and BPO company based in Mumbai. 28,000+ employees. IT services and digital transformation with HR challenges including attrition and multi-geography compliance.",
    },
    {
        "title": "Zensar Technologies - IT Services Pune India",
        "url": "https://www.zensar.com",
        "snippet": "Zensar Technologies is a mid-size IT company based in Pune with 10,000+ employees. Software services, delivery centers, and multi-country compliance management.",
    },
    {
        "title": "Persistent Systems - Software Company Pune India",
        "url": "https://www.persistent.com",
        "snippet": "Persistent Systems is a technology company based in Pune with 22,000+ employees. Product engineering and digital transformation. High attrition, talent management, and global HR compliance.",
    },
    {
        "title": "Cyient - Engineering Services Hyderabad India",
        "url": "https://www.cyient.com",
        "snippet": "Cyient is a global engineering services company based in Hyderabad. 15,000+ employees across India and international locations. Multi-geography HR operations and engineering talent management.",
    },
    {
        "title": "Quess Corp - Workforce Solutions Bengaluru India",
        "url": "https://quesscorp.com",
        "snippet": "Quess Corp is India's largest business services provider with 400,000+ managed associates. Headquartered in Bengaluru. Managing massive contract workforce requires advanced HRMS for compliance, payroll, and tracking.",
    },
    {
        "title": "TeamLease Services - Staffing Company India",
        "url": "https://www.teamlease.com",
        "snippet": "TeamLease is India's largest staffing company with 300,000+ associates on payroll. Managing distributed workforce across 3,000+ clients. HRMS needed for payroll, compliance, and workforce analytics.",
    },
    {
        "title": "Newgen Software - IT Product Company New Delhi India",
        "url": "https://www.newgensoft.com",
        "snippet": "Newgen Software is an enterprise software company headquartered in New Delhi. 4,000+ employees. Managing software development workforce, performance appraisals, and multi-location HR.",
    },
    {
        "title": "Sonata Software - IT Services Bengaluru India",
        "url": "https://www.sonata-software.com",
        "snippet": "Sonata Software is a global IT services company headquartered in Bengaluru. 6,000+ employees. IT services and platform transformation. HR challenges include talent retention and performance management.",
    },
    {
        "title": "NIIT Technologies - IT Services India",
        "url": "https://www.niit-tech.com",
        "snippet": "NIIT Technologies is a mid-size IT services company with 10,000+ employees. Based in Noida with delivery centers across India. Managing IT workforce, bench management, and multi-location payroll.",
    },

    # ── Construction / Real Estate / Infrastructure ────────────────────────────
    {
        "title": "Prestige Estates - Real Estate Developer Bengaluru India",
        "url": "https://www.prestigeconstructions.com",
        "snippet": "Prestige Estates is one of India's largest real estate developers with 8,000+ employees. Managing construction workforce, contract labour compliance, and corporate staff HR.",
    },
    {
        "title": "Brigade Group - Real Estate Developer Bengaluru India",
        "url": "https://www.brigadegroup.com",
        "snippet": "Brigade Group is a leading real estate developer with 3,500+ employees. Residential, commercial, and hospitality projects. Managing construction workforce and project HR.",
    },
    {
        "title": "Sobha Limited - Real Estate Developer Bengaluru India",
        "url": "https://www.sobha.com",
        "snippet": "Sobha Limited is a leading real estate developer with 5,000+ employees. Backward-integrated company managing construction, interiors, and admin workforce payroll.",
    },
    {
        "title": "Kolte-Patil Developers - Real Estate Pune India",
        "url": "https://www.koltepatil.com",
        "snippet": "Kolte-Patil is a leading real estate developer based in Pune with 2,000+ employees. Managing construction and corporate workforce across Pune, Mumbai, and Bengaluru.",
    },
    {
        "title": "NCC Limited - Infrastructure Company Hyderabad India",
        "url": "https://www.nccltd.in",
        "snippet": "NCC Limited is a leading infrastructure and construction EPC company with 10,000+ employees. Managing large project and contract workforce compliance across India and Gulf.",
    },
    {
        "title": "KEC International - Infrastructure EPC India",
        "url": "https://www.kecrpg.com",
        "snippet": "KEC International is a global infrastructure EPC company with 20,000+ employees across power transmission, railways, and civil projects. Complex multi-country workforce management.",
    },
    {
        "title": "Thermax - Energy and Environment Company Pune India",
        "url": "https://www.thermaxglobal.com",
        "snippet": "Thermax is a leading energy and environment solutions company based in Pune with 8,000+ employees. Engineering and project-based workforce management across multiple locations.",
    },

    # ── Textile / Garment ──────────────────────────────────────────────────────
    {
        "title": "Raymond Limited - Textile Company Mumbai India",
        "url": "https://www.raymond.in",
        "snippet": "Raymond is one of India's most trusted textile brands with 30,000+ employees. Manufacturing in Vapi and Chhindwara. Managing large factory workforce, retail staff, and corporate employees.",
    },
    {
        "title": "Arvind Limited - Textile Company Ahmedabad India",
        "url": "https://arvind.com",
        "snippet": "Arvind Limited is one of India's largest textile companies based in Ahmedabad with 30,000+ employees. Managing garment manufacturing workforce across multiple plants and retail formats.",
    },
    {
        "title": "Vardhman Textiles - Textile Manufacturer Ludhiana India",
        "url": "https://www.vardhman.com",
        "snippet": "Vardhman Textiles is a leading textile manufacturer based in Ludhiana with 25,000+ employees. Spinning, weaving, and processing units. Large factory workforce with shift scheduling.",
    },
    {
        "title": "KPR Mill - Garment Manufacturer Coimbatore India",
        "url": "https://www.kprmill.com",
        "snippet": "KPR Mill is an integrated apparel manufacturer based in Coimbatore with 20,000+ employees. Large worker housing facility requiring shift scheduling, dormitory compliance, and payroll.",
    },
    {
        "title": "Welspun India - Home Textiles Manufacturer India",
        "url": "https://www.welspunindia.com",
        "snippet": "Welspun India is a leading home textile manufacturer based in Mumbai with 20,000+ employees across Gujarat plants. Managing large factory workforce and global export compliance.",
    },
    {
        "title": "Trident Group - Textile and Paper Company India",
        "url": "https://www.tridentindia.com",
        "snippet": "Trident Group is a leading textile and paper manufacturer based in Ludhiana. 12,000+ employees. Managing spinning mills, weaving plants, and paper manufacturing workforce.",
    },

    # ── Specialty Chemicals ────────────────────────────────────────────────────
    {
        "title": "Pidilite Industries - Specialty Chemicals Mumbai India",
        "url": "https://www.pidilite.com",
        "snippet": "Pidilite Industries is India's leading manufacturer of adhesives (Fevicol) with 8,000+ employees. Managing sales force, factory workers, and corporate staff across India.",
    },
    {
        "title": "Aarti Industries - Specialty Chemicals Vapi India",
        "url": "https://www.aartiindustries.com",
        "snippet": "Aarti Industries is a leading specialty chemicals company based in Vapi, Gujarat with 5,000+ employees. Chemical plant workers, safety compliance, and multi-site payroll.",
    },
    {
        "title": "SRF Limited - Multi-Business Company Gurugram India",
        "url": "https://www.srf.com",
        "snippet": "SRF Limited is a diversified chemicals and textiles company based in Gurugram with 6,000+ employees. Chemicals, fluorochemicals, and packaging films — multi-division HR management.",
    },
    {
        "title": "Deepak Nitrite - Specialty Chemicals Vadodara India",
        "url": "https://www.deepaknitrite.com",
        "snippet": "Deepak Nitrite is a specialty chemicals manufacturer based in Vadodara with 2,500+ employees. Chemical plant workforce compliance, safety, and multi-location payroll.",
    },
    {
        "title": "Vinati Organics - Specialty Chemicals Mumbai India",
        "url": "https://www.vinatiorganics.com",
        "snippet": "Vinati Organics is a leading specialty chemicals company based in Mumbai with 1,000+ employees. Managing chemical plant workers, R&D staff, and export compliance.",
    },

    # ── Retail ─────────────────────────────────────────────────────────────────
    {
        "title": "Shoppers Stop - Retail Chain Mumbai India",
        "url": "https://www.shoppersstop.com",
        "snippet": "Shoppers Stop is a leading retail chain with 100+ stores across India. 15,000+ retail employees. Managing store staff, visual merchandising teams, and HO employees with retail-specific HRMS.",
    },
    {
        "title": "V-Mart Retail - Value Fashion Retail India",
        "url": "https://www.vmart.co.in",
        "snippet": "V-Mart is a value fashion retailer with 350+ stores across Tier-2 and Tier-3 India. 10,000+ employees. High attrition management, store onboarding, and multi-location payroll.",
    },
    {
        "title": "Bata India - Footwear Retail Company India",
        "url": "https://www.bata.in",
        "snippet": "Bata India is India's largest footwear retailer with 1,500+ stores. 10,000+ employees including retail staff and manufacturing workers. Retail workforce management and manufacturing compliance.",
    },
    {
        "title": "Metro Brands - Footwear Retail India",
        "url": "https://www.metrobrands.com",
        "snippet": "Metro Brands is a leading footwear specialty retail company with 800+ stores and 5,000+ employees. Managing retail store staff, buying teams, and logistics workforce.",
    },
    {
        "title": "Croma - Electronics Retail India",
        "url": "https://www.croma.com",
        "snippet": "Croma is India's largest electronics retail chain, part of Tata Group. 8,000+ employees across 200+ stores. Managing retail and service staff workforce across India.",
    },

    # ── Education / Training ───────────────────────────────────────────────────
    {
        "title": "Aakash Educational Services - Coaching India",
        "url": "https://www.aakash.ac.in",
        "snippet": "Aakash Educational Services is India's leading test preparation company with 300+ centres. 10,000+ employees including faculty and admin staff. Faculty scheduling, performance tracking, and multi-centre payroll.",
    },
    {
        "title": "NIIT Limited - Training and Education India",
        "url": "https://www.niit.com",
        "snippet": "NIIT Limited is a leading skills and talent development company with 6,000+ employees. Managing training instructors, corporate learning programs, and multi-location operations.",
    },
    {
        "title": "Manipal Academy of Higher Education - University India",
        "url": "https://manipal.edu",
        "snippet": "Manipal Academy is one of India's leading private universities with 26,000+ faculty and staff. Managing academic and non-academic staff across Manipal, Bengaluru, and Jaipur campuses.",
    },
    {
        "title": "LPU - Lovely Professional University India",
        "url": "https://www.lpu.in",
        "snippet": "Lovely Professional University is India's largest private university with 3,000+ faculty and staff. Managing academic scheduling, appraisals, and faculty payroll compliance.",
    },

    # ── Banking / Finance / NBFC ───────────────────────────────────────────────
    {
        "title": "Bajaj Finance - NBFC Pune India",
        "url": "https://www.bajajfinserv.in",
        "snippet": "Bajaj Finance is India's largest NBFC with 40,000+ employees. Based in Pune. Managing large sales force, branch staff, and collections teams with performance-linked incentives.",
    },
    {
        "title": "Muthoot Finance - Gold Loan NBFC Kochi India",
        "url": "https://www.muthootfinance.com",
        "snippet": "Muthoot Finance is India's largest gold loan company based in Kochi. 30,000+ employees across 5,000+ branches. Managing large branch staff network, payroll, and compliance across states.",
    },
    {
        "title": "IIFL Finance - NBFC India",
        "url": "https://www.iifl.com",
        "snippet": "IIFL Finance is a leading NBFC with 25,000+ employees across branches. HR challenges include managing sales force, compliance training, and branch payroll.",
    },
    {
        "title": "Cholamandalam Finance - NBFC Chennai India",
        "url": "https://www.cholamandalam.com",
        "snippet": "Cholamandalam Investment and Finance is a leading NBFC headquartered in Chennai. 15,000+ employees. Vehicle finance with large field sales force requiring incentive and performance management.",
    },

    # ── Hotels / Hospitality ───────────────────────────────────────────────────
    {
        "title": "Lemon Tree Hotels - Mid-Scale Hotel Chain India",
        "url": "https://www.lemontreehotels.com",
        "snippet": "Lemon Tree Hotels is India's largest mid-scale hotel chain with 7,500+ employees. Managing hotel operations, housekeeping, F&B, and front desk staff across 85+ hotels.",
    },
    {
        "title": "Club Mahindra - Resort Chain India",
        "url": "https://www.clubmahindra.com",
        "snippet": "Club Mahindra is India's leading leisure hospitality company with 60+ resorts and 8,000+ employees. Managing hospitality workforce, seasonal staffing, and multi-resort payroll.",
    },

    # ── Power / Energy ─────────────────────────────────────────────────────────
    {
        "title": "Tata Power - Power Company Mumbai India",
        "url": "https://www.tatapower.com",
        "snippet": "Tata Power is India's largest integrated power company with 15,000+ employees. Power generation, transmission, and distribution. Managing multi-location technical and administrative staff.",
    },
    {
        "title": "JSW Energy - Power Company India",
        "url": "https://www.jsw.in/energy",
        "snippet": "JSW Energy is a leading power company with 3,000+ employees across power plants in India. Managing technical workforce, plant operators, and compliance for power generation operations.",
    },

    # ── Agri / Fertilizers ─────────────────────────────────────────────────────
    {
        "title": "Coromandel International - Agri Solutions Hyderabad India",
        "url": "https://www.coromandel.biz",
        "snippet": "Coromandel International is a leading agri-solutions company based in Hyderabad with 3,500+ employees. Manufacturing workforce, field staff, and retailer network HR management.",
    },
    {
        "title": "PI Industries - Agrochemicals Udaipur India",
        "url": "https://www.piindustries.com",
        "snippet": "PI Industries is a leading agrochemical company based in Udaipur with 5,000+ employees. Managing manufacturing plant workers, R&D staff, and field sales force.",
    },
    {
        "title": "Chambal Fertilizers - Fertilizer Company Kota India",
        "url": "https://www.chambal.com",
        "snippet": "Chambal Fertilizers is a leading fertilizer producer based in Kota, Rajasthan with 2,500+ employees. Managing factory workers, technical staff, and administrative payroll compliance.",
    },
    {
        "title": "UPL Limited - Agrochemicals Company India",
        "url": "https://www.upl-ltd.com",
        "snippet": "UPL Limited is a global crop protection company headquartered in Mumbai. 13,000+ employees globally. Multi-country payroll, field sales management, and manufacturing workforce compliance.",
    },

    # ── Established Large Caps (kept at the end so they don't dominate every run) ──
    {
        "title": "Tata Consultancy Services (TCS) - IT Services India",
        "url": "https://www.tcs.com",
        "snippet": "TCS is India's largest IT services company with 600,000+ employees. Headquartered in Mumbai. Manages complex HR workflows across 50+ countries.",
    },
    {
        "title": "Infosys - Global IT Consulting and Services",
        "url": "https://www.infosys.com",
        "snippet": "Infosys is a global leader in IT services with 330,000+ employees based in Bengaluru. Complex payroll, compliance, and talent management across geographies.",
    },
    {
        "title": "Wipro Technologies - IT and Software Company India",
        "url": "https://www.wipro.com",
        "snippet": "Wipro is a leading global IT company based in Bengaluru. 250,000+ employees across 65 countries. Large workforce requiring unified HRMS for compliance and performance tracking.",
    },
    {
        "title": "Mahindra & Mahindra - Automotive Company Mumbai India",
        "url": "https://www.mahindra.com",
        "snippet": "Mahindra & Mahindra is a multinational automotive company with 200,000+ employees. Complex HR needs including factory workers, office staff, and international teams.",
    },
    {
        "title": "Bajaj Auto - Two-Wheeler Manufacturer Pune India",
        "url": "https://www.bajajauto.com",
        "snippet": "Bajaj Auto is one of India's leading two-wheeler manufacturers. 10,000+ employees across manufacturing plants. Attendance, shift scheduling, and compliance for blue-collar workforce.",
    },
    {
        "title": "Reliance Industries - Conglomerate India",
        "url": "https://www.ril.com",
        "snippet": "Reliance Industries is India's largest private sector company. 236,000+ employees across oil, retail, telecom, and media. Multi-division workforce management and payroll.",
    },
]


def _get_fallback_companies(keyword: str, max_results: int = 50) -> List[Dict]:
    """
    Return a shuffled subset of the curated Indian company list.

    Uses a fresh random shuffle on every call so repeated pipeline runs
    surface different companies even without Serper configured.

    Relevance filtering is applied first (keyword-matching companies appear
    at the front), but the shuffle ensures global variety.
    """
    kw_lower = keyword.lower()
    kw_words = [w for w in kw_lower.split() if len(w) > 3]

    # Split into keyword-relevant and other
    relevant = [
        c for c in _ALL_FALLBACK_COMPANIES
        if any(w in c["snippet"].lower() or w in c["title"].lower() for w in kw_words)
    ]
    other = [c for c in _ALL_FALLBACK_COMPANIES if c not in relevant]

    # Shuffle each group independently
    random.shuffle(relevant)
    random.shuffle(other)

    combined = relevant + other
    logger.info(
        f"[Fallback] {len(relevant)} relevant + {len(other)} other = "
        f"{len(combined)} total, returning {min(max_results, len(combined))}"
    )
    return combined[:max_results]


# ── Company website scraping ──────────────────────────────────────────────────

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

    for path in ["/contact", "/contact-us", "/about", "/about-us"]:
        try:
            contact_url = urljoin(url.rstrip("/"), path)
            _, contact_text = _fetch_text(contact_url, timeout=6)
            combined_text += "\n" + contact_text
            break
        except Exception:
            continue

    return combined_text[:4000]


def scrape_company_contacts(url: str) -> Dict:
    """
    Extract emails, phone numbers, and address from a company website.
    Scans homepage + contact page raw HTML before BeautifulSoup strips anything.
    Returns dict: {emails, phone, address}
    """
    all_emails: List[str] = []
    all_phones: List[str] = []
    address_hint = ""

    for path in ["", "/contact", "/contact-us", "/about", "/about-us"]:
        target = urljoin(url.rstrip("/"), path) if path else url
        try:
            raw_html, clean_text = _fetch_text(target, timeout=6)
            all_emails += extract_emails(raw_html)
            phone = extract_phone(clean_text)
            if phone and not all_phones:
                all_phones.append(phone)
            if not address_hint:
                # Try multiple address label patterns, most specific first
                for addr_pattern in [
                    r"(?:Registered\s+(?:Office|Address)|Corporate\s+(?:Office|Address))\s*[:\-]\s*([^\n<]{15,150})",
                    r"(?:Head\s+Office|Headquarters|HQ)\s*[:\-]\s*([^\n<]{15,150})",
                    r"(?:Address|Office\s+Address)\s*[:\-]\s*([^\n<]{15,150})",
                ]:
                    addr_match = re.search(addr_pattern, clean_text, re.I)
                    if addr_match:
                        candidate = _validate_address(addr_match.group(1))
                        if candidate:
                            address_hint = candidate
                            break
        except Exception:
            continue

    seen = []
    for e in all_emails:
        if e not in seen:
            seen.append(e)

    return {
        "emails": seen[:5],
        "phone": all_phones[0] if all_phones else "",
        "address": address_hint,
    }
