"""
Startup India registry harvester (FREE, government source).
-----------------------------------------------------------
startupindia.gov.in lists 454k+ companies (145k DPIIT-recognized). Its public
search API (api.startupindia.gov.in/sih/api/noauth/search/profiles) returns the
company NAME, STATE, CITY, INDUSTRY, SECTOR, STAGE, DPIIT status + registration
date — exactly the ICP feedstock for the HRMS campaign. Quirks reverse-engineered
from the live site:
  • `page` goes in the BODY (not the query string) — and it's 0-indexed.
  • page size is server-capped at ~9 (the `size` param is ignored).
  • sort is `{"orders":[{"field":"registeredOn","direction":"DESC"}]}`.

So the full crawl is ~50,500 pages (or ~16,210 for the DPIIT subset). This module
pages politely + concurrently, is RESUMABLE (last page persisted per filter), and
banks into a dedicated `startups` table. Contact details (step 2) are filled later
by the existing Maps/crawl enrichment using name+city. Fail-safe throughout.
"""
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import requests
from loguru import logger

from core import warehouse

_API = "https://api.startupindia.gov.in/sih/api/noauth/search/profiles"
_H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0",
      "Content-Type": "application/json", "Accept": "application/json"}
_PAGE_SIZE = 9          # server-fixed
_CHUNK = 6              # pages fetched concurrently per round (lower = fewer throttle hits)
_MAX_EMPTY_STREAK = 10  # consecutive empty chunks (throttle) before pausing the harvest

_lock = threading.Lock()
_stop = threading.Event()   # set by stop() → the harvest loop breaks at the next chunk
_state = {"running": False, "filter": "", "scraped": 0, "total": 0,
          "last_page": 0, "pages": 0, "started_at": 0.0, "error": ""}


def stop() -> dict:
    """Request the running harvest to pause cleanly (resume point is already saved)."""
    _stop.set()
    return {"status": "stopping", "message": "Harvest will pause at the next chunk; resume anytime."}


def _ensure() -> Optional[sqlite3.Connection]:
    c = warehouse._db()
    if not c:
        return None
    c.executescript("""
    CREATE TABLE IF NOT EXISTS startups (
        sid             TEXT PRIMARY KEY,
        name            TEXT,
        state           TEXT,
        city            TEXT,
        industry        TEXT,
        industries      TEXT,
        sector          TEXT,
        sectors         TEXT,
        stage           TEXT,
        dpiit_certified INTEGER,
        dipp_number     TEXT,
        registered_on   REAL,
        role            TEXT,
        raw             TEXT,
        discovered_at   REAL,
        website         TEXT,
        phone           TEXT,
        dm_name         TEXT,
        email           TEXT,
        contact_status  TEXT DEFAULT 'pending',
        enriched_at     REAL
    );
    CREATE INDEX IF NOT EXISTS idx_su_state    ON startups(state);
    CREATE INDEX IF NOT EXISTS idx_su_industry ON startups(industry);
    CREATE INDEX IF NOT EXISTS idx_su_contact  ON startups(contact_status);
    CREATE TABLE IF NOT EXISTS startup_harvest (
        filter_key TEXT PRIMARY KEY,
        last_page  INTEGER,
        total      INTEGER,
        updated_at REAL
    );
    """)
    c.commit()
    return c


# ── fetch ─────────────────────────────────────────────────────────────────────
def _body(page: int, dpiit: bool, states: list, industries: list) -> dict:
    return {
        "query": "", "focusSector": False,
        "industries": industries or [], "sectors": [], "states": states or [],
        "cities": [], "stages": [], "badges": [], "roles": ["Startup"],
        "page": page,
        "sort": {"orders": [{"field": "registeredOn", "direction": "DESC"}]},
        "dpiitRecogniseUser": dpiit, "internationalUser": False,
    }


def _fetch_page(page: int, dpiit: bool, states: list, industries: list) -> tuple[list, int]:
    """Return (records, totalElements). Retries DNS/timeout blips; () on hard fail."""
    for attempt in range(6):
        try:
            r = requests.post(_API, json=_body(page, dpiit, states, industries),
                              headers=_H, timeout=25)
            if r.status_code == 200:
                d = r.json()
                return d.get("content", []) or [], int(d.get("totalElements") or 0)
            time.sleep(1.0 + attempt)
        except Exception:
            time.sleep(1.0 + attempt)
    return [], -1


def _row(rec: dict) -> tuple:
    inds = rec.get("industries") or []
    secs = rec.get("sectors") or []
    stgs = rec.get("stages") or []
    return (
        rec.get("id"), rec.get("name"), rec.get("state"), rec.get("city"),
        (inds[0] if inds else ""), ", ".join(inds),
        (secs[0] if secs else ""), ", ".join(secs),
        (stgs[0] if stgs else ""),
        1 if rec.get("dippCertified") else 0, rec.get("dippNumber"),
        rec.get("registeredOn"), rec.get("role"),
        json.dumps(rec, ensure_ascii=False), time.time(),
    )


