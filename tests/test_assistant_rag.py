"""RAG retrieval and assistant routing (structured analytics vs documents)."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.database import session_scope
from backend.services.assistant_service import answer_question, route_with_rules
from backend.services.document_service import index_pending_documents
from backend.services.intervention_service import list_buildings
from backend.services.rag_service import HashingEmbedder, RagService, chunk_pages, get_rag_service
from tests.conftest import FakeLLM

EXAMPLES = {
    "Quels équipements présentent le plus de pannes ?": "top_failing_equipment",
    "Combien d'interventions ont été réalisées ce mois-ci ?": "interventions_count",
    "Quels bâtiments nécessitent le plus de maintenance ?": "building_ranking",
    "Quelles interventions nécessitent un suivi ?": "follow_up_list",
    "Quels problèmes ont été rencontrés sur la climatisation du bâtiment A ?": "equipment_issues",
    "Que recommande le manuel technique concernant les vibrations anormales ?": "document_search",
    "Quels équipements ont des incidents récurrents ?": "recurring_equipment",
}


def test_chunking_keeps_page_numbers_and_sections() -> None:
    pages = [
        (1, ["4. Diagnostic des vibrations", "Paragraphe " * 60, "Second paragraphe " * 40]),
        (2, ["Suite du chapitre sur la page deux."]),
    ]
    chunks = chunk_pages(pages, chunk_size=400, overlap=50)
    assert {c.page for c in chunks} == {1, 2}
    assert chunks[0].section == "4. Diagnostic des vibrations"
    assert chunks[-1].section == "4. Diagnostic des vibrations"  # section carries over to the next page
    assert all(len(c.text) <= 400 * 1.5 + 50 for c in chunks)


def test_vector_store_index_search_and_delete(settings: Settings) -> None:
    rag = RagService(settings, HashingEmbedder())
    rag.index_document(1, "Manuel CTA", [(3, ["Remplacer les roulements en cas de vibration persistante."])])
    rag.index_document(2, "Guide électrique", [(1, ["Mesure d'isolement et sectionnement des circuits."])])
    hits = rag.search("vibration persistante des roulements", top_k=2)
    assert hits[0].document_id == 1 and hits[0].page == 3
    rag.delete_document(1)
    assert all(hit.document_id != 1 for hit in rag.search("vibration roulements", top_k=2))
    assert rag.indexed_document_ids() == {2}


@pytest.mark.parametrize(("question", "tool"), EXAMPLES.items())
def test_rule_router_on_reference_questions(client: TestClient, question: str, tool: str) -> None:
    with session_scope() as db:
        routing = route_with_rules(question, list_buildings(db))
    assert routing.tool == tool
    if "bâtiment A" in question:
        assert routing.building_code == "BAT-A"
        assert routing.equipment_keyword == "climatisation"


def test_count_this_month_uses_the_database(client: TestClient, settings: Settings) -> None:
    with session_scope() as db:
        response = answer_question(db, "Combien d'interventions ont été réalisées ce mois-ci ?", settings, None,
                                   today=date(2026, 10, 29))
    assert response.mode == "analytics"
    assert response.answer.startswith("8 intervention(s) enregistrée(s) en octobre 2026")


def test_climatisation_question_returns_matching_records(client: TestClient) -> None:
    body = client.post(
        "/api/assistant/ask", json={"question": "Quels problèmes ont été rencontrés sur la climatisation du bâtiment A ?"}
    ).json()
    assert body["tool"] == "equipment_issues"
    assert body["data"] and all("GF-A01" in row["Équipement"] for row in body["data"])


def test_document_question_returns_sources_with_pages(client: TestClient, settings: Settings) -> None:
    index_pending_documents(settings)
    body = client.post(
        "/api/assistant/ask", json={"question": "Que recommande le manuel technique concernant les vibrations anormales ?"}
    ).json()
    assert body["mode"] == "documents"
    assert body["sources"][0]["title"].startswith("Manuel de maintenance - Centrales de traitement d'air")
    assert body["sources"][0]["page"] == 2
    assert body["disclaimer"]


def test_unsupported_question_is_rejected_when_retrieval_is_weak(configure) -> None:
    from backend.main import create_app

    settings = configure(rag_min_score_hashing=0.99)
    with TestClient(create_app()) as client:
        client.headers.update({"X-API-Key": "test-api-key"})
        index_pending_documents(settings)
        body = client.post("/api/assistant/ask", json={"question": "Quel est le prix d'un ascenseur neuf ?"}).json()
    assert body["mode"] == "unsupported"
    assert body["sources"] == []
    assert "Je ne trouve pas" in body["answer"]


def test_llm_router_and_grounded_generation(client: TestClient, settings: Settings) -> None:
    index_pending_documents(settings)
    llm = FakeLLM(
        [
            {"tool": "document_search", "period": "all"},
            {"supported": True, "answer": "Remplacer les roulements [S1].", "cited_sources": [1]},
        ]
    )
    with session_scope() as db:
        response = answer_question(db, "Que faire contre les vibrations de la CTA ?", settings, llm)
    assert response.routing.router == "gemini:fake-gemini"
    assert response.answer == "Remplacer les roulements [S1]."
    assert len(response.sources) == 1
    assert "<source" in llm.prompts[1]


def test_llm_router_cannot_invent_a_building(client: TestClient, settings: Settings) -> None:
    llm = FakeLLM([{"tool": "follow_up_list", "building_code": "BAT-Z", "period": "all"}])
    with session_scope() as db:
        response = answer_question(db, "Quels suivis pour le bâtiment Z ?", settings, llm)
    assert response.routing.building_code is None


def test_document_library_upload_search_and_delete(client: TestClient) -> None:
    from tests.conftest import sample_report

    data = sample_report("RI-2026-1042").read_bytes()
    created = client.post("/api/documents", files={"file": ("note_fuite.pdf", data, "application/pdf")})
    assert created.status_code == 201
    document_id = created.json()["id"]
    assert client.post("/api/documents", files={"file": ("copie.pdf", data, "application/pdf")}).status_code == 409

    documents = {d["id"]: d for d in client.get("/api/documents").json()}
    assert documents[document_id]["status"] == "indexed"
    hits = client.get("/api/documents/search", params={"q": "vanne d'isolement du départ nord"}).json()["hits"]
    assert hits[0]["document_id"] == document_id

    assert client.delete(f"/api/documents/{document_id}").status_code == 204
    assert document_id not in get_rag_service().indexed_document_ids()
