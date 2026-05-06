from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd


SUPPORTED_TECHNICAL_DATA_SUFFIXES = {".xlsx", ".xlsm"}
KNOWN_SECTION_KEYS = {
    "technical",
    "technical data",
    "performance",
    "performance data",
    "electrical",
    "electrical data",
    "mechanical",
    "mechanical data",
}


@dataclass
class TechnicalDataEntry:
    label: str
    value: str
    section: str = "Technical Data"
    canonical_key: str = ""
    source: str = "excel"


class TechnicalDataError(ValueError):
    """Raised when a Technical Data source cannot be parsed safely."""


class TechnicalDataSource(Protocol):
    source_type: str
    display_name: str

    def prepare_workbook(self) -> Path:
        ...


@dataclass(frozen=True)
class LocalTechnicalDataSource:
    path: Path
    source_type: str = "local_workbook"
    display_name: str = "Local workbook"

    def prepare_workbook(self) -> Path:
        path = self.path.resolve()
        validate_technical_data_file(path)
        return path


@dataclass(frozen=True)
class GoogleSheetTechnicalDataSource:
    url: str
    cache_path: Path
    downloader: object
    source_type: str = "google_sheet"
    display_name: str = "Google Sheet"

    def prepare_workbook(self) -> Path:
        output = self.cache_path.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        downloader = self.downloader
        if not callable(downloader):
            raise TechnicalDataError("Google Sheet source requires a callable downloader.")
        prepared = downloader(self.url, output)
        path = Path(prepared if prepared is not None else output).resolve()
        validate_technical_data_file(path)
        return path


