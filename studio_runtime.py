from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from studio_support import is_url

STAGE_DEFINITIONS = [
    ("beam", "Workbook"),
    ("compliance", "Compliance"),
    ("extract", "Extract"),
    ("plot", "Plots"),
    ("vswr", "VSWR"),
    ("datasheet", "Datasheet"),
]
STAGE_LABELS = dict(STAGE_DEFINITIONS)


class GoogleSheetDownloadError(RuntimeError):
    pass


def is_google_sheet_url(value: str | Path | None) -> bool:
    if not is_url(value):
        return False
    parsed = urlparse(str(value).strip())
    return parsed.netloc.lower().endswith("docs.google.com") and "/spreadsheets/" in parsed.path


def extract_google_sheet_id(value: str | Path | None) -> str:
    text = str(value or "").strip()
    match = re.search(r"/spreadsheets/d/([^/?#]+)", text)
    return match.group(1) if match else ""


def google_sheet_export_url(spreadsheet_id: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"


def format_timestamp(value: str | None) -> str:
    if not value:
        return "Never"
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return str(value)
    return stamp.astimezone().strftime("%Y-%m-%d %H:%M")


def clean_run_state(run_state: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(run_state, dict):
        return {}
    cleaned: dict[str, object] = {}
    for key, value in run_state.items():
        if key == "history":
            if isinstance(value, list) and value:
                cleaned[key] = value
        elif key == "stages":
            if isinstance(value, dict):
                stage_map = {
                    stage_key: stage_value
                    for stage_key, stage_value in value.items()
                    if isinstance(stage_value, dict) and stage_value
                }
                if stage_map:
                    cleaned[key] = stage_map
        elif value not in ({}, [], "", None):
            cleaned[key] = value
    return cleaned
