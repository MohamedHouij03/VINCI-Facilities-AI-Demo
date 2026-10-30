"""French intervention summaries that keep documented facts apart from suggestions."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date

from backend.domain import STATUS_LABELS, InterventionStatus
from backend.schemas.extraction import FIELD_LABELS, ExtractionResult, GeminiSummaryPayload
from backend.services.gemini_service import LLMClient, LLMError, llm_label

logger = logging.getLogger(__name__)

_STATUS_SENTENCES = {
    InterventionStatus.TERMINEE: "Le rapport indique que l'intervention est terminée.",
    InterventionStatus.EN_COURS: "L'intervention est en cours ; la résolution du problème n'est pas confirmée par le rapport.",
    InterventionStatus.EN_ATTENTE: "L'intervention est en attente ; le problème n'est pas résolu à ce stade.",
}

SUMMARY_SYSTEM_PROMPT = """Tu rédiges des résumés d'intervention de maintenance en français, pour un responsable \
de site. Tu t'appuies uniquement sur les champs fournis. Règles :
- N'ajoute aucun fait, diagnostic ou cause qui ne figure pas dans les champs.
- N'affirme jamais qu'un problème est résolu si le statut n'est pas « Terminée ».
- Si une information vaut null, ne l'invente pas.
- Les points d'attention sont des suggestions prudentes, à valider par un technicien qualifié.
- Ton professionnel, phrases courtes."""


@dataclass
class SummaryInput:
    reference: str | None
    date: date | None
    building: str | None
    equipment_code: str | None
    equipment_name: str | None
    technician: str | None
    problem_description: str | None
    actions_performed: str | None
    status: InterventionStatus | None
    follow_up_required: bool | None
    recommendations: str | None

    @classmethod
    def from_extraction(cls, result: ExtractionResult) -> SummaryInput:
        return cls(
            reference=result.intervention_id,
            date=result.date,
            building=result.building,
            equipment_code=result.equipment_id,
            equipment_name=result.equipment_name,
            technician=result.technician,
            problem_description=result.problem_description,
            actions_performed=result.actions_performed,
            status=result.status,
            follow_up_required=result.follow_up_required,
            recommendations=result.recommendations,
        )


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else f"{text}."


def template_facts(data: SummaryInput) -> str:
    parts: list[str] = []
    header = f"Intervention {data.reference or '(référence non précisée)'}"
    if data.date:
        header += f" du {data.date.strftime('%d/%m/%Y')}"
    if data.building:
        header += f", {data.building}"
    parts.append(header + ".")
    if data.equipment_code or data.equipment_name:
        equipment = " - ".join(x for x in (data.equipment_code, data.equipment_name) if x)
        parts.append(f"Équipement concerné : {equipment}.")
    if data.technician:
        parts.append(f"Technicien : {data.technician}.")
    parts.append(
        f"Problème constaté : {_sentence(data.problem_description)}"
        if data.problem_description
        else "Le problème n'est pas décrit dans le rapport."
    )
    parts.append(
        f"Actions réalisées : {_sentence(data.actions_performed)}"
        if data.actions_performed
        else "Les actions réalisées ne sont pas documentées."
    )
    parts.append(_STATUS_SENTENCES.get(data.status, "Le statut n'est pas précisé dans le rapport."))  # type: ignore[arg-type]
    if data.follow_up_required is True:
        parts.append("Un suivi est requis.")
    elif data.follow_up_required is False:
        parts.append("Aucun suivi n'est demandé dans le rapport.")
    else:
        parts.append("Le besoin de suivi n'est pas précisé.")
    return " ".join(parts)


def compose_summary(facts: str, data: SummaryInput, suggestions: list[str], missing: list[str]) -> str:
    sections = [f"**Faits documentés**\n\n{facts}"]
    if data.recommendations:
        sections.append(f"**Recommandations figurant dans le rapport**\n\n{_sentence(data.recommendations)}")
    if missing:
        labels = ", ".join(FIELD_LABELS[name].lower() for name in missing)
        sections.append(f"**Informations absentes du document**\n\n{labels.capitalize()}.")
    if suggestions:
        bullet_list = "\n".join(f"- {s}" for s in suggestions)
        sections.append(
            "**Suggestions générées par IA (non vérifiées, à valider par un technicien qualifié)**\n\n" + bullet_list
        )
    return "\n\n".join(sections)


def _llm_facts(data: SummaryInput, client: LLMClient) -> tuple[str, list[str]]:
    fields = {
        "reference": data.reference,
        "date": data.date.isoformat() if data.date else None,
        "batiment": data.building,
        "equipement": " - ".join(x for x in (data.equipment_code, data.equipment_name) if x) or None,
        "technicien": data.technician,
        "probleme": data.problem_description,
        "actions_realisees": data.actions_performed,
        "statut": STATUS_LABELS[data.status] if data.status else None,
        "suivi_necessaire": data.follow_up_required,
        "recommandations_du_rapport": data.recommendations,
    }
    prompt = "Champs validés de l'intervention (JSON) :\n" + json.dumps(fields, ensure_ascii=False, indent=2)
    payload = client.generate_json(prompt, GeminiSummaryPayload, SUMMARY_SYSTEM_PROMPT)
    return payload.facts.strip(), [p.strip() for p in payload.attention_points if p.strip()][:3]


def generate_summary(
    data: SummaryInput,
    client: LLMClient | None,
    suggestions: list[str] | None = None,
    missing: list[str] | None = None,
) -> tuple[str, str]:
    """Return (markdown summary, engine). Falls back to the deterministic template on LLM failure."""
    suggestions = list(suggestions or [])
    if client is not None:
        try:
            facts, attention_points = _llm_facts(data, client)
            merged = suggestions + [p for p in attention_points if p not in suggestions]
            return compose_summary(facts, data, merged[:3], missing or []), llm_label(client)
        except LLMError as exc:
            logger.warning("gemini summary failed, using template", extra={"error": str(exc)})
    return compose_summary(template_facts(data), data, suggestions, missing or []), "template"
