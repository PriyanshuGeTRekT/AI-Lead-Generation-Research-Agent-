"""
OpenStreetMap / Overpass source (FREE, keyless, HIGH VOLUME)
------------------------------------------------------------
OSM holds millions of real businesses — offices, factories, wholesalers, shops,
craft/industrial units — many tagged with name + website + phone + address. The
Overpass API is free and needs no key, so this is the volume engine for real
Indian company leads at zero cost.

Unlike web-search sources, OSM data is already structured: name, website, phone,
city and a business-type tag all arrive together — so these can be banked as
*enriched* leads directly, no scraping/LLM needed.

Returns candidate dicts {url, title, location, phone, industry, source}. Fail-safe.
"""
import re
from typing import Optional

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore

from loguru import logger

_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
_UA = "RazorInfotech-Leads/1.0 (razorinfotechpvtltd@gmail.com)"

# Approx bounding boxes (south,west,north,east) for the India SME belt cities.
CITY_BBOX = {
    "Mumbai": "18.89,72.77,19.30,72.99", "Delhi": "28.40,76.84,28.88,77.35",
    "Bengaluru": "12.83,77.46,13.14,77.78", "Hyderabad": "17.27,78.30,17.56,78.61",
    "Chennai": "12.90,80.13,13.15,80.32", "Pune": "18.44,73.74,18.64,73.96",
    "Kolkata": "22.46,88.27,22.63,88.43", "Ahmedabad": "22.95,72.49,23.13,72.70",
    "Noida": "28.49,77.30,28.63,77.45", "Gurugram": "28.38,76.96,28.51,77.12",
    "Jaipur": "26.80,75.70,26.98,75.88", "Indore": "22.66,75.78,22.79,75.93",
    "Coimbatore": "10.95,76.92,11.08,77.05", "Surat": "21.13,72.75,21.25,72.90",
    "Nagpur": "21.09,79.03,21.20,79.15", "Lucknow": "26.78,80.86,26.93,81.03",
    "Chandigarh": "30.69,76.72,30.79,76.83", "Kochi": "9.90,76.24,10.05,76.36",
    "Vadodara": "22.26,73.13,22.36,73.24", "Nashik": "19.93,73.71,20.05,73.83",
    "Rajkot": "22.25,70.74,22.34,70.85", "Ludhiana": "30.86,75.78,30.95,75.91",
    "Bhopal": "23.18,77.36,23.31,77.49", "Visakhapatnam": "17.66,83.18,17.78,83.32",
    "Faridabad": "28.35,77.27,28.47,77.36", "Thane": "19.17,72.94,19.27,73.04",
    "Vijayawada": "16.46,80.58,16.55,80.70", "Madurai": "9.88,78.08,9.97,78.18",
    "Bhubaneswar": "20.23,85.77,20.34,85.88", "Mysuru": "12.27,76.60,12.36,76.70",
    # Tier-2/3 expansion for volume.
    "Kanpur": "26.40,80.25,26.52,80.40", "Patna": "25.56,85.07,25.65,85.22",
    "Agra": "27.12,77.96,27.24,78.07", "Varanasi": "25.27,82.95,25.36,83.04",
    "Meerut": "28.95,77.66,29.04,77.76", "Amritsar": "31.59,74.84,31.68,74.93",
    "Jalandhar": "31.29,75.54,31.37,75.63", "Aurangabad": "19.84,75.28,19.93,75.39",
    "Solapur": "17.62,75.86,17.71,75.96", "Hubli": "15.32,75.10,15.39,75.18",
    "Mangaluru": "12.83,74.81,12.92,74.89", "Thiruvananthapuram": "8.46,76.91,8.56,77.00",
    "Kozhikode": "11.21,75.76,11.30,75.84", "Tiruchirappalli": "10.77,78.66,10.85,78.75",
    "Guntur": "16.27,80.40,16.35,80.49", "Guwahati": "26.10,91.68,26.20,91.84",
    "Ranchi": "23.33,85.27,23.42,85.36", "Jamshedpur": "22.76,86.16,22.84,86.25",
    "Raipur": "21.21,81.59,21.29,81.69", "Jodhpur": "26.24,72.97,26.33,73.06",
    "Kota": "25.14,75.81,25.22,75.90", "Gwalior": "26.18,78.13,26.27,78.22",
    "Jabalpur": "23.13,79.90,23.21,79.98", "Dehradun": "30.29,77.96,30.37,78.07",
    "Udaipur": "24.55,73.66,24.62,73.74", "Nellore": "14.41,79.94,14.48,80.02",
    "Bareilly": "28.32,79.38,28.40,79.46", "Moradabad": "28.81,78.72,28.89,78.81",
    "Salem": "11.62,78.11,11.70,78.20", "Warangal": "17.94,79.55,18.02,79.63",
}

