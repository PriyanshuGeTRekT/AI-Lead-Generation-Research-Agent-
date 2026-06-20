"""
Lead Processor
--------------
Turns harvested business *data* into pitch-ready *leads*:

  • MOBILE-FIRST contact: a landline reaches a front desk, not the buyer. The
    decision-maker's mobile is the only number worth dialing, so the mobile becomes
    the primary `phone`; any landline/toll-free is demoted to `office_phone`.
    Leads with no mobile get a website-scrape fallback to find one.
  • STATE: derived from the city so leads are filterable by state.
  • GRADE (A/B/C) + pain points: prioritises who to pitch first.

All deterministic + fail-safe. Heavy network work (mobile fallback scrape) is a
separate, bounded background pass.
"""
import re
import threading
from typing import Optional

from loguru import logger

# City → state (India SME belt covered by the OSM harvester).
CITY_STATE = {
    "Mumbai": "Maharashtra", "Pune": "Maharashtra", "Nagpur": "Maharashtra",
    "Nashik": "Maharashtra", "Thane": "Maharashtra", "Aurangabad": "Maharashtra",
    "Solapur": "Maharashtra", "Delhi": "Delhi", "Bengaluru": "Karnataka",
    "Mysuru": "Karnataka", "Hubli": "Karnataka", "Mangaluru": "Karnataka",
    "Hyderabad": "Telangana", "Warangal": "Telangana", "Chennai": "Tamil Nadu",
    "Coimbatore": "Tamil Nadu", "Madurai": "Tamil Nadu", "Tiruchirappalli": "Tamil Nadu",
    "Salem": "Tamil Nadu", "Kolkata": "West Bengal", "Ahmedabad": "Gujarat",
    "Surat": "Gujarat", "Vadodara": "Gujarat", "Rajkot": "Gujarat",
    "Noida": "Uttar Pradesh", "Lucknow": "Uttar Pradesh", "Kanpur": "Uttar Pradesh",
    "Agra": "Uttar Pradesh", "Varanasi": "Uttar Pradesh", "Meerut": "Uttar Pradesh",
    "Bareilly": "Uttar Pradesh", "Moradabad": "Uttar Pradesh", "Gurugram": "Haryana",
    "Faridabad": "Haryana", "Jaipur": "Rajasthan", "Jodhpur": "Rajasthan",
    "Kota": "Rajasthan", "Udaipur": "Rajasthan", "Indore": "Madhya Pradesh",
    "Bhopal": "Madhya Pradesh", "Gwalior": "Madhya Pradesh", "Jabalpur": "Madhya Pradesh",
    "Chandigarh": "Chandigarh", "Kochi": "Kerala", "Thiruvananthapuram": "Kerala",
    "Kozhikode": "Kerala", "Ludhiana": "Punjab", "Amritsar": "Punjab",
    "Jalandhar": "Punjab", "Visakhapatnam": "Andhra Pradesh", "Vijayawada": "Andhra Pradesh",
    "Guntur": "Andhra Pradesh", "Nellore": "Andhra Pradesh", "Bhubaneswar": "Odisha",
    "Patna": "Bihar", "Guwahati": "Assam", "Ranchi": "Jharkhand",
    "Jamshedpur": "Jharkhand", "Raipur": "Chhattisgarh", "Dehradun": "Uttarakhand",
}

_PAINS = {
    "manufacturing": ["Shop-floor attendance & shift tracking", "Payroll across grades", "Statutory compliance (PF/ESI)"],
    "hospital": ["Roster & shift scheduling for staff", "Nurse/doctor attendance", "Payroll & compliance"],
    "healthcare": ["Staff attendance & rostering", "Payroll & compliance", "Onboarding"],
    "hotel": ["Shift rosters across departments", "High attrition onboarding", "Payroll & tips"],
    "education": ["Faculty & staff attendance", "Payroll across roles", "Leave management"],
    "logistics": ["Driver/warehouse attendance", "Multi-site payroll", "High-attrition onboarding"],
    "IT services": ["Leave & attendance", "Appraisal cycles", "Onboarding at scale"],
    "retail": ["Multi-outlet attendance", "Hourly payroll", "High-attrition onboarding"],
}
_DEFAULT_PAIN = ["Manual HR & attendance", "Payroll & compliance", "Onboarding & leave management"]

