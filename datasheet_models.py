from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from datasheet_artifacts import artifact_manifest_path, load_artifact_manifest


FIELD_LABELS = [
    "Frequency Range",
    "Gain",
    "Azimuth Beam Width -3 dB/-6dB",
    "Elevation Beam Width -3 dB/-6dB",
    "Beam Efficiency",
    "Front-to-Back Ratio",
    "VSWR",
    "Polarization",
    "Impedance",
]
FIELD_LABEL_ALIASES = {
    "Frequency Range": (
        "Frequency Range",
        "Frequency",
        "Frequency Band",
        "Operating Frequency",
    ),
    "Gain": (
        "Gain",
        "Nominal Gain",
        "Antenna Gain",
    ),
    "Azimuth Beam Width -3 dB/-6dB": (
        "Azimuth Beam Width -3 dB/-6dB",
        "Azimuth Beam Width",
        "Azimuth Beamwidth",
        "Beamwidth Azimuth",
        "Beamwidth H plane.",
        "Beamwidth H plane",
        "H Plane Beamwidth",
        "H-Plane Beamwidth",
        "Horizontal Beamwidth",
        "Horizontal Beam Width",
    ),
    "Elevation Beam Width -3 dB/-6dB": (
        "Elevation Beam Width -3 dB/-6dB",
        "Elevation Beam Width",
        "Elevation Beamwidth",
        "Beamwidth Elevation",
        "Beamwidth E plane.",
        "Beamwidth E plane",
        "E Plane Beamwidth",
        "E-Plane Beamwidth",
        "Vertical Beamwidth",
        "Vertical Beam Width",
    ),
    "Beam Efficiency": (
        "Beam Efficiency",
        "Efficiency",
    ),
    "Front-to-Back Ratio": (
        "Front-to-Back Ratio",
        "Front to Back Ratio",
        "Front Back Ratio",
        "F/B Ratio",
    ),
    "VSWR": ("VSWR",),
    "Polarization": ("Polarization",),
    "Impedance": (
        "Impedance",
        "Nominal Impedance",
    ),
}
TECHNICAL_DATA_PLACEHOLDER = "text_placeholder"
TECHNICAL_DATA_RESERVED_KEYS = {"antenna name", "product id"}
KNOWN_POLARIZATION_KEYS = {"horizontal", "vertical", "rhcp", "lhcp"}


@dataclass
class TechnicalDataEntry:
    label: str
    value: str


@dataclass
class DatasheetModel:
    extract_workbook: Path
    technical_data_workbook: Path | None = None
    performance_fields: dict[str, str] = field(default_factory=dict)
    technical_entries: list[TechnicalDataEntry] = field(default_factory=list)
    artifact_manifest: dict[str, Any] = field(default_factory=dict)


def _load_sheet(path: Path, sheet_name: str) -> pd.DataFrame:
    try:
        return pd.read_excel(path, sheet_name=sheet_name)
    except ValueError as exc:
        raise ValueError(f"Workbook is missing required sheet '{sheet_name}'.") from exc


def _as_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _round_half_up(value: float) -> int:
    return int(math.floor(float(value) + 0.5))


def _round_half_up_to_decimals(value: float, decimals: int) -> float:
    factor = 10 ** decimals
    scaled = float(value) * factor
    if scaled >= 0:
        return math.floor(scaled + 0.5) / factor
    return math.ceil(scaled - 0.5) / factor


def _format_int_with_suffix(value: float, suffix: str) -> str:
    return f"{_round_half_up(value)} {suffix}".strip()


def _format_decimal_with_suffix(value: float, suffix: str, decimals: int) -> str:
    rounded = _round_half_up_to_decimals(value, decimals)
    return f"{rounded:.{decimals}f} {suffix}".strip()


def _format_frequency_range(fmin_ghz: float, fmax_ghz: float) -> str:
    return f"{_round_half_up(fmin_ghz * 1000.0)} - {_round_half_up(fmax_ghz * 1000.0)} MHz"


def _format_beamwidth_text(horizontal: pd.Series, vertical: pd.Series, three_db_col: str, six_db_col: str) -> str:
    return (
        f"H {_round_half_up(float(horizontal[three_db_col]))}\N{DEGREE SIGN}, "
        f"V {_round_half_up(float(vertical[three_db_col]))}\N{DEGREE SIGN} / "
        f"H {_round_half_up(float(horizontal[six_db_col]))}\N{DEGREE SIGN}, "
        f"V {_round_half_up(float(vertical[six_db_col]))}\N{DEGREE SIGN}"
    )


def _format_single_beamwidth_text(row: pd.Series, three_db_col: str, six_db_col: str) -> str:
    return (
        f"{_round_half_up(float(row[three_db_col]))}\N{DEGREE SIGN} / "
        f"{_round_half_up(float(row[six_db_col]))}\N{DEGREE SIGN}"
    )


def _format_vswr_limit(max_vswr: float) -> str:
    value = _round_half_up_to_decimals(max_vswr, 1)
    return f"<{value:.1f}"


