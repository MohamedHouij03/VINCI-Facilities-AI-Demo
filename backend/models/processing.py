from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.domain import JobStatus
from backend.models.base import Base, TimestampMixin, in_values, new_public_id


class ProcessingJob(TimestampMixin, Base):
    """One uploaded maintenance report going through extraction and human review."""

    __tablename__ = "processing_jobs"
    __table_args__ = (
        CheckConstraint(in_values("status", [s.value for s in JobStatus]), name="ck_job_status"),
        CheckConstraint(in_values("source", ("upload", "sample")), name="ck_job_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, default=new_public_id, nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(String(80), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(10), default="upload", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.UPLOADED, nullable=False, index=True)
    dispatch_mode: Mapped[str | None] = mapped_column(String(10))  # "n8n" or "direct"
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Extraction results (draft, never treated as validated data)
    page_count: Mapped[int | None] = mapped_column(Integer)
    extraction_method: Mapped[str | None] = mapped_column(String(10))
    extracted_text: Mapped[str | None] = mapped_column(Text)
    ai_engine: Mapped[str | None] = mapped_column(String(80))
    ai_engine_note: Mapped[str | None] = mapped_column(Text)
    draft: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ai_suggestions: Mapped[list[str] | None] = mapped_column(JSON)
    grounding: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    draft_summary: Mapped[str | None] = mapped_column(Text)
    processing_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # Human review
    corrected_fields: Mapped[list[str] | None] = mapped_column(JSON)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Plain column (no FK) to avoid a circular dependency with interventions.source_job_id.
    intervention_id: Mapped[int | None] = mapped_column(Integer)