# ICP fit — how HR-intensive / HRMS-likely an industry is (0..1). HumanMaximizer
# sells best into high-headcount, high-attrition, compliance-heavy sectors.
_INDUSTRY_FIT = {
    "manufacturing": 1.0, "factory": 1.0, "textile": 1.0, "pharmaceutical": 1.0,
    "automotive": 1.0, "auto components": 1.0, "chemical": 0.95, "logistics": 1.0,
    "hospital": 1.0, "healthcare": 0.95, "hotel": 1.0, "hospitality": 1.0,
    "BPO": 1.0, "call center": 1.0, "IT services": 0.9, "software": 0.85,
    "education": 0.9, "retail": 0.85, "food processing": 0.95, "construction": 0.95,
    "engineering": 0.9, "electronics": 0.85, "packaging": 0.9, "logistics and freight": 1.0,
    "pharmacy chain": 0.8, "banking": 0.7, "insurance": 0.75, "consulting": 0.6,
    "real estate": 0.7, "advertising": 0.6, "services": 0.55, "wholesale": 0.6,
    "trading": 0.55, "business": 0.4,
    # name-classifier labels:
    "steel": 1.0, "mining": 0.85, "utilities": 0.8, "printing": 0.8, "agriculture": 0.6,
    "packaging": 0.85, "media": 0.6, "electronics": 0.85, "BPO": 1.0,
    # HIGH-HR-INTENSITY sectors (workforce IS the business) → prime HRMS buyers:
    "staffing": 1.0,             # manpower / recruitment / payroll outsourcing
    "facility management": 1.0,  # housekeeping / security / integrated facilities
    "security services": 1.0,    # guarding — large blue-collar headcount
    "KPO": 1.0, "ITES": 1.0, "call centre": 1.0,
    "e-commerce": 0.95,          # warehousing + delivery + support workforce
    "QSR": 0.95, "restaurant": 0.95, "catering": 1.0,  # food-service, high attrition
    "EPC": 0.95, "infrastructure": 0.95,
    "aviation": 0.95,            # airlines / ground handling — large shift workforce
    "warehousing": 1.0, "cold chain": 1.0, "shipping": 0.95, "ports": 0.95,
    "dairy": 0.95, "plantation": 0.95, "sugar": 0.95,  # agro-labour heavy
    "jewellery": 0.9,            # gems & jewellery manufacturing (karigars)
    "telecom": 0.85, "microfinance": 0.92, "co-operative": 0.9,
    "gig": 1.0, "delivery": 0.95, "ride hailing": 0.95,
}
# Entity-type signals — a real registered company vs a single outlet.
_ENTITY_RE = re.compile(
    r"\b(pvt|private|ltd|limited|llp|inc|corp|industries|industrial|technologies|"
    r"tech|solutions|systems|enterprises|group|manufacturing|mfg|works|exports|"
    r"international|pharma|hospital|hospitals|hotels|resorts|logistics|services|"
    r"infotech|engineers|engineering|& sons|and sons|& co)\b", re.I)


def _industry_fit(industry: str) -> float:
    ind = (industry or "").lower()
    # Exact match first (case-insensitive), then substring — so 'BPO'/'IT services'
    # match correctly and 'services' doesn't shadow a more specific label.
    fits = {k.lower(): v for k, v in _INDUSTRY_FIT.items()}
    if ind in fits:
        return fits[ind]
    for k, v in fits.items():
        if k in ind:
            return v
    return 0.45


