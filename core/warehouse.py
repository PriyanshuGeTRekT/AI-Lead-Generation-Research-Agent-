"""
Lead Warehouse (SQLite)
-----------------------
A persistent, growing pool of companies so we DON'T re-crawl the sources on every
search. Two tiers (see the product design):

  • HARVEST (cheap)  → upsert_raw(): raw candidates (domain/name/location/source).
                       No AI, no scraping. The pool grows monotonically.
  • ENRICH (costly)  → save_enriched(): full funnel output (HRMS verdict, verified
                       phone, employee band, score, decision-maker) keyed by domain.

  • SEARCH = query(): an instant SQL filter over already-enriched leads, instead of
                      a live multi-source API crawl.

stdlib only (sqlite3) — zero infra. Every function is fail-safe: a warehouse error
must never break the pipeline or a request.
"""
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from loguru import logger

_PATH = Path(os.getenv("WAREHOUSE_PATH", "./data/warehouse.db"))
_LOCK = threading.Lock()
_conn: Optional[sqlite3.Connection] = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    domain              TEXT PRIMARY KEY,
    company_name        TEXT,
    website             TEXT,
    location            TEXT,
    region              TEXT,
    industry            TEXT,
    source              TEXT,
    status              TEXT DEFAULT 'raw',      -- raw | enriched | qualified | excluded
    no_hrms_confidence  REAL,
    score               REAL,
    phone               TEXT,
    employee_band       TEXT,
    employee_max        INTEGER,
    dm_name             TEXT,
    dm_email            TEXT,
    exclude_reason      TEXT,
    payload             TEXT,                    -- full lead JSON once enriched
    discovered_at       REAL,
    enriched_at         REAL
);
CREATE INDEX IF NOT EXISTS idx_status   ON leads(status);
CREATE INDEX IF NOT EXISTS idx_industry ON leads(industry);
CREATE INDEX IF NOT EXISTS idx_score    ON leads(score);
CREATE INDEX IF NOT EXISTS idx_region   ON leads(region);
"""

# New columns + their indexes are added via ALTER TABLE so they apply to the
# already-populated DB too. Each runs in its own try/except (idempotent) — they must
# NOT live in _SCHEMA, because CREATE INDEX on a not-yet-added column would abort the
# whole executescript. ALTER first, then index.
_MIGRATIONS = [
    "ALTER TABLE leads ADD COLUMN icp_tier TEXT",
    "ALTER TABLE leads ADD COLUMN state TEXT",
    "ALTER TABLE leads ADD COLUMN crm_stage TEXT DEFAULT 'new'",
    "ALTER TABLE leads ADD COLUMN contact_method TEXT",
    "ALTER TABLE leads ADD COLUMN contact_note TEXT",
    "ALTER TABLE leads ADD COLUMN contacted_at REAL",
    "ALTER TABLE leads ADD COLUMN crm_updated_at REAL",
    "CREATE INDEX IF NOT EXISTS idx_tier ON leads(icp_tier)",
    "CREATE INDEX IF NOT EXISTS idx_state ON leads(state)",
    "CREATE INDEX IF NOT EXISTS idx_crmstage ON leads(crm_stage)",
    "ALTER TABLE leads ADD COLUMN signal_score REAL",
    "CREATE INDEX IF NOT EXISTS idx_signal ON leads(signal_score)",
    "ALTER TABLE leads ADD COLUMN contact_enriched_at REAL",
    "CREATE INDEX IF NOT EXISTS idx_contactenriched ON leads(contact_enriched_at)",
]


def _db() -> Optional[sqlite3.Connection]:
    global _conn
    if _conn is not None:
        return _conn
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(_PATH), check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(_SCHEMA)
        for stmt in _MIGRATIONS:
            try:
                c.execute(stmt)
            except Exception:
                pass  # column/index already exists
        c.commit()
        _conn = c
        return c
    except Exception as e:
        logger.warning(f"[warehouse] init failed: {e}")
        return None


def _domain_of(url_or_dom: str) -> str:
    s = (url_or_dom or "").strip().lower()
    if not s:
        return ""
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/")[0]
    return s[4:] if s.startswith("www.") else s


# ── Tier 1: cheap raw harvest ─────────────────────────────────────────────────
def upsert_raw(candidates: list[dict], region: Optional[str] = None,
               industry: Optional[str] = None) -> int:
    """Insert raw candidates (skip ones already present in ANY status). Cheap.
    `industry` labels the whole batch (e.g. the matrix knows it per query) so the
    pool stays searchable; a candidate's own industry field wins if present."""
    db = _db()
    if not db:
        return 0
    added = 0
    now = time.time()
    with _LOCK:
        for c in candidates or []:
            dom = _domain_of(c.get("url") or c.get("website") or c.get("domain") or "")
            if not dom:
                continue
            try:
                cur = db.execute(
                    """INSERT OR IGNORE INTO leads
                       (domain, company_name, website, location, region, industry, source, status, discovered_at)
                       VALUES (?,?,?,?,?,?,?, 'raw', ?)""",
                    (
                        dom,
                        (c.get("title") or c.get("company_name") or "")[:200],
                        c.get("url") or c.get("website") or "",
                        c.get("location") or "",
                        region or "",
                        c.get("industry") or industry or "",
                        c.get("source") or "harvest",
                        now,
                    ),
                )
                added += cur.rowcount or 0
            except Exception:
                continue
        db.commit()
    return added


# ── Tier 2: enriched / qualified results ──────────────────────────────────────
def save_enriched(lead: dict, region: Optional[str] = None) -> None:
    """Upsert a fully-enriched lead (overwrites the raw shell). Fail-safe."""
    db = _db()
    if not db:
        return
    dom = _domain_of(lead.get("website") or lead.get("domain") or "")
    if not dom:
        return
    sc = (lead.get("lead_score") or {}).get("predicted_score")
    hrms = lead.get("hrms") or {}
    status = lead.get("status") or "enriched"
    if status in ("researched",):
        status = "enriched"
    # Never persist an invalid phone — a blank beats a wrong number. Validate here
    # so the pool stays clean no matter what the upstream resolver produced.
    phone = lead.get("phone") or ""
    if phone:
        try:
            from tools.contact_resolver import _normalize_phone
            if not _normalize_phone(phone, trusted=False):
                phone = ""
                for k in ("phone", "phone_type", "phone_source"):
                    lead.pop(k, None)
        except Exception:
            pass
    try:
        with _LOCK:
            db.execute(
                """INSERT INTO leads
                   (domain, company_name, website, location, region, industry, source, status,
                    no_hrms_confidence, score, phone, employee_band, employee_max, dm_name, dm_email,
                    payload, discovered_at, enriched_at, icp_tier, state, contact_enriched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(domain) DO UPDATE SET
                     company_name=excluded.company_name, website=excluded.website,
                     location=excluded.location, region=excluded.region, industry=excluded.industry,
                     status=excluded.status, no_hrms_confidence=excluded.no_hrms_confidence,
                     score=excluded.score, phone=excluded.phone, employee_band=excluded.employee_band,
                     employee_max=excluded.employee_max, dm_name=excluded.dm_name, dm_email=excluded.dm_email,
                     payload=excluded.payload, enriched_at=excluded.enriched_at,
                     icp_tier=excluded.icp_tier, state=excluded.state,
                     contact_enriched_at=COALESCE(excluded.contact_enriched_at, leads.contact_enriched_at)""",
                (
                    dom,
                    lead.get("company_name", "")[:200],
                    lead.get("website", ""),
                    lead.get("location", ""),
                    region or "",
                    lead.get("industry", ""),
                    "pipeline",
                    status,
                    hrms.get("no_hrms_confidence"),
                    sc,
                    phone,
                    lead.get("employee_band", ""),
                    lead.get("employee_max"),
                    lead.get("decision_maker_full_name") or lead.get("decision_maker_name") or lead.get("dm_name") or "",
                    (lead.get("contact_emails") or [lead.get("dm_email") or ""])[0],
                    json.dumps(lead),
                    time.time(),
                    time.time(),
                    lead.get("icp_tier", ""),
                    lead.get("state", ""),
                    lead.get("contact_enriched_at"),
                ),
            )
            db.commit()
    except Exception as e:
        logger.debug(f"[warehouse] save_enriched failed: {e}")


