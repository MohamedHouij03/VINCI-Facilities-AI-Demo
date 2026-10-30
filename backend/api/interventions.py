from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.api.deps import require_api_key, settings_dependency
from backend.config import Settings
from backend.database import get_db
from backend.schemas.interventions import (
    BuildingRead,
    EquipmentRead,
    InterventionPage,
    InterventionRead,
    InterventionUpdate,
)
from backend.services import analytics_service, automation_service, intervention_service
from backend.services.intervention_service import InterventionFilters

router = APIRouter(prefix="/api", tags=["interventions"], dependencies=[Depends(require_api_key)])


def filters_dependency(
    building: list[str] = Query(default=[]),
    category: list[str] = Query(default=[]),
    status: list[str] = Query(default=[]),
    date_from: date | None = None,
    date_to: date | None = None,
    follow_up_open: bool | None = None,
    search: str | None = Query(default=None, max_length=100),
) -> InterventionFilters:
    return InterventionFilters(
        building_codes=building,
        categories=category,
        statuses=status,
        date_from=date_from,
        date_to=date_to,
        follow_up_open=follow_up_open,
        search=search or None,
    )


@router.get("/buildings", response_model=list[BuildingRead])
def get_buildings(db: Session = Depends(get_db)):
    return intervention_service.list_buildings(db)


@router.get("/equipment", response_model=list[EquipmentRead])
def get_equipment(building: str | None = None, db: Session = Depends(get_db)):
    return intervention_service.list_equipment(db, building)


@router.get("/interventions", response_model=InterventionPage)
def get_interventions(
    filters: InterventionFilters = Depends(filters_dependency),
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    total, items = intervention_service.list_interventions(db, filters, limit, offset)
    return InterventionPage(total=total, items=[intervention_service.to_read(i) for i in items])


@router.get("/interventions/{intervention_id}", response_model=InterventionRead)
def get_intervention(intervention_id: int, db: Session = Depends(get_db)):
    return intervention_service.to_read(intervention_service.get_intervention(db, intervention_id))


@router.patch("/interventions/{intervention_id}", response_model=InterventionRead)
def patch_intervention(
    intervention_id: int,
    update: InterventionUpdate,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
):
    intervention, newly_required = intervention_service.update_intervention(db, intervention_id, update)
    if newly_required:  # a human decided that a follow-up is needed
        automation_service.request_follow_up_notification(db, intervention, settings)
    return intervention_service.to_read(intervention_service.get_intervention(db, intervention_id))


@router.post("/interventions/{intervention_id}/complete-follow-up", response_model=InterventionRead)
def complete_follow_up(intervention_id: int, db: Session = Depends(get_db)):
    return intervention_service.to_read(intervention_service.complete_follow_up(db, intervention_id))


@router.get("/analytics/dashboard")
def get_dashboard(
    filters: InterventionFilters = Depends(filters_dependency),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
):
    return analytics_service.dashboard(db, filters, settings)
