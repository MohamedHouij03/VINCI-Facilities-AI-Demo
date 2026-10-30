from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from sqlalchemy.orm import Session

from backend.api.deps import require_api_key, settings_dependency
from backend.config import Settings
from backend.database import get_db
from backend.models import ProcessingJob
from backend.schemas.interventions import InterventionApproval
from backend.schemas.jobs import ApprovalResponse, JobRead, RejectRequest, SampleReport, UploadResponse
from backend.services import intervention_service, report_service
from backend.services.errors import InvalidInputError
from backend.schemas.automation import NotificationRead

router = APIRouter(prefix="/api/reports", tags=["reports"], dependencies=[Depends(require_api_key)])


def _start(db: Session, job: ProcessingJob, background: BackgroundTasks, settings: Settings) -> None:
    if report_service.start_processing(db, job, settings):
        background.add_task(report_service.process_job, job.public_id, settings, "direct")


@router.get("/samples", response_model=list[SampleReport])
def list_samples(settings: Settings = Depends(settings_dependency)):
    return report_service.list_sample_reports(settings)


@router.post("/samples/{name}", response_model=UploadResponse, status_code=201)
def submit_sample(
    name: str,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
):
    data = report_service.read_sample_report(settings, name)
    job, warning = report_service.create_job(db, data, name, "sample", settings)
    _start(db, job, background, settings)
    return UploadResponse(job=report_service.job_to_read(db, job, settings), duplicate_warning=warning)


@router.post("/upload", response_model=UploadResponse, status_code=201)
async def upload_report(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
):
    if file.content_type not in ("application/pdf", "application/x-pdf", "application/octet-stream"):
        raise InvalidInputError("Seuls les fichiers PDF sont acceptés.")
    data = await file.read(settings.max_upload_bytes + 1)  # bounded read
    job, warning = report_service.create_job(db, data, file.filename, "upload", settings)
    _start(db, job, background, settings)
    return UploadResponse(job=report_service.job_to_read(db, job, settings), duplicate_warning=warning)


@router.get("/jobs", response_model=list[JobRead])
def list_jobs(limit: int = 30, db: Session = Depends(get_db), settings: Settings = Depends(settings_dependency)):
    return [report_service.job_to_read(db, job, settings, include_text=False) for job in report_service.list_jobs(db, limit)]


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: str, db: Session = Depends(get_db), settings: Settings = Depends(settings_dependency)):
    return report_service.job_to_read(db, report_service.get_job(db, job_id), settings)


@router.post("/jobs/{job_id}/approve", response_model=ApprovalResponse)
def approve_job(
    job_id: str,
    approval: InterventionApproval,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
):
    intervention, changed, notification = report_service.approve_job(db, job_id, approval, settings)
    return ApprovalResponse(
        intervention=intervention_service.to_read(intervention),
        corrected_fields=changed,
        notification=NotificationRead.model_validate(notification) if notification else None,
    )


@router.post("/jobs/{job_id}/reject", response_model=JobRead)
def reject_job(
    job_id: str,
    request: RejectRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
):
    return report_service.job_to_read(db, report_service.reject_job(db, job_id, request.reason), settings)
