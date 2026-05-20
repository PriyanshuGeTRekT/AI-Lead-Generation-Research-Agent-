from typing import TypedDict, List, Optional, Annotated
import operator


class Lead(TypedDict):
    company_name: str
    website: str
    industry: str
    size: Optional[str]
    location: Optional[str]
    description: Optional[str]
    decision_makers: Optional[List[str]]
    contact_emails: Optional[List[str]]
    pain_points: Optional[List[str]]
    qualification_score: Optional[float]
    qualification_reason: Optional[str]
    outreach_draft: Optional[str]
    status: str  # researched | qualified | disqualified | outreach_ready


class LeadState(TypedDict):
    keyword: str                              # Input: business category to search
    leads: List[Lead]                         # All leads — replaced (not appended) each step
    current_lead: Optional[Lead]              # Lead being processed right now
    rag_context: Optional[str]                # Retrieved context from vector DB
    messages: Annotated[List[str], operator.add]  # Agent message log (appended each step)
    next: str                                 # Which agent runs next
    iteration: int                            # Loop counter (prevent infinite loops)
    errors: Annotated[List[str], operator.add]
    correlation_id: Optional[str]             # Trace ID linking all agent logs for one run
