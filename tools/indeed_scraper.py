"""
Indeed.in Lead Scraper
-----------------------
Finds companies actively hiring for HR/HRMS roles on Indeed India.
Companies posting HR Manager, Payroll, or HR Operations jobs
are prime HRMS software prospects -- they have active HR hiring budgets.

Returns company names + websites as potential leads.
Always fails safe: returns [] on any error, never raises.
"""
import requests
from bs4 import BeautifulSoup
from loguru import logger


INDEED_URL = "https://in.indeed.com/jobs?q=hr+manager&l=India"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def search_indeed_companies() -> list[dict]:
    """
    Scrape Indeed India for companies hiring in HR/HRMS roles.
    Returns a list of dicts with company name, url, and source.
    Returns [] on any error -- never raises.
    """
    try:
        resp = requests.get(INDEED_URL, headers=HEADERS, timeout=10)

        if resp.status_code in (403, 429):
            logger.warning(
                f"[IndeedScraper] Blocked by Indeed (HTTP {resp.status_code}), returning []"
            )
            return []

        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        companies = []
        seen_names = set()

        # Indeed job cards use data-testid attributes and class-based selectors
        candidate_selectors = [
            {"name": "span", "attrs": {"data-testid": "company-name"}},
            {"name": "span", "class_": lambda c: c and "companyName" in " ".join(c)},
            {"name": "a", "class_": lambda c: c and "companyName" in " ".join(c)},
            {"name": "div", "class_": lambda c: c and "company_location" in " ".join(c)},
        ]

        for selector in candidate_selectors:
            if "attrs" in selector:
                elements = soup.find_all(selector["name"], attrs=selector["attrs"])
            else:
                elements = soup.find_all(selector["name"], class_=selector["class_"])

            for el in elements:
                company_name = el.get_text(strip=True)
                if not company_name or company_name.lower() in seen_names:
                    continue

                seen_names.add(company_name.lower())

                # Use href if available and external, otherwise construct a Google search URL
                href = el.get("href", "")
                if href and href.startswith("http") and "indeed.com" not in href:
                    company_url = href
                else:
                    company_url = (
                        f"https://www.google.com/search?q={company_name.replace(' ', '+')}+official+site"
                    )

                companies.append({
                    "company": company_name,
                    "url": company_url,
                    "source": "indeed",
                })

        if not companies:
            logger.warning(
                "[IndeedScraper] No company elements matched -- page structure may have changed"
            )

        logger.info(f"[IndeedScraper] Extracted {len(companies)} companies from Indeed")
        return companies

    except requests.exceptions.Timeout:
        logger.warning("[IndeedScraper] Request timed out, returning []")
        return []
    except Exception as e:
        logger.warning(f"[IndeedScraper] Unexpected error: {e}, returning []")
        return []
