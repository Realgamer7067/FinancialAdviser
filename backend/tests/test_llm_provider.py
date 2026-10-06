"""Regression test for a live crash: OpenRouter returned HTTP 200 with
message.content=None (reasoning/free-tier routing quirk), and
`complete_structured` did `response.choices[0].message.content` with no
None-guard, raising an unhandled TypeError instead of the
StructuredOutputError callers already know how to degrade on."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from openai import RateLimitError
from pydantic import BaseModel

from app.models_iface.llm import QwenOpenAICompatibleProvider, StructuredOutputError


def _rate_limit_error():
    request = httpx.Request("POST", "https://example.test/chat/completions")
    response = httpx.Response(429, request=request, json={"error": {"message": "rate limited"}})
    return RateLimitError("rate limited", response=response, body=None)


class _DummyOutput(BaseModel):
    value: str


def _fake_response(content, finish_reason="stop"):
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


@pytest.mark.asyncio
async def test_empty_completion_content_raises_structured_output_error(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "qwen_api_key", "test-key")
    provider = QwenOpenAICompatibleProvider()
    with patch.object(
        provider._clients[0].chat.completions, "create", AsyncMock(return_value=_fake_response(None, "length"))
    ):
        with pytest.raises(StructuredOutputError):
            await provider.complete_structured("system", {}, _DummyOutput, "v1")


@pytest.mark.asyncio
async def test_none_choices_raises_structured_output_error(monkeypatch):
    """A second live crash: OpenRouter returned HTTP 200 with a
    provider-side error embedded in the body and `choices=None` (not just an
    empty message) -- `response.choices[0]` isn't reachable at all in that
    case, so the guard has to check `response.choices` itself first."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "qwen_api_key", "test-key")
    provider = QwenOpenAICompatibleProvider()
    broken_response = SimpleNamespace(choices=None)
    with patch.object(
        provider._clients[0].chat.completions, "create", AsyncMock(return_value=broken_response)
    ):
        with pytest.raises(StructuredOutputError):
            await provider.complete_structured("system", {}, _DummyOutput, "v1")


@pytest.mark.asyncio
async def test_valid_completion_content_still_parses(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "qwen_api_key", "test-key")
    provider = QwenOpenAICompatibleProvider()
    with patch.object(
        provider._clients[0].chat.completions,
        "create",
        AsyncMock(return_value=_fake_response('{"value": "ok"}')),
    ):
        parsed, meta = await provider.complete_structured("system", {}, _DummyOutput, "v1")
    assert parsed.value == "ok"
    assert meta["prompt_version"] == "v1"


@pytest.mark.asyncio
async def test_key_pool_round_robins_across_calls(monkeypatch):
    """Multiple keys configured (e.g. 3 separate Gemini API keys, each with
    its own quota) -- successive calls should spread across all of them,
    not hammer the first one repeatedly."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "qwen_api_key", "key-1")
    monkeypatch.setattr(settings, "qwen_api_key_pool", "key-2,key-3")
    provider = QwenOpenAICompatibleProvider()
    assert len(provider._clients) == 3

    mocks = [AsyncMock(return_value=_fake_response('{"value": "ok"}')) for _ in provider._clients]
    for client, mock in zip(provider._clients, mocks):
        client.chat.completions.create = mock

    for _ in range(6):
        await provider.complete_structured("system", {}, _DummyOutput, "v1")

    # 6 calls across 3 keys, round-robin -> each key used exactly twice.
    for mock in mocks:
        assert mock.call_count == 2


@pytest.mark.asyncio
async def test_rate_limit_on_one_key_retries_with_the_next(monkeypatch):
    """A 429 on the currently-selected key must not fail the call outright
    when another key in the pool still has quota -- it should retry with
    the next key immediately, not back off against the exhausted one."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "qwen_api_key", "key-1")
    monkeypatch.setattr(settings, "qwen_api_key_pool", "key-2")
    provider = QwenOpenAICompatibleProvider()
    assert len(provider._clients) == 2

    provider._clients[0].chat.completions.create = AsyncMock(side_effect=_rate_limit_error())
    provider._clients[1].chat.completions.create = AsyncMock(return_value=_fake_response('{"value": "ok"}'))

    parsed, meta = await provider.complete_structured("system", {}, _DummyOutput, "v1")

    assert parsed.value == "ok"
    provider._clients[0].chat.completions.create.assert_awaited_once()
    provider._clients[1].chat.completions.create.assert_awaited_once()


@pytest.mark.asyncio
async def test_all_keys_rate_limited_raises_structured_output_error(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "qwen_api_key", "key-1")
    monkeypatch.setattr(settings, "qwen_api_key_pool", "key-2")
    provider = QwenOpenAICompatibleProvider()

    for client in provider._clients:
        client.chat.completions.create = AsyncMock(side_effect=_rate_limit_error())

    with pytest.raises(StructuredOutputError, match="rate-limited"):
        await provider.complete_structured("system", {}, _DummyOutput, "v1")

    # One lap of the pool per outer call attempt -- complete_structured's own
    # @retry(stop_after_attempt(2)) treats StructuredOutputError (which
    # exhausting the whole pool raises) as retryable, so each client gets
    # hit once per outer attempt: 2 attempts -> 2 calls per client.
    for client in provider._clients:
        assert client.chat.completions.create.call_count == 2
