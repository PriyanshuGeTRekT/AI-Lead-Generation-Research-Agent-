"""
HR Tech Stack Detector
------------------------
Identifies what HR software a prospect company currently uses.
This is critical for tailoring the sales pitch:
  - "Excel / manual" → sell automation and time savings
  - "Legacy system (SAP/Oracle)" → sell modern UX and mobile access
  - "Competitor (Darwinbox/Keka)" → need displacement angle, ask about contract renewal
  - "No detectable HRMS" → strongest prospect, greenfield opportunity

Detection method: scan the company website HTML and job postings for known
software signatures (script tags, meta tags, cookie names, text mentions).
No external API needed.

Returns:
  {
    "current_tools": ["SAP SuccessFactors"],   # detected software
    "maturity": "legacy" | "modern" | "manual" | "unknown",
    "signals": ["SAP integration mentioned in footer", "job posting requires SAP HR"],
    "pitch_angle": "...(suggested positioning vs their stack)"
  }
"""
import re
import requests
from typing import Dict, List
from loguru import logger

# Known HR software fingerprints: name → list of patterns to look for in HTML/text
_HR_STACK_SIGNATURES = {
    "SAP SuccessFactors": [
        "successfactors", "sap.com/hr", "sap hr", "sap successfactors",
        "sap hcm", "sap hana",
    ],
    "Oracle HCM": [
        "oracle.com/human-capital", "oracle hcm", "oracle fusion hr",
        "peoplesoft",
    ],
    "Workday": ["workday.com", "workday hcm", "workday hr"],
    "Darwinbox": ["darwinbox.com", "darwinbox hr"],
    "Keka HR": ["keka.com", "keka hr"],
    "GreytHR": ["greythr.com", "greythr"],
    "Zoho People": ["zoho.com/people", "zoho people", "zohopayroll"],
    "BambooHR": ["bamboohr.com", "bamboohr"],
    "Kredily": ["kredily.com"],
    "sumHR": ["sumhr.com"],
    "Spine HR": ["spinehr.com", "spine hr"],
    "HROne": ["hrone.cloud", "hrone hr"],
    "RazorpayX Payroll": ["razorpay.com/payroll"],
    "Excel / Manual": [
        "excel sheet", "spreadsheet", "manual hr", "manual payroll",
        "paper-based", "ms excel", "google sheet",
    ],
}

_MATURITY_MAP = {
    "SAP SuccessFactors": "legacy",
    "Oracle HCM": "legacy",
    "Workday": "modern",
    "Darwinbox": "modern",
    "Keka HR": "modern",
    "GreytHR": "modern",
    "Zoho People": "modern",
    "BambooHR": "modern",
    "Excel / Manual": "manual",
}

_PITCH_ANGLES = {
    "legacy": (
        "They use a legacy enterprise HRMS — pitch modern UX, mobile access, "
        "faster implementation, and lower TCO vs SAP/Oracle."
    ),
    "modern": (
        "They already use a modern HRMS — focus on specific gaps HumanMaximizer fills "
        "better: ask about contract renewal date, pricing pain, missing features."
    ),
    "manual": (
        "They manage HR manually in Excel — strongest prospect. "
        "Pitch automation, error reduction, and time savings with concrete numbers."
    ),
    "unknown": (
        "No current HRMS detected — greenfield opportunity. "
        "Lead with the business case: cost of manual HR at their company size."
    ),
}


def _fetch_page_text(url: str, timeout: int = 8) -> str:
    """Fetch page HTML as lowercase text for scanning."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; LeadGenBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=timeout)
        return resp.text.lower()
    except Exception:
        return ""


def detect_tech_stack(website_url: str, company_name: str = "") -> Dict:
    """
    Scan a company website to detect their current HR software stack.
    Also checks /careers and /jobs pages (job postings often list required tools).
    """
    # Collect text from homepage + careers page
    pages_text = _fetch_page_text(website_url)
    for path in ["/careers", "/jobs", "/about"]:
        from urllib.parse import urljoin
        pages_text += _fetch_page_text(urljoin(website_url.rstrip("/"), path), timeout=6)

    if not pages_text:
        return {
            "current_tools": [],
            "maturity": "unknown",
            "signals": [],
            "pitch_angle": _PITCH_ANGLES["unknown"],
        }

    detected: List[str] = []
    signals: List[str] = []

    for tool_name, patterns in _HR_STACK_SIGNATURES.items():
        for pattern in patterns:
            if pattern.lower() in pages_text:
                if tool_name not in detected:
                    detected.append(tool_name)
                    signals.append(f'"{pattern}" found on {website_url}')
                break  # one match per tool is enough

    # Determine maturity
    maturity = "unknown"
    for tool in detected:
        m = _MATURITY_MAP.get(tool)
        if m:
            # Priority: manual > legacy > modern > unknown
            if maturity == "unknown":
                maturity = m
            elif m == "manual":
                maturity = "manual"
            elif m == "legacy" and maturity == "modern":
                maturity = "legacy"

    pitch_angle = _PITCH_ANGLES.get(maturity, _PITCH_ANGLES["unknown"])

    if detected:
        logger.info(f"[TechStack] {company_name}: detected {detected}")
    else:
        logger.debug(f"[TechStack] {company_name}: no HR software detected")

    return {
        "current_tools": detected,
        "maturity": maturity,
        "signals": signals[:5],
        "pitch_angle": pitch_angle,
    }
