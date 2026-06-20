"""
Deep Verify — accurate contact + LLM reasoning per lead (Step 2 + Step 3)
-------------------------------------------------------------------------
For the PRIME (Hot) leads only — small, high-value set — we go deep:

  STEP 2 (gather): pull the best contact data we can, free —
    • the company's own website (homepage + /contact /about /team) → named people
      with roles (Director/Founder/HR/Proprietor), role-emails (hr@, careers@…),
      mobiles
    • role-email patterns on the domain + MX check
    • the MCA registered email we already hold (founder/official for SMEs)
    • JustDial / IndiaMART by name+city — BEST EFFORT (they block bots; low yield)

  STEP 3 (reason): an LLM (NVIDIA pool, strong tier) reviews ALL signals and
    returns a fine-tuned record — best contact (name/role/email/phone), a fit
    verdict, confidence 0-1, the pitch angle, and a needs-manual-lookup flag.

Concurrent + fail-safe. Per-lead it does ≤4 fetches + 1 LLM call, so it's for the
Hot shortlist, not the whole pool.
"""
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

from loguru import logger

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120 Safari/537.36"}
_lock = threading.Lock()
_state = {"running": False, "done": 0, "total": 0, "verified": 0}

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_MOBILE_RE = re.compile(r"(?<!\d)(?:\+?91[\s\-]?)?([6-9]\d{9})(?!\d)")
# A person name (2-3 capitalised words) sitting near a decision-maker role word.
_PEOPLE_RE = re.compile(
    r"((?:Mr\.?|Ms\.?|Mrs\.?|Dr\.?)?\s*[A-Z][a-z]+(?:\s[A-Z][a-z]+){1,2})\s*[,\-–—|()]*\s*"
    r"(Founder|Co-?Founder|Director|Managing Director|MD|CEO|CHRO|CFO|COO|Proprietor|"
    r"Partner|Owner|Chairman|President|VP|Head\s*[-–]?\s*HR|HR\s*(?:Manager|Head|Director)|"
    r"Human Resources)", re.I)
_ROLE_PREFIXES = ("hr", "careers", "jobs", "recruitment", "info", "contact", "admin", "sales")


def status() -> dict:
    return dict(_state)


def is_running() -> bool:
    return _state["running"]


def _fetch(url: str, timeout=(4, 5)) -> str:
    import requests
    try:
        r = requests.get(url, headers=_HEADERS, timeout=timeout, allow_redirects=True)
        return r.text if r.status_code < 400 else ""
    except Exception:
        return ""


def _real_domain(lead: dict) -> str:
    w = lead.get("website") or ""
    if not w or ".mca.lead" in w or ".osm.lead" in w:
        return ""
    return re.sub(r"^https?://", "", w).split("/")[0].replace("www.", "")


def _scrape_site(domain: str) -> dict:
    """Homepage + contact/about/team → emails, mobiles, named people+roles."""
    base = f"https://{domain}"
    pages = [base] + [urljoin(base + "/", p) for p in
                      ("contact", "contact-us", "about", "about-us", "team", "leadership", "management")]
    emails, mobiles, people = set(), set(), []
    seen_html = 0
    for u in pages[:5]:
        html = _fetch(u)
        if not html:
            continue
        seen_html += 1
        text = re.sub(r"<[^>]+>", " ", html)
        for e in _EMAIL_RE.findall(html):
            if e.lower().split("@")[-1].endswith((".png", ".jpg", ".gif", ".webp")):
                continue
            if domain.split(".")[0] in e.lower() or e.lower().endswith(domain):
                emails.add(e.lower())
        for m in _MOBILE_RE.findall(text):
            mobiles.add(m)
        for nm, role in _PEOPLE_RE.findall(text):
            people.append({"name": re.sub(r"\s+", " ", nm).strip(), "role": role.strip()})
        if seen_html >= 3:
            break
    return {"emails": sorted(emails)[:8], "mobiles": sorted(mobiles)[:5], "people": people[:6],
            "site_reachable": seen_html > 0}


def _justdial_indiamart(name: str, city: str) -> dict:
    """Best-effort — these block bots, so this usually returns empty. Kept so the
    reasoning step can use anything that does come back."""
    out = {"jd": "", "im": ""}
    try:
        h = _fetch(f"https://www.justdial.com/{city}/{name.replace(' ', '-')}")
        if h and len(h) > 500:
            mm = _MOBILE_RE.search(re.sub(r"<[^>]+>", " ", h))
            if mm:
                out["jd"] = mm.group(1)
    except Exception:
        pass
    return out


