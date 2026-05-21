"""
Qualification Agent
-------------------
Responsibility: Score and qualify each lead based on HRMS fit.
Uses RAG to ground scoring in actual HumanMaximizer product knowledge.
Input:  LeadState with researched leads
Output: Leads with qualification_score (0-10) and qualification_reason

Extends BaseAgent for retry, caching, structured logging.
"""
import json
from graph.state import LeadState
from agents.base import BaseAgent
from rag.retriever import retrieve_hrms_context
from rag.hallucination_guard import guard_llm_response
from observability.langsmith_tracer import stage_timer, log_hallucination_event
from core.config import get_settings
from models.schemas import QualificationResult

settings = get_settings()


def _score_bar(score: float) -> str:
    """Return a compact visual score bar, e.g. '████████░░ 8.2'"""
    filled = round(score)
    empty = 10 - filled
    return "█" * filled + "░" * empty


# Industries that indicate the company SELLS HR software (competitors, not prospects)
_HRMS_VENDOR_KEYWORDS = {
    "hrms software", "hr software", "payroll software", "hris", "hcm software",
    "human resource software", "hr saas", "hr platform", "hr tech", "hrtech",
    "workforce management software", "attendance software",
}


def _is_hrms_vendor(lead: dict) -> bool:
    """Return True if this company sells HRMS/HR software (i.e., is a competitor)."""
    industry = (lead.get("industry") or "").lower()
    description = (lead.get("description") or "").lower()
    combined = industry + " " + description
    return any(kw in combined for kw in _HRMS_VENDOR_KEYWORDS)


QUALIFICATION_PROMPT = """You are a B2B sales qualification expert for an HRMS software company called HumanMaximizer.

Your product knowledge (from our HRMS product, use ONLY this, do not fabricate features):
{rag_context}

Company to qualify:
{lead_info}

Score this lead from 0-10 based on:
- Likelihood they NEED HRMS software (employee management, payroll, attendance, recruitment)
- Company size (10-1000 employees is ideal; larger is fine)
- Industry fit (any industry with significant workforce: manufacturing, retail, IT services, logistics, healthcare, education, etc.)
- Growth signals (hiring, expanding, new offices)
- Decision maker accessibility

CRITICAL RULE: If the company SELLS HR software, HRMS, payroll software, or is an HR tech vendor,
they are a COMPETITOR — score them 1 and set recommended_action to "disqualify (competitor)".

Respond with JSON ONLY:
{{
  "score": <float 0-10>,
  "reasoning": "...(2-3 sentences explaining the score)",
  "key_signals": ["...", "...", "..."],
  "recommended_action": "...(how to approach this lead, or 'disqualify (competitor)' if they sell HR software)"
}}
"""


