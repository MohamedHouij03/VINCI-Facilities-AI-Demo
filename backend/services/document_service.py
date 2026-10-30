"""Technical document library: storage, indexing status and removal."""

from __future__ import annotations

import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.database import session_scope
from backend.models import TechnicalDocument, utcnow
from backend.services.errors import ConflictError, InvalidInputError, NotFoundError
from backend.services.pdf_service import PdfValidationError, extract_page_blocks, open_pdf, validate_pdf_bytes
from backend.services.rag_service import get_rag_service
from backend.services.storage import delete_stored_pdf, read_stored_pdf, safe_display_filename, sha256_bytes, store_pdf

logger = logging.getLogger(__name__)


def _title_from(data: bytes, filename: str, settings: Settings) -> tuple[str, int]:
    document = open_pdf(data, settings.max_pdf_pages)
    try:
        metadata_title = (document.metadata or {}).get("title") or ""
        page_count = document.page_count
    finally:
        document.close()
    fallback = re.sub(r"[_-]+", " ", filename.rsplit(".", 1)[0]).strip().capitalize()
    return (metadata_title.strip() or fallback)[:255], page_count


def register_document(
    db: Session, data: bytes, filename: str | None, settings: Settings, is_sample: bool = False
) -> TechnicalDocument:
    try:
        validate_pdf_bytes(data, settings.max_upload_bytes)
        display_name = safe_display_filename(filename)
        title, page_count = _title_from(data, display_name, settings)
    except PdfValidationError as exc:
        raise InvalidInputError(str(exc)) from exc
    digest = sha256_bytes(data)
    if db.scalars(select(TechnicalDocument).where(TechnicalDocument.sha256 == digest)).first():
        raise ConflictError("Ce document est déjà présent dans la bibliothèque.")
    document = TechnicalDocument(
        title=title,
        original_filename=display_name,
        stored_filename=store_pdf(settings.documents_dir, data),
        sha256=digest,
        file_size=len(data),
        page_count=page_count,
        status="pending",
        is_sample=is_sample,
    )
    db.add(document)
    db.commit()
    return document


def index_document(document_id: int, settings: Settings) -> None:
    """Extract, chunk, embed and store a document. Runs in a background task."""
    with session_scope() as db:
        document = db.get(TechnicalDocument, document_id)
        if document is None:
            return
        try:
            data = read_stored_pdf(settings.documents_dir, document.stored_filename)
            pages = extract_page_blocks(data, settings)
            document.chunk_count = get_rag_service().index_document(document.id, document.title, pages)
            document.status = "indexed"
            document.error_message = None
            document.indexed_at = utcnow()
            logger.info("document indexed", extra={"document_id": document.id, "chunks": document.chunk_count})
        except Exception as exc:
            logger.exception("document indexing failed", extra={"document_id": document_id})
            document.status = "failed"
            document.error_message = str(exc)[:500]


def index_pending_documents(settings: Settings) -> int:
    """Index documents that are pending, or whose vectors are missing (e.g. after an embedding model change)."""
    with session_scope() as db:
        documents = list(db.scalars(select(TechnicalDocument).where(TechnicalDocument.status != "failed")))
        candidates = [(d.id, d.status) for d in documents]
    indexed_ids = get_rag_service().indexed_document_ids() if candidates else set()
    count = 0
    for document_id, status in candidates:
        if status == "pending" or document_id not in indexed_ids:
            index_document(document_id, settings)
            count += 1
    return count


def list_documents(db: Session) -> list[TechnicalDocument]:
    return list(db.scalars(select(TechnicalDocument).order_by(TechnicalDocument.title)))


def get_document(db: Session, document_id: int) -> TechnicalDocument:
    document = db.get(TechnicalDocument, document_id)
    if document is None:
        raise NotFoundError("Document introuvable.")
    return document


def delete_document(db: Session, document_id: int, settings: Settings) -> None:
    document = get_document(db, document_id)
    get_rag_service().delete_document(document.id)
    delete_stored_pdf(settings.documents_dir, document.stored_filename)
    db.delete(document)
    db.commit()


def mark_for_reindex(db: Session, document_id: int) -> TechnicalDocument:
    document = get_document(db, document_id)
    document.status = "pending"
    document.error_message = None
    db.commit()
    return document