def _save(records: list) -> int:
    c = warehouse._db()
    if not c or not records:
        return 0
    rows = [_row(r) for r in records if r.get("id")]
    with warehouse._LOCK:
        c.executemany(
            """INSERT OR IGNORE INTO startups
               (sid,name,state,city,industry,industries,sector,sectors,stage,
                dpiit_certified,dipp_number,registered_on,role,raw,discovered_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
        c.commit()
    return len(rows)


# ── harvest (resumable, background-safe) ───────────────────────────────────────
def status() -> dict:
    # _lock is the run-once mutex held for the whole harvest; never block status on it.
    # _state is a plain dict — assignments are atomic under the GIL.
    s = dict(_state)
    s["scraped_in_db"] = _count_all()
    if s["total"] > 0:
        s["pct"] = round(min(100.0, s["last_page"] * _PAGE_SIZE * 100.0 / s["total"]), 2)
    return s


def _count_all() -> int:
    c = warehouse._db()
    if not c:
        return 0
    try:
        # Reads share the single warehouse connection with the harvest's concurrent
        # writes — guard with the same lock, else a cursor race returns None.
        with warehouse._LOCK:
            row = c.execute("SELECT COUNT(*) FROM startups").fetchone()
        return row[0] if row else 0
    except Exception:
        return 0


def harvest(dpiit: bool = False, states: Optional[str] = None,
            industries: Optional[str] = None, max_pages: Optional[int] = None,
            restart: bool = False) -> dict:
    """Page through the registry into the `startups` table. Resumable per filter."""
    if not _lock.acquire(blocking=False):
        return {"status": "busy", **status()}
    _stop.clear()
    try:
        c = _ensure()
        if not c:
            return {"status": "error", "message": "warehouse unavailable"}
        st = [s.strip() for s in (states or "").split(",") if s.strip()]
        ind = [s.strip() for s in (industries or "").split(",") if s.strip()]
        fkey = f"dpiit={dpiit}|states={','.join(st)}|ind={','.join(ind)}"

        row = c.execute("SELECT last_page,total FROM startup_harvest WHERE filter_key=?",
                        (fkey,)).fetchone()
        start_page = 0 if (restart or not row) else int(row[0])
        _, total = _fetch_page(start_page, dpiit, st, ind)  # warm + total
        if total < 0:
            return {"status": "error", "message": "API unreachable"}
        total_pages = (total + _PAGE_SIZE - 1) // _PAGE_SIZE
        if max_pages:
            total_pages = min(total_pages, start_page + max_pages)

        _state.update(running=True, filter=fkey, total=total, last_page=start_page,
                      pages=total_pages, started_at=time.time(), error="")
        logger.info(f"[startupindia] harvest {fkey}: {total} companies, "
                    f"{total_pages} pages, resume@{start_page}")

        page = start_page
        added = 0
        empty_streak = 0
        while page < total_pages:
            if _stop.is_set():
                logger.info(f"[startupindia] stop requested @page {page} — pausing")
                break
            chunk = list(range(page, min(page + _CHUNK, total_pages)))
            with ThreadPoolExecutor(max_workers=_CHUNK) as ex:
                results = list(ex.map(
                    lambda p: _fetch_page(p, dpiit, st, ind)[0], chunk))
            batch = [rec for recs in results for rec in recs]

            if not batch:
                # A whole chunk came back empty. We verified every deep page (to 50k)
                # returns data, so this is the gov server throttling our burst — NOT
                # end-of-data. Back off and RETRY the same pages (don't advance, don't
                # skip data). Only give up after a long sustained streak.
                empty_streak += 1
                _state["error"] = f"throttled — backing off (streak {empty_streak})"
                if empty_streak >= _MAX_EMPTY_STREAK:
                    logger.warning(f"[startupindia] {empty_streak} empty chunks @page {page} — pausing (resume later)")
                    break
                time.sleep(min(45, 4 * empty_streak))  # 4,8,12,… up to 45s cooldown
                continue

            empty_streak = 0
            _state["error"] = ""
            added += _save(batch)
            page = chunk[-1] + 1
            with warehouse._LOCK:
                c.execute("""INSERT INTO startup_harvest(filter_key,last_page,total,updated_at)
                             VALUES(?,?,?,?) ON CONFLICT(filter_key) DO UPDATE SET
                             last_page=excluded.last_page,total=excluded.total,updated_at=excluded.updated_at""",
                          (fkey, page, total, time.time()))
                c.commit()
            _state["last_page"] = page    # atomic dict assignment; no re-lock (would deadlock)
            _state["scraped"] = added
            time.sleep(0.15)  # be polite

        _state["running"] = False
        done = page >= total_pages
        if _stop.is_set():
            note = "stopped by user — click Resume to continue later"
        elif done:
            note = "complete"
        else:
            note = "throttled — click Resume to continue"
        return {"status": "ok" if done else "paused", "filter": fkey, "added": added,
                "scraped_in_db": _count_all(), "total": total, "note": note}
    except Exception as e:
        _state.update(running=False, error=str(e))
        logger.warning(f"[startupindia] harvest failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _lock.release()


# ── query / counts / export ────────────────────────────────────────────────────
# Delhi-NCR = the Delhi state (all its districts) + the core NCR cities that sit in
# Haryana / UP. Lowercased for case-insensitive match.
_NCR_CITIES = ["gurugram", "gurgaon", "noida", "greater noida",
               "gautam buddha nagar", "ghaziabad", "faridabad"]


def _where(state, industry, q, has_contact, ncr=False, dpiit=False, stage="") -> tuple[str, list]:
    cl, args = [], []
    if ncr:
        ph = ",".join("?" * len(_NCR_CITIES))
        cl.append(f"(state='Delhi' OR lower(city) IN ({ph}))")
        args += _NCR_CITIES
    elif state:
        cl.append("state=?"); args.append(state)
    if industry:
        cl.append("industry=?"); args.append(industry)
    if stage:
        cl.append("stage=?"); args.append(stage)
    if dpiit:
        cl.append("dpiit_certified=1")
    if q:
        cl.append("name LIKE ?"); args.append(f"%{q}%")
    if has_contact:
        cl.append("phone!='' AND phone IS NOT NULL")
    return (" WHERE " + " AND ".join(cl)) if cl else "", args


def query(state="", industry="", q="", limit=100, offset=0, has_contact=False,
          sort="registered_on", direction="desc", ncr=False, dpiit=False, stage="") -> dict:
    c = _ensure()
    if not c:
        return {"rows": [], "total": 0}
    w, args = _where(state, industry, q, has_contact, ncr, dpiit, stage)
    sort = sort if sort in ("registered_on", "name", "state", "industry", "enriched_at") else "registered_on"
    direction = "ASC" if direction.lower() == "asc" else "DESC"
    with warehouse._LOCK:
        trow = c.execute(f"SELECT COUNT(*) FROM startups{w}", args).fetchone()
        rows = c.execute(
            f"SELECT sid,name,state,city,industry,sector,stage,dpiit_certified,"
            f"registered_on,website,phone,dm_name,dm_role,linkedin,email,contact_status FROM startups{w} "
            f"ORDER BY {sort} {direction} LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
    return {"rows": [dict(r) for r in rows], "total": (trow[0] if trow else 0),
            "limit": limit, "offset": offset}


def counts() -> dict:
    c = _ensure()
    if not c:
        return {"total": 0, "by_state": [], "by_industry": []}
    with warehouse._LOCK:
        trow = c.execute("SELECT COUNT(*) FROM startups").fetchone()
        prow = c.execute("SELECT COUNT(*) FROM startups WHERE phone!='' AND phone IS NOT NULL").fetchone()
        by_state = [dict(r) for r in c.execute(
            "SELECT state, COUNT(*) n FROM startups GROUP BY state ORDER BY n DESC LIMIT 40").fetchall()]
        by_ind = [dict(r) for r in c.execute(
            "SELECT industry, COUNT(*) n FROM startups GROUP BY industry ORDER BY n DESC LIMIT 40").fetchall()]
    return {"total": (trow[0] if trow else 0), "with_phone": (prow[0] if prow else 0),
            "by_state": by_state, "by_industry": by_ind}


def filter_options() -> dict:
    c = _ensure()
    if not c:
        return {"states": [], "industries": []}
    with warehouse._LOCK:
        states = [r[0] for r in c.execute(
            "SELECT DISTINCT state FROM startups WHERE state!='' ORDER BY state").fetchall() if r[0]]
        inds = [r[0] for r in c.execute(
            "SELECT DISTINCT industry FROM startups WHERE industry!='' ORDER BY industry").fetchall() if r[0]]
    return {"states": states, "industries": inds}


def export_rows(state="", industry="", q="", limit=100000,
                ncr=False, dpiit=False, stage="") -> list[dict]:
    c = _ensure()
    if not c:
        return []
    w, args = _where(state, industry, q, False, ncr, dpiit, stage)
    with warehouse._LOCK:
        rows = c.execute(
            f"SELECT name,state,city,industry,sector,stage,dpiit_certified,dipp_number,"
            f"registered_on,website,phone,dm_name,dm_role,linkedin,email,company_linkedin,contact_status "
            f"FROM startups{w} ORDER BY state, industry, name LIMIT ?", args + [limit]).fetchall()
    return [dict(r) for r in rows]
