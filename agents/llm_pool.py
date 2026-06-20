"""
LLM Endpoint Pool
-----------------
A rotating pool of OpenAI-compatible chat endpoints (NVIDIA NIM + DeepSeek + Groq
+ OpenRouter). It round-robins requests, marks an endpoint "cooling down" on a
rate-limit / error and fails over to the next, and serves two tiers:

  • 'fast'   — small, cheap models for bulk classification (HRMS yes/no, industry…)
  • 'strong' — larger models for reasoning, qualification and email drafting

Why: with several free endpoints (e.g. multiple NVIDIA build keys) the combined
throughput is N× a single endpoint, and one rate-limited key never stalls a run.

The pool is auto-built from whatever keys are present in the runtime config — no
separate configuration needed. It exposes:
  • PoolLLM(...).invoke(prompt|messages) → object with .content  (drop-in for the
    existing _OpenAICompatLLM, so BaseAgent._get_llm can return it transparently)
  • complete(prompt, tier=...) → str   (used by the background enrichment worker)

stdlib + the `openai` SDK only (no tiktoken → ARM64-safe). Fully fail-safe.
"""
import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

_COOLDOWN_SECS = 25.0  # how long to skip an endpoint after a rate-limit / error


@dataclass
class _Endpoint:
    name: str
    base_url: str
    api_key: str
    model: str
    tier: str  # 'fast' | 'strong'
    cooldown_until: float = 0.0
    fails: int = 0
    _client: object = field(default=None, repr=False)

    def client(self):
        if self._client is None:
            from openai import OpenAI
            headers = {}
            if "openrouter" in self.base_url:
                headers = {"HTTP-Referer": "https://humanmaximizer.com",
                           "X-Title": "RazorInfotech HRMS Leads AI"}
            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key,
                                  default_headers=headers)
        return self._client


class _Resp:
    def __init__(self, content: str):
        self.content = content or ""


def _build_endpoints() -> list[_Endpoint]:
    """Discover every configured OpenAI-compatible endpoint from runtime config."""
    from core import runtime_config as rc

    eps: list[_Endpoint] = []
    # NVIDIA NIM (build.nvidia.com) — every key contributes BOTH a fast and a
    # strong endpoint. Multiple keys (nvidia_api_keys, comma-separated) are
    # separate accounts → the pool round-robins them to multiply the free rate
    # limit. Benchmarked best models: Llama-3.1-8B (fast) + Llama-3.3-70B (strong);
    # NVIDIA's reasoning models (gemma-4, deepseek-v4-flash, minimax-m3) are 16-70s
    # and deliberately NOT used as workhorses.
    nv_fast = rc.get("nvidia_model_fast", "meta/llama-3.1-8b-instruct")
    nv_strong = rc.get("nvidia_model_strong", "meta/llama-3.3-70b-instruct")
    nv_keys, seen = [], set()
    for src in (rc.get("nvidia_api_key"), rc.get("nvidia_api_keys")):
        for k in str(src or "").replace(" ", ",").split(","):
            k = k.strip()
            if k and k not in seen:
                seen.add(k)
                nv_keys.append(k)
    for i, k in enumerate(nv_keys, 1):
        sfx = f"-{i}" if len(nv_keys) > 1 else ""
        eps.append(_Endpoint(f"nvidia-fast{sfx}", "https://integrate.api.nvidia.com/v1", k, nv_fast, "fast"))
        eps.append(_Endpoint(f"nvidia-strong{sfx}", "https://integrate.api.nvidia.com/v1", k, nv_strong, "strong"))
    # Paid DeepSeek — reliable strong-tier fallback so the pool never fully stalls.
    if rc.get("deepseek_api_key"):
        eps.append(_Endpoint("deepseek", "https://api.deepseek.com", rc.get("deepseek_api_key"),
                             rc.get("deepseek_model", "deepseek-chat"), "strong"))
    # Groq — very fast small models → great fast tier.
    if rc.get("groq_api_key"):
        eps.append(_Endpoint("groq", "https://api.groq.com/openai/v1", rc.get("groq_api_key"),
                             rc.get("groq_model", "llama-3.1-8b-instant"), "fast"))
    # OpenRouter — extra strong-tier capacity.
    if rc.get("openrouter_api_key"):
        eps.append(_Endpoint("openrouter", "https://openrouter.ai/api/v1", rc.get("openrouter_api_key"),
                             rc.get("openrouter_model", "meta-llama/llama-3.3-70b-instruct"), "strong"))
    return eps


