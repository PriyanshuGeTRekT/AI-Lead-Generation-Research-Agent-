"""
Buying-Signal scoring — turn a flat lead list into a ranked Hot List.
---------------------------------------------------------------------
The old tool (and our volume pile) selected on FIT ("a manufacturing company in
Delhi"). Conversion (0.05% closed) dies because fit ≠ intent. This module scores
each lead 0–100 on how likely it is to BUY HRMS now, in two layers:

  OFFLINE (no network — runs on the warehouse we already have):
    • HR-intensity of the industry  (BPO/staffing/manufacturing/hospital… = high)
    • reachability                  (mobile? email? named decision-maker?)
    • no-HRMS likelihood            (the absence signal — they have the gap)
    • entity quality / size proxy   (Pvt Ltd, established, sweet-spot headcount)

  LIVE (needs network + a key — runs on the user's machine):
    • active HR/payroll hiring      (Serper job search, or Crustdata open_jobs)
    • headcount growth              (Crustdata — its core differentiator)
    • recent funding                (Serper news)

`score(lead, live=False)` returns (0–100, reasons[]). The CRM ranks on it; the Hot
List is the top slice. Fully deterministic offline so a presentable list exists with
zero network; live layer only adds boosts when reachable.
"""
import re
from typing import Optional

# HR-intensive industries (lots of people, manual HR, real HRMS pain) → base points.
# Reuses the spirit of lead_processor._INDUSTRY_FIT but tuned for buy-likelihood.
_INDUSTRY_BASE = {
    "bpo": 40, "staffing": 40, "facility management": 38, "manpower": 40,
    "recruitment": 40, "recruiting": 40, "hr consulting": 40, "hr services": 40,
    "outsourcing": 40, "kpo": 38, "ites": 32,
    "manufacturing": 38, "textile": 37, "automotive": 36, "auto components": 36,
    "hospital": 36, "healthcare": 34, "pharma": 34, "pharmaceutical": 34,
    "hotel": 34, "hospitality": 34, "logistics": 34, "construction": 32,
    "food processing": 32, "steel": 32, "chemical": 30, "education": 28,
    "IT services": 30, "software": 30, "exports": 30,
    "management consulting": 28, "consulting": 26, "consultancy": 26,
    "real estate": 26, "wholesale": 22, "services": 22, "business": 18,
    "retail": 14,
}

# HR-intensity read straight from the COMPANY NAME — labels are coarse (half this
# segment is just tagged "consulting"), but a name like "XYZ Staffing Solutions" or
# "ABC Manpower / Payroll Services" is unambiguously people-heavy → real HRMS pain.
_HR_NAME = re.compile(
    r"\b(staffing|recruit\w*|manpower|payroll|outsourc\w*|bpo|kpo|placement|"
    r"workforce|human\s*resource|hr\s*(solutions?|services?|consult)|"
    r"facilit(y|ies)\s*manage|housekeeping|security\s*services?|"
    r"talent|hiring|staff\w*\s*solutions?)\b", re.I)

# Roles that mean you've reached the actual buyer (not a junior).
_TOP_ROLE = re.compile(
    r"\b(founder|co-?founder|owner|proprietor|partner|director|managing|"
    r"\bmd\b|\bceo\b|chief|president|head|principal|promoter)\b", re.I)

# Company-name tokens that signal a real, employing entity (vs a shop/sole prop).
_ENTITY_STRONG = re.compile(
    r"\b(pvt|private limited|limited|ltd|industries|technologies|solutions|"
    r"systems|enterprises|corporation|group|manufactur|exports?|logistics|"
    r"hospital|hotels?|infotech|services)\b", re.I)
_ENTITY_WEAK = re.compile(r"\b(store|shop|stationery|kirana|boutique|salon|cafe)\b", re.I)

_DEAD = {"strike off", "struck off", "dissolved", "amalgamated", "liquidated",
         "dormant", "under process of striking off"}


def _industry_base(industry: str) -> int:
    s = (industry or "").lower().strip()
    if s in _INDUSTRY_BASE:
        return _INDUSTRY_BASE[s]
    for k, v in _INDUSTRY_BASE.items():
        if k in s or s in k:
            return v
    return 18


