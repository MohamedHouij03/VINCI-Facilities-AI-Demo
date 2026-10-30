from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.domain import EQUIPMENT_CATEGORIES, InterventionStatus, normalize_category
from backend.schemas.extraction import clean_optional_text

_IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]*$"


class BuildingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    sector: str
    city: str


class EquipmentRead(BaseModel):
    code: str
    name: str
    category: str
    location: str | None
    building_code: str
    building_name: str


class InterventionRead(BaseModel):
    id: int
    reference: str
    date: dt.date
    building_code: str
    building_name: str
    equipment_code: str
    equipment_name: str
    equipment_category: str
    technician: str | None
    problem_description: str
    actions_performed: str | None
    status: InterventionStatus
    status_label: str
    follow_up_required: bool
    follow_up_open: bool
    follow_up_completed_at: dt.datetime | None
    recommendations: str | None
    summary: str | None
    source: str
    source_job_id: int | None
    created_at: dt.datetime
    updated_at: dt.datetime


class InterventionPage(BaseModel):
    total: int
    items: list[InterventionRead]


class InterventionUpdate(BaseModel):
    """Fields a manager may correct after an intervention has been recorded."""

    model_config = ConfigDict(extra="forbid")

    date: dt.date | None = None
    technician: str | None = Field(None, max_length=120)
    problem_description: str | None = Field(None, min_length=3, max_length=4000)
    actions_performed: str | None = Field(None, max_length=4000)
    status: InterventionStatus | None = None
    follow_up_required: bool | None = None
    recommendations: str | None = Field(None, max_length=4000)


class InterventionApproval(BaseModel):
    """Human-validated intervention submitted from the review form."""

    model_config = ConfigDict(extra="forbid")

    reference: str = Field(min_length=3, max_length=50, pattern=_IDENTIFIER_PATTERN)
    date: dt.date
    building_code: str = Field(min_length=1, max_length=20)
    equipment_code: str = Field(min_length=2, max_length=30, pattern=_IDENTIFIER_PATTERN)
    equipment_name: str = Field(min_length=2, max_length=200)
    equipment_category: str
    technician: str | None = Field(None, max_length=120)
    problem_description: str = Field(min_length=3, max_length=4000)
    actions_performed: str | None = Field(None, max_length=4000)
    status: InterventionStatus
    follow_up_required: bool
    recommendations: str | None = Field(None, max_length=4000)

    @field_validator("reference", "equipment_code", "building_code", mode="before")
    @classmethod
    def _upper_identifier(cls, value: object) -> object:
        return str(value).strip().upper() if isinstance(value, str) else value

    @field_validator("technician", "actions_performed", "recommendations", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> str | None:
        return clean_optional_text(value)

    @field_validator("equipment_category")
    @classmethod
    def _known_category(cls, value: str) -> str:
        category = normalize_category(value)
        if category not in EQUIPMENT_CATEGORIES:
            raise ValueError(f"Catégorie inconnue : {value}")
        return category

    @field_validator("date")
    @classmethod
    def _not_in_future(cls, value: dt.date) -> dt.date:
        if value > dt.date.today() + dt.timedelta(days=1):
            raise ValueError("La date d'intervention ne peut pas être dans le futur.")
        return value