def _normalize_polarization(value: object) -> str:
    text = str(value or "").strip().lower()
    if text in {"horizontal", "h"}:
        return "horizontal"
    if text in {"vertical", "v"}:
        return "vertical"
    if text == "rhcp":
        return "rhcp"
    if text == "lhcp":
        return "lhcp"
    return text


def _infer_polarization_from_source_file(path_text: object) -> str:
    stem = Path(str(path_text or "")).stem
    tokens = [token.lower() for token in re.split(r"[_\-\s]+", stem) if token]
    aliases = {
        "horizontal": "Horizontal",
        "vertical": "Vertical",
        "rhcp": "RHCP",
        "lhcp": "LHCP",
        "hcp": "HCP",
        "vpol": "Vertical",
        "hpol": "Horizontal",
    }
    for token in reversed(tokens):
        if token in aliases:
            return aliases[token]
        if token == "h":
            return "Horizontal"
        if token == "v":
            return "Vertical"
    return stem


def polarization_keys_from_source_files(ffs_summary: pd.DataFrame) -> pd.Series:
    if "source_file" not in ffs_summary.columns:
        raise ValueError("ffs_summary is missing required column: source_file")
    keys = ffs_summary["source_file"].map(_infer_polarization_from_source_file).map(_normalize_polarization)
    if "polarization" in ffs_summary.columns:
        workbook_keys = ffs_summary["polarization"].map(_normalize_polarization)
        keys = keys.where(keys.isin(KNOWN_POLARIZATION_KEYS), workbook_keys)
    return keys


def _polarization_text(ffs_summary: pd.DataFrame) -> str:
    values = {value for value in polarization_keys_from_source_files(ffs_summary) if str(value).strip()}
    if {"horizontal", "vertical"}.issubset(values):
        return "Dual Linear H + V"
    if {"rhcp", "lhcp"}.issubset(values):
        return "Dual Circular RHCP + LHCP"
    if "horizontal" in values:
        return "Linear H"
    if "vertical" in values:
        return "Linear V"
    if "rhcp" in values:
        return "RHCP"
    if "lhcp" in values:
        return "LHCP"
    if len(ffs_summary) == 1:
        return "Single Polarization"
    raise ValueError("Unable to derive polarization from the extracted workbook.")


def build_performance_fields(extract_workbook: Path) -> dict[str, str]:
    ffs_summary = _load_sheet(extract_workbook, "ffs_summary")
    touchstone_summary = _load_sheet(extract_workbook, "touchstone_summary")

    if ffs_summary.empty:
        raise ValueError("The extracted workbook has no far-field summary rows.")
    if touchstone_summary.empty:
        raise ValueError("The extracted workbook has no Touchstone summary rows.")

    required_ffs = {
        "source_file",
        "freq_min_GHz",
        "freq_max_GHz",
        "max_gain_dBi_in_range",
        "avg_azimuth_bw_3dB_deg",
        "avg_azimuth_bw_6dB_deg",
        "avg_elevation_bw_3dB_deg",
        "avg_elevation_bw_6dB_deg",
        "avg_beam_efficiency_percent",
        "avg_front_to_back_dB",
    }
    required_touchstone = {"max_vswr_in_range", "reference_impedance_ohm"}
    missing_ffs = sorted(required_ffs.difference(ffs_summary.columns))
    missing_touchstone = sorted(required_touchstone.difference(touchstone_summary.columns))
    if missing_ffs:
        raise ValueError(f"ffs_summary is missing required columns: {', '.join(missing_ffs)}")
    if missing_touchstone:
        raise ValueError(f"touchstone_summary is missing required columns: {', '.join(missing_touchstone)}")

    polarizations = ffs_summary.assign(_polarization_key=polarization_keys_from_source_files(ffs_summary))
    horizontal = polarizations[polarizations["_polarization_key"] == "horizontal"]
    vertical = polarizations[polarizations["_polarization_key"] == "vertical"]
    has_dual_linear = not horizontal.empty and not vertical.empty
    if has_dual_linear:
        azimuth_beamwidth = _format_beamwidth_text(horizontal.iloc[0], vertical.iloc[0], "avg_azimuth_bw_3dB_deg", "avg_azimuth_bw_6dB_deg")
        elevation_beamwidth = _format_beamwidth_text(horizontal.iloc[0], vertical.iloc[0], "avg_elevation_bw_3dB_deg", "avg_elevation_bw_6dB_deg")
    else:
        summary_row = ffs_summary.iloc[0]
        azimuth_beamwidth = _format_single_beamwidth_text(summary_row, "avg_azimuth_bw_3dB_deg", "avg_azimuth_bw_6dB_deg")
        elevation_beamwidth = _format_single_beamwidth_text(summary_row, "avg_elevation_bw_3dB_deg", "avg_elevation_bw_6dB_deg")

    freq_min_values = [
        _as_float(ffs_summary["freq_min_GHz"].min()),
        _as_float(touchstone_summary.get("freq_min_GHz", pd.Series(dtype=float)).min()),
    ]
    freq_max_values = [
        _as_float(ffs_summary["freq_max_GHz"].max()),
        _as_float(touchstone_summary.get("freq_max_GHz", pd.Series(dtype=float)).max()),
    ]
    freq_min_candidates = [value for value in freq_min_values if value is not None]
    freq_max_candidates = [value for value in freq_max_values if value is not None]
    if not freq_min_candidates or not freq_max_candidates:
        raise ValueError("Unable to derive the frequency range from the extracted workbook.")
    freq_min = min(freq_min_candidates)
    freq_max = max(freq_max_candidates)

    gain = _as_float(ffs_summary["max_gain_dBi_in_range"].max())
    beam_eff = _as_float(ffs_summary["avg_beam_efficiency_percent"].mean())
    front_to_back = _as_float(ffs_summary["avg_front_to_back_dB"].mean())
    max_vswr = _as_float(touchstone_summary["max_vswr_in_range"].max())
    ref_values = touchstone_summary["reference_impedance_ohm"].dropna()
    ref_impedance = _as_float(ref_values.iloc[0] if not ref_values.empty else None)

    required_values = {
        "gain": gain is not None,
        "beam efficiency": beam_eff is not None,
        "front-to-back ratio": front_to_back is not None,
        "vswr": max_vswr is not None,
        "impedance": ref_impedance is not None,
    }
    missing_values = [name for name, present in required_values.items() if not present]
    if missing_values:
        raise ValueError(f"Unable to derive datasheet values: {', '.join(missing_values)}")

    return {
        "Frequency Range": _format_frequency_range(freq_min, freq_max),
        "Gain": _format_decimal_with_suffix(gain, "dBi", 1),
        "Azimuth Beam Width -3 dB/-6dB": azimuth_beamwidth,
        "Elevation Beam Width -3 dB/-6dB": elevation_beamwidth,
        "Beam Efficiency": f"{_round_half_up(beam_eff)} %*",
        "Front-to-Back Ratio": _format_int_with_suffix(front_to_back, "dB"),
        "VSWR": _format_vswr_limit(max_vswr),
        "Polarization": _polarization_text(ffs_summary),
        "Impedance": _format_int_with_suffix(ref_impedance, "Ohm"),
    }


