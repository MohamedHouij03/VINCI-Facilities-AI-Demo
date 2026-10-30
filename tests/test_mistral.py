"""Mistral client (HTTP API mocked) and provider selection."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.schemas.extraction import GeminiExtractionPayload
from backend.services.extraction_service import run_extraction
from backend.services.gemini_service import LLMError, get_llm_client
from backend.services.mistral_service import MistralClient
from tests.test_extraction import GEMINI_PAYLOAD, STRUCTURED_REPORT


class FakeMistralApi:
    """Replays queued HTTP responses: (status, content string or None, headers)."""

    def __init__(self, responses: list[tuple[int, str | None, dict]]) -> None:
        self.responses = list(responses)
        self.requests: list[dict] = []

    def __call__(self, url: str, json: dict, headers: dict, timeout: float) -> httpx.Response:  # noqa: A002
        self.requests.append({"url": url, "json": json, "headers": headers})
        status, content, extra_headers = self.responses.pop(0)
        body = {"choices": [{"message": {"content": content}}]} if content is not None else {"message": "error"}
        return httpx.Response(status, json=body, headers=extra_headers, request=httpx.Request("POST", url))


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    waits: list[float] = []
    monkeypatch.setattr("backend.services.mistral_service.time.sleep", waits.append)
    return waits


def test_valid_json_answer_is_parsed(monkeypatch, no_sleep) -> None:
    api = FakeMistralApi([(200, json.dumps(GEMINI_PAYLOAD), {})])
    monkeypatch.setattr(httpx, "post", api)
    result = MistralClient("key", "mistral-small-latest").generate_json("rapport", GeminiExtractionPayload, "consigne")
    assert result.fields.intervention_id == "RI-2026-2001"
    request = api.requests[0]
    assert request["headers"]["Authorization"] == "Bearer key"
    assert request["json"]["response_format"] == {"type": "json_object"}
    assert '"fields"' in request["json"]["messages"][0]["content"]  # expected schema given in the system prompt


def test_schema_mismatch_is_retried(monkeypatch, no_sleep) -> None:
    api = FakeMistralApi([(200, '{"unexpected": true}', {}), (200, json.dumps(GEMINI_PAYLOAD), {})])
    monkeypatch.setattr(httpx, "post", api)
    result = MistralClient("key", "m").generate_json("rapport", GeminiExtractionPayload, "consigne")
    assert result.fields.status == "Terminée" and len(api.requests) == 2


def test_rate_limit_waits_for_retry_after(monkeypatch, no_sleep) -> None:
    api = FakeMistralApi([(429, None, {"retry-after": "3"}), (200, json.dumps(GEMINI_PAYLOAD), {})])
    monkeypatch.setattr(httpx, "post", api)
    MistralClient("key", "m").generate_json("rapport", GeminiExtractionPayload, "consigne")
    assert no_sleep == [4.0]


def test_invalid_key_fails_without_retry_and_falls_back_to_rules(monkeypatch, settings, no_sleep) -> None:
    api = FakeMistralApi([(401, None, {})])
    monkeypatch.setattr(httpx, "post", api)
    client = MistralClient("bad-key", "m")
    with pytest.raises(LLMError, match="401"):
        client.generate_json("rapport", GeminiExtractionPayload, "consigne")
    api.responses = [(401, None, {})]
    outcome = run_extraction(STRUCTURED_REPORT, client, settings)
    assert outcome.engine == "rules" and "IA générative indisponible" in (outcome.note or "")


def test_provider_selection(configure) -> None:
    settings = configure(demo_mode="false", llm_provider="mistral", mistral_api_key="k", mistral_model="mistral-small-latest")
    client = get_llm_client(settings)
    assert isinstance(client, MistralClient) and client.model_name == "mistral-small-latest"
    assert configure(demo_mode="false", llm_provider="mistral", mistral_api_key="").ai_enabled is False
