from __future__ import annotations

from pathlib import Path


def evidence_pdf_path(workbook_path: str | Path) -> Path:
    workbook = Path(workbook_path)
    return workbook.with_name(f"{workbook.stem}-evidence.pdf")
