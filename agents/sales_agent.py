"""
Sales Agent
-----------
Responsibility: Generate personalized outreach emails for qualified leads.
Uses RAG to ensure product claims are grounded in real HumanMaximizer content.

Extends BaseAgent for retry, caching, structured logging, hallucination guard.
"""
import json
from graph.state import LeadState
from agents.base import BaseAgent
from rag.retriever import retrieve_hrms_context
from rag.hallucination_guard import guard_llm_response
from observability.langsmith_tracer import stage_timer, log_hallucination_event
from core.config import get_settings

settings = get_settings()

OUTREACH_PROMPT = """You are a B2B sales copywriter for HumanMaximizer, an HRMS software company.

Our product capabilities (use ONLY what is stated below, do not invent features):
{rag_context}

Prospect company details:
{lead_info}

Write a personalized cold outreach email that:
1. Opens with something specific about their company (not generic)
2. Mentions a specific pain point they likely face
3. Connects our HRMS solution to that pain point using ONLY the product info above
4. Has a clear, low-friction CTA (demo, quick call)
5. Is concise (max 150 words)

Respond with JSON ONLY:
{{
  "subject": "...",
  "email_body": "...",
  "follow_up_note": "...(internal note: why this angle was chosen)"
}}
"""


class SalesAgent(BaseAgent):
    name = "sales_agent"

    @stage_timer("sales_agent")
    def run(self, state: LeadState) -> LeadState:
        leads = state.get("leads", [])
        qualified = [l for l in leads if l.get("status") == "qualified"]
        correlation_id = state.get("correlation_id", self.correlation_id)

        self.log.info(f"Generating outreach for {len(qualified)} qualified leads")

        for lead in qualified:
            company_name = lead.get("company_name", "Unknown")
            self.log.info(f"Drafting outreach for: {company_name}")

            pain_points = " ".join(lead.get("pain_points", []))
            description = lead.get("description", "") + " " + pain_points
            rag_context = retrieve_hrms_context(description)

            prompt = OUTREACH_PROMPT.format(
                rag_context=rag_context,
                lead_info=json.dumps({
                    "company_name": lead.get("company_name"),
                    "industry": lead.get("industry"),
                    "size": lead.get("size"),
                    "description": lead.get("description"),
                    "pain_points": lead.get("pain_points"),
                    "decision_makers": lead.get("decision_makers"),
                    "qualification_reason": lead.get("qualification_reason"),
                }, indent=2),
            )

            try:
                # Creative temperature for email writing, no cache (each email should be unique)
                raw = self.call_llm(
                    prompt,
                    temperature=settings.llm_temperature_creative,
                    max_tokens=settings.llm_max_tokens_creative,
                    use_cache=False,
                )
                result = self.parse_json_response(raw)

                # Hallucination guard, strict for outreach (don't claim features we don't have)
                guard = guard_llm_response(
                    response_text=result.get("email_body", ""),
                    rag_context=rag_context,
                    strict=False,
                )
                if guard["action"] == "warn":
                    log_hallucination_event("sales_agent", guard, correlation_id)
                    self.log.warning(f"Hallucination warning in outreach for {company_name}")
                elif guard["action"] == "reject":
                    self.log.error(f"Outreach for {company_name} rejected by hallucination guard")
                    lead["outreach_draft"] = None
                    continue

                lead["outreach_draft"] = {
                    "subject": result.get("subject", ""),
                    "email_body": result.get("email_body", ""),
                    "follow_up_note": result.get("follow_up_note", ""),
                    "hallucination_confidence": guard["confidence"],
                }
                lead["status"] = "outreach_ready"
                self.log.info(f"Outreach ready for: {company_name}")

            except Exception as e:
                self.log.error(f"Error generating outreach for {company_name}: {e}")
                lead["outreach_draft"] = None

        # leads were mutated in-place above (outreach_draft + status updated per lead).
        # Return the same list, no reconstruction needed (avoids double-counting).
        outreach_count = sum(1 for l in leads if l.get("outreach_draft"))

        self.log.info(f"Sales Agent complete: {outreach_count} outreach drafts generated")

        return {
            **state,
            "leads": leads,
            "messages": [f"Sales Agent: {outreach_count} outreach drafts generated"],
            "next": "END",
        }


def sales_agent(state: LeadState) -> LeadState:
    agent = SalesAgent(correlation_id=state.get("correlation_id"))
    return agent.run(state)
