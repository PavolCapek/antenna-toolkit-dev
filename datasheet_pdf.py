#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import fitz
import pandas as pd

fitz.TOOLS.mupdf_display_errors(False)
fitz.TOOLS.mupdf_display_warnings(False)

THIS_DIR = Path(__file__).resolve().parent
MYRIAD_FONT_DIR = THIS_DIR / "Fonts" / "Myriad Pro"
MYRIAD_FONT_FILES = {
    "MyriadPro-Regular": MYRIAD_FONT_DIR / "MYRIADPRO-REGULAR.OTF",
    "MyriadPro-Bold": MYRIAD_FONT_DIR / "MYRIADPRO-BOLD.OTF",
    "MyriadPro-Semibold": MYRIAD_FONT_DIR / "MYRIADPRO-SEMIBOLD.OTF",
    "MyriadPro-Light": MYRIAD_FONT_DIR / "MyriadPro-Light.otf",
    "MyriadPro-Cond": MYRIAD_FONT_DIR / "MYRIADPRO-COND.OTF",
    "MyriadPro-BoldCond": MYRIAD_FONT_DIR / "MYRIADPRO-BOLDCOND.OTF",
    "MyriadPro-BoldCondIt": MYRIAD_FONT_DIR / "MYRIADPRO-BOLDCONDIT.OTF",
    "MyriadPro-BoldIt": MYRIAD_FONT_DIR / "MYRIADPRO-BOLDIT.OTF",
    "MyriadPro-CondIt": MYRIAD_FONT_DIR / "MYRIADPRO-CONDIT.OTF",
    "MyriadPro-SemiboldIt": MYRIAD_FONT_DIR / "MYRIADPRO-SEMIBOLDIT.OTF",
}

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
    origin: tuple[float, float]
    max_width: float
    font_name: str
    font_size: float
    color: tuple[float, float, float]


@dataclass(frozen=True)
class ChartSlot:
    rect: fitz.Rect
    image_name: str


@dataclass(frozen=True)
class ChartReplacement:
    kind: str
    rect: fitz.Rect
    asset_path: Path


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


def _polarization_keys_from_source_files(ffs_summary: pd.DataFrame) -> pd.Series:
    if "source_file" not in ffs_summary.columns:
        raise ValueError("ffs_summary is missing required column: source_file")
    return ffs_summary["source_file"].map(_infer_polarization_from_source_file).map(_normalize_polarization)


def _polarization_text(ffs_summary: pd.DataFrame) -> str:
    values = {value for value in _polarization_keys_from_source_files(ffs_summary) if str(value).strip()}
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

    polarizations = ffs_summary.assign(_polarization_key=_polarization_keys_from_source_files(ffs_summary))
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
        "Gain": _format_decimal_with_suffix(gain, "dBi", 1),
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


def _font_path_for_display_font(display_font: str) -> Path | None:
    path = MYRIAD_FONT_FILES.get(display_font)
    if path and path.exists():
        return path
    return None


@lru_cache(maxsize=None)
def _measurement_font(font_name: str, font_path_text: str | None) -> fitz.Font:
    if font_path_text:
        return fitz.Font(fontfile=font_path_text)
    return fitz.Font(fontname=font_name)


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
    return ReplacementSlot(
        label=label,
        erase_rect=erase_rect,
        origin=value_span.origin,
        max_width=max(1.0, right_edge - value_span.origin[0]),
        font_name=value_span.font,
        font_size=float(value_span.size),
        color=_int_color_to_rgb(value_span.color),
    )


def _fit_font_size(text: str, slot: ReplacementSlot, font_path: Path | None) -> float:
    font = _measurement_font(slot.font_name, str(font_path) if font_path else None)
    target_size = slot.font_size
    text_width = font.text_length(text, fontsize=target_size)
    if text_width <= slot.max_width:
        return target_size
    if text_width <= 0:
        return target_size
    scaled_size = target_size * (slot.max_width / text_width)
    return max(target_size * 0.75, scaled_size)


def _stem_without_suffix(stem: str, suffix: str) -> str:
    return stem[: -len(suffix)] if stem.endswith(suffix) else stem


def _find_plot_asset(output: Path, extract_workbook: Path, suffix: str) -> Path:
    candidate_dirs: list[Path] = []
    for path in [output.parent.resolve(), extract_workbook.parent.resolve()]:
        if path not in candidate_dirs:
            candidate_dirs.append(path)

    candidate_prefixes: list[str] = []
    for stem in [
        _stem_without_suffix(extract_workbook.stem, "_extracted_data"),
        _stem_without_suffix(output.stem, "_datasheet"),
        extract_workbook.stem,
        output.stem,
    ]:
        if stem and stem not in candidate_prefixes:
            candidate_prefixes.append(stem)

    checked: list[Path] = []
    for directory in candidate_dirs:
        for prefix in candidate_prefixes:
            candidate = directory / f"{prefix}{suffix}"
            checked.append(candidate)
            if candidate.exists():
                return candidate
    checked_list = ", ".join(str(path) for path in checked)
    raise ValueError(f"Missing required plot asset '{suffix}'. Checked: {checked_list}")


