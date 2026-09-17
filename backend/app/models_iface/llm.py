"""LLMProvider (Section 13/42). Qwen via any OpenAI-compatible endpoint --
DashScope, OpenRouter, or a self-hosted vLLM server -- config-driven, not
hardcoded to one host. Every call returns pydantic-validated structured output;
invalid JSON gets one repair retry before failing loudly (never silently
accepted -- Section 42)."""

import itertools
import json
from abc import ABC, abstractmethod
from typing import TypeVar

from openai import APIError, AsyncOpenAI, RateLimitError
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from app.core.config import settings

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(Exception):
    """Raised when the model can't produce schema-valid JSON after retries.
    Callers must treat this as a missing signal (reduce confidence / drop the
    candidate), never fabricate a result (Section 43)."""


class LLMProvider(ABC):
    @abstractmethod
    async def complete_structured(
        self, system_prompt: str, user_payload: dict, response_model: type[T], prompt_version: str
    ) -> tuple[T, dict]:
        """Returns (validated_object, metadata) where metadata carries
        model_name/model_version/prompt_version/timestamp (Section 26)."""


class QwenOpenAICompatibleProvider(LLMProvider):
    def __init__(self):
        # Optional key pool (V3, 2026-09-16 -- multiple Gemini API keys, each
        # with its own independent quota, pointed at the same base_url/model
        # via QWEN_BASE_URL/QWEN_MODEL). Round-robins across them per call to
        # spread load proactively, and on a 429 specifically retries with the
        # NEXT key immediately rather than backing off against an already
        # -exhausted one. A single configured key behaves exactly as before.
        keys = [settings.qwen_api_key] if settings.qwen_api_key else []
        keys += [k.strip() for k in settings.qwen_api_key_pool.split(",") if k.strip()]
        keys = list(dict.fromkeys(keys))  # de-dupe, preserve order
        self._keys = keys or ["unset"]
        self._clients = [AsyncOpenAI(base_url=settings.qwen_base_url, api_key=k) for k in self._keys]
        self._client_cycle = itertools.cycle(range(len(self._clients)))
        self._model = settings.qwen_model
        # Honest label derived from the configured host, not assumed --
        # "qwen_base_url" is the settings field name (kept for backward
        # compatibility with existing config/migrations/tests), but this
        # class works with any OpenAI-compatible endpoint per its own
        # docstring, Gemini's included.
        self._provider_label = "Gemini" if "generativelanguage.googleapis.com" in settings.qwen_base_url else self._model

    @retry(
        reraise=True,
        stop=stop_after_attempt(2),
        wait=wait_fixed(1),
        retry=retry_if_exception_type(StructuredOutputError),
    )
    async def complete_structured(
        self, system_prompt: str, user_payload: dict, response_model: type[T], prompt_version: str
    ) -> tuple[T, dict]:
        if not settings.qwen_configured:
            # Fail fast into the same "missing signal" path callers already
            # handle, instead of a pointless network call/retry (Section 50).
            raise StructuredOutputError("QWEN_API_KEY not configured")

        schema_hint = json.dumps(response_model.model_json_schema())
        messages = [
            {
                "role": "system",
                "content": (
                    f"{system_prompt}\n\nRespond ONLY with JSON matching this schema, no prose, "
                    f"no chain-of-thought, no markdown fences:\n{schema_hint}"
                ),
            },
            {"role": "user", "content": json.dumps(user_payload, default=str)},
        ]
        response = await self._create_completion(messages)

        if not response.choices:
            # Observed in practice: OpenRouter returning a 200 with a
            # provider-side error embedded in the body and `choices=None`
            # instead of raising -- the openai SDK doesn't treat that as an
            # APIError since the HTTP status was 200.
            raise StructuredOutputError(f"No choices returned from {self._model}")

        choice = response.choices[0]
        raw = choice.message.content
        if not raw:
            # Some OpenAI-compatible backends (OpenRouter routing to a
            # reasoning/free-tier model, content filtering, truncation) return
            # a 200 with an empty/None message.content instead of an API
            # error. Treat that the same as any other malformed-output case
            # rather than crashing the whole pipeline run.
            raise StructuredOutputError(
                f"Empty completion from {self._model} (finish_reason={choice.finish_reason!r})"
            )
        try:
            parsed = response_model.model_validate_json(raw)
        except (ValidationError, ValueError, TypeError) as exc:
            raise StructuredOutputError(f"Invalid structured output from {self._model}: {exc}") from exc

        metadata = {
            # Was a hardcoded "Qwen" literal -- misleading once this
            # config-driven OpenAI-compatible provider gets pointed at a
            # different backend (e.g. Gemini's OpenAI-compat endpoint).
            # Derive from the actual configured base_url/model instead of
            # asserting a specific vendor (Section 26: honest provenance).
            "model_name": self._provider_label,
            "model_version": self._model,
            "prompt_version": prompt_version,
        }
        return parsed, metadata

    async def _create_completion(self, messages: list[dict]):
        """Round-robins across the configured key pool for load spreading;
        on a 429 specifically, retries with the NEXT key immediately (up to
        one full lap of the pool) instead of hammering an already-exhausted
        key. Any other APIError still fails through to StructuredOutputError
        -- Section 50: a failed specialist shouldn't take down the run."""
        last_rate_limit_exc: RateLimitError | None = None
        for _ in range(len(self._clients)):
            client_index = next(self._client_cycle)
            client = self._clients[client_index]
            try:
                return await client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
            except RateLimitError as exc:
                last_rate_limit_exc = exc
                continue  # try the next key in the pool, no sleep
            except APIError as exc:
                raise StructuredOutputError(f"Qwen API call failed: {exc}") from exc

        raise StructuredOutputError(
            f"All {len(self._clients)} configured key(s) rate-limited: {last_rate_limit_exc}"
        )
