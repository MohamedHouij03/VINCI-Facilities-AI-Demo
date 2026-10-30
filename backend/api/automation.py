"""Automation endpoints: workflow status (frontend) and n8n callbacks (token-protected)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.api.deps import require_api_key, require_n8n_token, settings_dependency
from backend.config import Settings
from backend.database import get_db
from backend.schemas.automation import (
    AutomationEventRead,
    AutomationStatus,
    ClaimResponse,
    IntegrationStatus,
    JobFailureReport,
    NotificationAck,
    NotificationRead,
)
from backend.services import automation_service, report_service
from backend.services.pdf_service import ocr_available
from backend.services.rag_service import get_rag_service

status_router = APIRouter(prefix="/api/automation", tags=["automation"], dependencies=[Depends(require_api_key)])
n8n_router = APIRouter(prefix="/api/automation", tags=["n8n callbacks"], dependencies=[Depends(require_n8n_token)])


def _integrations(settings: Settings) -> list[IntegrationStatus]:
    def n8n_state(url: str) -> IntegrationStatus:
        if settings.demo_mode:
            return IntegrationStatus(name="", state="demo", detail="Mode démo : n8n désactivé, comportement simulé.")
        if url and settings.n8n_webhook_secret:
            return IntegrationStatus(name="", state="active", detail=url)
        return IntegrationStatus(name="", state="not_configured", detail="URL de webhook ou secret manquant.")

    provider = {"gemini": "Google Gemini", "mistral": "Mistral AI"}[settings.llm_provider]
    if settings.ai_enabled:
        llm = IntegrationStatus(name="IA générative", state="active", detail=f"{provider} · {settings.llm_model}")
    elif settings.demo_mode:
        llm = IntegrationStatus(name="IA générative", state="demo",
                                detail=f"Mode démo : extraction par règles, aucune requête vers {provider}.")
    else:
        llm = IntegrationStatus(name="IA générative", state="not_configured",
                                detail=f"{settings.llm_provider.upper()}_API_KEY manquante ({provider}).")

    processing = n8n_state(settings.n8n_processing_webhook_url).model_copy(update={"name": "n8n - traitement des rapports"})
    follow_up = n8n_state(settings.n8n_followup_webhook_url).model_copy(update={"name": "n8n - notifications de suivi"})
    if follow_up.state == "active" and not settings.notification_email:
        follow_up = follow_up.model_copy(update={"state": "not_configured", "detail": "NOTIFICATION_EMAIL manquant."})

    state, model = get_rag_service().embedder_status
    embedding_states = {
        "loaded": ("active", f"Sentence Transformers : {model}"),
        "not_loaded": ("active", f"Sentence Transformers : {model} (chargé à la première requête)"),
        "hashing": ("fallback", "Embeddings lexicaux (hashing) configurés"),
        "fallback": ("fallback", f"{settings.embedding_model} indisponible : embeddings lexicaux de secours"),
        "injected": ("active", model),
    }
    embedding_state, embedding_detail = embedding_states[state]
    ocr = (
        IntegrationStatus(name="OCR Tesseract", state="active", detail=f"Langue : {settings.ocr_language}")
        if ocr_available(settings)
        else IntegrationStatus(name="OCR Tesseract", state="unavailable", detail="Données tessdata introuvables.")
    )
    return [
        llm,
        processing,
        follow_up,
        IntegrationStatus(name="Embeddings (RAG)", state=embedding_state, detail=embedding_detail),  # type: ignore[arg-type]
        ocr,
    ]


@status_router.get("/status", response_model=AutomationStatus)
def automation_status(db: Session = Depends(get_db), settings: Settings = Depends(settings_dependency)):
    return AutomationStatus(
        demo_mode=settings.demo_mode,
        integrations=_integrations(settings),
        metrics=automation_service.automation_metrics(db),
        recent_events=[AutomationEventRead.model_validate(e) for e in automation_service.recent_events(db)],
        notifications=[NotificationRead.model_validate(n) for n in automation_service.list_notifications(db)],
    )


@status_router.post("/notifications/{notification_id}/retry", response_model=NotificationRead)
def retry_notification(
    notification_id: int, db: Session = Depends(get_db), settings: Settings = Depends(settings_dependency)
):
    return automation_service.retry_notification(db, notification_id, settings)


# ---- n8n callbacks -------------------------------------------------------------------


@n8n_router.post("/jobs/{job_id}/process")
def process_job_callback(job_id: str, settings: Settings = Depends(settings_dependency)):
    """Called by n8n. Idempotent: repeated calls do not re-process an already processed job."""
    status = report_service.process_job(job_id, settings, trigger="n8n")
    return {"job_id": job_id, "status": status}


@n8n_router.post("/jobs/{job_id}/failed")
def job_failed_callback(job_id: str, report: JobFailureReport, db: Session = Depends(get_db)):
    job = report_service.report_job_failure(db, job_id, report.error)
    return {"job_id": job_id, "status": job.status}


@n8n_router.post("/notifications/{notification_id}/claim", response_model=ClaimResponse)
def claim_notification(notification_id: str, db: Session = Depends(get_db)):
    return automation_service.claim_notification(db, notification_id)


@n8n_router.post("/notifications/{notification_id}/ack", response_model=NotificationRead)
def acknowledge_notification(notification_id: str, ack: NotificationAck, db: Session = Depends(get_db)):
    return automation_service.acknowledge_notification(db, notification_id, ack)