def save_enriched_bulk(leads: list, region: Optional[str] = None) -> int:
    """Insert many enriched leads in ONE transaction (for lakhs-scale ingests like
    the MCA registry). Far faster than per-row save_enriched. Fail-safe."""
    db = _db()
    if not db or not leads:
        return 0
    rows = []
    now = time.time()
    for lead in leads:
        dom = _domain_of(lead.get("website") or lead.get("domain") or "")
        if not dom:
            continue
        sc = (lead.get("lead_score") or {}).get("predicted_score")
        hrms = lead.get("hrms") or {}
        status = lead.get("status") or "enriched"
        rows.append((
            dom, (lead.get("company_name", "") or "")[:200], lead.get("website", ""),
            lead.get("location", ""), region or lead.get("state") or "",
            lead.get("industry", ""), lead.get("source", "registry"), status,
            hrms.get("no_hrms_confidence"), sc, lead.get("phone", "") or "",
            lead.get("employee_band", ""), lead.get("employee_max"),
            lead.get("decision_maker_full_name") or lead.get("dm_name") or "",
            (lead.get("contact_emails") or [lead.get("dm_email", "")])[0] or "",
            json.dumps(lead), now, now,
        ))
    if not rows:
        return 0
    try:
        with _LOCK:
            db.executemany(
                """INSERT INTO leads
                   (domain, company_name, website, location, region, industry, source, status,
                    no_hrms_confidence, score, phone, employee_band, employee_max, dm_name, dm_email,
                    payload, discovered_at, enriched_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(domain) DO UPDATE SET
                     company_name=excluded.company_name, location=excluded.location,
                     region=excluded.region, industry=excluded.industry, status=excluded.status,
                     score=excluded.score, dm_email=excluded.dm_email, payload=excluded.payload,
                     enriched_at=excluded.enriched_at""",
                rows,
            )
            db.commit()
        return len(rows)
    except Exception as e:
        logger.debug(f"[warehouse] save_enriched_bulk failed: {e}")
        return 0


def mark_excluded(url_or_dom: str, reason: str = "") -> None:
    db = _db()
    if not db:
        return
    dom = _domain_of(url_or_dom)
    if not dom:
        return
    try:
        with _LOCK:
            db.execute(
                """INSERT INTO leads (domain, status, exclude_reason, discovered_at)
                   VALUES (?, 'excluded', ?, ?)
                   ON CONFLICT(domain) DO UPDATE SET status='excluded', exclude_reason=excluded.exclude_reason""",
                (dom, reason[:200], time.time()),
            )
            db.commit()
    except Exception:
        pass


# ── Instant search / filter ───────────────────────────────────────────────────
def query(
    industry: Optional[str] = None,
    region: Optional[str] = None,
    min_score: float = 0.0,
    statuses: tuple = ("enriched", "qualified", "pending_review", "outreach_ready"),
    limit: int = 50,
) -> list[dict]:
    """Instant filtered retrieval of enriched leads (returns full payloads)."""
    db = _db()
    if not db:
        return []
    where = ["payload IS NOT NULL"]
    params: list = []
    if statuses:
        where.append("status IN (%s)" % ",".join("?" * len(statuses)))
        params += list(statuses)
    if min_score:
        where.append("score >= ?")
        params.append(min_score)
    if industry:
        where.append("LOWER(industry) LIKE ?")
        params.append(f"%{industry.lower()}%")
    if region:
        where.append("(LOWER(region) LIKE ? OR LOWER(location) LIKE ?)")
        params += [f"%{region.lower()}%", f"%{region.lower()}%"]
    sql = f"SELECT payload FROM leads WHERE {' AND '.join(where)} ORDER BY score DESC NULLS LAST LIMIT ?"
    params.append(limit)
    try:
        with _LOCK:
            rows = db.execute(sql, params).fetchall()
        out = []
        for r in rows:
            try:
                out.append(json.loads(r["payload"]))
            except Exception:
                continue
        return out
    except Exception as e:
        logger.debug(f"[warehouse] query failed: {e}")
        return []


def take_raw(limit: int = 30, industry: Optional[str] = None, region: Optional[str] = None) -> list[dict]:
    """Raw candidates awaiting enrichment (for lazy-enrich the shortfall)."""
    db = _db()
    if not db:
        return []
    where = ["status='raw'"]
    params: list = []
    if industry:
        where.append("(industry='' OR LOWER(industry) LIKE ?)")
        params.append(f"%{industry.lower()}%")
    sql = f"SELECT domain, company_name, website, location, region, industry, source FROM leads WHERE {' AND '.join(where)} ORDER BY discovered_at DESC LIMIT ?"
    params.append(limit)
    try:
        with _LOCK:
            rows = db.execute(sql, params).fetchall()
        return [{"url": r["website"] or f"https://{r['domain']}", "title": r["company_name"],
                 # Fall back to the harvest region (matrix stores the city there) so
                 # the India/geo gates have a location to work with.
                 "location": r["location"] or r["region"] or "India", "industry": r["industry"] or "",
                 "source": r["source"]} for r in rows]
    except Exception:
        return []


def reset() -> dict:
    """Wipe the pool (use when rebuilding from scratch). Fail-safe."""
    db = _db()
    if not db:
        return {"cleared": 0}
    try:
        with _LOCK:
            n = db.execute("SELECT COUNT(*) c FROM leads").fetchone()["c"]
            db.execute("DELETE FROM leads")
            db.commit()
        logger.info(f"[warehouse] reset: cleared {n} rows")
        return {"cleared": n}
    except Exception as e:
        return {"cleared": 0, "error": str(e)}


def revalidate_phones() -> dict:
    """Re-check every stored phone against the current (stricter) validator and
    NULL out any that no longer pass — a wrong phone is worse than no phone. Run
    after tightening phone rules to scrub legacy junk. Fail-safe."""
    db = _db()
    if not db:
        return {"checked": 0, "cleaned": 0}
    try:
        from tools.contact_resolver import _normalize_phone
    except Exception:
        return {"checked": 0, "cleaned": 0}
    checked = cleaned = 0
    with _LOCK:
        rows = db.execute("SELECT domain, phone, payload FROM leads WHERE phone IS NOT NULL AND phone != ''").fetchall()
        for r in rows:
            checked += 1
            # Trust nothing already stored — re-validate as an untrusted scrape.
            if _normalize_phone(r["phone"], trusted=False):
                continue
            cleaned += 1
            payload = r["payload"]
            try:
                p = json.loads(payload) if payload else None
                if isinstance(p, dict):
                    for k in ("phone", "phone_type", "phone_source"):
                        p.pop(k, None)
                    payload = json.dumps(p)
            except Exception:
                pass
            db.execute("UPDATE leads SET phone=NULL, payload=? WHERE domain=?", (payload, r["domain"]))
        db.commit()
    logger.info(f"[warehouse] revalidate_phones: cleaned {cleaned}/{checked}")
    return {"checked": checked, "cleaned": cleaned}