def _extract_frequency_ghz(text: str) -> float | None:
    match = re.search(r"(\d+(?:[\.,]\d+)?)\s*ghz", str(text), re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _parse_frequency_from_polar_asset(path: Path, plane: str) -> float | None:
    pattern = rf"_polar_{re.escape(plane)}_(\d+(?:\.\d+)?)_GHz\.svg$"
    match = re.search(pattern, path.name, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def _candidate_dirs(output: Path, extract_workbook: Path) -> list[Path]:
    candidate_dirs: list[Path] = []
    for path in [output.parent.resolve(), extract_workbook.parent.resolve()]:
        if path not in candidate_dirs:
            candidate_dirs.append(path)
    return candidate_dirs


def _candidate_prefixes(output: Path, extract_workbook: Path) -> list[str]:
    candidate_prefixes: list[str] = []
    for stem in [
        _stem_without_suffix(extract_workbook.stem, "_extracted_data"),
        _stem_without_suffix(output.stem, "_datasheet"),
        extract_workbook.stem,
        output.stem,
    ]:
        if stem and stem not in candidate_prefixes:
            candidate_prefixes.append(stem)
    return candidate_prefixes


def _find_template_polar_frequency(page: fitz.Page) -> float | None:
    values = [
        _extract_frequency_ghz(span.text)
        for span in _extract_page_spans(page)
        if "Port Pattern" in span.text
    ]
    values = [value for value in values if value is not None]
    if not values:
        return None
    rounded = [round(value, 6) for value in values]
    return float(Counter(rounded).most_common(1)[0][0])


def _find_polar_plot_assets(page: fitz.Page, output: Path, extract_workbook: Path) -> tuple[Path, Path]:
    plane_assets: dict[str, dict[float, Path]] = {"azimuth": {}, "elevation": {}}
    checked: list[Path] = []
    for directory in _candidate_dirs(output, extract_workbook):
        for prefix in _candidate_prefixes(output, extract_workbook):
            for plane in plane_assets:
                base_dir = directory / "polar_single" / plane
                pattern = f"{prefix}_polar_{plane}_*_GHz.svg"
                for candidate in sorted(base_dir.glob(pattern)):
                    checked.append(candidate)
                    frequency = _parse_frequency_from_polar_asset(candidate, plane)
                    if frequency is not None:
                        plane_assets[plane].setdefault(frequency, candidate)

    common_frequencies = sorted(set(plane_assets["azimuth"]).intersection(plane_assets["elevation"]))
    if not common_frequencies:
        checked_list = ", ".join(str(path) for path in checked) if checked else "none"
        raise ValueError(f"Missing required polar plot assets. Checked: {checked_list}")

    template_frequency = _find_template_polar_frequency(page)
    if template_frequency is None:
        template_frequency = sum(common_frequencies) / len(common_frequencies)
    selected_frequency = min(common_frequencies, key=lambda value: (abs(value - template_frequency), value))
    return plane_assets["azimuth"][selected_frequency], plane_assets["elevation"][selected_frequency]


def _collect_chart_slots(page: fitz.Page) -> list[ChartSlot]:
    slots: list[ChartSlot] = []
    for info in page.get_images(full=True):
        xref = int(info[0])
        image_name = str(info[7] or "")
        rects = page.get_image_rects(xref)
        for rect in rects:
            slots.append(ChartSlot(rect=fitz.Rect(rect), image_name=image_name))
    slots.sort(key=lambda slot: (slot.rect.y0, slot.rect.x0, slot.rect.y1, slot.rect.x1))
    return slots


def _expand_rect(rect: fitz.Rect, padding: float = 2.0) -> fitz.Rect:
    return fitz.Rect(rect.x0 - padding, rect.y0 - padding, rect.x1 + padding, rect.y1 + padding)


def _union_rects(rects: list[fitz.Rect]) -> fitz.Rect:
    combined = fitz.Rect(rects[0])
    for rect in rects[1:]:
        combined.include_rect(rect)
    return combined


def _legend_group(text: str) -> str | None:
    stripped = str(text).strip()
    if re.match(r"^Gain\b", stripped):
        return "gain"
    if re.match(r"^Beamwidth\b", stripped):
        return "beamwidth"
    if "Port Pattern" in stripped:
        return "polar"
    return None


def _build_chart_replacements(page: fitz.Page, output: Path, extract_workbook: Path) -> list[ChartReplacement]:
    slots = _collect_chart_slots(page)
    if len(slots) < 2:
        raise ValueError("Datasheet template page 2 does not contain the expected chart image slots.")

    replacements: list[ChartReplacement] = [
        ChartReplacement("gain", fitz.Rect(slots[0].rect), _find_plot_asset(output, extract_workbook, "_gain.svg")),
        ChartReplacement("beamwidth", fitz.Rect(slots[1].rect), _find_plot_asset(output, extract_workbook, "_beamwidth.svg")),
    ]
    if len(slots) >= 4:
        azimuth_asset, elevation_asset = _find_polar_plot_assets(page, output, extract_workbook)
        replacements.extend(
            [
                ChartReplacement("azimuth", fitz.Rect(slots[2].rect), azimuth_asset),
                ChartReplacement("elevation", fitz.Rect(slots[3].rect), elevation_asset),
            ]
        )

    index_by_kind = {replacement.kind: idx for idx, replacement in enumerate(replacements)}
    spans = _extract_page_spans(page)
    polar_centers = {
        "azimuth": _center_y(replacements[index_by_kind["azimuth"]].rect) if "azimuth" in index_by_kind else None,
        "elevation": _center_y(replacements[index_by_kind["elevation"]].rect) if "elevation" in index_by_kind else None,
    }
    polar_x_centers = {
        "azimuth": (replacements[index_by_kind["azimuth"]].rect.x0 + replacements[index_by_kind["azimuth"]].rect.x1) / 2.0 if "azimuth" in index_by_kind else None,
        "elevation": (replacements[index_by_kind["elevation"]].rect.x0 + replacements[index_by_kind["elevation"]].rect.x1) / 2.0 if "elevation" in index_by_kind else None,
    }
    legend_rects: dict[str, list[fitz.Rect]] = {replacement.kind: [] for replacement in replacements}

    for span in spans:
        group = _legend_group(span.text)
        if group == "gain" and "gain" in legend_rects:
            legend_rects["gain"].append(fitz.Rect(span.bbox))
        elif group == "beamwidth" and "beamwidth" in legend_rects:
            legend_rects["beamwidth"].append(fitz.Rect(span.bbox))
        elif group == "polar" and "azimuth" in legend_rects and "elevation" in legend_rects:
            center_x = (span.bbox.x0 + span.bbox.x1) / 2.0
            target_kind = min(
                ("azimuth", "elevation"),
                key=lambda kind: abs(center_x - float(polar_x_centers[kind])),
            )
            legend_rects[target_kind].append(fitz.Rect(span.bbox))

    resolved: list[ChartReplacement] = []
    for replacement in replacements:
        rects = [fitz.Rect(replacement.rect)] + legend_rects.get(replacement.kind, [])
        resolved.append(
            ChartReplacement(
                replacement.kind,
                _expand_rect(_union_rects(rects)),
                replacement.asset_path,
            )
        )
    return resolved


def _place_svg_as_vector(page: fitz.Page, target_rect: fitz.Rect, svg_path: Path) -> None:
    with fitz.open(svg_path) as svg_doc:
        pdf_bytes = svg_doc.convert_to_pdf()
    with fitz.open("pdf", pdf_bytes) as pdf_doc:
        page.show_pdf_page(target_rect, pdf_doc, 0, keep_proportion=True, overlay=True)


def _replace_chart_images(doc: fitz.Document, output: Path, extract_workbook: Path) -> None:
    if doc.page_count < 2:
        return

    page = doc[1]
    replacements = _build_chart_replacements(page, output, extract_workbook)
    for replacement in replacements:
        page.add_redact_annot(replacement.rect, fill=(1.0, 1.0, 1.0))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)
    for replacement in replacements:
        _place_svg_as_vector(page, replacement.rect, replacement.asset_path)


def build_datasheet_pdf(output: Path, template: Path, extract_workbook: Path) -> dict[str, str]:
    replacements = build_replacements_from_workbook(extract_workbook)
    template = template.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with fitz.open(template) as doc:
        page = doc[0]
        slots = {label: _find_replacement_slot(page, label) for label in FIELD_LABELS}
        registered_fonts: set[str] = set()
        for slot in slots.values():
            page.add_redact_annot(slot.erase_rect, fill=(1.0, 1.0, 1.0))
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        for label in FIELD_LABELS:
            slot = slots[label]
            text = replacements[label]
            font_path = _font_path_for_display_font(slot.font_name)
            pdf_font_name = slot.font_name
            fontfile = None
            if font_path is not None:
                fontfile = str(font_path)
                if pdf_font_name not in registered_fonts:
                    page.insert_font(fontname=pdf_font_name, fontfile=fontfile)
                    registered_fonts.add(pdf_font_name)
            else:
                pdf_font_name = _resolve_font_name(page, slot.font_name)
            fontsize = _fit_font_size(text, slot, font_path)
            result = page.insert_text(
                slot.origin,
                text,
                fontsize=fontsize,
                fontname=pdf_font_name,
                fontfile=fontfile,
                color=slot.color,
            )
            if result <= 0:
                raise ValueError(f"Replacement text for '{label}' could not be inserted.")

        _replace_chart_images(doc, output, extract_workbook)
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