# ── Name-based industry classifier (RELIABLE) ─────────────────────────────────
# Indian company names almost always state the business. This is far more accurate
# than the CIN's NIC code (which uses inconsistent old NIC schemes / generic codes).
# Order matters: most-specific / least-ambiguous keywords first. Each entry is
# (industry, [whole-word keywords]). Matching is on word boundaries to avoid e.g.
# "carpets" → "pet". Returns (industry, confident) — confident=True only on a name hit.
_NAME_RULES: list[tuple[str, list[str]]] = [
    ("hospital", ["hospital", "hospitals", "nursing home", "multispeciality", "multispecialty",
                  "healthcare", "health care", "medicare", "medical college", "clinic", "clinics",
                  "diagnostics", "diagnostic", "path labs", "pathology", "imaging", "scans",
                  "dental", "eye care", "eye hospital", "fertility", "ivf", "ayurveda", "wellness",
                  "lifecare", "lifeline", "polyclinic", "medical centre", "medical center"]),
    ("pharmaceutical", ["pharma", "pharmaceutical", "pharmaceuticals", "drugs", "laboratories",
                        "lifesciences", "life sciences", "biotech", "biotechnology", "remedies",
                        "formulations", "healthcare labs", "biologicals", "vaccines", "nutraceuticals",
                        "medical devices", "surgicals", "diagnostics labs"]),
    ("hotel", ["hotel", "hotels", "resort", "resorts", "inn ", "inns", "hospitality", "banquets",
               "banquet", "motel", "lodge", "guest house", "catering", "caterers", "caters",
               "event management", "events", "convention", "club resort", "homestays"]),
    ("textile", ["textile", "textiles", "fabrics", "fabric", "garment", "garments", "apparel",
                 "apparels", "spinning mills", "textile mills", "cotton mills", "spinning",
                 "weaving", "cotton", "silk", "knitwear", "knits", "fashions", "clothing",
                 "denim", "yarn", "wovens", "readymade"]),
    ("food processing", ["tea", "coffee", "foods", "food products", "dairy", "milk", "beverages",
                         "agro", "sugar", "sugars", "sugar mill", "sugar mills", "edible", "oils",
                         "oil mills", "rice mill", "rice mills", "flour", "flour mills", "spices",
                         "masala", "bakery", "biscuits", "snacks", "confectionery", "nutrition",
                         "fmcg", "fisheries", "seafood", "poultry", "meat", "feeds", "creamery",
                         "distillery", "distilleries", "breweries", "brewery"]),
    ("automotive", ["motors", "automobile", "automobiles", "automotive", "autos", "auto ",
                    "vehicles", "tyres", "tyre", "tractors", "auto components", "auto parts"]),
    ("logistics", ["logistics", "transport", "transports", "roadways", "roadlines", "carriers",
                   "courier", "couriers", "cargo", "freight", "shipping", "movers", "packers",
                   "supply chain", "warehousing", "warehouse", "forwarders", "container", "3pl",
                   "cold storage", "cold chain", "express", "fleet", "stevedore", "stevedoring",
                   "clearing", "last mile", "distribution logistics", "port services"]),
    ("steel", ["steel", "iron", "alloys", "alloy", "metals", "metal ", "forgings", "forging",
               "castings", "foundry", "ferro", "tubes", "tmt", "rolling mills", "smelting"]),
    ("chemical", ["chemical", "chemicals", "polymers", "polymer", "plastics", "plastic", "paints",
                  "coatings", "fertilizer", "fertilizers", "fertiliser", "petrochem", "cryogenics",
                  "gases", "gas ", "adhesives", "dyes", "pigments", "resins", "agrochem", "specialty chem"]),
    ("construction", ["construction", "constructions", "builders", "buildcon", "infrastructure",
                      "infra", "developers", "projects", "realtors", "cement", "concrete", "buildtech",
                      "engineers & contractors", "infratech", " readymix"]),
    ("real estate", ["realty", "estates", "estate", "properties", "property", "housing", "landmark",
                     "habitat", "townships"]),
    ("education", ["school", "schools", "college", "colleges", "institute", "institutes", "academy",
                   "education", "educational", "vidyalaya", "vidya", "university", "edutech",
                   "coaching", "gurukul", "learning", "skills", "iti", "polytechnic",
                   "skill development", "skilling", "training", "tutorials", "e-learning",
                   "classes", "kindergarten", "playschool"]),
    ("retail", ["retail", "retails", "stores", "store", "mart", "bazaar", "supermarket", "hypermarket",
                "fashion retail", "jewellers", "jewellery", "jewelry"]),
    ("financial services", ["finance", "financial", "fincorp", "fincap", "capital", "investments",
                            "securities", "fintech", "credits", "leasing", "nbfc",
                            "fund", "wealth", "broking", "stock"]),
    ("insurance", ["insurance", "assurance", "insurers"]),
    ("microfinance", ["microfinance", "micro finance", "micro credit", "microcredit"]),
    ("banking", ["bank ", "bancorp", "cooperative bank", "co-op bank"]),
    # High-HR-intensity service sectors FIRST (so a BPO/staffing/facility firm isn't
    # mis-caught by a generic tech keyword). These are prime HRMS buyers.
    ("BPO", ["bpo", "kpo", "lpo", "call center", "call centre", "contact center", "contact centre",
             "outsourcing", "business process", "teleservices", "tele services", "ites",
             "back office", "back-office", "transcription", "customer support services"]),
    ("staffing", ["staffing", "manpower", "recruitment", "recruiters", "placements", "placement",
                  "workforce", "hr services", "hr solutions", "payroll services", "talent solutions",
                  "talent acquisition", "staffing solutions", "human resource", "manpower solutions"]),
    ("facility management", ["facility management", "facilities management", "facility services",
                             "facilities services", "facility solutions", "housekeeping",
                             "integrated facility", "security services", "security solutions",
                             "guarding", "manned guarding", "cleaning services", "sanitation services",
                             "pest control"]),
    ("e-commerce", ["e-commerce", "ecommerce", "online retail", "marketplace", "fulfilment",
                    "fulfillment", "quick commerce"]),
    ("IT services", ["technologies", "infotech", "software", "softwares", "systems", "solutions",
                     "infosystems", "computers", "computer", "digital", "cyber", "technosoft",
                     "datatech", "infosys", "it solutions", "web", "cloud", "analytics"]),
    ("electronics", ["electronics", "electronic", "electricals", "electrical", "appliances",
                     "semiconductor", "semiconductors", "circuits", "telecom equipment"]),
    ("packaging", ["packaging", "packagings", "packs", "flexipack", "corrugated", "cartons"]),
    ("printing", ["printing", "printers", "printpack", "offset", "press ", "publications"]),
    ("media", ["media", "films", "entertainment", "broadcasting", "productions", "publishers",
               "publishing", "cinema", "tv ", "studios"]),
    ("mining", ["mining", "minerals", "mineral", "mines", "coal", "ores", "quarry"]),
    ("utilities", ["power", "energy", "solar", "renewables", "renewable", "hydro", "thermal",
                   "powergen", "powertech", "windpower"]),
    ("agriculture", ["agriculture", "agritech", "seeds", "agri ", "plantations", "plantation",
                     "horticulture", "farms", "farming"]),
    ("manufacturing", ["industries", "industrial", "manufacturing", "manufacturers", "mfg",
                       "engineering", "engineers", "works", "machinery", "machines", "equipments",
                       "equipment", "tools", "toolings", "products", "fabrication", "fabricators",
                       "exports", "polyplast", "rubber", "ceramics", "tiles", "sanitaryware",
                       "sanitary ware", "glass", "paper", "pulp", "leather", "footwear", "tannery",
                       "furniture", "plywood", "veneers", "timber", "sawmill", "cables", "wires",
                       "pipes", "valves", "pumps", "bearings", "fasteners", "gears", "moulds",
                       "dies", "extrusions", "laminates", "batteries", "lighting", "lamps",
                       "switchgear", "transformers", "gems", "jewellery manufacturing", "diamonds",
                       "components", "precision", "casting", "forging works"]),
    ("aviation", ["aviation", "airlines", "airways", "aero", "aerospace", "ground handling",
                  "airport services", "air cargo", "flying"]),
    ("telecom", ["telecom", "telecommunication", "telecommunications", "towers", "broadband",
                 "fiber", "fibre", "network services", "isp"]),
    ("restaurant", ["restaurant", "restaurants", "qsr", "quick service", "food court", "eatery",
                    "kitchens", "cloud kitchen", "fast food", "diner", "cafe", "cafes"]),
    ("logistics", ["mobility", "delivery", "deliveries", "rider", "riders"]),
    ("consulting", ["consulting", "consultancy", "consultants", "advisory", "advisors"]),
    ("trading", ["traders", "trading", "tradelink", "impex", "import export", "exim", "agencies",
                 "distributors", "marketing", "enterprises", "trade"]),
]
_NAME_INDEX = [(ind, [k.strip() for k in kws]) for ind, kws in _NAME_RULES]


