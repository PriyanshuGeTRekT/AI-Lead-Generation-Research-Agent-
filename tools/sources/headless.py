"""
Headless-browser harvester for JS-rendered Indian business directories.
-----------------------------------------------------------------------
JustDial, IndiaMART, TradeIndia, Sulekha and ExportersIndia all render their
listings client-side (the static HTML is an empty app shell; the businesses arrive
via XHR after load), so a plain `requests` fetch never sees them. This module drives
a real headless Chromium (Playwright) so the JS renders, waits for the network to go
idle, scrolls to trigger lazy loads, then extracts businesses from the live DOM —
preferring rendered schema.org JSON-LD, falling back to heuristic name/phone/locality.

One generic engine, many sites (see SITES). Free, but heavier than the API sources:
needs Playwright + a Chromium binary installed once, ~seconds per page.

Setup (run once):
    pip install playwright
    playwright install chromium

Returns candidate dicts {url,title,location,phone,industry,source}. Never raises.
"""
import re
from typing import Optional

from loguru import logger

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

INSTALL_HINT = "Playwright not installed. Run:  pip install playwright  &&  playwright install chromium"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# Per-site URL builders. category = a plain phrase ("manufacturers"); city = "Delhi".
# Each returns the listing-page URL for that (category, city). Unknown sites → None.
SITES = {
    "indiamart":      lambda cat, city: f"https://dir.indiamart.com/search.mp?ss={cat.replace(' ', '+')}&cq={city.replace(' ', '+')}",
    "justdial":       lambda cat, city: f"https://www.justdial.com/{city.replace(' ', '-')}/{cat.title().replace(' ', '-')}",
    "tradeindia":     lambda cat, city: f"https://www.tradeindia.com/{_slug(cat)}/{_slug(city)}/",
    "sulekha":        lambda cat, city: f"https://www.sulekha.com/{_slug(cat)}/{_slug(city)}",
    "exportersindia": lambda cat, city: f"https://www.exportersindia.com/search.php?ss={cat.replace(' ', '+')}+{city.replace(' ', '+')}",
}


def available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