def refine_icp() -> dict:
    """Re-score the whole pool for HRMS buy-likelihood and DISQUALIFY the unsellable.

    Hard gates / signals used:
      • company_status must be 'Active' (struck-off / dormant / amalgamated = dead → disqualified)
      • industry HR-intensity (manufacturing/hospital/hotel/logistics… score high)
      • reachable (has an email or phone)
      • CIN-derived: incorporation age (established 3-30y best) + Pvt/Public Ltd (real co.)

    Sets per lead: qualification_score, icp_tier (Hot/Warm/Cold), status
      ('outreach_ready' = prime prospect, 'qualified' = good, 'pending_review' = weak,
       'disqualified' = dead/irrelevant). CPU-only → fast over the full pool.
    """
    db = _db()
    if not db:
        return {"refined": 0}
    try:
        from core.lead_processor import _industry_fit, classify_industry
    except Exception:
        def _industry_fit(x):  # type: ignore
            return 0.5
        def classify_industry(name, fallback=""):  # type: ignore
            return (fallback or "business"), False
    import re as _re

    def _parse_cin(cin: str):
        # U/L + 5 NIC + 2 state + 4 YEAR + 3 TYPE + 6 num
        m = _re.match(r"^([UL])\d{5}[A-Z]{2}(\d{4})([A-Z]{3})", cin or "")
        if not m:
            return None, None, False
        listed = m.group(1) == "L"
        year = int(m.group(2))
        ctype = m.group(3)  # PTC=Private, PLC=Public, OPC=OnePerson, FTC/GOI/etc
        return year, ctype, listed

    refined = hot = qualified = disq = 0
    # Page through by rowid in small snapshots, releasing the lock between pages so
    # the app (stats / search) stays responsive during the multi-minute re-score.
    last_rowid = 0
    PAGE = 8000
    while True:
        with _LOCK:
            rows = db.execute(
                "SELECT rowid, domain, payload FROM leads WHERE rowid > ? AND payload IS NOT NULL "
                "ORDER BY rowid LIMIT ?", (last_rowid, PAGE)).fetchall()
        if not rows:
            break
        last_rowid = rows[-1]["rowid"]
        updates = []
        for r in rows:
            try:
                p = json.loads(r["payload"])
            except Exception:
                continue
            src = p.get("source", "")
            status_raw = (p.get("company_status") or "").strip().lower()
            # Re-classify industry from the NAME (reliable) — the CIN's NIC code uses
            # inconsistent old schemes and mislabels (e.g. a hotel coded as manufacturing).
            industry, name_confident = classify_industry(p.get("company_name", ""), p.get("industry", ""))
            p["industry"] = industry
            p["industry_confident"] = name_confident
            fit = _industry_fit(industry)
            has_email = bool(p.get("dm_email") or p.get("contact_emails"))
            has_phone = bool(p.get("mobile") or p.get("phone"))
            reachable = has_email or has_phone
            year, ctype, listed = _parse_cin(p.get("cin", "") or r["domain"].split(".")[0])

            # Hard gate: MCA companies must be Active. (Web-sourced leads have no
            # MCA status — treat as active since they have a live website.)
            is_mca = src == "MCA registry"
            active = (status_raw == "active") if is_mca else True
            if is_mca and not active:
                tier, score, st = "Cold", 1.0, "disqualified"
                disq += 1
            else:
                age = (2026 - year) if year else 8
                established = 3 <= age <= 35
                age_f = 1.0 if established else 0.3
                real_co = ctype in ("PTC", "PLC")   # Private / Public Ltd
                opc = ctype == "OPC"                 # one-person co — too small for HRMS
                type_f = 0.6 if real_co else (-0.8 if opc else 0.0)
                listed_f = 0.5 if listed else 0.0
                score = round(min(fit * 4.5 + (2.0 if reachable else 0) + age_f + type_f + listed_f, 10.0), 1)
                # PRIME (Hot) = extremely likely to buy, and we're SURE: the NAME
                # confirms a CORE HR-heavy sector (fit≥0.95: factories/steel, hospitals,
                # hotels, logistics, BPO, textile, auto, pharma…) + reachable + active +
                # an established Pvt/Public Ltd. A generic name can't be Hot — no guessing.
                if (fit >= 0.95 and name_confident and reachable and active
                        and established and real_co and not opc):
                    tier, st = "Hot", "outreach_ready"
                    hot += 1
                elif fit >= 0.6 and reachable and not opc:
                    tier, st = "Warm", "qualified"
                    qualified += 1
                elif reachable and not opc:
                    tier, st = "Cold", "pending_review"
                else:
                    tier, st = "Cold", "pending_review"
            p["icp_tier"] = tier
            p["qualification_score"] = score
            p["lead_score"] = {"predicted_score": score, "icp_tier": tier,
                               "rationale": p.get("lead_score", {}).get("rationale", "")}
            p["status"] = st
            sc_val = (p.get("lead_score") or {}).get("predicted_score")
            updates.append((st, sc_val, tier, p.get("state", ""), json.dumps(p), r["domain"]))
            refined += 1
        # Write this page under a brief lock, then release so reads can interleave.
        if updates:
            with _LOCK:
                db.executemany(
                    "UPDATE leads SET status=?, score=?, icp_tier=?, state=?, payload=? WHERE domain=?",
                    updates)
                db.commit()
    logger.info(f"[warehouse] refine_icp: {refined} refined, {hot} hot, {qualified} qualified, {disq} disqualified")
    return {"refined": refined, "hot": hot, "qualified": qualified, "disqualified": disq}


def stats() -> dict:
    db = _db()
    empty = {"total": 0, "raw": 0, "enriched": 0, "qualified": 0, "excluded": 0,
             "outreach_ready": 0, "pending_review": 0, "with_email": 0, "with_phone": 0,
             "leads": 0}
    if not db:
        return empty
    try:
        with _LOCK:
            rows = db.execute("SELECT status, COUNT(*) n FROM leads GROUP BY status").fetchall()
            with_email = db.execute("SELECT COUNT(*) n FROM leads WHERE dm_email != '' AND dm_email IS NOT NULL").fetchone()["n"]
            with_phone = db.execute("SELECT COUNT(*) n FROM leads WHERE phone != '' AND phone IS NOT NULL").fetchone()["n"]
        by = {r["status"]: r["n"] for r in rows}
        total = sum(by.values())
        # "leads" = everything that's a usable lead (not raw shells, not dead/excluded).
        usable = total - by.get("raw", 0) - by.get("excluded", 0)
        return {
            "total": total,
            "leads": usable,
            "raw": by.get("raw", 0),
            "enriched": by.get("enriched", 0),
            "qualified": by.get("qualified", 0),
            "outreach_ready": by.get("outreach_ready", 0),
            "pending_review": by.get("pending_review", 0),
            "excluded": by.get("excluded", 0),
            "with_email": with_email,
            "with_phone": with_phone,
        }
    except Exception:
        return empty


