"""
Research Agent
--------------
Responsibility: Find and extract company leads from the web based on a keyword.
Input:  LeadState with a keyword
Output: Populated list of Lead objects with basic company info

Funnel (cheap → expensive, so tokens are spent only on survivors):
  cache-gate → scrape → No-HRMS detect (drop+cache HAS-HRMS pre-LLM) → LLM extract
  → geo filter → verified contact + employee-band gate → enrich → score.

Candidates are processed CONCURRENTLY in a bounded thread pool for speed; the
driver stops as soon as `max_leads` good leads are collected.
"""
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from graph.state import LeadState
from agents.base import BaseAgent
from tools.web_search import search_companies_multi_source, scrape_company_info, scrape_company_contacts, search_company_address_snippets
from tools.linkedin_enricher import enrich_decision_maker
from tools.hrms_detector import detect_hrms
from tools.lead_scoring import score_lead, target_contact
from tools.contact_resolver import resolve_contact, in_target_band
from tools.verifier import cross_verify
from tools.geo import geo_match
from cache.redis_client import is_duplicate_lead, mark_lead_seen
from core.lead_cache import set_verdict, is_seen, domain_of
from core import runtime_config as rc
from rag.hallucination_guard import guard_llm_response
from observability.langsmith_tracer import stage_timer, log_hallucination_event
from observability.event_bus import emit
from core.config import get_settings

settings = get_settings()

# India metros used for backfilling a location from an address.
_INDIA_CITIES = [
    "mumbai", "bengaluru", "bangalore", "delhi", "noida", "gurugram", "gurgaon",
    "pune", "chennai", "hyderabad", "kolkata", "ahmedabad", "jaipur", "lucknow",
    "indore", "bhopal", "chandigarh", "coimbatore", "kochi", "nagpur",
]
# Broad India location indicators for the country gate (India-only ICP).
_INDIA_INDICATORS = [
    "india", "indian", "mumbai", "bangalore", "bengaluru", "delhi", "noida",
    "gurgaon", "gurugram", "pune", "hyderabad", "chennai", "kolkata", "ahmedabad",
    "gujarat", "maharashtra", "karnataka", "tamil nadu", "tamilnadu", "telangana",
    "haryana", "uttar pradesh", "west bengal", "punjab", "rajasthan", "kerala",
    "madhya pradesh", "bihar", "odisha", "andhra pradesh", "assam", "coimbatore",
    "kochi", "cochin", "mysore", "mysuru", "vadodara", "surat", "nagpur",
    "nashik", "thane", "navi mumbai", "ludhiana", "amritsar", "jalandhar",
    "chandigarh", "mohali", "lucknow", "kanpur", "ghaziabad", "meerut", "varanasi",
    "agra", "prayagraj", "dehradun", "jaipur", "jodhpur", "udaipur", "raipur",
    "ranchi", "jamshedpur", "patna", "bhubaneswar", "guwahati", "bhopal",
    "indore", "gwalior", "jabalpur", "vijayawada", "visakhapatnam", "vizag",
    "madurai", "salem", "tiruppur", "puducherry", "goa", "panaji",
]

