"""Maintenance assistant: routes a question to a predefined analytical function or to RAG.

The LLM (when available) only *selects* a whitelisted function and its parameters; it never writes SQL.
Figures in analytical answers come straight from the database, formatted by deterministic templates.
"""

from __future__ import annotations

import logging
import re
from datetime import date

from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.domain import EQUIPMENT_CATEGORIES, normalize_category, simplify
from backend.models import Building
from backend.schemas.assistant import AskResponse, PeriodCode, RoutingDecision, SourceReference, ToolName
from backend.services import analytics_service as analytics
from backend.services.gemini_service import LLMClient, LLMError, llm_label
from backend.services.intervention_service import list_buildings
from backend.services.rag_service import SAFETY_DISCLAIMER, get_rag_service

logger = logging.getLogger(__name__)

UNSUPPORTED_ANSWER = (
    "Je peux répondre aux questions sur les interventions enregistrées (volumes, équipements, bâtiments, suivis, "
    "incidents récurrents) ou sur la documentation technique indexée. Pouvez-vous reformuler votre question ?"
)

TOOL_DESCRIPTIONS: dict[str, str] = {
    "top_failing_equipment": "équipements ayant le plus d'interventions / de pannes",
    "interventions_count": "nombre d'interventions sur une période (avec répartition par statut)",
    "building_ranking": "bâtiments classés par nombre d'interventions (besoin de maintenance)",
    "follow_up_list": "interventions nécessitant un suivi non clôturé",
    "equipment_issues": "problèmes rencontrés sur un équipement, un type d'équipement ou un bâtiment",
    "recurring_equipment": "équipements présentant des incidents récurrents",
    "document_search": "question technique sur les manuels / la documentation (causes, procédures, recommandations)",
    "unsupported": "question hors du périmètre maintenance",
}

_CATEGORY_WORDS: dict[str, tuple[str, ...]] = {
    "CVC": ("climatisation", "clim", "ventilation", "chauffage", "cta", "vmc", "groupe froid", "chaudiere", "cvc"),
    "Électricité": ("electri", "disjoncteur", "tableau", "tgbt"),
    "Plomberie": ("fuite", "plomberie", "sanitaire", "eau chaude", "hydraulique"),
    "Sécurité incendie": ("incendie", "ssi", "desenfumage"),
    "Ascenseurs": ("ascenseur",),
}

_DOCUMENT_MARKERS = (
    "manuel", "documentation", "notice", "guide", "procedure", "recommande le", "preconise", "selon la doc",
    "que faire", "comment ", "pourquoi", "causes possibles", "quelle cause", "quelles causes", "frequence",
    "periodicite", "consigne",
)


class GeminiRouting(BaseModel):
    tool: ToolName
    building_code: str | None = None
    category: str | None = None
    equipment_keyword: str | None = None
    period: PeriodCode = "all"

    @field_validator("period", mode="before")
    @classmethod
    def _default_period(cls, value: object) -> object:
        return value or "all"


def _detect_period(text: str) -> PeriodCode:
    if "ce mois" in text or "mois en cours" in text:
        return "this_month"
    if "mois dernier" in text or "mois precedent" in text:
        return "last_month"
    if "30 derniers jours" in text or "trente derniers jours" in text:
        return "last_30_days"
    if "cette semaine" in text:
        return "this_week"
    if "cette annee" in text:
        return "this_year"
    return "all"


def _detect_building(text: str, buildings: list[Building]) -> str | None:
    codes = {b.code for b in buildings}
    if match := re.search(r"\bbat(?:iment)?[\s-]+([a-z])\b", text):
        code = f"BAT-{match.group(1).upper()}"
        if code in codes:
            return code
    for building in buildings:
        distinctive = simplify(building.name).split(" - ", 1)[-1]
        keywords = [w for w in distinctive.split() if len(w) >= 6]
        if keywords and any(w in text for w in keywords[:2]):
            return building.code
    return None


def _detect_category(text: str) -> str | None:
    for category, words in _CATEGORY_WORDS.items():
        if any(word in text for word in words):
            return category
    return None


def _detect_keyword(text: str) -> str | None:
    for keyword, synonyms in analytics.EQUIPMENT_KEYWORD_SYNONYMS.items():
        if keyword in text or any(f" {s}" in f" {text}" for s in synonyms if len(s) > 3):
            return keyword
    return None