# Many more Indian cities/towns by CENTER (lat, lon) → bbox generated below. This is
# the productive path to volume: city cores are dense with real companies (unlike
# the ocean/rural tiles a blind grid wastes time on).
CITY_COORDS = {
    "Prayagraj": (25.44, 81.85), "Ghaziabad": (28.67, 77.45), "Aligarh": (27.88, 78.08),
    "Gorakhpur": (26.76, 83.37), "Saharanpur": (29.97, 77.55), "Jhansi": (25.45, 78.58),
    "Muzaffarnagar": (29.47, 77.70), "Mathura": (27.49, 77.67), "Firozabad": (27.16, 78.40),
    "Jamnagar": (22.47, 70.07), "Bhavnagar": (21.76, 72.15), "Junagadh": (21.52, 70.46),
    "Gandhinagar": (23.22, 72.65), "Anand": (22.56, 72.96), "Bhuj": (23.25, 69.67),
    "Bhilai": (21.21, 81.38), "Bilaspur": (22.08, 82.15), "Durg": (21.19, 81.28),
    "Korba": (22.35, 82.69), "Siliguri": (26.73, 88.40), "Durgapur": (23.52, 87.31),
    "Asansol": (23.68, 86.97), "Kharagpur": (22.34, 87.32), "Cuttack": (20.46, 85.88),
    "Rourkela": (22.26, 84.85), "Berhampur": (19.31, 84.79), "Sambalpur": (21.47, 83.97),
    "Dhanbad": (23.80, 86.43), "Bokaro": (23.67, 86.15), "Gaya": (24.80, 85.00),
    "Bhagalpur": (25.24, 86.99), "Muzaffarpur": (26.12, 85.39), "Darbhanga": (26.15, 85.90),
    "Dibrugarh": (27.47, 94.91), "Silchar": (24.83, 92.78), "Shillong": (25.58, 91.89),
    "Imphal": (24.82, 93.94), "Agartala": (23.83, 91.28), "Jammu": (32.73, 74.87),
    "Srinagar": (34.08, 74.80), "Shimla": (31.10, 77.17), "Ambala": (30.38, 76.78),
    "Karnal": (29.69, 76.99), "Panipat": (29.39, 76.97), "Hisar": (29.15, 75.72),
    "Rohtak": (28.90, 76.61), "Sonipat": (28.99, 77.02), "Bathinda": (30.21, 74.95),
    "Patiala": (30.34, 76.39), "Mohali": (30.70, 76.72), "Bikaner": (28.02, 73.31),
    "Ajmer": (26.45, 74.64), "Bhilwara": (25.35, 74.64), "Alwar": (27.55, 76.63),
    "Sikar": (27.61, 75.14), "Ujjain": (23.18, 75.78), "Sagar": (23.84, 78.74),
    "Ratlam": (23.33, 75.04), "Dewas": (22.96, 76.06), "Satna": (24.58, 80.83),
    "Rewa": (24.53, 81.30), "Nanded": (19.15, 77.31), "Akola": (20.70, 77.00),
    "Amravati": (20.93, 77.78), "Kolhapur": (16.70, 74.24), "Sangli": (16.85, 74.58),
    "Latur": (18.40, 76.58), "Ahmednagar": (19.09, 74.74), "Jalgaon": (21.01, 75.56),
    "Chandrapur": (19.95, 79.30), "Belagavi": (15.85, 74.50), "Davangere": (14.47, 75.92),
    "Ballari": (15.14, 76.92), "Tumakuru": (13.34, 77.10), "Shivamogga": (13.93, 75.57),
    "Vijayapura": (16.83, 75.71), "Kalaburagi": (17.33, 76.83), "Udupi": (13.34, 74.75),
    "Hassan": (13.00, 76.10), "Tirupati": (13.63, 79.42), "Rajahmundry": (17.00, 81.78),
    "Kakinada": (16.99, 82.25), "Kurnool": (15.83, 78.04), "Anantapur": (14.68, 77.60),
    "Kadapa": (14.47, 78.82), "Eluru": (16.71, 81.10), "Ongole": (15.50, 80.05),
    "Tirunelveli": (8.71, 77.76), "Tiruppur": (11.11, 77.34), "Erode": (11.34, 77.72),
    "Vellore": (12.92, 79.13), "Thoothukudi": (8.76, 78.13), "Thanjavur": (10.79, 79.14),
    "Dindigul": (10.36, 77.98), "Nagercoil": (8.18, 77.43), "Thrissur": (10.52, 76.21),
    "Kollam": (8.89, 76.61), "Kannur": (11.87, 75.37), "Kottayam": (9.59, 76.52),
    "Palakkad": (10.79, 76.65), "Alappuzha": (9.49, 76.34), "Malappuram": (11.07, 76.07),
    "Bareilly2": (28.36, 79.41), "Gulbarga2": (17.33, 76.83), "Panvel": (18.99, 73.12),
    "Vasai": (19.39, 72.83), "Kalyan": (19.24, 73.13), "Navi Mumbai": (19.03, 73.03),
    "Pimpri": (18.63, 73.80), "Secunderabad": (17.44, 78.50), "Howrah": (22.59, 88.31),
}


