"""
Sales Agent
-----------
Responsibility: Generate full outreach sequences for qualified leads.
Includes: email verification, 4-touch email sequence, hallucination guard,
Slack HITL review, and CRM push on approval.

Extends BaseAgent for retry, caching, structured logging, hallucination guard.
"""
import json
from graph.state import LeadState
from agents.base import BaseAgent
from notifications.slack import send_lead_review_request
from rag.retriever import retrieve_hrms_context
from rag.hallucination_guard import guard_llm_response
from tools.email_verifier import verify_emails, best_emails
from observability.langsmith_tracer import stage_timer, log_hallucination_event
from observability.event_bus import emit
from agents.buyer_simulator import simulate_arena
from core.config import get_settings

settings = get_settings()

# ── Day 1: Cold intro ──────────────────────────────────────────────────────────
DAY1_PROMPT = """You are a B2B sales copywriter for HumanMaximizer, an HRMS software company.

Our product capabilities (use ONLY what is stated below, do not invent features):
{rag_context}

Prospect company details:
{lead_info}

Current HR tech stack: {tech_stack}
Pitch angle based on their stack: {pitch_angle}

Write a personalized cold outreach email (Day 1) that:
1. Opens with ONE specific insight about their company or industry (not generic)
2. Addresses decision maker by first name if known, else "Hi [Name]"
3. Mentions their specific pain point and connects it to HumanMaximizer
4. Uses the pitch angle above to differentiate vs their current stack
5. Has a single, low-friction CTA (15-min call or free demo link)
6. Is under 130 words
7. Signs off: "Best regards,\\n{sender_name}\\nHumanMaximizer | humanmaximizer.com"

Respond with JSON ONLY:
{{
  "subject": "...",
  "email_body": "...",
  "follow_up_note": "...(internal: why this angle was chosen)"
}}"""

# ── Day 3: Follow-up ───────────────────────────────────────────────────────────
DAY3_PROMPT = """Write a short Day 3 follow-up email for a cold outreach sequence.

Context:
- Company: {company_name}
- First email subject: {day1_subject}
- Decision maker first name: {dm_name}
- Their main pain point: {main_pain_point}
- Sender: {sender_name}, HumanMaximizer

The follow-up should:
1. Reference the previous email naturally (don't repeat it)
2. Add ONE new piece of value (a stat, a quick result, or a relevant question)
3. Be under 80 words
4. Keep same CTA (15-min call)

Respond with JSON ONLY:
{{
  "subject": "Re: {day1_subject}",
  "email_body": "..."
}}"""

# ── Day 7: Value email ─────────────────────────────────────────────────────────
DAY7_PROMPT = """Write a Day 7 value email for a B2B cold outreach sequence.

Context:
- Company: {company_name}
- Industry: {industry}
- Decision maker: {dm_name}
- Their pain: {main_pain_point}
- Sender: {sender_name}, HumanMaximizer
- Product capability: {rag_context}

This email should:
1. Lead with a specific insight or result relevant to their industry
2. NOT ask to buy — just provide value and keep the conversation alive
3. End with a soft question that invites a reply
4. Be under 100 words

Respond with JSON ONLY:
{{
  "subject": "...(something curiosity-driven, not salesy)",
  "email_body": "..."
}}"""

# ── Day 14: Break-up email ─────────────────────────────────────────────────────
DAY14_PROMPT = """Write a Day 14 "break-up" email — the final touch in a cold outreach sequence.

Context:
- Company: {company_name}
- Decision maker: {dm_name}
- Sender: {sender_name}, HumanMaximizer

Break-up emails should:
1. Be honest — say this is your last email
2. Be brief (under 60 words)
3. Leave the door open without pressure
4. Sometimes get replies because they feel final and human

Respond with JSON ONLY:
{{
  "subject": "Closing the loop — {company_name}",
  "email_body": "..."
}}"""


