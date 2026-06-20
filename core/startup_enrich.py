"""
Apify-powered contact enrichment for harvested startups.
--------------------------------------------------------
Two-stage, accuracy-first (the registry gives only NAME + CITY):

  Stage 1  Google Maps (lukaskrivka/google-maps-with-contact-details)
           "{name} {city}" → phone + website(domain). Maps FUZZY-matches, so we
           accept a result only if its title strongly matches the query name
           (token Jaccard ≥ 0.6 + first significant token present) — better to
           store nothing than the wrong company's phone.

  Stage 2  Apollo leads (microworlds/leads-finder)
           verified domain → decision-maker (first/last name), title, PERSONAL
           linkedin_url, email, + company linkedin. Picks the most senior match.

Uses the user's Apify token (rc.get('apify_api_token')). PAY_PER_EVENT — cost is
tracked per run and surfaced in status. Runs as a background task; resumable in the
sense that already-enriched rows (contact_status != 'pending') are skipped.
"""
import json
import re
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from loguru import logger

from core import warehouse, runtime_config as rc

_MAPS_ACTOR = "lukaskrivka~google-maps-with-contact-details"
_APOLLO_ACTOR = "microworlds~leads-finder"
_API = "https://api.apify.com/v2"
_MAPS_BATCH = 100          # search strings per Maps run
_APOLLO_TITLES = ["founder", "co-founder", "owner", "proprietor", "ceo",
                  "managing director", "director", "partner",
                  "head of human resources", "head of hr", "hr manager", "cto", "coo"]
# title → seniority rank (higher = more decision-authority) for picking the best person
_RANK = [("founder", 100), ("co-founder", 95), ("owner", 95), ("proprietor", 95),
         ("ceo", 90), ("managing director", 88), ("director", 70), ("partner", 68),
         ("head of human", 60), ("head of hr", 60), ("hr manager", 50),
         ("cto", 45), ("coo", 45)]

_REGISTRY_ACTOR = "foxlabs~indian-company-data"
_lock = threading.Lock()
_state = {"running": False, "done": 0, "total": 0, "with_phone": 0,
          "with_person": 0, "cost_usd": 0.0, "error": "", "stage": ""}
_reg_lock = threading.Lock()
_reg_state = {"running": False, "done": 0, "total": 0, "with_director": 0,
              "with_email": 0, "cost_usd": 0.0, "error": ""}

_LEGAL = {"private", "limited", "pvt", "ltd", "llp", "india", "the", "and",
          "co", "company", "corporation", "incorporated", "inc", "opc"}
_DIR_DOMAINS = ("justdial", "indiamart", "facebook", "linkedin", "zaubacorp",
                "tofler", "youtube", "instagram", "google.", "sulekha", "tradeindia")


def _toks(s: str) -> list:
    t = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split()
    return [x for x in t if x not in _LEGAL and len(x) > 1]


def _name_match(query: str, title: str) -> bool:
    q, t = _toks(query), _toks(title)
    if not q or not t:
        return False
    qs, ts = set(q), set(t)
    jac = len(qs & ts) / len(qs | ts)
    return q[0] in ts and jac >= 0.6


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_SITE_SUBS = ["", "about", "about-us", "team", "our-team", "leadership", "contact", "contact-us"]
_LI_RE = re.compile(r"linkedin\.com/in/[A-Za-z0-9\-_%]+", re.I)
_SITE_PROMPT = """You are reading an Indian company's website text. Find the SINGLE most senior \
NAMED human (founder, owner, proprietor, partner, director, MD, CEO, or HR head) explicitly named.
Return ONLY JSON: {{"name":"<full name or null>","role":"<title or null>"}}
- name MUST be a real person's full name in the text, NEVER the company name/city/product.
- If no individual is named, name=null.
COMPANY: {company}
TEXT:
{text}"""


