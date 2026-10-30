from __future__ import annotations

import pymupdf
import pytest

from backend.config import Settings
from backend.services.pdf_service import (
    PdfValidationError,
    extract_page_blocks,
    extract_pdf_text,
    ocr_available,
    validate_pdf_bytes,
)
from backend.services.storage import resolve_stored_path, safe_display_filename
from tests.conftest import sample_report


def _pdf_with_text(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    return document.tobytes()


def test_validation_rejects_empty_oversized_and_non_pdf_files() -> None:
    with pytest.raises(PdfValidationError, match="vide"):
        validate_pdf_bytes(b"", 1024)
    with pytest.raises(PdfValidationError, match="taille maximale"):
        validate_pdf_bytes(b"%PDF-1.7" + b"0" * 2048, 1024)
    with pytest.raises(PdfValidationError, match="PDF valide"):
        validate_pdf_bytes(b"MZ\x90\x00 not a pdf", 1024)


def test_corrupt_pdf_is_reported_as_validation_error(settings: Settings) -> None:
    with pytest.raises(PdfValidationError, match="illisible"):
        extract_pdf_text(b"%PDF-1.7\n garbage without structure", settings)


def test_text_layer_is_extracted_with_page_markers(settings: Settings) -> None:
    result = extract_pdf_text(_pdf_with_text("Vibration anormale constatée sur la centrale CTA-A01"), settings)
    assert result.method == "text"
    assert result.page_count == 1
    assert "CTA-A01" in result.text
    assert result.text_with_page_markers.startswith("--- Page 1 ---")


def test_page_limit_is_enforced(configure) -> None:
    settings = configure(max_pdf_pages=1)
    document = pymupdf.open()
    document.new_page()
    document.new_page()
    with pytest.raises(PdfValidationError, match="nombre maximal de pages"):
        extract_pdf_text(document.tobytes(), settings)


def test_scanned_report_without_ocr_data_is_flagged(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.services.pdf_service.resolve_tessdata", lambda *_args: None)
    assert not ocr_available(settings)
    result = extract_pdf_text(sample_report("RI-2026-1046").read_bytes(), settings)
    assert result.method == "empty"
    assert result.ocr_unavailable_pages == [1]


def test_scanned_report_goes_through_ocr(settings: Settings) -> None:
    if not ocr_available(settings):
        pytest.skip("French tessdata not installed (python scripts/download_tessdata.py)")
    result = extract_pdf_text(sample_report("RI-2026-1046").read_bytes(), settings)
    assert result.method == "ocr"
    assert "RI-2026-1046" in result.text
    assert "Ascenseur principal" in result.text


def test_page_blocks_skip_running_header_and_footer(settings: Settings) -> None:
    pages = extract_page_blocks(sample_report("RI-2026-1041").read_bytes(), settings)
    all_blocks = " ".join(block for _, blocks in pages for block in blocks)
    assert "Vibration anormale" in all_blocks
    assert "Document fictif" not in all_blocks


def test_storage_paths_cannot_escape_the_storage_directory(tmp_path) -> None:
    with pytest.raises(ValueError):
        resolve_stored_path(tmp_path, "../../etc/passwd")
    with pytest.raises(ValueError):
        resolve_stored_path(tmp_path, "report.pdf")
    assert safe_display_filename("C:\\Users\\x\\..\\rapport<1>.pdf") == "rapport1.pdf"
    assert safe_display_filename("../../secret.pdf") == "secret.pdf"
