"""Inspect external textbook PDFs without copying them into the repository."""

from __future__ import annotations

import argparse
from pathlib import Path

from pypdf import PdfReader


def inspect_textbooks(textbook_dir: Path) -> None:
    pdfs = sorted(textbook_dir.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs found under {textbook_dir}")

    for path in pdfs:
        reader = PdfReader(str(path))
        size_mb = path.stat().st_size / 1024 / 1024
        print(f"{path.name}\tpages={len(reader.pages)}\tsize_mb={size_mb:.1f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--textbook-dir", default="../textbooks")
    args = parser.parse_args()
    inspect_textbooks(Path(args.textbook_dir))


if __name__ == "__main__":
    main()
