"""
Explorium source adapter (plug-in)
----------------------------------
Explorium is a B2B data platform (firmographics + technographics + prospects).
This adapter uses it for discovery: fetch India SMEs matching the keyword, mapped
to candidate dicts the research agent understands. Activates when an
`explorium_api_key` is set; returns [] otherwise (fail-safe).

NOTE: Explorium's exact endpoint/filter names vary by plan/version. The request
shape below is the documented businesses-fetch style; only `_to_candidate` and the
filter keys need tweaking if your plan differs. Everything is wrapped fail-safe.
"""
import json
from typing import Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

_BASE = "https://api.explorium.ai/v1"
_SIZE_BANDS = ["11-50", "51-200", "201-500", "501-1000"]  # SME bands


def _to_candidate(b: dict) -> Optional[dict]:
    name = b.get("name") or b.get("company_name") or ""
    domain = b.get("domain") or b.get("website") or ""
    if not name:
        return None
    return {
        "url": domain if str(domain).startswith("http") else (f"https://{domain}" if domain else ""),
        "title": name,
        "source": "explorium",
        "location": ", ".join(
            filter(None, [b.get("city"), b.get("region") or b.get("state"), b.get("country") or "India"])
        ),
    }


def search_companies(
    keyword: str,
    country: str = "India",
    region: Optional[str] = None,
    max_results: int = 25,
    api_key: Optional[str] = None,
) -> list[dict]:
    """Fetch SME businesses from Explorium. Fail-safe [] on no key / any error."""
    if requests is None:
        return []
    key = api_key
    if not key:
        try:
            from core import runtime_config as rc
            key = rc.get("explorium_api_key")
        except Exception:
            key = None
    if not key:
        return []

    payload = {
        "mode": "full",
        "size": min(max_results, 100),
        "filters": {
            "company_size": _SIZE_BANDS,
            "country_code": ["IN"],
            "company_name_keywords": [keyword],
        },
    }
    if region:
        payload["filters"]["region"] = [region]

    headers = {"Content-Type": "application/json", "api_key": key, "Authorization": f"Bearer {key}"}
    for path in ("/businesses/fetch", "/businesses"):
        try:
            resp = requests.post(f"{_BASE}{path}", headers=headers, data=json.dumps(payload), timeout=20)
            if resp.status_code >= 400:
                continue
            data = resp.json()
            rows = data.get("data") or data.get("businesses") or data.get("results") or []
            out = [c for c in (_to_candidate(b) for b in rows) if c]
            if out:
                return out[:max_results]
        except Exception:
            continue
    return []


def probe(keyword: str = "manufacturing", region: Optional[str] = None) -> dict:
    """
    Diagnostic: hit Explorium live and return the RAW response (status + shape +
    first row) for each endpoint/auth variant tried, plus how many candidates our
    mapper extracted. Lets us lock `_to_candidate`/filter keys to your account.
    Secrets are never returned.
    """
    if requests is None:
        return {"error": "requests not installed"}
    try:
        from core import runtime_config as rc
        key = rc.get("explorium_api_key")
    except Exception:
        key = None
    if not key:
        return {"key_set": False, "note": "No explorium_api_key set in Settings."}

    payload = {
        "mode": "full",
        "size": 5,
        "filters": {"company_size": _SIZE_BANDS, "country_code": ["IN"], "company_name_keywords": [keyword]},
    }
    if region:
        payload["filters"]["region"] = [region]

    def _trunc(obj, n=1500):
        s = json.dumps(obj)[:n]
        return s + ("…" if len(json.dumps(obj)) > n else "")

    attempts = []
    # Try both header auth styles × both paths so we can see which your plan accepts.
    auth_variants = [
        {"name": "api_key", "headers": {"api_key": key}},
        {"name": "bearer", "headers": {"Authorization": f"Bearer {key}"}},
    ]
    for path in ("/businesses/fetch", "/businesses"):
        for av in auth_variants:
            url = f"{_BASE}{path}"
            rec = {"url": url, "auth": av["name"]}
            try:
                resp = requests.post(
                    url, headers={"Content-Type": "application/json", **av["headers"]},
                    data=json.dumps(payload), timeout=20,
                )
                rec["status"] = resp.status_code
                try:
                    body = resp.json()
                    rec["top_level_keys"] = list(body.keys()) if isinstance(body, dict) else "list"
                    rows = (body.get("data") or body.get("businesses") or body.get("results") or []) if isinstance(body, dict) else body
                    rec["row_count"] = len(rows) if isinstance(rows, list) else 0
                    rec["first_row"] = rows[0] if isinstance(rows, list) and rows else None
                    rec["candidates_mapped"] = len([c for c in (_to_candidate(b) for b in (rows or [])) if c]) if isinstance(rows, list) else 0
                except Exception:
                    rec["body_text"] = resp.text[:1500]
            except Exception as e:
                rec["error"] = str(e)[:300]
            attempts.append(rec)
    return {"key_set": True, "endpoint_base": _BASE, "payload": payload, "attempts": attempts}
