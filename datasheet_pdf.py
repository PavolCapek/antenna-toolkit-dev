#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import math
from dataclasses import dataclass
from pathlib import Path

import fitz
import pandas as pd

fitz.TOOLS.mupdf_display_errors(False)
fitz.TOOLS.mupdf_display_warnings(False)

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


@dataclass(frozen=True)
class TextSpan:
    text: str
    bbox: fitz.Rect
    origin: tuple[float, float]
    font: str
    size: float
    color: int


@dataclass(frozen=True)
class ReplacementSlot:
    label: str
    erase_rect: fitz.Rect
    text_rect: fitz.Rect
    font_size: float
    color: tuple[float, float, float]


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


def _format_int_with_suffix(value: float, suffix: str) -> str:
    return f"{_round_half_up(value)} {suffix}".strip()


def _format_frequency_range(fmin_ghz: float, fmax_ghz: float) -> str:
    return f"{_round_half_up(fmin_ghz * 1000.0)} - {_round_half_up(fmax_ghz * 1000.0)} MHz"


def _format_beamwidth_text(horizontal: pd.Series, vertical: pd.Series, three_db_col: str, six_db_col: str) -> str:
    return (
        f"H {_round_half_up(float(horizontal[three_db_col]))}\N{DEGREE SIGN}, "
        f"V {_round_half_up(float(vertical[three_db_col]))}\N{DEGREE SIGN} / "
        f"H {_round_half_up(float(horizontal[six_db_col]))}\N{DEGREE SIGN}, "
        f"V {_round_half_up(float(vertical[six_db_col]))}\N{DEGREE SIGN}"
    )


def _format_vswr_limit(max_vswr: float) -> str:
    limit = math.ceil(float(max_vswr) * 100.0) / 100.0
    value = f"{limit:.2f}".rstrip("0").rstrip(".")
    return f"<{value}"


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


def _polarization_text(ffs_summary: pd.DataFrame) -> str:
    values = {_normalize_polarization(value) for value in ffs_summary.get("polarization", []) if str(value).strip()}
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
    raise ValueError("Unable to derive polarization from the extracted workbook.")


def build_replacements_from_workbook(extract_workbook: Path) -> dict[str, str]:
    ffs_summary = _load_sheet(extract_workbook, "ffs_summary")
    touchstone_summary = _load_sheet(extract_workbook, "touchstone_summary")

    if ffs_summary.empty:
        raise ValueError("The extracted workbook has no far-field summary rows.")
    if touchstone_summary.empty:
        raise ValueError("The extracted workbook has no Touchstone summary rows.")

    required_ffs = {
        "polarization",
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

    polarizations = ffs_summary.assign(_polarization_key=ffs_summary["polarization"].map(_normalize_polarization))
    horizontal = polarizations[polarizations["_polarization_key"] == "horizontal"]
    vertical = polarizations[polarizations["_polarization_key"] == "vertical"]
    if horizontal.empty or vertical.empty:
        raise ValueError("The extracted workbook must contain both Horizontal and Vertical far-field summaries.")

    horizontal_row = horizontal.iloc[0]
    vertical_row = vertical.iloc[0]

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
        "Gain": _format_int_with_suffix(gain, "dBi"),
        "Azimuth Beam Width -3 dB/-6dB": _format_beamwidth_text(horizontal_row, vertical_row, "avg_azimuth_bw_3dB_deg", "avg_azimuth_bw_6dB_deg"),
        "Elevation Beam Width -3 dB/-6dB": _format_beamwidth_text(horizontal_row, vertical_row, "avg_elevation_bw_3dB_deg", "avg_elevation_bw_6dB_deg"),
        "Beam Efficiency": f"{_round_half_up(beam_eff)} %*",
        "Front-to-Back Ratio": _format_int_with_suffix(front_to_back, "dB"),
        "VSWR": _format_vswr_limit(max_vswr),
        "Polarization": _polarization_text(ffs_summary),
        "Impedance": _format_int_with_suffix(ref_impedance, "Ohm"),
    }


def _extract_page_spans(page: fitz.Page) -> list[TextSpan]:
    spans: list[TextSpan] = []
    for block in page.get_text("dict").get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = str(span.get("text", "")).strip()
                if not text:
                    continue
                spans.append(
                    TextSpan(
                        text=text,
                        bbox=fitz.Rect(span["bbox"]),
                        origin=tuple(float(v) for v in span.get("origin", (span["bbox"][0], span["bbox"][3] - 1.0))),
                        font=str(span.get("font", "helv")),
                        size=float(span.get("size", 7.0)),
                        color=int(span.get("color", 0)),
                    )
                )
    return spans


