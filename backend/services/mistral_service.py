"""Mistral AI client (REST API via httpx) returning validated Pydantic objects.

Same contract as GeminiClient: `generate_json(prompt, schema, system_instruction)`. Mistral's JSON mode
guarantees syntactically valid JSON; the expected JSON schema is given in the system prompt and the
answer is validated with Pydantic (one more attempt if it does not match).
"""

from __future__ import annotations

import json
import logging
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from backend.services.gemini_service import LLMError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

API_URL = "https://api.mistral.ai/v1/chat/completions"
_TRANSIENT_HTTP_CODES = {408, 429, 500, 502, 503, 504}


class MistralClient:
    provider = "mistral"

    def __init__(self, api_key: str, model: str, timeout_seconds: int = 60, max_attempts: int = 3) -> None:
        self.model_name = model
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._max_attempts = max_attempts

    def generate_json(self, prompt: str, schema: type[T], system_instruction: str) -> T:
        keys = ", ".join(schema.model_fields)
        system = (
            f"{system_instruction}\n\nRéponds uniquement avec un objet JSON dont les clés de premier niveau sont "
            f"exactement : {keys}. Ne recopie pas le schéma (pas de clé « properties »). Utilise null pour toute "
            f"valeur inconnue. Schéma de référence :\n{json.dumps(schema.model_json_schema(), ensure_ascii=False)}"
        )
        body = {
            "model": self.model_name,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"}
        last_error: str | None = None
        for attempt in range(1, self._max_attempts + 1):
            wait_seconds = min(2**attempt, 8)
            started = time.perf_counter()
            try:
                response = httpx.post(API_URL, json=body, headers=headers, timeout=self._timeout)
                if response.status_code == 429 and response.headers.get("x-ratelimit-limit-req-minute") == "0":
                    # A limit of 0 means the model is not included in the subscription: retrying is pointless.
                    raise LLMError(f"Le modèle {self.model_name} n'est pas inclus dans votre abonnement Mistral "
                                   "(limite de 0 requête/minute). Choisissez un autre MISTRAL_MODEL.")
                if response.status_code in _TRANSIENT_HTTP_CODES:
                    last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                    logger.warning(f"mistral transient error ({self.model_name}): {last_error}", extra={"attempt": attempt})
                    if retry_after := response.headers.get("retry-after"):
                        wait_seconds = min(float(retry_after) + 1, 65)
                elif response.is_error:
                    raise LLMError(f"Erreur API Mistral ({response.status_code}) : {response.text[:300]}")
                else:
                    data = json.loads(response.json()["choices"][0]["message"]["content"])
                    # Small models sometimes mirror the schema and nest the answer under "properties".
                    if isinstance(data, dict) and isinstance(data.get("properties"), dict) and "properties" not in schema.model_fields:
                        data = data["properties"]
                    result = schema.model_validate(data)
                    logger.info("mistral call succeeded", extra={"model": self.model_name, "schema": schema.__name__,
                                "attempt": attempt, "duration_ms": round((time.perf_counter() - started) * 1000)})
                    return result
            except ValidationError as exc:
                last_error = f"réponse non conforme au schéma : {exc}"
                logger.warning(f"mistral response failed validation ({self.model_name})", extra={"attempt": attempt})
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                last_error = repr(exc)
                logger.warning(f"mistral call error ({self.model_name}): {exc!r}", extra={"attempt": attempt})
            if attempt < self._max_attempts:
                time.sleep(wait_seconds)
        raise LLMError(f"Échec de l'appel Mistral après {self._max_attempts} tentatives : {last_error}")
