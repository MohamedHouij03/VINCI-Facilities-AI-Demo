"""n8n integration: outgoing webhooks, follow-up notifications, idempotency and the automation event log."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.domain import STATUS_LABELS, JobStatus, NotificationStatus
from backend.models import AutomationEvent, Intervention, Notification, ProcessingJob, utcnow
from backend.schemas.automation import ClaimResponse, NotificationAck
from backend.services.errors import ConflictError, NotFoundError

logger = logging.getLogger(__name__)

DUPLICATE_EVENT_TYPES = (
    "duplicate_processing_prevented",
    "duplicate_notification_prevented",
    "duplicate_upload_detected",
    "duplicate_intervention_rejected",
)
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
_STALE_SENDING_AFTER = timedelta(minutes=10)


def record_event(
    db: Session,
    event_type: str,
    message: str,
    *,
    level: str = "info",
    job_id: int | None = None,
    notification_id: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Append an event (committed by the caller's transaction) and mirror it to the structured log."""
    db.add(
        AutomationEvent(
            event_type=event_type,
            level=level,
            message=message,
            job_id=job_id,
            notification_id=notification_id,
            details=details,
        )
    )
    log = logger.warning if level in ("warning", "error") else logger.info
    log(message, extra={"event_type": event_type, "job_id": job_id, "notification_id": notification_id})


# --------------------------------------------------------------------------------------
# Outgoing webhooks
# --------------------------------------------------------------------------------------


@dataclass
class WebhookResult:
    ok: bool
    attempts: int
    status_code: int | None = None
    error: str | None = None


def post_webhook(url: str, payload: dict[str, Any], settings: Settings, idempotency_key: str) -> WebhookResult:
    """POST to an n8n webhook with retries (exponential backoff) on network errors and 5xx/429."""
    headers = {"X-Webhook-Secret": settings.n8n_webhook_secret, "Idempotency-Key": idempotency_key}
    last_error: str | None = None
    status_code: int | None = None
    for attempt in range(1, settings.webhook_max_attempts + 1):
        try:
            response = httpx.post(url, json=payload, headers=headers, timeout=settings.webhook_timeout_seconds)
            status_code = response.status_code
            if response.is_success:
                return WebhookResult(ok=True, attempts=attempt, status_code=status_code)
            last_error = f"HTTP {status_code}: {response.text[:200]}"
            if status_code not in _RETRYABLE_STATUS:
                return WebhookResult(ok=False, attempts=attempt, status_code=status_code, error=last_error)
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < settings.webhook_max_attempts:
            time.sleep(settings.webhook_backoff_seconds * 2 ** (attempt - 1))
    return WebhookResult(ok=False, attempts=settings.webhook_max_attempts, status_code=status_code, error=last_error)


def dispatch_processing_job(db: Session, job: ProcessingJob, settings: Settings) -> bool:
    """Hand a new job to n8n. The job is marked 'queued' *before* the call so a fast callback cannot race us."""
    job.status = JobStatus.QUEUED
    job.dispatch_mode = "n8n"
    db.commit()
    base = settings.n8n_callback_base_url.rstrip("/")
    payload = {
        "event": "report.uploaded",
        "job_id": job.public_id,
        "filename": job.original_filename,
        "process_url": f"{base}/api/automation/jobs/{job.public_id}/process",
        "failure_url": f"{base}/api/automation/jobs/{job.public_id}/failed",
        "sent_at": utcnow().isoformat(),
    }
    result = post_webhook(settings.n8n_processing_webhook_url, payload, settings, f"job:{job.public_id}")
    if result.ok:
        record_event(db, "processing_dispatched", f"Job transmis à n8n ({job.original_filename}).", job_id=job.id,
                     details={"attempts": result.attempts})
        db.commit()
        return True
    # Revert only if n8n has not already claimed the job in the meantime.
    db.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job.id, ProcessingJob.status == JobStatus.QUEUED)
        .values(status=JobStatus.UPLOADED, dispatch_mode="direct")
    )
    record_event(db, "webhook_dispatch_failed", f"Webhook n8n de traitement injoignable : {result.error}",
                 level="warning", job_id=job.id, details={"attempts": result.attempts})
    db.commit()
    db.refresh(job)
    return False


# --------------------------------------------------------------------------------------
# Follow-up notifications
# --------------------------------------------------------------------------------------


def build_follow_up_message(intervention: Intervention) -> tuple[str, str]:
    subject = "[Maintenance] Intervention nécessitant un suivi"
    body = (
        "Bonjour,\n\n"
        "Une intervention nécessite un suivi.\n\n"
        f"Référence : {intervention.reference}\n\n"
        f"Bâtiment : {intervention.building.name}\n\n"
        f"Équipement : {intervention.equipment.code} - {intervention.equipment.name}\n\n"
        f"Problème : {intervention.problem_description}\n\n"
        f"Date : {intervention.date.strftime('%d/%m/%Y')}\n\n"
        f"Statut : {STATUS_LABELS[intervention.status]}\n\n"
        "Merci de consulter le tableau de bord de maintenance pour plus de détails."
    )
    return subject, body


