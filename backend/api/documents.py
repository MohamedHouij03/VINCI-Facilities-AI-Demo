from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from backend.api.deps import require_api_key, settings_dependency
from backend.config import Settings
from backend.database import get_db
from backend.schemas.documents import DocumentRead, SearchResponse
from backend.services import document_service
from backend.services.errors import InvalidInputError
from backend.services.rag_service import get_rag_service

router = APIRouter(prefix="/api/documents", tags=["documents"], dependencies=[Depends(require_api_key)])


@router.get("", response_model=list[DocumentRead])
def list_documents(db: Session = Depends(get_db)):
    return document_service.list_documents(db)


@router.post("", response_model=DocumentRead, status_code=201)
async def upload_document(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
):
    if file.content_type not in ("application/pdf", "application/x-pdf", "application/octet-stream"):
        raise InvalidInputError("Seuls les fichiers PDF sont acceptés.")
    data = await file.read(settings.max_upload_bytes + 1)
    document = document_service.register_document(db, data, file.filename, settings)
    background.add_task(document_service.index_document, document.id, settings)
    return document


@router.get("/search", response_model=SearchResponse)
def search_documents(q: str = Query(min_length=3, max_length=300), top_k: int = Query(default=5, ge=1, le=10)):
    rag = get_rag_service()
    hits = rag.search(q, top_k)
    return SearchResponse(query=q, embedding_backend=rag.embedder_status[1], hits=hits)


@router.post("/{document_id}/reindex", response_model=DocumentRead)
def reindex_document(
    document_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(settings_dependency),
):
    document = document_service.mark_for_reindex(db, document_id)
    background.add_task(document_service.index_document, document.id, settings)
    return document


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: int, db: Session = Depends(get_db), settings: Settings = Depends(settings_dependency)):
    document_service.delete_document(db, document_id, settings)