RESEARCH_PROMPT = """You are a B2B lead research specialist identifying companies that need HRMS software.

IMPORTANT: Extract ONLY companies that BUY or USE HR software (manufacturers, retailers, IT firms,
logistics companies, hospitals, schools, startups, etc.). Do NOT extract companies that SELL
HR/payroll/HRMS software — those are competitors, not prospects.

CRITICAL ACCURACY RULE: You MUST extract data ONLY from the "Scraped Website Content" section below.
Do NOT infer, guess, hallucinate, or fill fields from general knowledge or from the Search Results snippet.
The Search Results are provided only to identify the company URL and name — NOT as a source for extracted fields.

Search Results (for URL/name identification only — do NOT extract field values from here):
{search_results}

Scraped Website Content (PRIMARY SOURCE — extract all fields from here only):
{scraped_content}

Address Search Snippets (Google):
{address_search_snippets}

Extract lead information and respond with a JSON object ONLY (no explanation):
{{
  "company_name": "...",
  "website": "...",
  "industry": "...(their actual business, NOT 'HRMS software')",
  "size": "...(ONLY state employee count if it is explicitly mentioned as a number in the Scraped Website Content, e.g. '200 employees'. If not explicitly mentioned, return empty string)",
  "location": "...(city and state if found in Scraped Website Content, e.g. Mumbai, Maharashtra)",
  "address": "...(physical office address if mentioned, else empty string)",
  "description": "...(what the company does, 2-3 sentences, based only on Scraped Website Content)",
  "decision_makers": ["...(ONLY names or job titles you can literally see on the page in the Scraped Website Content. Do NOT make up or infer titles. If none found, return [])"],
  "contact_emails": ["...(ONLY email addresses you can see as text in the Scraped Website Content. Do NOT guess or construct email addresses. If none visible, return [])"],
  "pain_points": ["...(Based ONLY on their industry and what their website says about their business. Do NOT guess generically.)"],
  "status": "researched"
}}

Rules:
- contact_emails: ONLY list emails you can see as literal text in the Scraped Website Content. Do NOT construct, guess, or infer emails. If none are visible in the content, return [].
- size: ONLY state employee count if it is explicitly mentioned as a number in the Scraped Website Content. Otherwise return empty string.
- phone: ONLY return a phone number if it appears literally in the Scraped Website Content. Do NOT infer.
- address: copy any physical office address found verbatim. Check the "Address Search Snippets (Google)" section for the physical address. If not found in the scraped content, prioritize the physical office address found in the Google Address Search Snippets!
- decision_makers: ONLY include names or titles you can literally see on the page. Do NOT make up or infer titles. If none found, return [].
- If this company sells HRMS/payroll/HR software itself, return: {{"status": "invalid"}}
- If you cannot extract valid company info, return: {{"status": "invalid"}}
- CRITICAL REGIONAL RULE: We target INDIA only. If the company is clearly located outside India, return: {{"status": "invalid"}}
"""

# Max concurrent candidates in flight (bounded so we don't hammer sources / LLM).
_MAX_WORKERS = 12


def _fetch_html(url: str) -> str:
    """One light homepage fetch (short timeout) for fast mode."""
    try:
        import requests
        u = url if "://" in url else "http://" + url
        r = requests.get(u, headers={"User-Agent": "Mozilla/5.0 (compatible; LeadGenBot/1.0)"},
                         timeout=settings.request_timeout)
        return (r.text or "")[:60000]
    except Exception:
        return ""


def _pain_for(kw: str) -> list:
    kw = (kw or "").lower()
    if any(w in kw for w in ("manufactur", "factory", "plant", "textile", "steel", "pharma", "engineering")):
        return ["Manual attendance across shifts", "Payroll & PF/ESI compliance", "High floor-staff attrition"]
    if any(w in kw for w in ("logistic", "transport", "warehouse", "courier", "freight", "supply chain")):
        return ["Shift & roster scheduling", "Multi-site attendance", "Overtime/payroll accuracy"]
    if any(w in kw for w in ("hospital", "clinic", "health", "diagnost", "pharmacy")):
        return ["24x7 shift rostering", "Compliance & duty logs", "Staff attendance tracking"]
    if any(w in kw for w in ("bpo", "software", "tech", "call center", "call centre", " it ", "fintech")):
        return ["Shift attendance", "Leave & WFH tracking", "Fast onboarding at scale"]
    if any(w in kw for w in ("retail", "store", "hotel", "restaurant", "hospitality")):
        return ["Multi-outlet attendance", "Roster & part-time payroll", "High-turnover onboarding"]
    return ["Manual HR & attendance", "Payroll & compliance", "Onboarding/offboarding"]


def _industry_label(keyword: str) -> str:
    """Clean industry label from a search phrase (drop geo/size words)."""
    kw = (keyword or "").lower()
    for label, hints in (
        ("Manufacturing", ("manufactur", "factory", "plant", "textile", "steel", "pharma", "engineering")),
        ("Logistics", ("logistic", "transport", "warehouse", "courier", "freight", "supply chain")),
        ("Healthcare", ("hospital", "clinic", "health", "diagnost", "medical")),
        ("IT / BPO", ("bpo", "software", "tech", "call cent", " it ", "fintech")),
        ("Retail & Hospitality", ("retail", "store", "hotel", "restaurant", "hospitality")),
        ("Education", ("school", "college", "education", "institute")),
    ):
        if any(h in kw for h in hints):
            return label
    # fall back to the first two words of the keyword
    words = [w for w in re.split(r"[^a-zA-Z]+", keyword or "") if w and w.lower() not in
             ("india", "company", "companies", "employees", "employee", "staff", "sme", "smes")]
    return " ".join(words[:2]).title() or "SME"


