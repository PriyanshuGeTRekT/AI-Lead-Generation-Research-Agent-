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
    phone_type: Optional[str]                # 'mobile' | 'landline'
    phone_source: Optional[str]              # 'google_places' | 'company_website'
    contact_confidence: Optional[str]        # 'high' | 'medium' | 'low'
    employee_band: Optional[str]             # e.g. "51-200 employees" (LinkedIn band)
    employee_min: Optional[int]
    employee_max: Optional[int]
    description: Optional[str]
    decision_makers: Optional[List[str]]
    contact_emails: Optional[List[str]]
    pain_points: Optional[List[str]]
    status: str  # researched | qualified | disqualified | outreach_ready | pending_review

    # ── LinkedIn Enrichment fields ────────────────────────────────────────────
    decision_maker_name: Optional[str]       # First name of HR/People DM
    decision_maker_full_name: Optional[str]  # Full name
    decision_maker_title: Optional[str]      # Job title
    decision_maker_linkedin: Optional[str]   # LinkedIn profile URL
    email_guesses: Optional[List[str]]       # Inferred email patterns from name+domain

    # ── Tech Stack Detection fields ───────────────────────────────────────────
    tech_stack: Optional[dict]               # {current_tools, maturity, signals, pitch_angle}

    # ── Qualification Agent fields ────────────────────────────────────────────
    qualification_score: Optional[float]     # 0.0-10.0
    qualification_reason: Optional[str]      # 2-3 sentence score explanation
    key_signals: Optional[List[str]]         # top 3 signals driving the score
    recommended_action: Optional[str]        # outreach | nurture | disqualify
    summary: Optional[str]                   # human-readable card for dashboard + Slack

    # ── Sales Agent fields ────────────────────────────────────────────────────
    outreach_draft: Optional[dict]           # {subject, email_body, follow_up_note, hallucination_confidence}
    follow_up_sequence: Optional[List[dict]] # [{day, subject, email_body}, ...] — 3 follow-ups
    verified_emails: Optional[List[dict]]    # [{email, valid, quality}, ...] from email verifier

    # ── Signature-feature payloads (optional, never required) ──────────────────
    debate: Optional[dict]                   # Adversarial debate transcript + consensus
    simulation: Optional[dict]               # Buyer simulation / email arena result


class LeadState(TypedDict):
    keyword: str                              # Input: business category to search
    leads: List[Lead]                         # All leads, replaced (not appended) each step
    messages: Annotated[List[str], operator.add]  # Agent message log (appended each step)
    next: str                                 # Which agent runs next
    iteration: int                            # Loop counter (prevent infinite loops)
    errors: Annotated[List[str], operator.add]
    correlation_id: Optional[str]             # Trace ID linking all agent logs for one run
    max_leads: Optional[int]                  # Per-run cap; overrides config default
    country: Optional[str]                    # geo filter: country (India-only ICP)
    region: Optional[str]                     # geo filter: state/region or preset
    exclude_with_hrms: Optional[bool]         # drop companies already running an HRMS
    mode: Optional[str]                       # 'discover' | 'company' (find a named company)
    fast: Optional[bool]                      # fast mode: deterministic, no per-candidate LLM
    run_id: Optional[str]                     # Theater stream id for live agent events
    run_id: Optional[str]                     # Theater stream id (matches the pollable job id)
    country: Optional[str]                    # Geo filter: target country
    region: Optional[str]                     # Geo filter: target state/region
    exclude_with_hrms: Optional[bool]         # Drop companies that already run an HRMS
