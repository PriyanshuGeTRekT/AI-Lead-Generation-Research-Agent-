"""
Scrapes humanmaximizer.com to build the RAG knowledge base.
This gives our agents domain knowledge about HRMS software
so they can identify relevant leads and craft better outreach.
"""
import requests
import time
from typing import List, Dict
from bs4 import BeautifulSoup
from loguru import logger


SEED_URLS = [
    "https://www.humanmaximizer.com",
    "https://www.humanmaximizer.com/features",
    "https://www.humanmaximizer.com/about",
    "https://www.humanmaximizer.com/pricing",
    "https://www.humanmaximizer.com/contact",
]


def scrape_page(url: str) -> Dict:
    """Scrape a single page and return structured content."""
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code != 200:
            return {"url": url, "content": "", "error": f"HTTP {resp.status_code}"}

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove noise
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        title = soup.title.string if soup.title else url
        content = soup.get_text(separator="\n", strip=True)

        return {
            "url": url,
            "title": title,
            "content": content[:5000],  # Cap per page
            "error": None,
        }
    except Exception as e:
        return {"url": url, "content": "", "error": str(e)}


def build_corpus() -> List[Dict]:
    """
    Scrape all seed URLs and return list of documents for RAG ingestion.
    """
    corpus = []
    logger.info("Building HRMS knowledge base from humanmaximizer.com...")

    for url in SEED_URLS:
        logger.info(f"Scraping: {url}")
        doc = scrape_page(url)
        if doc["content"]:
            corpus.append(doc)
        elif doc.get("error"):
            logger.warning(f"Scrape failed for {url}: {doc['error']}")
        time.sleep(1)  # Polite crawling

    logger.info(f"Done. {len(corpus)} pages scraped.")
    return corpus


if __name__ == "__main__":
    corpus = build_corpus()
    for doc in corpus:
        logger.info(f"=== {doc['url']} ===")
        logger.debug(doc["content"][:500])
