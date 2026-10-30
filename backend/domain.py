"""Business vocabulary shared by the API, the services and the sample-data generator."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from enum import StrEnum


class InterventionStatus(StrEnum):
    EN_ATTENTE = "en_attente"
    EN_COURS = "en_cours"
    TERMINEE = "terminee"


STATUS_LABELS: dict[str, str] = {
    InterventionStatus.EN_ATTENTE: "En attente",
    InterventionStatus.EN_COURS: "En cours",
    InterventionStatus.TERMINEE: "Terminée",
}

EQUIPMENT_CATEGORIES: tuple[str, ...] = (
    "CVC",
    "Électricité",
    "Plomberie",
    "Sécurité incendie",
    "Ascenseurs",
    "Autre",
)


class JobStatus(StrEnum):
    UPLOADED = "uploaded"
    QUEUED = "queued"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    FAILED = "failed"


# A job can be (re)claimed for processing only from these states.
CLAIMABLE_JOB_STATUSES = (JobStatus.UPLOADED, JobStatus.QUEUED, JobStatus.FAILED)


class NotificationStatus(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"  # handed to n8n, not yet confirmed
    SENDING = "sending"  # claimed by n8n, email being sent
    SENT = "sent"  # n8n confirmed the email was sent
    FAILED = "failed"
    SIMULATED = "simulated"  # demo mode: nothing was sent
    NOT_CONFIGURED = "not_configured"  # n8n or recipient missing: nothing was sent


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def simplify(value: str) -> str:
    """Lower-case, accent-free, single-spaced version of a string for matching."""
    value = strip_accents(value).lower()
    value = re.sub(r"[’'`]", "'", value)
    return re.sub(r"\s+", " ", value).strip()


_STATUS_SYNONYMS: dict[InterventionStatus, tuple[str, ...]] = {
    InterventionStatus.TERMINEE: ("terminee", "termine", "cloturee", "cloture", "clos", "realisee", "achevee"),
    InterventionStatus.EN_COURS: ("en cours", "en traitement", "partiellement", "non termine"),
    InterventionStatus.EN_ATTENTE: ("en attente", "a planifier", "attente de piece", "non commencee", "planifiee"),
}


def normalize_status(value: str | None) -> InterventionStatus | None:
    if value is None:
        return None
    text = simplify(str(value))
    if not text:
        return None
    for status in InterventionStatus:
        if text == status.value or text == simplify(STATUS_LABELS[status]):
            return status
    # "en attente" must be checked before generic words such as "terminee".
    for status in (InterventionStatus.EN_ATTENTE, InterventionStatus.EN_COURS, InterventionStatus.TERMINEE):
        if any(synonym in text for synonym in _STATUS_SYNONYMS[status]):
            return status
    return None


_CATEGORY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "CVC": ("cvc", "hvac", "climatisation", "ventilation", "chauffage", "genie climatique", "froid"),
    "Électricité": ("electricite", "electrique", "courant fort", "cfo"),
    "Plomberie": ("plomberie", "sanitaire", "hydraulique"),
    "Sécurité incendie": ("securite incendie", "incendie", "ssi", "desenfumage"),
    "Ascenseurs": ("ascenseur", "elevateur", "monte-charge"),
    "Autre": ("autre",),
}


def normalize_category(value: str | None) -> str | None:
    if value is None:
        return None
    text = simplify(str(value))
    if not text:
        return None
    for category in EQUIPMENT_CATEGORIES:
        if text == simplify(category):
            return category
    for category, synonyms in _CATEGORY_SYNONYMS.items():
        if any(synonym in text for synonym in synonyms):
            return category
    return None


_TRUE_WORDS = {"oui", "yes", "true", "vrai", "1", "requis", "necessaire", "o"}
_FALSE_WORDS = {"non", "no", "false", "faux", "0", "aucun", "n"}


def parse_yes_no(value: object) -> bool | None:
    if value is None or isinstance(value, bool):
        return value  # type: ignore[return-value]
    text = simplify(str(value))
    if not text:
        return None
    first_word = re.split(r"[\s,.;:()-]+", text)[0]
    if first_word in _TRUE_WORDS:
        return True
    if first_word in _FALSE_WORDS:
        return False
    return None


def building_letter_code(letter: str) -> str:
    return f"BAT-{letter.upper()}"


FRENCH_MONTHS: dict[str, int] = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}

_NUMERIC_DATE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b")
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_TEXT_DATE = re.compile(r"\b(\d{1,2})(?:er)?\s+([a-z]+)\s+(\d{4})\b")


def parse_french_date(value: object) -> date | None:
    """Parse ISO, dd/mm/yyyy or '28 octobre 2026' formats. Returns None when no valid date is found."""
    if value is None or isinstance(value, date):
        return value  # type: ignore[return-value]
    text = simplify(str(value))
    candidates: list[tuple[int, int, int]] = []
    if match := _ISO_DATE.search(text):
        candidates.append((int(match[1]), int(match[2]), int(match[3])))
    if match := _NUMERIC_DATE.search(text):
        candidates.append((int(match[3]), int(match[2]), int(match[1])))
    if (match := _TEXT_DATE.search(text)) and match[2] in FRENCH_MONTHS:
        candidates.append((int(match[3]), FRENCH_MONTHS[match[2]], int(match[1])))
    for year, month, day in candidates:
        try:
            return date(year, month, day)
        except ValueError:
            continue
    return None