class SalesAgent(BaseAgent):
    name = "sales_agent"

    def _build_lead_info(self, lead: dict) -> str:
        """Compact lead summary for the LLM prompt."""
        return json.dumps({
            "company_name": lead.get("company_name"),
            "industry": lead.get("industry"),
            "size": lead.get("size"),
            "location": lead.get("location"),
            "description": lead.get("description"),
            "pain_points": lead.get("pain_points"),
            "decision_maker_name": lead.get("decision_maker_name", ""),
            "decision_maker_title": lead.get("decision_maker_title", ""),
            "qualification_reason": lead.get("qualification_reason"),
        }, indent=2)

    def _generate_sequence(self, lead: dict, rag_context: str) -> tuple:
        """
        Generate the full 4-touch sequence (Day 1/3/7/14) in ONE LLM call.
        Returns (outreach_draft dict, follow_up_sequence list).
        """
        company = lead.get("company_name", "Unknown")
        dm_name = lead.get("decision_maker_name") or "there"
        main_pain = (lead.get("pain_points") or ["HR efficiency"])[0]
        tech = lead.get("tech_stack") or {}
        tech_stack_str = ", ".join(tech.get("current_tools", [])) or "not detected"
        pitch_angle = tech.get("pitch_angle", "Focus on automation and time savings.")

        prompt = f"""You are a B2B sales copywriter for HumanMaximizer, an Indian HRMS company.

Product capabilities (use ONLY what's stated, do not invent features):
{rag_context[:900]}

Prospect:
{self._build_lead_info(lead)}
Current HR stack: {tech_stack_str}
Pitch angle: {pitch_angle}
Decision-maker first name (else 'there'): {dm_name}
Main pain point: {main_pain}
Sender sign-off: {settings.sender_name}, HumanMaximizer | humanmaximizer.com

Write a 4-touch cold outreach sequence. Each email under 120 words, specific, one low-friction CTA,
no hype words. Respond with JSON ONLY:
{{
  "day1":  {{"subject": "...", "email_body": "...(cold intro, company-specific insight)", "follow_up_note": "...(why this angle)"}},
  "day3":  {{"subject": "Re: ...", "email_body": "...(short follow-up, one new value point)"}},
  "day7":  {{"subject": "...", "email_body": "...(value email, soft question, no hard ask)"}},
  "day14": {{"subject": "Closing the loop — {company}", "email_body": "...(brief break-up, leaves door open)"}}
}}"""

        data = self.parse_json_response(
            self.call_llm(prompt, temperature=settings.llm_temperature_creative, max_tokens=1100, use_cache=False)
        )
        d1, d3 = data.get("day1", {}), data.get("day3", {})
        d7, d14 = data.get("day7", {}), data.get("day14", {})

        outreach_draft = {
            "subject": d1.get("subject", ""),
            "email_body": d1.get("email_body", ""),
            "follow_up_note": d1.get("follow_up_note", ""),
        }
        follow_up_sequence = [
            {"day": 3,  "subject": d3.get("subject", ""),  "email_body": d3.get("email_body", "")},
            {"day": 7,  "subject": d7.get("subject", ""),  "email_body": d7.get("email_body", "")},
            {"day": 14, "subject": d14.get("subject", ""), "email_body": d14.get("email_body", "")},
        ]
        return outreach_draft, follow_up_sequence

    @stage_timer("sales_agent")
    def run(self, state: LeadState) -> LeadState:
        leads = state.get("leads", [])
        qualified = [l for l in leads if l.get("status") == "qualified"]
        correlation_id = state.get("correlation_id", self.correlation_id)
        run_id = state.get("run_id")
        emit(run_id, "stage_start", agent="sales_agent", stage="sales",
             message="Drafting + buyer-simulating sequences")

        # Only leads that passed qualification should get outreach drafts.
        qualified_for_sequences = qualified

        self.log.info(
            f"Generating outreach sequences for all {len(qualified_for_sequences)} leads"
        )

        for lead in qualified_for_sequences:
            company_name = lead.get("company_name", "Unknown")
            self.log.info(f"Drafting 4-email sequence for: {company_name}")

            # ── Email verification ──────────────────────────────────────────────
            all_emails = (lead.get("contact_emails") or []) + (lead.get("email_guesses") or [])
            if all_emails:
                verified = verify_emails(list(dict.fromkeys(all_emails)))
                lead["verified_emails"] = verified
                # Replace contact_emails with verified-only list (quality: high or medium)
                lead["contact_emails"] = [
                    r["email"] for r in verified
                    if r["valid"] and r["quality"] in ("high", "medium")
                ][:5]
                self.log.info(
                    f"Email verification for {company_name}: "
                    f"{len(lead['contact_emails'])}/{len(all_emails)} valid"
                )

            # ── RAG context ─────────────────────────────────────────────────────
            pain_points = " ".join(lead.get("pain_points", []))
            description = lead.get("description", "") + " " + pain_points
            rag_context = retrieve_hrms_context(description)

            try:
                outreach_draft, follow_up_sequence = self._generate_sequence(lead, rag_context)

                # ── Buyer Simulation & Email Arena ──────────────────────────────
                # Role-play the decision maker, A/B the Day-1 email against a sharper
                # Variant B, and ship the self-play winner. Fail-safe: keep Variant A.
                sim = simulate_arena(
                    self, lead,
                    outreach_draft.get("subject", ""),
                    outreach_draft.get("email_body", ""),
                )
                if sim:
                    lead["simulation"] = sim
                    winner = sim.get("winner")
                    wv = next((v for v in sim.get("variants", []) if v.get("variant") == winner), None)
                    if wv and winner == "B" and wv.get("email_body"):
                        outreach_draft["subject"] = wv.get("subject") or outreach_draft.get("subject")
                        outreach_draft["email_body"] = wv.get("email_body")
                    emit(run_id, "email", agent="sales_agent", stage="sales",
                         message=f"Variant {winner} won the arena for {company_name}", lead=lead)
                else:
                    emit(run_id, "email", agent="sales_agent", stage="sales",
                         message=f"Sequence drafted for {company_name}", lead=lead)

                # Hallucination guard on Day 1 email body
                # strict=False: sales emails naturally echo lead data (employee counts,
                # company names) which the strict guard incorrectly flags as hallucinations.
                guard = guard_llm_response(
                    response_text=outreach_draft.get("email_body", ""),
                    rag_context=rag_context,
                    strict=False,
                )
                if guard["action"] in ("warn", "reject"):
                    log_hallucination_event("sales_agent", guard, correlation_id)
                    self.log.warning(
                        f"Hallucination {guard['action']} in Day 1 email for {company_name}: {guard['warnings']}"
                    )

                outreach_draft["hallucination_confidence"] = guard["confidence"]
                outreach_draft["hallucination_action"] = guard["action"]
                outreach_draft["hallucination_warnings"] = guard["warnings"]
                lead["outreach_draft"] = outreach_draft
                lead["follow_up_sequence"] = follow_up_sequence

                self.log.info(
                    f"4-email sequence ready for {company_name} | "
                    f"verified emails: {len(lead.get('contact_emails', []))}"
                )

                # Human-in-the-loop: Slack review if configured
                if settings.slack_webhook_url:
                    lead["status"] = "pending_review"
                    send_lead_review_request(lead)
                    self.log.info(f"Lead sent to Slack for review: {company_name}")
                else:
                    lead["status"] = "outreach_ready"
                    self.log.info(f"Outreach ready: {company_name}")

            except Exception as e:
                self.log.error(f"Error generating sequence for {company_name}: {e}")
                lead["outreach_draft"] = None

        outreach_count = sum(1 for l in leads if l.get("outreach_draft"))
        self.log.info(f"Sales Agent complete: {outreach_count} sequences generated")
        emit(run_id, "stage_end", agent="sales_agent", stage="sales",
             message=f"{outreach_count} sequences generated")

        return {
            **state,
            "leads": leads,
            "messages": [f"Sales Agent: {outreach_count} 4-email sequences generated"],
            "next": "END",
        }


def sales_agent(state: LeadState) -> LeadState:
    agent = SalesAgent(correlation_id=state.get("correlation_id"))
    return agent.run(state)