def _format_technical_cell(value: object) -> str:
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


def normalize_technical_key(value: object) -> str:
    cleaned = re.sub(r"[\u200B-\u200D\uFEFF]", "", str(value or ""))
    return re.sub(r"\s+", " ", cleaned.strip()).lower()


def load_technical_data_entries(path: Path) -> list[TechnicalDataEntry]:
    try:
        data = pd.read_excel(path, sheet_name=0, header=None, dtype=object)
    except Exception as exc:
        raise ValueError(f"Could not read Technical Data workbook '{path}'.") from exc
    if data.shape[1] < 2:
        data[1] = ""

    entries: list[TechnicalDataEntry] = []
    index_by_key: dict[str, int] = {}
    for _idx, row in data.iloc[:, :2].iterrows():
        label = _format_technical_cell(row.iloc[0])
        key = normalize_technical_key(label)
        if not key:
            continue
        value = _format_technical_cell(row.iloc[1])
        if key in index_by_key:
            entries[index_by_key[key]].value = value
            continue
        index_by_key[key] = len(entries)
        entries.append(TechnicalDataEntry(label=label, value=value))
    if not entries:
        raise ValueError("Technical Data workbook does not contain any field/value rows.")
    return entries


def technical_data_by_key(entries: list[TechnicalDataEntry]) -> dict[str, TechnicalDataEntry]:
    return {normalize_technical_key(entry.label): entry for entry in entries}


def text_or_placeholder(value: str) -> tuple[str, bool]:
    text = str(value or "").strip()
    if text:
        return text, False
    return TECHNICAL_DATA_PLACEHOLDER, True


def load_datasheet_model(
    extract_workbook: Path,
    technical_data_workbook: Path | None = None,
    *,
    output_dir: Path | None = None,
) -> DatasheetModel:
    extract_workbook = extract_workbook.resolve()
    if output_dir is None:
        output_dir = extract_workbook.parent
    bookstem = extract_workbook.stem
    for suffix in ("-extracted-data", "_extracted_data"):
        if bookstem.endswith(suffix):
            bookstem = bookstem[: -len(suffix)]
            break
    manifest = load_artifact_manifest(artifact_manifest_path(output_dir, bookstem), bookstem=bookstem)
    entries = load_technical_data_entries(technical_data_workbook.resolve()) if technical_data_workbook else []
    return DatasheetModel(
        extract_workbook=extract_workbook,
        technical_data_workbook=technical_data_workbook.resolve() if technical_data_workbook else None,
        performance_fields=build_performance_fields(extract_workbook),
        technical_entries=entries,
        artifact_manifest=manifest,
    )

