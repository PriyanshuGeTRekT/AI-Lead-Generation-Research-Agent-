"""
Government / official registry source (India SMEs)
--------------------------------------------------
There is no single open government API that lists Indian SMEs WITH contact data
(Udyam/MSME registration and MCA company-master data are not openly bulk-queryable
with contacts). So this adapter does the practical, honest thing:

1. If `datagovin_api_key` (+ a `datagovin_resource_id`) is configured, it queries
   the real data.gov.in API (pluggable; returns [] until configured).
2. Otherwise it runs **registry-biased** searches that surface genuinely
   registered SMEs — "Pvt Ltd / LLP / Udyam / MSME" company homepages — via the
   same Serper key, filtered to real company sites (no listicles/directories).

Returns candidate dicts {url, title, source, snippet}. Fail-safe [].
"""
import json
from typing import Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore


def _datagovin(keyword: str, max_results: int) -> list[dict]:
    """Query data.gov.in if a key + resource id are configured. Pluggable."""
    if requests is None:
        return []
    try:
        from core import runtime_config as rc
        key = rc.get("datagovin_api_key")
        resource = rc.get("datagovin_resource_id")
    except Exception:
        key, resource = None, None
    if not key or not resource:
        return []
    try:
        r = requests.get(
            f"https://api.data.gov.in/resource/{resource}",
            params={"api-key": key, "format": "json", "limit": max_results, "q": keyword},
            timeout=15,
        )
        records = r.json().get("records", []) or []
        out = []
        for rec in records:
            name = rec.get("company_name") or rec.get("name") or rec.get("enterprise_name")
            web = rec.get("website") or rec.get("url") or ""
            if name:
                out.append({"url": web, "title": name, "source": "govt:data.gov.in",
                            "snippet": rec.get("address", "") or rec.get("district", "")})
        return out[:max_results]
    except Exception:
        return []


def search_companies(
    keyword: str,
    country: str = "India",
    region: Optional[str] = None,
    max_results: int = 25,
) -> list[dict]:
    """Registry-biased company discovery (Pvt Ltd / LLP / Udyam / MSME)."""
    # 1) Official open-data API (only if configured)
    out = _datagovin(keyword, max_results)
    if out:
        return out

    # 2) Registry-biased Serper queries → real registered-company homepages
    if requests is None:
        return []
    try:
        from tools.web_search import _serper_key, _is_company_url, _is_listicle, _get_domain
    except Exception:
        return []
    key = _serper_key()
    if not key:
        return []

    loc = region or "India"
    queries = [
        f'"{keyword}" ("Pvt Ltd" OR "Private Limited" OR LLP) {loc} India',
        f'"{keyword}" (Udyam OR MSME OR "registered office") {loc} company',
        f'{keyword} small medium enterprise {loc} India contact',
    ]
    seen, out = set(), []
    for q in queries:
        if len(out) >= max_results:
            break
        try:
            resp = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": key, "Content-Type": "application/json"},
                data=json.dumps({"q": q, "gl": "in", "hl": "en", "num": 10}),
                timeout=12,
            )
            organic = resp.json().get("organic", []) or []
        except Exception:
            continue
        for item in organic:
            url, title = item.get("link", ""), item.get("title", "")
            dom = _get_domain(url)
            if url and dom and dom not in seen and _is_company_url(url) and not _is_listicle(title):
                seen.add(dom)
                out.append({"url": url, "title": title, "source": "govt:registry",
                            "snippet": item.get("snippet", "")})
    return out[:max_results]
