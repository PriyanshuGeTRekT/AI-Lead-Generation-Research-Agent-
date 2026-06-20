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


def build_local_corpus() -> List[Dict]:
    """
    Load product knowledge from local files (the hcmv3 product content lives in
    ./knowledge — e.g. the curated llms.txt). Preferred over web scraping so RAG
    grounding never depends on the live site (which blocks scrapers).
    """
    import os
    from pathlib import Path

    base = Path(os.getenv("KNOWLEDGE_DIR", "./knowledge"))
    docs: List[Dict] = []
    if not base.exists():
        return docs
    for path in sorted(base.rglob("*")):
        if path.suffix.lower() not in (".md", ".mdx", ".txt"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
        except Exception:
            continue
        if len(text) < 30:
            continue
        docs.append({"url": f"local:{path.name}", "title": path.stem, "content": text, "error": None})
    if docs:
        logger.info(f"Loaded {len(docs)} local knowledge file(s) from {base}")
    return docs


def build_corpus() -> List[Dict]:
    """
    Build the RAG corpus. Prefers local curated knowledge (./knowledge); only
    falls back to scraping humanmaximizer.com if no local files are present.
    """
    local = build_local_corpus()
    if local:
        return local

    corpus = []
    logger.info("No local knowledge found — falling back to scraping humanmaximizer.com...")

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
