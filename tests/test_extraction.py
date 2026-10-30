from __future__ import annotations

from datetime import date

from backend.config import Settings
from backend.domain import InterventionStatus
from backend.schemas.extraction import ExtractionResult
from backend.services.extraction_service import RuleBasedExtractor, grounding_report, run_extraction
from backend.services.gemini_service import LLMError
from backend.services.summary_service import SummaryInput, generate_summary
from tests.conftest import FakeLLM

STRUCTURED_REPORT = """RAPPORT D'INTERVENTION
N° d'intervention : RI-2026-2001
Date d'intervention : 03/10/2026
Site / Bâtiment : Bâtiment B - Centre de soins Les Tilleuls
Équipement : GE-B01 - Groupe électrogène de secours
Catégorie : Électricité
Technicien : Sophie Lambert
Statut de l'intervention : Terminée
Suivi nécessaire : Non
Description du problème :
Échec de démarrage lors de l'essai mensuel.
Actions réalisées :
Remplacement de la batterie de démarrage.
Signature du technicien : ________
"""

GEMINI_PAYLOAD = {
    "fields": {
        "intervention_id": "RI-2026-2001",
        "date": "2026-10-03",
        "building": "Bâtiment B - Centre de soins Les Tilleuls",
        "equipment_id": "GE-B01",
        "equipment_name": "Groupe électrogène de secours",
        "equipment_category": "Électricité",
        "technician": "Sophie Lambert",
        "problem_description": "Échec de démarrage lors de l'essai mensuel.",
        "actions_performed": "Remplacement de la batterie de démarrage.",
        "status": "Terminée",
        "follow_up_required": False,
        "recommendations": None,
    },
    "ai_suggestions": ["Vérifier l'état de charge de la batterie lors du prochain essai."],
}


def test_rule_extractor_reads_labelled_fields_and_stops_at_signature() -> None:
    result = RuleBasedExtractor().extract(STRUCTURED_REPORT)
    assert result.intervention_id == "RI-2026-2001"
    assert result.date == date(2026, 10, 3)
    assert result.equipment_id == "GE-B01"
    assert result.equipment_name == "Groupe électrogène de secours"
    assert result.equipment_category == "Électricité"
    assert result.status == InterventionStatus.TERMINEE
    assert result.follow_up_required is False
    assert result.actions_performed == "Remplacement de la batterie de démarrage."
    assert result.recommendations is None  # absent from the document: never invented


def test_rule_extractor_does_not_guess_unlabelled_fields() -> None:
    narrative = "Le 21 octobre 2026, Sophie Lambert est intervenue sur TD-C01 au Bâtiment C. Référence : RI-2026-1043"
    result = RuleBasedExtractor().extract(narrative)
    assert result.intervention_id == "RI-2026-1043"
    assert result.equipment_id == "TD-C01"
    assert result.building == "Bâtiment C"
    assert result.technician is None
    assert result.status is None
    assert result.follow_up_required is None


def test_extraction_schema_normalises_values_and_nulls_placeholders() -> None:
    result = ExtractionResult.model_validate(
        {
            "intervention_id": " ri-2026-3000 ",
            "date": "1er octobre 2026",
            "technician": "Inconnu",
            "status": "clôturée",
            "equipment_category": "Climatisation",
            "follow_up_required": "Oui, à planifier",
            "recommendations": "   ",
            "unexpected_field": "ignored",
        }
    )
    assert result.intervention_id == "RI-2026-3000"
    assert result.date == date(2026, 10, 1)
    assert result.technician is None
    assert result.status == InterventionStatus.TERMINEE
    assert result.equipment_category == "CVC"
    assert result.follow_up_required is True
    assert result.recommendations is None
    assert "technician" in result.missing_fields()


def test_invalid_values_become_null_instead_of_failing() -> None:
    result = ExtractionResult.model_validate({"date": "31/02/2026", "status": "peut-être", "follow_up_required": "?"})
    assert result.date is None
    assert result.status is None
    assert result.follow_up_required is None


def test_gemini_extraction_is_validated_and_keeps_suggestions_separate(settings: Settings) -> None:
    llm = FakeLLM([GEMINI_PAYLOAD])
    outcome = run_extraction(STRUCTURED_REPORT, llm, settings)
    assert outcome.engine == "gemini:fake-gemini"
    assert outcome.result.status == InterventionStatus.TERMINEE
    assert outcome.suggestions == ["Vérifier l'état de charge de la batterie lors du prochain essai."]
    assert outcome.result.recommendations is None
    assert "<document>" in llm.prompts[0]


def test_gemini_failure_falls_back_to_rules_with_visible_note(settings: Settings) -> None:
    outcome = run_extraction(STRUCTURED_REPORT, FakeLLM([LLMError("quota dépassé")]), settings)
    assert outcome.engine == "rules"
    assert "quota dépassé" in (outcome.note or "")
    assert outcome.result.intervention_id == "RI-2026-2001"


def test_demo_mode_uses_rules_and_says_so(settings: Settings) -> None:
    outcome = run_extraction(STRUCTURED_REPORT, None, settings)
    assert outcome.engine == "rules"
    assert "Mode démo" in (outcome.note or "")


def test_grounding_flags_values_not_found_in_the_source() -> None:
    result = ExtractionResult.model_validate(
        {**GEMINI_PAYLOAD["fields"], "technician": "Jean Dupont", "equipment_id": "XYZ-Z99"}
    )
    report = grounding_report(result, STRUCTURED_REPORT)
    assert report["intervention_id"] == "found"
    assert report["date"] == "found"
    assert report["technician"] == "check"
    assert report["equipment_id"] == "check"
    assert report["recommendations"] == "missing"


def test_summary_separates_facts_from_suggestions_and_never_claims_resolution() -> None:
    data = SummaryInput.from_extraction(
        ExtractionResult.model_validate({**GEMINI_PAYLOAD["fields"], "status": "En cours", "follow_up_required": True})
    )
    summary, engine = generate_summary(data, None, ["Prévoir un contrôle."], ["recommendations"])
    assert engine == "template"
    assert summary.index("**Faits documentés**") < summary.index("**Suggestions générées par IA")
    assert "n'est pas confirmée" in summary
    assert "Un suivi est requis." in summary
    assert "Informations absentes du document" in summary
