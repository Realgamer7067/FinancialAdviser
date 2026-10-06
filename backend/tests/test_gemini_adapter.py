"""Tests for the V3 Phase 04 ModelAdapter (app/models_iface/model_adapter.py).
All HTTP is respx-mocked; no real network call is attempted anywhere here
(no GEMINI_API_KEY exists in this environment)."""

import httpx
import pytest
import respx
from pydantic import BaseModel

from app.core.config import settings
from app.models_iface.llm import StructuredOutputError
from app.models_iface.model_adapter import GeminiAdapter, ModelRequest, QwenAdapter, RetryClass


class _DummyOutput(BaseModel):
    value: str


def _request(**overrides) -> ModelRequest:
    defaults = dict(
        task_kind="extraction",
        schema_version="v1",
        model_id="gemini-3.5-flash-lite",
        thinking_level="low",
        output_token_limit=512,
        deadline_seconds=10.0,
        request_id="test-request-1",
        evidence_refs=["evidence-1"],
    )
    defaults.update(overrides)
    return ModelRequest(**defaults)


def _gen_content_response(text: str, finish_reason: str = "STOP", include_usage: bool = True) -> dict:
    body = {
        "candidates": [
            {
                "content": {"parts": [{"text": text}], "role": "model"},
                "finishReason": finish_reason,
            }
        ],
    }
    if include_usage:
        body["usageMetadata"] = {"promptTokenCount": 42, "candidatesTokenCount": 7}
    return body


GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"


