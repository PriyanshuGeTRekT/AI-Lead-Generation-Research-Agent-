from typing import TypedDict, List, Optional, Annotated
import operator


class Lead(TypedDict):
    # ── Research Agent fields ─────────────────────────────────────────────────
    id: str                                  # 8-char UUID, set by research_agent
    company_name: str
    website: str
    industry: str
    size: Optional[str]
    location: Optional[str]
    address: Optional[str]                   # Physical office address if found
    phone: Optional[str]                     # Contact phone number if found
    description: Optional[str]
    decision_makers: Optional[List[str]]
    contact_emails: Optional[List[str]]
    pain_points: Optional[List[str]]
    status: str  # researched | qualified | disqualified | outreach_ready | pending_review

    # ── Qualification Agent fields ────────────────────────────────────────────
    qualification_score: Optional[float]     # 0.0-10.0
    qualification_reason: Optional[str]      # 2-3 sentence score explanation
    key_signals: Optional[List[str]]         # top 3 signals driving the score
    recommended_action: Optional[str]        # outreach | nurture | disqualify
    summary: Optional[str]                   # human-readable card for dashboard + Slack

    # ── Sales Agent fields ────────────────────────────────────────────────────
    outreach_draft: Optional[dict]           # {subject, email_body, follow_up_note, hallucination_confidence}


class LeadState(TypedDict):
    keyword: str                              # Input: business category to search
    leads: List[Lead]                         # All leads, replaced (not appended) each step
    messages: Annotated[List[str], operator.add]  # Agent message log (appended each step)
    next: str                                 # Which agent runs next
    iteration: int                            # Loop counter (prevent infinite loops)
    errors: Annotated[List[str], operator.add]
    correlation_id: Optional[str]             # Trace ID linking all agent logs for one run
