"""
Website contact crawler — decision-maker + phone from a company's OWN site.
---------------------------------------------------------------------------
Goal: crawl4ai-style extraction (render JS → clean text → pull contacts). crawl4ai
itself won't install on this box (native deps lxml/shapely/cryptography have no
win-arm64 wheels), so we use the SAME engine crawl4ai wraps — Playwright (already
installed + proven here) — and keep crawl4ai as an automatic upgrade if it ever
becomes importable.

Optimized: per company, fetch the homepage, pick the ONE most contact-relevant
subpage (/contact, /about, /team, /leadership) and fetch only that (≤2 page-loads),
concurrent across companies (own browser per worker). Extracts phone (mobile-first),
email, and decision-maker name+role.

HONEST SCOPE: a crawler extracts only what a site PUBLISHES — office line, or owner
mobile for tiny SMEs, plus sometimes a named contact. Not a private direct dial.
Fail-safe throughout.
"""
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from loguru import logger

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

_MOBILE_RE = re.compile(r"(?:\+?91[\-\s]?|0)?([6-9]\d{9})\b")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_NAME_ROLE = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*[-–,:(]?\s*"
    r"(Founder|Co-?Founder|Managing Director|Director|Proprietor|Owner|CEO|Chairman|Partner)")
_ROLE_NAME = re.compile(
    r"(Founder|Co-?Founder|Managing Director|Director|Proprietor|Owner|CEO)\s*[-–,:]?\s*"
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})")
_CONTACT_KW = ["contact", "about", "team", "leadership", "management", "who-we-are"]


def available() -> bool:
    """True if any render engine is present (crawl4ai preferred, Playwright fallback)."""
    try:
        import crawl4ai  # noqa: F401
        return True
    except Exception:
        pass
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


try:
    import requests as _rq
except Exception:
    _rq = None

_TEL_HREF = re.compile(r'href=["\']tel:\+?([\d\-\s().]{8,16})["\']', re.I)
_MAILTO = re.compile(r'href=["\']mailto:([^"\'?]+)["\']', re.I)


def _best_phone(html: str, text: str) -> str:
    """Prefer tel: links (intentional), then a phone near contact words, then any."""
    for raw in _TEL_HREF.findall(html or ""):
        m = _MOBILE_RE.search(re.sub(r"\D", "", raw))
        if m:
            return m.group(1)
    # phone within ~40 chars of a contact cue
    for m in re.finditer(r"(?:call|phone|mobile|contact|tel|whatsapp|reach)[^0-9]{0,25}((?:\+?91[\-\s]?|0)?[6-9]\d{9})", text, re.I):
        mm = _MOBILE_RE.search(re.sub(r"\D", "", m.group(1)))
        if mm:
            return mm.group(1)
    m = _MOBILE_RE.search(text)
    return m.group(1) if m else ""


def _extract(text: str, html: str = "") -> dict:
    out = {"phone": "", "email": "", "name": "", "role": ""}
    out["phone"] = _best_phone(html, text)
    mt = _MAILTO.findall(html or "")
    em = (mt[0] if mt else "") or (_EMAIL_RE.search(text).group(0) if _EMAIL_RE.search(text) else "")
    if em and not re.search(r"(example|sentry|wixpress|godaddy|\.png|\.jpg|\.webp|@sentry)", em, re.I):
        out["email"] = em
    nm = _NAME_ROLE.search(text)
    cand_name = cand_role = ""
    if nm:
        cand_name, cand_role = nm.group(1).strip(), nm.group(2).title()
    else:
        rn = _ROLE_NAME.search(text)
        if rn:
            cand_role, cand_name = rn.group(1).title(), rn.group(2).strip()
    try:
        from core.contact_finder import valid_person
        if cand_name and valid_person(cand_name):
            out["name"], out["role"] = cand_name, cand_role
    except Exception:
        if cand_name:
            out["name"], out["role"] = cand_name, cand_role
    return out


def _fetch_requests(url: str) -> tuple[str, str]:
    """Fast path: plain HTTP. Returns (html, visible_text). ('','') on failure/block."""
    if _rq is None:
        return "", ""
    try:
        r = _rq.get(url, headers={"User-Agent": _UA, "Accept-Language": "en-IN,en;q=0.9"}, timeout=12)
        if r.status_code != 200 or not r.text:
            return "", ""
        html = r.text
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        return html, re.sub(r"\s+", " ", text)[:30000]
    except Exception:
        return "", ""