def score_offline(lead: dict) -> tuple[int, list[str]]:
    """Deterministic buy-likelihood from data already in the warehouse. 0–100."""
    payload = lead.get("payload") if isinstance(lead.get("payload"), dict) else lead
    reasons: list[str] = []
    pts = 0

    # 1) Industry HR-intensity (0–40), refined by the company NAME when the label
    #    is coarse — a "Staffing/Manpower/Payroll/BPO" name is people-heavy regardless.
    name = lead.get("company_name") or payload.get("company_name") or ""
    ind = lead.get("industry") or payload.get("industry") or ""
    base = _industry_base(ind)
    if _HR_NAME.search(name):
        base = max(base, 38); pts += 6
        reasons.append("HR-intensive (name: staffing/payroll/manpower)")
    pts += base
    if base >= 34 and "HR-intensive" not in (reasons[-1] if reasons else ""):
        reasons.append(f"HR-intensive industry ({ind})")

    # 2) Reachability — every lead in this segment already has a phone, so phone is a
    #    small base, NOT a differentiator. The differentiator is a NAMED decision-maker:
    #    you can ask for them by name, which is the best predictor of a productive call.
    has_mobile = bool(lead.get("mobile") or (lead.get("phone") and str(lead.get("phone"))[:1] in "6789"))
    has_phone = bool(lead.get("phone") or payload.get("phone"))
    emails = lead.get("contact_emails") or payload.get("contact_emails") or []
    has_email = bool(lead.get("dm_email") or payload.get("dm_email") or emails)
    dm_name = lead.get("dm_name") or payload.get("dm_name") or ""
    dm_role = lead.get("dm_role") or payload.get("dm_role") or ""
    if has_mobile:
        pts += 6; reasons.append("reachable by mobile")
    elif has_phone:
        pts += 3; reasons.append("reachable by phone")
    if has_email:
        pts += 6; reasons.append("email on file")
    if dm_name:
        pts += 16; reasons.append(f"named decision-maker ({dm_name})")
        if _TOP_ROLE.search(dm_role):
            pts += 6; reasons.append(f"reaches the buyer directly ({dm_role})")

    # 3) No-HRMS absence signal (0–14)
    hrms = lead.get("hrms") or payload.get("hrms") or {}
    conf = hrms.get("no_hrms_confidence")
    if hrms.get("has_hrms") is True:
        reasons.append("already has an HRMS (down-ranked)")
        pts -= 25
    elif isinstance(conf, (int, float)) and conf >= 0.6:
        pts += 14; reasons.append("no HRMS detected")
    else:
        pts += 5  # default: most SMEs in our pool have no HRMS

    # 3b) Active-business tie-breaker — a live website means a real, contactable
    #     operation (and we likely read their team page). Small but spreads the floor.
    web = lead.get("website") or payload.get("website") or ""
    if isinstance(web, str) and web.startswith("http") and not web.endswith(".lead"):
        pts += 4; reasons.append("active website")

    # 4) Entity quality / size proxy (0–16, can be negative)
    status = (payload.get("company_status") or "").lower()
    if any(d in status for d in _DEAD):
        return 0, ["inactive / struck-off company"]
    if _ENTITY_STRONG.search(name):
        pts += 8; reasons.append("registered entity (Ltd/Industries)")
    if _ENTITY_WEAK.search(name):
        pts -= 10; reasons.append("looks like a small shop (down-ranked)")
    # Headcount sweet spot for HRMS = ~50–500. Penalize tiny / giant if known.
    emp = lead.get("employee_max") or payload.get("employee_max")
    try:
        emp = int(emp) if emp else None
    except Exception:
        emp = None
    if emp:
        if 30 <= emp <= 500:
            pts += 8; reasons.append(f"sweet-spot size (~{emp} staff)")
        elif emp < 10:
            pts -= 8; reasons.append("very small (<10 staff)")
        elif emp > 2000:
            pts -= 6; reasons.append("enterprise (likely has HRMS)")

    pts = max(0, min(100, pts))
    return pts, reasons


# ── LIVE layer (network + key; runs on the user's machine) ────────────────────
import threading as _threading
_serper_lock = _threading.Lock()
_dead_keys: set[str] = set()   # keys that returned "Not enough credits" — skip them
_key_cursor = [0]


def _serper_keys() -> list[str]:
    """All configured Serper keys: serper_api_key + comma-separated serper_api_keys.
    Free Serper = 2,500 searches/account; stack several free keys to scale."""
    from core import runtime_config as rc
    keys = [(rc.get("serper_api_key") or "").strip()]
    extra = (rc.get("serper_api_keys") or "").strip()
    if extra:
        keys += [k.strip() for k in extra.split(",") if k.strip()]
    seen, out = set(), []
    for k in keys:
        if k and k not in seen and k not in _dead_keys:
            seen.add(k); out.append(k)
    return out


