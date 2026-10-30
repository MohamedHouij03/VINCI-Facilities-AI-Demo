from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field

from backend.schemas.automation import NotificationRead
from backend.schemas.extraction import ExtractionResult
from backend.schemas.interventions import InterventionRead


class EquipmentHistoryItem(BaseModel):
    reference: str
    date: dt.date
    problem_description: str
    status_label: str


class ReviewContext(BaseModel):
    """Database context shown next to the draft so the reviewer can check it."""

    resolved_building_code: str | None = None
    matched_equipment: dict[str, Any] | None = None
    equipment_history: list[EquipmentHistoryItem] = []
    equipment_recurring: bool = False
    duplicate_reference: bool = False


class JobRead(BaseModel):
    job_id: str
    original_filename: str
    source: str
    status: str
    dispatch_mode: str | None
    attempts: int
    page_count: int | None
    extraction_method: str | None
    extracted_text: str | None = None
    ai_engine: str | None
    ai_engine_note: str | None
    draft: ExtractionResult | None
    missing_fields: list[str] = []
    ai_suggestions: list[str] = []
    grounding: dict[str, Any] | None
    draft_summary: str | None
    processing_ms: int | None
    error_message: str | None
    corrected_fields: list[str] | None
    rejection_reason: str | None
    intervention_id: int | None
    created_at: dt.datetime
    processed_at: dt.datetime | None
    reviewed_at: dt.datetime | None
    review_context: ReviewContext | None = None


class UploadResponse(BaseModel):
    job: JobRead
    duplicate_warning: str | None = None


class SampleReport(BaseModel):
    name: str
    title: str
    size_kb: float
    layout: str


class RejectRequest(BaseModel):
    reason: str | None = Field(None, max_length=500)


class ApprovalResponse(BaseModel):
    intervention: InterventionRead
    corrected_fields: list[str]
    notification: NotificationRead | None
