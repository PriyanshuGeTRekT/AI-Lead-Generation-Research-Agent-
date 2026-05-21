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
from tools.web_search import search_companies_multi_source, scrape_company_info
from cache.redis_client import is_duplicate_lead, mark_lead_seen
from rag.hallucination_guard import guard_llm_response
from observability.langsmith_tracer import stage_timer, log_hallucination_event
from core.config import get_settings

settings = get_settings()

RESEARCH_PROMPT = """You are a B2B lead research specialist.
Given search results about companies, extract structured lead information.

Focus on companies that could benefit from HRMS (Human Resource Management Software).
Look for: company name, website, industry, size, location, and what they do.

Search Results:
{search_results}

Scraped Website Content:
{scraped_content}

Extract lead information and respond with a JSON object ONLY (no explanation):
{{
  "company_name": "...",
  "website": "...",
  "industry": "...",
  "size": "...(e.g. 50-200 employees)",
  "location": "...",
  "description": "...(what the company does, 2-3 sentences)",
  "decision_makers": ["...", "..."],
  "contact_emails": [],
  "pain_points": ["...", "...(likely HR challenges they face)"],
  "status": "researched"
}}

If you cannot extract valid company info, return: {{"status": "invalid"}}
"""


class ResearchAgent(BaseAgent):
    name = "research_agent"

    @stage_timer("research_agent")
    def run(self, state: LeadState) -> LeadState:
        keyword = state["keyword"]
        correlation_id = state.get("correlation_id", self.correlation_id)
        self.log.info(f"Starting search for keyword: '{keyword}'")

        search_results = search_companies_multi_source(keyword)

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

        # Cap results at max_leads_per_run. Domain filtering already handled upstream
        # by _BLOCKED_DOMAINS in tools/web_search.py (Serper path) and the
        # search_companies_multi_source dedup step. A redundant SKIP_DOMAINS list
        # here was removed to avoid maintaining two copies of the same allowlist.
        valid_results = [
            r for r in search_results if r.get("url")
        ][:settings.max_leads_per_run]

        for result in valid_results:
            url = result.get("url", "")

            # Scrape website content
            scraped = scrape_company_info(url)

            prompt = RESEARCH_PROMPT.format(
                search_results=json.dumps(result, indent=2),
                scraped_content=scraped[:1500],
            )

            try:
                raw = self.call_llm(prompt, temperature=settings.llm_temperature_extract)
                lead_data = self.parse_json_response(raw)

                if lead_data.get("status") == "invalid":
                    self.log.debug(f"LLM marked lead as invalid for URL: {url}")
                    continue

                company_name = lead_data.get("company_name", "")

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
