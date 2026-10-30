from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.domain import NotificationStatus
from backend.models.base import Base, TimestampMixin, in_values, new_public_id, utcnow


class Notification(TimestampMixin, Base):
    """A follow-up notification. The unique idempotency key prevents duplicate emails."""

    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(in_values("status", [s.value for s in NotificationStatus]), name="ck_notification_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, default=new_public_id, nullable=False)
    intervention_id: Mapped[int] = mapped_column(ForeignKey("interventions.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(30), default="follow_up", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=NotificationStatus.PENDING, nullable=False)
    recipient: Mapped[str | None] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)


class AutomationEvent(Base):
    """Append-only log used by the workflow-status screen and the automation metrics."""

    __tablename__ = "automation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(10), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("processing_jobs.id"))
    notification_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("notifications.id"))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
