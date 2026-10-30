"""n8n integration: webhook payloads, retries, idempotency and duplicate-notification prevention."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.services.automation_service import post_webhook
from tests.conftest import API_KEY, N8N_TOKEN

N8N_HEADERS = {"X-N8N-Token": N8N_TOKEN}


class FakeN8n:
    """Records outgoing webhook calls; can simulate network failures or HTTP errors."""

    def __init__(self, failures: int = 0, status_code: int = 200) -> None:
        self.calls: list[dict] = []
        self.failures = failures
        self.status_code = status_code

    def __call__(self, url: str, json: dict, headers: dict, timeout: float) -> httpx.Response:
        self.calls.append({"url": url, "json": json, "headers": headers})
        if len(self.calls) <= self.failures:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(self.status_code, json={"received": True}, request=httpx.Request("POST", url))


@pytest.fixture
def n8n(monkeypatch: pytest.MonkeyPatch) -> FakeN8n:
    fake = FakeN8n()
    monkeypatch.setattr(httpx, "post", fake)
    return fake


@pytest.fixture
def live_client(configure, n8n: FakeN8n) -> Iterator[TestClient]:
    """Client with n8n 'configured' (demo mode off) and the fake n8n endpoint."""
    from backend.main import create_app

    configure(
        demo_mode="false",
        n8n_processing_webhook_url="http://n8n.test/webhook/processing",
        n8n_followup_webhook_url="http://n8n.test/webhook/follow-up",
        n8n_webhook_secret="webhook-secret",
        notification_email="responsable@example.com",
        n8n_callback_base_url="http://backend:8000",
    )
    with TestClient(create_app()) as client:
        client.headers.update({"X-API-Key": API_KEY})
        yield client


def _approve(client: TestClient, job_id: str) -> dict:
    job = client.get(f"/api/reports/jobs/{job_id}").json()
    draft = job["draft"]
    payload = {
        "reference": draft["intervention_id"], "date": draft["date"], "building_code": "BAT-A",
        "equipment_code": draft["equipment_id"], "equipment_name": draft["equipment_name"],
        "equipment_category": draft["equipment_category"], "technician": draft["technician"],
        "problem_description": draft["problem_description"], "actions_performed": draft["actions_performed"],
        "status": draft["status"], "follow_up_required": True, "recommendations": draft["recommendations"],
    }
    response = client.post(f"/api/reports/jobs/{job_id}/approve", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_post_webhook_retries_transient_failures(settings, monkeypatch) -> None:
    fake = FakeN8n(failures=2)
    monkeypatch.setattr(httpx, "post", fake)
    result = post_webhook("http://n8n.test/hook", {"a": 1}, settings, "key-1")
    assert result.ok and result.attempts == 3
    assert fake.calls[0]["headers"]["Idempotency-Key"] == "key-1"


def test_post_webhook_does_not_retry_client_errors(settings, monkeypatch) -> None:
    fake = FakeN8n(status_code=404)
    monkeypatch.setattr(httpx, "post", fake)
    result = post_webhook("http://n8n.test/hook", {}, settings, "key-2")
    assert not result.ok and result.attempts == 1 and "404" in (result.error or "")


def test_upload_is_dispatched_to_n8n_and_processed_once(live_client: TestClient, n8n: FakeN8n) -> None:
    created = live_client.post("/api/reports/samples/RI-2026-1041_CTA_vibrations.pdf").json()["job"]
    assert created["status"] == "queued" and created["dispatch_mode"] == "n8n"
    payload = n8n.calls[0]["json"]
    assert n8n.calls[0]["url"] == "http://n8n.test/webhook/processing"
    assert n8n.calls[0]["headers"]["X-Webhook-Secret"] == "webhook-secret"
    assert payload["job_id"] == created["job_id"]
    assert payload["process_url"] == f"http://backend:8000/api/automation/jobs/{created['job_id']}/process"

    process_url = f"/api/automation/jobs/{created['job_id']}/process"
    assert live_client.post(process_url).status_code == 401  # API key is not enough: n8n token required
    assert live_client.post(process_url, headers=N8N_HEADERS).json()["status"] == "awaiting_review"
    # n8n retry: the job is not processed a second time
    assert live_client.post(process_url, headers=N8N_HEADERS).json()["status"] == "awaiting_review"
    job = live_client.get(f"/api/reports/jobs/{created['job_id']}").json()
    assert job["attempts"] == 1
    assert "IA générative non configurée" in job["ai_engine_note"]
    assert live_client.get("/api/automation/status").json()["metrics"]["duplicates_prevented"] >= 1


def test_unreachable_n8n_falls_back_to_direct_processing(live_client: TestClient, n8n: FakeN8n) -> None:
    n8n.failures = 99
    created = live_client.post("/api/reports/samples/RI-2026-1042_fuite_circuit_chauffage.pdf").json()["job"]
    job = live_client.get(f"/api/reports/jobs/{created['job_id']}").json()
    assert job["status"] == "awaiting_review" and job["dispatch_mode"] == "direct"
    assert len(n8n.calls) == 3  # three attempts before giving up
    status = live_client.get("/api/automation/status").json()
    assert status["metrics"]["webhook_dispatch_failures"] == 1


def test_follow_up_notification_flow_with_duplicate_prevention(live_client: TestClient, n8n: FakeN8n) -> None:
    created = live_client.post("/api/reports/samples/RI-2026-1041_CTA_vibrations.pdf").json()["job"]
    live_client.post(f"/api/automation/jobs/{created['job_id']}/process", headers=N8N_HEADERS)
    approval = _approve(live_client, created["job_id"])

    notification = approval["notification"]
    assert notification["status"] == "dispatched"
    assert notification["idempotency_key"] == "follow-up:RI-2026-1041"
    follow_up_call = n8n.calls[-1]
    assert follow_up_call["url"] == "http://n8n.test/webhook/follow-up"
    assert follow_up_call["json"]["intervention"]["reference"] == "RI-2026-1041"

    claim_url = f"/api/automation/notifications/{notification['public_id']}/claim"
    first = live_client.post(claim_url, headers=N8N_HEADERS).json()
    assert first["should_send"] is True
    assert first["recipient"] == "responsable@example.com"
    assert first["subject"] == "[Maintenance] Intervention nécessitant un suivi"
    assert "Bâtiment : Bâtiment A - Immeuble de bureaux Horizon" in first["body"]
    assert "Merci de consulter le tableau de bord de maintenance" in first["body"]

    second = live_client.post(claim_url, headers=N8N_HEADERS).json()
    assert second["should_send"] is False  # a retried webhook cannot send the email twice

    ack_url = f"/api/automation/notifications/{notification['public_id']}/ack"
    sent = live_client.post(ack_url, json={"status": "sent"}, headers=N8N_HEADERS).json()
    assert sent["status"] == "sent" and sent["sent_at"]
    retry = live_client.post(f"/api/automation/notifications/{notification['id']}/retry")
    assert retry.status_code == 409

    metrics = live_client.get("/api/automation/status").json()["metrics"]
    assert metrics["notifications_sent"] == 1
    assert metrics["duplicates_prevented"] >= 2


def test_failed_email_can_be_retried(live_client: TestClient, n8n: FakeN8n) -> None:
    created = live_client.post("/api/reports/samples/RI-2026-1041_CTA_vibrations.pdf").json()["job"]
    live_client.post(f"/api/automation/jobs/{created['job_id']}/process", headers=N8N_HEADERS)
    notification = _approve(live_client, created["job_id"])["notification"]
    live_client.post(f"/api/automation/notifications/{notification['public_id']}/claim", headers=N8N_HEADERS)
    failed = live_client.post(
        f"/api/automation/notifications/{notification['public_id']}/ack",
        json={"status": "failed", "error": "SMTP auth failed"},
        headers=N8N_HEADERS,
    ).json()
    assert failed["status"] == "failed" and failed["last_error"] == "SMTP auth failed"
    retried = live_client.post(f"/api/automation/notifications/{notification['id']}/retry").json()
    assert retried["status"] == "dispatched" and retried["attempts"] == 2


def test_missing_configuration_never_claims_an_email_was_sent(configure, n8n: FakeN8n) -> None:
    from backend.main import create_app

    configure(demo_mode="false")  # no n8n URL, no recipient
    with TestClient(create_app()) as client:
        client.headers.update({"X-API-Key": API_KEY})
        created = client.post("/api/reports/samples/RI-2026-1041_CTA_vibrations.pdf").json()["job"]
        notification = _approve(client, created["job_id"])["notification"]
    assert notification["status"] == "not_configured"
    assert n8n.calls == []


def test_n8n_token_does_not_grant_access_to_business_data(live_client: TestClient) -> None:
    response = live_client.get("/api/interventions", headers={"X-API-Key": "", **N8N_HEADERS})
    assert response.status_code == 401
