"""HTTP client used by the Streamlit pages to call the FastAPI backend."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

FIELD_NAMES = {
    "reference": "N° d'intervention",
    "date": "Date",
    "building_code": "Bâtiment",
    "equipment_code": "Identifiant équipement",
    "equipment_name": "Équipement",
    "equipment_category": "Catégorie",
    "technician": "Technicien",
    "problem_description": "Problème",
    "actions_performed": "Actions réalisées",
    "status": "Statut",
    "follow_up_required": "Suivi nécessaire",
    "recommendations": "Recommandations",
    "question": "Question",
}


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"Erreur {response.status_code}"
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, list):  # FastAPI validation errors
        messages = []
        for error in detail:
            field = FIELD_NAMES.get(str(error.get("loc", ["", ""])[-1]), str(error.get("loc", [""])[-1]))
            message = str(error.get("msg", "")).removeprefix("Value error, ")
            messages.append(f"{field} : {message}")
        return " ; ".join(messages)
    return str(detail or f"Erreur {response.status_code}")


class ApiClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 120.0) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), headers={"X-API-Key": api_key}, timeout=timeout)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.ConnectError as exc:
            raise ApiError("L'API backend est injoignable. Vérifiez qu'elle est démarrée (BACKEND_URL).") from exc
        except httpx.TimeoutException as exc:
            raise ApiError("Le délai de réponse de l'API a été dépassé.") from exc
        if response.is_error:
            raise ApiError(_error_message(response), response.status_code, response.json() if response.content else None)
        return None if response.status_code == 204 else response.json()

    # -- reference data & analytics ------------------------------------------------------
    def health(self) -> bool:
        try:
            return self._client.get("/health", timeout=3).is_success
        except httpx.HTTPError:
            return False

    def buildings(self) -> list[dict]:
        return self._request("GET", "/api/buildings")

    def equipment(self, building: str | None = None) -> list[dict]:
        return self._request("GET", "/api/equipment", params={"building": building} if building else None)

    def dashboard(self, params: dict) -> dict:
        return self._request("GET", "/api/analytics/dashboard", params=params)

    # -- interventions -------------------------------------------------------------------------
    def interventions(self, params: dict) -> dict:
        return self._request("GET", "/api/interventions", params=params)

    def intervention(self, intervention_id: int) -> dict:
        return self._request("GET", f"/api/interventions/{intervention_id}")

    def update_intervention(self, intervention_id: int, changes: dict) -> dict:
        return self._request("PATCH", f"/api/interventions/{intervention_id}", json=changes)

    def complete_follow_up(self, intervention_id: int) -> dict:
        return self._request("POST", f"/api/interventions/{intervention_id}/complete-follow-up")

    # -- reports ---------------------------------------------------------------------------------
    def sample_reports(self) -> list[dict]:
        return self._request("GET", "/api/reports/samples")

    def submit_sample(self, name: str) -> dict:
        return self._request("POST", f"/api/reports/samples/{name}")

    def upload_report(self, filename: str, data: bytes) -> dict:
        return self._request("POST", "/api/reports/upload", files={"file": (filename, data, "application/pdf")})

    def job(self, job_id: str) -> dict:
        return self._request("GET", f"/api/reports/jobs/{job_id}")

    def jobs(self, limit: int = 15) -> list[dict]:
        return self._request("GET", "/api/reports/jobs", params={"limit": limit})

    def approve(self, job_id: str, payload: dict) -> dict:
        return self._request("POST", f"/api/reports/jobs/{job_id}/approve", json=payload)

    def reject(self, job_id: str, reason: str | None) -> dict:
        return self._request("POST", f"/api/reports/jobs/{job_id}/reject", json={"reason": reason})

    # -- assistant & documents ---------------------------------------------------------------
    def ask(self, question: str) -> dict:
        return self._request("POST", "/api/assistant/ask", json={"question": question})

    def documents(self) -> list[dict]:
        return self._request("GET", "/api/documents")

    def upload_document(self, filename: str, data: bytes) -> dict:
        return self._request("POST", "/api/documents", files={"file": (filename, data, "application/pdf")})

    def delete_document(self, document_id: int) -> None:
        self._request("DELETE", f"/api/documents/{document_id}")

    def reindex_document(self, document_id: int) -> dict:
        return self._request("POST", f"/api/documents/{document_id}/reindex")

    def search_documents(self, query: str, top_k: int = 5) -> dict:
        return self._request("GET", "/api/documents/search", params={"q": query, "top_k": top_k})

    # -- automation ------------------------------------------------------------------------------
    def automation_status(self) -> dict:
        return self._request("GET", "/api/automation/status")

    def retry_notification(self, notification_id: int) -> dict:
        return self._request("POST", f"/api/automation/notifications/{notification_id}/retry")


@st.cache_resource
def get_client() -> ApiClient:
    return ApiClient(os.getenv("BACKEND_URL", "http://localhost:8000"), os.getenv("API_KEY", ""))
