"""Provider-agnostic prompt runner with usage tracking.

Reads `provider` from a prompt skill's frontmatter (default "gemini") and
dispatches the call to the right backend. Returns a PromptResult containing
the model's plain-text response plus token usage and a best-effort cost
estimate.

For structured / JSON-mode calls (Stage 2 classifier), use the specialized path
in `app/tools/classification_tools.py` — that one validates against a Pydantic
schema and retries on validation failure.
"""

import os
from dataclasses import asdict, dataclass
from typing import Any

from app.core.prompt_manager import load_prompt


# ---------------------------------------------------------------------------
# Pricing — APPROXIMATE rates per million tokens. Verify and update from
# https://platform.deepseek.com/pricing — DeepSeek's tiers + off-peak discounts
# (~50% off UTC 16:30-00:30) change. None means "no estimate available".
# ---------------------------------------------------------------------------
_PRICING_USD_PER_M_TOKENS: dict[str, dict[str, float]] = {
    "deepseek-v4-pro":   {"input": 1.50, "output": 6.00},   # approximation
    "deepseek-v4-flash": {"input": 0.30, "output": 1.20},   # approximation
    "deepseek-chat":     {"input": 0.27, "output": 1.10},   # confirmed for V3 chat
    "deepseek-reasoner": {"input": 0.55, "output": 2.20},   # confirmed for R1
    # Gemini left out: no Gemini prompts currently in use.
}


@dataclass
class PromptResult:
    text: str
    provider: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_usd: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def estimate_cost_usd(model: str, prompt_tokens: int | None, completion_tokens: int | None) -> float | None:
    rates = _PRICING_USD_PER_M_TOKENS.get(model)
    if not rates or prompt_tokens is None or completion_tokens is None:
        return None
    cost = (prompt_tokens * rates["input"] + completion_tokens * rates["output"]) / 1_000_000
    return round(cost, 6)


_gemini_client = None
_deepseek_client = None


def run_prompt(prompt_name: str, **vars: Any) -> PromptResult:
    """
    Load a prompt skill, render its template variables, dispatch to the
    declared provider, and return a PromptResult with text + usage.
    """
    config, prompt = load_prompt(prompt_name, **vars)
    provider = (config.get("provider") or "gemini").lower()
    model = config.get("model")
    temperature = float(config.get("temperature", 0.1))

    print(f"  [LLM] {prompt_name}: {provider}/{model}")

    if provider == "gemini":
        return _call_gemini(model, prompt, temperature)
    if provider == "deepseek":
        return _call_deepseek(model, prompt, temperature)
    raise ValueError(f"Unknown LLM provider {provider!r} in prompt {prompt_name!r}")


def _call_gemini(model: str, prompt: str, temperature: float) -> PromptResult:
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"),
            http_options={"api_version": "v1beta"},
        )
    response = _gemini_client.models.generate_content(
        model=model,
        contents=prompt,
        config={"temperature": temperature},
    )
    usage = getattr(response, "usage_metadata", None)
    p_tok = getattr(usage, "prompt_token_count", None) if usage else None
    c_tok = getattr(usage, "candidates_token_count", None) if usage else None
    t_tok = getattr(usage, "total_token_count", None) if usage else None
    return PromptResult(
        text=response.text,
        provider="gemini",
        model=model,
        prompt_tokens=p_tok,
        completion_tokens=c_tok,
        total_tokens=t_tok,
        estimated_cost_usd=estimate_cost_usd(model, p_tok, c_tok),
    )


def _call_deepseek(model: str, prompt: str, temperature: float) -> PromptResult:
    global _deepseek_client
    if _deepseek_client is None:
        import httpx
        from openai import OpenAI
        # Longer read timeout than the classifier (30s) — narrative outputs can
        # take 60-180s to stream from Pro-tier DeepSeek models.
        http_client = httpx.Client(
            timeout=httpx.Timeout(connect=10, read=180, write=10, pool=5),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=2),
        )
        _deepseek_client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
            http_client=http_client,
            max_retries=2,
        )
    resp = _deepseek_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    usage = resp.usage
    p_tok = getattr(usage, "prompt_tokens", None) if usage else None
    c_tok = getattr(usage, "completion_tokens", None) if usage else None
    t_tok = getattr(usage, "total_tokens", None) if usage else None
    return PromptResult(
        text=resp.choices[0].message.content or "",
        provider="deepseek",
        model=model,
        prompt_tokens=p_tok,
        completion_tokens=c_tok,
        total_tokens=t_tok,
        estimated_cost_usd=estimate_cost_usd(model, p_tok, c_tok),
    )
