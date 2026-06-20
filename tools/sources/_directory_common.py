"""
Shared helpers for B2B-directory sources (JustDial, IndiaMART, …).

Directory listings already carry name + locality + category, and often a phone.
This module turns a normalized candidate dict into a ready-to-show *enriched*
warehouse lead — the same shape OSM uses — so directory leads land graded and
contactable, not as empty raw rows.

A directory candidate is: {url, title, location, phone, industry, source}.
"""
import re
import uuid
from typing import Optional


def synthetic_key(lead: dict, tag_source: str) -> str:
    """Unique dedup URL for a lead that has no real website. Keyed by phone (so the
    same business dedups across harvests) and namespaced by source, since warehouse
    dedup is by host."""
    ph = re.sub(r"\D", "", lead.get("phone") or "")
    name = re.sub(r"[^a-z0-9]", "", (lead.get("company_name") or "").lower())[:24]
    tag = ("p" + ph) if ph else (name or lead.get("id", "x"))
    return f"https://{tag}.{tag_source}.lead"


def to_lead(c: dict, source_label: str, trusted: bool = False) -> dict:
    """Build an enriched lead from a directory candidate. `c` keys: title, url,
    location, phone, industry, source. Phones are marked trusted=False for scraped
    directories (re-checked by the validator); trusted=True for verified sources
    like Google Places."""
    from tools.contact_resolver import _normalize_phone
    phone = ""
    norm = _normalize_phone(c.get("phone", ""), trusted=trusted)
    if norm:
        phone = norm["number"]
    website = (c.get("url") or "").strip()
    if website and not website.startswith(("http://", "https://")):
        website = "https://" + website
    has_web, has_phone = bool(website), bool(phone)
    # Directory listing = a real, operating business actively marketing itself →
    # a solid lead. Reward direct contactability.
    score = 5.5 + (1.0 if has_web else 0) + (2.0 if has_phone else 0)
    lead = {
        "id": str(uuid.uuid4())[:8],
        "company_name": c.get("title", ""),
        "website": website,
        "industry": c.get("industry") or "business",
        "location": c.get("location") or "India",
        "phone": phone,
        "phone_type": norm["type"] if norm else None,
        "phone_source": c.get("source") if phone else None,
        "contact_emails": [],
        "source": source_label,
        "hrms": {"has_hrms": False, "no_hrms_confidence": 0.5, "vendors": [],
                 "note": f"HRMS not yet checked ({source_label}-sourced)"},
        "lead_score": {"predicted_score": round(score, 1),
                       "rationale": f"Listed, operating business ({source_label}) in target geo."},
        "qualification_score": round(score, 1),
        "status": "qualified" if (has_web and has_phone) else "enriched",
        "outreach_draft": None,
    }
    try:
        from core.lead_processor import process_lead
        lead = process_lead(lead)
    except Exception:
        pass
    return lead


def bank(candidates: list[dict], region: str, source_label: str, tag_source: str,
         trusted: bool = False) -> int:
    """Convert candidates → leads and upsert into the warehouse. Returns # banked."""
    from core import warehouse
    n = 0
    for c in candidates:
        lead = to_lead(c, source_label, trusted=trusted)
        if not (lead["website"] or lead["phone"]):
            continue
        if not lead["website"]:
            lead["website"] = synthetic_key(lead, tag_source)
        try:
            warehouse.save_enriched(lead, region=region)
            n += 1
        except Exception:
            pass
    return n