def _format_cell(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return str(int(value))
        return f"{value:g}"
    return str(value).strip()


def _normalize_header(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").strip().lower()).strip()


def normalize_table_section(value: object) -> str:
    key = _normalize_header(value)
    if key in {"performance", "performance data", "electrical", "electrical data"}:
        return "Performance" if "performance" in key else "Electrical Data"
    if key in {"mechanical", "mechanical data"}:
        return "Mechanical Data"
    return "Technical Data"


def normalize_technical_key(value: object) -> str:
    cleaned = re.sub(r"[\u200B-\u200D\uFEFF]", "", str(value or ""))
    return re.sub(r"\s+", " ", cleaned.strip()).lower()


def validate_technical_data_file(path: Path) -> None:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_TECHNICAL_DATA_SUFFIXES:
        if suffix == ".xls":
            raise TechnicalDataError("Legacy .xls Technical Data files are not supported yet. Save the file as .xlsx or .xlsm.")
        raise TechnicalDataError("Technical Data must be a .xlsx or .xlsm workbook.")
    if not path.exists():
        raise TechnicalDataError(f"Technical Data workbook does not exist: {path}")


def _first_non_empty_index(data: pd.DataFrame) -> int:
    for index, row in data.iterrows():
        if any(_format_cell(value) for value in row.tolist()):
            return int(index)
    return 0


def _has_section_column(data: pd.DataFrame, first_index: int) -> tuple[bool, int]:
    if data.shape[1] < 3:
        return False, first_index
    headers = [_normalize_header(value) for value in data.iloc[first_index, :3].tolist()]
    if headers[:3] == ["section", "label", "value"]:
        return True, first_index + 1
    if headers[0] in KNOWN_SECTION_KEYS:
        return True, first_index
    sampled_sections = 0
    sampled_labels = 0
    for _index, row in data.iloc[first_index:, :3].head(25).iterrows():
        section_key = _normalize_header(row.iloc[0])
        label = _format_cell(row.iloc[1])
        if section_key in KNOWN_SECTION_KEYS:
            sampled_sections += 1
        if label:
            sampled_labels += 1
    return sampled_sections > 0 and sampled_labels > 0, first_index


def _wide_table_header_index(data: pd.DataFrame, first_index: int) -> int | None:
    for index in range(first_index, min(first_index + 8, len(data))):
        headers = [_normalize_header(value) for value in data.iloc[index].tolist()]
        non_empty_headers = [header for header in headers if header]
        if len(non_empty_headers) < 3:
            continue
        if headers and headers[0] in KNOWN_SECTION_KEYS:
            continue
        if {"label", "value"}.issubset(set(non_empty_headers)):
            continue
        if "product id" in headers or "sku" in headers or "antenna name" in headers:
            return index
    return None


def _entry_factory(*, section: str, label: str, value: str, canonical_key_factory) -> TechnicalDataEntry:
    return TechnicalDataEntry(
        label=label,
        value=value,
        section=normalize_table_section(section),
        canonical_key=canonical_key_factory(label),
        source="excel",
    )


def _parse_section_or_key_value_rows(data: pd.DataFrame, *, canonical_key_factory) -> list[TechnicalDataEntry]:
    first_index = _first_non_empty_index(data)
    has_section_column, start_index = _has_section_column(data, first_index)
    if data.shape[1] < 2:
        data = data.copy()
        data[1] = ""

    entries: list[TechnicalDataEntry] = []
    index_by_key: dict[tuple[str, str], int] = {}
    for _idx, row in data.iloc[start_index:].iterrows():
        if has_section_column:
            section = normalize_table_section(row.iloc[0])
            label = _format_cell(row.iloc[1])
            value = _format_cell(row.iloc[2] if data.shape[1] > 2 else "")
        else:
            section = "Technical Data"
            label = _format_cell(row.iloc[0])
            value = _format_cell(row.iloc[1] if data.shape[1] > 1 else "")
        key = normalize_technical_key(label)
        if not key:
            continue
        dedupe_key = (normalize_table_section(section), key)
        if dedupe_key in index_by_key:
            entries[index_by_key[dedupe_key]].value = value
            continue
        index_by_key[dedupe_key] = len(entries)
        entries.append(_entry_factory(section=section, label=label, value=value, canonical_key_factory=canonical_key_factory))
    return entries


def _parse_wide_product_table(
    data: pd.DataFrame,
    *,
    header_index: int,
    product_id: str | None,
    canonical_key_factory,
) -> list[TechnicalDataEntry]:
    labels = [_format_cell(value) for value in data.iloc[header_index].tolist()]
    keys = [_normalize_header(label) for label in labels]
    rows = data.iloc[header_index + 1 :].copy()
    rows = rows[rows.apply(lambda row: any(_format_cell(value) for value in row.tolist()), axis=1)]
    if rows.empty:
        raise TechnicalDataError("Wide Technical Data table does not contain any product rows.")

    product_key_indexes = [index for index, key in enumerate(keys) if key in {"product id", "sku"}]
    selected_row = None
    if product_id:
        wanted = normalize_technical_key(product_id)
        for _index, row in rows.iterrows():
            for column_index in product_key_indexes:
                if normalize_technical_key(row.iloc[column_index]) == wanted:
                    selected_row = row
                    break
            if selected_row is not None:
                break
        if selected_row is None:
            raise TechnicalDataError(f"Wide Technical Data table does not contain product '{product_id}'.")
    elif len(rows) == 1:
        selected_row = rows.iloc[0]
    else:
        raise TechnicalDataError("Wide Technical Data table has multiple product rows. Select a product ID.")

    entries: list[TechnicalDataEntry] = []
    for column_index, label in enumerate(labels):
        if not label:
            continue
        value = _format_cell(selected_row.iloc[column_index])
        entries.append(_entry_factory(section="Technical Data", label=label, value=value, canonical_key_factory=canonical_key_factory))
    return entries


def load_technical_data_entries(
    path: Path,
    *,
    sheet_name: str | int | None = None,
    product_id: str | None = None,
    canonical_key_factory=None,
) -> list[TechnicalDataEntry]:
    validate_technical_data_file(path)
    if canonical_key_factory is None:
        canonical_key_factory = normalize_technical_key
    selected_sheet = 0 if sheet_name in {None, ""} else sheet_name
    try:
        data = pd.read_excel(path, sheet_name=selected_sheet, header=None, dtype=object)
    except ValueError as exc:
        raise TechnicalDataError(f"Technical Data workbook is missing sheet '{selected_sheet}'.") from exc
    except Exception as exc:
        raise TechnicalDataError(f"Could not read Technical Data workbook '{path}'.") from exc

    if data.empty:
        raise TechnicalDataError("Technical Data workbook does not contain any rows.")
    first_index = _first_non_empty_index(data)
    wide_header_index = _wide_table_header_index(data, first_index)
    if wide_header_index is not None:
        entries = _parse_wide_product_table(
            data,
            header_index=wide_header_index,
            product_id=product_id,
            canonical_key_factory=canonical_key_factory,
        )
    else:
        entries = _parse_section_or_key_value_rows(data, canonical_key_factory=canonical_key_factory)
    if not entries:
        raise TechnicalDataError("Technical Data workbook does not contain any field/value rows.")
    empty_labels = [str(index + 1) for index, entry in enumerate(entries) if not normalize_technical_key(entry.label)]
    if empty_labels:
        raise TechnicalDataError(f"Technical Data contains rows with missing labels: {', '.join(empty_labels[:5])}")
    return entries
