from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ToolName = Literal[
    "top_failing_equipment",
    "interventions_count",
    "building_ranking",
    "follow_up_list",
    "equipment_issues",
    "recurring_equipment",
    "document_search",
    "unsupported",
]

PeriodCode = Literal["all", "this_month", "last_month", "last_30_days", "this_year", "this_week"]


class RoutingDecision(BaseModel):
    """Which predefined function answers a question. The LLM never writes SQL."""

    tool: ToolName
    building_code: str | None = Field(None, description="Code bâtiment, ex. BAT-A, si mentionné.")
    category: str | None = Field(None, description="Catégorie d'équipement si mentionnée.")
    equipment_keyword: str | None = Field(None, description="Mot-clé d'équipement, ex. climatisation.")
    period: PeriodCode = "all"
    router: str = "rules"


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class SourceReference(BaseModel):
    document_id: int
    title: str
    page: int | None
    section: str | None
    score: float
    excerpt: str


class AskResponse(BaseModel):
    answer: str
    mode: Literal["analytics", "documents", "unsupported"]
    tool: ToolName
    routing: RoutingDecision
    engine: str
    data: list[dict[str, Any]] = []
    sources: list[SourceReference] = []
    disclaimer: str | None = None
