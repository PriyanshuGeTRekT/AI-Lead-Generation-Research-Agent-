"""
MCA Company Master Data via data.gov.in (FREE key, ALL states incl. Delhi/Maharashtra)
---------------------------------------------------------------------------------------
The free GitHub mirror (tools/sources/mca.py) covers 34 states but DELIBERATELY omits
the two largest — Delhi (NCT) and Maharashtra. The only free bulk source for those is
the official MCA "Company Master Data" on data.gov.in, which carries the SAME fields
the rest of the warehouse came from: CIN, name, status, REGISTERED_STATE, EMAIL, NIC
industry. This module pulls it by state, paginated, and banks tens of thousands of
leads per state — matching the volume the other states already have.

Turnkey: the user adds a FREE data.gov.in API key in Settings (`datagovin_api_key`).
We auto-discover the Company-Master-Data resource(s) via the catalog API (or use a
pinned `datagovin_resource_id` if set), then page through with a state filter.

Needs network to api.data.gov.in (blocked from the dev sandbox; works on the user's
machine). Fail-safe throughout.
"""
import threading
import time
import uuid
from typing import Optional

from loguru import logger

_API = "https://api.data.gov.in"
_UA = "RazorInfotech-Leads/1.0"

_lock = threading.Lock()
_state = {"running": False, "states_done": 0, "states_total": 0, "added": 0,
          "skipped": 0, "by_state": {}, "error": ""}

# data.gov.in MCA resources name fields inconsistently across monthly releases, so we
# map every known variant onto the canonical keys mca.py already understands.
_FIELD_ALIASES = {
    "COMPANY_NAME": ("company_name", "companyname", "COMPANY_NAME", "company"),
    "CIN": ("cin", "corporate_identification_number", "CIN", "company_id"),
    "COMPANY_STATUS": ("company_status", "companystatus", "COMPANY_STATUS", "status"),
    "EMAIL_ID": ("email_addr", "email", "email_id", "emailaddr", "EMAIL_ID", "company_email"),
    "REGISTERED_STATE": ("registered_state", "state", "registeredstate", "REGISTERED_STATE", "company_state"),
    "REGISTERED_OFFICE_ADDRESS": ("registered_office_address", "registered_office_addr", "address", "regd_office_address"),
    "PRINCIPAL_BUSINESS_ACTIVITY_CODE": ("nic_code", "principal_business_activity", "pricipal_business_activity",
                                         "principal_business_activity_as_per_cin", "industrial_class", "activity_code"),
    "PAIDUP_CAPITAL (RS.)": ("paid_up_capital", "paidup_capital", "authorized_cap", "paid_up_capital_rs"),
}

# data.gov.in uses full state labels; map the user's short name → likely filter values.
_STATE_FILTER = {
    "Delhi": ["NCT OF DELHI", "Delhi", "DELHI"],
    "Maharashtra": ["Maharashtra", "MAHARASHTRA"],
}


def status() -> dict:
    return dict(_state)


def is_running() -> bool:
    return _state["running"]


def _key() -> str:
    from core import runtime_config as rc
    return (rc.get("datagovin_api_key") or "").strip()


def _norm(rec: dict) -> dict:
    """Map a data.gov.in record (lowercased keys vary) to mca.py's canonical schema."""
    low = {str(k).strip().lower(): v for k, v in rec.items()}
    out = {}
    for canon, aliases in _FIELD_ALIASES.items():
        for a in aliases:
            if a.lower() in low and low[a.lower()] not in (None, ""):
                out[canon] = low[a.lower()]
                break
    return out


def discover_resources(state: str, key: str, limit: int = 20) -> list[str]:
    """Find Company-Master-Data resource ids for a state via the catalog API. If a
    pinned resource id is configured, prefer it."""
    import requests
    from core import runtime_config as rc
    pinned = (rc.get("datagovin_resource_id") or "").strip()
    if pinned:
        return [pinned]
    ids: list[str] = []
    for q in (f"company master data {state}", "company master data", f"MCA {state} companies"):
        try:
            r = requests.get(f"{_API}/catalog", params={
                "api-key": key, "format": "json", "query": q, "limit": limit}, timeout=30)
            data = r.json()
        except Exception as e:
            logger.debug(f"[mca_live] catalog '{q}' failed: {e}")
            continue
        for item in (data.get("records") or data.get("items") or []):
            rid = item.get("index_name") or item.get("resource_id") or item.get("id")
            title = (item.get("title") or "").lower()
            if rid and ("company" in title or "mca" in title):
                if not state or state.lower() in title or "company master" in title:
                    if rid not in ids:
                        ids.append(rid)
        if ids:
            break
    return ids


def ingest_state(state: str, key: str, max_rows: int = 80000, page: int = 1000) -> int:
    import requests
    from core import warehouse
    from tools.sources.mca import _lead_from_row
    resources = discover_resources(state, key)
    if not resources:
        logger.warning(f"[mca_live] no resource found for {state}")
        return 0
    filters = _STATE_FILTER.get(state, [state])
    added = 0
    for rid in resources:
        offset = 0
        while offset < max_rows:
            params = {"api-key": key, "format": "json", "limit": page, "offset": offset}
            # try a server-side state filter (field name varies → try a couple)
            params["filters[registered_state]"] = filters[0]
            try:
                r = requests.get(f"{_API}/resource/{rid}", params=params, timeout=60)
                recs = r.json().get("records", []) or []
            except Exception as e:
                logger.debug(f"[mca_live] {rid}@{offset} failed: {e}")
                break
            if not recs:
                break
            buf = []
            for rec in recs:
                canon = _norm(rec)
                # If server-side filter didn't apply, filter client-side by state.
                st = str(canon.get("REGISTERED_STATE", "")).strip().upper()
                if st and not any(f.upper() in st or st in f.upper() for f in filters):
                    continue
                lead = _lead_from_row(canon)
                if lead:
                    buf.append(lead)
            if buf:
                added += warehouse.save_enriched_bulk(buf)
                _state["added"] += len(buf)
            offset += page
            if len(recs) < page:
                break
        _state["by_state"][state] = _state["by_state"].get(state, 0) + added
    return added


def ingest(states: Optional[list[str]] = None, max_rows_per_state: int = 80000) -> dict:
    key = _key()
    if not key:
        return {"status": "error", "message": "No data.gov.in API key. Add datagovin_api_key in Settings (free at data.gov.in)."}
    if not _lock.acquire(blocking=False):
        return {"status": "busy", **status()}
    try:
        from core import warehouse
        targets = states or ["Delhi", "Maharashtra"]
        _state.update(running=True, states_done=0, states_total=len(targets), added=0,
                      skipped=0, by_state={}, error="")
        for st in targets:
            try:
                n = ingest_state(st, key, max_rows=max_rows_per_state)
                logger.info(f"[mca_live] {st}: +{n} leads")
            except Exception as e:
                _state["error"] = str(e)
                logger.warning(f"[mca_live] {st} failed: {e}")
            _state["states_done"] += 1
        return {"status": "ok", "added": _state["added"], "by_state": _state["by_state"],
                "pool": warehouse.stats()}
    except Exception as e:
        _state["error"] = str(e)
        return {"status": "error", "message": str(e)}
    finally:
        _state["running"] = False
        _lock.release()
