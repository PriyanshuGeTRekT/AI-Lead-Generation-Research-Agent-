"""
Tracking: website-visitor ID + live email A/B (open/click)
----------------------------------------------------------
Two mechanisms that "complete" the Apollo/Instantly-style feature set:

1. Website-visitor ID — a 1x1 pixel endpoint records each visit and resolves the
   visitor's IP to a company/org (IPinfo when `ipinfo_token` is set, else reverse
   DNS). Embed the pixel on your marketing site to surface anonymous traffic.

2. Live email A/B — open-pixel + click-redirect endpoints record per-variant
   opens/clicks so the sales A/B winner is driven by REAL engagement (not just the
   pre-send buyer simulation). Activates once outreach is sent through these links.

Storage is a single JSON file (fail-safe, lock-guarded). No external infra needed
to run; richer data arrives with an IPinfo token + emails routed through the links.
"""
import json
import os
import socket
import threading
from pathlib import Path
from typing import Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

# 1x1 transparent GIF
PIXEL = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00"
    b"\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)

_PATH = Path(os.getenv("TRACKING_PATH", "./data/tracking.json"))
_LOCK = threading.Lock()
_AGG_IPS = {"127.0.0.1", "::1", ""}


def _load() -> dict:
    if _PATH.exists():
        try:
            with open(_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {"visitors": [], "email_events": [], "sends": []}


def _save(d: dict) -> None:
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, _PATH)
    except Exception:
        pass


# ── Visitor identification ────────────────────────────────────────────────────
def resolve_ip(ip: str) -> dict:
    """Best-effort IP → company/org. IPinfo if a token is set, else reverse DNS."""
    out = {"ip": ip, "org": "", "domain": "", "city": "", "country": ""}
    if not ip or ip in _AGG_IPS:
        return out
    try:
        from core import runtime_config as rc
        token = rc.get("ipinfo_token")
    except Exception:
        token = None
    if token and requests is not None:
        try:
            d = requests.get(f"https://ipinfo.io/{ip}/json", params={"token": token}, timeout=5).json()
            company = d.get("company") or {}
            out.update(
                org=company.get("name") or d.get("org", ""),
                domain=company.get("domain", ""),
                city=d.get("city", ""),
                country=d.get("country", ""),
            )
        except Exception:
            pass
    if not out["org"]:
        try:
            out["org"] = socket.gethostbyaddr(ip)[0]
        except Exception:
            pass
    return out


def record_visit(ip: str, page: str = "", ref: str = "", ts: Optional[str] = None) -> dict:
    info = resolve_ip(ip)
    rec = {**info, "page": page, "ref": ref, "ts": ts or ""}
    with _LOCK:
        d = _load()
        d["visitors"].append(rec)
        d["visitors"] = d["visitors"][-2000:]
        _save(d)
    return rec


def list_visitors(limit: int = 200) -> list[dict]:
    # Most recent first; collapse obvious noise (no org resolved).
    vs = [v for v in _load().get("visitors", []) if v.get("org")]
    return list(reversed(vs))[:limit]


# ── Email A/B (open / click) ──────────────────────────────────────────────────
def record_send(lead_id: str, variant: str) -> None:
    with _LOCK:
        d = _load()
        d["sends"].append({"lead_id": lead_id, "variant": variant})
        _save(d)


def record_email_event(lead_id: str, variant: str, kind: str) -> None:
    """kind: 'open' | 'click'."""
    with _LOCK:
        d = _load()
        d["email_events"].append({"lead_id": lead_id, "variant": variant, "kind": kind})
        d["email_events"] = d["email_events"][-5000:]
        _save(d)


def ab_stats() -> dict:
    """Per-variant sent / opens / clicks + rates — drives the live A/B winner."""
    d = _load()
    stats: dict = {}

    def _row(v: str) -> dict:
        return stats.setdefault(v, {"variant": v, "sent": 0, "opens": 0, "clicks": 0})

    for s in d.get("sends", []):
        _row(s.get("variant", "?"))["sent"] += 1
    for e in d.get("email_events", []):
        row = _row(e.get("variant", "?"))
        if e.get("kind") == "open":
            row["opens"] += 1
        elif e.get("kind") == "click":
            row["clicks"] += 1
    for row in stats.values():
        base = max(1, row["sent"] or row["opens"])
        row["open_rate"] = round(row["opens"] / base, 3) if row["sent"] else None
        row["click_rate"] = round(row["clicks"] / base, 3) if row["sent"] else None
    rows = list(stats.values())
    winner = max(rows, key=lambda r: (r["clicks"], r["opens"]), default=None)
    return {"variants": rows, "winner": winner["variant"] if winner else None}


# ── Link helpers (embed in outreach emails) ───────────────────────────────────
def pixel_url(base_url: str, lead_id: str, variant: str) -> str:
    return f"{base_url.rstrip('/')}/track/open/{lead_id}/{variant}.gif"


def click_url(base_url: str, lead_id: str, variant: str, target: str) -> str:
    from urllib.parse import quote
    return f"{base_url.rstrip('/')}/track/click/{lead_id}/{variant}?u={quote(target, safe='')}"
