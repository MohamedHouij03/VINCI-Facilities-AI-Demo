"""Load the fictional dataset into the database and index the sample manuals.

Usage:  python scripts/seed_database.py
(The API also does this automatically on startup when SEED_ON_STARTUP=true.)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import get_settings  # noqa: E402
from backend.database import init_db, session_scope  # noqa: E402
from backend.logging_config import configure_logging  # noqa: E402
from backend.services.document_service import index_pending_documents  # noqa: E402
from backend.services.seed_service import register_sample_manuals, seed_reference_data  # noqa: E402


def main() -> None:
    settings = get_settings()
    configure_logging("WARNING")
    settings.ensure_directories()
    init_db()
    with session_scope() as db:
        counts = seed_reference_data(db, settings.sample_data_dir)
        manuals = register_sample_manuals(db, settings)
    if any(counts.values()):
        print(f"Inserted {counts['buildings']} buildings, {counts['equipment']} equipment, "
              f"{counts['interventions']} interventions.")
    else:
        print("Reference data already present: nothing inserted.")
    print(f"Registered {manuals} new manual(s). Indexing (first run downloads the embedding model)...")
    indexed = index_pending_documents(settings)
    print(f"Indexed {indexed} document(s).")


if __name__ == "__main__":
    main()
