"""End-to-end API tests of the core workflow: upload -> extraction -> human review -> database -> dashboard."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.conftest import sample_report

SAMPLE = "RI-2026-1041_CTA_vibrations.pdf"


def _submit_sample(client: TestClient, name: str = SAMPLE) -> dict:
    response = client.post(f"/api/reports/samples/{name}")
    assert response.status_code == 201, response.text
    job_id = response.json()["job"]["job_id"]
    # TestClient runs background tasks before returning, so processing is already finished.
    job = client.get(f"/api/reports/jobs/{job_id}").json()
    assert job["status"] == "awaiting_review", job
    return job


def _approval_from(job: dict, **changes: object) -> dict:
    draft = job["draft"]
    payload = {
        "reference": draft["intervention_id"],
        "date": draft["date"],
        "building_code": job["review_context"]["resolved_building_code"],
        "equipment_code": draft["equipment_id"],
        "equipment_name": draft["equipment_name"],
        "equipment_category": draft["equipment_category"],
        "technician": draft["technician"],
        "problem_description": draft["problem_description"],
        "actions_performed": draft["actions_performed"],
        "status": draft["status"],
        "follow_up_required": draft["follow_up_required"],
        "recommendations": draft["recommendations"],
    }
    payload.update(changes)
    return payload


def test_api_requires_the_api_key(client: TestClient) -> None:
    assert client.get("/api/interventions", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/interventions", headers={"X-API-Key": ""}).status_code == 401
    assert client.get("/health").status_code == 200


def test_sample_report_is_extracted_into_a_draft_with_review_context(client: TestClient) -> None:
    job = _submit_sample(client)
    assert job["ai_engine"] == "rules"
    assert job["extraction_method"] == "text"
    assert job["draft"]["intervention_id"] == "RI-2026-1041"
    assert job["draft"]["equipment_id"] == "CTA-A01"
    assert job["grounding"]["intervention_id"] == "found"
    assert "--- Page 1 ---" in job["extracted_text"]
    assert "**Faits documentés**" in job["draft_summary"]
    context = job["review_context"]
    assert context["resolved_building_code"] == "BAT-A"
    assert context["matched_equipment"]["code"] == "CTA-A01"
    assert context["equipment_recurring"] is True  # three vibration interventions in October already
    assert context["duplicate_reference"] is False


def test_draft_is_not_an_intervention_until_approved(client: TestClient) -> None:
    before = client.get("/api/interventions").json()["total"]
    _submit_sample(client)
    assert client.get("/api/interventions").json()["total"] == before


def test_approval_saves_intervention_updates_dashboard_and_records_corrections(client: TestClient) -> None:
    dashboard_before = client.get("/api/analytics/dashboard").json()["kpis"]
    job = _submit_sample(client)

    approval = _approval_from(job, technician="Julien MOREAU (corrigé)")
    response = client.post(f"/api/reports/jobs/{job['job_id']}/approve", json=approval)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["intervention"]["reference"] == "RI-2026-1041"
    assert body["intervention"]["source"] == "report"
    assert body["corrected_fields"] == ["technician"]
    assert body["notification"]["status"] == "simulated"  # demo mode: no email is sent

    dashboard_after = client.get("/api/analytics/dashboard").json()["kpis"]
    assert dashboard_after["total"] == dashboard_before["total"] + 1
    assert dashboard_after["pending"] == dashboard_before["pending"] + 1
    assert dashboard_after["follow_up_open"] == dashboard_before["follow_up_open"] + 1

    search = client.get("/api/interventions", params={"search": "RI-2026-1041"}).json()
    assert search["total"] == 1 and search["items"][0]["summary"]

    metrics = client.get("/api/automation/status").json()["metrics"]
    assert metrics["approvals"] == 1
    assert metrics["corrected_fields_total"] == 1


def test_same_report_cannot_be_saved_twice(client: TestClient) -> None:
    first = _submit_sample(client)
    assert client.post(f"/api/reports/jobs/{first['job_id']}/approve", json=_approval_from(first)).status_code == 200
    assert client.post(f"/api/reports/jobs/{first['job_id']}/approve", json=_approval_from(first)).status_code == 409

    response = client.post(f"/api/reports/samples/{SAMPLE}")
    assert "déjà été validé" in response.json()["duplicate_warning"]
    second = client.get(f"/api/reports/jobs/{response.json()['job']['job_id']}").json()
    assert second["review_context"]["duplicate_reference"] is True
    conflict = client.post(f"/api/reports/jobs/{second['job_id']}/approve", json=_approval_from(second))
    assert conflict.status_code == 409
    assert "doublon" in conflict.json()["detail"]
    assert client.get("/api/interventions", params={"search": "RI-2026-1041"}).json()["total"] == 1


def test_rejected_extraction_is_not_saved(client: TestClient) -> None:
    job = _submit_sample(client)
    response = client.post(f"/api/reports/jobs/{job['job_id']}/reject", json={"reason": "Mauvais document"})
    assert response.json()["status"] == "rejected"
    assert client.post(f"/api/reports/jobs/{job['job_id']}/approve", json=_approval_from(job)).status_code == 409


def test_approval_payload_is_validated(client: TestClient) -> None:
    job = _submit_sample(client)
    bad_category = client.post(f"/api/reports/jobs/{job['job_id']}/approve", json=_approval_from(job, equipment_category="Jardinage"))
    assert bad_category.status_code == 422
    future = client.post(f"/api/reports/jobs/{job['job_id']}/approve", json=_approval_from(job, date="2099-01-01"))
    assert future.status_code == 422
    wrong_building = client.post(f"/api/reports/jobs/{job['job_id']}/approve", json=_approval_from(job, building_code="BAT-B"))
    assert wrong_building.status_code == 422
    assert "rattaché au bâtiment BAT-A" in wrong_building.json()["detail"]


def test_upload_rejects_non_pdf_and_accepts_real_pdf(client: TestClient) -> None:
    fake = client.post("/api/reports/upload", files={"file": ("notes.pdf", b"hello", "application/pdf")})
    assert fake.status_code == 422
    wrong_type = client.post("/api/reports/upload", files={"file": ("image.png", b"\x89PNG", "image/png")})
    assert wrong_type.status_code == 422

    data = sample_report("RI-2026-1042").read_bytes()
    response = client.post("/api/reports/upload", files={"file": ("../../rapport.pdf", data, "application/pdf")})
    assert response.status_code == 201
    job = client.get(f"/api/reports/jobs/{response.json()['job']['job_id']}").json()
    assert job["original_filename"] == "rapport.pdf"
    assert job["draft"]["equipment_id"] == "HYD-D01"


def test_new_equipment_is_created_when_unknown(client: TestClient) -> None:
    job = _submit_sample(client, "RI-2026-1042_fuite_circuit_chauffage.pdf")
    approval = _approval_from(job, equipment_code="VAN-D07", equipment_name="Vanne d'isolement départ nord")
    assert client.post(f"/api/reports/jobs/{job['job_id']}/approve", json=approval).status_code == 200
    codes = [e["code"] for e in client.get("/api/equipment", params={"building": "BAT-D"}).json()]
    assert "VAN-D07" in codes


def test_intervention_update_and_follow_up_completion(client: TestClient) -> None:
    item = client.get("/api/interventions", params={"follow_up_open": True}).json()["items"][0]
    done = client.post(f"/api/interventions/{item['id']}/complete-follow-up").json()
    assert done["follow_up_open"] is False and done["follow_up_completed_at"]

    updated = client.patch(f"/api/interventions/{item['id']}", json={"status": "terminee"}).json()
    assert updated["status_label"] == "Terminée"
    assert client.patch(f"/api/interventions/{item['id']}", json={"reference": "X"}).status_code == 422