def _site_person(company: str, url: str) -> Optional[dict]:
    """Free fallback: read the company's own site with the LLM pool → founder name
    (+ a personal LinkedIn link if present in the page). Returns {name,role,linkedin}."""
    import requests
    m = re.match(r"(https?://[^/]+)", url or "")
    if not m:
        return None
    base = m.group(1)
    chunks, li = [], ""
    s = requests.Session(); s.headers["User-Agent"] = _UA
    for sub in _SITE_SUBS:
        if sum(len(x) for x in chunks) > 6500:
            break
        try:
            r = s.get(base if not sub else f"{base}/{sub}", timeout=8)
            if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
                continue
            html = r.text
            if not li:
                hit = _LI_RE.search(html)
                if hit and "/company/" not in hit.group(0):
                    li = "https://www." + hit.group(0)
            txt = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html))
            txt = re.sub(r"\s+", " ", txt).strip()
            if len(txt) > 60:
                chunks.append(f"[{sub or 'home'}] {txt[:2200]}")
        except Exception:
            continue
    if not chunks:
        return None
    try:
        from agents import llm_pool
        resp = llm_pool.complete(_SITE_PROMPT.format(company=company, text="\n".join(chunks)[:7000]),
                                 tier="strong", temperature=0.0, max_tokens=160)
        mm = re.search(r"\{.*?\}", resp, re.S)
        data = json.loads(mm.group(0)) if mm else {}
    except Exception:
        return None
    name = (data.get("name") or "").strip() if isinstance(data.get("name"), str) else ""
    if not name or name.lower() in ("null", "none") or not _is_person(name):
        return None
    cn = re.sub(r"[^a-z]", "", company.lower()); nn = re.sub(r"[^a-z]", "", name.lower())
    if nn and (nn in cn or cn in nn):
        return None
    role = (data.get("role") or "").strip() if isinstance(data.get("role"), str) else ""
    return {"name": name, "role": role[:80] if role.lower() not in ("null", "none") else "",
            "linkedin": li}


def _is_person(name: str) -> bool:
    try:
        from core.contact_finder import valid_person
        return valid_person(name)
    except Exception:
        w = name.split()
        return 2 <= len(w) <= 3 and all(x[:1].isupper() for x in w)


def _domain(url: str) -> str:
    m = re.search(r"https?://([^/]+)", url or "")
    d = (m.group(1) if m else "").lower().replace("www.", "").strip()
    if not d or any(x in d for x in _DIR_DOMAINS):
        return ""
    return d


# ── Apify run helpers ───────────────────────────────────────────────────────
def _http(url: str, data: Optional[dict] = None, timeout: int = 60):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"},
                                 method="POST" if data is not None else "GET")
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt == 3:
                logger.warning(f"[startup_enrich] http fail {url[:60]}: {e}")
                return None
            time.sleep(2 + attempt)


def _run_actor(actor: str, inp: dict, token: str, max_wait: int = 900):
    """Start an actor run, poll to completion, return (items, usd, status)."""
    started = _http(f"{_API}/acts/{actor}/runs?token={token}", inp)
    if not started:
        return [], 0.0, "START_FAILED"
    run = started.get("data", {})
    rid, dsid = run.get("id"), run.get("defaultDatasetId")
    waited = 0
    while waited < max_wait:
        time.sleep(6); waited += 6
        st = _http(f"{_API}/actor-runs/{rid}?token={token}")
        run = (st or {}).get("data", run)
        if run.get("status") in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT", "TIMING-OUT"):
            break
    items = []
    if dsid:
        got = _http(f"{_API}/datasets/{dsid}/items?token={token}&clean=true")
        items = got if isinstance(got, list) else []
    usd = run.get("usageTotalUsd") or 0.0
    return items, float(usd), run.get("status")


# ── status ──────────────────────────────────────────────────────────────────
def enrich_status() -> dict:
    return dict(_state)


