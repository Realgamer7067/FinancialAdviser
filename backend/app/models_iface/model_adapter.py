"""ModelAdapter (V3 Phase 04, Section 11.3 of the V3 implementation plan).

Provider-neutral typed request/response contract for LLM calls, additive to
(not a replacement for) `app.models_iface.llm.LLMProvider`. `GeminiAdapter` is
a real REST implementation against the Gemini `generateContent` endpoint
using `httpx` directly (no SDK -- this venv has no `pip`). `QwenAdapter` is a
thin translation wrapper around the existing `QwenOpenAICompatibleProvider`
so Qwen stays usable through this same interface without touching `llm.py`.

Design principle carried over from the rest of this codebase: deterministic
code decides retry/failure classification, the LLM never gets a silent pass
on invalid JSON (Section 42/43) -- either it validates or the caller gets a
clearly-classified failure back, never a crash and never a fabricated result.

Endpoint shape confirmed against https://ai.google.dev/api/generate-content
(2026-09-14): `POST /v1beta/models/{model}:generateContent`,
`contents[].{role,parts[].text}`, `systemInstruction`, `generationConfig.
{maxOutputTokens, responseMimeType, responseSchema, thinkingConfig.
thinkingLevel}`; response `candidates[].{content, finishReason}` with
finishReason in {STOP, MAX_TOKENS, SAFETY, RECITATION, ...}, and
`usageMetadata.{promptTokenCount, candidatesTokenCount}`. A prompt blocked
before any candidate is produced comes back as `promptFeedback.blockReason`
with no `candidates` key at all -- handled explicitly below, not assumed
absent. NOTE for the coordinator: two other fetched pages
(docs/text-generation, docs/structured-output) described a *different*,
newer "Interactions API" (`/v1beta/interactions`, `response_format`/`input`
fields) -- this module deliberately targets the classic `generateContent`
endpoint per the frozen task instructions, but that surface should be
re-verified before any live key is wired up.
"""

import json
import time
import uuid
from abc import ABC, abstractmethod
from typing import Literal, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import settings
from app.models_iface.llm import QwenOpenAICompatibleProvider, StructuredOutputError

T = TypeVar("T", bound=BaseModel)


class ModelRequest(BaseModel):
    task_kind: Literal["extraction", "synthesis", "verification", "classification"]
    schema_version: str
    model_id: str
    thinking_level: Literal["low", "medium", "high"] | None = None
    output_token_limit: int
    deadline_seconds: float
    request_id: str
    evidence_refs: list[str] = []


class RetryClass:
    """Plain string constants, not an Enum -- frozen contract shape."""

    NONE = "none"
    RETRYABLE = "retryable"
    PERMANENT = "permanent"


class ModelResponse(BaseModel):
    parsed: dict | None
    provider: str
    model_id: str
    input_tokens: int | None
    output_tokens: int | None
    finish_reason: str
    grounding_refs: list[str] = []
    retry_class: str
    latency_ms: float
    error: str | None = None


class ModelAdapter(ABC):
    @abstractmethod
    async def complete(
        self, request: ModelRequest, system_prompt: str, user_payload: dict, response_model: type[T]
    ) -> ModelResponse:
        ...


# Gemini finishReason values that mean the model refused/was blocked rather
# than producing (possibly malformed) content -- best-effort mapping, not
# spelled out in the V3 plan's Section 12.3 table (which covers HTTP-level
# failures, not in-band refusals). Flagged for the coordinator to confirm.
_REFUSAL_FINISH_REASONS = {"SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"}


