from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.domain import EQUIPMENT_CATEGORIES, InterventionStatus
from backend.models.base import Base, TimestampMixin, in_values


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    sector: Mapped[str] = mapped_column(String(50), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)

    equipment: Mapped[list[Equipment]] = relationship(back_populates="building")


class Equipment(Base):
    __tablename__ = "equipment"
    __table_args__ = (CheckConstraint(in_values("category", EQUIPMENT_CATEGORIES), name="ck_equipment_category"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    location: Mapped[str | None] = mapped_column(String(200))
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"), nullable=False, index=True)

    building: Mapped[Building] = relationship(back_populates="equipment")


class Intervention(TimestampMixin, Base):
    __tablename__ = "interventions"
    __table_args__ = (
        CheckConstraint(in_values("status", [s.value for s in InterventionStatus]), name="ck_intervention_status"),
        CheckConstraint(in_values("source", ("seed", "report", "manual")), name="ck_intervention_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id"), nullable=False, index=True)
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"), nullable=False, index=True)
    technician: Mapped[str | None] = mapped_column(String(120))
    problem_description: Mapped[str] = mapped_column(Text, nullable=False)
    actions_performed: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    follow_up_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    follow_up_completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    recommendations: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="seed", nullable=False)
    source_job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("processing_jobs.id"))

    building: Mapped[Building] = relationship()
    equipment: Mapped[Equipment] = relationship()

    @property
    def follow_up_open(self) -> bool:
        return self.follow_up_required and self.follow_up_completed_at is None