def _coords_to_bbox(lat: float, lon: float, d: float = 0.11) -> str:
    return f"{lat - d:.2f},{lon - d:.2f},{lat + d:.2f},{lon + d:.2f}"


# Merge generated bboxes for every coord-listed city not already covered.
for _city, (_lat, _lon) in CITY_COORDS.items():
    CITY_BBOX.setdefault(_city, _coords_to_bbox(_lat, _lon))

# OSM tag → readable industry label.
_TAG_INDUSTRY = {
    "office": "services", "company": "services", "it": "IT services",
    "consulting": "consulting", "lawyer": "law firm", "accountant": "accounting",
    "insurance": "insurance", "financial": "financial services",
    "logistics": "logistics", "estate_agent": "real estate", "advertising_agency": "advertising",
    "employment_agency": "staffing", "educational_institution": "education",
}


_AMENITY_INDUSTRY = {
    "hospital": "hospital", "clinic": "healthcare", "pharmacy": "pharmacy chain",
    "college": "education", "university": "education", "bank": "banking",
}


def _industry_for(tags: dict) -> str:
    if tags.get("healthcare"):
        return "healthcare"
    am = tags.get("amenity")
    if am in _AMENITY_INDUSTRY:
        return _AMENITY_INDUSTRY[am]
    if tags.get("tourism") == "hotel":
        return "hotel"
    if tags.get("man_made") == "works" or tags.get("industrial"):
        return "manufacturing"
    for key in ("industrial", "craft", "office", "shop"):
        v = tags.get(key)
        if v and v not in ("yes", "no"):
            return _TAG_INDUSTRY.get(v, v.replace("_", " "))
    if tags.get("office"):
        return _TAG_INDUSTRY.get(tags.get("office"), "services")
    if tags.get("craft"):
        return "manufacturing"
    return "business"


def _bbox_for(region: Optional[str]) -> Optional[str]:
    if not region:
        return None
    for city, bb in CITY_BBOX.items():
        if city.lower() in region.lower() or region.lower() in city.lower():
            return bb
    return None


