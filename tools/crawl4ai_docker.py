"""
Client for the REAL crawl4ai library, run as a Docker service.
---------------------------------------------------------------
crawl4ai can't pip-install on win-arm64 (native deps), so we run the official
`unclecode/crawl4ai` image (FastAPI server on :11235) and call its /crawl endpoint.
This gives the genuine crawl4ai engine (JS render + markdown). We then extract the
decision-maker + phone from the returned markdown using the same validated logic.

available() → True only when the container's /health responds, so callers fall back
to the Playwright crawler when the service is down. Fail-safe.
"""
from typing import Optional

try:
    import requests as _rq
except Exception:
    _rq = None

_BASE = "http://localhost:11235"


def available() -> bool:
    if _rq is None:
        return False
    try:
        r = _rq.get(f"{_BASE}/health", timeout=4)
        return r.status_code == 200
    except Exception:
        return False


def _markdown_of(res: dict) -> str:
    md = res.get("markdown")
    if isinstance(md, dict):
        return md.get("raw_markdown") or md.get("fit_markdown") or ""
    if isinstance(md, str):
        return md
    # some versions: cleaned_html / fit_html
    return res.get("cleaned_html") or res.get("fit_html") or res.get("html") or ""


def _llm_config() -> Optional[dict]:
    """NVIDIA NIM (OpenAI-compatible) config for crawl4ai's LLM extraction, if a key
    is set. Lets crawl4ai read each page with an LLM and return a STRUCTURED
    decision-maker {name,title,phone,email} — far cleaner than regex."""
    from core import runtime_config as rc
    key = (rc.get("nvidia_api_key") or "").strip()
    if not key:
        return None
    model = rc.get("nvidia_model_strong") or "meta/llama-3.3-70b-instruct"
    return {"provider": "openai/" + model, "api_token": key,
            "base_url": "https://integrate.api.nvidia.com/v1"}


_SCHEMA = {"title": "Contact", "type": "object", "properties": {
    "decision_maker_name": {"type": "string"}, "title": {"type": "string"},
    "phone": {"type": "string"}, "email": {"type": "string"}}}
_INSTR = ("Extract the company's owner / founder / director / proprietor: their full "
          "name, job title, phone number and email if present on the page. Use 'Not "
          "Available' when a field is absent. Return exactly one object.")


def crawl_contacts(urls: list[str], concurrency: int = 6, tries: int = 3) -> dict:
    """POST urls to the crawl4ai server → {url:{phone,email,name,role}} per url.
    Uses LLM extraction (NVIDIA) when a key is set (structured, accurate); else
    markdown+regex. Retries the batch on transient SSRF/DNS blips."""
    from tools.crawl4ai_contacts import _extract, _MOBILE_RE
    import re, json
    try:
        from core.contact_finder import valid_person
    except Exception:
        valid_person = lambda n: bool(n)
    if _rq is None or not available() or not urls:
        return {}
    llm = _llm_config()
    cc = {"cache_mode": "bypass", "page_timeout": 30000, "word_count_threshold": 5, "stream": False}
    if llm:
        cc["extraction_strategy"] = {"type": "LLMExtractionStrategy", "params": {
            "llm_config": {"type": "LLMConfig", "params": llm},
            "extraction_type": "schema", "schema": _SCHEMA, "instruction": _INSTR,
            "apply_chunking": False}}
    body = {"urls": urls,
            "browser_config": {"type": "BrowserConfig", "params": {"headless": True}},
            "crawler_config": {"type": "CrawlerRunConfig", "params": cc}}
    results = []
    for _ in range(tries):
        try:
            r = _rq.post(f"{_BASE}/crawl", json=body, timeout=max(90, len(urls) * 15))
            if r.status_code == 200:
                data = r.json()
                results = data.get("results") or (data if isinstance(data, list) else [])
                break
            # transient SSRF/DNS block → retry
            if r.status_code == 400 and "ssrf" in r.text.lower():
                continue
            return {}
        except Exception:
            continue
    out: dict = {}
    for res in results:
        if not isinstance(res, dict):
            continue
        url = res.get("url") or ""
        found = {"phone": "", "email": "", "name": "", "role": ""}
        # 1) LLM structured output
        ec = res.get("extracted_content")
        if ec:
            try:
                items = json.loads(ec) if isinstance(ec, str) else ec
                rec = items[0] if isinstance(items, list) and items else (items if isinstance(items, dict) else {})
                def clean(v):
                    v = (v or "").strip()
                    return "" if v.lower() in ("not available", "n/a", "none", "") else v
                nm = clean(rec.get("decision_maker_name"))
                if nm and valid_person(nm):
                    found["name"] = nm; found["role"] = clean(rec.get("title")) or "Decision-maker"
                ph = re.sub(r"\D", "", clean(rec.get("phone")))
                m = _MOBILE_RE.search(ph[2:] if ph.startswith("91") and len(ph) > 10 else ph)
                if m:
                    found["phone"] = m.group(1)
                em = clean(rec.get("email"))
                if em and "@" in em and not re.search(r"(example|sentry|godaddy)", em, re.I):
                    found["email"] = em
            except Exception:
                pass
        # 2) fallback: regex over markdown/html for anything still missing
        if not (found["phone"] and found["name"]):
            md = _markdown_of(res); html = res.get("html") or res.get("cleaned_html") or ""
            rx = _extract(md or "", html)
            for k, v in rx.items():
                if v and not found[k]:
                    found[k] = v
        out[url] = found
    return out
