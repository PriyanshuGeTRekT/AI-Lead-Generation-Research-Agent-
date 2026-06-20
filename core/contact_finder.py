"""
Contact finder (Serper, free-tier friendly) — get the RIGHT PERSON + a phone.
-----------------------------------------------------------------------------
For a company, find the decision-maker (founder / director / proprietor / MD) and
the best available phone, in ONE Serper call so a free 2,500-credit key covers a
full city. Reads the person from Zauba/LinkedIn-style snippets and a phone from
directory snippets (JustDial/IndiaMART) — the same public signals the old tool used,
but folded into a single query.

HONEST LIMITS: the founder's *direct mobile* is rarely public — free sources reliably
give the person's NAME + ROLE and the company's listed phone, not a personal cell.
True person-level direct dials need paid data (Crustdata/PDL/Apollo). Fail-safe {}.
"""
import re
from typing import Optional

_ROLE_RE = re.compile(r"\b(founder|co-?founder|managing director|director|proprietor|"
                      r"owner|partner|chairman|ceo|cmd|promoter)\b", re.I)
# A person name near a role: "Rajesh Kumar - Director", "Director: Rajesh Kumar",
# "... are Rajesh Kumar and Sunil Gupta" (Zauba phrasing).
_NAME_ROLE = re.compile(
    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*[-–,:]?\s*(?:is\s+the\s+)?"
    r"(?:Founder|Co-?Founder|Managing Director|Director|Proprietor|Owner|Partner|CEO|Chairman)",
)
_ROLE_NAME = re.compile(
    r"(?:Founder|Co-?Founder|Managing Director|Director|Proprietor|Owner|CEO)\s*"
    r"[-–,:]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})")
_MOBILE_RE = re.compile(r"(?:\+?91[\-\s]?|0)?([6-9]\d{9})\b")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Reject generic/role/company tokens masquerading as a person name. Includes the
# web/marketing/page-fragment jargon that older scrapes banked as fake names
# ("Your Digital Marketing", "Public Sector", "Customer Login", "Read More"...).
_NOT_A_NAME = re.compile(
    r"\b(profile|listing|listings|service|services|manager|director|directors|solution|solutions|"
    r"contact|details|detail|development|business|company|companies|pvt|ltd|limited|team|owner|founder|"
    r"enquiry|department|head|executive|officer|consultant|consulting|consultancy|group|industries|private|"
    r"corporation|associates|partners|partner|overview|home|about|career|careers|"
    r"digital|marketing|growth|recruitment|recruiters|recruiter|hiring|security|outsourcing|"
    r"web|website|design|designing|login|customer|support|popular|brands|success|stories|preferred|"
    r"public|sector|transformation|corporate|clients|trusted|premium|verified|manufacturing|industry|"
    r"largest|leadership|message|pharma|salesforce|summit|tally|responsive|engineer|agents|"
    r"submit|quote|vision|profit|proprietorship|registration|annual|information|conscious|reliable|"
    r"strategic|designation|startup|network|networks|systems|technologies|technology|software|"
    r"compliance|compliances|certifications|certification|certificate|certified)\b", re.I)


def valid_person(name: str) -> bool:
    """A real person name = 2-3 capitalized words, no role/generic/company tokens."""
    if not name:
        return False
    w = name.split()
    if not (2 <= len(w) <= 3):
        return False
    if _NOT_A_NAME.search(name):
        return False
    return all(re.match(r"^[A-Z][a-zA-Z.&]+$", x) for x in w)


def find_contact(company: str, city: str = "") -> dict:
    """One Serper query → {name, role, phone, email} (any may be blank). Fail-safe."""
    from core import signals  # reuse the rotating, credit-aware _serper
    if not company:
        return {}
    geo = f" {city}" if city else ""
    d = signals._serper(
        f'"{company}"{geo} (founder OR director OR proprietor OR "managing director" OR owner) '
        f'(contact OR phone OR email OR linkedin OR zaubacorp)')
    hits = (d.get("organic") or [])[:8]
    name = role = phone = email = ""
    for h in hits:
        title = h.get("title", "") or ""
        snippet = h.get("snippet", "") or ""
        text = f"{title} {snippet}"
        link = (h.get("link", "") or "").lower()
        # Person + role
        if not name:
            m = _NAME_ROLE.search(text) or _ROLE_NAME.search(text)
            if m:
                cand = m.group(1).strip()
                # reject the company name itself echoed back + non-person tokens
                if cand.lower() not in company.lower() and valid_person(cand):
                    name = cand
                    rm = _ROLE_RE.search(text)
                    role = rm.group(1).title() if rm else "Decision-maker"
        # LinkedIn title pattern: "Name - Role - Company | LinkedIn"
        if not name and "linkedin" in link and " - " in title:
            parts = [p.strip() for p in title.split(" - ")]
            if len(parts) >= 2 and _ROLE_RE.search(parts[1]) and len(parts[0].split()) <= 3:
                name = parts[0]; role = parts[1]
        # Phone (prefer directory/own-site snippets)
        if not phone:
            pm = _MOBILE_RE.search(text)
            if pm:
                phone = pm.group(1)
        if not email:
            em = _EMAIL_RE.search(text)
            if em and not re.search(r"(justdial|indiamart|sulekha|zaubacorp|linkedin)", em.group(0), re.I):
                email = em.group(0)
    return {"name": name, "role": role, "phone": phone, "email": email}
