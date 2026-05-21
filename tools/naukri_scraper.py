"""
Naukri.com Lead Scraper
------------------------
Finds companies actively hiring for HR/HRMS roles on Naukri.com.
Companies posting HR Manager, HRIS, Payroll Manager, HR Operations roles
are prime HRMS software prospects -- they have active HR hiring budgets.

Returns company names + websites as potential leads.
Always fails safe: returns [] on any error, never raises.
"""
import requests
from bs4 import BeautifulSoup
from loguru import logger


NAUKRI_URL = "https://www.naukri.com/hr-jobs-in-india"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def search_naukri_companies() -> list[dict]:
    """
    Scrape Naukri.com for companies hiring in HR/HRMS roles.
    Returns a list of dicts with company name, url, and source.
    Returns [] on any error -- never raises.
    """
    try:
        resp = requests.get(NAUKRI_URL, headers=HEADERS, timeout=10)

        if resp.status_code in (403, 429):
            logger.warning(
                f"[NaukriScraper] Blocked by Naukri (HTTP {resp.status_code}), returning []"
            )
            return []

        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        companies = []
        seen_names = set()

        # Naukri job cards use various class patterns; try multiple selectors
        # Primary: article tags or divs with job-related class names
        candidate_selectors = [
            {"name": "a", "class_": lambda c: c and "comp-name" in " ".join(c)},
            {"name": "span", "class_": lambda c: c and "comp-name" in " ".join(c)},
            {"name": "div", "class_": lambda c: c and "comp-name" in " ".join(c)},
            {"name": "a", "class_": lambda c: c and "companyName" in " ".join(c)},
            {"name": "span", "class_": lambda c: c and "companyName" in " ".join(c)},
        ]

        for selector in candidate_selectors:
            elements = soup.find_all(selector["name"], class_=selector["class_"])
            for el in elements:
                company_name = el.get_text(strip=True)
                if not company_name or company_name.lower() in seen_names:
                    continue

                seen_names.add(company_name.lower())

                # Use href if it looks like a company page, otherwise construct a Google search URL
                href = el.get("href", "")
                if href and href.startswith("http") and "naukri.com" not in href:
                    company_url = href
                else:
                    company_url = (
                        f"https://www.google.com/search?q={company_name.replace(' ', '+')}+official+site"
                    )

                companies.append({
                    "company": company_name,
                    "url": company_url,
                    "source": "naukri",
                })

        if not companies:
            logger.warning(
                "[NaukriScraper] No company elements matched -- page structure may have changed"
            )

        logger.info(f"[NaukriScraper] Extracted {len(companies)} companies from Naukri")
        return companies

    except requests.exceptions.Timeout:
        logger.warning("[NaukriScraper] Request timed out, returning []")
        return []
    except Exception as e:
        logger.warning(f"[NaukriScraper] Unexpected error: {e}, returning []")
        return []