# ── CRM (sales pipeline) ──────────────────────────────────────────────────────
# A lead is CRM-eligible once it's a real prospect (not a raw shell / dead company).
_CRM_ELIGIBLE = "status NOT IN ('raw','excluded','disqualified')"
_CRM_STAGES = ("new", "contacted", "in_loop", "won", "rejected")
# Columns the UI may sort by (whitelist — prevents SQL injection via sort param).
_SORTABLE = {"company_name": "company_name", "industry": "industry", "state": "state",
             "icp_tier": "icp_tier", "score": "score", "crm_stage": "crm_stage",
             "dm_email": "dm_email", "phone": "phone", "contacted_at": "contacted_at",
             "signal_score": "signal_score"}


def backfill_crm_columns() -> dict:
    """One-time: populate icp_tier/state columns from payload + default crm_stage,
    for rows ingested before these columns existed. Paged, lock released per page."""
    db = _db()
    if not db:
        return {"updated": 0}
    updated, last = 0, 0
    while True:
        with _LOCK:
            rows = db.execute(
                "SELECT rowid, domain, payload FROM leads WHERE rowid > ? AND icp_tier IS NULL "
                "ORDER BY rowid LIMIT 8000", (last,)).fetchall()
        if not rows:
            break
        last = rows[-1]["rowid"]
        ups = []
        for r in rows:
            try:
                p = json.loads(r["payload"]) if r["payload"] else {}
            except Exception:
                p = {}
            ups.append((p.get("icp_tier", ""), p.get("state", ""), r["domain"]))
        with _LOCK:
            db.executemany("UPDATE leads SET icp_tier=?, state=? WHERE domain=?", ups)
            db.execute("UPDATE leads SET crm_stage='new' WHERE crm_stage IS NULL")
            db.commit()
        updated += len(ups)
    logger.info(f"[warehouse] backfill_crm_columns: {updated} rows")
    return {"updated": updated}


def tag_delhi_ncr() -> dict:
    """Surface the Delhi MARKET as one segment. A Delhi sales team works the whole
    NCR — Gurgaon/Gurugram, Noida/Greater Noida, Faridabad, Ghaziabad — but those
    companies are tagged by their REGISTERED state (Haryana/UP), so a state='Delhi'
    filter hides them. This relabels their `state` to 'Delhi NCR' (registered state
    stays in payload), turning a handful of Delhi-proper leads into the real ~30k
    Delhi-market pipeline. Non-destructive to payload; re-runnable; refreshes cache."""
    db = _db()
    if not db:
        return {"tagged": 0}
    ncr_like = ["%Gurgaon%", "%Gurugram%", "%Noida%", "%Faridabad%", "%Ghaziabad%"]
    like_clause = " OR ".join(["payload LIKE ?"] * len(ncr_like))
    with _LOCK:
        cur = db.execute(
            f"UPDATE leads SET state='Delhi NCR' "
            f"WHERE {_CRM_ELIGIBLE} AND state != 'Delhi NCR' "
            f"AND ( state IN ('Delhi','NCT of Delhi','Nct Of Delhi','NCT OF DELHI') OR {like_clause} )",
            tuple(ncr_like))
        n = cur.rowcount
        db.commit()
    logger.info(f"[warehouse] tag_delhi_ncr: {n} leads → 'Delhi NCR'")
    try:
        warm_crm_cache()  # recompute counts/options/dashboard so the segment shows
    except Exception:
        pass
    return {"tagged": n}


_sig_state = {"running": False, "done": 0, "total": 0, "scored": 0, "live": False}
_ce_state = {"running": False, "done": 0, "total": 0, "got_person": 0, "got_phone": 0}


def signal_scan_status() -> dict:
    return dict(_sig_state)


def contact_enrich_status() -> dict:
    return dict(_ce_state)


_rs_state = {"running": False, "done": 0, "total": 0, "excluded_enterprise": 0,
             "excluded_oversized": 0, "excluded_micro": 0, "bad_phone": 0, "kept": 0}


def right_size_status() -> dict:
    return dict(_rs_state)


def right_size_segment(state: Optional[str] = None, industries: Optional[str] = None,
                       min_emp: int = 10, max_emp: int = 800, do_headcount: bool = True) -> dict:
    """Tighten a segment to the HRMS sweet spot + verify: (1) exclude enterprise/MNC/
    outlet names, (2) scrub invalid phones, (3) Serper headcount → drop >max_emp
    (already has HRMS) and <min_emp (too small). Concurrent. Marks status='excluded'
    so dropped leads leave CRM. Fail-safe."""
    import time as _t
    from concurrent.futures import ThreadPoolExecutor
    from core import sizing
    try:
        from tools.contact_resolver import _normalize_phone
    except Exception:
        _normalize_phone = None
    db = _db()
    if not db:
        return {"kept": 0}
    where = [_CRM_ELIGIBLE, "phone IS NOT NULL", "phone != ''"]
    params: list = []
    if state:
        where.append("state=?"); params.append(state)
    if industries:
        inds = [x.strip() for x in industries.split(",") if x.strip()]
        if inds:
            where.append("industry IN (%s)" % ",".join("?" * len(inds))); params += inds
    wsql = " AND ".join(where)
    with _LOCK:
        rows = db.execute(f"SELECT domain, company_name, phone, payload FROM leads WHERE {wsql}",
                          params).fetchall()
    _rs_state.update(running=True, done=0, total=len(rows), excluded_enterprise=0,
                     excluded_oversized=0, excluded_micro=0, bad_phone=0, kept=0)

    def _assess(r):
        name = r["company_name"] or ""
        try:
            p = json.loads(r["payload"]) if r["payload"] else {}
        except Exception:
            p = {}
        # 1) enterprise / outlet name
        if sizing.is_enterprise(name):
            return (r["domain"], "excluded", "enterprise", None, p)
        # 2) phone validity
        phone = r["phone"]
        if _normalize_phone and not _normalize_phone(phone, trusted=False):
            return (r["domain"], "excluded", "bad_phone", None, p)
        # 3) headcount gate (Serper) — only if enabled + still have credits
        emp = None
        if do_headcount:
            city = (p.get("location") or "").split(",")[0].strip()
            try:
                emp = sizing.employee_count(name, city)
            except Exception:
                emp = None
        band = sizing.size_band(emp)
        if emp is not None:
            p["employee_max"] = emp; p["size_band"] = band
        p["size_verified"] = True
        if band == "enterprise":
            return (r["domain"], "excluded", "oversized", emp, p)
        if band == "micro":
            return (r["domain"], "excluded", "micro", emp, p)
        return (r["domain"], "keep", band, emp, p)

    try:
        with ThreadPoolExecutor(max_workers=8) as ex:
            out = list(ex.map(_assess, rows))
        upd = []
        for dom, action, reason, emp, p in out:
            if action == "excluded":
                if reason == "enterprise": _rs_state["excluded_enterprise"] += 1
                elif reason == "oversized": _rs_state["excluded_oversized"] += 1
                elif reason == "micro": _rs_state["excluded_micro"] += 1
                elif reason == "bad_phone": _rs_state["bad_phone"] += 1
                upd.append(("excluded", json.dumps(p), dom))
            else:
                _rs_state["kept"] += 1
                upd.append((None, json.dumps(p), dom))  # keep status, update payload
            _rs_state["done"] += 1
        with _LOCK:
            for status_v, pl, dom in upd:
                if status_v:
                    db.execute("UPDATE leads SET status=?, payload=? WHERE domain=?", (status_v, pl, dom))
                else:
                    db.execute("UPDATE leads SET payload=? WHERE domain=?", (pl, dom))
            db.commit()
        try:
            warm_crm_cache()
        except Exception:
            pass
        res = {k: _rs_state[k] for k in ("excluded_enterprise", "excluded_oversized", "excluded_micro", "bad_phone", "kept")}
        logger.info(f"[right_size] {res}")
        return res
    except Exception as e:
        logger.warning(f"[right_size] failed: {e}")
        return {"error": str(e), **{k: _rs_state[k] for k in ("excluded_enterprise", "kept")}}
    finally:
        _rs_state["running"] = False