def classify_industry(name: str, fallback: str = "") -> tuple[str, bool]:
    """Classify a company by its NAME (reliable). Returns (industry, confident).

    Matches keywords as WHOLE WORDS so prefixes can't conflate (e.g. 'hospital' must
    NOT fire on 'hospitality', 'pharma' not on 'dharma'). confident=True only on a
    name hit; otherwise returns the supplied fallback (unreliable NIC guess) as not
    confident — and a not-confident lead can never be marked Hot."""
    n = (name or "").lower()
    for ind, kws in _NAME_INDEX:
        for k in kws:
            # \b…\b — whole word/phrase only. 'hospital' won't match 'hospitality'
            # because there's no word boundary between 'hospital' and 'ity'.
            if re.search(rf"\b{re.escape(k)}\b", n):
                return ind, True
    return (fallback or "business"), False

_lock = threading.Lock()
_state = {"running": False, "done": 0, "total": 0, "mobiles_found": 0}


def status() -> dict:
    return dict(_state)


def _state_for(location: str, region: Optional[str]) -> str:
    hay = f"{location or ''} {region or ''}"
    for city, st in CITY_STATE.items():
        if city.lower() in hay.lower():
            return st
    # already-named states
    for st in set(CITY_STATE.values()):
        if st.lower() in hay.lower():
            return st
    return ""


