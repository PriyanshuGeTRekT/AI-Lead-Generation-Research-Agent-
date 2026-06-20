"""
No-HRMS Detector  (the targeting core)
--------------------------------------
You cannot search for "companies without HRMS" — you must DETECT absence from
signals. This module fingerprints a company's web/careers footprint and returns a
calibrated `no_hrms_confidence` (0..1, higher = more confident they have NO HRMS),
so the pipeline can prioritize greenfield prospects and DROP companies that already
run an HRMS *before* spending any LLM tokens on them.

Method (deterministic, no paid API):
  1. Positive fingerprint  — known HRMS/payroll vendor footprints (script src,
     vendor subdomains in apply links, text mentions). Found ⇒ HAS HRMS.
  2. Manual fingerprint     — "attendance register", "salary in excel",
     mailto:/Google-Form apply flow ⇒ strong NO-HRMS.
  3. Application-method      — how candidates apply (vendor ATS portal vs email vs
     static page) is the single best tell of HR-tech maturity.
  4. Calibration            — combine into a confidence + a recommended pitch angle.

Returns:
  {
    has_hrms: bool,
    no_hrms_confidence: float,            # 0..1
    detected_vendors: [str],
    maturity: 'manual'|'legacy'|'modern'|'none'|'unknown',
    application_method: 'ats_portal'|'email'|'google_form'|'static'|'unknown',
    signals: [str],                       # human-readable evidence
    pitch_angle: str,
  }
"""
import re
from urllib.parse import urljoin
from typing import Dict, List, Optional

import requests
from loguru import logger

# ── Vendor fingerprints ──────────────────────────────────────────────────────
# name → (patterns, tier).  tier: 'legacy' (enterprise) | 'modern' (saas).
# Presence of ANY of these ⇒ the company already runs HR tech ⇒ exclude.
_VENDORS: dict[str, tuple[list[str], str]] = {
    # India-heavy mid-market HRMS / payroll
    "Darwinbox": (["darwinbox.com", "darwinbox"], "modern"),
    "Keka HR": (["keka.com", "keka hr", "keka.io"], "modern"),
    "GreytHR": (["greythr.com", "greythr", "greytip"], "modern"),
    "Zoho People": (["zoho.com/people", "zoho people", "zohopayroll", "zoho payroll"], "modern"),
    "Zimyo": (["zimyo.com", "zimyo"], "modern"),
    "HROne": (["hrone.cloud", "hrone hr", "hrone"], "modern"),
    "Pocket HRMS": (["pockethrms.com", "pocket hrms"], "modern"),
    "sumHR": (["sumhr.com", "sumhr"], "modern"),
    "Kredily": (["kredily.com", "kredily"], "modern"),
    "factoHR": (["factohr.com", "factohr"], "modern"),
    "Quikchex": (["quikchex.in", "quikchex"], "modern"),
    "Beehive HRMS": (["beehivehrms.com", "beehive hrms"], "modern"),
    "Spine HR": (["spinehr.com", "spine hr", "spinepayroll"], "legacy"),
    "PeopleStrong": (["peoplestrong.com", "peoplestrong"], "modern"),
    "Ramco HCM": (["ramco.com/hcm", "ramco hr"], "legacy"),
    "RazorpayX Payroll": (["razorpay.com/payroll", "razorpayx payroll", "xpayroll"], "modern"),
    # Global SaaS
    "Workday": (["workday.com", "myworkday.com", "workday hcm"], "modern"),
    "SAP SuccessFactors": (["successfactors", "sap successfactors", "sap hcm", "sap.com/hr"], "legacy"),
    "Oracle HCM": (["oracle.com/human-capital", "oracle hcm", "peoplesoft", "oraclecloud.com/hcm"], "legacy"),
    "BambooHR": (["bamboohr.com", "bamboohr"], "modern"),
    "Rippling": (["rippling.com", "rippling"], "modern"),
    "Gusto": (["gusto.com", "gusto payroll"], "modern"),
    "Deel": (["deel.com", "letsdeel.com"], "modern"),
    "HiBob": (["hibob.com", "bob hr"], "modern"),
    "Personio": (["personio.com", "personio.de"], "modern"),
    "Zenefits": (["zenefits.com"], "modern"),
    "Namely": (["namely.com"], "modern"),
    "UKG": (["ukg.com", "ultipro", "kronos"], "legacy"),
    "ADP": (["adp.com", "workforcenow", "adp vantage"], "legacy"),
    "Ceridian Dayforce": (["dayforce", "ceridian.com"], "legacy"),
    "Paycom": (["paycom.com"], "modern"),
    "Paychex": (["paychex.com"], "modern"),
    "Freshteam": (["freshteam.com", "freshworks.com/hrms"], "modern"),
    # ATS / recruiting portals — weaker signal (recruiting tool ≠ full HRMS) but
    # still indicates HR-tech adoption.
    "Workday Recruiting": (["workday.com/recruiting"], "modern"),
    "SmartRecruiters": (["smartrecruiters.com"], "modern"),
    "Lever": (["jobs.lever.co", "lever.co"], "modern"),
    "Greenhouse": (["greenhouse.io", "boards.greenhouse.io"], "modern"),
    "Zoho Recruit": (["zoho.com/recruit", "zoho recruit"], "modern"),
}

