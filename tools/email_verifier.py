"""
Email Verification
-------------------
Validates discovered email addresses before the Sales Agent drafts outreach.
Sending to bad emails destroys domain deliverability (spam score goes up,
future emails land in junk for everyone).

Three-layer check:
  1. Format validation  — is it a valid email string?
  2. MX record check    — does the domain have mail servers? (DNS lookup)
  3. Quality scoring    — is it a generic/role address or a real person?

No SMTP handshake (too slow, many servers block it). MX check is the best
fast signal — if the domain has no MX records, the email will 100% bounce.

Requires: dnspython  (pip install dnspython)
Falls back gracefully if dns is unavailable.
"""
import re
from typing import List, Dict
from loguru import logger

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

# Generic/role addresses — real people don't read these
_GENERIC_PREFIXES = {
    "info", "hello", "contact", "support", "admin", "noreply", "no-reply",
    "sales", "marketing", "team", "enquiry", "enquiries", "query", "queries",
    "help", "feedback", "webmaster", "postmaster", "abuse", "careers",
    "jobs", "recruitment", "general", "office", "mail", "email",
}

# Domains that are clearly not business emails
_PERSONAL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
    "rediffmail.com", "ymail.com", "live.com", "icloud.com",
}


def _check_mx(domain: str) -> bool:
    """Return True if the domain has at least one MX record."""
    try:
        import dns.resolver
        answers = dns.resolver.resolve(domain, "MX", lifetime=2)
        return len(answers) > 0
    except Exception:
        # If dns library missing or lookup fails, assume valid (don't block)
        return True


def _quality_score(email: str) -> str:
    """
    Return quality tier: 'high' | 'medium' | 'low'.
    High  = firstname.lastname pattern → real person
    Medium = role address but reads by humans (hr@, people@)
    Low   = generic catch-all unlikely to reach decision maker
    """
    prefix = email.split("@")[0].lower()
    domain = email.split("@")[-1].lower()

    if domain in _PERSONAL_DOMAINS:
        return "low"  # personal email, not a business contact

    if prefix in _GENERIC_PREFIXES:
        return "low"

    # HR-specific role addresses are medium (someone does read them)
    if prefix in {"hr", "people", "humanresources", "hrd", "hrm", "talent", "recruit"}:
        return "medium"

    # Looks like a real name (has a dot or is a name-length word)
    if "." in prefix or (len(prefix) >= 4 and prefix.isalpha()):
        return "high"

    return "medium"


def verify_emails(emails: List[str]) -> List[Dict]:
    """
    Verify and score a list of email addresses.

    Returns list of dicts:
      {email, valid, mx_ok, quality, reason}
    Sorted by quality (high first).
    """
    results = []
    checked_domains: Dict[str, bool] = {}  # cache MX lookups per domain

    for email in emails:
        email = email.lower().strip()

        # Format check
        if not _EMAIL_RE.match(email):
            results.append({
                "email": email, "valid": False, "mx_ok": False,
                "quality": "low", "reason": "invalid format",
            })
            continue

        domain = email.split("@")[-1]

        # MX check (cached per domain)
        if domain not in checked_domains:
            checked_domains[domain] = _check_mx(domain)
        mx_ok = checked_domains[domain]

        quality = _quality_score(email)
        valid = mx_ok  # consider valid only if MX exists

        results.append({
            "email": email,
            "valid": valid,
            "mx_ok": mx_ok,
            "quality": quality,
            "reason": "ok" if valid else "domain has no MX records",
        })

    # Sort: high quality valid first, then medium, then low, invalids last
    order = {"high": 0, "medium": 1, "low": 2}
    results.sort(key=lambda r: (not r["valid"], order.get(r["quality"], 3)))

    logger.debug(f"Email verification: {len(results)} checked, "
                 f"{sum(1 for r in results if r['valid'])} valid")
    return results


def best_emails(emails: List[str], max_results: int = 3) -> List[str]:
    """
    Return up to max_results verified, quality-ranked email addresses.
    Used by the Sales Agent to pick the best address to target.
    """
    verified = verify_emails(emails)
    return [r["email"] for r in verified if r["valid"]][:max_results]