def route_with_rules(question: str, buildings: list[Building]) -> RoutingDecision:
    text = simplify(question)
    building_code = _detect_building(text, buildings)
    category = _detect_category(text)
    keyword = _detect_keyword(text)
    period = _detect_period(text)

    tool: ToolName
    if any(marker in text for marker in _DOCUMENT_MARKERS):
        tool = "document_search"
    elif "suivi" in text:
        tool = "follow_up_list"
    elif "recurr" in text or "repet" in text:
        tool = "recurring_equipment"
    elif "combien" in text and any(w in text for w in ("intervention", "panne", "incident")):
        tool = "interventions_count"
    elif "batiment" in text and not building_code and any(w in text for w in ("le plus", "plus de", "classement")):
        tool = "building_ranking"
    elif "equipement" in text and any(w in text for w in ("le plus", "plus de panne", "plus souvent", "plus d'")):
        tool = "top_failing_equipment"
    elif any(w in text for w in ("probleme", "panne", "incident", "defaut", "historique", "intervention")) and (
        building_code or keyword or category
    ):
        tool = "equipment_issues"
    else:
        tool = "document_search"
    return RoutingDecision(
        tool=tool,
        building_code=building_code,
        category=category,
        equipment_keyword=keyword,
        period=period,
        router="rules",
    )


ROUTER_SYSTEM_PROMPT = """Tu es le routeur d'un assistant de maintenance de bâtiments. Tu choisis UNE fonction \
prédéfinie pour répondre à la question et tu extrais ses paramètres. Tu ne réponds pas à la question.
Utilise null pour tout paramètre non mentionné explicitement. N'invente pas de code bâtiment."""


def route_with_llm(question: str, buildings: list[Building], client: LLMClient) -> RoutingDecision:
    tools = "\n".join(f"- {name} : {description}" for name, description in TOOL_DESCRIPTIONS.items())
    building_list = "\n".join(f"- {b.code} : {b.name}" for b in buildings)
    prompt = (
        f"Fonctions disponibles :\n{tools}\n\nBâtiments connus :\n{building_list}\n\n"
        f"Catégories d'équipement : {', '.join(EQUIPMENT_CATEGORIES)}\n"
        "Périodes : all, this_month, last_month, last_30_days, this_year, this_week\n\n"
        f"Question : {question}"
    )
    routing = client.generate_json(prompt, GeminiRouting, ROUTER_SYSTEM_PROMPT)
    known_codes = {b.code for b in buildings}
    return RoutingDecision(
        tool=routing.tool,
        building_code=routing.building_code if routing.building_code in known_codes else None,
        category=normalize_category(routing.category),
        equipment_keyword=routing.equipment_keyword,
        period=routing.period,
        router=llm_label(client),
    )


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)


def _scope(routing: RoutingDecision, buildings: dict[str, str]) -> str:
    parts = []
    if routing.building_code:
        parts.append(f"pour {buildings.get(routing.building_code, routing.building_code)}")
    if routing.category:
        parts.append(f"(catégorie {routing.category})")
    return (" " + " ".join(parts)) if parts else ""


