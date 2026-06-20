"""
Predictive Lead Scoring + Timing
--------------------------------
Deterministic, explainable scoring so sales focuses on the highest-convert leads
without burning LLM tokens. Four weighted components:

  no_hrms   (0.35) — confidence they have NO HRMS (the whole premise)
  need      (0.30) — workforce pain / hiring signals / manual HR
  fit       (0.20) — firmographic fit (size band × workforce-heavy industry)
  reach     (0.15) — can we actually contact the right person?

It also predicts TIMING — *when* they'll need HRMS — which is the edge over
Apollo/Instantly: reach them just before the pain forces a purchase.

Returns: {predicted_score: 0-10, propensity: 0-1, timing: 'now'|'quarter'|'watch',
          fit: 0-1, need: 0-1, reach: 0-1, reasons: [str]}
"""
import re
from typing import Optional

_WORKFORCE_HEAVY = (
    "manufactur", "logistic", "supply", "retail", "hospitalit", "hotel", "restaurant",
    "healthcare", "hospital", "clinic", "construction", "real estate", "facility",
    "bpo", "call center", "call centre", "staffing", "security", "textile", "fmcg",
    "pharma", "automobile", "auto ", "education", "school", "college", "ecommerce",
    "e-commerce", "warehous", "transport", "agro", "food processing",
)
_HIRING_HINTS = (
    "hiring", "we are hiring", "open position", "vacanc", "join our team",
    "recruit", "career", "now hiring", "walk-in", "walk in",
)


def parse_size(size: Optional[str]) -> Optional[int]:
    if not size:
        return None
    m = re.search(r"(\d[\d,]*)", str(size).replace(",", ""))
    return int(m.group(1)) if m else None


def _size_fit(n: Optional[int]) -> float:
    """HRMS adoption gap is widest in the 30–500 band."""
    if n is None:
        return 0.5
    if n < 15:
        return 0.2
    if n < 30:
        return 0.55
    if n <= 200:
        return 1.0
    if n <= 500:
        return 0.9
    if n <= 1000:
        return 0.65
    if n <= 2000:
        return 0.4
    return 0.2


# GCC / captive-center signals (a later segment — these often already run a
# parent-company HRMS, so they're flagged, not prioritized, unless targeted).
_GCC_HINTS = (
    "global capability cent", "capability centre", "captive", "shared services",
    "global in-house", "gic", "offshore development cent", "delivery cent",
    "global delivery", "gcc",
)


def _industry_fit(industry: Optional[str], description: Optional[str]) -> float:
    # ICP = SMEs across ALL industries (India), so every industry is a decent
    # fit; workforce-heavy ones still score highest.
    blob = f"{industry or ''} {description or ''}".lower()
    return 1.0 if any(k in blob for k in _WORKFORCE_HEAVY) else 0.8


def is_gcc(lead: dict) -> bool:
    blob = f"{lead.get('company_name','')} {lead.get('industry','')} {lead.get('description','')}".lower()
    return any(h in blob for h in _GCC_HINTS)


def score_lead(lead: dict) -> dict:
    reasons: list[str] = []
    n = parse_size(lead.get("size"))

    # ── no_hrms ──────────────────────────────────────────────────────────────
    hrms = lead.get("hrms") or {}
    no_hrms = hrms.get("no_hrms_confidence")
    if no_hrms is None:
        maturity = (lead.get("tech_stack") or {}).get("maturity")
        no_hrms = {"manual": 0.9, "none": 0.7, "unknown": 0.45, "legacy": 0.1, "modern": 0.05}.get(
            maturity, 0.5
        )
    if no_hrms >= 0.7:
        reasons.append("no HRMS detected (greenfield)")
    elif no_hrms <= 0.15:
        reasons.append("already runs an HRMS — weak fit")

    # ── fit ──────────────────────────────────────────────────────────────────
    size_fit = _size_fit(n)
    ind_fit = _industry_fit(lead.get("industry"), lead.get("description"))
    fit = round(0.6 * size_fit + 0.4 * ind_fit, 3)
    if size_fit >= 0.9:
        reasons.append(f"{n} employees — prime HRMS-adoption band")
    if ind_fit >= 1.0:
        reasons.append("workforce-heavy industry")

    # ── need ───────────────────────────────────────────────────────────────────
    blob = " ".join(
        [
            str(lead.get("description") or ""),
            " ".join(lead.get("pain_points") or []),
            " ".join((hrms.get("signals") or [])),
            (lead.get("tech_stack") or {}).get("maturity") or "",
        ]
    ).lower()
    need = 0.4
    if (hrms.get("maturity") or (lead.get("tech_stack") or {}).get("maturity")) == "manual":
        need = max(need, 0.9)
        reasons.append("manual HR processes")
    if any(h in blob for h in _HIRING_HINTS):
        need = max(need, 0.75)
        reasons.append("actively hiring — scaling headcount")
    if lead.get("pain_points"):
        need = max(need, 0.6)

    # ── reach ──────────────────────────────────────────────────────────────────
    has_dm = bool(lead.get("decision_maker_full_name") or lead.get("decision_maker_name"))
    verified = [
        v for v in (lead.get("verified_emails") or [])
        if (v.get("valid") if isinstance(v, dict) else True)
    ]
    emails = lead.get("contact_emails") or []
    reach = 0.2
    if has_dm:
        reach += 0.4
        reasons.append("decision maker identified")
    if verified or emails:
        reach += 0.4
    reach = min(1.0, reach)

    predicted = 10 * (0.35 * no_hrms + 0.30 * need + 0.20 * fit + 0.15 * reach)
    predicted = round(max(0.0, min(10.0, predicted)), 1)

    # ── timing / propensity ────────────────────────────────────────────────────
    hiring = any(h in blob for h in _HIRING_HINTS)
    near_threshold = n is not None and (40 <= n <= 120 or 90 <= n <= 220)
    if no_hrms >= 0.7 and (hiring or near_threshold):
        timing = "now"
    elif no_hrms >= 0.6 and fit >= 0.7:
        timing = "quarter"
    else:
        timing = "watch"

    gcc = is_gcc(lead)
    if gcc:
        reasons.append("GCC / captive center (later segment)")

    return {
        "predicted_score": predicted,
        "propensity": round(predicted / 10, 2),
        "timing": timing,
        "fit": fit,
        "need": round(need, 2),
        "reach": round(reach, 2),
        "no_hrms_confidence": round(float(no_hrms), 2),
        "segment": "gcc" if gcc else "sme",
        "reasons": reasons[:5],
    }


# ── decision-maker targeting by company size ───────────────────────────────────
def target_contact(lead: dict) -> dict:
    """Which role to reach out to, given company size. Drives enrichment + pitch."""
    n = parse_size(lead.get("size"))
    if n is None:
        title, rationale = "HR Head / Founder", "size unknown — start with HR head, fall back to founder"
    elif n < 50:
        title, rationale = "Founder / Director", "<50 staff: HR usually reports to the founder/owner"
    elif n <= 200:
        title, rationale = "HR Manager / HR Head", "50–200 staff: a dedicated HR manager owns tooling decisions"
    elif n <= 500:
        title, rationale = "Head of People / VP HR", "200–500 staff: people-ops leader drives HRMS purchases"
    else:
        title, rationale = "CHRO / VP HR", "500+ staff: CHRO/VP owns the HRMS budget"
    return {"target_title": title, "rationale": rationale}
