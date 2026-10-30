"""Create the database schema, optionally resetting all application data.

Usage:  python scripts/init_db.py [--reset]
--reset deletes the SQLite tables, uploaded files and the vector index before recreating the schema.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import get_settings  # noqa: E402
from backend.database import init_db  # noqa: E402
from backend.database.session import drop_db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="drop all data before creating the schema")
    args = parser.parse_args()
    settings = get_settings()
    settings.ensure_directories()
    if args.reset:
        drop_db()
        for directory in (settings.uploads_dir, settings.documents_dir, settings.chroma_dir):
            shutil.rmtree(directory, ignore_errors=True)
        settings.ensure_directories()
        print("All application data removed.")
    init_db()
    print(f"Schema ready: {settings.resolved_database_url}")


if __name__ == "__main__":
    main()