def _classify_phone(raw: str):
    """Return (mobile, office_phone) — mobile only if it's truly a mobile line."""
    from tools.contact_resolver import _normalize_phone
    n = _normalize_phone(raw or "", trusted=False)
    if not n:
        return "", ""
    if n["type"] == "mobile":
        return n["number"], ""
    return "", n["number"]  # landline / tollfree → office line


def process_lead(lead: dict) -> dict:
    """Normalise one lead: mobile-first contact, state, grade, pains. Pure/fast."""
    mobile, office = _classify_phone(lead.get("phone") or lead.get("mobile") or "")
    # An existing office_phone in the payload may still be useful.
    office = office or lead.get("office_phone") or ""
    city = (lead.get("location") or "").split(",")[0].strip()
    state = _state_for(lead.get("location") or "", lead.get("region") or lead.get("location"))
    lead["mobile"] = mobile
    lead["office_phone"] = office
    lead["phone"] = mobile           # primary contact = mobile ONLY
    lead["phone_type"] = "mobile" if mobile else None
    lead["state"] = state
    if state and city and state.lower() not in (lead.get("location") or "").lower():
        lead["location"] = f"{city}, {state}"
    ind = (lead.get("industry") or "").lower()
    lead["pain_points"] = next((v for k, v in _PAINS.items() if k in ind), _DEFAULT_PAIN)
    has_web = bool(lead.get("website") and ".osm.lead" not in str(lead.get("website")))
    fit = _industry_fit(ind)
    entity = bool(_ENTITY_RE.search(lead.get("company_name") or ""))

    # QUALITY score (0..10): is this the kind of company that BUYS HRMS, and can we
    # reach them? Industry HR-intensity dominates; contactability + being a real
    # registered entity (not a one-person shop) add on top.
    score = (fit * 4.5) + (2.5 if mobile else 0) + (1.2 if has_web else 0) \
        + (1.3 if entity else 0) + (0.5 if office else 0)
    score = round(min(score, 10.0), 1)

    # Contactability grade (A/B/C) — how reachable.
    grade = "A" if mobile and has_web else "A" if mobile else "B" if (office and has_web) else "C"
    # ICP tier — how likely to buy + reachable.
    tier = "Hot" if (score >= 7.5 and mobile) else "Warm" if score >= 5.5 else "Cold"
    lead["lead_grade"] = grade
    lead["icp_tier"] = tier
    lead["icp_fit"] = round(fit, 2)
    lead["lead_score"] = {"predicted_score": score, "icp_tier": tier,
                          "rationale": f"{tier} — {ind or 'business'} "
                          f"({'HR-intensive' if fit >= 0.8 else 'moderate fit' if fit >= 0.55 else 'low fit'}), "
                          + ("mobile-reachable" if mobile else "office line" if office else "needs contact")
                          + (", registered company" if entity else "")}
    lead["qualification_score"] = score
    # Hot+mobile → outreach-ready; reachable warm → qualified; else a lead to nurture.
    if tier == "Hot" and mobile:
        lead["status"] = "outreach_ready"
    elif mobile:
        lead["status"] = "qualified"
    elif has_web:
        lead["status"] = "pending_review"
    else:
        lead["status"] = "enriched"
    return lead