_crawl_state = {"running": False, "done": 0, "total": 0, "got_phone": 0, "got_person": 0}


def crawl_enrich_status() -> dict:
    return dict(_crawl_state)


def crawl_enrich_contacts(state: Optional[str] = None, limit: int = 1000,
                          only_missing_phone: bool = True) -> dict:
    """Crawl the OWN websites of leads (crawl4ai) to extract a published phone +
    decision-maker name/role/email, then update the lead + stamp contact_enriched_at.
    Targets only leads with a real (non-synthetic) website. Fail-safe."""
    import time as _t
    from tools import crawl4ai_contacts
    db = _db()
    if not db:
        return {"enriched": 0}
    if not crawl4ai_contacts.available():
        return {"status": "error", "message": "crawl4ai not installed (pip install crawl4ai && crawl4ai-setup)."}
    where = [_CRM_ELIGIBLE,
             "website LIKE 'http%'", "website NOT LIKE '%.lead'"]
    params: list = []
    if state:
        where.append("state=?"); params.append(state)
    if only_missing_phone:
        where.append("(phone IS NULL OR phone='')")
    wsql = " AND ".join(where)
    with _LOCK:
        rows = db.execute(
            f"SELECT domain, website, payload FROM leads WHERE {wsql} "
            f"ORDER BY signal_score DESC LIMIT ?", params + [limit]).fetchall()
    if not rows:
        return {"enriched": 0, "message": "no crawlable website-leads matched"}
    _crawl_state.update(running=True, done=0, total=len(rows), got_phone=0, got_person=0)
    try:
        from tools.contact_resolver import _normalize_phone
    except Exception:
        _normalize_phone = None
    try:
        url_to_dom = {r["website"]: r["domain"] for r in rows}
        payloads = {r["domain"]: r["payload"] for r in rows}
        # Crawl in batches so progress + writes are incremental.
        urls = list(url_to_dom.keys())
        BATCH = 60
        for i in range(0, len(urls), BATCH):
            chunk = urls[i:i + BATCH]
            results = crawl4ai_contacts.crawl_contacts(chunk, concurrency=6)
            ups = []
            for url, found in (results or {}).items():
                dom = url_to_dom.get(url)
                if not dom:
                    continue
                try:
                    p = json.loads(payloads.get(dom) or "{}")
                except Exception:
                    p = {}
                phone = ""
                if found.get("phone"):
                    if _normalize_phone:
                        n = _normalize_phone(found["phone"], trusted=False)
                        phone = n["number"] if n else ""
                    else:
                        phone = found["phone"]
                if found.get("name"):
                    p["dm_name"] = found["name"]; p["dm_role"] = found.get("role") or "Decision-maker"
                    _crawl_state["got_person"] += 1
                if phone:
                    p["phone"] = phone; _crawl_state["got_phone"] += 1
                if found.get("email") and "@" in found["email"]:
                    p["dm_email"] = found["email"]
                    ce = set(p.get("contact_emails") or []); ce.add(found["email"]); p["contact_emails"] = list(ce)
                p["contact_enriched_at"] = _t.time()
                ups.append((p.get("dm_name") or "", p.get("dm_email") or "", phone or (p.get("phone") or ""),
                            json.dumps(p), _t.time(), dom))
            if ups:
                with _LOCK:
                    db.executemany(
                        "UPDATE leads SET dm_name=?, dm_email=?, phone=?, payload=?, contact_enriched_at=? "
                        "WHERE domain=?", ups)
                    db.commit()
            _crawl_state["done"] = min(i + BATCH, len(urls))
        logger.info(f"[crawl4ai] enriched {len(rows)}: +{_crawl_state['got_phone']} phones, +{_crawl_state['got_person']} people")
        try:
            warm_crm_cache()
        except Exception:
            pass
        return {"enriched": len(rows), "got_phone": _crawl_state["got_phone"], "got_person": _crawl_state["got_person"]}
    except Exception as e:
        logger.warning(f"[crawl4ai] enrich failed: {e}")
        return {"enriched": _crawl_state["done"], "error": str(e)}
    finally:
        _crawl_state["running"] = False


def enrich_contacts(state: Optional[str] = None, limit: int = 3000,
                    only_missing_phone: bool = True, min_signal: float = 0.0) -> dict:
    """Find the decision-maker (founder/director/owner) + a phone for leads via Serper
    (1 call/lead), write dm_name/dm_role/phone/dm_email into the lead, and stamp
    contact_enriched_at so the 'just enriched' filter can show them. PRIME-first.
    Concurrent. Fail-safe per lead."""
    import time as _t
    from concurrent.futures import ThreadPoolExecutor
    from core import contact_finder
    from tools.sources import apollo
    use_apollo = apollo.configured()   # Apollo = named decision-maker + DIRECT DIAL
    db = _db()
    if not db:
        return {"enriched": 0}
    where = [_CRM_ELIGIBLE]
    params: list = []
    if state:
        where.append("state=?"); params.append(state)
    if min_signal:
        where.append("signal_score >= ?"); params.append(float(min_signal))
    if only_missing_phone:
        where.append("(phone IS NULL OR phone = '')")
    wsql = " AND ".join(where)
    _ce_state.update(running=True, done=0, got_person=0, got_phone=0)

    def _one(r):
        try:
            p = json.loads(r["payload"]) if r["payload"] else {}
        except Exception:
            p = {}
        city = (p.get("location") or "").split(",")[0].strip()
        company = p.get("company_name") or ""
        if use_apollo:
            dom = ""
            w = p.get("website") or ""
            m = re.match(r"https?://([^/]+)", w)
            if m and ".lead" not in m.group(1):
                dom = m.group(1)
            ppl = apollo.find_people(company, domain=dom)
            best = ppl[0] if ppl else {}
            res = {"name": best.get("name", ""), "role": best.get("title", ""),
                   "phone": best.get("phone", ""), "email": best.get("email", "")}
        else:
            res = contact_finder.find_contact(company, city)
        phone = ""
        if res.get("phone"):
            try:
                from tools.contact_resolver import _normalize_phone
                n = _normalize_phone(res["phone"], trusted=False)
                phone = n["number"] if n else ""
            except Exception:
                phone = res["phone"]
        if res.get("name"):
            p["dm_name"] = res["name"]; p["dm_role"] = res.get("role") or "Decision-maker"
        if phone:
            p["phone"] = phone
        if res.get("email") and "@" in res["email"]:
            p["dm_email"] = res["email"]
            ce = set(p.get("contact_emails") or []); ce.add(res["email"]); p["contact_emails"] = list(ce)
        p["contact_enriched_at"] = _t.time()
        return (r["domain"], p.get("dm_name") or "", p.get("dm_email") or "",
                phone or (p.get("phone") or ""), json.dumps(p), _t.time(), bool(res.get("name")), bool(phone))

    try:
        with _LOCK:
            total = db.execute(f"SELECT COUNT(*) c FROM leads WHERE {wsql}", params).fetchone()["c"]
        _ce_state["total"] = min(total, limit)
        done, offset = 0, 0
        while done < limit:
            page_n = min(300, limit - done)
            with _LOCK:
                rows = db.execute(
                    f"SELECT rowid, domain, payload FROM leads WHERE {wsql} "
                    f"ORDER BY signal_score DESC LIMIT ? OFFSET ?", params + [page_n, offset]).fetchall()
            if not rows:
                break
            offset += len(rows)
            with ThreadPoolExecutor(max_workers=8) as ex:
                out = list(ex.map(_one, rows))
            ups = [(o[1], o[2], o[3], o[4], o[5], o[0]) for o in out]
            with _LOCK:
                db.executemany(
                    "UPDATE leads SET dm_name=?, dm_email=?, phone=?, payload=?, contact_enriched_at=? "
                    "WHERE domain=?", ups)
                db.commit()
            done += len(rows)
            _ce_state["done"] = done
            _ce_state["got_person"] += sum(1 for o in out if o[6])
            _ce_state["got_phone"] += sum(1 for o in out if o[7])
        logger.info(f"[contacts] enriched {done}: +{_ce_state['got_person']} people, +{_ce_state['got_phone']} phones")
        try:
            warm_crm_cache()
        except Exception:
            pass
        return {"enriched": done, "got_person": _ce_state["got_person"], "got_phone": _ce_state["got_phone"]}
    except Exception as e:
        logger.warning(f"[contacts] failed: {e}")
        return {"enriched": _ce_state["done"], "error": str(e)}
    finally:
        _ce_state["running"] = False


