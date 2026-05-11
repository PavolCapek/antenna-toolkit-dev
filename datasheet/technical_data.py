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
    raw = _format_cell(value)
    if key in {"performance", "performance data", "electrical", "electrical data"}:
        return "Performance" if "performance" in key else "Electrical Data"
    if key in {"mechanical", "mechanical data"}:
        return "Mechanical Data"
    if raw:
        return " ".join(part.capitalize() for part in re.split(r"\s+", raw.strip()) if part)
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


def _as_float(value: object) -> float | None:
    text = _format_cell(value).replace(",", ".")
    if not text:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        number = float(match.group(0))
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def _format_number(value: float | None, *, decimals: int = 0, trim: bool = True) -> str:
    if value is None:
        return ""
    if decimals <= 0:
        rounded = int(math.floor(value + 0.5)) if value >= 0 else int(math.ceil(value - 0.5))
        return str(rounded)
    text = f"{value:.{decimals}f}"
    return text.rstrip("0").rstrip(".") if trim and "." in text else text


def _format_metric(value: float | None, unit: str, *, decimals: int = 0) -> str:
    text = _format_number(value, decimals=decimals)
    return f"{text} {unit}".strip() if text else ""


def _format_dimension(values: dict[str, object]) -> str:
    ordered = [_as_float(values.get(key)) for key in ("x", "y", "z")]
    metric = " x ".join(_format_number(value) for value in ordered if value is not None)
    imperial = " x ".join(_format_number(value / 25.4, decimals=1, trim=False) for value in ordered if value is not None)
    if metric and imperial:
        return f"{metric} mm ({imperial} inch)"
    return f"{metric} mm".strip()


def _format_weight(values: dict[str, object]) -> str:
    netto = _as_float(values.get("netto"))
    brutto = _as_float(values.get("brutto"))
    parts: list[str] = []
    if netto is not None:
        parts.append(
            f"{_format_number(netto, decimals=1)} kg / "
            f"{_format_number(netto * 2.2046226218, decimals=1, trim=False)} lbs - single unit"
        )
    if brutto is not None:
        parts.append(
            f"{_format_number(brutto, decimals=1)} kg / "
            f"{_format_number(brutto * 2.2046226218, decimals=1, trim=False)} lbs - single unit incl. package"
        )
    return "\n".join(parts)


def _format_pole_diameter(values: dict[str, object]) -> str:
    min_value = _as_float(values.get("min"))
    max_value = _as_float(values.get("max"))
    if min_value is None or max_value is None:
        return ""
    return (
        f"{_format_number(min_value)}-{_format_number(max_value)} mm "
        f"({_format_number(min_value / 25.4, decimals=1)}-{_format_number(max_value / 25.4, decimals=1)} inch)"
    )


def _format_front_side(values: dict[str, object], *, metric_unit: str, imperial_factor: float, imperial_unit: str, decimals: int) -> str:
    front = _as_float(values.get("front"))
    side = _as_float(values.get("side"))
    metric = "/".join(_format_number(value) for value in (front, side) if value is not None)
    imperial = "/".join(_format_number(value * imperial_factor, decimals=decimals, trim=decimals <= 0) for value in (front, side) if value is not None)
    if metric and imperial:
        return f"{metric} {metric_unit} - Front/Side ({imperial} {imperial_unit})"
    return f"{metric} {metric_unit}".strip()


def _format_wind_load(values: dict[str, object], wind_speed: object | None) -> str:
    front_side = _format_front_side(values, metric_unit="N", imperial_factor=1.0, imperial_unit="N", decimals=0)
    text = re.sub(r"\s+\([^)]*\)$", "", front_side)
    speed = _as_float(wind_speed)
    if speed is not None:
        mph = round(speed * 0.6213711922 / 5.0) * 5.0
        text = f"{text} at {_format_number(speed)} km/h ({_format_number(mph)} mph)"
    return text