def _build_lead_fast(result: dict, url: str, html: str, keyword: str) -> dict:
    """Deterministic lead build (NO LLM) from the search result + homepage HTML."""
    title = result.get("title") or ""
    name = title.split(" - ")[0].split(" | ")[0].split(":")[0].strip()
    if len(name) < 2:
        name = (domain_of(url).split(".")[0] or "Company").replace("-", " ").title()
    desc = result.get("snippet") or ""
    m = re.search(
        r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']{20,300})',
        html or "", re.I,
    )
    if m:
        desc = m.group(1).strip()
    # Derive location: explicit field wins, else scan the (un-cleaned) title +
    # snippet + meta-description for an India city/indicator. The name-split above
    # drops "… Mumbai India" from the company name, so without this the India gate
    # would reject perfectly valid leads that only name their city in the title.
    loc = (result.get("location") or "").strip()
    if not loc:
        hay = f"{title} {result.get('snippet','')} {desc}".lower()
        city = next((c for c in _INDIA_INDICATORS if c not in ("india", "indian") and c in hay), None)
        if city:
            loc = f"{city.title()}, India"
        elif "india" in hay:
            loc = "India"
    return {
        "company_name": name,
        # Prefer the industry the candidate was harvested under (matrix knows it);
        # fall back to deriving it from the keyword.
        "industry": (result.get("industry") or "").strip() or _industry_label(keyword),
        "website": url,
        "description": desc[:300],
        "contact_emails": [],
        "pain_points": _pain_for(keyword),
        "location": loc,
        "address": "",
        "status": "researched",
    }


