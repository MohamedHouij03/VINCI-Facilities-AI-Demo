"""Queries and updates on buildings, equipment and interventions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, joinedload

from backend.domain import STATUS_LABELS, InterventionStatus, simplify
from backend.models import Building, Equipment, Intervention, utcnow
from backend.schemas.interventions import EquipmentRead, InterventionRead, InterventionUpdate
from backend.services.errors import ConflictError, NotFoundError


@dataclass
class InterventionFilters:
    building_codes: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    date_from: date | None = None
    date_to: date | None = None
    follow_up_open: bool | None = None
    search: str | None = None

    def apply(self, statement: Select) -> Select:
        if self.building_codes:
            statement = statement.where(Building.code.in_(self.building_codes))
        if self.categories:
            statement = statement.where(Equipment.category.in_(self.categories))
        if self.statuses:
            statement = statement.where(Intervention.status.in_(self.statuses))
        if self.date_from:
            statement = statement.where(Intervention.date >= self.date_from)
        if self.date_to:
            statement = statement.where(Intervention.date <= self.date_to)
        if self.follow_up_open is True:
            statement = statement.where(
                Intervention.follow_up_required.is_(True), Intervention.follow_up_completed_at.is_(None)
            )
        elif self.follow_up_open is False:
            statement = statement.where(
                or_(Intervention.follow_up_required.is_(False), Intervention.follow_up_completed_at.is_not(None))
            )
        if self.search:
            pattern = f"%{self.search.strip()}%"
            statement = statement.where(
                or_(
                    Intervention.reference.ilike(pattern),
                    Intervention.problem_description.ilike(pattern),
                    Intervention.actions_performed.ilike(pattern),
                    Intervention.technician.ilike(pattern),
                    Equipment.code.ilike(pattern),
                    Equipment.name.ilike(pattern),
                    Building.name.ilike(pattern),
                )
            )
        return statement


def to_read(intervention: Intervention) -> InterventionRead:
    return InterventionRead(
        id=intervention.id,
        reference=intervention.reference,
        date=intervention.date,
        building_code=intervention.building.code,
        building_name=intervention.building.name,
        equipment_code=intervention.equipment.code,
        equipment_name=intervention.equipment.name,
        equipment_category=intervention.equipment.category,
        technician=intervention.technician,
        problem_description=intervention.problem_description,
        actions_performed=intervention.actions_performed,
        status=InterventionStatus(intervention.status),
        status_label=STATUS_LABELS[intervention.status],
        follow_up_required=intervention.follow_up_required,
        follow_up_open=intervention.follow_up_open,
        follow_up_completed_at=intervention.follow_up_completed_at,
        recommendations=intervention.recommendations,
        summary=intervention.summary,
        source=intervention.source,
        source_job_id=intervention.source_job_id,
        created_at=intervention.created_at,
        updated_at=intervention.updated_at,
    )


def _base_query() -> Select:
    return (
        select(Intervention)
        .join(Intervention.building)
        .join(Intervention.equipment)
        .options(joinedload(Intervention.building), joinedload(Intervention.equipment))
    )


def list_interventions(
    db: Session, filters: InterventionFilters, limit: int = 500, offset: int = 0
) -> tuple[int, list[Intervention]]:
    statement = filters.apply(_base_query())
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    rows = db.scalars(statement.order_by(Intervention.date.desc(), Intervention.id.desc()).limit(limit).offset(offset))
    return total, list(rows.unique())


def get_intervention(db: Session, intervention_id: int) -> Intervention:
    intervention = db.scalars(_base_query().where(Intervention.id == intervention_id)).first()
    if intervention is None:
        raise NotFoundError(f"Intervention {intervention_id} introuvable.")
    return intervention


def get_by_reference(db: Session, reference: str) -> Intervention | None:
    return db.scalars(_base_query().where(Intervention.reference == reference.upper())).first()


def update_intervention(db: Session, intervention_id: int, update: InterventionUpdate) -> tuple[Intervention, bool]:
    """Apply a manager's correction. Returns (intervention, follow_up_newly_required)."""
    intervention = get_intervention(db, intervention_id)
    changes = update.model_dump(exclude_unset=True)
    if "problem_description" in changes and not changes["problem_description"]:
        raise ConflictError("La description du problème ne peut pas être vide.")
    newly_required = changes.get("follow_up_required") is True and not intervention.follow_up_required
    for name, value in changes.items():
        setattr(intervention, name, value.value if isinstance(value, InterventionStatus) else value)
    if changes.get("follow_up_required") is False:
        intervention.follow_up_completed_at = None
    db.commit()
    db.refresh(intervention)
    return intervention, newly_required


def complete_follow_up(db: Session, intervention_id: int) -> Intervention:
    intervention = get_intervention(db, intervention_id)
    if not intervention.follow_up_required:
        raise ConflictError("Cette intervention ne nécessite pas de suivi.")
    if intervention.follow_up_completed_at is None:
        intervention.follow_up_completed_at = utcnow()
        db.commit()
        db.refresh(intervention)
    return intervention


def list_buildings(db: Session) -> list[Building]:
    return list(db.scalars(select(Building).order_by(Building.code)))


def list_equipment(db: Session, building_code: str | None = None) -> list[EquipmentRead]:
    statement = select(Equipment).join(Equipment.building).options(joinedload(Equipment.building))
    if building_code:
        statement = statement.where(Building.code == building_code)
    return [
        EquipmentRead(
            code=e.code,
            name=e.name,
            category=e.category,
            location=e.location,
            building_code=e.building.code,
            building_name=e.building.name,
        )
        for e in db.scalars(statement.order_by(Equipment.code))
    ]


def find_equipment(db: Session, code: str | None) -> Equipment | None:
    if not code:
        return None
    return db.scalars(
        select(Equipment).options(joinedload(Equipment.building)).where(Equipment.code == code.strip().upper())
    ).first()


_LETTER_PATTERN = re.compile(r"\bbatiment\s+([a-z])\b")


def resolve_building(db: Session, text: str | None) -> Building | None:
    """Match free text such as 'Bâtiment A - Immeuble Horizon' or 'BAT-A' to a known building."""
    if not text:
        return None
    buildings = list_buildings(db)
    simplified = simplify(text)
    for building in buildings:
        if simplify(building.code) in simplified.replace(" ", "-"):
            return building
    if match := _LETTER_PATTERN.search(simplified):
        code = f"BAT-{match.group(1).upper()}"
        for building in buildings:
            if building.code == code:
                return building
    for building in buildings:
        name = simplify(building.name)
        distinctive = name.split(" - ", 1)[-1]
        if distinctive and distinctive in simplified:
            return building
    return None