def _sanitize_schema_for_gemini(schema: dict) -> dict:
    """Strip Pydantic JSON Schema constructs Gemini's OpenAPI-3.0-subset
    `responseSchema` doesn't accept ($defs/$ref, title, default, additional
    metadata keys). Inlines single-level $defs by $ref lookup; nested models
    in this codebase's current council schemas are all flat, so this is a
    best-effort generic pass, not exhaustively tested against deep nesting.
    """
    defs = schema.get("$defs", {})

    def _clean(node):
        if isinstance(node, dict):
            if "$ref" in node:
                ref_name = node["$ref"].rsplit("/", 1)[-1]
                return _clean(defs.get(ref_name, {}))
            out = {}
            for key, value in node.items():
                if key in ("$defs", "title", "default", "additionalProperties"):
                    continue
                out[key] = _clean(value)
            return out
        if isinstance(node, list):
            return [_clean(v) for v in node]
        return node

    return _clean(schema)


class GeminiAdapter(ModelAdapter):
    def __init__(self):
        self._base_url = settings.gemini_base_url

    async def complete(
        self, request: ModelRequest, system_prompt: str, user_payload: dict, response_model: type[T]
    ) -> ModelResponse:
        if not settings.gemini_configured:
            # Fail fast, same pattern as QwenOpenAICompatibleProvider's
            # qwen_configured check -- no network call attempted.
            return ModelResponse(
                parsed=None,
                provider="gemini",
                model_id=request.model_id,
                input_tokens=None,
                output_tokens=None,
                finish_reason="error",
                retry_class=RetryClass.PERMANENT,
                latency_ms=0.0,
                error="GEMINI_API_KEY not configured",
            )

        start = time.monotonic()
        response_schema = _sanitize_schema_for_gemini(response_model.model_json_schema())
        async with httpx.AsyncClient(timeout=request.deadline_seconds) as client:
            first = await self._call_once(client, request, system_prompt, user_payload, response_schema)
            result = self._handle_http_result(first, request, response_model, start)
            if result is not None:
                return result

            # First HTTP call succeeded (200) but content failed schema
            # validation -- exactly one repair retry, mirroring the
            # bounded-ness of QwenOpenAICompatibleProvider's single retry,
            # but as a real second request carrying the bad output + the
            # validation error so the model has something to fix.
            bad_output, validation_error = first["_repair_context"]
            repair_payload = dict(user_payload)
            repair_user_text = (
                f"{json.dumps(user_payload, default=str)}\n\n"
                "Your previous response failed schema validation and must be "
                f"corrected. Previous response:\n{bad_output}\n\nValidation error:\n"
                f"{validation_error}\n\nRespond again with ONLY corrected JSON matching the schema."
            )
            retry_http = await self._call_once(
                client, request, system_prompt, {"_repair": True}, response_schema, raw_user_text=repair_user_text
            )
            retry_result = self._handle_http_result(retry_http, request, response_model, start)
            if retry_result is not None:
                return retry_result

            # Still invalid after the one repair attempt -> permanent.
            _, validation_error2 = retry_http["_repair_context"]
            input_tokens, output_tokens, finish_reason = self._usage_from_result(retry_http)
            latency_ms = (time.monotonic() - start) * 1000
            return ModelResponse(
                parsed=None,
                provider="gemini",
                model_id=request.model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
                retry_class=RetryClass.PERMANENT,
                latency_ms=latency_ms,
                error=f"Invalid structured output after repair retry: {validation_error2}",
            )

    @staticmethod
    def _usage_from_result(call_result: dict) -> tuple[int | None, int | None, str]:
        http_response = call_result.get("_http_response")
        if http_response is None:
            return None, None, "error"
        try:
            data = http_response.json()
        except ValueError:
            return None, None, "error"
        usage = data.get("usageMetadata", {})
        candidates = data.get("candidates") or [{}]
        finish_reason = candidates[0].get("finishReason", "UNKNOWN")
        return usage.get("promptTokenCount"), usage.get("candidatesTokenCount"), finish_reason

    async def _call_once(
        self,
        client: httpx.AsyncClient,
        request: ModelRequest,
        system_prompt: str,
        user_payload: dict,
        response_schema: dict,
        raw_user_text: str | None = None,
    ) -> dict:
        url = f"{self._base_url}/models/{request.model_id}:generateContent"
        headers = {"x-goog-api-key": settings.gemini_api_key, "Content-Type": "application/json"}
        generation_config: dict = {
            "maxOutputTokens": request.output_token_limit,
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
        }
        if request.thinking_level is not None:
            generation_config["thinkingConfig"] = {"thinkingLevel": request.thinking_level}

        user_text = raw_user_text if raw_user_text is not None else json.dumps(user_payload, default=str)
        body = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "generationConfig": generation_config,
        }

        try:
            http_response = await client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            return {"_transport_error": ("timeout", str(exc))}

        return {"_http_response": http_response}

    def _handle_http_result(
        self,
        call_result: dict,
        request: ModelRequest,
        response_model: type[T],
        start: float,
    ) -> ModelResponse | None:
        """Returns a terminal ModelResponse for anything that isn't a
        "successful HTTP call but content needs a repair retry" case; in
        that one case returns None and stashes (raw_text, validation_error)
        onto call_result["_repair_context"] for the caller to use.
        """
        latency_ms = (time.monotonic() - start) * 1000

        if "_transport_error" in call_result:
            _, detail = call_result["_transport_error"]
            return ModelResponse(
                parsed=None,
                provider="gemini",
                model_id=request.model_id,
                input_tokens=None,
                output_tokens=None,
                finish_reason="error",
                retry_class=RetryClass.RETRYABLE,
                latency_ms=latency_ms,
                error=f"Request timed out: {detail}",
            )

        http_response: httpx.Response = call_result["_http_response"]
        status = http_response.status_code

        if status == 429:
            return ModelResponse(
                parsed=None, provider="gemini", model_id=request.model_id, input_tokens=None,
                output_tokens=None, finish_reason="error", retry_class=RetryClass.RETRYABLE,
                latency_ms=latency_ms, error=f"Rate limited (HTTP 429): {http_response.text[:500]}",
            )
        if status in (401, 403):
            return ModelResponse(
                parsed=None, provider="gemini", model_id=request.model_id, input_tokens=None,
                output_tokens=None, finish_reason="error", retry_class=RetryClass.PERMANENT,
                latency_ms=latency_ms, error=f"Auth failure (HTTP {status}): {http_response.text[:500]}",
            )
        if status >= 500:
            return ModelResponse(
                parsed=None, provider="gemini", model_id=request.model_id, input_tokens=None,
                output_tokens=None, finish_reason="error", retry_class=RetryClass.RETRYABLE,
                latency_ms=latency_ms, error=f"Server error (HTTP {status}): {http_response.text[:500]}",
            )
        if status >= 400:
            # Any other 4xx (e.g. bad request / unsupported capability
            # combination) is treated as permanent, not retryable.
            return ModelResponse(
                parsed=None, provider="gemini", model_id=request.model_id, input_tokens=None,
                output_tokens=None, finish_reason="error", retry_class=RetryClass.PERMANENT,
                latency_ms=latency_ms, error=f"Request rejected (HTTP {status}): {http_response.text[:500]}",
            )

        try:
            data = http_response.json()
        except ValueError as exc:
            return ModelResponse(
                parsed=None, provider="gemini", model_id=request.model_id, input_tokens=None,
                output_tokens=None, finish_reason="error", retry_class=RetryClass.PERMANENT,
                latency_ms=latency_ms, error=f"Non-JSON HTTP body: {exc}",
            )

        usage = data.get("usageMetadata", {})
        input_tokens = usage.get("promptTokenCount")
        output_tokens = usage.get("candidatesTokenCount")

        candidates = data.get("candidates")
        if not candidates:
            # Blocked before any candidate was produced -- promptFeedback,
            # no candidates[] key at all.
            block_reason = data.get("promptFeedback", {}).get("blockReason", "UNKNOWN")
            return ModelResponse(
                parsed=None, provider="gemini", model_id=request.model_id,
                input_tokens=input_tokens, output_tokens=output_tokens,
                finish_reason=block_reason, retry_class=RetryClass.PERMANENT,
                latency_ms=latency_ms, error=f"Prompt blocked before generation: {block_reason}",
            )

        candidate = candidates[0]
        finish_reason = candidate.get("finishReason", "UNKNOWN")

        if finish_reason in _REFUSAL_FINISH_REASONS:
            return ModelResponse(
                parsed=None, provider="gemini", model_id=request.model_id,
                input_tokens=input_tokens, output_tokens=output_tokens,
                finish_reason=finish_reason, retry_class=RetryClass.PERMANENT,
                latency_ms=latency_ms, error=f"Response refused/blocked (finishReason={finish_reason})",
            )

        parts = candidate.get("content", {}).get("parts", [])
        raw_text = "".join(part.get("text", "") for part in parts)

        if not raw_text:
            # Empty content -- e.g. MAX_TOKENS truncation before any text,
            # or a malformed response. Route through the same repair-retry
            # path as invalid JSON rather than a distinct code path.
            call_result["_repair_context"] = (raw_text, f"empty response body (finishReason={finish_reason})")
            return None  # caller retries once, or finalizes as permanent using this context

        try:
            validated = response_model.model_validate_json(raw_text)
        except (ValidationError, ValueError, TypeError) as exc:
            reason_hint = " (truncated: MAX_TOKENS)" if finish_reason == "MAX_TOKENS" else ""
            call_result["_repair_context"] = (raw_text, f"{exc}{reason_hint}")
            return None

        return ModelResponse(
            parsed=validated.model_dump(mode="json"),
            provider="gemini",
            model_id=request.model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=finish_reason,
            grounding_refs=_extract_grounding_refs(candidate),
            retry_class=RetryClass.NONE,
            latency_ms=latency_ms,
        )