class ResearchAgent(BaseAgent):
    name = "research_agent"

    # ── Per-candidate pipeline (runs in a worker thread) ─────────────────────
    def _process_candidate(self, result: dict, ctx: dict) -> Optional[dict]:
        """Full funnel for ONE candidate. Returns a lead dict or None (dropped)."""
        run_id = ctx["run_id"]
        url = result.get("url", "")
        dom = domain_of(url)

        # Cache gate — skip ANY company already evaluated (hot OR ruled out), so
        # repeat searches never re-spend tokens on the same lead. Skipped in
        # company-lookup mode (there we always want a fresh fetch).
        if not ctx.get("company_mode") and is_seen(url):
            emit(run_id, "tool", agent="research_agent", stage="research",
                 message=f"Skipped {dom} (already evaluated — saved, not re-searched)")
            return None

        fast = ctx.get("fast", True)

        # ── Fetch + No-HRMS detect + build lead (fast = deterministic, no LLM) ──
        if fast:
            scraped = _fetch_html(url)
            hrms = detect_hrms(url, prefetched_html=scraped, company_name=result.get("title", ""))
            if ctx["exclude_with_hrms"] and hrms["has_hrms"]:
                vendor = (hrms["detected_vendors"] or ["an HRMS"])[0]
                set_verdict(url, "excluded", reason=f"already uses {vendor}", no_hrms_confidence=hrms["no_hrms_confidence"])
                emit(run_id, "tool", agent="research_agent", stage="research", message=f"Dropped {dom}: already runs {vendor}")
                return None
            from tools.web_search import extract_emails
            contacts = {"emails": extract_emails(scraped or ""), "phone": "", "address": ""}
            lead_data = _build_lead_fast(result, url, scraped, ctx.get("keyword", ""))
        else:
            scraped = scrape_company_info(url)
            hrms = detect_hrms(url, prefetched_html=scraped, company_name=result.get("title", ""))
            if ctx["exclude_with_hrms"] and hrms["has_hrms"]:
                vendor = (hrms["detected_vendors"] or ["an HRMS"])[0]
                set_verdict(url, "excluded", reason=f"already uses {vendor}", no_hrms_confidence=hrms["no_hrms_confidence"])
                emit(run_id, "tool", agent="research_agent", stage="research", message=f"Dropped {dom}: already runs {vendor}")
                return None
            contacts = scrape_company_contacts(url)
            try:
                lead_data = self.parse_json_response(self.call_llm(
                    RESEARCH_PROMPT.format(search_results=json.dumps(result, indent=2),
                                           scraped_content=scraped, address_search_snippets=""),
                    temperature=settings.llm_temperature_extract))
            except Exception as e:
                self.log.error(f"Error processing {url}: {e}")
                return None
            if lead_data.get("status") == "invalid":
                return None

        company_name = lead_data.get("company_name", "")
        if not company_name:
            return None

        # Merge regex contacts
        lead_data["contact_emails"] = list(dict.fromkeys((lead_data.get("contact_emails") or []) + contacts["emails"]))
        if contacts.get("phone") and not lead_data.get("phone"):
            lead_data["phone"] = contacts["phone"]
        if contacts.get("address") and not lead_data.get("address"):
            lead_data["address"] = contacts["address"]

        # ── Verified contact (Places + LinkedIn band) — EARLY, so geo/size gates
        #    have real location + employee data (essential in fast mode) ─────────
        loc_city = (lead_data.get("location") or "").split(",")[0].strip() or None
        resolved = resolve_contact(
            company_name, website=url, city=loc_city,
            pincode=ctx["region"] if (ctx["region"] and str(ctx["region"]).isdigit()) else None,
            serper_key=rc.get("serper_api_key"),
        )
        if resolved.get("phone"):
            lead_data["phone"] = resolved["phone"]
            lead_data["phone_type"] = resolved["phone_type"]
            lead_data["phone_source"] = resolved["phone_source"]
            lead_data["contact_confidence"] = resolved["contact_confidence"]
        if resolved.get("website") and not lead_data.get("website"):
            lead_data["website"] = resolved["website"]
        if resolved.get("address") and not lead_data.get("address"):
            lead_data["address"] = resolved["address"]
        if resolved.get("employee_band"):
            lead_data["employee_band"] = resolved["employee_band"]
            lead_data["employee_min"] = resolved["employee_min"]
            lead_data["employee_max"] = resolved["employee_max"]
            if not lead_data.get("size"):
                lead_data["size"] = resolved["employee_band"]
        if not lead_data.get("location") and lead_data.get("address"):
            al = lead_data["address"].lower()
            lead_data["location"] = next((f"{c.capitalize()}, India" for c in _INDIA_CITIES if c in al), "India")

        # India-only country gate
        combined_loc = f"{company_name} {lead_data.get('location','')} {lead_data.get('address','')}".lower()
        if not any(ind in combined_loc for ind in _INDIA_INDICATORS):
            self.log.info(f"Rejecting {company_name}: not India")
            return None

        # Keyword size hint gate
        if ctx["target_size"] > 0:
            m = re.search(r"(\d+)", (lead_data.get("size") or "").replace(",", ""))
            if m and int(m.group(1)) > ctx["target_size"] * 20:
                return None

        # Employee-band gate (>50, not too big)
        if not ctx.get("company_mode") and in_target_band(
            {"min": resolved.get("employee_min"), "max": resolved.get("employee_max")}, 50, 1000
        ) is False:
            set_verdict(url, "excluded", reason=f"size band {resolved.get('employee_band')}", company_name=company_name)
            return None

        # Explicit geo filter (region / preset)
        if ctx["explicit_geo"] and not geo_match(lead_data, ctx["geo_country"], ctx["geo_region"]):
            set_verdict(url, "excluded", reason="outside geo filter", company_name=company_name)
            return None

        # Decision-maker enrichment (Instantly pre-fill, else LinkedIn)
        if result.get("dm_name"):
            lead_data["decision_maker_name"] = result["dm_name"].split()[0]
            lead_data["decision_maker_full_name"] = result.get("dm_name", "")
            lead_data["decision_maker_title"] = result.get("dm_title", "")
            lead_data["decision_maker_linkedin"] = result.get("dm_linkedin", "")
            if result.get("dm_email"):
                lead_data["contact_emails"] = list(dict.fromkeys([result["dm_email"]] + lead_data.get("contact_emails", [])))
            lead_data["email_guesses"] = []
        else:
            dm = enrich_decision_maker(company_name, domain_of(url))
            lead_data["decision_maker_name"] = dm.get("name", "")
            lead_data["decision_maker_full_name"] = dm.get("full_name", "")
            lead_data["decision_maker_title"] = dm.get("title", "")
            lead_data["decision_maker_linkedin"] = dm.get("linkedin_url", "")
            lead_data["contact_emails"] = list(dict.fromkeys(lead_data.get("contact_emails", []) + dm.get("email_guesses", [])))
            lead_data["email_guesses"] = dm.get("email_guesses", [])

        # HRMS verdict + back-compat tech_stack + scoring
        lead_data["hrms"] = hrms
        lead_data["tech_stack"] = {
            "current_tools": hrms["detected_vendors"],
            "maturity": {"manual": "manual", "legacy": "legacy", "modern": "modern"}.get(hrms["maturity"], "unknown"),
            "signals": hrms["signals"],
            "pitch_angle": hrms["pitch_angle"],
        }
        lead_data["target_contact"] = target_contact(lead_data)
        lead_data["lead_score"] = score_lead(lead_data)

        # ── Cross-source verification (double/triple-check before trusting) ─────
        verification = cross_verify(lead_data, scraped, hrms, rc.get("serper_api_key"), loc_city)
        lead_data["verification"] = verification
        # If a SECOND source shows they already run an HRMS, drop (when filtering).
        if ctx["exclude_with_hrms"] and verification["hrms_absence"]["second_source"] == "vendor_found":
            vendor = verification["hrms_absence"]["vendor"]
            set_verdict(url, "excluded", reason=f"HRMS confirmed via 2nd source ({vendor})", company_name=company_name)
            emit(run_id, "tool", agent="research_agent", stage="research",
                 message=f"Dropped {dom}: 2nd source shows it runs {vendor}")
            return None

        # Dedup (24h) + hallucination guard + persist HOT verdict
        if is_duplicate_lead(company_name):
            return None
        guard = guard_llm_response(response_text=json.dumps(lead_data), rag_context=scraped, strict=False)
        if guard["action"] == "warn":
            log_hallucination_event("research_agent", guard, ctx["correlation_id"])
        mark_lead_seen(company_name)
        set_verdict(url, "hot", reason="no-HRMS prospect", company_name=company_name,
                    no_hrms_confidence=hrms["no_hrms_confidence"],
                    score=(lead_data.get("lead_score") or {}).get("predicted_score"))

        lead_data.setdefault("id", str(uuid.uuid4())[:8])
        lead_data.setdefault("qualification_score", None)
        lead_data.setdefault("qualification_reason", None)
        lead_data.setdefault("outreach_draft", None)
        lead_data.setdefault("status", "researched")
        # Bank the enriched lead in the warehouse so future searches serve it
        # instantly without re-crawling the sources.
        try:
            from core import warehouse
            warehouse.save_enriched(lead_data, region=ctx.get("region"))
        except Exception:
            pass
        return lead_data

    def _process_batch(self, batch: list, ctx: dict, run_cap: int, new_leads: list, run_id) -> None:
        """Process a candidate batch concurrently; append valid leads until run_cap."""
        workers = min(_MAX_WORKERS, max(2, len(batch)))
        ex = ThreadPoolExecutor(max_workers=workers)
        futures = [ex.submit(self._process_candidate, r, ctx) for r in batch]
        try:
            for fut in as_completed(futures):
                try:
                    lead = fut.result()
                except Exception as e:
                    self.log.error(f"candidate failed: {e}")
                    continue
                if not lead:
                    continue
                new_leads.append(lead)
                emit(run_id, "lead_found", agent="research_agent", stage="research",
                     message=f"Extracted {lead.get('company_name','')}", lead=lead)
                self.log.info(f"Lead extracted: {lead.get('company_name','')}")
                if len(new_leads) >= run_cap:
                    break
        finally:
            ex.shutdown(wait=False, cancel_futures=True)

    @stage_timer("research_agent")
    def run(self, state: LeadState) -> LeadState:
        keyword = state["keyword"]
        run_id = state.get("run_id")
        emit(run_id, "stage_start", agent="research_agent", stage="research",
             message=f"Searching multi-source for '{keyword}'")
        self.log.info(f"Starting search for keyword: '{keyword}'")

        # India-only ICP — country defaults to India.
        target_country = state.get("country") or "India"
        target_size = 0
        m = re.search(r"\b(\d{2,5})\s*(?:employees?|staff|workers?|people)\b", keyword, re.I)
        if m:
            target_size = int(m.group(1))

        run_cap = state.get("max_leads") or settings.max_leads_per_run
        mode = state.get("mode", "discover")
        company_mode = mode == "company"

        ctx = {
            "run_id": run_id,
            "correlation_id": state.get("correlation_id", self.correlation_id),
            "fast": state.get("fast", True),
            "keyword": keyword,
            "target_country": target_country,
            "target_size": target_size,
            "geo_country": target_country,
            "geo_region": state.get("region"),
            "region": state.get("region"),
            "explicit_geo": bool(state.get("country") or state.get("region")) and not company_mode,
            # In company-lookup mode we always want the target's details, so don't
            # exclude on existing-HRMS or size band.
            "exclude_with_hrms": state.get("exclude_with_hrms", True) and not company_mode,
            "company_mode": company_mode,
        }

        # Keep pulling FRESH candidate waves until we actually hit the requested
        # count (user asked for N → return N), or the sources are exhausted.
        new_leads: list[dict] = []
        seen_urls: set = set()
        # Keep pulling fresh waves until we hit the requested count (or new
        # domains run out). More waves for bigger asks so "find 50" returns ~50.
        max_waves = 1 if company_mode else 12
        any_candidates = False

        for wave in range(max_waves):
            if len(new_leads) >= run_cap:
                break
            if company_mode:
                from tools.web_search import find_company
                batch_src = find_company(keyword, state.get("region") or "", max_results=max(run_cap, 1))
            else:
                # Each call reshuffles query variants → surfaces new domains.
                batch_src = search_companies_multi_source(keyword, max_results=max(run_cap * 8, 40))

            batch = []
            for r in batch_src:
                u = r.get("url")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    batch.append(r)
            if not batch:
                self.log.info(f"Wave {wave + 1}: no new candidates — source pool exhausted")
                break
            any_candidates = True
            # Bank every discovered candidate as 'raw' in the warehouse pool so it
            # need not be re-discovered next time (cheap; deduped by domain).
            try:
                from core import warehouse
                warehouse.upsert_raw(batch, region=state.get("region"))
            except Exception:
                pass
            need = run_cap - len(new_leads)
            emit(run_id, "tool", agent="research_agent", stage="research",
                 message=f"Wave {wave + 1}: {len(batch)} new candidates (need {need} more)")
            # Cap how many sites we fully process per wave so wall-time stays low;
            # the next wave fetches fresh candidates if we still need more.
            batch = batch[: max(run_cap * 4, 12)]
            self.log.info(f"Wave {wave + 1}: {len(batch)} candidates (have {len(new_leads)}/{run_cap})")
            self._process_batch(batch, ctx, run_cap, new_leads, run_id)

        if not new_leads:
            msg = "No leads matched the criteria" if any_candidates else f"No results for '{keyword}'"
            self.log.warning(msg)
            return {**state, "messages": [f"Research Agent: {msg}"], "errors": [msg], "next": "END"}

        self.log.info(f"Research complete: {len(new_leads)}/{run_cap} leads extracted")
        emit(run_id, "stage_end", agent="research_agent", stage="research",
             message=f"{len(new_leads)} leads extracted")

        return {
            **state,
            "leads": state.get("leads", []) + new_leads,
            "messages": [f"Research Agent: Found {len(new_leads)} leads for '{keyword}'"],
            "iteration": state.get("iteration", 0) + 1,
            "next": "qualify",
        }


# LangGraph-compatible function wrapper
def research_agent(state: LeadState) -> LeadState:
    agent = ResearchAgent(correlation_id=state.get("correlation_id"))
    return agent.run(state)
