"""File storage helpers. Uploaded files are stored under random names, never under user-supplied paths."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

_STORED_NAME = re.compile(r"^[0-9a-f]{32}\.pdf$")
_UNSAFE_CHARS = re.compile(r"[\x00-\x1f<>:\"|?*]")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_display_filename(filename: str | None, default: str = "document.pdf") -> str:
    """Keep only the base name of a client-provided filename, for display purposes."""
    if not filename:
        return default
    name = re.split(r"[\\/]", filename)[-1]
    name = _UNSAFE_CHARS.sub("", name).strip(" .")
    return name[:255] or default


def resolve_stored_path(directory: Path, stored_filename: str) -> Path:
    if not _STORED_NAME.fullmatch(stored_filename):
        raise ValueError(f"Invalid stored filename: {stored_filename!r}")
    base = directory.resolve()
    path = (base / stored_filename).resolve()
    if not path.is_relative_to(base):
        raise ValueError("Resolved path escapes the storage directory")
    return path


def store_pdf(directory: Path, data: bytes) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{uuid.uuid4().hex}.pdf"
    resolve_stored_path(directory, stored_filename).write_bytes(data)
    return stored_filename


def read_stored_pdf(directory: Path, stored_filename: str) -> bytes:
    return resolve_stored_path(directory, stored_filename).read_bytes()


def delete_stored_pdf(directory: Path, stored_filename: str) -> None:
    resolve_stored_path(directory, stored_filename).unlink(missing_ok=True)