def _format_adjustment(values: dict[str, object]) -> str:
    parts: list[str] = []
    for label in ("elevation", "azimuth"):
        value = _format_cell(values.get(label))
        if value:
            normalized = value.replace("\N{PLUS-MINUS SIGN}", "+/-")
            parts.append(f"{normalized} {label.capitalize()}")
    return ", ".join(parts)


def _is_rfe_v2_table(data: pd.DataFrame, first_index: int) -> bool:
    if data.shape[1] < 3:
        return False
    rows = data.iloc[first_index : first_index + 40, :3]
    first_col = {_normalize_header(value) for value in rows.iloc[:, 0].tolist() if _format_cell(value)}
    has_sections = {"general", "performance", "dimensions", "technical data"}.issubset(first_col)
    has_product_name = any(_normalize_header(row.iloc[0]) == "product name" and _format_cell(row.iloc[2]) for _idx, row in rows.iterrows())
    return has_sections and has_product_name


def _parse_rfe_v2_rows(data: pd.DataFrame, *, canonical_key_factory) -> list[TechnicalDataEntry]:
    rfe_section_keys = {*KNOWN_SECTION_KEYS, "general", "dimensions", "wind"}
    section = "Technical Data"
    rows_by_label: dict[str, dict[str, object]] = {}
    simple_rows: list[tuple[str, str, str]] = []
    section_by_label: dict[str, str] = {}
    wind_speed: object | None = None

    for _idx, row in data.iterrows():
        label = _format_cell(row.iloc[0] if data.shape[1] > 0 else "")
        qualifier = _format_cell(row.iloc[1] if data.shape[1] > 1 else "")
        value = _format_cell(row.iloc[2] if data.shape[1] > 2 else "")
        label_key = _normalize_header(label)
        qualifier_key = _normalize_header(qualifier)
        if label_key in rfe_section_keys and not qualifier and not value:
            section = normalize_table_section(label)
            continue
        if not label:
            if not qualifier:
                continue
            if not rows_by_label:
                continue
            last_label = next(reversed(rows_by_label))
            rows_by_label[last_label][qualifier_key] = value
            continue
        if label_key == "wind load at speed km h":
            wind_speed = value
            continue
        if qualifier:
            rows_by_label.setdefault(label, {})[qualifier_key] = value
            section_by_label.setdefault(label, section)
        elif value:
            simple_rows.append((section, "Antenna Name" if label_key == "product name" else label, value))

    combined: list[tuple[str, str, str]] = []
    for label, values in rows_by_label.items():
        key = _normalize_header(label)
        section_for_label = section_by_label.get(label, "Technical Data")
        if key == "size single unit mm":
            combined.append((section_for_label, "Single Unit", _format_dimension(values)))
        elif key == "weight single unit kg":
            combined.append((section_for_label, "Weight", _format_weight(values)))
        elif key == "pole mounting diameter mm":
            combined.append((section_for_label, "Pole Mounting Diameter", _format_pole_diameter(values)))
        elif key == "wind load n":
            combined.append((section_for_label, "Wind Load", _format_wind_load(values, wind_speed)))
        elif key in {"effective projected area cm2", "effective projected area cm"}:
            combined.append((section_for_label, "Effective Projected Area", _format_front_side(values, metric_unit="cm²", imperial_factor=0.15500031, imperial_unit="in²", decimals=1)))
        elif key == "mechanical adjustment":
            combined.append((section_for_label, "Mechanical Adjustment", _format_adjustment(values)))

    entries: list[TechnicalDataEntry] = []
    for section_name, label, value in [*simple_rows, *combined]:
        if not normalize_technical_key(label):
            continue
        entries.append(_entry_factory(section=section_name, label=label, value=value, canonical_key_factory=canonical_key_factory))
    return entries


def load_technical_data_entries(
    path: Path,
    *,
    sheet_name: str | int | None = None,
    product_id: str | None = None,
    canonical_key_factory=None,
    technical_data_profile: str | None = None,
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
    if technical_data_profile == "rfe" and _is_rfe_v2_table(data, first_index):
        entries = _parse_rfe_v2_rows(data, canonical_key_factory=canonical_key_factory)
    elif wide_header_index is not None:
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