def request_follow_up_notification(db: Session, intervention: Intervention, settings: Settings) -> Notification:
    """Create (once) and dispatch the follow-up notification for a *validated* intervention."""
    key = f"follow-up:{intervention.reference}"
    existing = db.scalars(select(Notification).where(Notification.idempotency_key == key)).first()
    if existing is not None:
        record_event(db, "duplicate_notification_prevented",
                     f"Notification déjà existante pour {intervention.reference} (statut : {existing.status}).",
                     notification_id=existing.id)
        db.commit()
        return existing
    subject, body = build_follow_up_message(intervention)
    notification = Notification(
        intervention_id=intervention.id,
        idempotency_key=key,
        recipient=settings.notification_email or None,
        subject=subject,
        body=body,
    )
    db.add(notification)
    try:
        db.commit()
    except IntegrityError:  # concurrent request created it first
        db.rollback()
        return db.scalars(select(Notification).where(Notification.idempotency_key == key)).one()
    return dispatch_notification(db, notification, intervention, settings)


def dispatch_notification(
    db: Session, notification: Notification, intervention: Intervention, settings: Settings
) -> Notification:
    if settings.demo_mode:
        notification.status = NotificationStatus.SIMULATED
        record_event(db, "notification_simulated",
                     f"Mode démo : notification de suivi simulée pour {intervention.reference} (aucun e-mail envoyé).",
                     notification_id=notification.id)
        db.commit()
        return notification
    if not settings.n8n_followup_enabled or not notification.recipient:
        notification.status = NotificationStatus.NOT_CONFIGURED
        missing = "N8N_FOLLOWUP_WEBHOOK_URL / N8N_WEBHOOK_SECRET" if not settings.n8n_followup_enabled else "NOTIFICATION_EMAIL"
        notification.last_error = f"Configuration manquante : {missing}"
        record_event(db, "notification_not_configured",
                     f"Notification non envoyée pour {intervention.reference} : configuration manquante ({missing}).",
                     level="warning", notification_id=notification.id)
        db.commit()
        return notification

    base = settings.n8n_callback_base_url.rstrip("/")
    payload = {
        "event": "intervention.follow_up_required",
        "notification_id": notification.public_id,
        "idempotency_key": notification.idempotency_key,
        "claim_url": f"{base}/api/automation/notifications/{notification.public_id}/claim",
        "ack_url": f"{base}/api/automation/notifications/{notification.public_id}/ack",
        "intervention": {
            "reference": intervention.reference,
            "date": intervention.date.isoformat(),
            "building": intervention.building.name,
            "equipment": f"{intervention.equipment.code} - {intervention.equipment.name}",
            "problem": intervention.problem_description,
            "status": STATUS_LABELS[intervention.status],
        },
    }
    notification.attempts += 1
    notification.status = NotificationStatus.PENDING
    db.commit()
    result = post_webhook(settings.n8n_followup_webhook_url, payload, settings, notification.idempotency_key)
    # Conditional updates: n8n may already have claimed the notification while we were waiting.
    still_pending = (Notification.id == notification.id, Notification.status == NotificationStatus.PENDING)
    if result.ok:
        db.execute(
            update(Notification)
            .where(*still_pending)
            .values(status=NotificationStatus.DISPATCHED, dispatched_at=utcnow(), last_error=None)
        )
        record_event(db, "notification_dispatched",
                     f"Notification de suivi transmise à n8n pour {intervention.reference}.",
                     notification_id=notification.id, details={"attempts": result.attempts})
    else:
        db.execute(
            update(Notification).where(*still_pending).values(status=NotificationStatus.FAILED, last_error=result.error)
        )
        record_event(db, "webhook_dispatch_failed",
                     f"Échec de transmission de la notification {intervention.reference} : {result.error}",
                     level="error", notification_id=notification.id)
    db.commit()
    db.refresh(notification)
    return notification


def _get_notification(db: Session, public_id: str) -> Notification:
    notification = db.scalars(select(Notification).where(Notification.public_id == public_id)).first()
    if notification is None:
        raise NotFoundError("Notification introuvable.")
    return notification


def claim_notification(db: Session, public_id: str) -> ClaimResponse:
    """Called by n8n right before sending the email. Only the first claim wins (atomic UPDATE)."""
    notification = _get_notification(db, public_id)
    claimed = db.execute(
        update(Notification)
        .where(
            Notification.id == notification.id,
            Notification.status.in_([NotificationStatus.DISPATCHED, NotificationStatus.PENDING]),
        )
        .values(status=NotificationStatus.SENDING, updated_at=utcnow())
    ).rowcount
    if claimed == 1:
        db.commit()
        return ClaimResponse(
            should_send=True,
            status=NotificationStatus.SENDING,
            recipient=notification.recipient,
            subject=notification.subject,
            body=notification.body,
        )
    db.refresh(notification)
    record_event(db, "duplicate_notification_prevented",
                 f"Envoi en double évité (statut actuel : {notification.status}).", notification_id=notification.id)
    db.commit()
    return ClaimResponse(should_send=False, status=notification.status, reason="already_processed")