def answer_question(
    db: Session, question: str, settings: Settings, client: LLMClient | None, today: date | None = None
) -> AskResponse:
    today = today or date.today()
    buildings = list_buildings(db)
    building_names = {b.code: b.name for b in buildings}

    routing = route_with_rules(question, buildings)
    if client is not None:
        try:
            routing = route_with_llm(question, buildings, client)
        except LLMError as exc:
            logger.warning("LLM routing failed, using rules", extra={"error": str(exc)})

    tool = routing.tool
    engine = f"routage : {routing.router} · réponse : calcul sur la base de données"
    scope = _scope(routing, building_names)

    if tool == "top_failing_equipment":
        rows, label = analytics.top_failing_equipment(db, settings, today, routing.period, routing.building_code,
                                                      routing.category)
        if not rows:
            return AskResponse(answer=f"Aucune intervention enregistrée {label}{scope}.", mode="analytics",
                               tool=tool, routing=routing, engine=engine)
        lines = [
            f"{r['Équipement']} ({r['Bâtiment']}) : {r['Interventions']} intervention(s)"
            + (" - incidents récurrents" if r["Incidents récurrents"] == "Oui" else "")
            for r in rows[:3]
        ]
        answer = f"Équipements ayant fait l'objet du plus grand nombre d'interventions {label}{scope} :\n{_bullets(lines)}"
        return AskResponse(answer=answer, mode="analytics", tool=tool, routing=routing, engine=engine, data=rows)

    if tool == "interventions_count":
        counts, label = analytics.interventions_count(db, today, routing.period, routing.building_code,
                                                      routing.category)
        answer = (
            f"{counts['total']} intervention(s) enregistrée(s) {label}{scope} : {counts['Terminée']} terminée(s), "
            f"{counts['En cours']} en cours et {counts['En attente']} en attente."
        )
        data = [{"Statut": key, "Interventions": value} for key, value in counts.items() if key != "total"]
        return AskResponse(answer=answer, mode="analytics", tool=tool, routing=routing, engine=engine, data=data)

    if tool == "building_ranking":
        rows, label = analytics.building_ranking(db, today, routing.period)
        if not rows:
            return AskResponse(answer=f"Aucune intervention enregistrée {label}.", mode="analytics", tool=tool,
                               routing=routing, engine=engine)
        lines = [
            f"{r['Bâtiment']} : {r['Interventions']} intervention(s), {r['Non terminées']} non terminée(s), "
            f"{r['Suivis ouverts']} suivi(s) ouvert(s)"
            for r in rows[:3]
        ]
        answer = f"Bâtiments ayant nécessité le plus d'interventions {label} :\n{_bullets(lines)}"
        return AskResponse(answer=answer, mode="analytics", tool=tool, routing=routing, engine=engine, data=rows)

    if tool == "follow_up_list":
        rows = analytics.follow_up_list(db, routing.building_code)
        if not rows:
            answer = f"Aucune intervention ne nécessite de suivi ouvert{scope}."
        else:
            lines = [f"{r['Référence']} ({r['Date']}) - {r['Équipement']}, {r['Bâtiment']} : {r['Statut']}" for r in rows[:6]]
            more = f"\n… et {len(rows) - 6} autre(s)." if len(rows) > 6 else ""
            answer = f"{len(rows)} intervention(s) nécessitent un suivi non clôturé{scope} :\n{_bullets(lines)}{more}"
        return AskResponse(answer=answer, mode="analytics", tool=tool, routing=routing, engine=engine, data=rows)

    if tool == "equipment_issues":
        rows = analytics.equipment_issues(db, routing.building_code, routing.equipment_keyword, routing.category)
        subject = routing.equipment_keyword or routing.category or "les équipements"
        where = f" ({building_names.get(routing.building_code, routing.building_code)})" if routing.building_code else ""
        if not rows:
            answer = f"Aucune intervention enregistrée concernant {subject}{where}."
        else:
            lines = [f"{r['Date']} - {r['Équipement']} : {r['Problème']} ({r['Statut']})" for r in rows[:6]]
            more = f"\n… et {len(rows) - 6} autre(s)." if len(rows) > 6 else ""
            answer = f"{len(rows)} intervention(s) concernant {subject}{where} :\n{_bullets(lines)}{more}"
        return AskResponse(answer=answer, mode="analytics", tool=tool, routing=routing, engine=engine, data=rows)

    if tool == "recurring_equipment":
        rows = analytics.recurring_equipment(db, settings)
        rule = f"au moins {settings.recurrence_threshold} interventions sur {settings.recurrence_window_days} jours"
        if not rows:
            answer = f"Aucun équipement ne présente d'incidents récurrents ({rule})."
        else:
            lines = [f"{r['Équipement']} ({r['Bâtiment']}) : {r['Interventions dans la fenêtre']} interventions, {r['Période']}"
                     for r in rows]
            answer = f"Équipements présentant des incidents récurrents ({rule}) :\n{_bullets(lines)}"
        return AskResponse(answer=answer, mode="analytics", tool=tool, routing=routing, engine=engine, data=rows)

    if tool == "document_search":
        rag = get_rag_service().answer(question, client)
        sources = [
            SourceReference(
                document_id=hit.document_id,
                title=hit.title,
                page=hit.page,
                section=hit.section,
                score=hit.score,
                excerpt=hit.text[:600],
            )
            for hit in rag.sources
        ]
        return AskResponse(
            answer=rag.answer,
            mode="documents" if rag.supported else "unsupported",
            tool=tool,
            routing=routing,
            engine=f"routage : {routing.router} · réponse : {rag.engine} (RAG)",
            sources=sources if rag.supported else [],
            disclaimer=SAFETY_DISCLAIMER if rag.supported else None,
        )

    return AskResponse(answer=UNSUPPORTED_ANSWER, mode="unsupported", tool="unsupported", routing=routing,
                       engine=f"routage : {routing.router}")
