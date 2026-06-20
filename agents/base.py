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

# ── Global LLM throttle ──────────────────────────────────────────────────────
# Free models have tiny rate limits; firing concurrent calls causes 429 storms.
# This serializes every LLM call process-wide with a minimum gap between them.
import threading as _threading

_LLM_GATE = _threading.Lock()
_LLM_LAST = [0.0]


def _throttle() -> None:
    from core import runtime_config as rc
    try:
        interval = float(rc.get("llm_min_interval", 1.2) or 1.2)
    except Exception:
        interval = 1.2
    if interval <= 0:
        return
    with _LLM_GATE:
        now = time.monotonic()
        wait = _LLM_LAST[0] + interval - now
        if wait > 0:
            time.sleep(wait)
        _LLM_LAST[0] = time.monotonic()


class _Resp:
    """Minimal stand-in for a LangChain message (has .content)."""
    def __init__(self, content: str):
        self.content = content or ""


class _OpenAICompatLLM:
    """LangChain-compatible wrapper over the openai SDK for ANY OpenAI-compatible
    endpoint (OpenRouter, DeepSeek, …). No tiktoken → installs/runs on ARM64.
    Implements .invoke(messages|str) → object with .content. It does NOT implement
    .with_structured_output, so call_llm_structured() falls back to raw-JSON parse
    (which the prompts already request)."""

    def __init__(self, model: str, api_key: str, base_url: str, temperature: float,
                 max_tokens: int, headers: dict = None):
        from openai import OpenAI
        self._client = OpenAI(base_url=base_url, api_key=api_key, default_headers=headers or {})
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @staticmethod
    def _to_messages(inp):
        if isinstance(inp, str):
            return [{"role": "user", "content": inp}]
        out = []
        for m in inp:
            role = getattr(m, "type", None)
            content = getattr(m, "content", m if isinstance(m, str) else "")
            mapped = {"human": "user", "ai": "assistant", "system": "system"}.get(role, "user")
            out.append({"role": mapped, "content": content})
        return out

    def invoke(self, inp):
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=self._to_messages(inp),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
        return _Resp(resp.choices[0].message.content)


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
        Return an LLM instance for the active provider. Keys/provider are read
        from the runtime config overlay (set via the UI Settings panel) first,
        then env/Settings. Supported: AWS Bedrock (Claude), DeepSeek, Groq.

        Creating per-call is intentional: temperature and max_tokens differ
        between extraction (low temp) and creative (higher temp) calls.
        """
        from core import runtime_config as rc
        provider = rc.active_provider()

        def _missing(pkg: str, pip: str):
            return LLMError(f"Provider '{provider}' selected but {pkg} is not installed (pip install {pip})")

        # LLM endpoint pool — round-robins across every configured OpenAI-compatible
        # endpoint (NVIDIA NIM + DeepSeek + Groq + OpenRouter) with automatic
        # failover. Selected explicitly ('pool') or auto when use_llm_pool is on.
        if (provider == "pool" or rc.get("use_llm_pool")):
            from agents.llm_pool import PoolLLM, available
            if available():
                return PoolLLM(tier="strong", temperature=temperature, max_tokens=max_tokens)

        if provider == "nvidia" and rc.get("nvidia_api_key"):
            # NVIDIA NIM (build.nvidia.com) — OpenAI-compatible, free frontier models.
            return _OpenAICompatLLM(
                model=rc.get("nvidia_model_strong", "meta/llama-3.3-70b-instruct"),
                api_key=rc.get("nvidia_api_key"),
                base_url="https://integrate.api.nvidia.com/v1",
                temperature=temperature, max_tokens=max_tokens,
            )

        if provider == "bedrock":
            import os
            region = rc.get("aws_region", "us-east-1")
            bearer = rc.get("bedrock_api_key")
            ak, sk = rc.get("aws_access_key_id"), rc.get("aws_secret_access_key")
            if bearer:
                # New-style Bedrock API key (ABSK… bearer token); boto3 ≥1.39 reads this.
                os.environ["AWS_BEARER_TOKEN_BEDROCK"] = bearer
            if ak:
                os.environ["AWS_ACCESS_KEY_ID"] = ak
            if sk:
                os.environ["AWS_SECRET_ACCESS_KEY"] = sk
            os.environ["AWS_REGION"] = region
            os.environ.setdefault("AWS_DEFAULT_REGION", region)
            try:
                from langchain_aws import ChatBedrockConverse
            except ImportError as e:
                raise _missing("langchain-aws", "langchain-aws boto3") from e
            return ChatBedrockConverse(
                model=rc.get("bedrock_model", "us.anthropic.claude-sonnet-4-20250514-v1:0"),
                region_name=region, temperature=temperature, max_tokens=max_tokens,
            )

        if provider == "anthropic" and rc.get("anthropic_api_key"):
            try:
                from langchain_anthropic import ChatAnthropic
            except ImportError as e:
                raise _missing("langchain-anthropic", "langchain-anthropic") from e
            return ChatAnthropic(
                model=rc.get("anthropic_model", "claude-3-5-sonnet-latest"),
                api_key=rc.get("anthropic_api_key"),
                temperature=temperature, max_tokens=max_tokens,
            )

        if provider == "openai" and rc.get("openai_api_key"):
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=rc.get("openai_model", "gpt-4o"),
                openai_api_key=rc.get("openai_api_key"),
                temperature=temperature, max_tokens=max_tokens,
            )

        if provider == "deepseek" and rc.get("deepseek_api_key"):
            # OpenAI-compatible — via the openai SDK (no tiktoken → ARM64-safe).
            return _OpenAICompatLLM(
                model=rc.get("deepseek_model", "deepseek-chat"),
                api_key=rc.get("deepseek_api_key"),
                base_url="https://api.deepseek.com",
                temperature=temperature, max_tokens=max_tokens,
            )

        if provider == "gemini" and rc.get("gemini_api_key"):
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
            except ImportError as e:
                raise _missing("langchain-google-genai", "langchain-google-genai") from e
            gkw = dict(
                model=rc.get("gemini_model", "gemini-2.5-flash"),
                google_api_key=rc.get("gemini_api_key"),
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
            # 2.5 models "think" and spend the output budget on reasoning, which
            # truncates answers — disable it so the full budget goes to the reply.
            try:
                return ChatGoogleGenerativeAI(**gkw, thinking_budget=0)
            except Exception:
                return ChatGoogleGenerativeAI(**gkw)

        if provider == "groq" and rc.get("groq_api_key"):
            from langchain_groq import ChatGroq
            return ChatGroq(
                api_key=rc.get("groq_api_key"),
                model=rc.get("groq_model", settings.groq_model),
                temperature=temperature, max_tokens=max_tokens,
            )

        if provider == "openrouter" and rc.get("openrouter_api_key"):
            # OpenAI-compatible gateway. Uses the plain `openai` SDK (no tiktoken,
            # so it installs on ARM64). Wrapped to look like a LangChain LLM.
            return _OpenAICompatLLM(
                model=rc.get("openrouter_model", "google/gemma-4-31b-it:free"),
                api_key=rc.get("openrouter_api_key"),
                base_url="https://openrouter.ai/api/v1",
                temperature=temperature, max_tokens=max_tokens,
                headers={"HTTP-Referer": "https://humanmaximizer.com", "X-Title": "RazorInfotech HRMS Leads AI"},
            )

        raise LLMError(
            "No LLM provider configured. Add a key for Bedrock / Claude / OpenAI / "
            "DeepSeek / Gemini / Groq in Settings ⚙."
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

        from core import runtime_config as rc
        provider = rc.active_provider()

        # Retry loop with exponential backoff (works for both Groq and DeepSeek)
        for attempt in range(self.max_retries):
            try:
                self.log.debug(f"[{provider}] LLM call attempt {attempt + 1}/{self.max_retries}")
                _throttle()
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
            _throttle()
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
