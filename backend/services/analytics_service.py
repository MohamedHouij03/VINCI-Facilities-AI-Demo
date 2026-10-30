"""Maintenance analytics computed from the database (no hard-coded figures).

Recurring-incident rule (configurable): an equipment asset has recurring incidents when at least
RECURRENCE_THRESHOLD interventions fall within a window of RECURRENCE_WINDOW_DAYS consecutive days,
i.e. the last and first dates of the group are less than RECURRENCE_WINDOW_DAYS days apart.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.domain import STATUS_LABELS, InterventionStatus, simplify
from backend.models import Building, Equipment, Intervention
from backend.services.intervention_service import InterventionFilters

FRENCH_MONTH_NAMES = (
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
FRENCH_MONTH_ABBREVIATIONS = (
    "janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.",
)

COLUMNS = [
    "id", "reference", "date", "status", "follow_up_required", "follow_up_completed_at", "technician",
    "problem_description", "building_code", "building_name", "equipment_code", "equipment_name", "category",
]


def interventions_frame(db: Session, filters: InterventionFilters | None = None) -> pd.DataFrame:
    statement = (
        select(
            Intervention.id,
            Intervention.reference,
            Intervention.date,
            Intervention.status,
            Intervention.follow_up_required,
            Intervention.follow_up_completed_at,
            Intervention.technician,
            Intervention.problem_description,
            Building.code,
            Building.name,
            Equipment.code,
            Equipment.name,
            Equipment.category,
        )
        .join(Building, Intervention.building_id == Building.id)
        .join(Equipment, Intervention.equipment_id == Equipment.id)
    )
    if filters is not None:
        statement = filters.apply(statement)
    frame = pd.DataFrame(db.execute(statement).all(), columns=COLUMNS)
    frame["date"] = pd.to_datetime(frame["date"])
    frame["follow_up_open"] = frame["follow_up_required"].astype(bool) & frame["follow_up_completed_at"].isna()
    return frame


def max_events_in_window(dates: Sequence[date], window_days: int) -> tuple[int, date | None, date | None]:
    """Largest number of events whose first and last dates are less than `window_days` apart (two pointers)."""
    ordered = sorted(dates)
    best, best_start, best_end = 0, None, None
    left = 0
    for right, current in enumerate(ordered):
        while (current - ordered[left]).days >= window_days:
            left += 1
        if right - left + 1 > best:
            best, best_start, best_end = right - left + 1, ordered[left], current
    return best, best_start, best_end


def detect_recurring(frame: pd.DataFrame, threshold: int, window_days: int) -> pd.DataFrame:
    rows = []
    for (code, name, building_code, building_name, category), group in frame.groupby(
        ["equipment_code", "equipment_name", "building_code", "building_name", "category"]
    ):
        dates = [d.date() for d in group["date"]]
        count, start, end = max_events_in_window(dates, window_days)
        rows.append(
            {
                "equipment_code": code,
                "equipment_name": name,
                "building_code": building_code,
                "building_name": building_name,
                "category": category,
                "total_interventions": len(group),
                "max_in_window": count,
                "window_start": start.isoformat() if start else None,
                "window_end": end.isoformat() if end else None,
                "recurring": count >= threshold,
            }
        )
    result = pd.DataFrame(rows)
    if result.empty:
        return result
    return result.sort_values(["recurring", "max_in_window", "total_interventions"], ascending=False)


def _month_series(frame: pd.DataFrame, filters: InterventionFilters) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    start = pd.Timestamp(filters.date_from) if filters.date_from else frame["date"].min()
    end = pd.Timestamp(filters.date_to) if filters.date_to else frame["date"].max()
    months = pd.period_range(start.to_period("M"), end.to_period("M"), freq="M")
    counts = frame.groupby(frame["date"].dt.to_period("M")).size()
    return [
        {
            "month": str(period),
            "label": f"{FRENCH_MONTH_ABBREVIATIONS[period.month - 1]} {period.year}",
            "count": int(counts.get(period, 0)),
        }
        for period in months
    ]


def _counts(frame: pd.DataFrame, column: str, label_column: str | None = None) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    keys = [column] + ([label_column] if label_column else [])
    grouped = frame.groupby(keys).size().reset_index(name="count").sort_values("count", ascending=False)
    return grouped.to_dict(orient="records")


def dashboard(db: Session, filters: InterventionFilters, settings: Settings) -> dict[str, Any]:
    frame = interventions_frame(db, filters)
    recurring = detect_recurring(frame, settings.recurrence_threshold, settings.recurrence_window_days)
    recurring_codes = set(recurring.loc[recurring["recurring"], "equipment_code"]) if not recurring.empty else set()

    building_query = select(func.count(Building.id))
    if filters.building_codes:
        building_query = building_query.where(Building.code.in_(filters.building_codes))

    status_counts = frame["status"].value_counts().to_dict() if not frame.empty else {}
    kpis = {
        "total": len(frame),
        "completed": int(status_counts.get(InterventionStatus.TERMINEE, 0)),
        "pending": int(status_counts.get(InterventionStatus.EN_ATTENTE, 0) + status_counts.get(InterventionStatus.EN_COURS, 0)),
        "in_progress": int(status_counts.get(InterventionStatus.EN_COURS, 0)),
        "waiting": int(status_counts.get(InterventionStatus.EN_ATTENTE, 0)),
        "follow_up_open": int(frame["follow_up_open"].sum()) if not frame.empty else 0,
        "recurring_equipment": len(recurring_codes),
        "buildings_monitored": db.scalar(building_query) or 0,
    }

    by_status = [
        {"status": status.value, "label": STATUS_LABELS[status], "count": int(status_counts.get(status, 0))}
        for status in InterventionStatus
    ]

    top_equipment: list[dict[str, Any]] = []
    follow_up_equipment: list[dict[str, Any]] = []
    recent: list[dict[str, Any]] = []
    if not frame.empty:
        equipment_counts = (
            frame.groupby(["equipment_code", "equipment_name", "building_code"]).size().reset_index(name="count")
        )
        equipment_counts = equipment_counts.sort_values(["count", "equipment_code"], ascending=[False, True]).head(10)
        equipment_counts["recurring"] = equipment_counts["equipment_code"].isin(recurring_codes)
        top_equipment = equipment_counts.to_dict(orient="records")

        open_follow_ups = frame[frame["follow_up_open"]]
        if not open_follow_ups.empty:
            follow_up_equipment = (
                open_follow_ups.groupby(["equipment_code", "equipment_name", "building_code"])
                .agg(open_follow_ups=("id", "count"), last_date=("date", "max"))
                .reset_index()
                .sort_values(["open_follow_ups", "last_date"], ascending=False)
                .assign(last_date=lambda df: df["last_date"].dt.date.astype(str))
                .to_dict(orient="records")
            )

        latest = frame.sort_values(["date", "id"], ascending=False).head(8)
        recent = [
            {
                "id": int(row.id),
                "reference": row.reference,
                "date": row.date.date().isoformat(),
                "building_code": row.building_code,
                "equipment": f"{row.equipment_code} - {row.equipment_name}",
                "problem": row.problem_description,
                "status": STATUS_LABELS[row.status],
                "follow_up_open": bool(row.follow_up_open),
            }
            for row in latest.itertuples()
        ]

    return {
        "kpis": kpis,
        "by_month": _month_series(frame, filters),
        "by_building": _counts(frame, "building_code", "building_name"),
        "by_category": _counts(frame, "category"),
        "by_status": by_status,
        "top_equipment": top_equipment,
        "follow_up_equipment": follow_up_equipment,
        "recurring": recurring.to_dict(orient="records") if not recurring.empty else [],
        "recent": recent,
        "recurrence_rule": {
            "threshold": settings.recurrence_threshold,
            "window_days": settings.recurrence_window_days,
        },
        "date_bounds": {
            "min": frame["date"].min().date().isoformat() if not frame.empty else None,
            "max": frame["date"].max().date().isoformat() if not frame.empty else None,
        },
    }


# --------------------------------------------------------------------------------------
# Predefined analytical functions used by the assistant (no free-form SQL)
# --------------------------------------------------------------------------------------


def resolve_period(code: str, today: date) -> tuple[date | None, date | None, str]:
    if code == "this_month":
        start = today.replace(day=1)
        return start, today, f"en {FRENCH_MONTH_NAMES[today.month - 1]} {today.year}"
    if code == "last_month":
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end, f"en {FRENCH_MONTH_NAMES[end.month - 1]} {end.year}"
    if code == "last_30_days":
        return today - timedelta(days=29), today, "sur les 30 derniers jours"
    if code == "this_week":
        return today - timedelta(days=today.weekday()), today, "cette semaine"
    if code == "this_year":
        return date(today.year, 1, 1), today, f"en {today.year}"
    return None, None, "sur l'ensemble de l'historique"


def _period_filters(period: str, today: date, building_code: str | None = None, category: str | None = None):
    start, end, label = resolve_period(period, today)
    filters = InterventionFilters(
        building_codes=[building_code] if building_code else [],
        categories=[category] if category else [],
        date_from=start,
        date_to=end,
    )
    return filters, label


def top_failing_equipment(
    db: Session, settings: Settings, today: date, period: str = "all",
    building_code: str | None = None, category: str | None = None, limit: int = 5,
) -> tuple[list[dict[str, Any]], str]:
    filters, label = _period_filters(period, today, building_code, category)
    frame = interventions_frame(db, filters)
    if frame.empty:
        return [], label
    recurring = detect_recurring(frame, settings.recurrence_threshold, settings.recurrence_window_days)
    recurring_codes = set(recurring.loc[recurring["recurring"], "equipment_code"])
    grouped = (
        frame.groupby(["equipment_code", "equipment_name", "building_code"])
        .agg(interventions=("id", "count"), derniere=("date", "max"))
        .reset_index()
        .sort_values(["interventions", "derniere"], ascending=False)
        .head(limit)
    )
    rows = [
        {
            "Équipement": f"{r.equipment_code} - {r.equipment_name}",
            "Bâtiment": r.building_code,
            "Interventions": int(r.interventions),
            "Dernière intervention": r.derniere.date().isoformat(),
            "Incidents récurrents": "Oui" if r.equipment_code in recurring_codes else "Non",
        }
        for r in grouped.itertuples()
    ]
    return rows, label


def interventions_count(
    db: Session, today: date, period: str = "all", building_code: str | None = None, category: str | None = None
) -> tuple[dict[str, int], str]:
    filters, label = _period_filters(period, today, building_code, category)
    frame = interventions_frame(db, filters)
    counts = frame["status"].value_counts().to_dict() if not frame.empty else {}
    return {
        "total": len(frame),
        **{STATUS_LABELS[s]: int(counts.get(s, 0)) for s in InterventionStatus},
    }, label


def building_ranking(db: Session, today: date, period: str = "all") -> tuple[list[dict[str, Any]], str]:
    filters, label = _period_filters(period, today)
    frame = interventions_frame(db, filters)
    if frame.empty:
        return [], label
    grouped = (
        frame.groupby(["building_code", "building_name"])
        .agg(
            interventions=("id", "count"),
            en_cours=("status", lambda s: int((s != InterventionStatus.TERMINEE).sum())),
            suivis=("follow_up_open", "sum"),
        )
        .reset_index()
        .sort_values(["interventions", "suivis"], ascending=False)
    )
    rows = [
        {
            "Bâtiment": r.building_name,
            "Interventions": int(r.interventions),
            "Non terminées": int(r.en_cours),
            "Suivis ouverts": int(r.suivis),
        }
        for r in grouped.itertuples()
    ]
    return rows, label


def follow_up_list(db: Session, building_code: str | None = None) -> list[dict[str, Any]]:
    filters = InterventionFilters(building_codes=[building_code] if building_code else [], follow_up_open=True)
    frame = interventions_frame(db, filters).sort_values("date", ascending=False)
    return [
        {
            "Référence": r.reference,
            "Date": r.date.date().isoformat(),
            "Bâtiment": r.building_code,
            "Équipement": f"{r.equipment_code} - {r.equipment_name}",
            "Problème": r.problem_description,
            "Statut": STATUS_LABELS[r.status],
        }
        for r in frame.itertuples()
    ]


EQUIPMENT_KEYWORD_SYNONYMS: dict[str, tuple[str, ...]] = {
    "climatisation": ("climatisation", "groupe froid", "split", "froid", "climatiseur"),
    "ventilation": ("ventilation", "cta", "traitement d'air", "vmc", "extracteur"),
    "chauffage": ("chaudiere", "chauffage", "pompe a chaleur"),
    "electricite": ("tableau", "tgbt", "disjoncteur", "groupe electrogene"),
    "ascenseur": ("ascenseur",),
    "plomberie": ("eau", "surpresseur", "reseau", "hydraulique", "ballon"),
    "incendie": ("incendie", "ssi", "desenfumage"),
}


def equipment_issues(
    db: Session, building_code: str | None = None, keyword: str | None = None, category: str | None = None
) -> list[dict[str, Any]]:
    filters = InterventionFilters(building_codes=[building_code] if building_code else [])
    frame = interventions_frame(db, filters)
    if frame.empty:
        return []
    selected = frame
    if keyword:
        terms = EQUIPMENT_KEYWORD_SYNONYMS.get(simplify(keyword), (simplify(keyword),))
        names = frame["equipment_name"].map(simplify) + " " + frame["equipment_code"].map(simplify)
        mask = names.apply(lambda text: any(term in text for term in terms))
        selected = frame[mask]
        if selected.empty and category:
            selected = frame[frame["category"] == category]
    elif category:
        selected = frame[frame["category"] == category]
    selected = selected.sort_values("date", ascending=False)
    return [
        {
            "Référence": r.reference,
            "Date": r.date.date().isoformat(),
            "Bâtiment": r.building_code,
            "Équipement": f"{r.equipment_code} - {r.equipment_name}",
            "Problème": r.problem_description,
            "Statut": STATUS_LABELS[r.status],
        }
        for r in selected.itertuples()
    ]


def recurring_equipment(db: Session, settings: Settings) -> list[dict[str, Any]]:
    frame = interventions_frame(db)
    recurring = detect_recurring(frame, settings.recurrence_threshold, settings.recurrence_window_days)
    if recurring.empty:
        return []
    flagged = recurring[recurring["recurring"]]
    return [
        {
            "Équipement": f"{r.equipment_code} - {r.equipment_name}",
            "Bâtiment": r.building_code,
            "Interventions dans la fenêtre": int(r.max_in_window),
            "Période": f"{r.window_start} → {r.window_end}",
            "Total historique": int(r.total_interventions),
        }
        for r in flagged.itertuples()
    ]