def scan_signals(state: Optional[str] = None, industry: Optional[str] = None,
                 limit: int = 50000, live: bool = False, min_base_tier: str = "",
                 min_signal: float = 0.0) -> dict:
    """Score the buy-likelihood (signal_score 0–100) of CRM-eligible leads and write
    it to the indexed column so the CRM can rank a Hot List. OFFLINE by default (no
    network); `live=True` adds Serper/Crustdata intent boosts per lead (concurrent,
    needs keys). `min_signal` restricts the (live) scan to already-high-base leads so
    we only spend API calls on PRIME prospects. Paged, lock released per page."""
    from core import signals as sig
    from concurrent.futures import ThreadPoolExecutor
    db = _db()
    if not db:
        return {"scored": 0}
    where = [_CRM_ELIGIBLE]
    params: list = []
    if state:
        where.append("state=?"); params.append(state)
    if industry:
        where.append("industry=?"); params.append(industry)
    if min_base_tier:
        where.append("icp_tier=?"); params.append(min_base_tier)
    if min_signal:
        where.append("signal_score >= ?"); params.append(float(min_signal))
    wsql = " AND ".join(where)
    # Live scan: PRIME-first (high base signal_score) so the API budget hits the best
    # leads; offline scan: rowid order (full sweep).
    order = "signal_score DESC" if live else "rowid"
    _sig_state.update(running=True, done=0, scored=0, live=live)

    def _score_row(r):
        try:
            p = json.loads(r["payload"]) if r["payload"] else {}
        except Exception:
            p = {}
        sc, reasons = sig.score(p, live=live)
        p["signal_score"] = sc
        p["signal_reasons"] = reasons
        return (sc, json.dumps(p), r["domain"])

    try:
        with _LOCK:
            total = db.execute(f"SELECT COUNT(*) c FROM leads WHERE {wsql}", params).fetchone()["c"]
        _sig_state["total"] = min(total, limit)
        scored, offset = 0, 0
        while scored < limit:
            page_n = min(300 if live else 2000, limit - scored)
            with _LOCK:
                rows = db.execute(
                    f"SELECT rowid, domain, payload FROM leads WHERE {wsql} "
                    f"ORDER BY {order} LIMIT ? OFFSET ?", params + [page_n, offset]).fetchall()
            if not rows:
                break
            offset += len(rows)
            if live:  # concurrent Serper/Crustdata calls — I/O bound
                with ThreadPoolExecutor(max_workers=8) as ex:
                    ups = list(ex.map(_score_row, rows))
            else:
                ups = [_score_row(r) for r in rows]
            with _LOCK:
                db.executemany("UPDATE leads SET signal_score=?, payload=? WHERE domain=?", ups)
                db.commit()
            scored += len(ups)
            _sig_state["done"] = scored
            _sig_state["scored"] = scored
        logger.info(f"[warehouse] scan_signals: scored {scored} leads (live={live})")
        try:
            warm_crm_cache()
        except Exception:
            pass
        return {"scored": scored, "live": live}
    except Exception as e:
        logger.warning(f"[warehouse] scan_signals failed: {e}")
        return {"scored": _sig_state["scored"], "error": str(e)}
    finally:
        _sig_state["running"] = False


def crm_counts(tier: Optional[str] = None, state: Optional[str] = None,
               industry: Optional[str] = None, industries: Optional[str] = None,
               has_phone: bool = False) -> dict:
    """Per-stage counts (for the CRM panel badges), honoring active filters."""
    db = _db()
    if not db:
        return {}
    # No filters → serve from the warm aggregate cache (instant).
    if not (tier or state or industry or industries or has_phone):
        st = (crm_aggregates() or {}).get("stages", {})
        return {
            "all": sum(st.values()), "new": st.get("new", 0), "contacted": st.get("contacted", 0),
            "in_loop": st.get("in_loop", 0), "won": st.get("won", 0), "rejected": st.get("rejected", 0),
        }
    where = [_CRM_ELIGIBLE]
    params: list = []
    if tier:
        where.append("icp_tier=?"); params.append(tier)
    if state:
        where.append("state=?"); params.append(state)
    if industry:
        where.append("industry=?"); params.append(industry)
    if industries:
        inds = [x.strip() for x in industries.split(",") if x.strip()]
        if inds:
            where.append("industry IN (%s)" % ",".join("?" * len(inds))); params += inds
    if has_phone:
        where.append("phone IS NOT NULL AND phone != ''")
    wsql = " AND ".join(where)
    try:
        with _LOCK:
            rows = db.execute(
                f"SELECT COALESCE(NULLIF(crm_stage,''),'new') s, COUNT(*) n FROM leads "
                f"WHERE {wsql} GROUP BY s", params).fetchall()
        by = {r["s"]: r["n"] for r in rows}
        return {
            "all": sum(by.values()),
            "new": by.get("new", 0),
            "contacted": by.get("contacted", 0),
            "in_loop": by.get("in_loop", 0),
            "won": by.get("won", 0),
            "rejected": by.get("rejected", 0),
        }
    except Exception as e:
        logger.debug(f"[crm] counts failed: {e}")
        return {}


