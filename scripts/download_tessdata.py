"""Download the Tesseract French language model used by PyMuPDF's built-in OCR engine.

PyMuPDF ships MuPDF's embedded Tesseract engine: only the language file is needed, no system install.
Usage:  python scripts/download_tessdata.py [--lang fra] [--dest data/tessdata]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx

SOURCE = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{lang}.traineddata"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", default="fra")
    parser.add_argument("--dest", type=Path, default=Path(__file__).resolve().parent.parent / "data" / "tessdata")
    args = parser.parse_args()

    target = args.dest / f"{args.lang}.traineddata"
    if target.is_file():
        print(f"Already present: {target}")
        return
    args.dest.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", SOURCE.format(lang=args.lang), follow_redirects=True, timeout=60) as response:
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)
    print(f"Downloaded {target} ({target.stat().st_size / 1e6:.1f} MB). OCR is now available (TESSDATA_DIR={args.dest}).")


if __name__ == "__main__":
    main()