def _int_color_to_rgb(color: int) -> tuple[float, float, float]:
    red = (color >> 16) & 0xFF
    green = (color >> 8) & 0xFF
    blue = color & 0xFF
    return (red / 255.0, green / 255.0, blue / 255.0)


def _center_y(rect: fitz.Rect) -> float:
    return (rect.y0 + rect.y1) / 2.0


def _resolve_font_name(page: fitz.Page, display_font: str) -> str:
    matches: list[str] = []
    type1_matches: list[str] = []
    for font in page.get_fonts(full=True):
        base_font = str(font[3] or "")
        resource_name = str(font[4] or "")
        if not resource_name:
            continue
        if base_font == display_font or base_font.endswith(f"+{display_font}"):
            matches.append(resource_name)
            if resource_name.startswith("T1_"):
                type1_matches.append(resource_name)
    if type1_matches:
        return type1_matches[0]
    if matches:
        return matches[0]
    return "helv"


def _rgb_to_hex(color: tuple[float, float, float]) -> str:
    red, green, blue = color
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, round(red * 255))),
        max(0, min(255, round(green * 255))),
        max(0, min(255, round(blue * 255))),
    )


def _find_replacement_slot(page: fitz.Page, label: str) -> ReplacementSlot:
    spans = _extract_page_spans(page)
    label_span = next((span for span in spans if span.text == label), None)
    if label_span is None:
        raise ValueError(f"Could not find datasheet label '{label}' in the template.")

    label_center = _center_y(label_span.bbox)
    candidates = [
        span
        for span in spans
        if span.bbox.x0 >= label_span.bbox.x1 - 2.0 and abs(_center_y(span.bbox) - label_center) <= 8.0
    ]
    if not candidates:
        raise ValueError(f"Could not find the value slot for '{label}' in the template.")

    value_span = min(
        candidates,
        key=lambda span: (
            abs(_center_y(span.bbox) - label_center),
            max(0.0, span.bbox.x0 - label_span.bbox.x1),
        ),
    )
    right_edge = min(page.rect.x1 - 20.0, max(value_span.bbox.x1 + 4.0, 290.0))
    erase_rect = fitz.Rect(
        max(0.0, value_span.bbox.x0 - 1.0),
        max(0.0, value_span.bbox.y0),
        right_edge,
        min(page.rect.y1, value_span.bbox.y1),
    )
    text_rect = fitz.Rect(
        value_span.bbox.x0,
        max(0.0, value_span.bbox.y0 - 1.0),
        right_edge,
        min(page.rect.y1, value_span.bbox.y1 + 1.5),
    )
    return ReplacementSlot(
        label=label,
        erase_rect=erase_rect,
        text_rect=text_rect,
        font_size=float(value_span.size),
        color=_int_color_to_rgb(value_span.color),
    )


def build_datasheet_pdf(output: Path, template: Path, extract_workbook: Path) -> dict[str, str]:
    replacements = build_replacements_from_workbook(extract_workbook)
    template = template.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with fitz.open(template) as doc:
        page = doc[0]
        slots = {label: _find_replacement_slot(page, label) for label in FIELD_LABELS}
        for slot in slots.values():
            page.add_redact_annot(slot.erase_rect, fill=(1.0, 1.0, 1.0))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        for label in FIELD_LABELS:
            slot = slots[label]
            text = replacements[label]
            css = (
                f"* {{ margin: 0; padding: 0; "
                f"font-family: Arial, Calibri, \"Segoe UI\", sans-serif; "
                f"font-size: {slot.font_size:.3f}pt; color: {_rgb_to_hex(slot.color)}; }}"
            )
            result = page.insert_htmlbox(
                slot.text_rect,
                html.escape(text).replace("\n", "<br>"),
                css=css,
                scale_low=0.8,
            )
            if not result:
                raise ValueError(f"Replacement text for '{label}' could not be inserted.")

        doc.save(output, garbage=3, deflate=True)

    return replacements


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a datasheet PDF from the extracted workbook.")
    parser.add_argument("output", type=Path, help="Output PDF path.")
    parser.add_argument("--template", type=Path, required=True, help="Template PDF path.")
    parser.add_argument("--extract-workbook", type=Path, required=True, help="Extracted workbook path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        replacements = build_datasheet_pdf(
            output=args.output,
            template=args.template,
            extract_workbook=args.extract_workbook,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"Wrote datasheet PDF to {args.output}")
    for label in FIELD_LABELS:
        print(f"{label}: {replacements[label]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
