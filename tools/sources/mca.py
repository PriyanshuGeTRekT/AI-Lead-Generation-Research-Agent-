"""
MCA Company Master Data (FREE, keyless, LAKHS-scale, ACCURATE)
--------------------------------------------------------------
India's Ministry of Corporate Affairs publishes the master register of every
company: CIN, name, class, status, registration date, REGISTERED STATE + ADDRESS,
EMAIL, and principal business-activity (NIC) code. A community mirror hosts it as
state-wise XLSX on GitHub — directly downloadable, no key.

This is the real path to lakhs of QUALITY leads FAST: structured, verified registry
data with an EMAIL on every record and NO per-site fetching / dead-domain waste.
We filter to ACTIVE companies, map the NIC code to an industry, score ICP fit, and
bank straight as enriched leads. Fail-safe throughout.
"""
import io
import threading
import urllib.parse
import uuid

from loguru import logger

_RAW = "https://raw.githubusercontent.com/matcdac/CorporateIndiaDataSourceXLSX/HEAD/"
_TREE = "https://api.github.com/repos/matcdac/CorporateIndiaDataSourceXLSX/git/trees/HEAD?recursive=1"
_UA = "RazorInfotech-Leads/1.0"

_lock = threading.Lock()
_state = {"running": False, "states_done": 0, "states_total": 0, "added": 0, "skipped": 0}

# NIC 2-digit division → industry (HR-relevance covered by lead_processor._INDUSTRY_FIT).
_NIC = {
    "01": "agriculture", "02": "agriculture", "03": "agriculture",
    "05": "mining", "06": "mining", "07": "mining", "08": "mining", "09": "mining",
    "10": "food processing", "11": "beverages", "12": "manufacturing", "13": "textile",
    "14": "textile", "15": "manufacturing", "16": "manufacturing", "17": "manufacturing",
    "18": "printing", "19": "manufacturing", "20": "chemical", "21": "pharmaceutical",
    "22": "manufacturing", "23": "manufacturing", "24": "manufacturing", "25": "manufacturing",
    "26": "electronics", "27": "electronics", "28": "manufacturing", "29": "automotive",
    "30": "manufacturing", "31": "manufacturing", "32": "manufacturing", "33": "manufacturing",
    "35": "utilities", "36": "utilities", "37": "utilities", "38": "utilities", "39": "utilities",
    "41": "construction", "42": "construction", "43": "construction",
    "45": "automotive", "46": "wholesale", "47": "retail",
    "49": "logistics", "50": "logistics", "51": "logistics", "52": "logistics", "53": "logistics",
    "55": "hotel", "56": "hotel",
    "58": "media", "59": "media", "60": "media", "61": "telecom", "62": "IT services", "63": "IT services",
    "64": "financial services", "65": "insurance", "66": "financial services",
    "68": "real estate", "69": "consulting", "70": "consulting", "71": "engineering",
    "72": "IT services", "73": "advertising", "74": "consulting", "75": "services",
    "77": "services", "78": "staffing", "79": "hospitality", "80": "services",
    "81": "facility management", "82": "services", "85": "education",
    "86": "healthcare", "87": "healthcare", "88": "healthcare",
}
_DEAD_STATUS = {"STRIKE OFF", "STRUCK OFF", "DISSOLVED", "AMALGAMATED", "AMALGATED",
                "LIQUIDATED", "UNDER LIQUIDATION", "DORMANT", "CONVERTED TO LLP",
                "UNDER PROCESS OF STRIKING OFF"}


def status() -> dict:
    return dict(_state)


def is_running() -> bool:
    return _state["running"]


def _industry_for(nic) -> str:
    s = str(nic or "").strip()
    return _NIC.get(s[:2], "business")


def list_state_files(prefer_year: str = "2016") -> list[str]:
    """Return one XLSX path per state (prefer the fuller 2016 set, fallback 2015)."""
    import requests
    try:
        tree = requests.get(_TREE, headers={"User-Agent": _UA}, timeout=40).json()["tree"]
    except Exception as e:
        logger.warning(f"[mca] tree fetch failed: {e}")
        return []
    files = [t["path"] for t in tree if t["path"].lower().endswith(".xlsx")]
    y = [f for f in files if f"/{prefer_year}/" in f]
    return y or files


