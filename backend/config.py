"""Application settings loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General -----------------------------------------------------------
    app_name: str = "VINCI Facilities AI Demo"
    demo_mode: bool = True
    log_level: str = "INFO"
    api_key: str = Field(default="", description="Shared secret required by every /api endpoint.")

    # --- Storage -----------------------------------------------------------
    data_dir: Path = PROJECT_ROOT / "data"
    database_url: str = ""
    sample_data_dir: Path = PROJECT_ROOT / "sample_data"
    seed_on_startup: bool = True
    index_on_startup: bool = True

    # --- Generative AI provider -----------------------------------------------
    llm_provider: Literal["gemini", "mistral"] = "gemini"
    llm_timeout_seconds: int = 60
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    mistral_api_key: str = ""
    mistral_model: str = "ministral-14b-latest"

    # --- Document processing -------------------------------------------------
    max_upload_mb: int = 10
    max_pdf_pages: int = 30
    ocr_min_chars_per_page: int = 40
    ocr_language: str = "fra"
    tessdata_dir: str = ""

    # --- RAG -------------------------------------------------------------------
    embedding_backend: str = "sentence-transformers"  # or "hashing" (offline, lexical)
    embedding_model: str = "intfloat/multilingual-e5-small"
    rag_top_k: int = 5
    # Cosine-similarity threshold below which a question is treated as unsupported by the documents.
    # Calibrated on sample_data/evaluation/rag_questions.json (scripts/evaluate_rag.py).
    rag_min_score: float = 0.84
    rag_min_score_hashing: float = 0.30  # the lexical fallback has a different score scale
    rag_context_margin: float = 0.05  # passages within this margin of the best score are used as context
    chunk_size: int = 900
    chunk_overlap: int = 150

    # --- Analytics -----------------------------------------------------------
    recurrence_threshold: int = 3
    recurrence_window_days: int = 30

    # --- n8n automation ------------------------------------------------------
    n8n_processing_webhook_url: str = ""
    n8n_followup_webhook_url: str = ""
    n8n_webhook_secret: str = ""
    n8n_api_token: str = ""
    n8n_callback_base_url: str = "http://localhost:8000"
    notification_email: str = ""
    webhook_timeout_seconds: float = 10.0
    webhook_max_attempts: int = 3
    webhook_backoff_seconds: float = 1.0

    @field_validator("data_dir", "sample_data_dir", mode="after")
    @classmethod
    def _anchor_to_project(cls, value: Path) -> Path:
        """Relative paths are resolved against the project root, not the current directory."""
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    @field_validator("tessdata_dir", mode="after")
    @classmethod
    def _anchor_tessdata(cls, value: str) -> str:
        if value and not Path(value).is_absolute():
            return str((PROJECT_ROOT / value).resolve())
        return value

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'maintenance.db').as_posix()}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def llm_api_key(self) -> str:
        return self.mistral_api_key if self.llm_provider == "mistral" else self.gemini_api_key

    @property
    def llm_model(self) -> str:
        return self.mistral_model if self.llm_provider == "mistral" else self.gemini_model

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def ai_enabled(self) -> bool:
        """The LLM is used only outside demo mode and when the selected provider has a key."""
        return not self.demo_mode and self.llm_configured

    @property
    def n8n_processing_enabled(self) -> bool:
        return not self.demo_mode and bool(self.n8n_processing_webhook_url and self.n8n_webhook_secret)

    @property
    def n8n_followup_enabled(self) -> bool:
        return not self.demo_mode and bool(self.n8n_followup_webhook_url and self.n8n_webhook_secret)

    def ensure_directories(self) -> None:
        for directory in (self.data_dir, self.uploads_dir, self.documents_dir, self.chroma_dir):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