# HR-relevant business categories — companies that actually employ people & buy
# HRMS (offices, factories, hospitals, hotels, colleges…), NOT lone retail shops.
def _bbox_query(bbox: str, cap: int, timeout: int = 50) -> str:
    return f"""[out:json][timeout:{timeout}];
(
  node["office"]["name"]({bbox});
  way["office"]["name"]({bbox});
  node["industrial"]["name"]({bbox});
  way["industrial"]["name"]({bbox});
  node["craft"]["name"]({bbox});
  way["craft"]["name"]({bbox});
  node["shop"~"wholesale|trade|car_repair|hardware|electronics|medical_supply|furniture"]["name"]({bbox});
  node["healthcare"]["name"]({bbox});
  way["healthcare"]["name"]({bbox});
  node["amenity"~"hospital|clinic|college|university|pharmacy"]["name"]({bbox});
  way["amenity"~"hospital|college|university"]["name"]({bbox});
  node["tourism"="hotel"]["name"]({bbox});
  way["tourism"="hotel"]["name"]({bbox});
  node["man_made"="works"]["name"]({bbox});
  way["man_made"="works"]["name"]({bbox});
);
out tags {cap};"""


def _run_query(bbox: str, region: str, cap: int, timeout: int = 50) -> list[dict]:
    if requests is None:
        return []
    q = _bbox_query(bbox, max(1, min(cap, 2000)), timeout=timeout)
    for ep in _ENDPOINTS:
        try:
            r = requests.post(ep, data={"data": q}, headers={"User-Agent": _UA}, timeout=timeout + 8)
            if r.status_code != 200:
                continue
            return _normalize(r.json().get("elements", []), region)
        except Exception as e:
            logger.debug(f"[overpass] {ep} failed: {e}")
            continue
    return []


def harvest_city(region: str, limit: int = 400) -> list[dict]:
    """Pull named businesses (office/industrial/craft/wholesale) in a city bbox."""
    bbox = _bbox_for(region)
    if not bbox:
        return []
    return _run_query(bbox, region, limit)


# Office sub-types that aren't HRMS sales targets (embassies, govt, NGOs, religion…).
_SKIP_OFFICE = {"government", "diplomatic", "ngo", "association", "political_party",
                "religion", "quango", "administrative", "register"}

# Retail-bank / ATM chains are POOR HRMS leads: they already run enterprise HRMS,
# and each is a branch (not a decision-making HQ). Drop them by name so a metro
# harvest isn't dominated by ICICI/HDFC/Axis branches.
_BANK_CHAINS = (
    "icici", "hdfc", "axis bank", "state bank", "sbi", "kotak", "punjab national",
    " pnb", "bank of baroda", "canara bank", "union bank", "yes bank", "idfc",
    "indusind", "federal bank", "bandhan bank", "rbl bank", "au small finance",
    "atm", "bank of india", "central bank of india", "indian bank", "uco bank",
)


def _normalize(elements: list[dict], region: str) -> list[dict]:
    out = []
    for e in elements:
        t = e.get("tags", {}) or {}
        if t.get("office") in _SKIP_OFFICE or t.get("government") or t.get("diplomatic"):
            continue  # not a commercial lead
        if t.get("amenity") in ("bank", "atm"):
            continue  # retail bank branch / ATM — already has HRMS, not a target
        name = t.get("name") or t.get("operator") or ""
        if not name or len(name) < 2:
            continue
        nlow = name.lower()
        if any(b in nlow for b in _BANK_CHAINS):
            continue  # bank-chain branch slipping through via office/other tags
        website = (t.get("website") or t.get("contact:website")
                   or t.get("url") or "").strip()
        phone = (t.get("phone") or t.get("contact:phone") or t.get("mobile") or "").strip()
        # Need a website (clean domain dedup + enrichable) OR a phone (directly
        # actionable). Skip anonymous map dots.
        if not website and not phone:
            continue
        if website and not website.startswith(("http://", "https://")):
            website = "https://" + website
        # Prefer the business's OWN address tags for an accurate location.
        city = (t.get("addr:city") or t.get("addr:town") or t.get("addr:suburb") or "").strip()
        st = (t.get("addr:state") or "").strip()
        if city and st:
            loc = f"{city}, {st}"
        elif city:
            loc = f"{city}, India"
        elif st:
            loc = f"{st}, India"
        else:
            loc = (region + ", India") if region else "India"
        out.append({
            "url": website,
            "title": name[:200],
            "location": loc,
            "phone": phone,
            "industry": _industry_for(t),
            "source": "osm",
        })
    return out