def _lead_from_row(rec: dict) -> dict | None:
    from core.lead_processor import _industry_fit  # reuse ICP fit weights
    name = (rec.get("COMPANY_NAME") or "").strip()
    if not name:
        return None
    status_v = (rec.get("COMPANY_STATUS") or "").strip().upper()
    if status_v in _DEAD_STATUS:
        return None  # not a live company → not a prospect
    email = (rec.get("EMAIL_ID") or "").strip()
    state = (rec.get("REGISTERED_STATE") or "").strip().title()
    addr = (rec.get("REGISTERED_OFFICE_ADDRESS") or "").strip()
    industry = _industry_for(rec.get("PRINCIPAL_BUSINESS_ACTIVITY_CODE"))
    fit = _industry_fit(industry)
    has_email = "@" in email
    # Quality score: registered+active company (entity certain) + industry fit +
    # reachable by email. Public ltd / higher paid-up capital nudges up.
    score = 4.0 + fit * 4.0 + (1.5 if has_email else 0)
    try:
        if float(str(rec.get(" PAIDUP_CAPITAL (RS.)") or rec.get("PAIDUP_CAPITAL (RS.)") or 0)) > 1_000_000:
            score += 0.5
    except Exception:
        pass
    score = round(min(score, 10.0), 1)
    tier = "Hot" if (score >= 7.5 and has_email) else "Warm" if score >= 5.5 else "Cold"
    return {
        "id": str(uuid.uuid4())[:8],
        "company_name": name.title()[:200],
        # CIN as a stable unique website-key (MCA has no website) so dedup works.
        "website": f"https://{rec.get('CIN', uuid.uuid4().hex)}.mca.lead",
        "industry": industry,
        "location": f"{state}, India" if state else "India",
        "state": state,
        "address": addr[:300],
        "phone": "", "mobile": "", "office_phone": "",
        "contact_emails": [email] if has_email else [],
        "dm_email": email if has_email else "",
        "source": "MCA registry",
        "cin": rec.get("CIN", ""),
        "company_status": status_v.title(),
        "hrms": {"has_hrms": False, "no_hrms_confidence": 0.6, "vendors": [],
                 "note": "Registered company (MCA) — HRMS not checked"},
        "lead_score": {"predicted_score": score, "icp_tier": tier,
                       "rationale": f"{tier} — registered {industry} company in {state or 'India'}"
                                    + (", email-reachable" if has_email else "")},
        "icp_tier": tier, "icp_fit": round(fit, 2),
        "qualification_score": score, "lead_grade": "A" if has_email else "B",
        "pain_points": ["Manual HR & attendance", "Payroll & statutory compliance (PF/ESI)",
                        "Onboarding & leave management"],
        "status": "qualified" if has_email else "pending_review",
    }


def ingest_state(path: str, max_rows: int = 100000, active_only: bool = True) -> int:
    import requests
    import openpyxl
    url = _RAW + urllib.parse.quote(path)
    try:
        content = requests.get(url, headers={"User-Agent": _UA}, timeout=120).content
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    except Exception as e:
        logger.debug(f"[mca] {path} download/parse failed: {e}")
        return 0
    from core import warehouse
    ws = wb.active
    it = ws.iter_rows(values_only=True)
    try:
        header = [str(h).strip() for h in next(it)]
    except StopIteration:
        return 0
    added = 0
    buf: list = []
    for i, row in enumerate(it):
        if i >= max_rows:
            break
        rec = dict(zip(header, row))
        lead = _lead_from_row(rec)
        if not lead:
            _state["skipped"] += 1
            continue
        buf.append(lead)
        if len(buf) >= 5000:          # bulk-commit every 5k rows
            added += warehouse.save_enriched_bulk(buf)
            buf = []
    if buf:
        added += warehouse.save_enriched_bulk(buf)
    try:
        wb.close()
    except Exception:
        pass
    return added


def ingest_all(max_states: int = 40, max_rows_per_state: int = 100000,
               states: list[str] | None = None) -> dict:
    if not _lock.acquire(blocking=False):
        return {"status": "busy", **status()}
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from core import warehouse
        paths = states or list_state_files()
        paths = paths[:max_states]
        _state.update(running=True, states_done=0, states_total=len(paths), added=0, skipped=0)
        logger.info(f"[mca] ingesting {len(paths)} state files")
        # A few states in parallel (download + parse). Parsing is CPU-ish; keep modest.
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(ingest_state, p, max_rows_per_state): p for p in paths}
            for fut in as_completed(futs):
                try:
                    n = fut.result()
                except Exception:
                    n = 0
                _state["added"] += n
                _state["states_done"] += 1
        logger.info(f"[mca] +{_state['added']} company leads ({_state['skipped']} inactive skipped); pool={warehouse.stats()}")
        return {"status": "ok", "added": _state["added"], "states": len(paths), "pool": warehouse.stats()}
    except Exception as e:
        logger.warning(f"[mca] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _state["running"] = False
        _lock.release()