def crm_query(stage: Optional[str] = None, tier: Optional[str] = None,
              state: Optional[str] = None, industry: Optional[str] = None,
              q: Optional[str] = None, sort: str = "score", direction: str = "desc",
              page: int = 1, page_size: int = 50, min_signal: float = 0.0,
              has_phone: bool = False, has_contact: bool = False,
              enriched_recently: bool = False, industries: Optional[str] = None) -> dict:
    """Server-side filter + sort + paginate over the whole pool. Returns one page of
    full lead objects + the total — so the browser never holds more than `page_size`."""
    db = _db()
    if not db:
        return {"total": 0, "page": 1, "page_size": page_size, "leads": []}
    where = [_CRM_ELIGIBLE]
    params: list = []
    if stage and stage != "all":
        if stage == "new":
            where.append("COALESCE(NULLIF(crm_stage,''),'new')='new'")
        else:
            where.append("crm_stage=?"); params.append(stage)
    if tier:
        where.append("icp_tier=?"); params.append(tier)
    if state:
        where.append("state=?"); params.append(state)
    if industry:
        where.append("industry=?"); params.append(industry)
    if industries:
        inds = [x.strip() for x in industries.split(",") if x.strip()]
        if inds:
            where.append("industry IN (%s)" % ",".join("?" * len(inds))); params += inds
    if min_signal:
        where.append("signal_score >= ?"); params.append(float(min_signal))
    if has_phone:
        where.append("phone IS NOT NULL AND phone != ''")
    if has_contact:
        where.append("((phone IS NOT NULL AND phone != '') OR (dm_email IS NOT NULL AND dm_email != ''))")
    if enriched_recently:
        where.append("contact_enriched_at IS NOT NULL AND contact_enriched_at > 0")
    if q:
        where.append("(company_name LIKE ? OR dm_email LIKE ? OR phone LIKE ?)")
        params += [f"%{q}%", f"%{q}%", f"%{q}%"]
    wsql = " AND ".join(where)
    col = _SORTABLE.get(sort, "score")
    dir_ = "ASC" if str(direction).lower() == "asc" else "DESC"
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 50), 1), 200)
    try:
        with _LOCK:
            total = db.execute(f"SELECT COUNT(*) c FROM leads WHERE {wsql}", params).fetchone()["c"]
            rows = db.execute(
                f"SELECT domain, crm_stage, contact_method, contacted_at, payload FROM leads "
                f"WHERE {wsql} ORDER BY {col} {dir_} LIMIT ? OFFSET ?",
                params + [page_size, (page - 1) * page_size]).fetchall()
        leads = []
        for r in rows:
            try:
                p = json.loads(r["payload"]) if r["payload"] else {}
            except Exception:
                p = {}
            p["crm_stage"] = r["crm_stage"] or "new"
            p["contact_method"] = r["contact_method"]
            p["contacted_at"] = r["contacted_at"]
            p.setdefault("id", r["domain"])
            leads.append(p)
        return {"total": total, "page": page, "page_size": page_size, "leads": leads}
    except Exception as e:
        logger.debug(f"[crm] query failed: {e}")
        return {"total": 0, "page": page, "page_size": page_size, "leads": []}


def crm_update_stage(domain_or_id: str, stage: str, method: Optional[str] = None,
                     note: Optional[str] = None) -> dict:
    """Move a lead to a CRM stage (+ optional contact method/note). Matches by domain
    or by the lead's id stored in payload."""
    db = _db()
    if not db or stage not in _CRM_STAGES:
        return {"ok": False, "error": "invalid stage"}
    key = _domain_of(domain_or_id) or domain_or_id
    try:
        with _LOCK:
            row = db.execute(
                "SELECT domain, payload FROM leads WHERE domain=? OR payload LIKE ? LIMIT 1",
                (key, f'%"id": "{domain_or_id}"%')).fetchone()
            if not row:
                return {"ok": False, "error": "lead not found"}
            dom = row["domain"]
            try:
                p = json.loads(row["payload"]) if row["payload"] else {}
            except Exception:
                p = {}
            old_stage = p.get("crm_stage") or "new"
            p["crm_stage"] = stage
            if method:
                p["contact_method"] = method
            if note:
                p["contact_note"] = note
            now = time.time()
            db.execute(
                "UPDATE leads SET crm_stage=?, contact_method=COALESCE(?,contact_method), "
                "contact_note=COALESCE(?,contact_note), contacted_at=?, crm_updated_at=?, payload=? "
                "WHERE domain=?",
                (stage, method, note, now if stage == "contacted" else None, now, json.dumps(p), dom))
            db.commit()
        _agg_move_stage(old_stage, stage)  # keep cached counts accurate, no recompute
        return {"ok": True, "domain": dom, "stage": stage}
    except Exception as e:
        logger.debug(f"[crm] update failed: {e}")
        return {"ok": False, "error": str(e)}


# ── Aggregate cache ───────────────────────────────────────────────────────────
# The dashboard/counts/options run GROUP BY/DISTINCT scans over ~900k rows (~6s
# total). They barely change second-to-second, so compute ALL of them in one pass,
# cache for a while, warm on startup, and adjust in-place on stage moves → instant.
_AGG: dict = {"data": None, "ts": 0.0}
_AGG_TTL = 1800  # 30 min
_AGG_PATH = Path(os.getenv("CRM_AGG_PATH", "./data/crm_agg.json"))


def _load_agg_disk() -> None:
    """Load the last-computed aggregates from disk so the cache is warm the instant
    the server starts (no cold 6s first-request)."""
    try:
        if _AGG["data"] is None and _AGG_PATH.exists():
            j = json.loads(_AGG_PATH.read_text())
            _AGG["data"], _AGG["ts"] = j.get("data"), j.get("ts", 0.0)
    except Exception:
        pass


def _save_agg_disk() -> None:
    try:
        _AGG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _AGG_PATH.write_text(json.dumps({"data": _AGG["data"], "ts": _AGG["ts"]}))
    except Exception:
        pass


def _compute_agg() -> dict:
    db = _db()
    if not db:
        return {}
    with _LOCK:
        stage_rows = db.execute(
            f"SELECT COALESCE(NULLIF(crm_stage,''),'new') s, COUNT(*) n FROM leads "
            f"WHERE {_CRM_ELIGIBLE} GROUP BY s").fetchall()
        tier_rows = db.execute(
            f"SELECT COALESCE(NULLIF(icp_tier,''),'Unrated') t, COUNT(*) n FROM leads "
            f"WHERE {_CRM_ELIGIBLE} GROUP BY t").fetchall()
        ind_rows = db.execute(
            f"SELECT industry, COUNT(*) n FROM leads WHERE {_CRM_ELIGIBLE} AND industry!='' "
            f"GROUP BY industry ORDER BY n DESC").fetchall()
        state_rows = db.execute(
            f"SELECT state, COUNT(*) n FROM leads WHERE {_CRM_ELIGIBLE} AND state!='' "
            f"GROUP BY state ORDER BY n DESC").fetchall()
        with_email = db.execute(
            f"SELECT COUNT(*) n FROM leads WHERE {_CRM_ELIGIBLE} AND dm_email!='' AND dm_email IS NOT NULL").fetchone()["n"]
        with_phone = db.execute(
            f"SELECT COUNT(*) n FROM leads WHERE {_CRM_ELIGIBLE} AND phone!='' AND phone IS NOT NULL").fetchone()["n"]
    stages = {r["s"]: r["n"] for r in stage_rows}
    return {
        "stages": stages,
        "tiers": {r["t"]: r["n"] for r in tier_rows},
        "industries": [{"name": r["industry"], "count": r["n"]} for r in ind_rows],
        "states": [{"name": r["state"], "count": r["n"]} for r in state_rows],
        "with_email": with_email, "with_phone": with_phone,
    }