# ── Bulk reprocess + mobile fallback ──────────────────────────────────────────
def reprocess_all(scrape_fallback: bool = False, max_scrape: int = 400) -> dict:
    """Reprocess every pooled lead (mobile-first, state, grade). If scrape_fallback,
    visit the website of mobile-less leads to find a mobile (bounded, background)."""
    if not _lock.acquire(blocking=False):
        return {"status": "busy", **status()}
    try:
        from core import warehouse
        from concurrent.futures import ThreadPoolExecutor, as_completed
        leads = warehouse.query(min_score=0.0, limit=10000)
        _state.update(running=True, done=0, total=len(leads), mobiles_found=0)
        # Pass 1 — instant reclassification (mobile-first, state, grade) for ALL.
        for lead in leads:
            try:
                process_lead(lead)
                warehouse.save_enriched(lead, region=lead.get("region"))
            except Exception:
                pass
            _state["done"] += 1
        # Pass 2 — concurrent website scrape to FIND mobiles for mobile-less leads.
        if scrape_fallback:
            need = [l for l in leads if not l.get("mobile")
                    and l.get("website") and ".osm.lead" not in str(l["website"])][:max_scrape]
            with ThreadPoolExecutor(max_workers=12) as ex:
                futs = {ex.submit(_scrape_mobile, l["website"]): l for l in need}
                for fut in as_completed(futs):
                    lead = futs[fut]
                    try:
                        mob = fut.result()
                    except Exception:
                        mob = ""
                    if mob:
                        lead["mobile"] = mob
                        lead["phone"] = mob
                        lead["phone_type"] = "mobile"
                        lead["status"] = "qualified"
                        lead["lead_grade"] = "A"
                        _state["mobiles_found"] += 1
                        try:
                            warehouse.save_enriched(lead, region=lead.get("region"))
                        except Exception:
                            pass
        logger.info(f"[leadproc] reprocessed {len(leads)} leads, +{_state['mobiles_found']} mobiles via scrape")
        return {"status": "ok", "processed": len(leads), "mobiles_found": _state["mobiles_found"]}
    except Exception as e:
        logger.warning(f"[leadproc] failed: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        _state["running"] = False
        _lock.release()


def _scrape_mobile(website: str) -> str:
    """Visit the site's contact pages and return the first valid MOBILE number."""
    try:
        import requests
        from tools.contact_resolver import _normalize_phone, _HEADERS
        from urllib.parse import urljoin
    except Exception:
        return ""
    base = website if "://" in website else "https://" + website
    pages = [base] + [urljoin(base.rstrip("/") + "/", p) for p in
                      ("contact", "contact-us", "contactus", "about", "reach-us")]
    pat = re.compile(r'(?<!\d)(?:\+?91[\s\-]?)?[6-9]\d{9}(?!\d)')
    for url in pages[:4]:
        try:
            html = requests.get(url, headers=_HEADERS, timeout=6).text
        except Exception:
            continue
        for m in pat.findall(html):
            n = _normalize_phone(m, trusted=False)
            if n and n["type"] == "mobile":
                return n["number"]
    return ""
