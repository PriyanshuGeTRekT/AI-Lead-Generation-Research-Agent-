"""
Custom Exception Taxonomy
--------------------------
Structured exception hierarchy gives us:
  - Precise error handling per failure type
  - Clean API error responses with meaningful messages
  - Better observability (different alerts per exception type)

Architectural Decision:
  Rather than catching generic Exception everywhere, a typed hierarchy
  lets the supervisor route failures correctly. For example, a WebSearchError
  can trigger a retry, while a PromptInjectionError should hard-stop.
"""


class LeadGenBaseError(Exception):
    """Base for all application errors."""
    def __init__(self, message: str, details: dict = None):
        self.message = message
        self.details = details or {}
        super().__init__(message)


# ── LLM Errors ────────────────────────────────────────────────────────────────

class LLMError(LeadGenBaseError):
    """LLM API call failed."""

class LLMRateLimitError(LLMError):
    """Groq/LLM rate limit hit, triggers exponential backoff."""

class LLMResponseParseError(LLMError):
    """LLM returned non-JSON or malformed response."""

class LLMHallucinationError(LLMError):
    """Response failed hallucination guard checks."""


# ── RAG Errors ────────────────────────────────────────────────────────────────

class RAGError(LeadGenBaseError):
    """Vector store operation failed."""

class RAGLowConfidenceError(RAGError):
    """Retrieved context has poor relevance score, risk of hallucination."""


# ── Web / Research Errors ─────────────────────────────────────────────────────

class WebSearchError(LeadGenBaseError):
    """DuckDuckGo search failed or returned no results."""

class ScrapingError(LeadGenBaseError):
    """Company website scraping failed."""


# ── Security Errors ───────────────────────────────────────────────────────────

class PromptInjectionError(LeadGenBaseError):
    """Input contains suspected prompt injection patterns."""

class RateLimitExceededError(LeadGenBaseError):
    """API rate limit exceeded, returns 429."""

class InputValidationError(LeadGenBaseError):
    """Input failed validation (too long, empty, invalid chars)."""


# ── Pipeline Errors ───────────────────────────────────────────────────────────

class PipelineError(LeadGenBaseError):
    """General pipeline orchestration failure."""

class MaxIterationsError(PipelineError):
    """Pipeline hit max iteration limit (safety circuit breaker)."""