def acknowledge_notification(db: Session, public_id: str, ack: NotificationAck) -> Notification:
    notification = _get_notification(db, public_id)
    if notification.status == NotificationStatus.SENT:
        return notification  # idempotent acknowledgement
    if notification.status != NotificationStatus.SENDING:
        raise ConflictError(f"Accusé de réception inattendu (statut : {notification.status}).")
    if ack.status == "sent":
        notification.status = NotificationStatus.SENT
        notification.sent_at = utcnow()
        notification.last_error = None
        record_event(db, "notification_sent", f"E-mail de suivi envoyé par n8n à {notification.recipient}.",
                     notification_id=notification.id)
    else:
        notification.status = NotificationStatus.FAILED
        notification.last_error = ack.error or "Erreur non précisée par n8n"
        record_event(db, "notification_failed", f"n8n signale un échec d'envoi : {notification.last_error}",
                     level="error", notification_id=notification.id)
    db.commit()
    return notification


def retry_notification(db: Session, notification_id: int, settings: Settings) -> Notification:
    notification = db.get(Notification, notification_id)
    if notification is None:
        raise NotFoundError("Notification introuvable.")
    stale_sending = (
        notification.status == NotificationStatus.SENDING
        and notification.updated_at < utcnow() - _STALE_SENDING_AFTER
    )
    if notification.status in (NotificationStatus.SENT, NotificationStatus.DISPATCHED) or (
        notification.status == NotificationStatus.SENDING and not stale_sending
    ):
        record_event(db, "duplicate_notification_prevented",
                     f"Relance refusée : notification déjà {notification.status}.", notification_id=notification.id)
        db.commit()
        raise ConflictError(f"La notification est déjà au statut « {notification.status} » : relance refusée.")
    intervention = db.get(Intervention, notification.intervention_id)
    assert intervention is not None
    notification.status = NotificationStatus.PENDING
    return dispatch_notification(db, notification, intervention, settings)


# --------------------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------------------


def _count_by(db: Session, column) -> dict[str, int]:  # noqa: ANN001
    return {key: count for key, count in db.execute(select(column, func.count()).group_by(column))}


def automation_metrics(db: Session) -> dict[str, Any]:
    jobs_by_status = _count_by(db, ProcessingJob.status)
    notifications_by_status = _count_by(db, Notification.status)
    events_by_type = _count_by(db, AutomationEvent.event_type)
    processed_ok = db.scalar(
        select(func.count()).where(
            ProcessingJob.processed_at.is_not(None),
            ProcessingJob.status.in_([JobStatus.AWAITING_REVIEW, JobStatus.APPROVED, JobStatus.REJECTED]),
        )
    )
    avg_ms = db.scalar(select(func.avg(ProcessingJob.processing_ms)).where(ProcessingJob.processing_ms.is_not(None)))

    reviewed = list(db.scalars(select(ProcessingJob).where(ProcessingJob.status == JobStatus.APPROVED)))
    corrections = [len(job.corrected_fields or []) for job in reviewed]
    return {
        "jobs_total": sum(jobs_by_status.values()),
        "jobs_by_status": jobs_by_status,
        "jobs_processed_successfully": processed_ok or 0,
        "processing_failures": events_by_type.get("processing_failed", 0),
        "average_processing_ms": round(avg_ms) if avg_ms else None,
        "notifications_by_status": notifications_by_status,
        "notifications_sent": notifications_by_status.get(NotificationStatus.SENT, 0),
        "notifications_simulated": notifications_by_status.get(NotificationStatus.SIMULATED, 0),
        "webhook_dispatch_failures": events_by_type.get("webhook_dispatch_failed", 0),
        "duplicates_prevented": sum(events_by_type.get(t, 0) for t in DUPLICATE_EVENT_TYPES),
        "approvals": len(reviewed),
        "rejections": jobs_by_status.get(JobStatus.REJECTED, 0),
        "approvals_with_corrections": sum(1 for c in corrections if c),
        "corrected_fields_total": sum(corrections),
        "field_correction_rate": round(sum(corrections) / (12 * len(reviewed)), 4) if reviewed else None,
    }


def recent_events(db: Session, limit: int = 50) -> list[AutomationEvent]:
    return list(db.scalars(select(AutomationEvent).order_by(AutomationEvent.id.desc()).limit(limit)))


def list_notifications(db: Session, limit: int = 50) -> list[Notification]:
    return list(db.scalars(select(Notification).order_by(Notification.id.desc()).limit(limit)))
