"""
NASSCOM member-directory harvester (FREE, ICP-exact).
-----------------------------------------------------
nasscom.in/members-listing is 3,200+ IT / software / BPO / e-commerce companies —
exactly the HRMS-buyer ICP. The grid is JS-rendered (no static HTML, no clean AJAX
JSON), so we render it with Playwright, scroll to lazy-load more members, and read
each card (company name + city). NASSCOM gives the curated COMPANY + CITY; phone +
decision-maker are added afterwards by the Maps/crawl enrichment.

Returns candidate dicts {url, title, location, phone, industry, source}. Fail-safe.
"""
import re
import threading
from typing import Optional

from loguru import logger

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_URL = "https://nasscom.in/members-listing"

# NCR cities (so we can keep only the Delhi-NCR members for the campaign).
NCR = {"delhi", "new delhi", "noida", "greater noida", "gurgaon", "gurugram",
       "faridabad", "ghaziabad"}

_state = {"running": False, "loaded": 0, "ncr": 0, "added": 0}
_lock = threading.Lock()


def status() -> dict:
    return dict(_state)


def running() -> bool:
    return _state["running"]


# JS run after render: read every member card → {name, city}. Cards repeat in the
# DOM, so we de-dup by name on the Python side.
_EXTRACT = r"""
() => {
  const out = [];
  const cards = document.querySelectorAll('.views-row, [class*="member-card" i], [class*="members-listing" i] [class*="card" i]');
  cards.forEach(c => {
    const t = (c.innerText || '').trim();
    if (!t) return;
    const lines = t.split('\n').map(s => s.trim()).filter(Boolean);
    if (lines.length >= 2 && lines[0].length > 2 && lines[0].length < 90) {
      out.push({ name: lines[0], city: lines[1] });
    }
  });
  return out;
}
"""


def _render_members(max_scrolls: int = 25) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []
    rows: list[dict] = []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-blink-features=AutomationControlled"])
            page = b.new_context(user_agent=_UA, locale="en-IN", viewport={"width": 1366, "height": 1000}).new_page()
            page.goto(_URL, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(6000)
            seen = 0
            for _ in range(max_scrolls):
                page.mouse.wheel(0, 6000)
                page.wait_for_timeout(1500)
                # click a "load more" / "show more" button if present
                try:
                    btn = page.query_selector("text=/load more|show more|view more/i")
                    if btn:
                        btn.click(); page.wait_for_timeout(1500)
                except Exception:
                    pass
                cur = page.eval_on_selector_all(".views-row", "els=>els.length") or 0
                if cur == seen:
                    break  # no new rows loaded
                seen = cur
            rows = page.evaluate(_EXTRACT) or []
            b.close()
    except Exception as e:
        logger.debug(f"[nasscom] render failed: {e}")
    return rows


def harvest(ncr_only: bool = True, max_scrolls: int = 25) -> list[dict]:
    """Render the NASSCOM directory, return member companies as candidates."""
    raw = _render_members(max_scrolls)
    seen, out = set(), []
    for r in raw:
        name = r.get("name", "").strip()
        city = (r.get("city", "") or "").strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        if ncr_only and not any(c in city.lower() for c in NCR):
            continue
        # BPO vs IT label from the name; default IT services (NASSCOM core).
        ind = "BPO" if re.search(r"\b(bpo|bpm|outsourc|call cent|kpo)\b", name, re.I) else "IT services"
        out.append({"url": "", "title": name[:200], "location": f"{city}, India" if city else "India",
                    "phone": "", "industry": ind, "source": "nasscom"})
    return out


def harvest_to_warehouse(ncr_only: bool = True, max_scrolls: int = 25) -> dict:
    """Render NASSCOM, bank member companies as leads (no phone yet — enriched after)."""
    if not _lock.acquire(blocking=False):
        return {"status": "busy", **status()}
    try:
        from tools.sources import _directory_common as dc
        from core import warehouse
        _state.update(running=True, loaded=0, ncr=0, added=0)
        cands = harvest(ncr_only=ncr_only, max_scrolls=max_scrolls)
        _state["ncr"] = len(cands)
        # region = the member's city so tag_delhi_ncr folds them in.
        n = 0
        for c in cands:
            city = (c.get("location") or "").split(",")[0].strip()
            n += dc.bank([c], region=city or "Delhi", source_label="NASSCOM", tag_source="nsc")
        _state["added"] = n
        warehouse.tag_delhi_ncr()
        logger.info(f"[nasscom] banked {n} member companies ({len(cands)} NCR)")
        return {"status": "ok", "ncr_members": len(cands), "added": n, "pool": warehouse.stats()}
    except Exception as e:
        logger.warning(f"[nasscom] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _state["running"] = False
        _lock.release()
