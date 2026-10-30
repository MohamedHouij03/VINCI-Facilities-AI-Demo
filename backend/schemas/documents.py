from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    original_filename: str
    file_size: int
    page_count: int | None
    chunk_count: int
    status: str
    error_message: str | None
    is_sample: bool
    created_at: dt.datetime
    indexed_at: dt.datetime | None


class PassageHit(BaseModel):
    document_id: int
    title: str
    page: int | None
    section: str | None
    score: float
    text: str


class SearchResponse(BaseModel):
    query: str
    embedding_backend: str
    hits: list[PassageHit]
