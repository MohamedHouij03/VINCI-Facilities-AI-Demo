"""Load the synthetic dataset (CSV files + fictional manuals) into an empty database."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.domain import parse_yes_no
from backend.models import Building, Equipment, Intervention, TechnicalDocument, utcnow
from backend.services.document_service import register_document
from backend.services.errors import ConflictError
from backend.services.storage import sha256_bytes

logger = logging.getLogger(__name__)


def _optional(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def seed_reference_data(db: Session, sample_dir: Path) -> dict[str, int]:
    """Insert buildings, equipment and historical interventions if the database is empty."""
    if db.scalar(select(func.count(Building.id))):
        return {"buildings": 0, "equipment": 0, "interventions": 0}

    buildings = pd.read_csv(sample_dir / "buildings.csv", dtype=str)
    equipment = pd.read_csv(sample_dir / "equipment.csv", dtype=str)
    interventions = pd.read_csv(sample_dir / "interventions.csv", dtype=str)

    building_ids: dict[str, int] = {}
    for row in buildings.itertuples():
        building = Building(code=row.code, name=row.name, sector=row.sector, city=row.city)
        db.add(building)
        db.flush()
        building_ids[row.code] = building.id

    equipment_ids: dict[str, tuple[int, int]] = {}
    for row in equipment.itertuples():
        item = Equipment(
            code=row.code,
            name=row.name,
            category=row.category,
            location=_optional(row.location),
            building_id=building_ids[row.building_code],
        )
        db.add(item)
        db.flush()
        equipment_ids[row.code] = (item.id, building_ids[row.building_code])

    for row in interventions.itertuples():
        equipment_id, building_id = equipment_ids[row.equipment_code]
        completed_at = _optional(row.follow_up_completed_at)
        db.add(
            Intervention(
                reference=row.reference,
                date=pd.Timestamp(row.date).date(),
                building_id=building_id,
                equipment_id=equipment_id,
                technician=_optional(row.technician),
                problem_description=row.problem_description,
                actions_performed=_optional(row.actions_performed),
                status=row.status,
                follow_up_required=bool(parse_yes_no(row.follow_up_required)),
                follow_up_completed_at=pd.Timestamp(completed_at).to_pydatetime() if completed_at else None,
                recommendations=_optional(row.recommendations),
                source="seed",
                created_at=utcnow(),
            )
        )
    db.commit()
    counts = {"buildings": len(buildings), "equipment": len(equipment), "interventions": len(interventions)}
    logger.info("database seeded", extra=counts)
    return counts


def register_sample_manuals(db: Session, settings: Settings) -> int:
    """Register the fictional manuals in the document library (indexing happens separately)."""
    manuals_dir = settings.sample_data_dir / "manuals"
    if not manuals_dir.is_dir():
        return 0
    known = set(db.scalars(select(TechnicalDocument.sha256)))
    registered = 0
    for path in sorted(manuals_dir.glob("*.pdf")):
        data = path.read_bytes()
        if sha256_bytes(data) in known:
            continue
        try:
            register_document(db, data, path.name, settings, is_sample=True)
            registered += 1
        except ConflictError:
            continue
    return registered
