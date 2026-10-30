"""LLM access: provider-neutral protocol and factory, plus the Google Gemini client (google-genai SDK)."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from backend.config import Settings, get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_TRANSIENT_HTTP_CODES = {408, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """Raised when the LLM call fails or returns an unusable response."""


class LLMClient(Protocol):
    provider: str
    model_name: str

    def generate_json(self, prompt: str, schema: type[T], system_instruction: str) -> T: ...


def llm_label(client: LLMClient) -> str:
    """Engine label shown to users, e.g. 'mistral:mistral-small-latest'."""
    return f"{client.provider}:{client.model_name}"


class GeminiClient:
    provider = "gemini"

    def __init__(self, api_key: str, model: str, timeout_seconds: int = 60, max_attempts: int = 3) -> None:
        from google import genai  # noqa: PLC0415 - optional dependency, imported lazily
        from google.genai import types  # noqa: PLC0415

        self.model_name = model
        self._types = types
        self._max_attempts = max_attempts
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=timeout_seconds * 1000),
        )

    def generate_json(self, prompt: str, schema: type[T], system_instruction: str) -> T:
        from google.genai import errors  # noqa: PLC0415

        config = self._types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.1,
            response_mime_type="application/json",
            response_schema=schema,
        )
        last_error: Exception | None = None
        wait_seconds = 0.0
        for attempt in range(1, self._max_attempts + 1):
            if wait_seconds:
                time.sleep(wait_seconds)
            started = time.perf_counter()
            try:
                response = self._client.models.generate_content(model=self.model_name, contents=prompt, config=config)
                if not response.text:
                    raise LLMError("Réponse vide du modèle.")
                result = schema.model_validate_json(response.text)
                logger.info(
                    "gemini call succeeded",
                    extra={"model": self.model_name, "schema": schema.__name__, "attempt": attempt,
                           "duration_ms": round((time.perf_counter() - started) * 1000)},
                )
                return result
            except ValidationError as exc:
                # The model answered but not in the expected shape: one more try is worthwhile.
                last_error = exc
                logger.warning("gemini response failed validation", extra={"attempt": attempt, "error": str(exc)})
            except errors.APIError as exc:
                last_error = exc
                if exc.code not in _TRANSIENT_HTTP_CODES:
                    raise LLMError(f"Erreur API Gemini ({exc.code}) : {exc.message}") from exc
                logger.warning(f"gemini transient error {exc.code} ({self.model_name}): {exc.message}",
                               extra={"attempt": attempt, "code": exc.code})
                if exc.code == 429 and "per day" in str(exc.message):  # daily quota: retrying is pointless
                    raise LLMError(f"Quota journalier Gemini atteint pour {self.model_name}.") from exc
                # Rate limits (429) say how long to wait: honour it, within reason.
                if exc.code == 429 and (match := re.search(r"retry in ([\d.]+)s", str(exc.message))):
                    wait_seconds = min(float(match.group(1)) + 1, 65)
                    continue
            except LLMError as exc:
                last_error = exc
            except Exception as exc:  # network errors, timeouts
                last_error = exc
                logger.warning(f"gemini call error ({self.model_name}): {exc!r}", extra={"attempt": attempt})
            wait_seconds = min(2**attempt, 8)
        raise LLMError(f"Échec de l'appel Gemini après {self._max_attempts} tentatives : {last_error}")


_client_lock = threading.Lock()
_client: LLMClient | None = None
_client_override: LLMClient | None = None


def get_llm_client(settings: Settings | None = None) -> LLMClient | None:
    """Return the configured LLM client, or None in demo mode / without an API key."""
    if _client_override is not None:
        return _client_override
    settings = settings or get_settings()
    if not settings.ai_enabled:
        return None
    global _client
    with _client_lock:
        if _client is None or llm_label(_client) != f"{settings.llm_provider}:{settings.llm_model}":
            if settings.llm_provider == "mistral":
                from backend.services.mistral_service import MistralClient  # noqa: PLC0415 - avoids an import cycle

                _client = MistralClient(settings.mistral_api_key, settings.mistral_model, settings.llm_timeout_seconds)
            else:
                _client = GeminiClient(settings.gemini_api_key, settings.gemini_model, settings.llm_timeout_seconds)
    return _client


def set_llm_client_override(client: LLMClient | None) -> None:
    """Inject a fake client (tests, evaluation scripts)."""
    global _client_override
    _client_override = client
