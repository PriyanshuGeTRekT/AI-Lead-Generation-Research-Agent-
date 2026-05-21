"""
Research Agent
--------------
Responsibility: Find and extract company leads from the web based on a keyword.
Input:  LeadState with a keyword
Output: Populated list of Lead objects with basic company info

Extends BaseAgent for:
  - Structured logging with correlation ID
  - LLM calls with Redis caching + exponential backoff retry
  - Consistent JSON parsing
"""
import json
import uuid
from graph.state import LeadState
from agents.base import BaseAgent
from tools.web_search import search_companies_multi_source, scrape_company_info, scrape_company_contacts
from tools.linkedin_enricher import enrich_decision_maker
from tools.tech_stack_detector import detect_tech_stack
from cache.redis_client import is_duplicate_lead, mark_lead_seen
from rag.hallucination_guard import guard_llm_response
from observability.langsmith_tracer import stage_timer, log_hallucination_event
from core.config import get_settings

settings = get_settings()

RESEARCH_PROMPT = """You are a B2B lead research specialist identifying companies that need HRMS software.

IMPORTANT: Extract ONLY companies that BUY or USE HR software (manufacturers, retailers, IT firms,
logistics companies, hospitals, schools, startups, etc.). Do NOT extract companies that SELL
HR/payroll/HRMS software — those are competitors, not prospects.

Search Results:
{search_results}

Scraped Website Content:
{scraped_content}

Address Search Snippets (Google):
{address_search_snippets}

Extract lead information and respond with a JSON object ONLY (no explanation):
{{
  "company_name": "...",
  "website": "...",
  "industry": "...(their actual business, NOT 'HRMS software')",
  "size": "...(e.g. 200 employees, 500+ staff — look for headcount mentions)",
  "location": "...(city and state if found, e.g. Mumbai, Maharashtra)",
  "address": "...(physical office address if mentioned, else empty string)",
  "description": "...(what the company does, 2-3 sentences)",
  "decision_makers": ["...(names or titles like HR Manager, CEO found on site)"],
  "contact_emails": ["...(any business email addresses found on the site)"],
  "pain_points": ["...(likely HR challenges they face based on their industry/size)"],
  "status": "researched"
}}

Rules:
- contact_emails: list every email address you can find in the content (look for @domain patterns)
- address: copy any physical office address found verbatim. Check the "Address Search Snippets (Google)" section for the physical address. If not found in the scraped content, prioritize the physical office address found in the Google Address Search Snippets!
- decision_makers: include names if found, else job titles (HR Manager, CEO, etc.)
- If this company sells HRMS/payroll/HR software itself, return: {{"status": "invalid"}}
- If you cannot extract valid company info, return: {{"status": "invalid"}}
- CRITICAL REGIONAL RULE: If the target keyword specifies a country (e.g., "India"), you MUST verify that the company is actually located in, has a major office in, or operates significantly in that country. If it is located in a completely different country/region (for example, a USA-only company when the keyword specifies "India"), you MUST return: {{"status": "invalid"}}
"""