@pytest.mark.asyncio
async def test_valid_structured_json_parses_with_retry_class_none(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    with respx.mock(assert_all_called=True) as mock:
        mock.post(GEMINI_URL).mock(
            return_value=httpx.Response(200, json=_gen_content_response('{"value": "ok"}'))
        )
        adapter = GeminiAdapter()
        response = await adapter.complete(_request(), "system", {"k": "v"}, _DummyOutput)

    assert response.retry_class == RetryClass.NONE
    assert response.parsed == {"value": "ok"}
    assert response.provider == "gemini"
    assert response.input_tokens == 42
    assert response.output_tokens == 7
    assert response.finish_reason == "STOP"
    assert response.error is None


@pytest.mark.asyncio
async def test_malformed_json_triggers_one_repair_then_permanent(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(GEMINI_URL)
        route.side_effect = [
            httpx.Response(200, json=_gen_content_response("{not valid json")),
            httpx.Response(200, json=_gen_content_response("{still not valid json")),
        ]
        adapter = GeminiAdapter()
        response = await adapter.complete(_request(), "system", {"k": "v"}, _DummyOutput)

    assert route.call_count == 2
    assert response.retry_class == RetryClass.PERMANENT
    assert response.parsed is None
    assert response.error is not None


@pytest.mark.asyncio
async def test_malformed_json_repaired_on_second_attempt_succeeds(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(GEMINI_URL)
        route.side_effect = [
            httpx.Response(200, json=_gen_content_response("{not valid json")),
            httpx.Response(200, json=_gen_content_response('{"value": "fixed"}')),
        ]
        adapter = GeminiAdapter()
        response = await adapter.complete(_request(), "system", {"k": "v"}, _DummyOutput)

    assert route.call_count == 2
    assert response.retry_class == RetryClass.NONE
    assert response.parsed == {"value": "fixed"}


@pytest.mark.asyncio
async def test_refusal_safety_blocked_response(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    with respx.mock(assert_all_called=True) as mock:
        mock.post(GEMINI_URL).mock(
            return_value=httpx.Response(200, json=_gen_content_response("", finish_reason="SAFETY"))
        )
        adapter = GeminiAdapter()
        response = await adapter.complete(_request(), "system", {"k": "v"}, _DummyOutput)

    assert response.parsed is None
    assert response.finish_reason == "SAFETY"
    assert response.retry_class == RetryClass.PERMANENT


@pytest.mark.asyncio
async def test_missing_usage_metadata_yields_none_tokens_not_crash(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    with respx.mock(assert_all_called=True) as mock:
        mock.post(GEMINI_URL).mock(
            return_value=httpx.Response(
                200, json=_gen_content_response('{"value": "ok"}', include_usage=False)
            )
        )
        adapter = GeminiAdapter()
        response = await adapter.complete(_request(), "system", {"k": "v"}, _DummyOutput)

    assert response.parsed == {"value": "ok"}
    assert response.input_tokens is None
    assert response.output_tokens is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_auth_failures_are_permanent(monkeypatch, status):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(GEMINI_URL).mock(return_value=httpx.Response(status, text="forbidden"))
        adapter = GeminiAdapter()
        response = await adapter.complete(_request(), "system", {"k": "v"}, _DummyOutput)

    assert route.call_count == 1
    assert response.retry_class == RetryClass.PERMANENT
    assert response.parsed is None


@pytest.mark.asyncio
async def test_429_is_retryable(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(GEMINI_URL).mock(return_value=httpx.Response(429, text="rate limited"))
        adapter = GeminiAdapter()
        response = await adapter.complete(_request(), "system", {"k": "v"}, _DummyOutput)

    assert route.call_count == 1
    assert response.retry_class == RetryClass.RETRYABLE


@pytest.mark.asyncio
async def test_timeout_is_retryable(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(GEMINI_URL).mock(side_effect=httpx.TimeoutException("deadline exceeded"))
        adapter = GeminiAdapter()
        response = await adapter.complete(_request(), "system", {"k": "v"}, _DummyOutput)

    assert route.call_count == 1
    assert response.retry_class == RetryClass.RETRYABLE


@pytest.mark.asyncio
async def test_5xx_is_retryable(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(GEMINI_URL).mock(return_value=httpx.Response(503, text="unavailable"))
        adapter = GeminiAdapter()
        response = await adapter.complete(_request(), "system", {"k": "v"}, _DummyOutput)

    assert route.call_count == 1
    assert response.retry_class == RetryClass.RETRYABLE


@pytest.mark.asyncio
async def test_not_configured_fails_fast_with_zero_http_calls(monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "")
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(GEMINI_URL).mock(return_value=httpx.Response(200, json={}))
        adapter = GeminiAdapter()
        response = await adapter.complete(_request(), "system", {"k": "v"}, _DummyOutput)

    assert route.call_count == 0
    assert response.retry_class == RetryClass.PERMANENT
    assert response.parsed is None
    assert response.error == "GEMINI_API_KEY not configured"


@pytest.mark.asyncio
async def test_qwen_adapter_translates_successful_complete_structured(monkeypatch):
    monkeypatch.setattr(settings, "qwen_api_key", "test-key")

    async def fake_complete_structured(system_prompt, user_payload, response_model, prompt_version):
        return _DummyOutput(value="ok"), {
            "model_name": "Qwen",
            "model_version": "qwen2.5-32b-instruct",
            "prompt_version": prompt_version,
        }

    adapter = QwenAdapter()
    monkeypatch.setattr(adapter._provider, "complete_structured", fake_complete_structured)

    response = await adapter.complete(
        _request(model_id="qwen2.5-32b-instruct"), "system", {"k": "v"}, _DummyOutput
    )

    assert response.provider == "qwen"
    assert response.model_id == "qwen2.5-32b-instruct"
    assert response.parsed == {"value": "ok"}
    assert response.retry_class == RetryClass.NONE
    assert response.error is None


@pytest.mark.asyncio
async def test_qwen_adapter_translates_structured_output_error_to_permanent(monkeypatch):
    monkeypatch.setattr(settings, "qwen_api_key", "test-key")

    async def fake_complete_structured(*args, **kwargs):
        raise StructuredOutputError("Invalid structured output from qwen2.5-32b-instruct: boom")

    adapter = QwenAdapter()
    monkeypatch.setattr(adapter._provider, "complete_structured", fake_complete_structured)

    response = await adapter.complete(
        _request(model_id="qwen2.5-32b-instruct"), "system", {"k": "v"}, _DummyOutput
    )

    assert response.provider == "qwen"
    assert response.retry_class == RetryClass.PERMANENT
    assert response.parsed is None
    assert response.error is not None
