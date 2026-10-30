"""Schemas for AI information extraction.

`ExtractionResult` is the validated contract for information *found in the document*.
AI-generated suggestions are kept in a separate structure and never merged into it.
"""

from __future__ import annotations

import datetime as dt
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.domain import (
    InterventionStatus,
    normalize_category,
    normalize_status,
    parse_french_date,
    parse_yes_no,
    simplify,
)

EXTRACTION_FIELDS: tuple[str, ...] = (
    "intervention_id",
    "date",
    "building",
    "equipment_id",
    "equipment_name",
    "equipment_category",
    "technician",
    "problem_description",
    "actions_performed",
    "status",
    "follow_up_required",
    "recommendations",
)

FIELD_LABELS: dict[str, str] = {
    "intervention_id": "N° d'intervention",
    "date": "Date",
    "building": "Bâtiment",
    "equipment_id": "Identifiant équipement",
    "equipment_name": "Équipement",
    "equipment_category": "Catégorie",
    "technician": "Technicien",
    "problem_description": "Problème constaté",
    "actions_performed": "Actions réalisées",
    "status": "Statut",
    "follow_up_required": "Suivi nécessaire",
    "recommendations": "Recommandations",
}

_NULL_TOKENS = {
    "", "null", "none", "n/a", "na", "-", "?", "inconnu", "inconnue", "non renseigne", "non renseignee",
    "non precise", "non precisee", "non communique", "non indique", "non mentionne", "aucune information",
}

_TEXT_FIELDS = ("building", "equipment_name", "technician", "problem_description", "actions_performed", "recommendations")


def clean_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip(" \t\n;,")
    if simplify(text) in _NULL_TOKENS:
        return None
    return text


class ExtractionResult(BaseModel):
    """Information explicitly documented in a maintenance report. Unknown values stay null."""

    model_config = ConfigDict(extra="ignore")

    intervention_id: str | None = None
    date: dt.date | None = None
    building: str | None = None
    equipment_id: str | None = None
    equipment_name: str | None = None
    equipment_category: str | None = None
    technician: str | None = None
    problem_description: str | None = None
    actions_performed: str | None = None
    status: InterventionStatus | None = None
    follow_up_required: bool | None = None
    recommendations: str | None = None

    @field_validator(*_TEXT_FIELDS, mode="before")
    @classmethod
    def _clean_text(cls, value: object) -> str | None:
        return clean_optional_text(value)

    @field_validator("intervention_id", "equipment_id", mode="before")
    @classmethod
    def _clean_identifier(cls, value: object) -> str | None:
        text = clean_optional_text(value)
        return re.sub(r"\s+", "", text).upper() if text else None

    @field_validator("date", mode="before")
    @classmethod
    def _parse_date(cls, value: object) -> dt.date | None:
        if isinstance(value, dt.date):
            return value
        return parse_french_date(clean_optional_text(value))

    @field_validator("status", mode="before")
    @classmethod
    def _parse_status(cls, value: object) -> InterventionStatus | None:
        return normalize_status(clean_optional_text(value))

    @field_validator("equipment_category", mode="before")
    @classmethod
    def _parse_category(cls, value: object) -> str | None:
        return normalize_category(clean_optional_text(value))

    @field_validator("follow_up_required", mode="before")
    @classmethod
    def _parse_follow_up(cls, value: object) -> bool | None:
        return parse_yes_no(value)

    def missing_fields(self) -> list[str]:
        return [name for name in EXTRACTION_FIELDS if getattr(self, name) is None]


class GeminiExtractedFields(BaseModel):
    """Plain-typed schema sent to Gemini as `response_schema` (validated afterwards by ExtractionResult)."""

    intervention_id: str | None = Field(None, description="Numéro/référence du rapport, tel qu'écrit.")
    date: str | None = Field(None, description="Date de l'intervention au format AAAA-MM-JJ.")
    building: str | None = Field(None, description="Bâtiment ou site, tel qu'écrit.")
    equipment_id: str | None = Field(None, description="Identifiant/repère de l'équipement (ex. CTA-A01).")
    equipment_name: str | None = Field(None, description="Désignation de l'équipement.")
    equipment_category: str | None = Field(
        None, description="Une valeur parmi : CVC, Électricité, Plomberie, Sécurité incendie, Ascenseurs, Autre."
    )
    technician: str | None = Field(None, description="Nom du technicien intervenant.")
    problem_description: str | None = Field(None, description="Problème constaté, reformulé fidèlement.")
    actions_performed: str | None = Field(None, description="Actions effectivement réalisées.")
    status: str | None = Field(None, description="Une valeur parmi : En attente, En cours, Terminée.")
    follow_up_required: bool | None = Field(None, description="true/false seulement si le document l'indique.")
    recommendations: str | None = Field(None, description="Recommandations écrites dans le rapport.")


class GeminiExtractionPayload(BaseModel):
    fields: GeminiExtractedFields
    ai_suggestions: list[str] = Field(
        default_factory=list,
        description="0 à 3 suggestions de prochaines étapes, NON présentes dans le document.",
    )


class GeminiSummaryPayload(BaseModel):
    facts: str = Field(description="Résumé factuel en 2 à 4 phrases, uniquement à partir des champs fournis.")
    attention_points: list[str] = Field(default_factory=list, description="0 à 3 points d'attention.")