class QualificationAgent(BaseAgent):
    name = "qualification_agent"

    @stage_timer("qualification_agent")
    def run(self, state: LeadState) -> LeadState:
        leads = state.get("leads", [])
        researched = [l for l in leads if l.get("status") == "researched"]
        correlation_id = state.get("correlation_id", self.correlation_id)

        self.log.info(f"Qualifying {len(researched)} leads (threshold: {settings.qualification_threshold})")

        qualified_leads = []
        disqualified_leads = []

        for lead in researched:
            company_name = lead.get("company_name", "Unknown")
            self.log.info(f"Scoring: {company_name}")

            # Fast-path: auto-disqualify competitors (companies that sell HRMS software)
            if _is_hrms_vendor(lead):
                self.log.info(f"Auto-disqualified competitor: {company_name}")
                lead["qualification_score"] = 1.0
                lead["qualification_reason"] = (
                    f"{company_name} is an HRMS/HR software vendor — a competitor, not a prospect. "
                    "They already have their own HR solution and are not a sales target."
                )
                lead["key_signals"] = ["sells HR/HRMS software", "competitor"]
                lead["recommended_action"] = "disqualify (competitor)"
                lead["status"] = "disqualified"
                lead["summary"] = (
                    f"{company_name}  |  {lead.get('industry', '')}  |  "
                    f"{lead.get('location', '')}  |  {lead.get('size', '')}\n"
                    f"Score: 1.0/10  █░░░░░░░░░\n"
                    f"COMPETITOR — sells HRMS software, not a prospect.\n"
                    f"Key signals: sells HR/HRMS software · competitor\n"
                    f"Decision maker: N/A"
                )
                disqualified_leads.append(lead)
                continue

            # RAG retrieval for grounding
            description = lead.get("description", "") + " " + " ".join(lead.get("pain_points", []))
            rag_context = retrieve_hrms_context(description)

            prompt = QUALIFICATION_PROMPT.format(
                rag_context=rag_context,
                lead_info=json.dumps(lead, indent=2),
            )

            try:
                # Use structured output to get a validated QualificationResult instance
                result = self.call_llm_structured(
                    prompt,
                    QualificationResult,
                    temperature=settings.llm_temperature_extract,
                )

                score = result.score
                reasoning = result.reasoning

                # Hallucination guard on qualification output
                guard = guard_llm_response(
                    response_text=json.dumps(result.model_dump()),
                    rag_context=rag_context,
                    strict=False,
                )
                if guard["action"] == "warn":
                    log_hallucination_event("qualification_agent", guard, correlation_id)
                    self.log.warning(f"Hallucination warning for {company_name}: {guard['warnings']}")

                lead["qualification_score"] = score
                lead["qualification_reason"] = reasoning
                lead["key_signals"] = result.key_signals
                lead["recommended_action"] = result.recommended_action

                # Build a clean, human-readable summary for dashboard + Slack display
                score_bar = _score_bar(score)
                signals_str = " · ".join(result.key_signals[:3]) if result.key_signals else "—"
                size_str = lead.get("size") or lead.get("employee_count") or "unknown size"
                industry_str = lead.get("industry", "company")
                location_str = lead.get("location", "India")
                dm_str = lead.get("decision_maker") or (
                    lead.get("decision_makers", ["Unknown"])[0]
                    if lead.get("decision_makers") else "Unknown"
                )
                lead["summary"] = (
                    f"{lead.get('company_name', 'Unknown Company')}  |  "
                    f"{industry_str}  |  {location_str}  |  {size_str}\n"
                    f"Score: {score:.1f}/10  {score_bar}\n"
                    f"{reasoning}\n"
                    f"Key signals: {signals_str}\n"
                    f"Decision maker: {dm_str}"
                )

                if score >= settings.qualification_threshold:
                    lead["status"] = "qualified"
                    qualified_leads.append(lead)
                    self.log.info(f"QUALIFIED (score: {score}): {company_name}")
                else:
                    lead["status"] = "disqualified"
                    disqualified_leads.append(lead)
                    self.log.info(f"DISQUALIFIED (score: {score}): {company_name}")

            except Exception as e:
                self.log.error(f"Error scoring {company_name}: {e}")
                lead["status"] = "disqualified"
                lead["qualification_score"] = 0.0
                lead["qualification_reason"] = f"Scoring error: {type(e).__name__}"
                disqualified_leads.append(lead)

        # leads were mutated in-place above (status updated per lead).
        # Return the same list, no reconstruction needed (avoids double-counting).
        self.log.info(
            f"Qualification complete: {len(qualified_leads)} qualified, "
            f"{len(disqualified_leads)} disqualified"
        )

        return {
            **state,
            "leads": leads,
            "messages": [
                f"Qualification Agent: {len(qualified_leads)} qualified, "
                f"{len(disqualified_leads)} disqualified"
            ],
            "next": "sales" if leads else "END",
        }


def qualification_agent(state: LeadState) -> LeadState:
    agent = QualificationAgent(correlation_id=state.get("correlation_id"))
    return agent.run(state)
