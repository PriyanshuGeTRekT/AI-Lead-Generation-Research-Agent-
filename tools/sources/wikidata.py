"""
Wikidata source (FREE, keyless company discovery)
-------------------------------------------------
The paid Serper key can run out of credits, which silently drops the tool back to
a tiny hardcoded fallback. Wikidata's SPARQL endpoint is FREE and keyless, and
holds thousands of real Indian companies with official websites + industry — so
discovery keeps working at zero marginal cost.

Scope: ~2-5k Indian businesses with websites (skews to established firms). This is
the free baseline; true 6-figure SME volume needs a budgeted search API or the
data.gov.in MSME registry (see tools/sources/govt.py). Fail-safe: returns [].
"""
import re
import threading
from typing import Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

_ENDPOINT = "https://query.wikidata.org/sparql"
_UA = "RazorInfotech-Leads/1.0 (razorinfotechpvtltd@gmail.com)"
_STOP = {"company", "companies", "india", "indian", "pvt", "ltd", "private", "limited",
         "llp", "msme", "udyam", "sme", "enterprise", "enterprises", "firm", "business",
         "200", "300", "500", "800", "1000", "employees", "staff", "site"}

# Rotating offset so repeated calls page through the dataset instead of returning
# the same first rows (lets the harvest matrix drain Wikidata over many queries).
_lock = threading.Lock()
_offset = {"n": 0}


def _industry_term(keyword: str) -> str:
    """Pull the meaningful industry word(s) out of a search keyword."""
    toks = [t for t in re.findall(r"[a-zA-Z]+", (keyword or "").lower()) if t not in _STOP]
    return toks[0] if toks else ""


def search_companies(keyword: str, region: Optional[str] = None, max_results: int = 50) -> list[dict]:
    if requests is None:
        return []
    term = _industry_term(keyword)
    # Industry- or name-matched Indian businesses with a website. The label filter
    # is applied in SPARQL when we have a term; otherwise we page broadly.
    filt = ""
    if term:
        safe = re.sub(r'[^a-z]', '', term)
        if safe:
            filt = (f'?c wdt:P452 ?ind . ?ind rdfs:label ?il . '
                    f'FILTER(LANG(?il)="en" && CONTAINS(LCASE(?il), "{safe}"))')
    with _lock:
        off = _offset["n"]
        _offset["n"] = (off + max_results) % 2000  # wrap so we keep cycling
    query = f"""SELECT DISTINCT ?cLabel ?web ?indLabel WHERE {{
  ?c wdt:P17 wd:Q668 ; wdt:P856 ?web ; wdt:P31/wdt:P279* wd:Q4830453 .
  {filt}
  OPTIONAL {{ ?c wdt:P452 ?i2 . ?i2 rdfs:label ?indLabel . FILTER(LANG(?indLabel)="en") }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT {max(1, min(max_results, 100))} OFFSET {off if not filt else 0}"""
    try:
        r = requests.get(_ENDPOINT, params={"query": query, "format": "json"},
                         headers={"User-Agent": _UA, "Accept": "application/sparql-results+json"},
                         timeout=40)
        if r.status_code != 200:
            return []
        rows = r.json().get("results", {}).get("bindings", [])
    except Exception:
        return []
    out = []
    for b in rows:
        web = b.get("web", {}).get("value", "")
        name = b.get("cLabel", {}).get("value", "")
        if not web or not name or name.startswith("Q"):  # skip unlabeled QIDs
            continue
        out.append({
            "url": web,
            "title": name,
            "source": "wikidata",
            # The SPARQL query filters to country=India (Q668), so these ARE Indian
            # — stamp the location so the downstream India gate doesn't drop them.
            "location": region or "India",
            "snippet": b.get("indLabel", {}).get("value", "") or "",
        })
    return out[:max_results]
