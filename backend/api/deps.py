"""Shared API dependencies: authentication and settings."""

from __future__ import annotations

import secrets

from fastapi import Depends, Header, HTTPException, status

from backend.config import Settings, get_settings


def settings_dependency() -> Settings:
    return get_settings()


def _check_secret(provided: str | None, expected: str, name: str) -> None:
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"{name} n'est pas configuré côté serveur.")
    if not provided or not secrets.compare_digest(provided.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentification requise.")


def require_api_key(
    x_api_key: str | None = Header(default=None), settings: Settings = Depends(settings_dependency)
) -> None:
    """Every /api endpoint used by the Streamlit frontend requires the shared API key."""
    _check_secret(x_api_key, settings.api_key, "API_KEY")


def require_n8n_token(
    x_n8n_token: str | None = Header(default=None), settings: Settings = Depends(settings_dependency)
) -> None:
    """Callbacks from n8n use a separate token with access limited to the automation endpoints."""
    _check_secret(x_n8n_token, settings.n8n_api_token, "N8N_API_TOKEN")
