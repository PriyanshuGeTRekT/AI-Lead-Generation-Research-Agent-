"""
Runtime Config Overlay
----------------------
Lets the operator set API keys / LLM provider FROM THE UI at runtime, without
editing code or .env (and without committing secrets — fixing the hardcoded key
in the old tool). Precedence for any value:

    runtime overrides (data/runtime_config.json)  →  env / Settings  →  default

Persisted to a gitignored JSON file so a restart keeps the demo config. Secrets
are never returned raw to the client — use `public_config()` for the masked view.
"""
import json
import os
from pathlib import Path
from typing import Any, Optional

_PATH = Path(os.getenv("RUNTIME_CONFIG_PATH", "./data/runtime_config.json"))

# Keys the UI may set. Secret keys are masked in public_config().
KNOWN_KEYS = [
    "llm_provider",  # bedrock | anthropic | openai | deepseek | gemini | groq | openrouter | nvidia | pool
    "llm_min_interval",  # min seconds between LLM calls (0 = no throttle; for free tiers)
    "use_llm_pool",  # "1" → route all LLM calls through the multi-endpoint pool (round-robin + failover)
    # ── NVIDIA NIM (build.nvidia.com — OpenAI-compatible, free frontier models) ──
    "nvidia_api_key",
    "nvidia_api_keys",      # OPTIONAL: comma-separated extra nvapi- keys → pool triples throughput
    "nvidia_model_fast",    # small/fast model for bulk classification
    "nvidia_model_strong",  # larger model for reasoning / email
    # ── AWS Bedrock ──
    "bedrock_api_key",       # new-style Bedrock bearer token (ABSK…) — preferred
    "aws_access_key_id",     # OR classic access-key/secret pair
    "aws_secret_access_key",
    "aws_region",
    "bedrock_model",
    # ── Anthropic (Claude direct) ──
    "anthropic_api_key",
    "anthropic_model",
    # ── OpenAI ──
    "openai_api_key",
    "openai_model",
    # ── DeepSeek ──
    "deepseek_api_key",
    "deepseek_model",
    # ── Google Gemini ──
    "gemini_api_key",
    "gemini_model",
    # ── Groq ──
    "groq_api_key",
    "groq_model",
    # ── OpenRouter (OpenAI-compatible gateway to many models) ──
    "openrouter_api_key",
    "openrouter_model",
    # ── Data sources / integrations ──
    "datagovin_api_key",      # data.gov.in open-data API key (free) — official MSME registry
    "datagovin_resource_id",  # the MSME/company dataset resource id to query
    "serper_api_key",
    "serper_api_keys",
    "google_places_api_key",
    "crustdata_api_key",
    "pdl_api_key",
    "apollo_api_key",
    "apify_api_token",      # Apify platform token — runs store actors (Maps + Apollo leads)
    "instantly_api_key",
    "explorium_api_key",
    "ipinfo_token",
    "slack_webhook_url",
    "crm_webhook_url",
    "langchain_api_key",
    "langchain_project",
]
_SECRET_KEYS = {
    "bedrock_api_key", "aws_access_key_id", "aws_secret_access_key",
    "anthropic_api_key", "openai_api_key", "deepseek_api_key",
    "gemini_api_key", "groq_api_key", "openrouter_api_key", "nvidia_api_key", "nvidia_api_keys",
    "serper_api_key", "serper_api_keys", "google_places_api_key", "crustdata_api_key", "pdl_api_key",
    "apollo_api_key", "apify_api_token", "instantly_api_key", "datagovin_api_key",
    "explorium_api_key", "ipinfo_token", "slack_webhook_url", "crm_webhook_url",
    "langchain_api_key",
}

_cache: Optional[dict] = None


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    if _PATH.exists():
        try:
            with open(_PATH) as f:
                _cache = json.load(f)
        except Exception:
            _cache = {}
    else:
        _cache = {}
    return _cache


def _save(d: dict) -> None:
    global _cache
    _cache = d
    try:
        _PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _PATH.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, _PATH)
    except Exception:
        pass


def get(name: str, default: Any = None) -> Any:
    """Resolve a config value: runtime override → env var (UPPER) → Settings → default."""
    overrides = _load()
    if overrides.get(name) not in (None, ""):
        return overrides[name]
    env = os.getenv(name.upper())
    if env:
        return env
    try:
        from core.config import get_settings
        val = getattr(get_settings(), name, None)
        if val not in (None, ""):
            return val
    except Exception:
        pass
    return default


def update(patch: dict) -> dict:
    """Merge a partial config from the UI. Empty strings clear a key. Returns masked view."""
    d = dict(_load())
    for k, v in (patch or {}).items():
        if k not in KNOWN_KEYS:
            continue
        if v in (None, ""):
            d.pop(k, None)
        else:
            d[k] = v
    _save(d)
    return public_config()


def _mask(v: str) -> str:
    if not v:
        return ""
    s = str(v)
    return ("•" * max(0, len(s) - 4)) + s[-4:] if len(s) > 4 else "••••"


def public_config() -> dict:
    """Masked, safe-to-return view: secrets show only as set/last-4."""
    overrides = _load()
    out: dict = {}
    for k in KNOWN_KEYS:
        val = overrides.get(k)
        if k in _SECRET_KEYS:
            out[k] = {"set": bool(val), "preview": _mask(val) if val else ""}
        else:
            out[k] = val or ""
    # which provider will actually be used
    out["active_provider"] = active_provider()
    return out


def active_provider() -> str:
    """Explicit selection wins; otherwise auto-pick the first provider with a key."""
    p = get("llm_provider")
    if p:
        return p
    if get("bedrock_api_key") or get("aws_access_key_id"):
        return "bedrock"
    if get("anthropic_api_key"):
        return "anthropic"
    if get("openai_api_key"):
        return "openai"
    if get("deepseek_api_key"):
        return "deepseek"
    if get("nvidia_api_key"):
        return "nvidia"
    if get("gemini_api_key"):
        return "gemini"
    if get("groq_api_key"):
        return "groq"
    if get("openrouter_api_key"):
        return "openrouter"
    return "none"
