"""Regression test for a live crash: OpenRouter returned HTTP 200 with
message.content=None (reasoning/free-tier routing quirk), and
`complete_structured` did `response.choices[0].message.content` with no
None-guard, raising an unhandled TypeError instead of the
StructuredOutputError callers already know how to degrade on."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from app.models_iface.llm import QwenOpenAICompatibleProvider, StructuredOutputError


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
        provider._client.chat.completions, "create", AsyncMock(return_value=_fake_response(None, "length"))
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
        provider._client.chat.completions, "create", AsyncMock(return_value=broken_response)
    ):
        with pytest.raises(StructuredOutputError):
            await provider.complete_structured("system", {}, _DummyOutput, "v1")


@pytest.mark.asyncio
async def test_valid_completion_content_still_parses(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "qwen_api_key", "test-key")
    provider = QwenOpenAICompatibleProvider()
    with patch.object(
        provider._client.chat.completions,
        "create",
        AsyncMock(return_value=_fake_response('{"value": "ok"}')),
    ):
        parsed, meta = await provider.complete_structured("system", {}, _DummyOutput, "v1")
    assert parsed.value == "ok"
    assert meta["prompt_version"] == "v1"