# Generic source interface (used by web_search.search_companies_multi_source).
def search_companies(keyword: str, region: Optional[str] = None, max_results: int = 50) -> list[dict]:
    if not region:
        return []
    res = harvest_city(region, limit=max_results * 4)
    return res[:max_results]


# ── Bulk harvest → bank directly as enriched leads ────────────────────────────
import threading
import uuid

_osm_lock = threading.Lock()
_osm_state = {"running": False, "cities_done": 0, "cities_total": 0, "added": 0}


def osm_status() -> dict:
    return dict(_osm_state)


def osm_running() -> bool:
    return _osm_state["running"]


def _synthetic_key(lead: dict) -> str:
    """A UNIQUE dedup URL for a phone-only lead (no real website). Keyed by phone so
    the same business dedups across harvests, but distinct businesses stay separate.
    Uses a subdomain (not a path) because warehouse dedup is by host."""
    ph = re.sub(r"\D", "", lead.get("phone") or "")
    tag = ("p" + ph) if ph else lead.get("id", "x")
    return f"https://{tag}.osm.lead"


def _to_lead(c: dict) -> dict:
    """Build a ready-to-show enriched lead from an OSM business candidate."""
    from tools.contact_resolver import _normalize_phone
    phone = ""
    norm = _normalize_phone(c.get("phone", ""), trusted=True)  # OSM phone tags are curated
    if norm:
        phone = norm["number"]
    has_web, has_phone = bool(c.get("url")), bool(phone)
    # Simple deterministic score: real OSM business is a solid lead; reward contactability.
    score = 5.0 + (1.5 if has_web else 0) + (1.5 if has_phone else 0)
    lead = {
        "id": str(uuid.uuid4())[:8],
        "company_name": c.get("title", ""),
        "website": c.get("url", ""),
        "industry": c.get("industry", "business"),
        "location": c.get("location", "India"),
        "phone": phone,
        "phone_type": norm["type"] if norm else None,
        "phone_source": "osm" if phone else None,
        "contact_emails": [],
        "source": "OpenStreetMap",
        "hrms": {"has_hrms": False, "no_hrms_confidence": 0.5, "vendors": [],
                 "note": "HRMS not yet checked (OSM-sourced)"},
        "lead_score": {"predicted_score": round(score, 1),
                       "rationale": "Verified business (OpenStreetMap) in target geo."},
        "qualification_score": round(score, 1),
        # Both website + phone → strong, ready to contact; else still a real lead.
        "status": "qualified" if (has_web and has_phone) else "enriched",
        "outreach_draft": None,
    }
    # Apply the ICP quality model (mobile-first, state, Hot/Warm/Cold tier) so every
    # harvested lead is graded the moment it lands.
    try:
        from core.lead_processor import process_lead
        lead = process_lead(lead)
    except Exception:
        pass
    return lead