# JS run in the page after render. Two strategies, merged + de-duped:
#  1) schema.org JSON-LD LocalBusiness/Organization blocks (name + phone + locality)
#  2) heuristic: business-name nodes across many class-name variants, with the phone
#     + own-site link found in the surrounding card container.
_EXTRACT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const push = (name, phone, url, loc) => {
    name = (name || '').replace(/\s+/g, ' ').trim();
    if (!name || name.length < 3 || seen.has(name.toLowerCase())) return;
    seen.add(name.toLowerCase());
    out.push({ title: name, phone: phone || '', url: url || '', locality: loc || '' });
  };

  // 1) JSON-LD
  document.querySelectorAll('script[type="application/ld+json"]').forEach(s => {
    let data; try { data = JSON.parse(s.textContent); } catch (e) { return; }
    const items = Array.isArray(data) ? data : [data];
    for (const it of items) {
      if (!it || typeof it !== 'object') continue;
      const t = (it['@type'] || '').toString().toLowerCase();
      if (!/business|organization|store|company|professional/.test(t)) continue;
      const addr = it.address || {};
      const loc = (addr.addressLocality || addr.addressRegion || '');
      push(it.name, it.telephone || '', it.url || '', loc);
    }
  });

  // 2) Heuristic name nodes
  const sel = [
    '.lng_cont_name', '.resultbox_title_anchor', '.jcn a', '.store-name',
    '.companyname', '.lcname', '.cmpnm', '.cardlinks', '.prod-name', '.coname',
    '.company-name', '.cmp-name', '.seller-name', '.fs-result-cmp-name',
    'h2 a', 'h3 a', '[class*="company" i] a', '[class*="seller" i] a', '[itemprop="name"]'
  ];
  const nodes = [];
  for (const s of sel) document.querySelectorAll(s).forEach(n => nodes.push(n));
  for (const n of nodes) {
    const name = (n.textContent || '').replace(/\s+/g, ' ').trim();
    if (!name || name.length < 3) continue;
    let card = n;
    for (let i = 0; i < 6 && card.parentElement; i++) card = card.parentElement;
    const tel = card.querySelector('a[href^="tel:"]');
    let phone = tel ? tel.getAttribute('href').replace('tel:', '') : '';
    if (!phone) {
      const m = (card.textContent || '').match(/(?:\+?91[\-\s]?)?[6-9]\d{9}/);
      if (m) phone = m[0];
    }
    let link = '';
    if (n.tagName === 'A' && n.getAttribute('href')) link = n.getAttribute('href');
    else { const a = card.querySelector('a[href^="http"]'); if (a) link = a.getAttribute('href'); }
    push(name, phone, link, '');
  }
  return out;
}
"""


def _render_and_extract(url: str, wait_ms: int = 6000) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        logger.warning(f"[headless] {INSTALL_HINT}")
        return []
    rows: list[dict] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=[
                "--no-sandbox", "--disable-blink-features=AutomationControlled"])
            ctx = browser.new_context(user_agent=_UA, locale="en-IN",
                                      viewport={"width": 1366, "height": 900})
            page = ctx.new_page()
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            page.wait_for_timeout(wait_ms)
            for _ in range(4):  # trigger lazy/infinite loads
                page.mouse.wheel(0, 5000)
                page.wait_for_timeout(1300)
            rows = page.evaluate(_EXTRACT_JS) or []
            browser.close()
    except Exception as e:
        logger.debug(f"[headless] render failed for {url}: {e}")
        return []
    return rows


def _clean_phone(raw: str) -> str:
    d = re.sub(r"\D", "", raw or "")
    if d.startswith("91") and len(d) == 12:
        d = d[2:]
    return d if (len(d) == 10 and d[0] in "6789") else ""


def _to_candidates(rows: list[dict], city: str, industry: str, source: str) -> list[dict]:
    out = []
    for r in rows:
        name = (r.get("title") or "").strip()
        if not name or len(name) < 3:
            continue
        url = (r.get("url") or "").strip()
        # Drop directory-internal links (not the company's own site).
        if url and re.search(r"justdial|indiamart|imimg|tradeindia|sulekha|exportersindia", url, re.I):
            url = ""
        loc = (r.get("locality") or "").strip()
        out.append({
            "url": url,
            "title": name[:200],
            "location": f"{loc}, {city}" if loc and loc.lower() != city.lower() else f"{city}, India",
            "phone": _clean_phone(r.get("phone", "")),
            "industry": industry,
            "source": source,
        })
    return out


def harvest_site(site: str, category: str, city: str, industry: str) -> list[dict]:
    """Render one directory site's (category × city) page and extract businesses."""
    builder = SITES.get(site)
    if not builder:
        return []
    return _to_candidates(_render_and_extract(builder(category, city)), city, industry, site)


def probe_site(site: str, category: str = "manufacturers", city: str = "Delhi") -> dict:
    """Diagnostic: render one site and report yield + a sample (no banking)."""
    if not available():
        return {"ok": False, "hint": INSTALL_HINT}
    builder = SITES.get(site)
    if not builder:
        return {"ok": False, "error": f"unknown site '{site}'", "sites": list(SITES)}
    url = builder(category, city)
    rows = harvest_site(site, category, city, category)
    return {"ok": True, "site": site, "url": url, "extracted": len(rows),
            "with_phone": len([r for r in rows if r["phone"]]),
            "sample": rows[:8]}


# ── Back-compat wrappers used by indiamart.py / justdial.py ───────────────────
def fetch_indiamart(keyword: str, city: str, industry: str) -> list[dict]:
    return harvest_site("indiamart", keyword, city, industry)


def fetch_justdial(category: str, city: str, industry: str) -> list[dict]:
    return harvest_site("justdial", category, city, industry)