# Manual / no-tooling signals — strong evidence of NO HRMS.
_MANUAL_SIGNALS = [
    "attendance register", "muster roll", "salary in excel", "payroll in excel",
    "manual payroll", "manual attendance", "ms excel", "google sheet", "google sheets",
    "maintain registers", "paper-based", "manual hr", "excel-based", "excel based",
    "tally payroll", "salary sheet",
]

# Apply-by-email / form patterns in raw HTML (href scan).
_EMAIL_APPLY_RE = re.compile(r"mailto:[^\"'>\s]*(career|job|hr|recruit|hiring|apply|resume|cv)", re.I)
_GFORM_RE = re.compile(r"(docs\.google\.com/forms|forms\.gle|typeform\.com|jotform\.com)", re.I)

_PITCH = {
    "manual": (
        "They run HR manually (Excel/registers) — strongest prospect. Lead with the "
        "cost of manual payroll/attendance errors at their headcount and the hours saved."
    ),
    "none": (
        "No HR system detected — greenfield. Lead with the business case: what manual HR "
        "is costing them at their size, and how fast HumanMaximizer pays back."
    ),
    "legacy": (
        "Legacy enterprise HRMS — displacement play. Pitch modern mobile UX, faster rollout, "
        "and lower TCO; probe contract-renewal timing."
    ),
    "modern": (
        "Already on a modern HRMS — only pursue on a specific gap. Probe pricing pain, missing "
        "modules, or renewal date; otherwise deprioritize."
    ),
    "unknown": (
        "Insufficient signal — treat as a maybe. Worth a light-touch check before investing."
    ),
}


def _fetch(url: str, timeout: int = 7) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; LeadGenBot/1.0)"}
        return requests.get(url, headers=headers, timeout=timeout).text
    except Exception:
        return ""


def _gather_html(website_url: str, prefetched: Optional[str]) -> str:
    """Homepage (prefetched if available) + careers/jobs pages, raw HTML."""
    html = prefetched or _fetch(website_url)
    base = website_url.rstrip("/")
    for path in ("/careers", "/career", "/jobs", "/job-openings", "/work-with-us", "/about"):
        html += "\n" + _fetch(urljoin(base + "/", path.lstrip("/")), timeout=5)
    return html


def detect_hrms(
    website_url: str,
    prefetched_html: Optional[str] = None,
    company_name: str = "",
) -> Dict:
    """Run the full no-HRMS fingerprint. Fail-safe: returns an 'unknown' verdict."""
    try:
        html = _gather_html(website_url, prefetched_html)
    except Exception:
        html = prefetched_html or ""

    if not html:
        return {
            "has_hrms": False,
            "no_hrms_confidence": 0.4,
            "detected_vendors": [],
            "maturity": "unknown",
            "application_method": "unknown",
            "signals": ["no page content retrieved"],
            "pitch_angle": _PITCH["unknown"],
        }

    text = html.lower()
    signals: List[str] = []

    # 1) Vendor fingerprint
    detected: List[str] = []
    tiers: List[str] = []
    for name, (patterns, tier) in _VENDORS.items():
        if any(p in text for p in patterns):
            detected.append(name)
            tiers.append(tier)
            signals.append(f"HR-tech footprint: {name}")

    # 2) Manual signals
    manual_hits = [s for s in _MANUAL_SIGNALS if s in text]
    if manual_hits:
        signals.append(f"manual-HR phrasing: {', '.join(manual_hits[:3])}")

    # 3) Application method
    if _EMAIL_APPLY_RE.search(html):
        application_method = "email"
        signals.append("applications go to a plain email address")
    elif _GFORM_RE.search(html):
        application_method = "google_form"
        signals.append("applications collected via Google Form / Typeform")
    elif detected:
        application_method = "ats_portal"
    elif re.search(r"(careers|jobs|hiring|vacanc)", text):
        application_method = "static"
        signals.append("static careers page, no detectable HR system")
    else:
        application_method = "unknown"

    # ── Calibrate ────────────────────────────────────────────────────────────
    has_hrms = bool(detected)
    if has_hrms:
        # They already run HR tech → very low chance of being greenfield.
        maturity = "legacy" if "legacy" in tiers else "modern"
        confidence = 0.05 if "modern" in tiers or "legacy" in tiers else 0.1
    elif manual_hits:
        maturity = "manual"
        confidence = 0.9
    elif application_method in ("email", "google_form"):
        maturity = "none"
        confidence = 0.82
    elif application_method == "static":
        maturity = "none"
        confidence = 0.6
    else:
        maturity = "unknown"
        confidence = 0.45

    if company_name:
        logger.info(
            f"[HRMS] {company_name}: has_hrms={has_hrms} conf_no_hrms={confidence} "
            f"vendors={detected or '—'} apply={application_method}"
        )

    return {
        "has_hrms": has_hrms,
        "no_hrms_confidence": round(confidence, 2),
        "detected_vendors": detected,
        "maturity": maturity,
        "application_method": application_method,
        "signals": signals[:6],
        "pitch_angle": _PITCH.get(maturity, _PITCH["unknown"]),
    }
