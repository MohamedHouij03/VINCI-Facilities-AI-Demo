"""PDF validation and text extraction (PyMuPDF), with Tesseract OCR for scanned pages."""

from __future__ import annotations

import logging
import os
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pymupdf

from backend.config import PROJECT_ROOT, Settings

logger = logging.getLogger(__name__)


class PdfValidationError(ValueError):
    """The uploaded file is not a PDF we can process (message is shown to the user)."""


@dataclass(frozen=True)
class PageText:
    number: int
    text: str
    method: str  # "text", "ocr" or "empty"


@dataclass
class PdfExtraction:
    pages: list[PageText]
    ocr_unavailable_pages: list[int] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def method(self) -> str:
        methods = {page.method for page in self.pages if page.method != "empty"}
        if not methods:
            return "empty"
        return methods.pop() if len(methods) == 1 else "mixed"

    @property
    def text(self) -> str:
        return "\n\n".join(page.text.strip() for page in self.pages if page.text.strip())

    @property
    def text_with_page_markers(self) -> str:
        return "\n\n".join(f"--- Page {page.number} ---\n{page.text.strip()}" for page in self.pages)


def validate_pdf_bytes(data: bytes, max_bytes: int) -> None:
    if not data:
        raise PdfValidationError("Le fichier est vide.")
    if len(data) > max_bytes:
        raise PdfValidationError(f"Le fichier dépasse la taille maximale autorisée ({max_bytes // (1024 * 1024)} Mo).")
    if b"%PDF-" not in data[:1024]:
        raise PdfValidationError("Le fichier n'est pas un PDF valide.")


def open_pdf(data: bytes, max_pages: int) -> pymupdf.Document:
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # PyMuPDF raises several exception types for corrupt files
        raise PdfValidationError("Le PDF est illisible ou corrompu.") from exc
    if document.needs_pass:
        document.close()
        raise PdfValidationError("Le PDF est protégé par un mot de passe.")
    if document.page_count == 0:
        document.close()
        raise PdfValidationError("Le PDF ne contient aucune page.")
    if document.page_count > max_pages:
        document.close()
        raise PdfValidationError(f"Le PDF dépasse le nombre maximal de pages ({max_pages}).")
    return document


@lru_cache
def resolve_tessdata(configured_dir: str, language: str) -> str | None:
    """Locate a tessdata directory containing the OCR language file, if any."""
    candidates = [configured_dir, os.environ.get("TESSDATA_PREFIX", ""), str(PROJECT_ROOT / "data" / "tessdata")]
    for candidate in candidates:
        if candidate and (Path(candidate) / f"{language}.traineddata").is_file():
            return candidate
    try:
        detected = pymupdf.get_tessdata()
    except Exception:  # raised when Tesseract is not installed
        return None
    if detected and (Path(detected) / f"{language}.traineddata").is_file():
        return detected
    return None


def ocr_available(settings: Settings) -> bool:
    return resolve_tessdata(settings.tessdata_dir, settings.ocr_language) is not None


def _normalize(text: str) -> str:
    """NFKC turns typographic ligatures (ﬁ, ﬂ) and non-breaking spaces into plain characters."""
    return unicodedata.normalize("NFKC", text)


def _ocr_page(page: pymupdf.Page, settings: Settings, tessdata: str) -> str:
    textpage = page.get_textpage_ocr(language=settings.ocr_language, dpi=300, full=True, tessdata=tessdata)
    return _normalize(page.get_text(textpage=textpage))


def extract_pdf_text(data: bytes, settings: Settings) -> PdfExtraction:
    """Extract text page by page; pages without a text layer go through OCR when available."""
    document = open_pdf(data, settings.max_pdf_pages)
    tessdata = resolve_tessdata(settings.tessdata_dir, settings.ocr_language)
    pages: list[PageText] = []
    ocr_unavailable: list[int] = []
    try:
        for index, page in enumerate(document, start=1):
            text = _normalize(page.get_text("text"))
            if len(text.strip()) >= settings.ocr_min_chars_per_page:
                pages.append(PageText(index, text, "text"))
                continue
            if tessdata is None:
                ocr_unavailable.append(index)
                pages.append(PageText(index, text, "text" if text.strip() else "empty"))
                continue
            try:
                ocr_text = _ocr_page(page, settings, tessdata)
            except Exception:
                logger.exception("OCR failed", extra={"page": index})
                ocr_unavailable.append(index)
                pages.append(PageText(index, text, "text" if text.strip() else "empty"))
                continue
            pages.append(PageText(index, ocr_text, "ocr" if ocr_text.strip() else "empty"))
    finally:
        document.close()
    return PdfExtraction(pages=pages, ocr_unavailable_pages=ocr_unavailable)


def extract_page_blocks(data: bytes, settings: Settings) -> list[tuple[int, list[str]]]:
    """Return text blocks (paragraphs) per page, skipping running headers and footers.

    Used for RAG chunking. Scanned pages fall back to OCR text split on blank lines.
    """
    document = open_pdf(data, settings.max_pdf_pages)
    tessdata = resolve_tessdata(settings.tessdata_dir, settings.ocr_language)
    result: list[tuple[int, list[str]]] = []
    try:
        for index, page in enumerate(document, start=1):
            height = page.rect.height
            margin = height * 0.06
            blocks = [
                _normalize(block[4]).strip()
                for block in page.get_text("blocks", sort=True)
                if block[6] == 0 and block[4].strip() and block[1] > margin and block[3] < height - margin
            ]
            if sum(len(block) for block in blocks) < settings.ocr_min_chars_per_page and tessdata:
                ocr_text = _ocr_page(page, settings, tessdata)
                blocks = [part.strip() for part in ocr_text.split("\n\n") if part.strip()]
            result.append((index, blocks))
    finally:
        document.close()
    return result