def _serper(query: str, kind: str = "search") -> dict:
    """Query Serper, rotating across all live keys; retires a key on credit exhaustion."""
    import requests
    keys = _serper_keys()
    for _ in range(len(keys)):
        with _serper_lock:
            k = keys[_key_cursor[0] % len(keys)]
            _key_cursor[0] += 1
        try:
            r = requests.post(f"https://google.serper.dev/{kind}",
                              headers={"X-API-KEY": k, "Content-Type": "application/json"},
                              json={"q": query, "gl": "in", "num": 10}, timeout=12)
        except Exception:
            continue
        if r.status_code == 200:
            return r.json()
        # Out of credits → retire this key and try the next.
        if r.status_code == 400 and "credit" in r.text.lower():
            _dead_keys.add(k)
            keys = _serper_keys()
            if not keys:
                break
    return {}


def live_boost(lead: dict) -> tuple[int, list[str]]:
    """Add buying-intent boosts from live sources. Returns (boost, reasons). Needs
    a Serper or Crustdata key + network; returns (0,[]) otherwise. Fail-safe."""
    from core import runtime_config as rc
    company = lead.get("company_name") or ""
    domain = ""
    w = lead.get("website") or ""
    m = re.search(r"https?://([^/]+)", w)
    if m and ".lead" not in m.group(1):
        domain = m.group(1)
    boost, reasons = 0, []

    # Crustdata: the clean path for headcount growth + open jobs.
    try:
        from tools.sources import crustdata
        if crustdata.configured() and domain:
            c = crustdata.enrich_company(domain)
            ec = c.get("employee_count")
            # (Crustdata also exposes growth/open-jobs in its full payload; wired here
            #  as company enrichment — extend with screener signals when keyed.)
            if ec and isinstance(ec, (int, float)) and 30 <= ec <= 500:
                boost += 10; reasons.append("size confirmed in sweet spot (Crustdata)")
    except Exception:
        pass

    # Serper (free-tier friendly): ONE call/lead. We require SPECIFIC evidence, not just
    # a keyword — otherwise every Naukri "company overview" or any snippet mentioning
    # "crore" falsely triggers. Precision matters: a noisy signal is worse than none.
    if _serper_keys() and company:
        try:
            d = _serper(f'"{company}" ("HR" OR payroll OR recruiter OR "talent acquisition") '
                        f'(hiring OR vacancy OR "job opening" OR walk-in OR funding OR raised) India')
            hits = d.get("organic", []) or []
            hire_hit = fund_hit = False
            for h in hits[:8]:
                t = (h.get("title", "") + " | " + h.get("snippet", "")).lower()
                link = (h.get("link", "")).lower()
                # HIRING: needs an HR-role token AND a hiring/job token in the SAME result,
                # and ideally a jobs domain — i.e. an actual open HR/payroll role.
                hr_role = re.search(r"\b(hr |h\.r\.|payroll|recruit|talent acquisition|human resource)", t)
                job_word = re.search(r"\b(hiring|vacanc|job opening|walk-?in|now hiring|apply now|openings?)\b", t)
                if hr_role and job_word and re.search(r"naukri|linkedin|indeed|shine|monster|timesjobs|/career|/jobs", link + t):
                    hire_hit = True
                # FUNDING: needs explicit amount+round language, not bare "investment/crore".
                if re.search(r"(raise[sd]|secured|bags?|closes?)\s+(rs\.?|₹|inr|\$|usd)?\s?[\d.,]+\s*(crore|cr\b|lakh|million|mn|billion|bn)"
                             r"|series\s+[a-e]\b.*(funding|round|raise)|funding round|pre-?series", t):
                    fund_hit = True
            if hire_hit:
                boost += 22; reasons.append("actively hiring HR/payroll roles")
            if fund_hit:
                boost += 12; reasons.append("recent funding (budget + scaling)")
        except Exception:
            pass
    return boost, reasons


def score(lead: dict, live: bool = False) -> tuple[int, list[str]]:
    base, reasons = score_offline(lead)
    if live and base > 0:
        b, r = live_boost(lead)
        base = min(100, base + b)
        reasons += r
    return base, reasons
