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

QUALIFICATION_PROMPT = """You are a B2B sales qualification expert for an HRMS software company.

Your product knowledge (from our HRMS product, use ONLY this, do not fabricate features):
{rag_context}

Company to qualify:
{lead_info}

Score this lead from 0-10 based on:
- Likelihood they need HRMS software (employee management, payroll, attendance, recruitment)
- Company size (10-500 employees is ideal)
- Industry fit (any industry with significant workforce)
- Growth signals (hiring, expanding)
- Decision maker accessibility

Respond with JSON ONLY:
{{
  "qualification_score": <float 0-10>,
  "qualification_reason": "...(2-3 sentences explaining the score)",
  "pain_points_identified": ["...", "..."],
  "recommended_approach": "...(how to approach this lead)"
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
            "next": "sales" if qualified_leads else "END",
        }


def qualification_agent(state: LeadState) -> LeadState:
    agent = QualificationAgent(correlation_id=state.get("correlation_id"))
    return agent.run(state)
