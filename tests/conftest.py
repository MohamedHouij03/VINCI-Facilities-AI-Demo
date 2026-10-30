"""Shared fixtures: isolated data directory, demo settings, FastAPI test client and fake LLM."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from backend.config import PROJECT_ROOT, Settings, get_settings
from backend.database import reset_engine
from backend.services.gemini_service import LLMError, set_llm_client_override
from backend.services.pdf_service import resolve_tessdata
from backend.services.rag_service import set_rag_service

API_KEY = "test-api-key"
N8N_TOKEN = "test-n8n-token"
SAMPLE_REPORTS = PROJECT_ROOT / "sample_data" / "reports"
TESSDATA_DIR = PROJECT_ROOT / "data" / "tessdata"


@pytest.fixture(scope="session", autouse=True)
def _isolate_data_dir(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Keep DATA_DIR pointing to a temporary folder for the whole session, so that no code path
    (including late background work) can ever touch the developer's real ./data directory."""
    previous = os.environ.get("DATA_DIR")
    os.environ["DATA_DIR"] = str(tmp_path_factory.mktemp("session-data"))
    yield
    if previous is None:
        os.environ.pop("DATA_DIR", None)
    else:
        os.environ["DATA_DIR"] = previous


def _reset_singletons() -> None:
    get_settings.cache_clear()
    resolve_tessdata.cache_clear()
    reset_engine()
    set_rag_service(None)
    set_llm_client_override(None)


@pytest.fixture
def configure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Settings]]:
    """Return a function that (re)configures the application settings for a test."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)  # ignore the developer's .env

    def apply(**overrides: object) -> Settings:
        values: dict[str, object] = {
            "API_KEY": API_KEY,
            "N8N_API_TOKEN": N8N_TOKEN,
            "DATA_DIR": tmp_path / "data",
            "DATABASE_URL": "",
            "DEMO_MODE": "true",
            "GEMINI_API_KEY": "",
            "MISTRAL_API_KEY": "",
            "LLM_PROVIDER": "gemini",
            "EMBEDDING_BACKEND": "hashing",
            "RAG_MIN_SCORE_HASHING": "0.05",
            "TESSDATA_DIR": str(TESSDATA_DIR),
            "N8N_PROCESSING_WEBHOOK_URL": "",
            "N8N_FOLLOWUP_WEBHOOK_URL": "",
            "N8N_WEBHOOK_SECRET": "",
            "NOTIFICATION_EMAIL": "",
            "WEBHOOK_BACKOFF_SECONDS": "0",
            "SEED_ON_STARTUP": "true",
            "INDEX_ON_STARTUP": "false",  # tests index explicitly (index_pending_documents)
        }
        values.update({key.upper(): value for key, value in overrides.items()})
        for key, value in values.items():
            monkeypatch.setenv(key, str(value))
        _reset_singletons()
        return get_settings()

    yield apply
    _reset_singletons()


@pytest.fixture
def settings(configure: Callable[..., Settings]) -> Settings:
    return configure()


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    from backend.main import create_app

    with TestClient(create_app()) as test_client:
        test_client.headers.update({"X-API-Key": API_KEY})
        yield test_client


class FakeLLM:
    """Deterministic stand-in for Gemini: returns queued payloads (dicts) or raises queued errors."""

    provider = "gemini"
    model_name = "fake-gemini"

    def __init__(self, responses: list[dict | Exception] | None = None) -> None:
        self.responses = list(responses or [])
        self.prompts: list[str] = []

    def generate_json(self, prompt: str, schema: type[BaseModel], system_instruction: str) -> BaseModel:
        self.prompts.append(prompt)
        if not self.responses:
            raise LLMError("no fake response queued")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return schema.model_validate_json(json.dumps(response))


def sample_report(name_prefix: str) -> Path:
    return next(SAMPLE_REPORTS.glob(f"{name_prefix}*.pdf"))