class _Pool:
    def __init__(self):
        self._lock = threading.Lock()
        self._eps: list[_Endpoint] = []
        self._rr = itertools.count()  # global round-robin counter
        self._built_for: tuple = ()

    def _ensure(self):
        """(Re)build the endpoint list if the configured keys changed."""
        from core import runtime_config as rc
        sig = (rc.get("nvidia_api_key"), rc.get("nvidia_api_keys"),
               bool(rc.get("deepseek_api_key")), bool(rc.get("groq_api_key")),
               bool(rc.get("openrouter_api_key")),
               rc.get("nvidia_model_fast"), rc.get("nvidia_model_strong"))
        if sig != self._built_for or not self._eps:
            self._eps = _build_endpoints()
            self._built_for = sig

    def endpoints(self) -> list[_Endpoint]:
        with self._lock:
            self._ensure()
            return list(self._eps)

    def _pick(self, tier: str) -> Optional[_Endpoint]:
        now = time.time()
        with self._lock:
            self._ensure()
            if not self._eps:
                return None
            # Prefer healthy endpoints of the requested tier; then any healthy
            # endpoint; then the least-cooling-down one (better than failing).
            healthy_tier = [e for e in self._eps if e.tier == tier and e.cooldown_until <= now]
            healthy_any = [e for e in self._eps if e.cooldown_until <= now]
            pool = healthy_tier or healthy_any or self._eps
            idx = next(self._rr) % len(pool)
            return pool[idx]

    def complete(self, prompt, tier: str = "strong", temperature: float = 0.2,
                 max_tokens: int = 800) -> str:
        """Call the pool with failover. Returns the completion text ("" on total
        failure). `prompt` is a string or a list of chat messages."""
        self._ensure()
        attempts = max(len(self.endpoints()), 1)
        messages = ([{"role": "user", "content": prompt}] if isinstance(prompt, str)
                    else prompt)
        last_err = None
        for _ in range(attempts):
            ep = self._pick(tier)
            if ep is None:
                logger.warning("[llm_pool] no endpoints configured")
                return ""
            try:
                resp = ep.client().chat.completions.create(
                    model=ep.model, messages=messages,
                    temperature=temperature, max_tokens=max_tokens,
                )
                content = (resp.choices[0].message.content or "").strip()
                # An empty 200 (e.g. an invalid model name the API silently accepts)
                # is a soft failure — cool the endpoint down and fail over, don't
                # hand back a blank.
                if not content:
                    last_err = f"{ep.name} returned empty content (check model id '{ep.model}')"
                    ep.cooldown_until = time.time() + _COOLDOWN_SECS
                    ep.fails += 1
                    logger.debug(f"[llm_pool] {last_err}; failing over")
                    continue
                ep.fails = 0
                return content
            except Exception as e:  # rate-limit, network, model error → cool down + next
                last_err = e
                ep.cooldown_until = time.time() + _COOLDOWN_SECS
                ep.fails += 1
                logger.debug(f"[llm_pool] {ep.name} failed ({e}); cooling down, failing over")
        logger.warning(f"[llm_pool] all endpoints exhausted: {last_err}")
        return ""

    def stats(self) -> dict:
        now = time.time()
        eps = self.endpoints()
        return {
            "endpoints": len(eps),
            "fast": sum(1 for e in eps if e.tier == "fast"),
            "strong": sum(1 for e in eps if e.tier == "strong"),
            "available": sum(1 for e in eps if e.cooldown_until <= now),
            "providers": [{"name": e.name, "model": e.model, "tier": e.tier,
                           "cooling_down": e.cooldown_until > now} for e in eps],
        }


# Process-wide singleton.
_POOL = _Pool()


def complete(prompt, tier: str = "strong", temperature: float = 0.2, max_tokens: int = 800) -> str:
    return _POOL.complete(prompt, tier=tier, temperature=temperature, max_tokens=max_tokens)


def stats() -> dict:
    return _POOL.stats()


def available() -> bool:
    return len(_POOL.endpoints()) > 0


class PoolLLM:
    """Drop-in for _OpenAICompatLLM that routes every .invoke() through the pool
    (round-robin + failover). Returned by BaseAgent._get_llm when provider='pool'
    so all existing agent code benefits transparently."""

    def __init__(self, tier: str = "strong", temperature: float = 0.2, max_tokens: int = 800):
        self.tier = tier
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
        text = _POOL.complete(self._to_messages(inp), tier=self.tier,
                              temperature=self.temperature, max_tokens=self.max_tokens)
        return _Resp(text)
