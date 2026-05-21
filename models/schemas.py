"""
LLM Output Schemas
-------------------
Pydantic models used with LangChain .with_structured_output() to enforce
schema compliance at the LLM call level. Eliminates manual JSON parsing
for structured agent calls.

These schemas are passed to BaseAgent.call_llm_structured() which uses
llm.with_structured_output(schema) to get validated model instances back
instead of raw strings.
"""
from pydantic import BaseModel, Field
from typing import List


class LeadExtraction(BaseModel):
    """Schema for research agent: extract structured company info from scraped text."""
    company_name: str = Field(description="Full legal company name")
    industry: str = Field(description="Industry sector, e.g. Manufacturing, IT Services, Retail")
    employee_count: str = Field(description="Approximate headcount or range, e.g. '200-500' or '1000+'")
    location: str = Field(description="City and country, e.g. Mumbai, India")
    decision_maker: str = Field(description="Name and title of HR or People decision maker, or Unknown")
    pain_points: List[str] = Field(description="HR or workforce pain points the company likely faces")
    website: str = Field(description="Company website URL")


class QualificationResult(BaseModel):
    """Schema for qualification agent: score and reason a lead."""
    score: float = Field(description="Lead quality score from 0.0 to 10.0", ge=0.0, le=10.0)
    reasoning: str = Field(description="2-3 sentence explanation of the score grounded in product fit")
    key_signals: List[str] = Field(description="Top 3 signals that most influenced this score")
    recommended_action: str = Field(description="One of: outreach, nurture, disqualify")
