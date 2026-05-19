"""DeepSeek client wrapper for the structured classifier.

Uses the OpenAI-compatible DeepSeek endpoint. Forces JSON-mode output, validates
the response against a Pydantic schema, and retries on validation failure.
"""

import json
import time
from typing import Literal

import httpx
from openai import APIError, APITimeoutError, OpenAI, RateLimitError
from pydantic import BaseModel, ValidationError

from app.tools.llm_router import build_deepseek_client

_MAX_VALIDATION_RETRIES = 2
# 30s read timeout is right for JSON-mode classification (no streaming, short
# output). The narrator uses 180s in `llm_router._call_deepseek`.
_READ_TIMEOUT_S = 30
_MAX_TRANSPORT_RETRIES = 2


class ClassifyData(BaseModel):
    market_cap_tier: str
    sector: str
    industry: str
    revenue_model: str
    customer_type: str
    asset_intensity: str
    value_chain_position: str
    geographic_exposure: str
    inventory_strategy: str
    global_presence: str


class ClassifyMetadata(BaseModel):
    primary_category: Literal["Software", "Consumer Goods", "Other"]
    logic_summary: str


class ClassifyResult(BaseModel):
    ticker: str
    data: ClassifyData
    metadata: ClassifyMetadata


# Module-level singleton — built on first use, reused across all calls in the
# process. Avoids constructing a new OpenAI() + httpx connection pool on every
# classify_company invocation (was a real cost during the 7K-row classifier run).
_classify_client: OpenAI | None = None


def _client() -> OpenAI:
    global _classify_client
    if _classify_client is not None:
        return _classify_client
    _classify_client = build_deepseek_client(
        read_timeout_s=_READ_TIMEOUT_S,
        max_retries=_MAX_TRANSPORT_RETRIES,
    )
    return _classify_client


def classify_company(
    prompt: str,
    *,
    model: str,
    temperature: float = 0.1,
    client: OpenAI | None = None,
) -> tuple[Literal["ok", "validation_failed", "rate_limited", "error"], dict | None, str | None]:
    """
    Returns (status, parsed_dict, error_message).
      - 'ok' -> parsed_dict is the validated ClassifyResult as a dict
      - 'validation_failed' -> response parsed as JSON but didn't match schema after retries
      - 'rate_limited' -> caller should back off and retry
      - 'error' -> network/API failure; error_message has details
    """
    client = client or _client()
    last_validation_error: str | None = None

    for attempt in range(_MAX_VALIDATION_RETRIES + 1):
        messages = [{"role": "user", "content": prompt}]
        if last_validation_error:
            # Feed the prior failure back so the model can self-correct.
            messages.append({
                "role": "user",
                "content": (
                    f"Your previous response failed schema validation: {last_validation_error}\n"
                    "Re-emit a single JSON object that matches the template exactly."
                ),
            })

        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
        except RateLimitError:
            return "rate_limited", None, "DeepSeek rate-limited"
        except APITimeoutError as e:
            return "error", None, f"timeout: {e}"
        except APIError as e:
            return "error", None, f"APIError: {e}"
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            return "error", None, f"{type(e).__name__}: {e}"
        except Exception as e:
            return "error", None, f"{type(e).__name__}: {e}"

        raw = resp.choices[0].message.content or ""
        try:
            payload = json.loads(raw)
            validated = ClassifyResult.model_validate(payload)
            return "ok", validated.model_dump(), None
        except (json.JSONDecodeError, ValidationError) as e:
            last_validation_error = str(e)[:300]
            if attempt < _MAX_VALIDATION_RETRIES:
                time.sleep(0.5)
                continue
            return "validation_failed", None, last_validation_error

    # Unreachable, satisfies type checker.
    return "validation_failed", None, last_validation_error
