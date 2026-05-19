"""Unit tests for the structured classifier — the retry-with-feedback
loop, the four status branches, and Pydantic validation.

The real DeepSeek client is replaced with a hand-rolled fake so the test
suite stays offline. Each test feeds a deterministic response queue and
asserts the status enum + payload that comes back.
"""
from __future__ import annotations

import json
from typing import Iterable
from unittest.mock import MagicMock

import httpx
import pytest
from openai import APIError, APITimeoutError, RateLimitError

from app.tools.classification_tools import classify_company


def _valid_payload(ticker: str = "POOL") -> dict:
    """A payload shaped like a real DeepSeek JSON-mode response that
    satisfies the Pydantic ClassifyResult schema."""
    return {
        "ticker": ticker,
        "data": {
            "market_cap_tier": "mid",
            "sector": "Consumer Cyclical",
            "industry": "Specialty Retail",
            "revenue_model": "wholesale distribution",
            "customer_type": "B2B",
            "asset_intensity": "asset-light",
            "value_chain_position": "distributor",
            "geographic_exposure": "domestic",
            "inventory_strategy": "stocked inventory",
            "global_presence": "US-only",
        },
        "metadata": {
            "primary_category": "Consumer Goods",
            "logic_summary": "Pool supply distributor with stocked inventory.",
        },
    }


def _make_choice(content: str):
    """Wrap a response string in the OpenAI SDK's nested `.choices[0].message.content`
    shape using MagicMock so attribute access works without subclassing the SDK."""
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


class _FakeClient:
    """Replaces the OpenAI client. Returns successive items from `responses` —
    each item is either a string (return as response content) or an Exception
    instance (raise it). Records every call args for assertions."""

    def __init__(self, responses: Iterable):
        self._responses = list(responses)
        self.calls: list[dict] = []
        self.chat = self  # so `client.chat.completions.create(...)` works
        self.completions = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("FakeClient: ran out of canned responses")
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return _make_choice(nxt)


# ============ happy path ============


def test_classify_company_returns_ok_on_valid_response():
    fake = _FakeClient([json.dumps(_valid_payload())])
    status, payload, err = classify_company("prompt body", model="deepseek-v4-flash", client=fake)

    assert status == "ok"
    assert err is None
    assert payload is not None
    assert payload["ticker"] == "POOL"
    assert payload["metadata"]["primary_category"] == "Consumer Goods"
    assert len(fake.calls) == 1
    # JSON-mode flag must be forwarded to the API.
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


def test_classify_company_forwards_model_and_temperature():
    fake = _FakeClient([json.dumps(_valid_payload())])
    classify_company("prompt body", model="deepseek-v4-flash", temperature=0.3, client=fake)
    assert fake.calls[0]["model"] == "deepseek-v4-flash"
    assert fake.calls[0]["temperature"] == 0.3


# ============ rate limit ============


def _build_rate_limit_error() -> RateLimitError:
    """RateLimitError requires a body in newer openai SDKs — synthesize one."""
    return RateLimitError(
        message="rate limited",
        response=httpx.Response(429, request=httpx.Request("POST", "https://api.deepseek.com")),
        body=None,
    )


def test_classify_company_returns_rate_limited_status():
    fake = _FakeClient([_build_rate_limit_error()])
    status, payload, err = classify_company("prompt body", model="deepseek-v4-flash", client=fake)

    assert status == "rate_limited"
    assert payload is None
    assert err is not None
    # Doesn't retry on rate-limit (caller decides backoff).
    assert len(fake.calls) == 1


# ============ timeout / API error ============


def _build_api_timeout() -> APITimeoutError:
    return APITimeoutError(httpx.Request("POST", "https://api.deepseek.com"))


def test_classify_company_returns_error_on_timeout():
    fake = _FakeClient([_build_api_timeout()])
    status, payload, err = classify_company("p", model="deepseek-v4-flash", client=fake)

    assert status == "error"
    assert payload is None
    assert err and "timeout" in err


def test_classify_company_returns_error_on_api_error():
    api_err = APIError(
        message="server error",
        request=httpx.Request("POST", "https://api.deepseek.com"),
        body=None,
    )
    fake = _FakeClient([api_err])
    status, payload, err = classify_company("p", model="deepseek-v4-flash", client=fake)
    assert status == "error"
    assert err and "APIError" in err


def test_classify_company_returns_error_on_network_failure():
    fake = _FakeClient([httpx.ConnectError("connection refused")])
    status, payload, err = classify_company("p", model="deepseek-v4-flash", client=fake)
    assert status == "error"
    assert err and "ConnectError" in err


# ============ validation retries ============


def test_classify_company_self_corrects_on_invalid_json_first_then_valid():
    fake = _FakeClient(["not-json-at-all", json.dumps(_valid_payload())])
    status, payload, err = classify_company("prompt body", model="deepseek-v4-flash", client=fake)

    assert status == "ok"
    assert payload is not None and payload["ticker"] == "POOL"
    # First call is the original prompt; second call should append a
    # corrective system-style message about the schema failure.
    assert len(fake.calls) == 2
    second_messages = fake.calls[1]["messages"]
    assert len(second_messages) == 2
    assert "failed schema validation" in second_messages[1]["content"]


def test_classify_company_self_corrects_on_schema_failure_first_then_valid():
    bad_payload = {"ticker": "POOL"}  # missing data/metadata
    fake = _FakeClient([json.dumps(bad_payload), json.dumps(_valid_payload())])
    status, payload, err = classify_company("prompt", model="deepseek-v4-flash", client=fake)
    assert status == "ok"
    assert payload is not None
    assert len(fake.calls) == 2


def test_classify_company_returns_validation_failed_after_exhausting_retries():
    # 3 attempts (initial + 2 retries) all returning invalid output.
    fake = _FakeClient(["not-json"] * 3)
    status, payload, err = classify_company("p", model="deepseek-v4-flash", client=fake)

    assert status == "validation_failed"
    assert payload is None
    assert err is not None
    # All 3 attempts consumed.
    assert len(fake.calls) == 3


# ============ unknown / unexpected exception ============


def test_classify_company_returns_error_on_unexpected_exception():
    fake = _FakeClient([ValueError("something weird")])
    status, payload, err = classify_company("p", model="deepseek-v4-flash", client=fake)
    assert status == "error"
    assert err and "ValueError" in err