def _targets(ncr, dpiit, stage, limit) -> list:
    from core import startup_india as si
    c = si._ensure()
    if not c:
        return []
    w, args = si._where("", "", "", False, ncr, dpiit, stage)
    cond = (w + " AND " if w else " WHERE ") + "(contact_status IS NULL OR contact_status='pending')"
    with warehouse._LOCK:
        rows = c.execute(
            f"SELECT sid,name,city,state FROM startups{cond} LIMIT ?", args + [limit]).fetchall()
    return [dict(r) for r in rows]


# ── main pipeline ─────────────────────────────────────────────────────────────
def enrich(ncr=True, dpiit=True, stage="Scaling", limit=40) -> dict:
    if not _lock.acquire(blocking=False):
        return {"status": "busy", **enrich_status()}
    token = (rc.get("apify_api_token") or "").strip()
    try:
        if not token:
            return {"status": "error", "message": "No apify_api_token configured"}
        from core import startup_india as si
        c = si._ensure()
        targets = _targets(ncr, dpiit, stage, limit)
        _state.update(running=True, done=0, total=len(targets), with_phone=0,
                      with_person=0, cost_usd=0.0, error="", stage="maps")
        if not targets:
            _state["running"] = False
            return {"status": "ok", "message": "no pending targets", "total": 0}
        logger.info(f"[startup_enrich] enriching {len(targets)} startups via Apify")

        by_sid = {t["sid"]: t for t in targets}
        verified = {}   # sid -> {phone, website, domain}

        # ── Stage 1: Google Maps (phone + domain), name-verified ──
        for i in range(0, len(targets), _MAPS_BATCH):
            chunk = targets[i:i + _MAPS_BATCH]
            queries = [f'{t["name"]} {t["city"]}' for t in chunk]
            qmap = {q.lower(): t for q, t in zip(queries, chunk)}
            items, usd, status = _run_actor(_MAPS_ACTOR, {
                "searchStringsArray": queries, "maxCrawledPlacesPerSearch": 1,
                "language": "en", "scrapePlaceDetailPage": True}, token)
            _state["cost_usd"] = round(_state["cost_usd"] + usd, 4)
            for it in items:
                q = (it.get("searchString") or "").lower()
                t = qmap.get(q)
                if not t or not _name_match(t["name"], it.get("title", "")):
                    continue
                phone = it.get("phone") or ""
                site = it.get("website") or ""
                dom = _domain(site)
                verified[t["sid"]] = {"phone": phone, "website": site, "domain": dom,
                                      "maps_title": it.get("title")}
            _state["done"] = min(len(targets), i + len(chunk))

        # write Stage-1 results (phone/website) immediately
        now = time.time()
        with warehouse._LOCK:
            for sid, v in verified.items():
                c.execute("UPDATE startups SET phone=?, website=? WHERE sid=?",
                          (v["phone"], v["website"], sid))
                if v["phone"]:
                    _state["with_phone"] += 1
            c.commit()

        # ── Stage 2: Apollo by verified domain → decision-maker ──
        _state["stage"] = "apollo"
        domains = sorted({v["domain"] for v in verified.values() if v["domain"]})
        dom_to_sid = {}
        for sid, v in verified.items():
            if v["domain"]:
                dom_to_sid.setdefault(v["domain"], sid)
        people_by_dom = {}
        if domains:
            for i in range(0, len(domains), 100):
                dchunk = domains[i:i + 100]
                items, usd, status = _run_actor(_APOLLO_ACTOR, {
                    "company_domains": dchunk, "contact_job_titles": _APOLLO_TITLES,
                    "max_result": max(10, len(dchunk) * 3)}, token)
                _state["cost_usd"] = round(_state["cost_usd"] + usd, 4)
                for p in items:
                    if set(p.keys()) == {"message"}:
                        continue
                    dom = (p.get("organization_primary_domain") or "").lower().replace("www.", "")
                    if dom:
                        people_by_dom.setdefault(dom, []).append(p)

        def _score(p) -> int:
            tl = (p.get("title") or "").lower()
            for kw, r in _RANK:
                if kw in tl:
                    return r
            return 10

        person_done = set()
        with warehouse._LOCK:
            for dom, sid in dom_to_sid.items():
                ppl = people_by_dom.get(dom)
                if not ppl:
                    continue
                best = max(ppl, key=_score)
                name = " ".join(x for x in [best.get("first_name"), best.get("last_name")] if x).strip()
                # reject junk: must be a plausible person name, and NOT the company
                # name echoed back (Apollo sometimes returns the org as a "person").
                cn = re.sub(r"[^a-z]", "", by_sid[sid]["name"].lower())
                nn = re.sub(r"[^a-z]", "", name.lower())
                if not name or not _is_person(name) or (nn and (nn in cn or cn in nn)):
                    continue
                c.execute(
                    "UPDATE startups SET dm_name=?, dm_role=?, linkedin=?, email=?, company_linkedin=? WHERE sid=?",
                    (name, (best.get("title") or "")[:80], best.get("linkedin_url") or "",
                     best.get("email") or "", best.get("organization_linkedin_url") or "", sid))
                _state["with_person"] += 1
                person_done.add(sid)

        # ── Stage 3 (FREE): for verified companies Apollo couldn't name but that have
        #    a website, read the site with the LLM pool to get the founder + LinkedIn ──
        _state["stage"] = "website-llm"
        s3 = [(sid, by_sid[sid]["name"], v["website"]) for sid, v in verified.items()
              if sid not in person_done and v.get("website")]
        if s3:
            with ThreadPoolExecutor(max_workers=8) as ex:
                found = list(ex.map(lambda t: (t[0], _site_person(t[1], t[2])), s3))
            with warehouse._LOCK:
                for sid, res in found:
                    if not res:
                        continue
                    c.execute(
                        "UPDATE startups SET dm_name=?, dm_role=?, linkedin=COALESCE(NULLIF(?,''),linkedin) WHERE sid=?",
                        (res["name"], res.get("role") or "", res.get("linkedin") or "", sid))
                    _state["with_person"] += 1
                c.commit()

        with warehouse._LOCK:
            # mark everything we attempted
            for sid in by_sid:
                got = sid in verified
                c.execute("UPDATE startups SET contact_status=?, enriched_at=? WHERE sid=?",
                          ("enriched" if got else "no_data", now, sid))
            c.commit()

        _state["running"] = False
        return {"status": "ok", "total": len(targets), "with_phone": _state["with_phone"],
                "with_person": _state["with_person"], "cost_usd": _state["cost_usd"]}
    except Exception as e:
        _state.update(running=False, error=str(e))
        logger.warning(f"[startup_enrich] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _lock.release()


# ── Registry enrichment (Tofler/MCA via foxlabs/indian-company-data) ──────────
# The universal-coverage source: every one of these companies is MCA-registered,
# so directors (the relevant person) + registered email + address exist for ~100%.
_GENERIC_DIN_ROLE = ("director", "managing director", "whole-time director",
                     "additional director", "designated partner")


def reg_enrich_status() -> dict:
    return dict(_reg_state)


def _pick_director(directors: list) -> Optional[dict]:
    """Prefer Managing Director, then longest-tenure Director."""
    if not directors:
        return None
    def rank(d):
        desig = (d.get("designation") or "").lower()
        base = 90 if "managing" in desig else (70 if "director" in desig else 40)
        # tenure like "3 years"
        m = re.search(r"(\d+)", d.get("tenure") or "")
        return base + (int(m.group(1)) if m else 0)
    return max(directors, key=rank)


def enrich_registry(ncr=True, dpiit=True, stage="Scaling", limit=2000, batch=120) -> dict:
    """Fill directors (relevant person) + registered email + CIN + address for the
    filtered slice from the MCA/Tofler registry. ~100% coverage since all are
    registered companies. Does NOT clobber an existing Apollo/site person (which
    carries LinkedIn) — only fills when empty; always fills email/cin/address."""
    if not _reg_lock.acquire(blocking=False):
        return {"status": "busy", **reg_enrich_status()}
    token = (rc.get("apify_api_token") or "").strip()
    try:
        if not token:
            return {"status": "error", "message": "No apify_api_token"}
        from core import startup_india as si
        c = si._ensure()
        w, args = si._where("", "", "", False, ncr, dpiit, stage)
        with warehouse._LOCK:
            rows = c.execute(
                f"SELECT sid,name FROM startups{w} ORDER BY name LIMIT ?", args + [limit]).fetchall()
        targets = [dict(r) for r in rows]
        _reg_state.update(running=True, done=0, total=len(targets), with_director=0,
                          with_email=0, cost_usd=0.0, error="")
        logger.info(f"[reg_enrich] registry lookup for {len(targets)} companies")

        def norm(s):
            return re.sub(r"[^a-z0-9]", "", (s or "").lower())
        by_norm = {norm(t["name"]): t for t in targets}

        for i in range(0, len(targets), batch):
            chunk = targets[i:i + batch]
            names = [t["name"] for t in chunk]
            items, usd, status = _run_actor(_REGISTRY_ACTOR, {
                "companyNames": names, "maxResults": len(names), "maxConcurrency": 10},
                token, max_wait=1200)
            _reg_state["cost_usd"] = round(_reg_state["cost_usd"] + usd, 4)
            updates = []
            for it in items:
                if it.get("error") or not it.get("name"):
                    continue
                t = by_norm.get(norm(it.get("name")))
                if not t:
                    # fuzzy: match on the matched/input name token overlap
                    continue
                dirs = it.get("directors") or []
                best = _pick_director(dirs)
                updates.append((t["sid"], best, it))
            now = time.time()
            with warehouse._LOCK:
                for sid, best, it in updates:
                    dname = (best or {}).get("name") or ""
                    drole = (best or {}).get("designation") or ""
                    email = it.get("email") or ""
                    c.execute(
                        """UPDATE startups SET
                             dm_name = CASE WHEN (dm_name IS NULL OR dm_name='') THEN ? ELSE dm_name END,
                             dm_role = CASE WHEN (dm_role IS NULL OR dm_role='') THEN ? ELSE dm_role END,
                             reg_email=?, email = CASE WHEN (email IS NULL OR email='') THEN ? ELSE email END,
                             cin=?, reg_address=?, incorporation=?, directors_json=?,
                             contact_status = CASE WHEN contact_status='no_data' OR contact_status IS NULL OR contact_status='pending'
                                                   THEN 'registry' ELSE contact_status END,
                             enriched_at=?
                           WHERE sid=?""",
                        (dname, drole, email, email, it.get("cin") or "",
                         (it.get("registeredAddress") or "")[:300], it.get("incorporationDate") or "",
                         json.dumps(dirs)[:2000], now, sid))
                    if dname:
                        _reg_state["with_director"] += 1
                    if email:
                        _reg_state["with_email"] += 1
                c.commit()
            _reg_state["done"] = min(len(targets), i + len(chunk))

        _reg_state["running"] = False
        return {"status": "ok", "total": len(targets),
                "with_director": _reg_state["with_director"],
                "with_email": _reg_state["with_email"], "cost_usd": _reg_state["cost_usd"]}
    except Exception as e:
        _reg_state.update(running=False, error=str(e))
        logger.warning(f"[reg_enrich] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _reg_lock.release()


# ── Deep contact discovery (Google search → website + LinkedIn → site phone) ───
_GOOGLE_ACTOR = "apify~google-search-scraper"
_deep_lock = threading.Lock()
_deep_state = {"running": False, "done": 0, "total": 0, "with_phone": 0,
               "with_website": 0, "with_linkedin": 0, "cost_usd": 0.0, "error": ""}
_NOT_SITE = ("linkedin.", "tracxn.", "falconebiz.", "indiafilings.", "instafinancials.",
             "zaubacorp.", "tofler.", "justdial.", "indiamart.", "facebook.", "youtube.",
             "crunchbase.", "instagram.", "twitter.", "x.com", "thecompanycheck.",
             "zicom", "dnb.com", "google.", "wikipedia.", "sgpgrid.", "quickcompany.",
             "setindiabiz", "indiamace", "lbcorp", "mca.gov", "startupindia.gov",
             "ynos.in", "placementindia.", "surereach.", "naukri.", "glassdoor.",
             "ambitionbox.", "indeed.", "slintel.", "rocketreach.", "apollo.io",
             "6sense.", "leadiq.", "zoominfo.", "signalhire.", "thomasnet.",
             "exportersindia.", "tradeindia.", "sulekha.", "yellowpages.", "bizapedia.",
             "opencorporates.", "goodfirms.", "clutch.co", "f6s.", "startupindia.",
             "moneycontrol.", "economictimes.", "business-standard.", "yourstory.",
             "medium.", "blogspot.", "wordpress.com", "amazon.", "flipkart.")
_PHONE_RE = re.compile(r"(?:\+?91[\s\-]?)?\b[6-9]\d{4}[\s\-]?\d{5}\b")


def _domain_matches(company: str, domain: str) -> bool:
    """Accept a website only if its domain shares a real token with the company name —
    keeps us from banking a directory / wrong-company page, so the scraped phone stays
    accurate. Better to leave a field blank than fill it with the wrong company's data."""
    core = re.sub(r"^www\.", "", (domain or "").lower()).split(".")[0]
    coreflat = re.sub(r"[^a-z0-9]", "", core)
    toks = [t for t in re.sub(r"[^a-z0-9 ]", " ", (company or "").lower()).split()
            if t not in _LEGAL and len(t) > 2]
    if not toks or len(coreflat) < 3:
        return False
    if any(t in coreflat for t in toks):
        return True
    joined = "".join(toks)
    return coreflat in joined or (len(joined) >= 6 and joined[:8] in coreflat)


def deep_enrich_status() -> dict:
    return dict(_deep_state)


def _site_phone(url: str) -> str:
    import requests
    m = re.match(r"(https?://[^/]+)", url or "")
    if not m:
        return ""
    base = m.group(1)
    s = requests.Session(); s.headers["User-Agent"] = _UA
    for sub in ("", "contact", "contact-us", "about", "about-us"):
        try:
            r = s.get(base if not sub else f"{base}/{sub}", timeout=8)
            if r.status_code != 200:
                continue
            html = r.text
            # tel: links are the most reliable
            for tl in re.findall(r'tel:([+0-9\s\-]{8,18})', html):
                d = re.sub(r"\D", "", tl)[-10:]
                if len(d) == 10 and d[0] in "6789":
                    return d
            for hit in _PHONE_RE.findall(re.sub(r"<[^>]+>", " ", html)):
                d = re.sub(r"\D", "", hit)[-10:]
                if len(d) == 10 and d[0] in "6789":
                    return d
        except Exception:
            continue
    return ""


_CIN_RE = re.compile(r"[LUu]\d{5}[A-Za-z]{2}\d{4}[A-Za-z]{3}\d{6}")


def _parse_google(page: dict, company: str = "") -> dict:
    out = {"website": "", "linkedin": "", "company_linkedin": "", "cin": ""}
    # the CIN is embedded in directory result URLs/titles (zauba/tofler/indiafilings)
    m = _CIN_RE.search(json.dumps(page))
    if m:
        out["cin"] = m.group(0).upper()
    for r in (page.get("organicResults") or []):
        u = (r.get("url") or "")
        low = u.lower()
        if "linkedin.com/in/" in low and not out["linkedin"]:
            out["linkedin"] = u.split("?")[0]
        elif "linkedin.com/company/" in low and not out["company_linkedin"]:
            out["company_linkedin"] = u.split("?")[0]
        elif not out["website"] and not any(x in low for x in _NOT_SITE):
            host = re.sub(r"https?://", "", u).split("/")[0]
            # accuracy gate: only accept the site if its domain matches the company name
            if _domain_matches(company, host):
                out["website"] = u
    return out


def enrich_deep(ncr=True, dpiit=True, stage="Scaling", limit=2000, batch=20) -> dict:
    """Google-search each company → official website + LinkedIn; scrape the site's
    PUBLISHED phone (accurate). Fills only-empty fields. Additive to registry/Maps."""
    if not _deep_lock.acquire(blocking=False):
        return {"status": "busy", **deep_enrich_status()}
    token = (rc.get("apify_api_token") or "").strip()
    try:
        if not token:
            return {"status": "error", "message": "No apify_api_token"}
        from core import startup_india as si
        c = si._ensure()
        w, args = si._where("", "", "", False, ncr, dpiit, stage)
        with warehouse._LOCK:
            rows = c.execute(f"SELECT sid,name,city FROM startups{w} ORDER BY name LIMIT ?",
                             args + [limit]).fetchall()
        targets = [dict(r) for r in rows]
        _deep_state.update(running=True, done=0, total=len(targets), with_phone=0,
                           with_website=0, with_linkedin=0, cost_usd=0.0, error="")
        for i in range(0, len(targets), batch):
            chunk = targets[i:i + batch]
            queries = "\n".join(f'{t["name"]} {t["city"]}' for t in chunk)
            items, usd, status = _run_actor(_GOOGLE_ACTOR, {
                "queries": queries, "resultsPerPage": 5, "maxPagesPerQuery": 1,
                "countryCode": "in"}, token, max_wait=900)
            _deep_state["cost_usd"] = round(_deep_state["cost_usd"] + usd, 4)
            # map each result page back to its company by query term order
            term_to_name = {f'{t["name"]} {t["city"]}'.strip().lower(): t["name"] for t in chunk}
            parsed = {}
            for page in items:
                term = (page.get("searchQuery", {}) or {}).get("term", "").strip().lower()
                parsed[term] = _parse_google(page, term_to_name.get(term, ""))
            now = time.time()
            for t in chunk:
                key = f'{t["name"]} {t["city"]}'.strip().lower()
                info = parsed.get(key)
                if not info:
                    continue
                phone = _site_phone(info["website"]) if info["website"] else ""
                li = info["linkedin"] or info["company_linkedin"]
                with warehouse._LOCK:
                    c.execute(
                        """UPDATE startups SET
                             website = CASE WHEN (website IS NULL OR website='') THEN ? ELSE website END,
                             phone   = CASE WHEN (phone IS NULL OR phone='') THEN ? ELSE phone END,
                             linkedin= CASE WHEN (linkedin IS NULL OR linkedin='') THEN ? ELSE linkedin END,
                             company_linkedin = CASE WHEN (company_linkedin IS NULL OR company_linkedin='') THEN ? ELSE company_linkedin END,
                             cin = CASE WHEN (cin IS NULL OR cin='') THEN ? ELSE cin END
                           WHERE sid=?""",
                        (info["website"], phone, info["linkedin"], info["company_linkedin"],
                         info.get("cin", ""), t["sid"]))
                    c.commit()
                if info["website"]:
                    _deep_state["with_website"] += 1
                if phone:
                    _deep_state["with_phone"] += 1
                if li:
                    _deep_state["with_linkedin"] += 1
            _deep_state["done"] = min(len(targets), i + len(chunk))
        _deep_state["running"] = False
        return {"status": "ok", **deep_enrich_status()}
    except Exception as e:
        _deep_state.update(running=False, error=str(e))
        logger.warning(f"[deep_enrich] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _deep_lock.release()


# ── Registry-by-CIN (token-free director/email lookup; exact, no name-resolution) ─
def enrich_registry_by_cin(ncr=True, dpiit=True, stage="Scaling", limit=2000, batch=80) -> dict:
    """For companies that now have a CIN (from the deep/Google pass) but no director,
    look them up in the MCA/Tofler registry BY CIN (exact → no name-resolution failure)
    to fill director + registered email + address. Reuses _reg_state for status."""
    if not _reg_lock.acquire(blocking=False):
        return {"status": "busy", **reg_enrich_status()}
    token = (rc.get("apify_api_token") or "").strip()
    try:
        if not token:
            return {"status": "error", "message": "No apify_api_token"}
        from core import startup_india as si
        c = si._ensure()
        w, args = si._where("", "", "", False, ncr, dpiit, stage)
        cond = (w + " AND " if w else " WHERE ") + \
               "cin!='' AND cin IS NOT NULL AND (dm_name IS NULL OR dm_name='')"
        with warehouse._LOCK:
            rows = c.execute(f"SELECT sid,cin FROM startups{cond} LIMIT ?", args + [limit]).fetchall()
        targets = [dict(r) for r in rows]
        cin_to_sid = {r["cin"].upper(): r["sid"] for r in targets}
        _reg_state.update(running=True, done=0, total=len(targets), with_director=0,
                          with_email=0, cost_usd=0.0, error="")
        logger.info(f"[reg_cin] {len(targets)} companies with CIN to look up")
        cins = list(cin_to_sid.keys())
        for i in range(0, len(cins), batch):
            chunk = cins[i:i + batch]
            items, usd, status = _run_actor(_REGISTRY_ACTOR, {
                "cins": chunk, "maxResults": len(chunk), "maxConcurrency": 8}, token, max_wait=1200)
            _reg_state["cost_usd"] = round(_reg_state["cost_usd"] + usd, 4)
            now = time.time()
            with warehouse._LOCK:
                for it in items:
                    if it.get("error"):
                        continue
                    cin = (it.get("cin") or "").upper()
                    sid = cin_to_sid.get(cin)
                    if not sid:
                        continue
                    best = _pick_director(it.get("directors") or [])
                    dname = (best or {}).get("name") or ""
                    drole = (best or {}).get("designation") or ""
                    email = it.get("email") or ""
                    c.execute(
                        """UPDATE startups SET
                             dm_name = CASE WHEN (dm_name IS NULL OR dm_name='') THEN ? ELSE dm_name END,
                             dm_role = CASE WHEN (dm_role IS NULL OR dm_role='') THEN ? ELSE dm_role END,
                             reg_email=?, email = CASE WHEN (email IS NULL OR email='') THEN ? ELSE email END,
                             reg_address=?, incorporation=?, directors_json=?,
                             contact_status = CASE WHEN contact_status IN ('no_data','pending') OR contact_status IS NULL
                                                   THEN 'registry' ELSE contact_status END,
                             enriched_at=? WHERE sid=?""",
                        (dname, drole, email, email, (it.get("registeredAddress") or "")[:300],
                         it.get("incorporationDate") or "", json.dumps(it.get("directors") or [])[:2000],
                         now, sid))
                    if dname:
                        _reg_state["with_director"] += 1
                    if email:
                        _reg_state["with_email"] += 1
                c.commit()
            _reg_state["done"] = min(len(cins), i + len(chunk))
        _reg_state["running"] = False
        return {"status": "ok", "total": len(targets), "with_director": _reg_state["with_director"],
                "with_email": _reg_state["with_email"], "cost_usd": _reg_state["cost_usd"]}
    except Exception as e:
        _reg_state.update(running=False, error=str(e))
        logger.warning(f"[reg_cin] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _reg_lock.release()