def _extract_grounding_refs(candidate: dict) -> list[str]:
    grounding = candidate.get("groundingMetadata")
    if not grounding:
        return []
    refs: list[str] = []
    for chunk in grounding.get("groundingChunks", []):
        web = chunk.get("web", {})
        uri = web.get("uri")
        if uri:
            refs.append(uri)
    return refs


class QwenAdapter(ModelAdapter):
    """Thin translation wrapper -- constructs a QwenOpenAICompatibleProvider
    internally and maps its (validated_object, metadata) return onto the new
    ModelResponse shape. `complete_structured` already does its own single
    internal repair retry (tenacity, Section 42) and collapses auth/rate-
    limit/schema failures into one StructuredOutputError -- so the mapping
    here is necessarily coarse: any failure becomes PERMANENT/parsed=None,
    since by the time it reaches us Qwen's own retry budget is already
    spent. Provider label stays "qwen" throughout, never relabeled as
    Gemini metadata (Section 11.3: "do not route Gemini through
    Qwen-labelled metadata" -- symmetrically, don't do the reverse either).
    """

    def __init__(self):
        self._provider = QwenOpenAICompatibleProvider()

    async def complete(
        self, request: ModelRequest, system_prompt: str, user_payload: dict, response_model: type[T]
    ) -> ModelResponse:
        start = time.monotonic()
        try:
            parsed, metadata = await self._provider.complete_structured(
                system_prompt, user_payload, response_model, request.schema_version
            )
        except StructuredOutputError as exc:
            latency_ms = (time.monotonic() - start) * 1000
            return ModelResponse(
                parsed=None,
                provider="qwen",
                model_id=request.model_id,
                input_tokens=None,
                output_tokens=None,
                finish_reason="error",
                retry_class=RetryClass.PERMANENT,
                latency_ms=latency_ms,
                error=str(exc),
            )

        latency_ms = (time.monotonic() - start) * 1000
        return ModelResponse(
            parsed=parsed.model_dump(mode="json"),
            provider="qwen",
            model_id=metadata.get("model_version", request.model_id),
            input_tokens=None,
            output_tokens=None,
            finish_reason="stop",
            retry_class=RetryClass.NONE,
            latency_ms=latency_ms,
        )


def new_request_id() -> str:
    return str(uuid.uuid4())