class ResearchAgent(BaseAgent):
    name = "research_agent"

    @stage_timer("research_agent")
    def run(self, state: LeadState) -> LeadState:
        keyword = state["keyword"]
        correlation_id = state.get("correlation_id", self.correlation_id)
        self.log.info(f"Starting search for keyword: '{keyword}'")

        # Target country detection
        keyword_lower = keyword.lower()
        target_country = ""
        if "india" in keyword_lower:
            target_country = "India"
        elif any(k in keyword_lower for k in ["usa", "united states", " u.s.", "/us"]):
            target_country = "United States"
        elif "germany" in keyword_lower:
            target_country = "Germany"
        elif "uk" in keyword_lower or "united kingdom" in keyword_lower:
            target_country = "United Kingdom"

        if target_country:
            self.log.info(f"Target country constraint detected: '{target_country}'")

        # Determine cap before searching so we don't over-fetch
        run_cap = state.get("max_leads") or settings.max_leads_per_run
        # Fetch 4× more candidates than needed to cover scraping failures and
        # LLM-invalid results, but no more — keeps search fast for small runs
        search_limit = max(run_cap * 4, 20)
        search_results = search_companies_multi_source(keyword, max_results=search_limit)

        if not search_results:
            self.log.warning("Web search returned no results")
            return {
                **state,
                "messages": [f"Research Agent: No results for '{keyword}'"],
                "errors": ["Web search returned no results"],
                "next": "END",
            }

        self.log.info(f"Found {len(search_results)} search results")
        new_leads = []

        # Try every available URL — no artificial ceiling.
        # The break below stops as soon as run_cap good leads are collected,
        # so asking for 1 lead stops after the first valid company is found.
        valid_results = [r for r in search_results if r.get("url")]
        self.log.info(f"Processing up to {len(valid_results)} candidates (target={run_cap})")

        for result in valid_results:
            # Stop the moment we have enough leads
            if len(new_leads) >= run_cap:
                self.log.info(f"Reached target of {run_cap} leads, stopping early")
                break
            url = result.get("url", "")

            # Scrape homepage + contact page text for LLM
            scraped = scrape_company_info(url)

            # Regex-extract contacts from raw HTML (independent of LLM)
            contacts = scrape_company_contacts(url)

            # Google Address Snippet Search for grounding physical address
            search_title = result.get("title", "")
            company_search_name = search_title.split("-")[0].split("|")[0].strip()
            
            from tools.web_search import search_company_address_snippets
            address_snippets = search_company_address_snippets(company_search_name, target_country)

            prompt = RESEARCH_PROMPT.format(
                search_results=json.dumps(result, indent=2),
                scraped_content=scraped,
                address_search_snippets=address_snippets,
            )

            try:
                raw = self.call_llm(prompt, temperature=settings.llm_temperature_extract)
                lead_data = self.parse_json_response(raw)

                if lead_data.get("status") == "invalid":
                    self.log.debug(f"LLM marked lead as invalid for URL: {url}")
                    continue

                company_name = lead_data.get("company_name", "")

                # Merge regex-extracted contacts with LLM-extracted ones
                llm_emails = lead_data.get("contact_emails") or []
                merged_emails = list(dict.fromkeys(llm_emails + contacts["emails"]))  # dedup, preserve order
                lead_data["contact_emails"] = merged_emails

                if contacts["phone"] and not lead_data.get("phone"):
                    lead_data["phone"] = contacts["phone"]
                if contacts["address"] and not lead_data.get("address"):
                    lead_data["address"] = contacts["address"]

                # Fallback Address parsing from Serper snippets if still empty
                if not lead_data.get("address"):
                    if "Google Knowledge Graph Address for" in address_snippets:
                        for line in address_snippets.split("\n"):
                            if "Google Knowledge Graph Address for" in line:
                                lead_data["address"] = line.split(":", 1)[1].strip()
                                break
                    elif "Google Direct Answer:" in address_snippets:
                        for line in address_snippets.split("\n"):
                            if "Google Direct Answer:" in line:
                                lead_data["address"] = line.split(":", 1)[1].strip()
                                break
                    else:
                        # Fallback: extract address-like content from organic snippets
                        for line in address_snippets.split("\n"):
                            line_lower = line.lower()
                            if any(k in line_lower for k in ["address", "headquarters", "registered office", "corporate office", "office location", "office at", "located at", "stands located at", "plot no", "street", "building", "road", "sector", "industrial area"]):
                                if ":" in line:
                                    parts = line.split(":", 1)[1].strip()
                                    if len(parts) > 15:
                                        lead_data["address"] = parts
                                        break

                # If location is empty but we got a valid address, extract city/state/country as location
                if not lead_data.get("location") and lead_data.get("address"):
                    addr_lower = lead_data["address"].lower()
                    if target_country == "India":
                        for city in ["mumbai", "bengaluru", "bangalore", "delhi", "noida", "gurugram", "gurgaon", "pune", "chennai", "hyderabad", "kolkata"]:
                            if city in addr_lower:
                                lead_data["location"] = f"{city.capitalize()}, India"
                                break
                        else:
                            lead_data["location"] = "India"
                    elif target_country == "United States":
                        lead_data["location"] = "United States"
                    elif target_country:
                        lead_data["location"] = target_country

                # Target country filtering (run after all address and location fields are resolved)
                if target_country:
                    loc_val = (lead_data.get("location") or "").lower()
                    addr_val = (lead_data.get("address") or "").lower()
                    combined_loc = company_name.lower() + " " + loc_val + " " + addr_val

                    if target_country == "India":
                        indian_indicators = [
                            "india", "indian", "mumbai", "bangalore", "bengaluru", "delhi", "noida", 
                            "gurgaon", "gurugram", "pune", "hyderabad", "chennai", "kolkata", "ahmedabad", 
                            "gujarat", "maharashtra", "karnataka", "tamil nadu", "tamilnadu", "telangana", 
                            "haryana", "uttar pradesh", "west bengal", "punjab", "rajasthan", "kerala", 
                            "madhya pradesh", "bihar", "odisha", "andhra pradesh", "assam", "coimbatore", 
                            "kochi", "cochin", "mysore", "mysuru", "hubli", "vadodara", "surat", "nagpur", 
                            "nashik", "aurangabad", "thane", "navi mumbai", "ludhiana", "amritsar", 
                            "jalandhar", "chandigarh", "mohali", "panchkula", "lucknow", "kanpur", 
                            "ghaziabad", "meerut", "varanasi", "agra", "allahabad", "prayagraj", "dehradun", 
                            "haridwar", "jaipur", "jodhpur", "udaipur", "raipur", "bilaspur", "ranchi", 
                            "jamshedpur", "patna", "bhubaneswar", "cuttack", "guwahati", "shillong", 
                            "imphal", "itanagar", "dispur", "gangtok", "kohima", "aizawl", "agartala", 
                            "bhopal", "indore", "gwalior", "jabalpur", "ujjain", "jammu", "srinagar", 
                            "vijayawada", "visakhapatnam", "vizag", "tirupati", "guntur", "nellore", 
                            "warangal", "madurai", "tiruchirappalli", "salem", "tiruppur", "vellore", 
                            "pondicherry", "puducherry", "goa", "panaji", "margao", "daman", "diu"
                        ]
                        if not any(ind in combined_loc for ind in indian_indicators):
                            self.log.info(f"Rejecting company {company_name} because it does not match target country '{target_country}'. Location: {lead_data.get('location')}, Address: {lead_data.get('address')}")
                            continue
                    elif target_country == "United States":
                        us_indicators = [
                            "usa", "united states", " u.s.", "america", "alaska", "alabama", "arkansas", 
                            "arizona", "california", "colorado", "connecticut", "delaware", "florida", 
                            "georgia", "hawaii", "iowa", "idaho", "illinois", "indiana", "kansas", 
                            "kentucky", "louisiana", "massachusetts", "maryland", "maine", "michigan", 
                            "minnesota", "missouri", "mississippi", "montana", "north carolina", 
                            "north dakota", "nebraska", "new hampshire", "new jersey", "new mexico", 
                            "nevada", "new york", "ohio", "oklahoma", "oregon", "pennsylvania", 
                            "rhode island", "south carolina", "south dakota", "tennessee", "texas", 
                            "utah", "virginia", "vermont", "washington", "wisconsin", "west virginia", 
                            "wyoming", "nyc", "la ", "los angeles", "sf ", "san francisco", "chicago", 
                            "boston", "seattle", "austin", "dallas", "houston", "miami", "atlanta", 
                            "denver", "phoenix", "detroit", "philadelphia", "portland", "las vegas"
                        ]
                        if not any(ind in combined_loc for ind in us_indicators):
                            self.log.info(f"Rejecting company {company_name} because it does not match target country '{target_country}'. Location: {lead_data.get('location')}, Address: {lead_data.get('address')}")
                            continue

                # LinkedIn decision maker enrichment.
                # Skip if Instantly.ai already pre-filled the DM data —
                # no need to spend Serper credits finding what we already have.
                instantly_dm_name = result.get("dm_name", "")
                instantly_dm_email = result.get("dm_email", "")
                if instantly_dm_name:
                    lead_data["decision_maker_name"] = instantly_dm_name.split()[0] if instantly_dm_name else ""
                    lead_data["decision_maker_full_name"] = instantly_dm_name
                    lead_data["decision_maker_title"] = result.get("dm_title", "")
                    lead_data["decision_maker_linkedin"] = result.get("dm_linkedin", "")
                    if instantly_dm_email:
                        merged_emails = list(dict.fromkeys([instantly_dm_email] + lead_data.get("contact_emails", [])))
                        lead_data["contact_emails"] = merged_emails
                    lead_data["email_guesses"] = []
                    self.log.debug(f"[Instantly] Pre-filled DM for {lead_data.get('company_name','')}: {instantly_dm_name}")
                else:
                    domain = url.replace("https://", "").replace("http://", "").split("/")[0]
                    dm = enrich_decision_maker(lead_data.get("company_name", ""), domain)
                    lead_data["decision_maker_name"] = dm.get("name", "")
                    lead_data["decision_maker_full_name"] = dm.get("full_name", "")
                    lead_data["decision_maker_title"] = dm.get("title", "")
                    lead_data["decision_maker_linkedin"] = dm.get("linkedin_url", "")
                    all_emails = list(dict.fromkeys(
                        lead_data.get("contact_emails", []) + dm.get("email_guesses", [])
                    ))
                    lead_data["contact_emails"] = all_emails
                    lead_data["email_guesses"] = dm.get("email_guesses", [])

                # Tech stack detection
                lead_data["tech_stack"] = detect_tech_stack(url, lead_data.get("company_name", ""))

                # Deduplication: skip if processed in last 24 hours
                if is_duplicate_lead(company_name):
                    self.log.info(f"Skipping duplicate lead: {company_name}")
                    continue

                # Hallucination guard on extracted data
                guard = guard_llm_response(
                    response_text=json.dumps(lead_data),
                    rag_context=scraped,
                    strict=False,
                )
                if guard["action"] == "warn":
                    log_hallucination_event("research_agent", guard, correlation_id)
                    self.log.warning(f"Hallucination warning for {company_name}: {guard['warnings']}")

                # Mark as seen in Redis (dedup)
                mark_lead_seen(company_name)

                lead_data.setdefault("id", str(uuid.uuid4())[:8])
                lead_data.setdefault("qualification_score", None)
                lead_data.setdefault("qualification_reason", None)
                lead_data.setdefault("outreach_draft", None)
                lead_data.setdefault("status", "researched")

                new_leads.append(lead_data)
                self.log.info(f"Lead extracted: {company_name}")

            except Exception as e:
                self.log.error(f"Error processing {url}: {e}")
                continue

        self.log.info(f"Research complete: {len(new_leads)} leads extracted")

        # Use replace semantics: combine existing leads with newly found ones
        existing_leads = state.get("leads", [])
        all_leads = existing_leads + new_leads

        return {
            **state,
            "leads": all_leads,
            "messages": [f"Research Agent: Found {len(new_leads)} leads for '{keyword}'"],
            "iteration": state.get("iteration", 0) + 1,
            "next": "qualify" if new_leads else "END",
        }


# LangGraph-compatible function wrapper
def research_agent(state: LeadState) -> LeadState:
    agent = ResearchAgent(correlation_id=state.get("correlation_id"))
    return agent.run(state)
