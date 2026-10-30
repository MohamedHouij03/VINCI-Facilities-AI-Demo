"""Create .env from .env.example and fill the shared secrets with random values.

Existing values are never overwritten. Usage:  python scripts/bootstrap_env.py
"""

from __future__ import annotations

import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED = ("API_KEY", "N8N_WEBHOOK_SECRET", "N8N_API_TOKEN")


def main() -> None:
    target = ROOT / ".env"
    content = target.read_text(encoding="utf-8") if target.exists() else (ROOT / ".env.example").read_text(encoding="utf-8")
    for name in GENERATED:
        pattern = re.compile(rf"^{name}=\s*$", re.MULTILINE)
        if pattern.search(content):
            content = pattern.sub(f"{name}={secrets.token_urlsafe(32)}", content)
            print(f"{name}: generated")
        else:
            print(f"{name}: already set, unchanged")
    target.write_text(content, encoding="utf-8")
    print(f"Configuration written to {target}")


if __name__ == "__main__":
    main()
