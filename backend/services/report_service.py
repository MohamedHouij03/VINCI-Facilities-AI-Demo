"""Maintenance-report workflow: upload -> processing job -> AI draft -> human review -> intervention."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.database import session_scope
from backend.domain import CLAIMABLE_JOB_STATUSES, STATUS_LABELS, JobStatus, simplify
from backend.models import Building, Equipment, Intervention, ProcessingJob, utcnow
from backend.schemas.extraction import ExtractionResult
from backend.schemas.interventions import InterventionApproval
from backend.schemas.jobs import EquipmentHistoryItem, JobRead, ReviewContext, SampleReport
from backend.services import automation_service, intervention_service
from backend.services.analytics_service import max_events_in_window
from backend.services.errors import ConflictError, InvalidInputError, NotFoundError
from backend.services.extraction_service import grounding_report, run_extraction
from backend.services.gemini_service import get_llm_client
from backend.services.pdf_service import PdfValidationError, extract_pdf_text, validate_pdf_bytes
from backend.services.storage import read_stored_pdf, safe_display_filename, sha256_bytes, store_pdf
from backend.services.summary_service import SummaryInput, generate_summary

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------------------
# Sample reports
# --------------------------------------------------------------------------------------


def _reports_dir(settings: Settings) -> Path:
    return settings.sample_data_dir / "reports"


def list_sample_reports(settings: Settings) -> list[SampleReport]:
    catalog_path = _reports_dir(settings) / "catalog.json"
    if not catalog_path.is_file():
        return []
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    reports = []
    for entry in catalog:
        path = _reports_dir(settings) / entry["file"]
        if path.is_file():
            reports.append(
                SampleReport(
                    name=entry["file"],
                    title=entry["title"],
                    size_kb=round(path.stat().st_size / 1024, 1),
                    layout=entry["layout"],
                )
            )
    return reports


def read_sample_report(settings: Settings, name: str) -> bytes:
    allowed = {report.name for report in list_sample_reports(settings)}
    if name not in allowed:  # whitelist: no path built from user input
        raise NotFoundError("Rapport d'exemple introuvable.")
    return (_reports_dir(settings) / name).read_bytes()


# --------------------------------------------------------------------------------------
# Job creation and processing
# --------------------------------------------------------------------------------------


def get_job(db: Session, public_id: str) -> ProcessingJob:
    job = db.scalars(select(ProcessingJob).where(ProcessingJob.public_id == public_id)).first()
    if job is None:
        raise NotFoundError("Traitement introuvable.")
    return job


def create_job(
    db: Session, data: bytes, filename: str | None, source: str, settings: Settings
) -> tuple[ProcessingJob, str | None]:
    try:
        validate_pdf_bytes(data, settings.max_upload_bytes)
    except PdfValidationError as exc:
        raise InvalidInputError(str(exc)) from exc

    digest = sha256_bytes(data)
    warning = None
    previous = db.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.file_sha256 == digest, ProcessingJob.status.in_([JobStatus.APPROVED, JobStatus.AWAITING_REVIEW]))
        .order_by(ProcessingJob.id.desc())
    ).first()
    if previous is not None:
        warning = (
            "Ce document a déjà été validé : l'enregistrement d'un doublon sera refusé."
            if previous.status == JobStatus.APPROVED
            else "Ce document est déjà en attente de vérification dans un autre traitement."
        )

    job = ProcessingJob(
        original_filename=safe_display_filename(filename),
        stored_filename=store_pdf(settings.uploads_dir, data),
        file_sha256=digest,
        file_size=len(data),
        source=source,
        status=JobStatus.UPLOADED,
    )
    db.add(job)
    db.flush()
    automation_service.record_event(db, "job_created", f"Rapport reçu : {job.original_filename}.", job_id=job.id)
    if warning:
        automation_service.record_event(db, "duplicate_upload_detected", warning, level="warning", job_id=job.id)
    db.commit()
    return job, warning


def start_processing(db: Session, job: ProcessingJob, settings: Settings) -> bool:
    """Dispatch to n8n when configured. Returns True if the caller must process the job directly."""
    if settings.n8n_processing_enabled and automation_service.dispatch_processing_job(db, job, settings):
        return False
    job.dispatch_mode = "direct"
    db.commit()
    return True


def _claim_job(db: Session, job_id: int) -> bool:
    claimed = db.execute(
        update(ProcessingJob)
        .where(ProcessingJob.id == job_id, ProcessingJob.status.in_(list(CLAIMABLE_JOB_STATUSES)))
        .values(status=JobStatus.PROCESSING, attempts=ProcessingJob.attempts + 1, updated_at=utcnow())
    ).rowcount
    db.commit()
    return claimed == 1


def process_job(public_id: str, settings: Settings, trigger: str = "direct") -> str:
    """Run text extraction + AI extraction for a job. Idempotent: a job is processed only once.

    Opens its own session because it runs in a background task or an n8n callback.
    Returns the resulting job status.
    """
    with session_scope() as db:
        job = get_job(db, public_id)
        if not _claim_job(db, job.id):
            db.refresh(job)
            automation_service.record_event(db, "duplicate_processing_prevented",
                                            f"Demande de traitement ignorée ({trigger}) : job déjà au statut {job.status}.",
                                            job_id=job.id)
            return job.status
        db.refresh(job)
        started = time.perf_counter()
        try:
            data = read_stored_pdf(settings.uploads_dir, job.stored_filename)
            pdf = extract_pdf_text(data, settings)
            job.page_count = pdf.page_count
            job.extraction_method = pdf.method
            job.extracted_text = pdf.text_with_page_markers
            if not pdf.text.strip():
                hint = " (OCR indisponible : installez les données Tesseract « fra »)" if pdf.ocr_unavailable_pages else ""
                raise PdfValidationError(f"Aucun texte exploitable n'a été trouvé dans le document{hint}.")

            client = get_llm_client(settings)
            outcome = run_extraction(pdf.text, client, settings)
            notes = [outcome.note] if outcome.note else []
            if pdf.ocr_unavailable_pages:
                notes.append(f"OCR indisponible pour les pages {pdf.ocr_unavailable_pages}.")
            summary, summary_engine = generate_summary(
                SummaryInput.from_extraction(outcome.result),
                client,
                outcome.suggestions,
                outcome.result.missing_fields(),
            )
            job.ai_engine = outcome.engine
            job.ai_engine_note = " ".join(notes) or None
            job.draft = outcome.result.model_dump(mode="json")
            job.ai_suggestions = outcome.suggestions
            job.grounding = grounding_report(outcome.result, pdf.text)
            job.draft_summary = summary
            job.status = JobStatus.AWAITING_REVIEW
            job.error_message = None
            job.processed_at = utcnow()
            job.processing_ms = round((time.perf_counter() - started) * 1000)
            automation_service.record_event(db, "processing_succeeded",
                                            f"Extraction terminée ({outcome.engine}, résumé : {summary_engine}) "
                                            f"en {job.processing_ms} ms, en attente de vérification.",
                                            job_id=job.id)
        except Exception as exc:
            message = str(exc) if isinstance(exc, PdfValidationError) else f"Erreur de traitement : {exc}"
            logger.exception("job processing failed", extra={"job": public_id})
            job.status = JobStatus.FAILED
            job.error_message = message
            job.processing_ms = round((time.perf_counter() - started) * 1000)
            automation_service.record_event(db, "processing_failed", message, level="error", job_id=job.id)
        return job.status


def report_job_failure(db: Session, public_id: str, error: str) -> ProcessingJob:
    """n8n reports that it could not complete the processing call (after its own retries)."""
    job = get_job(db, public_id)
    if job.status in (JobStatus.QUEUED, JobStatus.PROCESSING, JobStatus.UPLOADED):
        job.status = JobStatus.FAILED
        job.error_message = f"Échec signalé par n8n : {error}"
    automation_service.record_event(db, "processing_failed", f"n8n signale un échec : {error}", level="error",
                                    job_id=job.id)
    db.commit()
    return job


# --------------------------------------------------------------------------------------
# Review
# --------------------------------------------------------------------------------------


def build_review_context(db: Session, draft: ExtractionResult, settings: Settings) -> ReviewContext:
    context = ReviewContext()
    building = intervention_service.resolve_building(db, draft.building)
    equipment = intervention_service.find_equipment(db, draft.equipment_id)
    if equipment is not None:
        context.matched_equipment = {
            "code": equipment.code,
            "name": equipment.name,
            "category": equipment.category,
            "building_code": equipment.building.code,
            "building_name": equipment.building.name,
        }
        building = building or equipment.building
        history = list(
            db.scalars(
                select(Intervention)
                .where(Intervention.equipment_id == equipment.id)
                .order_by(Intervention.date.desc())
            )
        )
        context.equipment_history = [
            EquipmentHistoryItem(
                reference=item.reference,
                date=item.date,
                problem_description=item.problem_description,
                status_label=STATUS_LABELS[item.status],
            )
            for item in history[:8]
        ]
        dates = sorted([item.date for item in history] + ([draft.date] if draft.date else []))
        count, _, _ = max_events_in_window(dates, settings.recurrence_window_days)
        context.equipment_recurring = count >= settings.recurrence_threshold
    context.resolved_building_code = building.code if building else None
    if draft.intervention_id:
        context.duplicate_reference = intervention_service.get_by_reference(db, draft.intervention_id) is not None
    return context


def job_to_read(db: Session, job: ProcessingJob, settings: Settings, include_text: bool = True) -> JobRead:
    draft = ExtractionResult.model_validate(job.draft) if job.draft else None
    context = None
    if draft is not None and job.status == JobStatus.AWAITING_REVIEW:
        context = build_review_context(db, draft, settings)
    return JobRead(
        job_id=job.public_id,
        original_filename=job.original_filename,
        source=job.source,
        status=job.status,
        dispatch_mode=job.dispatch_mode,
        attempts=job.attempts,
        page_count=job.page_count,
        extraction_method=job.extraction_method,
        extracted_text=job.extracted_text if include_text else None,
        ai_engine=job.ai_engine,
        ai_engine_note=job.ai_engine_note,
        draft=draft,
        missing_fields=draft.missing_fields() if draft else [],
        ai_suggestions=job.ai_suggestions or [],
        grounding=job.grounding,
        draft_summary=job.draft_summary,
        processing_ms=job.processing_ms,
        error_message=job.error_message,
        corrected_fields=job.corrected_fields,
        rejection_reason=job.rejection_reason,
        intervention_id=job.intervention_id,
        created_at=job.created_at,
        processed_at=job.processed_at,
        reviewed_at=job.reviewed_at,
        review_context=context,
    )


def _normalized(value: object) -> str:
    return simplify(str(value)) if value is not None else ""


def corrected_fields(draft: ExtractionResult, approval: InterventionApproval, draft_building_code: str | None) -> list[str]:
    """Which extracted fields the reviewer had to change (used for the human-correction-rate metric)."""
    pairs = {
        "intervention_id": (draft.intervention_id, approval.reference),
        "date": (draft.date, approval.date),
        "building": (draft_building_code, approval.building_code),
        "equipment_id": (draft.equipment_id, approval.equipment_code),
        "equipment_name": (draft.equipment_name, approval.equipment_name),
        "equipment_category": (draft.equipment_category, approval.equipment_category),
        "technician": (draft.technician, approval.technician),
        "problem_description": (draft.problem_description, approval.problem_description),
        "actions_performed": (draft.actions_performed, approval.actions_performed),
        "status": (draft.status, approval.status),
        "follow_up_required": (draft.follow_up_required, approval.follow_up_required),
        "recommendations": (draft.recommendations, approval.recommendations),
    }
    return [name for name, (before, after) in pairs.items() if _normalized(before) != _normalized(after)]


def _resolve_equipment(db: Session, approval: InterventionApproval, building: Building) -> Equipment:
    equipment = intervention_service.find_equipment(db, approval.equipment_code)
    if equipment is None:
        equipment = Equipment(
            code=approval.equipment_code,
            name=approval.equipment_name,
            category=approval.equipment_category,
            building_id=building.id,
        )
        db.add(equipment)
        db.flush()
        return equipment
    if equipment.building_id != building.id:
        raise InvalidInputError(
            f"L'équipement {equipment.code} est rattaché au bâtiment {equipment.building.code}, "
            f"pas au bâtiment {building.code}."
        )
    return equipment


def approve_job(db: Session, public_id: str, approval: InterventionApproval, settings: Settings):
    """Persist a human-validated intervention, then trigger the follow-up workflow if required."""
    job = get_job(db, public_id)
    if job.status == JobStatus.APPROVED:
        raise ConflictError("Ce rapport a déjà été validé.", intervention_id=job.intervention_id)
    if job.status != JobStatus.AWAITING_REVIEW:
        raise ConflictError(f"Ce traitement n'est pas en attente de vérification (statut : {job.status}).")

    existing = intervention_service.get_by_reference(db, approval.reference)
    if existing is not None:
        automation_service.record_event(db, "duplicate_intervention_rejected",
                                        f"Intervention {approval.reference} déjà enregistrée : doublon refusé.",
                                        level="warning", job_id=job.id)
        db.commit()
        raise ConflictError(
            f"L'intervention {approval.reference} existe déjà dans la base (doublon).", intervention_id=existing.id
        )

    building = db.scalars(select(Building).where(Building.code == approval.building_code)).first()
    if building is None:
        raise InvalidInputError(f"Bâtiment inconnu : {approval.building_code}.")
    equipment = _resolve_equipment(db, approval, building)

    draft = ExtractionResult.model_validate(job.draft or {})
    draft_building = intervention_service.resolve_building(db, draft.building)
    changed = corrected_fields(draft, approval, draft_building.code if draft_building else None)

    summary_input = SummaryInput(
        reference=approval.reference,
        date=approval.date,
        building=building.name,
        equipment_code=equipment.code,
        equipment_name=equipment.name,
        technician=approval.technician,
        problem_description=approval.problem_description,
        actions_performed=approval.actions_performed,
        status=approval.status,
        follow_up_required=approval.follow_up_required,
        recommendations=approval.recommendations,
    )
    if changed or not job.draft_summary:
        summary, _ = generate_summary(summary_input, get_llm_client(settings), job.ai_suggestions)
    else:
        summary = job.draft_summary

    intervention = Intervention(
        reference=approval.reference,
        date=approval.date,
        building_id=building.id,
        equipment_id=equipment.id,
        technician=approval.technician,
        problem_description=approval.problem_description,
        actions_performed=approval.actions_performed,
        status=approval.status.value,
        follow_up_required=approval.follow_up_required,
        recommendations=approval.recommendations,
        summary=summary,
        source="report",
        source_job_id=job.id,
    )
    db.add(intervention)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(f"L'intervention {approval.reference} existe déjà (doublon).") from exc

    job.status = JobStatus.APPROVED
    job.intervention_id = intervention.id
    job.corrected_fields = changed
    job.reviewed_at = utcnow()
    automation_service.record_event(db, "intervention_approved",
                                    f"Intervention {intervention.reference} validée et enregistrée "
                                    f"({len(changed)} champ(s) corrigé(s)).",
                                    job_id=job.id)
    db.commit()
    intervention = intervention_service.get_intervention(db, intervention.id)

    notification = None
    if intervention.follow_up_required:
        notification = automation_service.request_follow_up_notification(db, intervention, settings)
    return intervention, changed, notification


def reject_job(db: Session, public_id: str, reason: str | None) -> ProcessingJob:
    job = get_job(db, public_id)
    if job.status != JobStatus.AWAITING_REVIEW:
        raise ConflictError(f"Seul un traitement en attente de vérification peut être rejeté (statut : {job.status}).")
    job.status = JobStatus.REJECTED
    job.rejection_reason = reason
    job.reviewed_at = utcnow()
    automation_service.record_event(db, "extraction_rejected", f"Extraction rejetée : {reason or 'sans motif'}.",
                                    job_id=job.id)
    db.commit()
    return job


def list_jobs(db: Session, limit: int = 30) -> list[ProcessingJob]:
    return list(db.scalars(select(ProcessingJob).order_by(ProcessingJob.id.desc()).limit(limit)))