def harvest_all_to_warehouse(per_city: int = 300, cities: Optional[list[str]] = None) -> dict:
    """Loop every city, pull OSM businesses, bank them as enriched leads. Returns summary."""
    if not _osm_lock.acquire(blocking=False):
        return {"status": "busy", **osm_status()}
    try:
        from core import warehouse
        from concurrent.futures import ThreadPoolExecutor, as_completed
        targets = cities or list(CITY_BBOX.keys())
        _osm_state.update(running=True, cities_done=0, cities_total=len(targets), added=0)
        # Query cities concurrently (4 workers) — Overpass I/O dominates.
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(harvest_city, city, per_city): city for city in targets}
            for fut in as_completed(futs):
                city = futs[fut]
                try:
                    businesses = fut.result()
                except Exception as e:
                    logger.debug(f"[osm] {city} failed: {e}")
                    businesses = []
                for c in businesses:
                    lead = _to_lead(c)
                    if not (lead["website"] or lead["phone"]):
                        continue
                    if not lead["website"]:
                        lead["website"] = _synthetic_key(lead)
                    try:
                        warehouse.save_enriched(lead, region=city)
                        _osm_state["added"] += 1
                    except Exception:
                        pass
                _osm_state["cities_done"] += 1
        logger.info(f"[osm] harvested {_osm_state['added']} leads across {len(targets)} cities")
        return {"status": "ok", "added": _osm_state["added"], "cities": len(targets),
                "pool": warehouse.stats()}
    except Exception as e:
        logger.warning(f"[osm] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _osm_state["running"] = False
        _osm_lock.release()


# ── GRID SWEEP — tile India and harvest every populated cell (lakhs of leads) ──
import json as _json
import os as _os
from pathlib import Path as _Path

# India mainland bbox (skips far ocean). south, west, north, east.
INDIA_BBOX = (8.0, 68.0, 35.5, 97.5)
_GRID_CURSOR = _Path(_os.getenv("GRID_CURSOR_PATH", "./data/grid_cursor.json"))
_grid_lock = threading.Lock()
_grid_state = {"running": False, "tiles_done": 0, "tiles_total": 0, "added": 0, "empty": 0}


def grid_status() -> dict:
    return dict(_grid_state)


def grid_running() -> bool:
    return _grid_state["running"]


def _tiles(step: float = 0.6) -> list[str]:
    """All bbox tiles covering India at `step` degrees (~66km at 0.6°)."""
    s, w, n, e = INDIA_BBOX
    out = []
    lat = s
    while lat < n:
        lon = w
        while lon < e:
            out.append(f"{lat:.2f},{lon:.2f},{min(lat + step, n):.2f},{min(lon + step, e):.2f}")
            lon += step
        lat += step
    return out


def _load_grid_cursor() -> int:
    try:
        return int(_json.loads(_GRID_CURSOR.read_text()).get("pos", 0))
    except Exception:
        return 0


def _save_grid_cursor(pos: int) -> None:
    try:
        _GRID_CURSOR.parent.mkdir(parents=True, exist_ok=True)
        _GRID_CURSOR.write_text(_json.dumps({"pos": pos}))
    except Exception:
        pass


def harvest_grid(max_tiles: int = 120, per_tile: int = 800, step: float = 0.6) -> dict:
    """Sweep India tile-by-tile (cursor-persisted) harvesting HR-relevant businesses
    straight into the warehouse as leads. Designed to run repeatedly until India is
    fully covered — the path to lakhs of leads. Empty (ocean/rural) tiles are cheap."""
    if not _grid_lock.acquire(blocking=False):
        return {"status": "busy", **grid_status()}
    try:
        from core import warehouse
        tiles = _tiles(step)
        start = _load_grid_cursor() % len(tiles)
        batch = [tiles[(start + i) % len(tiles)] for i in range(min(max_tiles, len(tiles)))]
        _save_grid_cursor((start + len(batch)) % len(tiles))
        _grid_state.update(running=True, tiles_done=0, tiles_total=len(batch), added=0, empty=0)
        logger.info(f"[grid] sweeping {len(batch)} tiles from {start}/{len(tiles)}")
        from concurrent.futures import ThreadPoolExecutor, as_completed
        # Concurrent tiles (4 workers) with a short per-tile timeout so a slow metro
        # tile can never block the sweep. Bank results as each tile returns.
        with ThreadPoolExecutor(max_workers=4) as ex:
            futs = {ex.submit(_run_query, bbox, "", per_tile, 45): bbox for bbox in batch}
            for fut in as_completed(futs):
                try:
                    businesses = fut.result()
                except Exception:
                    businesses = []
                if not businesses:
                    _grid_state["empty"] += 1
                for c in businesses:
                    lead = _to_lead(c)
                    if not (lead["website"] or lead["phone"]):
                        continue
                    if not lead["website"]:
                        lead["website"] = _synthetic_key(lead)
                    try:
                        warehouse.save_enriched(lead, region=(c.get("location") or "").split(",")[0])
                        _grid_state["added"] += 1
                    except Exception:
                        pass
                _grid_state["tiles_done"] += 1
        stats = warehouse.stats()
        logger.info(f"[grid] +{_grid_state['added']} leads ({_grid_state['empty']} empty tiles); pool={stats}")
        return {"status": "ok", "added": _grid_state["added"], "tiles": len(batch),
                "cursor": f"{start}/{len(tiles)}", "pool": stats}
    except Exception as e:
        logger.warning(f"[grid] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _grid_state["running"] = False
        _grid_lock.release()