def _merge(a: dict, b: dict) -> dict:
    for k, v in b.items():
        if v and not a.get(k):
            a[k] = v
    return a


def _contact_link(html: str, base: str) -> Optional[str]:
    for kw in _CONTACT_KW:
        m = re.search(r'href=["\'](/?[^"\']*' + kw + r'[^"\']*)["\']', html or "", re.I)
        if m:
            href = m.group(1)
            if href.startswith("/"):
                href = base.rstrip("/") + href
            return href if href.startswith("http") else None
    return None


def _crawl_site(url: str) -> dict:
    """requests-first (fast); Playwright fallback for JS/blocked sites. Homepage +
    one contact subpage."""
    found = {"phone": "", "email": "", "name": "", "role": ""}
    # 1) Fast HTTP path
    html, text = _fetch_requests(url)
    if text:
        _merge(found, _extract(text, html))
        if not (found["phone"] and found["name"]):
            cu = _contact_link(html, url)
            if cu:
                h2, t2 = _fetch_requests(cu)
                if t2:
                    _merge(found, _extract(t2, h2))
        if found["phone"]:
            return found
    # 2) Playwright fallback (JS-rendered or HTTP blocked but browser-allowed)
    found = _crawl_site_playwright(url, seed=found)
    return found


def _crawl_site_playwright(url: str, seed: dict) -> dict:
    """Render homepage + best contact subpage with Playwright, extract contacts."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return seed
    found = dict(seed)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            ctx = b.new_context(user_agent=_UA, locale="en-IN", viewport={"width": 1280, "height": 900})
            page = ctx.new_page()
            try:
                page.goto(url, timeout=25000, wait_until="domcontentloaded")
                page.wait_for_timeout(1200)
                _merge(found, _extract(page.inner_text("body")[:25000]))
                # tel: links are the most reliable phone
                try:
                    tel = page.eval_on_selector('a[href^="tel:"]', "e=>e.getAttribute('href')")
                    if tel:
                        m = _MOBILE_RE.search(re.sub(r"\D", "", tel))
                        if m and not found["phone"]:
                            found["phone"] = m.group(1)
                except Exception:
                    pass
                # one targeted contact subpage if still missing phone or name
                if not (found["phone"] and found["name"]):
                    href = None
                    try:
                        links = page.eval_on_selector_all(
                            "a[href]", "els=>els.map(e=>e.getAttribute('href'))") or []
                    except Exception:
                        links = []
                    for kw in _CONTACT_KW:
                        href = next((l for l in links if l and kw in l.lower()), None)
                        if href:
                            break
                    if href:
                        if href.startswith("/"):
                            href = url.rstrip("/") + href
                        if href.startswith("http"):
                            try:
                                page.goto(href, timeout=20000, wait_until="domcontentloaded")
                                page.wait_for_timeout(1000)
                                _merge(found, _extract(page.inner_text("body")[:25000]))
                                tel = page.eval_on_selector('a[href^="tel:"]', "e=>e.getAttribute('href')")
                                if tel and not found["phone"]:
                                    m = _MOBILE_RE.search(re.sub(r"\D", "", tel))
                                    if m:
                                        found["phone"] = m.group(1)
                            except Exception:
                                pass
            finally:
                b.close()
    except Exception as e:
        logger.debug(f"[crawl] {url} failed: {e}")
    return found


def engine() -> str:
    """Which crawl engine is active: real crawl4ai (Docker), Playwright, or none."""
    try:
        from tools import crawl4ai_docker
        if crawl4ai_docker.available():
            return "crawl4ai-docker"
    except Exception:
        pass
    try:
        import playwright  # noqa: F401
        return "playwright"
    except Exception:
        return "none"


def crawl_contacts(urls: list[str], concurrency: int = 6) -> dict:
    """Crawl many company sites → {url: {phone,email,name,role}}. Prefers the REAL
    crawl4ai library via its Docker service; falls back to Playwright (per-thread)."""
    if not urls:
        return {}
    # 1) Real crawl4ai (Docker service) if running
    try:
        from tools import crawl4ai_docker
        if crawl4ai_docker.available():
            res = crawl4ai_docker.crawl_contacts(urls, concurrency)
            if res:
                return res
    except Exception:
        pass
    # 2) Playwright fallback
    if not available():
        return {}
    out: dict = {}
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        for url, r in zip(urls, ex.map(_crawl_site, urls)):
            out[url] = r
    return out
