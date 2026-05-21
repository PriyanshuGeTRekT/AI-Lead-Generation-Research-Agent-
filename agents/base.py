"""
Base Agent Class
-----------------
All agents inherit from BaseAgent to get:
  - Consistent logging with correlation IDs
  - Retry logic with exponential backoff
  - LLM call wrapper with error handling
  - Redis caching for LLM responses
  - LangSmith tracing on every LLM call

LLM Priority:
  1. DeepSeek (if DEEPSEEK_API_KEY set) — higher rate limits, OpenAI-compatible
  2. Groq (fallback)                    — fast inference, 30 req/min free tier

LangSmith Tracing:
  Both ChatOpenAI (DeepSeek) and ChatGroq are LangChain Runnable objects,
  so calls are automatically traced when LANGCHAIN_TRACING_V2=true.
"""
import json
import re
import time
import uuid
from abc import ABC, abstractmethod
from langchain_core.messages import HumanMessage
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

    def _get_llm(self, temperature: float, max_tokens: int):
        """
        Return an LLM instance. DeepSeek is preferred (higher rate limits);
        falls back to Groq if DEEPSEEK_API_KEY is not set.
        Creating per-call is intentional: temperature and max_tokens differ
        between extraction (low temp) and creative (higher temp) calls.
        """
        if settings.deepseek_api_key:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=settings.deepseek_model,
                openai_api_key=settings.deepseek_api_key,
                openai_api_base="https://api.deepseek.com",
                temperature=temperature,
                max_tokens=max_tokens,
            )
        from langchain_groq import ChatGroq
        return ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def call_llm(
        self,
        prompt: str,
        temperature: float = None,
        max_tokens: int = None,
        use_cache: bool = True,
    ) -> str:
        # Bug fix: `temperature or default` is falsy when temperature=0.0, which is a
        # valid value (maximally deterministic). Use explicit None check instead.
        """
        LLM call with:
          - Redis caching (skip duplicate calls for same company)
          - Retry with exponential backoff on rate limits
          - Structured error handling
          - Automatic LangSmith tracing (via ChatGroq)

        Every call through this method appears in LangSmith as a traced
        LLM run nested under the parent LangGraph pipeline run, showing
        the full prompt, response, token usage, and latency.
        """
        temperature = temperature if temperature is not None else settings.llm_temperature_extract
        max_tokens = max_tokens if max_tokens is not None else settings.llm_max_tokens_extract

        # Check cache first. Hash the FULL prompt to distinguish per-company calls.
        # Bug fix: prompt[:200] was always the static preamble, causing cache collisions
        ck = cache_key("llm", self.name, prompt, str(temperature))
        if use_cache:
            cached = get_cached(ck)
            if cached:
                self.log.debug(f"LLM cache hit (key: {ck[:16]})")
                return cached

        llm = self._get_llm(temperature, max_tokens)

        provider = "DeepSeek" if settings.deepseek_api_key else "Groq"

        # Retry loop with exponential backoff (works for both Groq and DeepSeek)
        for attempt in range(self.max_retries):
            try:
                self.log.debug(f"[{provider}] LLM call attempt {attempt + 1}/{self.max_retries}")
                response = llm.invoke([HumanMessage(content=prompt)])
                result = response.content.strip()

                # Cache successful response
                if use_cache:
                    set_cached(ck, result, ttl=settings.redis_cache_ttl)

                return result

            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = (
                    "rate" in err_str and ("limit" in err_str or "429" in err_str)
                    or "429" in err_str
                    or "too many requests" in err_str
                )
                if is_rate_limit:
                    delay = self.base_delay * (2 ** attempt)
                    self.log.warning(f"[{provider}] Rate limit hit. Retrying in {delay}s…")
                    time.sleep(delay)
                    if attempt == self.max_retries - 1:
                        raise LLMRateLimitError(f"{provider} rate limit exceeded after retries")
                else:
                    self.log.error(f"[{provider}] LLM error: {e}")
                    raise LLMError(f"LLM error: {e}")

        raise LLMError("LLM call failed after all retries")

    def call_llm_structured(
        self,
        prompt: str,
        schema: type,
        temperature: float = None,
        max_tokens: int = None,
        use_cache: bool = True,
    ) -> object:
        """
        LLM call enforcing a Pydantic schema via .with_structured_output().
        Returns a validated Pydantic model instance, not a raw string.

        How it works: LangChain passes the schema as a JSON Schema tool definition
        to the model. Groq/Llama 3.1 uses tool calling to return structured JSON
        that LangChain auto-validates against the schema.

        Falls back to call_llm() + parse_json_response() + manual model construction
        if structured output fails. This ensures the agent never hard-fails due to
        a schema enforcement issue.

        Bug fix: removed `if True:` placeholder — added proper `use_cache` parameter
        so callers can opt out of caching (e.g. when schema output must be unique).
        Also fixed `temperature or default` falsy bug (temperature=0.0 is valid).
        """
        temperature = temperature if temperature is not None else settings.llm_temperature_extract
        max_tokens = max_tokens if max_tokens is not None else settings.llm_max_tokens_extract

        # Cache key based on schema name + prompt
        ck = cache_key("llm_structured", self.name, schema.__name__, prompt, str(temperature))
        if use_cache:
            cached = get_cached(ck)
            if cached:
                self.log.debug(f"Structured LLM cache hit (key: {ck[:16]})")
                try:
                    return schema.model_validate_json(cached)
                except Exception:
                    pass  # cache miss effectively, proceed to LLM call

        llm = self._get_llm(temperature, max_tokens)

        # Attempt 1: structured output via .with_structured_output()
        try:
            structured_llm = llm.with_structured_output(schema)
            result = structured_llm.invoke(prompt)
            # Cache the result
            set_cached(ck, result.model_dump_json(), ttl=settings.redis_cache_ttl)
            return result
        except Exception as e:
            self.log.warning(f"Structured output failed ({schema.__name__}), falling back to raw LLM: {e}")

        # Fallback: raw LLM + JSON parsing + manual schema construction
        raw = self.call_llm(prompt, temperature=temperature, max_tokens=max_tokens)
        parsed = self.parse_json_response(raw)
        return schema(**parsed)

    def parse_json_response(self, raw: str) -> dict:
        """
        Safely extract JSON from LLM response.
        LLMs often wrap JSON in markdown code blocks or add commentary.
        Handles: code fences, preamble/postamble text, raw newlines in strings.
        """
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

        # Attempt 2: escape unescaped control characters inside string values.
        # LLMs sometimes emit literal newlines/tabs inside JSON strings.
        def fix_control_chars(s: str) -> str:
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