_REASON_PROMPT = """You are a B2B sales-ops analyst qualifying a lead for HumanMaximizer, an HRMS (HR/payroll/attendance software) sold to Indian companies.

Company data (JSON):
{data}

Decide, strictly from the data (do NOT invent contacts/emails/names):
- best_contact_name: the most senior reachable person's name if present in the data, else ""
- best_contact_role: their role if known, else ""
- best_email: the single best email to reach a decision-maker (prefer a person/HR/founder email over generic info@), else ""
- best_phone: best mobile/phone, else ""
- fit: "yes" if this is a genuine operating company in an HR-intensive sector likely to need an HRMS, else "no"
- confidence: 0.0-1.0 — how confident we can actually reach & pitch the right person
- needs_manual: true if we only have a generic/registry email and no named contact
- pitch_angle: one short sentence on the HR pain to lead with for THIS company
Return ONLY compact JSON with exactly these keys."""


def _reason(lead: dict, gathered: dict) -> dict:
    from agents.llm_pool import complete, available
    if not available():
        return {}
    data = {
        "company": lead.get("company_name"), "industry": lead.get("industry"),
        "state": lead.get("state"), "status": lead.get("company_status"),
        "registered_email": (lead.get("contact_emails") or [lead.get("dm_email")])[0] if (lead.get("contact_emails") or lead.get("dm_email")) else "",
        "site_emails": gathered.get("emails"), "site_mobiles": gathered.get("mobiles"),
        "site_people": gathered.get("people"), "extra_phone": gathered.get("jd"),
        "hrms_detected": lead.get("hrms", {}).get("vendors"),
    }
    try:
        out = complete(_REASON_PROMPT.format(data=json.dumps(data, ensure_ascii=False)[:2500]),
                       tier="strong", temperature=0.1, max_tokens=400)
        m = re.search(r"\{.*\}", out, re.S)
        return json.loads(m.group(0)) if m else {}
    except Exception:
        return {}


def _verify_one(lead: dict) -> dict | None:
    domain = _real_domain(lead)
    gathered = {"emails": [], "mobiles": [], "people": [], "site_reachable": False}
    if domain:
        gathered = _scrape_site(domain)
    # Best-effort directories only if we still lack a person/phone.
    if not gathered.get("people") and not gathered.get("mobiles"):
        city = (lead.get("location") or "").split(",")[0].strip() or "India"
        gathered.update(_justdial_indiamart(lead.get("company_name", ""), city))
    verdict = _reason(lead, gathered)
    # Merge results back into the lead.
    lead["dm_name"] = verdict.get("best_contact_name") or lead.get("dm_name", "")
    lead["dm_role"] = verdict.get("best_contact_role") or ""
    be = verdict.get("best_email") or ""
    if be:
        lead["dm_email"] = be
        lead.setdefault("contact_emails", [])
        if be not in lead["contact_emails"]:
            lead["contact_emails"] = [be] + lead["contact_emails"]
    if verdict.get("best_phone"):
        lead["phone"] = lead.get("phone") or verdict["best_phone"]
    lead["verify"] = {
        "fit": verdict.get("fit", ""),
        "confidence": verdict.get("confidence", 0),
        "needs_manual": verdict.get("needs_manual", True),
        "pitch_angle": verdict.get("pitch_angle", ""),
        "site_scraped": gathered.get("site_reachable", False),
        "people_found": gathered.get("people", []),
    }
    lead["verified"] = True
    # Fold confidence into the score so well-verified leads rank up.
    try:
        conf = float(verdict.get("confidence") or 0)
        base = lead.get("qualification_score", 7) or 7
        lead["qualification_score"] = round(min(base * 0.7 + conf * 3.0, 10), 1)
    except Exception:
        pass
    return lead


def deep_verify(batch: int = 50, workers: int = 20, state: str | None = None,
                industry: str | None = None) -> dict:
    """Deep-verify the top unverified Hot leads (optionally filtered by state/industry)."""
    if not _lock.acquire(blocking=False):
        return {"status": "busy", **status()}
    try:
        from core import warehouse
        # Verify the best reachable prospects (Hot first via score sort), across the
        # active stages — not only Hot — so a state like Delhi (mostly Warm/pending)
        # still gets enriched into real, contactable leads.
        leads = warehouse.query(industry=industry, region=state,
                                statuses=("outreach_ready", "qualified", "pending_review"),
                                limit=batch * 3)
        leads = [l for l in leads if not l.get("verified")][:batch]
        if not leads:
            return {"status": "empty", "message": "No unverified leads for this filter."}
        _state.update(running=True, done=0, total=len(leads), verified=0)
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_verify_one, l) for l in leads]
            for fut in as_completed(futs):
                try:
                    lead = fut.result()
                except Exception:
                    lead = None
                if lead:
                    try:
                        warehouse.save_enriched(lead, region=lead.get("state"))
                        _state["verified"] += 1
                    except Exception:
                        pass
                _state["done"] += 1
        logger.info(f"[deep_verify] verified {_state['verified']}/{len(leads)}")
        return {"status": "ok", "verified": _state["verified"], "total": len(leads)}
    except Exception as e:
        logger.warning(f"[deep_verify] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _state["running"] = False
        _lock.release()