_agg_refreshing = threading.Event()


def _refresh_agg_bg() -> None:
    """Recompute aggregates in the background (stale-while-revalidate)."""
    if _agg_refreshing.is_set():
        return
    _agg_refreshing.set()
    def _run():
        try:
            d = _compute_agg()
            if d:
                _AGG.update(data=d, ts=time.time())
                _save_agg_disk()
        finally:
            _agg_refreshing.clear()
    threading.Thread(target=_run, daemon=True).start()


def crm_aggregates(force: bool = False) -> dict:
    if _AGG["data"] is None:
        _load_agg_disk()                       # warm from disk on first touch
    fresh = _AGG["data"] and (time.time() - _AGG["ts"] < _AGG_TTL)
    if force or _AGG["data"] is None:
        d = _compute_agg()                     # blocking only when we truly have nothing
        if d:
            _AGG.update(data=d, ts=time.time())
            _save_agg_disk()
    elif not fresh:
        _refresh_agg_bg()                      # stale → serve now, refresh behind the scenes
    return _AGG["data"] or {}


def warm_crm_cache() -> dict:
    """Compute + cache aggregates (call at startup so the first CRM open is instant)."""
    return crm_aggregates(force=True)


def _agg_move_stage(old: str, new: str) -> None:
    """Keep the cached stage counts accurate after a single stage change — avoids a
    full 6s recompute on every CRM update."""
    if not _AGG["data"]:
        return
    st = _AGG["data"].get("stages", {})
    old = old or "new"
    st[old] = max(0, st.get(old, 0) - 1)
    st[new] = st.get(new, 0) + 1
    _save_agg_disk()


def crm_dashboard() -> dict:
    """KPIs + distributions for the CRM overview — served from the warm cache."""
    a = crm_aggregates()
    if not a:
        return {}
    stages = a["stages"]
    total = sum(stages.values())
    won = stages.get("won", 0)
    worked = stages.get("contacted", 0) + stages.get("in_loop", 0) + won + stages.get("rejected", 0)
    return {
        "total": total,
        "stages": {k: stages.get(k, 0) for k in ("new", "contacted", "in_loop", "won", "rejected")},
        "tiers": a["tiers"],
        "top_industries": a["industries"][:8],
        "top_states": a["states"][:8],
        "with_email": a["with_email"],
        "with_phone": a["with_phone"],
        "win_rate": round(100 * won / worked, 1) if worked else 0.0,
    }


def _crm_dashboard_legacy() -> dict:
    db = _db()
    if not db:
        return {}
    try:
        with _LOCK:
            stage_rows = db.execute(
                f"SELECT COALESCE(NULLIF(crm_stage,''),'new') s, COUNT(*) n FROM leads "
                f"WHERE {_CRM_ELIGIBLE} GROUP BY s").fetchall()
            tier_rows = db.execute(
                f"SELECT COALESCE(NULLIF(icp_tier,''),'Unrated') t, COUNT(*) n FROM leads "
                f"WHERE {_CRM_ELIGIBLE} GROUP BY t").fetchall()
            ind_rows = db.execute(
                f"SELECT industry, COUNT(*) n FROM leads WHERE {_CRM_ELIGIBLE} AND industry!='' "
                f"GROUP BY industry ORDER BY n DESC LIMIT 8").fetchall()
            state_rows = db.execute(
                f"SELECT state, COUNT(*) n FROM leads WHERE {_CRM_ELIGIBLE} AND state!='' "
                f"GROUP BY state ORDER BY n DESC LIMIT 8").fetchall()
            with_email = db.execute(
                f"SELECT COUNT(*) n FROM leads WHERE {_CRM_ELIGIBLE} AND dm_email!='' AND dm_email IS NOT NULL").fetchone()["n"]
            with_phone = db.execute(
                f"SELECT COUNT(*) n FROM leads WHERE {_CRM_ELIGIBLE} AND phone!='' AND phone IS NOT NULL").fetchone()["n"]
        stages = {r["s"]: r["n"] for r in stage_rows}
        total = sum(stages.values())
        won = stages.get("won", 0)
        worked = stages.get("contacted", 0) + stages.get("in_loop", 0) + won + stages.get("rejected", 0)
        return {
            "total": total,
            "stages": {
                "new": stages.get("new", 0), "contacted": stages.get("contacted", 0),
                "in_loop": stages.get("in_loop", 0), "won": won, "rejected": stages.get("rejected", 0),
            },
            "tiers": {r["t"]: r["n"] for r in tier_rows},
            "top_industries": [{"name": r["industry"], "count": r["n"]} for r in ind_rows],
            "top_states": [{"name": r["state"], "count": r["n"]} for r in state_rows],
            "with_email": with_email,
            "with_phone": with_phone,
            "win_rate": round(100 * won / worked, 1) if worked else 0.0,
        }
    except Exception as e:
        logger.debug(f"[crm] dashboard failed: {e}")
        return {}


def crm_export_rows(stage=None, tier=None, state=None, industry=None, q=None, limit=50000,
                    sort="score", min_signal=0.0):
    """Yield filtered CRM leads as flat dicts for CSV export (capped). Supports sorting
    by signal_score + a min_signal floor so the export IS the ranked Hot List."""
    # Page through (crm_query caps a page at 200) so the export covers the full set.
    page, emitted = 1, 0
    while emitted < limit:
        res = crm_query(stage=stage, tier=tier, state=state, industry=industry, q=q,
                        sort=sort, direction="desc", page=page, page_size=200,
                        min_signal=min_signal)
        leads = res.get("leads", [])
        if not leads:
            break
        page += 1
        for l in leads:
            emitted += 1
            if emitted > limit:
                return
            src = (l.get("source") or "")
            phone_verified = "Google Maps (verified)" if "google" in src.lower() or "maps" in src.lower() else ("web-enriched" if l.get("contact_enriched_at") else "")
            yield {
            "signal_score": l.get("signal_score", ""),
            "why_now": " · ".join(l.get("signal_reasons", []) or []),
            "company_name": l.get("company_name", ""),
            "contact_person": l.get("dm_name", ""),
            "role": l.get("dm_role", ""),
            "phone": l.get("mobile") or l.get("phone", ""),
            "phone_source": phone_verified,
            "email": (l.get("contact_emails") or [l.get("dm_email", "")])[0],
            "industry": l.get("industry", ""),
            "state": l.get("state", ""),
            "tier": l.get("icp_tier", ""),
            "hrms_fit_score": l.get("qualification_score", ""),
            "crm_stage": l.get("crm_stage", "new"),
            "website": l.get("website", ""),
            "cin": l.get("cin", ""),
            "company_status": l.get("company_status", ""),
        }


def crm_filter_options() -> dict:
    """Distinct states + industries for the dropdowns — derived from the warm cache."""
    a = crm_aggregates() or {}
    states = sorted(x["name"] for x in a.get("states", []))
    industries = sorted(x["name"] for x in a.get("industries", []))
    return {"states": states, "industries": industries}
