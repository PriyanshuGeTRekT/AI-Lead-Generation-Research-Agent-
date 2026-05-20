"""
Base Agent Class
-----------------
All agents inherit from BaseAgent to get:
  - Consistent logging with correlation IDs
  - Retry logic with exponential backoff
  - LLM call wrapper with error handling
  - Redis caching for LLM responses
  - Input/output validation hooks

Architectural Decision:
  Without a base class, each agent reimplements retry logic, logging,
  and error handling differently — leading to inconsistent behavior
  and maintenance burden. The base class enforces a contract:
  every agent handles failures the same way, logs the same fields,
  and benefits from caching automatically.
"""
import json
import time
import uuid
from abc import ABC, abstractmethod
from typing import Optional
from groq import Groq, RateLimitError, APIError
from core.config import get_settings
from core.exceptions import LLMError, LLMRateLimitError, LLMResponseParseError
from cache.redis_client import get_cached, set_cached, cache_key
from loguru import logger

settings = get_settings()


class BaseAgent(ABC):
    """Abstract base for all pipeline agents."""

    name: str = "base_agent"
    max_retries: int = 3
    base_delay: float = 1.0  # seconds, doubles each retry

    def __init__(self, correlation_id: str = None):
        self.correlation_id = correlation_id or str(uuid.uuid4())[:8]
        self.log = logger.bind(agent=self.name, correlation_id=self.correlation_id)
        self.client = Groq(api_key=settings.groq_api_key)

    def call_llm(
        self,
        prompt: str,
        temperature: float = None,
        max_tokens: int = None,
        use_cache: bool = True,
    ) -> str:
        """
        LLM call with:
          - Redis caching (skip duplicate calls)
          - Retry with exponential backoff on rate limits
          - Structured error handling

        Architectural Decision:
          Wrapping all LLM calls through this method means:
          - Cache hit rate is measurable (log cache hits vs misses)
          - Rate limit retries happen automatically
          - Any future LLM provider swap only needs to change this method
        """
        temperature = temperature or settings.llm_temperature_extract
        max_tokens = max_tokens or settings.llm_max_tokens_extract

        # Check cache first — hash the FULL prompt to distinguish per-company calls
        # Bug fix: prompt[:200] was always the static preamble, causing cache collisions
        ck = cache_key("llm", self.name, prompt, str(temperature))
        if use_cache:
            cached = get_cached(ck)
            if cached:
                self.log.debug("LLM cache hit", extra={"cache_key": ck[:16]})
                return cached

        # Retry loop with exponential backoff
        for attempt in range(self.max_retries):
            try:
                self.log.debug(f"LLM call attempt {attempt + 1}/{self.max_retries}")
                response = self.client.chat.completions.create(
                    model=settings.groq_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                result = response.choices[0].message.content.strip()

                # Cache successful response
                if use_cache:
                    set_cached(ck, result, ttl=settings.redis_cache_ttl)

                return result

            except RateLimitError:
                delay = self.base_delay * (2 ** attempt)
                self.log.warning(f"Rate limit hit. Retrying in {delay}s...")
                time.sleep(delay)
                if attempt == self.max_retries - 1:
                    raise LLMRateLimitError("Groq rate limit exceeded after retries")

            except APIError as e:
                self.log.error(f"Groq API error: {e}")
                raise LLMError(f"LLM API error: {e}")

        raise LLMError("LLM call failed after all retries")

    def parse_json_response(self, raw: str) -> dict:
        """
        Safely extract JSON from LLM response.
        LLMs often wrap JSON in markdown code blocks or add commentary.
        Handles: code fences, preamble/postamble text, raw newlines in strings.
        """
        import re

        # Strip markdown code fences if present
        raw = raw.strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0]

        # Find JSON boundaries
        start = raw.find("{")
        end = raw.rfind("}") + 1

        if start < 0 or end <= start:
            raise LLMResponseParseError(
                "No valid JSON found in LLM response",
                details={"raw_response": raw[:500]}
            )

        json_str = raw[start:end]

        # Attempt 1: direct parse
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        # Attempt 2: escape unescaped control characters inside string values
        # LLMs sometimes emit literal newlines/tabs inside JSON strings
        def fix_control_chars(s: str) -> str:
            # Replace raw newlines/tabs/carriage returns that appear inside
            # JSON string values (between quotes) with their escaped equivalents
            result = []
            in_string = False
            escape_next = False
            for ch in s:
                if escape_next:
                    result.append(ch)
                    escape_next = False
                elif ch == "\\":
                    result.append(ch)
                    escape_next = True
                elif ch == '"' and not escape_next:
                    result.append(ch)
                    in_string = not in_string
                elif in_string and ch == "\n":
                    result.append("\\n")
                elif in_string and ch == "\r":
                    result.append("\\r")
                elif in_string and ch == "\t":
                    result.append("\\t")
                else:
                    result.append(ch)
            return "".join(result)

        try:
            return json.loads(fix_control_chars(json_str))
        except json.JSONDecodeError as e:
            raise LLMResponseParseError(
                f"JSON parse failed: {e}",
                details={"raw_response": raw[:500]}
            )

    @abstractmethod
    def run(self, state: dict) -> dict:
        """Each agent implements its own run() logic."""
        pass
