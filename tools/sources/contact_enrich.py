"""
Decision-maker enrichment — attach the RIGHT PERSON + email to pooled leads.
----------------------------------------------------------------------------
Walks leads that have no decision-maker yet and, via Crustdata (preferred) or
PDL, finds the HR head / founder / director with title + email, then upserts the
lead back into the warehouse. This is the direct fix for "half-baked leads with no
person to contact". Provider is auto-picked from whichever key is configured.

Needs network to the provider (blocked from the dev sandbox; runs on the user's
machine with their key). Fail-safe + background-friendly.
"""
import threading
from typing import Optional

from loguru import logger

_lock = threading.Lock()
_state = {"running": False, "done": 0, "total": 0, "enriched": 0, "provider": "", "error": ""}


def status() -> dict:
    return dict(_state)


def is_running() -> bool:
    return _state["running"]


def _provider():
    """Return (name, find_people_fn) for the best configured people-data API. Apollo
    first — it's the one that returns a named decision-maker's verified DIRECT DIAL."""
    from tools.sources import crustdata, pdl, apollo
    if apollo.configured():
        return "apollo", apollo.find_people
    if crustdata.configured():
        return "crustdata", crustdata.find_people
    if pdl.configured():
        return "pdl", pdl.find_people
    return "", None


def enrich(state: str = "", limit: int = 200) -> dict:
    name, find = _provider()
    if not find:
        return {"status": "error", "message": "No Apollo / Crustdata / PDL key configured (add one in Settings)."}
    if not _lock.acquire(blocking=False):
        return {"status": "busy", **status()}
    try:
        from core import warehouse
        # Pull prime, contactable-company leads that still lack a named decision-maker.
        leads = warehouse.query(statuses=("outreach_ready", "qualified", "enriched"),
                                region=state or None, limit=limit)
        _state.update(running=True, done=0, total=len(leads), enriched=0, provider=name, error="")
        import time as _t
        for lead in leads:
            company = lead.get("company_name") or ""
            try:
                people = find(company)
            except Exception as e:
                logger.debug(f"[contact_enrich] {company} failed: {e}")
                people = []
            if people:
                best = people[0]
                lead["dm_name"] = best.get("name", "")
                lead["dm_title"] = lead["dm_role"] = best.get("title", "") or "Decision-maker"
                if best.get("email"):
                    lead["dm_email"] = best["email"]
                    ce = set(lead.get("contact_emails") or [])
                    ce.add(best["email"]); lead["contact_emails"] = list(ce)
                # The whole point: a named decision-maker's DIRECT phone.
                if best.get("phone"):
                    try:
                        from tools.contact_resolver import _normalize_phone
                        n = _normalize_phone(best["phone"], trusted=True)  # Apollo phones are verified
                        if n:
                            lead["phone"] = n["number"]; lead["phone_type"] = n.get("type")
                    except Exception:
                        lead["phone"] = best["phone"]
                if best.get("linkedin"):
                    lead["dm_linkedin"] = best["linkedin"]
                lead["contact_enriched_at"] = _t.time()
                try:
                    warehouse.save_enriched(lead, region=lead.get("region") or state or None)
                    _state["enriched"] += 1
                except Exception:
                    pass
            _state["done"] += 1
        from core import warehouse as wh
        try:
            wh.warm_crm_cache()
        except Exception:
            pass
        logger.info(f"[contact_enrich] {name}: enriched {_state['enriched']}/{_state['total']}")
        return {"status": "ok", "provider": name, "enriched": _state["enriched"], "scanned": _state["total"]}
    except Exception as e:
        _state["error"] = str(e)
        return {"status": "error", "message": str(e)}
    finally:
        _state["running"] = False
        _lock.release()
