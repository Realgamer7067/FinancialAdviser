"""LLMProvider (Section 13/42). Qwen via any OpenAI-compatible endpoint --
DashScope, OpenRouter, or a self-hosted vLLM server -- config-driven, not
hardcoded to one host. Every call returns pydantic-validated structured output;
invalid JSON gets one repair retry before failing loudly (never silently
accepted -- Section 42)."""

import json
from abc import ABC, abstractmethod
from typing import TypeVar

from openai import APIError, AsyncOpenAI
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
        self._client = AsyncOpenAI(base_url=settings.qwen_base_url, api_key=settings.qwen_api_key or "unset")
        self._model = settings.qwen_model

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
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.2,
            )
        except APIError as exc:
            # Auth/connection/rate-limit/etc -- a missing signal, not a crash
            # (Section 50: a failed specialist shouldn't take down the run).
            raise StructuredOutputError(f"Qwen API call failed: {exc}") from exc

        raw = response.choices[0].message.content
        try:
            parsed = response_model.model_validate_json(raw)
        except (ValidationError, ValueError, TypeError) as exc:
            raise StructuredOutputError(f"Invalid structured output from {self._model}: {exc}") from exc

        metadata = {
            "model_name": "Qwen",
            "model_version": self._model,
            "prompt_version": prompt_version,
        }
        return parsed, metadata
