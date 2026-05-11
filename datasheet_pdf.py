#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import fitz
import pandas as pd

from datasheet.asset_catalog import build_asset_catalog
from datasheet.pdf_models import ChartReplacement, ChartSlot, ReplacementSlot, TechnicalDataRowSlot, TextSpan
from datasheet.models import (
    FIELD_LABELS,
    FIELD_LABEL_ALIASES,
    TECHNICAL_DATA_PLACEHOLDER,
    TECHNICAL_DATA_RESERVED_KEYS,
    DatasheetModel,
    TechnicalDataEntry,
    build_performance_fields,
    load_technical_data_entries,
    normalize_technical_key,
    polarization_keys_from_source_files,
    technical_data_by_key,
    text_or_placeholder,
)
from datasheet.service import build_render_context
from datasheet.tables import (
    ResolvedDatasheetTables,
    canonical_key_for_template,
    extra_rows_for_sections,
    is_electrical_section,
    is_mechanical_section,
    resolve_datasheet_tables,
    row_for_fixed_label,
)
from datasheet.templates import DatasheetTemplateAdapter, NETQUI_1POL_TEMPLATE_MANIFEST, TemplateChartManifest, TemplateChartSlot
from datasheet.layouts.netqui_1pol import (
    NETQUI_POLAR_LEGEND_SCALE_CAP,
    NETQUI_SIDE_LEGEND_SCALE_CAP,
    align_1pol_cartesian_slots,
    beamwidth_rects as netqui_beamwidth_rects,
    polar_rects as netqui_polar_rects,
    top_chart_rects as netqui_top_chart_rects,
)
from datasheet.layouts.rfe import order_chart_slots_first_two_then_x
from plotting.config import CARTESIAN_FIGURE_HEIGHT_IN, CARTESIAN_FIGURE_WIDTH_IN, POLAR_FIGURE_SIZE_IN

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

MISSING_VALUE_COLOR = (0.9, 0.0, 0.0)
NETQUI_TABLE_FONT_SIZE = 9.0
NETQUI_TABLE_VERTICAL_OFFSET = 1.4
NETQUI_CHART_HEADING_GAP = 4.0
NETQUI_SECTION_GAP = 16.0
NETQUI_HEADING_FONT = "OpenSans-Medium"
NETQUI_HEADING_FONT_FILE = Path(r"C:\Windows\Fonts\OpenSans-Semibold.ttf")
NETQUI_CHART_SECTION_TITLES = {
    "ANTENNA GAIN",
    "VSWR",
    "ANTENNA BEAMWIDTH",
    "RADIATION PATTERNS",
}
PERFORMANCE_FIELD_KEYS = {
    re.sub(r"\s+", " ", str(alias or "").strip()).lower()
    for aliases in FIELD_LABEL_ALIASES.values()
    for alias in aliases
    if str(alias or "").strip()
}


def emit_progress(stage: str, current: int, total: int, label: str) -> None:
    print(
        f"AT_PROGRESS {json.dumps({'stage': stage, 'current': int(current), 'total': int(total), 'label': label})}",
        flush=True,
    )

PDF_METADATA_KEYS = (
    "title",
    "author",
    "subject",
    "keywords",
    "creator",
    "producer",
    "creationDate",
    "modDate",
    "trapped",
)
PDF_CREATOR = "Antenna Toolkit"
PDF_PRODUCER = "Antenna Toolkit (PyMuPDF)"


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


def _polarization_keys_from_source_files(ffs_summary: pd.DataFrame) -> pd.Series:
    return polarization_keys_from_source_files(ffs_summary)


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
    if len(ffs_summary) == 1:
        return "Single Polarization"
    raise ValueError("Unable to derive polarization from the extracted workbook.")


def build_replacements_from_workbook(extract_workbook: Path) -> dict[str, str]:
    return build_performance_fields(extract_workbook)


def _normalize_technical_key(value: object) -> str:
    return normalize_technical_key(value)


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


def load_technical_data_workbook(path: Path) -> list[TechnicalDataEntry]:
    return load_technical_data_entries(path)


def _technical_data_by_key(entries: list[TechnicalDataEntry]) -> dict[str, TechnicalDataEntry]:
    return technical_data_by_key(entries)


def _text_or_placeholder(value: str) -> tuple[str, bool]:
    return text_or_placeholder(value)


def _register_pdf_font(
    page: fitz.Page,
    display_font: str,
    registered_fonts: set[str],
    required_text: str | None = None,
) -> tuple[str, str | None, Path | None]:
    font_path = _font_path_for_display_font(display_font)
    pdf_font_name = display_font
    fontfile = None
    if font_path is not None:
        fontfile = str(font_path)
        page.insert_font(fontname=pdf_font_name, fontfile=fontfile)
        registered_fonts.add(pdf_font_name)
    else:
        if required_text is not None and not _embedded_font_supports_text(page, display_font, required_text):
            return "helv", None, None
        pdf_font_name = _resolve_font_name(page, display_font)
    return pdf_font_name, fontfile, font_path


def _insert_fit_textbox(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    font_name: str,
    font_size: float,
    color: tuple[float, float, float],
    registered_fonts: set[str],
) -> None:
    pdf_font_name, fontfile, _font_path = _register_pdf_font(page, font_name, registered_fonts, required_text=text)
    size = float(font_size)
    for _attempt in range(8):
        result = page.insert_textbox(
            rect,
            text,
            fontsize=size,
            fontname=pdf_font_name,
            fontfile=fontfile,
            color=color,
            align=fitz.TEXT_ALIGN_LEFT,
        )
        if result >= 0:
            return
        size *= 0.9
    page.insert_text((rect.x0, rect.y0 + max(size, 1.0)), text, fontsize=size, fontname=pdf_font_name, fontfile=fontfile, color=color)


def _wrap_text_to_width(text: str, font: fitz.Font, font_size: float, max_width: float) -> list[str]:
    words = str(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or font.text_length(candidate, fontsize=font_size) <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
        if font.text_length(current, fontsize=font_size) <= max_width:
            continue
        pieces: list[str] = []
        piece = ""
        for char in current:
            if piece and font.text_length(piece + char, fontsize=font_size) > max_width:
                pieces.append(piece)
                piece = char
            else:
                piece += char
        if pieces:
            lines.extend(pieces)
        current = piece
    if current:
        lines.append(current)
    return lines or [""]


def _insert_wrapped_text(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    origin: tuple[float, float] | None,
    font_name: str,
    font_size: float,
    color: tuple[float, float, float],
    registered_fonts: set[str],
    center_vertically: bool = False,
    vertical_offset: float = 0.0,
    line_height_factor: float = 1.2,
) -> None:
    pdf_font_name, fontfile, font_path = _register_pdf_font(page, font_name, registered_fonts, required_text=text)
    font = _measurement_font(pdf_font_name, str(font_path) if font_path else None)
    lines = _wrap_text_to_width(text, font, font_size, max(1.0, rect.width))
    line_height = max(font_size * line_height_factor, font_size + 1.0)
    x = rect.x0 if origin is None else origin[0]
    if origin is None and center_vertically:
        ascender = float(getattr(font, "ascender", 1.0))
        descender = float(getattr(font, "descender", -0.25))
        glyph_height = max(0.1, (ascender - descender) * font_size)
        total_height = glyph_height + (max(1, len(lines)) - 1) * line_height
        first_baseline = rect.y0 + max(0.0, (rect.height - total_height) / 2.0) + ascender * font_size + vertical_offset
    else:
        first_baseline = (rect.y0 + font_size) if origin is None else origin[1]
    max_baseline = rect.y1 + 0.8
    for index, line in enumerate(lines):
        baseline = first_baseline + (index * line_height)
        if baseline > max_baseline and index > 0:
            break
        page.insert_text(
            (x, baseline),
            line,
            fontsize=font_size,
            fontname=pdf_font_name,
            fontfile=fontfile,
            color=color,
        )


def _technical_table_font_size(font_size: float, layout_mode: str) -> float:
    if layout_mode in {"netqui", "netqui_1pol"}:
        return min(font_size, NETQUI_TABLE_FONT_SIZE)
    return font_size


def _wrapped_text_height(
    page: fitz.Page,
    text: str,
    *,
    font_name: str,
    font_size: float,
    width: float,
    registered_fonts: set[str],
    line_height_factor: float = 1.2,
) -> float:
    pdf_font_name, _fontfile, font_path = _register_pdf_font(page, font_name, registered_fonts, required_text=text)
    font = _measurement_font(pdf_font_name, str(font_path) if font_path else None)
    lines = _wrap_text_to_width(text, font, font_size, max(1.0, width))
    line_height = max(font_size * line_height_factor, font_size + 1.0)
    ascender = float(getattr(font, "ascender", 1.0))
    descender = float(getattr(font, "descender", -0.25))
    glyph_height = max(0.1, (ascender - descender) * font_size)
    return glyph_height + (max(1, len(lines)) - 1) * line_height


def _loose_technical_key(value: object) -> str:
    text = re.sub(r"[\u200B-\u200D\uFEFF]", "", str(value or "")).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _technical_labels_match(template_label: str, entry_label: str) -> bool:
    template_key = _normalize_technical_key(template_label)
    entry_key = _normalize_technical_key(entry_label)
    if template_key == entry_key:
        return True
    loose_template = _loose_technical_key(template_label)
    loose_entry = _loose_technical_key(entry_label)
    if loose_template == loose_entry:
        return True
    if "dimension" in loose_template and "dimension" in loose_entry:
        return True
    return bool(loose_template and loose_entry and (loose_template in loose_entry or loose_entry in loose_template))


def _insert_replacement_slot_text(
    page: fitz.Page,
    slot: ReplacementSlot,
    text: str,
    *,
    registered_fonts: set[str],
    color: tuple[float, float, float] | None = None,
) -> None:
    pdf_font_name, fontfile, font_path = _register_pdf_font(page, slot.font_name, registered_fonts, required_text=text)
    fontsize = _fit_font_size(text, slot, font_path)
    result = page.insert_text(
        slot.origin,
        text,
        fontsize=fontsize,
        fontname=pdf_font_name,
        fontfile=fontfile,
        color=color or slot.color,
    )
    if result <= 0:
        raise ValueError(f"Replacement text for '{slot.label}' could not be inserted.")


def _find_span_exact(page: fitz.Page, text: str, spans: list[TextSpan] | None = None) -> TextSpan | None:
    page_spans = spans if spans is not None else _extract_page_spans(page)
    return next((span for span in page_spans if span.text == text), None)


def _technical_data_region(page: fitz.Page, spans: list[TextSpan] | None = None) -> tuple[float, float] | None:
    technical_heading = _find_span_exact(page, "TECHNICAL DATA", spans)
    performance_heading = _find_span_exact(page, "PERFORMANCE", spans)
    if technical_heading is None or performance_heading is None:
        return None
    return technical_heading.bbox.y1, performance_heading.bbox.y0


def _netqui_technical_data_bounds(
    page: fitz.Page,
    spans: list[TextSpan],
) -> tuple[TextSpan, TextSpan, float] | None:
    electrical_heading = _find_span_exact(page, "ELECTRICAL DATA", spans)
    mechanical_heading = _find_span_exact(page, "MECHANICAL DATA", spans)
    if electrical_heading is None or mechanical_heading is None:
        return None
    lower_bound_candidates = [
        span.bbox.y0
        for span in spans
        if span.text in {"DIMMENSIONS", "DIMENSIONS"} and span.bbox.y0 > electrical_heading.bbox.y1
    ]
    if not lower_bound_candidates:
        return None
    return electrical_heading, mechanical_heading, min(lower_bound_candidates)


def _technical_table_separators(page: fitz.Page, top_y: float, bottom_y: float) -> tuple[list[float], float]:
    separators: list[float] = []
    table_right = 299.0
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        width = drawing.get("width")
        color = drawing.get("color")
        if rect is None or width is None or color is None:
            continue
        if not (top_y < rect.y0 < bottom_y):
            continue
        if abs(rect.y1 - rect.y0) > 0.2 or width > 0.75:
            continue
        if not (rect.x0 <= 150.0 and rect.x1 >= 130.0):
            continue
        y = float(rect.y0)
        if not any(abs(existing - y) <= 0.2 for existing in separators):
            separators.append(y)
        table_right = max(table_right, float(rect.x1))
    return sorted(separators), table_right


def _redraw_split_table_separators(page: fitz.Page) -> None:
    segments: list[tuple[fitz.Rect, float, tuple[float, float, float]]] = []
    for drawing in page.get_drawings():
        rect = drawing.get("rect")
        width = drawing.get("width")
        color = drawing.get("color")
        if rect is None or width is None or color is None:
            continue
        if abs(rect.y1 - rect.y0) > 0.2 or width > 0.75:
            continue
        segments.append((fitz.Rect(rect), float(width), color))

    redrawn: set[tuple[float, float, float, float, tuple[float, float, float]]] = set()
    for left, width, color in segments:
        if not (35.0 <= left.x0 <= 38.0 and 137.0 <= left.x1 <= 139.0):
            continue
        right = next(
            (
                rect
                for rect, right_width, right_color in segments
                if abs(rect.y0 - left.y0) <= 0.2
                and abs(rect.x0 - left.x1) <= 0.8
                and 295.0 <= rect.x1 <= 305.0
                and abs(right_width - width) <= 0.05
                and all(abs(a - b) <= 0.01 for a, b in zip(right_color, color))
            ),
            None,
        )
        if right is None:
            continue
        key = (
            round(left.x0, 3),
            round(left.y0, 3),
            round(right.x1, 3),
            round(width, 3),
            tuple(round(component, 6) for component in color),
        )
        if key in redrawn:
            continue
        redrawn.add(key)
        page.draw_line(
            (left.x0, left.y0),
            (right.x1, left.y0),
            color=color,
            width=width,
            overlay=True,
        )


def _redraw_netqui_table_separators(page: fitz.Page, layout_mode: str) -> None:
    if layout_mode not in {"netqui", "netqui_1pol"}:
        return
    slots = _technical_data_row_slots(page, layout_mode=layout_mode)
    if not slots:
        return

    line_color = (0.13669031858444214, 0.12195010483264923, 0.1252918243408203)
    seen: set[tuple[float, float, float]] = set()
    for slot in slots:
        line_left = 36.638 if slot.label_rect.x0 < 280.0 else max(302.25, slot.label_rect.x0)
        line_right = slot.table_right
        key = (round(line_left, 3), round(slot.row_bottom, 3), round(line_right, 3))
        if key in seen:
            continue
        seen.add(key)
        page.draw_line(
            (line_left, slot.row_bottom),
            (line_right, slot.row_bottom),
            color=line_color,
            width=0.25,
            overlay=True,
        )


def _redraw_template_table_separators(page: fitz.Page, adapter: DatasheetTemplateAdapter | None) -> None:
    layout_mode = adapter.technical_layout_mode if adapter is not None else "auto"
    if layout_mode in {"netqui", "netqui_1pol"}:
        _redraw_netqui_table_separators(page, layout_mode)
        return
    _redraw_split_table_separators(page)
    _redraw_netqui_table_separators(page, layout_mode)


def _technical_data_row_slots(page: fitz.Page, *, layout_mode: str = "auto") -> list[TechnicalDataRowSlot]:
    spans = _extract_page_spans(page)
    region = _technical_data_region(page, spans) if layout_mode in {"auto", "generic"} else None
    if region is not None:
        top_y, bottom_y = region
        separators, detected_table_right = _technical_table_separators(page, top_y, bottom_y)
        labels = [
            span
            for span in spans
            if top_y < span.bbox.y0 < bottom_y
            and 25.0 <= span.bbox.x0 <= 125.0
            and span.bbox.x1 <= 138.0
        ]
        labels.sort(key=lambda span: (span.bbox.y0, span.bbox.x0))
        if not labels:
            return []

        value_x = 140.0
        table_right = min(page.rect.x1 - 20.0, detected_table_right)
        slots: list[TechnicalDataRowSlot] = []
        for index, label_span in enumerate(labels):
            next_separator = next((y for y in separators if y > label_span.bbox.y1 + 0.3), None)
            previous_separator = max((y for y in separators if y < label_span.bbox.y0 - 0.3), default=None)
            if previous_separator is not None:
                row_top = max(top_y, previous_separator + 0.5)
            else:
                row_top = max(top_y, label_span.bbox.y0 - 1.0)
            if next_separator is not None:
                row_bottom = next_separator
            else:
                next_y = labels[index + 1].bbox.y0 if index + 1 < len(labels) else min(bottom_y - 6.0, label_span.bbox.y0 + 13.0)
                row_bottom = max(label_span.bbox.y1 + 2.0, min(bottom_y - 4.0, next_y - 1.0))
            value_spans = [
                span
                for span in spans
                if value_x - 3.0 <= span.bbox.x0 <= table_right + 2.0
                and row_top - 1.0 <= span.bbox.y0 < row_bottom + 1.0
            ]
            value_origin_span = value_spans[0] if value_spans else label_span
            value_style_span = value_origin_span
            if (
                label_span.text == "Temperature"
                and len(value_spans) > 1
                and value_origin_span.text.strip() in {"-", "+"}
            ):
                value_style_span = value_spans[1]
            slots.append(
                TechnicalDataRowSlot(
                    label=label_span.text,
                    label_rect=fitz.Rect(label_span.bbox),
                    value_rect=fitz.Rect(value_x, row_top, table_right, row_bottom),
                    erase_rect=fitz.Rect(value_x - 2.0, row_top, table_right + 2.0, row_bottom + 1.0),
                    label_font_name=label_span.font,
                    label_font_size=float(label_span.size),
                    label_color=_int_color_to_rgb(label_span.color),
                    value_font_name=value_style_span.font,
                    value_font_size=float(value_style_span.size),
                    value_origin=value_origin_span.origin,
                    value_color=_int_color_to_rgb(value_style_span.color),
                    row_bottom=row_bottom,
                    table_right=table_right,
                )
            )
        return slots

    netqui_bounds = _netqui_technical_data_bounds(page, spans) if layout_mode in {"auto", "netqui", "netqui_1pol"} else None
    if netqui_bounds is None:
        return []

    electrical_heading, mechanical_heading, bottom_y = netqui_bounds
    sections = [
        {
            "heading": electrical_heading,
            "label_x0": 25.0,
            "label_x1": 140.0,
            "value_x": 148.5,
            "table_right": 280.0,
        },
        {
            "heading": mechanical_heading,
            "label_x0": 285.0,
            "label_x1": 425.0,
            "value_x": 433.5,
            "table_right": min(page.rect.x1 - 20.0, 548.0),
        },
    ]
    slots: list[TechnicalDataRowSlot] = []
    for section in sections:
        labels = [
            span
            for span in spans
            if (label_text := span.text.strip().replace("\u200b", ""))
            and label_text.upper() not in {"DIMMENSIONS", "DIMENSIONS"}
            and span.bbox.y0 > section["heading"].bbox.y1
            and span.bbox.y0 < bottom_y
            and section["label_x0"] <= span.bbox.x0 <= section["label_x1"]
            and span.bbox.x1 <= section["label_x1"] + 18.0
        ]
        labels.sort(key=lambda span: (span.bbox.y0, span.bbox.x0))
        for index, label_span in enumerate(labels):
            row_top = max(section["heading"].bbox.y1 + 1.0, label_span.bbox.y0 - 1.0)
            next_y = labels[index + 1].bbox.y0 if index + 1 < len(labels) else label_span.bbox.y1 + 3.0
            row_bottom = max(label_span.bbox.y1 + 2.0, min(bottom_y - 4.0, next_y - 1.0))
            value_spans = [
                span
                for span in spans
                if section["value_x"] - 4.0 <= span.bbox.x0 <= section["table_right"] + 2.0
                and row_top - 1.0 <= span.bbox.y0 < row_bottom + 1.0
            ]
            value_origin_span = value_spans[0] if value_spans else label_span
            value_style_span = value_origin_span
            slots.append(
                TechnicalDataRowSlot(
                    label=label_span.text,
                    label_rect=fitz.Rect(label_span.bbox),
                    value_rect=fitz.Rect(section["value_x"], row_top, section["table_right"], row_bottom),
                    erase_rect=fitz.Rect(section["value_x"] - 2.0, row_top, section["table_right"] + 2.0, row_bottom + 1.0),
                    label_font_name=label_span.font,
                    label_font_size=float(label_span.size),
                    label_color=_int_color_to_rgb(label_span.color),
                    value_font_name=value_style_span.font,
                    value_font_size=float(value_style_span.size),
                    value_origin=(section["value_x"], value_origin_span.origin[1]),
                    value_color=_int_color_to_rgb(value_style_span.color),
                    row_bottom=row_bottom,
                    table_right=section["table_right"],
                )
            )
    return slots


def _draw_technical_data_row(
    page: fitz.Page,
    label: str,
    value: str,
    rect: fitz.Rect,
    *,
    label_font_name: str,
    value_font_name: str,
    font_size: float,
    label_color: tuple[float, float, float],
    value_color: tuple[float, float, float],
    table_right: float,
    registered_fonts: set[str],
) -> None:
    label_rect = fitz.Rect(38.0, rect.y0, 136.0, rect.y1)
    value_rect = fitz.Rect(140.0, rect.y0, table_right, rect.y1)
    _insert_wrapped_text(
        page,
        label_rect,
        label,
        origin=None,
        font_name=label_font_name,
        font_size=font_size,
        color=label_color,
        registered_fonts=registered_fonts,
        center_vertically=True,
    )
    text, is_missing = _text_or_placeholder(value)
    _insert_wrapped_text(
        page,
        value_rect,
        text,
        origin=None,
        font_name=value_font_name,
        font_size=font_size,
        color=MISSING_VALUE_COLOR if is_missing else value_color,
        registered_fonts=registered_fonts,
        center_vertically=True,
    )
    page.draw_line(
        (36.638, rect.y1),
        (table_right, rect.y1),
        color=(0.13669031858444214, 0.12195010483264923, 0.1252918243408203),
        width=0.25,
        overlay=True,
    )


def _technical_data_row_step(slots: list[TechnicalDataRowSlot]) -> float:
    deltas = [
        slots[index].row_bottom - slots[index - 1].row_bottom
        for index in range(1, len(slots))
        if 9.0 <= slots[index].row_bottom - slots[index - 1].row_bottom <= 18.0
    ]
    if not deltas:
        return 12.0
    rounded = [round(delta * 2.0) / 2.0 for delta in deltas]
    return Counter(rounded).most_common(1)[0][0]


def _technical_table_row_height(
    page: fitz.Page,
    *,
    label: str,
    value: str,
    label_font_name: str,
    value_font_name: str,
    font_size: float,
    label_width: float,
    value_width: float,
    minimum_height: float,
    registered_fonts: set[str],
) -> float:
    label_height = _wrapped_text_height(
        page,
        label,
        font_name=label_font_name,
        font_size=font_size,
        width=label_width,
        registered_fonts=registered_fonts,
    )
    value_height = _wrapped_text_height(
        page,
        value,
        font_name=value_font_name,
        font_size=font_size,
        width=value_width,
        registered_fonts=registered_fonts,
    )
    return max(minimum_height, label_height + 4.0, value_height + 4.0)


def _replace_technical_table(
    doc: fitz.Document,
    tables: ResolvedDatasheetTables,
    *,
    adapter: DatasheetTemplateAdapter | None = None,
    registered_fonts: set[str],
) -> None:
    page = doc[0]
    layout_mode = adapter.technical_layout_mode if adapter is not None else "auto"
    if layout_mode in {"netqui", "netqui_1pol"}:
        return
    slots = _technical_data_row_slots(page, layout_mode=layout_mode)
    if not slots:
        return
    used_keys: set[str] = set()
    editable_slots = [
        slot
        for slot in slots
        if (key := canonical_key_for_template(slot.label, adapter))
        and key not in PERFORMANCE_FIELD_KEYS
    ]
    if not editable_slots:
        return

    row_step = _technical_data_row_step(slots)
    minimum_height = max(1.0, row_step - 0.5)
    table_left = min(36.638, min(slot.label_rect.x0 for slot in editable_slots) - 1.0)
    table_right = max(slot.table_right for slot in editable_slots)
    table_top = min(slot.value_rect.y0 for slot in editable_slots) - 1.0
    row_specs: list[tuple[TechnicalDataRowSlot, str, bool, float]] = []
    prototype = editable_slots[-1]
    for slot in editable_slots:
        row = row_for_fixed_label(tables, slot.label)
        if row is not None and row.canonical_key:
            used_keys.add(row.canonical_key)
        text, is_missing = _text_or_placeholder(row.value if row is not None else "")
        font_size = _technical_table_font_size(slot.value_font_size, layout_mode)
        row_height = _technical_table_row_height(
            page,
            label=slot.label,
            value=text,
            label_font_name=slot.label_font_name,
            value_font_name=slot.value_font_name,
            font_size=font_size,
            label_width=max(slot.label_rect.width, slot.value_rect.x0 - slot.label_rect.x0 - 4.0),
            value_width=slot.value_rect.width,
            minimum_height=minimum_height,
            registered_fonts=registered_fonts,
        )
        row_specs.append((slot, text, is_missing, row_height))

    extra_entries = extra_rows_for_sections(tables, used_keys=used_keys, section_filter=is_mechanical_section)
    region = _technical_data_region(page)
    bottom_limit = (region[1] - 8.0) if region else page.rect.y1 - 72.0
    y = table_top
    dynamic_bottom = table_top
    remaining: list[TechnicalDataEntry] = []
    extra_specs: list[tuple[TechnicalDataEntry, float]] = []
    drawable_extra_specs: list[tuple[TechnicalDataEntry, float]] = []
    for entry in extra_entries:
        text, _is_missing = _text_or_placeholder(entry.value)
        row_height = _technical_table_row_height(
            page,
            label=entry.label,
            value=text,
            label_font_name=prototype.label_font_name,
            value_font_name=prototype.value_font_name,
            font_size=prototype.value_font_size,
            label_width=max(prototype.label_rect.width, prototype.value_rect.x0 - prototype.label_rect.x0 - 4.0),
            value_width=prototype.value_rect.width,
            minimum_height=minimum_height,
            registered_fonts=registered_fonts,
        )
        extra_specs.append((entry, row_height))

    for _slot, _text, _is_missing, row_height in row_specs:
        dynamic_bottom = y + row_height
        y = dynamic_bottom
    for entry, row_height in extra_specs:
        if y + row_height > bottom_limit:
            remaining.append(entry)
            continue
        drawable_extra_specs.append((entry, row_height))
        dynamic_bottom = y + row_height
        y = dynamic_bottom

    erase_bottom = min(bottom_limit, max(max(slot.row_bottom for slot in editable_slots), dynamic_bottom) + 1.0)
    erase_rect = fitz.Rect(table_left - 1.0, table_top, table_right + 1.0, erase_bottom)
    page.add_redact_annot(erase_rect, fill=None)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED)
    page.draw_rect(
        erase_rect,
        color=(1.0, 1.0, 1.0),
        fill=(1.0, 1.0, 1.0),
        overlay=True,
    )

    line_color = (0.13669031858444214, 0.12195010483264923, 0.1252918243408203)
    y = table_top
    for slot, text, is_missing, row_height in row_specs:
        row_rect = fitz.Rect(table_left, y, table_right, y + row_height)
        label_rect = fitz.Rect(slot.label_rect.x0, row_rect.y0, slot.value_rect.x0 - 4.0, row_rect.y1)
        value_rect = fitz.Rect(slot.value_rect.x0, row_rect.y0, slot.value_rect.x1, row_rect.y1)
        font_size = _technical_table_font_size(slot.value_font_size, layout_mode)
        _insert_wrapped_text(
            page,
            label_rect,
            slot.label,
            origin=None,
            font_name=slot.label_font_name,
            font_size=font_size,
            color=slot.label_color,
            registered_fonts=registered_fonts,
            center_vertically=True,
        )
        _insert_wrapped_text(
            page,
            value_rect,
            text,
            origin=None,
            font_name=slot.value_font_name,
            font_size=font_size,
            color=MISSING_VALUE_COLOR if is_missing else slot.value_color,
            registered_fonts=registered_fonts,
            center_vertically=True,
        )
        page.draw_line((table_left, row_rect.y1), (table_right, row_rect.y1), color=line_color, width=0.25, overlay=True)
        y = row_rect.y1

    for entry, row_height in drawable_extra_specs:
        row_rect = fitz.Rect(table_left, y, table_right, y + row_height)
        _draw_technical_data_row(
            page,
            entry.label,
            entry.value,
            row_rect,
            label_font_name=prototype.label_font_name,
            value_font_name=prototype.value_font_name,
            font_size=prototype.value_font_size,
            label_color=prototype.label_color,
            value_color=prototype.value_color,
            table_right=prototype.table_right,
            registered_fonts=registered_fonts,
        )
        y = row_rect.y1

    if remaining:
        _insert_technical_continuation_page(doc, remaining, prototype, registered_fonts=registered_fonts)


def _insert_technical_continuation_page(
    doc: fitz.Document,
    entries: list[TechnicalDataEntry],
    prototype: TechnicalDataRowSlot,
    *,
    registered_fonts: set[str],
) -> None:
    source_page = doc[0]
    page = doc.new_page(pno=1, width=source_page.rect.width, height=source_page.rect.height)
    heading_font = "MyriadPro-Semibold" if MYRIAD_FONT_FILES["MyriadPro-Semibold"].exists() else "helv"
    pdf_font_name, fontfile, _font_path = _register_pdf_font(page, heading_font, registered_fonts, required_text="TECHNICAL DATA")
    page.insert_text((38.0, 58.0), "TECHNICAL DATA", fontsize=10.0, fontname=pdf_font_name, fontfile=fontfile, color=(0.237, 0.237, 0.237))
    y = 78.0
    row_height = 16.0
    for entry in entries:
        if y + row_height > page.rect.y1 - 58.0:
            break
        _draw_technical_data_row(
            page,
            entry.label,
            entry.value,
            fitz.Rect(38.0, y, prototype.table_right, y + row_height),
            label_font_name=prototype.label_font_name,
            value_font_name=prototype.value_font_name,
            font_size=prototype.value_font_size,
            label_color=prototype.label_color,
            value_color=prototype.value_color,
            table_right=prototype.table_right,
            registered_fonts=registered_fonts,
        )
        y += row_height


def _insert_performance_extra_rows(
    doc: fitz.Document,
    page: fitz.Page,
    slots: dict[str, ReplacementSlot],
    tables: ResolvedDatasheetTables,
    *,
    adapter: DatasheetTemplateAdapter | None = None,
    registered_fonts: set[str],
) -> None:
    if not slots:
        return
    used_keys = {canonical_key_for_template(label, adapter) for label in slots}
    extras = extra_rows_for_sections(tables, used_keys=used_keys, section_filter=is_electrical_section)
    if not extras:
        return

    ordered_slots = sorted(slots.values(), key=lambda slot: (slot.origin[1], slot.origin[0]))
    prototype = ordered_slots[-1]
    row_height = max(14.0, prototype.font_size + 7.0)
    label_x = 38.0
    value_x = prototype.origin[0]
    table_right = min(page.rect.x1 - 20.0, max(value_x + prototype.max_width, value_x + 160.0))
    y = prototype.origin[1] + row_height
    remaining: list[TechnicalDataEntry] = []
    for row in extras:
        if y + row_height > page.rect.y1 - 58.0:
            remaining.append(row)
            continue
        pdf_font_name, fontfile, _font_path = _register_pdf_font(page, prototype.font_name, registered_fonts, required_text=row.label)
        page.insert_text(
            (label_x, y),
            row.label,
            fontsize=prototype.font_size,
            fontname=pdf_font_name,
            fontfile=fontfile,
            color=prototype.color,
        )
        _insert_wrapped_text(
            page,
            fitz.Rect(value_x, y - prototype.font_size, table_right, y + row_height - prototype.font_size),
            row.value,
            origin=(value_x, y),
            font_name=prototype.font_name,
            font_size=prototype.font_size,
            color=prototype.color,
            registered_fonts=registered_fonts,
        )
        y += row_height

    if not remaining:
        return
    continuation = doc.new_page(pno=1, width=page.rect.width, height=page.rect.height)
    heading_font = "MyriadPro-Semibold" if MYRIAD_FONT_FILES["MyriadPro-Semibold"].exists() else "helv"
    pdf_font_name, fontfile, _font_path = _register_pdf_font(continuation, heading_font, registered_fonts, required_text="PERFORMANCE")
    continuation.insert_text((38.0, 58.0), "PERFORMANCE", fontsize=10.0, fontname=pdf_font_name, fontfile=fontfile, color=(0.237, 0.237, 0.237))
    y = 78.0
    for row in remaining:
        if y + row_height > continuation.rect.y1 - 58.0:
            break
        row_font_name, row_fontfile, _row_font_path = _register_pdf_font(continuation, prototype.font_name, registered_fonts, required_text=row.label)
        continuation.insert_text((label_x, y), row.label, fontsize=prototype.font_size, fontname=row_font_name, fontfile=row_fontfile, color=prototype.color)
        _insert_wrapped_text(
            continuation,
            fitz.Rect(value_x, y - prototype.font_size, table_right, y + row_height - prototype.font_size),
            row.value,
            origin=(value_x, y),
            font_name=prototype.font_name,
            font_size=prototype.font_size,
            color=prototype.color,
            registered_fonts=registered_fonts,
        )
        y += row_height


def _netqui_entry_for_slot(slot: TechnicalDataRowSlot, entries: list[TechnicalDataEntry]) -> TechnicalDataEntry | None:
    key = _normalize_technical_key(slot.label)
    data_by_key = _technical_data_by_key(entries)
    if key in data_by_key:
        return data_by_key[key]
    for entry in entries:
        if _technical_labels_match(slot.label, entry.label):
            return entry
    return None


def _netqui_slot_text(
    slot: TechnicalDataRowSlot,
    tables: ResolvedDatasheetTables,
) -> tuple[str, bool, bool, str]:
    row = row_for_fixed_label(tables, slot.label)
    text, is_missing = _text_or_placeholder(row.value if row is not None else "")
    source = row.source if row is not None else ""
    key = row.canonical_key if row is not None else canonical_key_for_template(slot.label, tables.adapter)
    return text, is_missing, source == "generated", key


def _netqui_row_layout(
    page: fitz.Page,
    slots: list[TechnicalDataRowSlot],
    tables: ResolvedDatasheetTables,
    *,
    font_size: float,
    bottom_limit: float,
    registered_fonts: set[str],
) -> list[tuple[TechnicalDataRowSlot, str, bool, bool, float, str]]:
    measured_rows: list[tuple[TechnicalDataRowSlot, str, bool, bool, float, float, str]] = []
    for slot in slots:
        text, is_missing, is_performance, key = _netqui_slot_text(slot, tables)
        value_height = _wrapped_text_height(
            page,
            text,
            font_name=slot.value_font_name,
            font_size=font_size,
            width=slot.value_rect.width,
            registered_fonts=registered_fonts,
            line_height_factor=1.3,
        )
        label_height = _wrapped_text_height(
            page,
            slot.label,
            font_name=slot.label_font_name,
            font_size=font_size,
            width=slot.label_rect.width,
            registered_fonts=registered_fonts,
        )
        original_height = max(1.0, slot.row_bottom - slot.value_rect.y0)
        if value_height <= font_size * 1.6 and label_height <= font_size * 1.6:
            row_height = original_height
        else:
            row_height = max(original_height, value_height + 6.0, label_height + 4.0)
        measured_rows.append((slot, text, is_missing, is_performance, original_height, row_height, key))

    return [(slot, text, is_missing, is_performance, row_height, key) for slot, text, is_missing, is_performance, _original_height, row_height, key in measured_rows]


def _netqui_rows_bottom(rows: list[tuple[TechnicalDataRowSlot, str, bool, bool, float, str]]) -> float:
    offset = 0.0
    dynamic_bottom = 0.0
    for slot, _text, _is_missing, _is_performance, row_height, _key in rows:
        dynamic_bottom = max(dynamic_bottom, slot.value_rect.y0 + offset + row_height)
        offset = dynamic_bottom - slot.row_bottom
    return dynamic_bottom


def _netqui_extra_row_slot(prototype: TechnicalDataRowSlot, label: str, y: float, row_height: float) -> TechnicalDataRowSlot:
    label_width = prototype.label_rect.width
    return TechnicalDataRowSlot(
        label=label,
        label_rect=fitz.Rect(prototype.label_rect.x0, y, prototype.label_rect.x0 + label_width, y + row_height),
        value_rect=fitz.Rect(prototype.value_rect.x0, y, prototype.value_rect.x1, y + row_height),
        erase_rect=fitz.Rect(prototype.erase_rect.x0, y, prototype.erase_rect.x1, y + row_height + 1.0),
        label_font_name=prototype.label_font_name,
        label_font_size=prototype.label_font_size,
        label_color=prototype.label_color,
        value_font_name=prototype.value_font_name,
        value_font_size=prototype.value_font_size,
        value_origin=(prototype.value_origin[0], y + prototype.value_font_size),
        value_color=prototype.value_color,
        row_bottom=y + row_height,
        table_right=prototype.table_right,
    )


def _replace_netqui_table(
    page: fitz.Page,
    tables: ResolvedDatasheetTables,
    *,
    adapter: DatasheetTemplateAdapter | None,
    registered_fonts: set[str],
) -> bool:
    layout_mode = adapter.technical_layout_mode if adapter is not None else "auto"
    if layout_mode not in {"netqui", "netqui_1pol"}:
        return False
    spans = _extract_page_spans(page)
    bounds = _netqui_technical_data_bounds(page, spans)
    if bounds is None:
        return False
    _electrical_heading, _mechanical_heading, bottom_y = bounds
    slots = _technical_data_row_slots(page, layout_mode=layout_mode)
    if not slots:
        return False

    groups = [
        [slot for slot in slots if slot.label_rect.x0 < 280.0],
        [slot for slot in slots if slot.label_rect.x0 >= 280.0],
    ]
    line_color = (0.13669031858444214, 0.12195010483264923, 0.1252918243408203)
    prepared_groups: list[tuple[list[TechnicalDataRowSlot], list[TechnicalDataRowSlot], float, float]] = []
    for group in groups:
        if not group:
            continue
        group.sort(key=lambda slot: (slot.value_rect.y0, slot.label_rect.x0))
        base_font_size = _technical_table_font_size(group[0].value_font_size, layout_mode)
        bottom_limit = bottom_y - 2.0
        used_keys = {canonical_key_for_template(slot.label, adapter) for slot in group}
        section_filter = is_electrical_section if group[0].label_rect.x0 < 280.0 else is_mechanical_section
        extra_rows = extra_rows_for_sections(tables, used_keys=used_keys, section_filter=section_filter)
        layout_slots = list(group)
        if extra_rows:
            row_step = _technical_data_row_step(group)
            row_height = max(1.0, row_step - 0.5)
            y = group[-1].row_bottom + 0.5
            prototype = group[-1]
            for extra in extra_rows:
                layout_slots.append(_netqui_extra_row_slot(prototype, extra.label, y, row_height))
                y += row_step
        prepared_groups.append((group, layout_slots, base_font_size, bottom_limit))

    if not prepared_groups:
        return False

    group_font_sizes: list[float] = []
    for _group, layout_slots, base_font_size, bottom_limit in prepared_groups:
        selected_font_size = max(7.0, base_font_size - 2.0)
        for candidate_font_size in (
            base_font_size,
            base_font_size - 0.35,
            base_font_size - 0.7,
            base_font_size - 1.0,
            base_font_size - 1.3,
            base_font_size - 1.6,
            base_font_size - 2.0,
        ):
            candidate_font_size = max(7.0, candidate_font_size)
            rows_for_candidate = _netqui_row_layout(
                page,
                layout_slots,
                tables,
                font_size=candidate_font_size,
                bottom_limit=bottom_limit,
                registered_fonts=registered_fonts,
            )
            if _netqui_rows_bottom(rows_for_candidate) <= bottom_limit:
                selected_font_size = candidate_font_size
                break
        group_font_sizes.append(selected_font_size)
    shared_font_size = min(group_font_sizes)

    for group, layout_slots, _base_font_size, _bottom_limit in prepared_groups:
        rows = _netqui_row_layout(
            page,
            layout_slots,
            tables,
            font_size=shared_font_size,
            bottom_limit=_bottom_limit,
            registered_fonts=registered_fonts,
        )
        if not rows:
            continue
        table_left = 36.638 if group[0].label_rect.x0 < 280.0 else max(302.25, min(slot.label_rect.x0 for slot in group))
        table_right = max(slot.table_right for slot in group)
        table_top = min(slot.value_rect.y0 for slot in group) - 1.0
        dynamic_bottom = max(table_top, _netqui_rows_bottom(rows))
        erase_bottom = min(bottom_y - 1.0, max(max(slot.row_bottom for slot in layout_slots), dynamic_bottom))
        erase_rect = fitz.Rect(table_left - 1.0, table_top, table_right + 1.0, erase_bottom)
        page.add_redact_annot(erase_rect, fill=None)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=0)
        page.draw_rect(
            erase_rect,
            color=(1.0, 1.0, 1.0),
            fill=(1.0, 1.0, 1.0),
            overlay=True,
        )
        offset = 0.0
        for slot, text, is_missing, is_performance, row_height, _key in rows:
            y = slot.value_rect.y0 + offset
            row_rect = fitz.Rect(table_left, y, table_right, y + row_height)
            label_rect = fitz.Rect(slot.label_rect.x0, row_rect.y0, slot.label_rect.x1, row_rect.y1)
            value_rect = fitz.Rect(slot.value_rect.x0, row_rect.y0, slot.value_rect.x1, row_rect.y1)
            _insert_wrapped_text(
                page,
                label_rect,
                slot.label,
                origin=None,
                font_name=slot.label_font_name,
                font_size=shared_font_size,
                color=slot.label_color,
                registered_fonts=registered_fonts,
                center_vertically=True,
                vertical_offset=NETQUI_TABLE_VERTICAL_OFFSET,
            )
            value_color = MISSING_VALUE_COLOR if is_missing else (0.0, 0.0, 0.0)
            _insert_wrapped_text(
                page,
                value_rect,
                text,
                origin=None,
                font_name=slot.value_font_name,
                font_size=shared_font_size,
                color=value_color,
                registered_fonts=registered_fonts,
                center_vertically=True,
                vertical_offset=NETQUI_TABLE_VERTICAL_OFFSET,
                line_height_factor=1.3,
            )
            page.draw_line(
                (table_left, row_rect.y1),
                (table_right, row_rect.y1),
                color=line_color,
                width=0.25,
                overlay=True,
            )
            offset = row_rect.y1 - slot.row_bottom
    return True


def _replace_exact_span_text(
    page: fitz.Page,
    span: TextSpan,
    text: str,
    *,
    registered_fonts: set[str],
    color: tuple[float, float, float] | None = None,
) -> None:
    rect = fitz.Rect(span.bbox)
    _remove_white_placeholder_backgrounds(page, rect)
    page.add_redact_annot(
        fitz.Rect(rect.x0 - 1.0, rect.y0 - 1.0, rect.x1 + 1.0, rect.y1 + 1.0),
        fill=None,
    )
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=0)
    font_name, fontfile, _font_path = _register_pdf_font(page, span.font, registered_fonts, required_text=text)
    page.insert_text(
        span.origin,
        text,
        fontsize=span.size,
        fontname=font_name,
        fontfile=fontfile,
        color=color or _int_color_to_rgb(span.color),
    )


def _is_white(color: tuple[float, ...] | None) -> bool:
    return color is not None and len(color) >= 3 and all(component >= 0.98 for component in color[:3])


def _remove_white_placeholder_backgrounds(page: fitz.Page, text_rect: fitz.Rect) -> None:
    background_rects: list[fitz.Rect] = []
    artifact_rects: list[fitz.Rect] = []
    expanded_text_rect = fitz.Rect(text_rect.x0 - 1.0, text_rect.y0 - 1.0, text_rect.x1 + 1.0, text_rect.y1 + 1.0)
    drawings = page.get_drawings()
    for drawing in drawings:
        rect = drawing.get("rect")
        items = drawing.get("items") or []
        fill = drawing.get("fill")
        if rect is None or fill is None:
            continue
        drawing_rect = fitz.Rect(rect)
        is_placeholder_background = (
            _is_white(fill)
            and items
            and items[0][0] == "re"
            and drawing_rect.width <= 350.0
            and drawing_rect.height <= 45.0
            and drawing_rect.intersects(text_rect)
        )
        is_placeholder_artifact = (
            not _is_white(fill)
            and drawing_rect.width <= 350.0
            and drawing_rect.height <= 18.0
            and drawing_rect.intersects(expanded_text_rect)
        )
        if is_placeholder_background:
            background_rects.append(drawing_rect)
        elif is_placeholder_artifact:
            artifact_rects.append(drawing_rect)

    _remove_matching_fill_commands(page, background_rects + artifact_rects)


_NUMBER_RE = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)")
_FILL_RECT_BLOCK_RE = re.compile(
    r"q\b(?:(?!\bQ\b).){0,500}?"
    r"(?P<x>[-+]?(?:\d+\.\d*|\.\d+|\d+))\s+"
    r"(?P<y>[-+]?(?:\d+\.\d*|\.\d+|\d+))\s+"
    r"(?P<w>[-+]?(?:\d+\.\d*|\.\d+|\d+))\s+"
    r"(?P<h>[-+]?(?:\d+\.\d*|\.\d+|\d+))\s+re\s+"
    r"(?:(?!\bQ\b).){0,250}?\b[Bf]\s*Q",
    re.DOTALL,
)
_INK_BLOCK_RE = re.compile(r"/GOOG:INKIsInker\s+BMC\s+q\b.*?\bf\s+Q\s+EMC", re.DOTALL)


def _remove_matching_fill_commands(page: fitz.Page, target_rects: list[fitz.Rect]) -> None:
    if not target_rects:
        return
    doc = page.parent
    page_height = float(page.rect.height)
    targets = [fitz.Rect(rect) for rect in target_rects]
    for xref in page.get_contents():
        original = doc.xref_stream(xref)
        try:
            text = original.decode("latin1")
        except UnicodeDecodeError:
            continue
        updated = _remove_matching_fill_rect_blocks(text, targets, page_height)
        updated = _remove_matching_ink_blocks(updated, targets, page_height)
        if updated != text:
            doc.update_stream(xref, updated.encode("latin1"))


def _remove_matching_fill_rect_blocks(content: str, target_rects: list[fitz.Rect], page_height: float) -> str:
    def replace(match: re.Match[str]) -> str:
        x = float(match.group("x"))
        y = float(match.group("y"))
        width = float(match.group("w"))
        height = float(match.group("h"))
        rect = _pdf_rect_to_page_rect(x, y, width, height, page_height)
        if any(_rects_close(rect, target, tolerance=1.2) for target in target_rects):
            return ""
        return match.group(0)

    return _FILL_RECT_BLOCK_RE.sub(replace, content)


def _remove_matching_ink_blocks(content: str, target_rects: list[fitz.Rect], page_height: float) -> str:
    def replace(match: re.Match[str]) -> str:
        rect = _ink_block_page_rect(match.group(0), page_height)
        if rect is not None and any(_rects_close(rect, target, tolerance=1.5) for target in target_rects):
            return ""
        return match.group(0)

    return _INK_BLOCK_RE.sub(replace, content)


def _pdf_rect_to_page_rect(x: float, y: float, width: float, height: float, page_height: float) -> fitz.Rect:
    x0 = min(x, x + width)
    x1 = max(x, x + width)
    y0 = min(y, y + height)
    y1 = max(y, y + height)
    return fitz.Rect(x0, page_height - y1, x1, page_height - y0)


def _rects_close(first: fitz.Rect, second: fitz.Rect, *, tolerance: float) -> bool:
    return (
        abs(first.x0 - second.x0) <= tolerance
        and abs(first.y0 - second.y0) <= tolerance
        and abs(first.x1 - second.x1) <= tolerance
        and abs(first.y1 - second.y1) <= tolerance
    )


def _ink_block_page_rect(block: str, page_height: float) -> fitz.Rect | None:
    match = re.search(r"/[A-Za-z0-9_.:-]+\s+gs\s+(?P<path>.*?)\s+f\s+Q", block, re.DOTALL)
    if match is None:
        return None
    path = match.group("path")
    tokens = re.findall(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)|re|m|l|c|h", path)
    points: list[tuple[float, float]] = []
    stack: list[float] = []
    for token in tokens:
        if _NUMBER_RE.fullmatch(token):
            stack.append(float(token))
            continue
        if token in {"m", "l"} and len(stack) >= 2:
            points.append((stack[-2], stack[-1]))
        elif token == "c" and len(stack) >= 6:
            points.extend([(stack[-6], stack[-5]), (stack[-4], stack[-3]), (stack[-2], stack[-1])])
        elif token == "re" and len(stack) >= 4:
            x, y, width, height = stack[-4], stack[-3], stack[-2], stack[-1]
            x0 = min(x, x + width)
            x1 = max(x, x + width)
            y0 = min(y, y + height)
            y1 = max(y, y + height)
            points.extend([(x0, y0), (x1, y1)])
        stack.clear()
    if not points:
        return None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return fitz.Rect(min(xs), page_height - max(ys), max(xs), page_height - min(ys))


def _replace_header_placeholders(
    doc: fitz.Document,
    entries: list[TechnicalDataEntry],
    *,
    registered_fonts: set[str],
) -> dict[str, str]:
    data_by_key = _technical_data_by_key(entries)
    replacements: dict[str, str] = {}
    placeholder_groups = (
        ("antenna name", ("ANTENNA NAME",)),
        ("product id", ("PRODUCT_ID_PLACEHOLDER", "PRODUCT_OD_PLACEHOLDER")),
    )
    for key, placeholders in placeholder_groups:
        entry = data_by_key.get(key)
        text, is_missing = _text_or_placeholder(entry.value if entry is not None else "")
        replacements[key] = text
        for page in doc:
            spans = [
                (span, placeholder)
                for span in _extract_page_spans(page)
                for placeholder in placeholders
                if placeholder in span.text
            ]
            for span in spans:
                source_span, placeholder = span
                replacement_text = source_span.text.replace(placeholder, text)
                _replace_exact_span_text(
                    page,
                    source_span,
                    replacement_text,
                    registered_fonts=registered_fonts,
                    color=MISSING_VALUE_COLOR if is_missing else None,
                )
    return replacements


def _update_footer_dates(
    doc: fitz.Document,
    generated_at: datetime,
    *,
    registered_fonts: set[str],
) -> None:
    replacement = generated_at.strftime("%m-%Y")
    pattern = re.compile(r"^\s*\d{2}-\d{4}(?:\s+v\d+)?\s*$", re.IGNORECASE)
    for page in doc:
        for span in _extract_page_spans(page):
            text = span.text.replace("\u200b", "").strip()
            if not pattern.match(text):
                continue
            _replace_exact_span_text(page, span, replacement, registered_fonts=registered_fonts)


def _update_footer_page_numbers(
    doc: fitz.Document,
    antenna_name: str,
    generated_at: datetime,
    *,
    registered_fonts: set[str],
) -> None:
    pattern = re.compile(r"^(\d+)/(\d+)\s+(.+?)\s+Rev\s+(.+)$")
    total = doc.page_count
    revision = generated_at.strftime("%m-%Y")
    for page_index, page in enumerate(doc, start=1):
        for span in _extract_page_spans(page):
            match = pattern.match(span.text)
            if not match:
                continue
            replacement = f"{page_index}/{total} {antenna_name} Rev {revision}"
            _replace_exact_span_text(page, span, replacement, registered_fonts=registered_fonts)


def _apply_technical_data(
    doc: fitz.Document,
    entries: list[TechnicalDataEntry],
    tables: ResolvedDatasheetTables,
    generated_at: datetime,
    *,
    adapter: DatasheetTemplateAdapter | None = None,
    registered_fonts: set[str],
) -> dict[str, str]:
    header_values = _replace_header_placeholders(doc, entries, registered_fonts=registered_fonts)
    _replace_technical_table(doc, tables, adapter=adapter, registered_fonts=registered_fonts)
    antenna_name = header_values.get("antenna name") or TECHNICAL_DATA_PLACEHOLDER
    _update_footer_page_numbers(doc, antenna_name, generated_at, registered_fonts=registered_fonts)
    return {
        "Antenna Name": header_values.get("antenna name", ""),
        "Product ID": header_values.get("product id", ""),
    }


def _extract_page_spans(page: fitz.Page) -> list[TextSpan]:
    spans: list[TextSpan] = []
    for block in page.get_text("dict", flags=fitz.TEXTFLAGS_TEXT).get("blocks", []):
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


def _normalized_span_text(text: str) -> str:
    stripped = re.sub(r"[\u200B-\u200D\uFEFF]", "", str(text or ""))
    return re.sub(r"\s+", " ", stripped).strip().upper()


def _shift_text_span_y(span: TextSpan, y0: float) -> TextSpan:
    dy = y0 - span.bbox.y0
    return TextSpan(
        text=_normalized_span_text(span.text),
        bbox=fitz.Rect(span.bbox.x0, span.bbox.y0 + dy, span.bbox.x1, span.bbox.y1 + dy),
        origin=(span.origin[0], span.origin[1] + dy),
        font=span.font,
        size=span.size,
        color=span.color,
    )


def _font_buffer_for_display_font(doc: fitz.Document, display_font: str) -> bytes | None:
    for page in doc:
        for font in page.get_fonts(full=True):
            xref = int(font[0])
            base_font = str(font[3] or "")
            if base_font != display_font and not base_font.endswith(f"+{display_font}"):
                continue
            try:
                _name, _ext, _font_type, font_buffer = doc.extract_font(xref)
            except Exception:
                continue
            if font_buffer:
                return bytes(font_buffer)
    return None


def _font_path_for_display_font(display_font: str) -> Path | None:
    path = MYRIAD_FONT_FILES.get(display_font)
    if path and path.exists():
        return path
    return None


def _font_supports_text(font: fitz.Font, text: str) -> bool:
    if not text or not hasattr(font, "valid_codepoints"):
        return True
    valid_codepoints = set(font.valid_codepoints())
    return all(char.isspace() or ord(char) in valid_codepoints for char in text)


def _embedded_font_supports_text(page: fitz.Page, display_font: str, text: str) -> bool:
    if not hasattr(page, "get_fonts") or not hasattr(page, "parent"):
        return True
    matched_font = False
    for font in page.get_fonts(full=True):
        xref = int(font[0])
        base_font = str(font[3] or "")
        if base_font != display_font and not base_font.endswith(f"+{display_font}"):
            continue
        matched_font = True
        try:
            _name, _ext, _font_type, font_buffer = page.parent.extract_font(xref)
            if font_buffer and _font_supports_text(fitz.Font(fontbuffer=font_buffer), text):
                return True
        except Exception:
            continue
    return not matched_font


@lru_cache(maxsize=None)
def _measurement_font(font_name: str, font_path_text: str | None) -> fitz.Font:
    if font_path_text:
        return fitz.Font(fontfile=font_path_text)
    try:
        return fitz.Font(fontname=font_name)
    except Exception:
        return fitz.Font(fontname="helv")


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


def _normalize_template_label(value: object) -> str:
    text = str(value or "").replace("\u200b", " ").replace("\xa0", " ").lower()
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    text = re.sub(r"\bbeam\s+width\b", "beamwidth", text)
    return re.sub(r"\s+", " ", text)


FIELD_LABEL_ALIAS_KEYS = {
    _normalize_template_label(alias): label
    for label, aliases in FIELD_LABEL_ALIASES.items()
    for alias in aliases
}


def _infer_field_label_from_template_text(text: str) -> str | None:
    key = _normalize_template_label(text)
    if not key:
        return None
    if key in FIELD_LABEL_ALIAS_KEYS:
        return FIELD_LABEL_ALIAS_KEYS[key]
    if "beamwidth" in key:
        if "azimuth" in key or "h plane" in key or "horizontal" in key:
            return "Azimuth Beam Width -3 dB/-6dB"
        if "elevation" in key or "e plane" in key or "vertical" in key:
            return "Elevation Beam Width -3 dB/-6dB"
    if "frequency" in key:
        return "Frequency Range"
    if key in {"gain", "nominal gain", "antenna gain"}:
        return "Gain"
    if "beam" in key and "efficiency" in key:
        return "Beam Efficiency"
    if "front" in key and "back" in key:
        return "Front-to-Back Ratio"
    if "vswr" in key:
        return "VSWR"
    if "polarization" in key or "polarisation" in key:
        return "Polarization"
    if "impedance" in key:
        return "Impedance"
    return None


def _replacement_slot_with_label(slot: ReplacementSlot, label: str) -> ReplacementSlot:
    return ReplacementSlot(
        label=label,
        erase_rect=slot.erase_rect,
        origin=slot.origin,
        max_width=slot.max_width,
        font_name=slot.font_name,
        font_size=slot.font_size,
        color=slot.color,
    )


def _template_label_candidates(label: str, spans: list[TextSpan]) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        key = _normalize_template_label(candidate)
        if key and key not in seen:
            labels.append(candidate)
            seen.add(key)

    for alias in FIELD_LABEL_ALIASES.get(label, (label,)):
        add(alias)
    for span in spans:
        if _infer_field_label_from_template_text(span.text) == label:
            add(span.text)
    return labels


def _find_replacement_slots(page: fitz.Page, labels: list[str], spans: list[TextSpan]) -> dict[str, ReplacementSlot]:
    slots: dict[str, ReplacementSlot] = {}
    used_template_keys: set[str] = set()
    for label in labels:
        for template_label in _template_label_candidates(label, spans):
            template_key = _normalize_template_label(template_label)
            if template_key in used_template_keys:
                continue
            try:
                slot = _find_replacement_slot(page, template_label, spans)
            except ValueError:
                continue
            slots[label] = _replacement_slot_with_label(slot, label)
            used_template_keys.add(template_key)
            break
    if not slots:
        raise ValueError("Datasheet template page 1 does not contain any recognizable performance data labels.")
    return slots


def _find_replacement_slot(page: fitz.Page, label: str, spans: list[TextSpan] | None = None) -> ReplacementSlot:
    spans = spans if spans is not None else _extract_page_spans(page)
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


def _stem_without_any_suffix(stem: str, suffixes: tuple[str, ...]) -> str:
    for suffix in suffixes:
        if stem.endswith(suffix):
            return stem[: -len(suffix)]
    return stem


def _pdf_timestamp(value: datetime) -> str:
    local_value = value.astimezone()
    offset = local_value.utcoffset()
    if offset is None:
        suffix = "Z"
    else:
        total_minutes = int(offset.total_seconds() // 60)
        sign = "+" if total_minutes >= 0 else "-"
        hours, minutes = divmod(abs(total_minutes), 60)
        suffix = f"{sign}{hours:02d}'{minutes:02d}'"
    return local_value.strftime(f"D:%Y%m%d%H%M%S{suffix}")


def _xmp_timestamp(value: datetime) -> str:
    return value.astimezone().isoformat(timespec="seconds")


def _derive_datasheet_title(output: Path) -> str:
    stem = _stem_without_any_suffix(output.stem, ("-datasheet", "_datasheet"))
    base_name = re.sub(r"[_\-]+", " ", stem).strip() or output.stem
    if base_name.lower().endswith(" datasheet"):
        return base_name
    return f"{base_name} Datasheet"


def _merge_keywords(existing: str, *extra_values: str) -> str:
    seen: set[str] = set()
    merged: list[str] = []
    for value in (existing, *extra_values):
        for item in str(value or "").split(","):
            keyword = item.strip()
            lowered = keyword.lower()
            if not keyword or lowered in seen:
                continue
            seen.add(lowered)
            merged.append(keyword)
    return ", ".join(merged)


def _build_pdf_metadata(
    template_metadata: dict[str, str],
    output: Path,
    now: datetime,
    metadata_author: str | None = None,
) -> dict[str, str]:
    title = _derive_datasheet_title(output)
    product_name = re.sub(r"\s+Datasheet$", "", title, flags=re.IGNORECASE).strip()
    metadata = {key: str(template_metadata.get(key) or "") for key in PDF_METADATA_KEYS}
    metadata.update(
        {
            "title": title,
            "subject": title,
            "keywords": _merge_keywords(metadata["keywords"], product_name, "datasheet"),
            "creator": PDF_CREATOR,
            "producer": PDF_PRODUCER,
            "creationDate": metadata["creationDate"] or _pdf_timestamp(now),
            "modDate": _pdf_timestamp(now),
        }
    )
    if metadata_author is not None:
        metadata["author"] = metadata_author
    return metadata


def _build_xmp_metadata(metadata: dict[str, str], created_at: datetime, modified_at: datetime) -> str:
    title = xml_escape(metadata.get("title", ""))
    author = xml_escape(metadata.get("author", ""))
    subject = xml_escape(metadata.get("subject", ""))
    keywords = xml_escape(metadata.get("keywords", ""))
    creator = xml_escape(metadata.get("creator", ""))
    producer = xml_escape(metadata.get("producer", ""))
    creation_date = xml_escape(_xmp_timestamp(created_at))
    mod_date = xml_escape(_xmp_timestamp(modified_at))
    return (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        '  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '    <rdf:Description rdf:about=""\n'
        '      xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
        '      xmlns:pdf="http://ns.adobe.com/pdf/1.3/"\n'
        '      xmlns:xmp="http://ns.adobe.com/xap/1.0/">\n'
        '      <dc:title><rdf:Alt><rdf:li xml:lang="x-default">'
        f"{title}"
        '</rdf:li></rdf:Alt></dc:title>\n'
        '      <dc:creator><rdf:Seq><rdf:li>'
        f"{author}"
        '</rdf:li></rdf:Seq></dc:creator>\n'
        '      <dc:subject><rdf:Bag><rdf:li>'
        f"{subject}"
        '</rdf:li></rdf:Bag></dc:subject>\n'
        f"      <pdf:Keywords>{keywords}</pdf:Keywords>\n"
        f"      <pdf:Producer>{producer}</pdf:Producer>\n"
        f"      <xmp:CreatorTool>{creator}</xmp:CreatorTool>\n"
        f"      <xmp:CreateDate>{creation_date}</xmp:CreateDate>\n"
        f"      <xmp:ModifyDate>{mod_date}</xmp:ModifyDate>\n"
        f"      <xmp:MetadataDate>{mod_date}</xmp:MetadataDate>\n"
        "    </rdf:Description>\n"
        "  </rdf:RDF>\n"
        "</x:xmpmeta>\n"
        '<?xpacket end="w"?>'
    )


def _find_plot_asset(output: Path, extract_workbook: Path, suffix: str) -> Path:
    candidate_dirs: list[Path] = []
    for path in [output.parent.resolve(), extract_workbook.parent.resolve()]:
        if path not in candidate_dirs:
            candidate_dirs.append(path)

    candidate_prefixes: list[str] = []
    for stem in [
        _stem_without_any_suffix(extract_workbook.stem, ("-extracted-data", "_extracted_data")),
        _stem_without_any_suffix(output.stem, ("-datasheet", "_datasheet")),
        extract_workbook.stem,
        output.stem,
    ]:
        if stem and stem not in candidate_prefixes:
            candidate_prefixes.append(stem)

    suffixes = [suffix]
    if suffix.startswith("-"):
        suffixes.append(suffix.replace("-", "_"))
    elif suffix.startswith("_"):
        suffixes.append(suffix.replace("_", "-"))

    checked: list[Path] = []
    for directory in candidate_dirs:
        for prefix in candidate_prefixes:
            for candidate_suffix in suffixes:
                candidate = directory / f"{prefix}{candidate_suffix}"
                checked.append(candidate)
                if candidate.exists():
                    return candidate
    checked_list = ", ".join(str(path) for path in checked)
    raise ValueError(f"Missing required plot asset '{suffix}'. Rerun Plots only for this project. Checked: {checked_list}")


def _manifest_chart_record(artifact_manifest: dict[str, object] | None, key: str) -> dict[str, object] | None:
    if not isinstance(artifact_manifest, dict):
        return None
    charts = artifact_manifest.get("charts")
    if not isinstance(charts, dict):
        return None
    record = charts.get(key)
    return record if isinstance(record, dict) else None


def _manifest_svg_path(record: dict[str, object] | None, field: str = "svg") -> Path | None:
    if not isinstance(record, dict):
        return None
    value = str(record.get(field) or "").strip()
    if not value:
        return None
    path = Path(value)
    return path if path.exists() else None


def _manifest_record_for_svg_path(
    artifact_manifest: dict[str, object] | None,
    svg_path: Path,
) -> dict[str, object] | None:
    if not isinstance(artifact_manifest, dict):
        return None
    charts = artifact_manifest.get("charts")
    if not isinstance(charts, dict):
        return None
    target = svg_path.resolve()
    chart_values: list[object] = []
    for value in charts.values():
        if isinstance(value, list):
            chart_values.extend(value)
        else:
            chart_values.append(value)
    for record in chart_values:
        if not isinstance(record, dict):
            continue
        manifest_path = _manifest_svg_path(record)
        if manifest_path is not None and manifest_path.resolve() == target:
            return record
    return None


def _find_manifest_chart_asset(artifact_manifest: dict[str, object] | None, key: str) -> Path | None:
    return _manifest_svg_path(_manifest_chart_record(artifact_manifest, key))


def _find_manifest_beamwidth_plane_asset(
    artifact_manifest: dict[str, object] | None,
    plane: str,
    suffixes: list[str],
) -> Path | None:
    if not isinstance(artifact_manifest, dict):
        return None
    charts = artifact_manifest.get("charts")
    if not isinstance(charts, dict):
        return None
    records = charts.get("beamwidth_planes")
    if not isinstance(records, list):
        return None
    normalized_plane = str(plane).strip().lower()
    for suffix in suffixes:
        wanted_polarization = {"h": "H", "v": "V", "": ""}.get(suffix, suffix.upper())
        for record in records:
            if not isinstance(record, dict):
                continue
            if str(record.get("plane") or "").strip().lower() != normalized_plane:
                continue
            polarization = str(record.get("polarization") or "").strip().upper()
            if wanted_polarization and polarization != wanted_polarization:
                continue
            if not wanted_polarization and polarization not in {"", "UNKNOWN"}:
                continue
            path = _manifest_svg_path(record)
            if path is not None:
                return path
    return None


def _find_manifest_polar_assets(
    artifact_manifest: dict[str, object] | None,
    template_frequency: float | None,
) -> tuple[Path, Path] | None:
    if not isinstance(artifact_manifest, dict):
        return None
    charts = artifact_manifest.get("charts")
    if not isinstance(charts, dict):
        return None
    records = charts.get("polar_single")
    if not isinstance(records, list):
        return None

    by_plane: dict[str, dict[float, Path]] = {"azimuth": {}, "elevation": {}}
    for record in records:
        if not isinstance(record, dict):
            continue
        plane = str(record.get("plane") or "").strip().lower()
        if plane not in by_plane:
            continue
        try:
            frequency = float(record.get("frequency_ghz"))
        except (TypeError, ValueError):
            continue
        path = _manifest_svg_path(record)
        if path is None:
            continue
        by_plane[plane].setdefault(frequency, path)

    common_frequencies = sorted(set(by_plane["azimuth"]).intersection(by_plane["elevation"]))
    if not common_frequencies:
        return None
    reference_frequency = template_frequency if template_frequency is not None else (sum(common_frequencies) / len(common_frequencies))
    selected = min(common_frequencies, key=lambda value: (abs(value - reference_frequency), value))
    return by_plane["azimuth"][selected], by_plane["elevation"][selected]


def _manifest_combined_polar_assets(
    artifact_manifest: dict[str, object] | None,
    chart_key: str = "polar_combined",
) -> dict[float, Path]:
    if not isinstance(artifact_manifest, dict):
        return {}
    charts = artifact_manifest.get("charts")
    if not isinstance(charts, dict):
        return {}
    records = charts.get(chart_key)
    if not isinstance(records, list):
        return {}

    assets: dict[float, Path] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        try:
            frequency = float(record.get("frequency_ghz"))
        except (TypeError, ValueError):
            continue
        path = _manifest_svg_path(record)
        if path is not None:
            assets.setdefault(frequency, path)
    return assets


def _find_optional_plot_asset(output: Path, extract_workbook: Path, suffix: str) -> Path | None:
    try:
        return _find_plot_asset(output, extract_workbook, suffix)
    except ValueError:
        return None


def _legend_asset_path(path: Path, artifact_manifest: dict[str, object] | None = None) -> Path:
    manifest_record = _manifest_record_for_svg_path(artifact_manifest, path)
    manifest_legend = _manifest_svg_path(manifest_record, "legend_svg")
    if manifest_legend is not None:
        return manifest_legend
    preferred = path.with_name(f"{path.stem}-legend{path.suffix}")
    legacy = path.with_name(f"{path.stem}_legend{path.suffix}")
    if preferred.exists() or not legacy.exists():
        return preferred
    return legacy


def _extract_frequency_ghz(text: str) -> float | None:
    match = re.search(r"(\d+(?:[\.,]\d+)?)\s*ghz", str(text), re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1).replace(",", "."))


def _parse_frequency_from_polar_asset(path: Path, plane: str) -> float | None:
    pattern = rf"[-_]polar[-_]{re.escape(plane)}[-_](\d+(?:\.\d+)?)[-_]GHz\.svg$"
    match = re.search(pattern, path.name, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def _parse_frequency_from_combined_polar_asset(path: Path) -> float | None:
    pattern = r"[-_]polar[-_](\d+(?:\.\d+)?)[-_]GHz(?:[-_]e[-_]h[-_]plane)?[-_]combined\.svg$"
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
        _stem_without_any_suffix(extract_workbook.stem, ("-extracted-data", "_extracted_data")),
        _stem_without_any_suffix(output.stem, ("-datasheet", "_datasheet")),
        extract_workbook.stem,
        output.stem,
    ]:
        if stem and stem not in candidate_prefixes:
            candidate_prefixes.append(stem)
    return candidate_prefixes


def _find_template_polar_frequency(page: fitz.Page, spans: list[TextSpan] | None = None) -> float | None:
    page_spans = spans if spans is not None else _extract_page_spans(page)
    values = [
        _extract_frequency_ghz(span.text)
        for span in page_spans
        if "Port Pattern" in span.text
    ]
    values = [value for value in values if value is not None]
    if not values:
        return None
    rounded = [round(value, 6) for value in values]
    return float(Counter(rounded).most_common(1)[0][0])


def _find_polar_plot_assets(
    page: fitz.Page,
    output: Path,
    extract_workbook: Path,
    spans: list[TextSpan] | None = None,
    artifact_manifest: dict[str, object] | None = None,
) -> tuple[Path, Path]:
    template_frequency = _find_template_polar_frequency(page, spans)
    manifest_assets = _find_manifest_polar_assets(artifact_manifest, template_frequency)
    if manifest_assets is not None:
        return manifest_assets

    plane_assets: dict[str, dict[float, Path]] = {"azimuth": {}, "elevation": {}}
    checked: list[Path] = []
    for directory in _candidate_dirs(output, extract_workbook):
        for prefix in _candidate_prefixes(output, extract_workbook):
            for plane in plane_assets:
                base_dir = directory / "polar_single" / plane
                for pattern in (
                    f"{prefix}-polar-{plane}-*-GHz.svg",
                    f"{prefix}_polar_{plane}_*_GHz.svg",
                ):
                    for candidate in sorted(base_dir.glob(pattern)):
                        checked.append(candidate)
                        frequency = _parse_frequency_from_polar_asset(candidate, plane)
                        if frequency is not None:
                            plane_assets[plane].setdefault(frequency, candidate)

    common_frequencies = sorted(set(plane_assets["azimuth"]).intersection(plane_assets["elevation"]))
    if not common_frequencies:
        checked_list = ", ".join(str(path) for path in checked) if checked else "none"
        raise ValueError(
            "Missing required polar plot assets. Rerun Plots only for this project; "
            f"missing matching azimuth/elevation polar SVGs. Checked: {checked_list}"
        )

    if template_frequency is None:
        template_frequency = sum(common_frequencies) / len(common_frequencies)
    selected_frequency = min(common_frequencies, key=lambda value: (abs(value - template_frequency), value))
    return plane_assets["azimuth"][selected_frequency], plane_assets["elevation"][selected_frequency]


def _frequency_triplet_targets(extract_workbook: Path) -> tuple[float, float, float]:
    ffs_summary = _load_sheet(extract_workbook, "ffs_summary")
    min_values = [
        value
        for value in (_as_float(item) for item in ffs_summary.get("freq_min_GHz", []))
        if value is not None
    ]
    max_values = [
        value
        for value in (_as_float(item) for item in ffs_summary.get("freq_max_GHz", []))
        if value is not None
    ]
    if not min_values or not max_values:
        raise ValueError("Workbook is missing frequency range values needed for Netqui 1Pol radiation plots.")
    fmin = min(min_values)
    fmax = max(max_values)
    return fmin, (fmin + fmax) / 2.0, fmax


def _frequency_series_targets(extract_workbook: Path, count: int) -> tuple[float, ...]:
    if count <= 0:
        return ()
    low, _mid, high = _frequency_triplet_targets(extract_workbook)
    if count == 1:
        return (low,)
    step = (high - low) / float(count - 1)
    return tuple(low + step * index for index in range(count))


def _select_unique_frequency_assets(assets: dict[float, Path], targets: tuple[float, ...], roles: tuple[str, ...]) -> dict[str, Path]:
    if len(assets) < len(roles):
        raise ValueError(f"Netqui 1Pol requires at least {len(roles)} combined polar radiation plot frequencies.")

    selected: dict[str, Path] = {}
    used: set[float] = set()
    for role, target in zip(roles, targets):
        remaining = [frequency for frequency in assets if frequency not in used]
        if not remaining:
            break
        frequency = min(remaining, key=lambda value: (abs(value - target), value))
        used.add(frequency)
        selected[role] = assets[frequency]
    if set(selected) != set(roles):
        raise ValueError(f"Netqui 1Pol could not select {len(roles)} unique combined polar radiation plots.")
    return selected


def _select_unique_frequency_triplet(assets: dict[float, Path], targets: tuple[float, float, float]) -> dict[str, Path]:
    return _select_unique_frequency_assets(assets, targets, ("low", "mid", "high"))


def _normalize_selected_radiation_frequencies(values: list[float] | tuple[float, ...] | None) -> list[float] | None:
    if values is None:
        return None
    selected: set[float] = set()
    for raw in values:
        try:
            value = round(float(raw), 6)
        except (TypeError, ValueError):
            continue
        if value > 0:
            selected.add(value)
    return sorted(selected)


def _parse_asset_ids(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = value.split(",")
    else:
        raw_items = value
    result: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        text = str(raw or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _radiation_frequencies_from_asset_ids(
    artifact_manifest: dict[str, object] | None,
    asset_ids: str | list[str] | tuple[str, ...] | None,
) -> list[float] | None:
    selected_ids = _parse_asset_ids(asset_ids)
    if not selected_ids:
        return None
    catalog = build_asset_catalog(artifact_manifest)
    by_id = catalog.by_id()
    frequencies: list[float] = []
    seen: set[float] = set()
    missing: list[str] = []
    for asset_id in selected_ids:
        item = by_id.get(asset_id)
        if item is None:
            missing.append(asset_id)
            continue
        if item.chart_family != "polar" or item.frequency_ghz is None:
            continue
        frequency = round(float(item.frequency_ghz), 6)
        if frequency > 0 and frequency not in seen:
            frequencies.append(frequency)
            seen.add(frequency)
    if missing:
        raise ValueError(f"Unknown generated image asset ID(s): {', '.join(missing)}.")
    return frequencies if frequencies else None


def _selected_frequency_asset_map(
    assets: dict[float, Path],
    selected_frequencies: list[float],
    *,
    label: str,
    tolerance: float = 0.0005,
) -> list[Path]:
    selected: list[Path] = []
    for requested in selected_frequencies:
        matches = [
            frequency
            for frequency in assets
            if abs(float(frequency) - float(requested)) <= tolerance
        ]
        if not matches:
            available = ", ".join(f"{frequency:g}" for frequency in sorted(assets)) or "none"
            raise ValueError(
                f"Missing required {label} radiation plot asset for {requested:g} GHz. "
                f"Rerun Plots only or adjust the selected radiation frequencies. Available: {available}"
            )
        frequency = min(matches, key=lambda value: (abs(value - requested), value))
        selected.append(assets[frequency])
    return selected


def _manifest_polar_single_assets(artifact_manifest: dict[str, object] | None) -> dict[str, dict[float, Path]]:
    if not isinstance(artifact_manifest, dict):
        return {"azimuth": {}, "elevation": {}}
    charts = artifact_manifest.get("charts")
    if not isinstance(charts, dict):
        return {"azimuth": {}, "elevation": {}}
    records = charts.get("polar_single")
    if not isinstance(records, list):
        return {"azimuth": {}, "elevation": {}}

    by_plane: dict[str, dict[float, Path]] = {"azimuth": {}, "elevation": {}}
    for record in records:
        if not isinstance(record, dict):
            continue
        plane = str(record.get("plane") or "").strip().lower()
        if plane not in by_plane:
            continue
        try:
            frequency = round(float(record.get("frequency_ghz")), 6)
        except (TypeError, ValueError):
            continue
        path = _manifest_svg_path(record)
        if path is not None:
            by_plane[plane].setdefault(frequency, path)
    return by_plane


def _filesystem_polar_single_assets(output: Path, extract_workbook: Path) -> dict[str, dict[float, Path]]:
    by_plane: dict[str, dict[float, Path]] = {"azimuth": {}, "elevation": {}}
    for directory in _candidate_dirs(output, extract_workbook):
        for prefix in _candidate_prefixes(output, extract_workbook):
            for plane in by_plane:
                base_dir = directory / "polar_single" / plane
                for pattern in (
                    f"{prefix}-polar-{plane}-*-GHz.svg",
                    f"{prefix}_polar_{plane}_*_GHz.svg",
                ):
                    for candidate in sorted(base_dir.glob(pattern)):
                        frequency = _parse_frequency_from_polar_asset(candidate, plane)
                        if frequency is not None:
                            by_plane[plane].setdefault(round(frequency, 6), candidate)
    return by_plane


def _find_selected_polar_single_asset_pairs(
    output: Path,
    extract_workbook: Path,
    selected_frequencies: list[float],
    artifact_manifest: dict[str, object] | None,
) -> list[tuple[Path, Path]]:
    by_plane = _manifest_polar_single_assets(artifact_manifest)
    if not by_plane["azimuth"] or not by_plane["elevation"]:
        filesystem = _filesystem_polar_single_assets(output, extract_workbook)
        for plane in ("azimuth", "elevation"):
            by_plane[plane].update(filesystem[plane])
    azimuth = _selected_frequency_asset_map(by_plane["azimuth"], selected_frequencies, label="azimuth")
    elevation = _selected_frequency_asset_map(by_plane["elevation"], selected_frequencies, label="elevation")
    return list(zip(azimuth, elevation))


def _find_selected_combined_polar_assets(
    output: Path,
    extract_workbook: Path,
    selected_frequencies: list[float],
    artifact_manifest: dict[str, object] | None,
    *,
    chart_key: str,
) -> list[Path]:
    assets = _manifest_combined_polar_assets(artifact_manifest, chart_key=chart_key)
    if not assets:
        for directory in _candidate_dirs(output, extract_workbook):
            for prefix in _candidate_prefixes(output, extract_workbook):
                if chart_key == "polar_combined_planes":
                    combined_dirs = (directory / "polar_combined" / "e-h-plane",)
                    patterns = (
                        f"{prefix}-polar-*-GHz-e-h-plane-combined.svg",
                        f"{prefix}_polar_*_GHz_e_h_plane_combined.svg",
                    )
                else:
                    combined_dirs = (
                        directory / "polar_combined" / "azimuth-elevation",
                        directory / "polar_combined",
                    )
                    patterns = (
                        f"{prefix}-polar-*-GHz-combined.svg",
                        f"{prefix}_polar_*_GHz_combined.svg",
                    )
                for pattern in patterns:
                    for combined_dir in combined_dirs:
                        for candidate in sorted(combined_dir.glob(pattern)):
                            frequency = _parse_frequency_from_combined_polar_asset(candidate)
                            if frequency is not None:
                                assets.setdefault(round(frequency, 6), candidate)
    return _selected_frequency_asset_map(assets, selected_frequencies, label="combined E/H-plane")


def _find_combined_polar_triplet_assets(
    output: Path,
    extract_workbook: Path,
    artifact_manifest: dict[str, object] | None = None,
    *,
    chart_key: str = "polar_combined",
) -> dict[str, Path]:
    assets = _manifest_combined_polar_assets(artifact_manifest, chart_key=chart_key)
    checked: list[Path] = []
    if not assets:
        for directory in _candidate_dirs(output, extract_workbook):
            for prefix in _candidate_prefixes(output, extract_workbook):
                if chart_key == "polar_combined_planes":
                    combined_dirs = (directory / "polar_combined" / "e-h-plane",)
                    patterns = (
                        f"{prefix}-polar-*-GHz-e-h-plane-combined.svg",
                        f"{prefix}_polar_*_GHz_e_h_plane_combined.svg",
                    )
                else:
                    combined_dirs = (
                        directory / "polar_combined" / "azimuth-elevation",
                        directory / "polar_combined",
                    )
                    patterns = (
                        f"{prefix}-polar-*-GHz-combined.svg",
                        f"{prefix}_polar_*_GHz_combined.svg",
                    )
                for pattern in patterns:
                    for combined_dir in combined_dirs:
                        checked.append(combined_dir / pattern)
                        for candidate in sorted(combined_dir.glob(pattern)):
                            frequency = _parse_frequency_from_combined_polar_asset(candidate)
                            if frequency is not None:
                                assets.setdefault(frequency, candidate)
    if not assets:
        checked_list = ", ".join(str(path) for path in checked) if checked else "none"
        raise ValueError(
            "Missing required combined polar radiation plot assets for Netqui 1Pol. "
            f"Rerun Plots only for this project. Checked: {checked_list}"
        )
    return _select_unique_frequency_triplet(assets, _frequency_triplet_targets(extract_workbook))


def _find_combined_polar_series_assets(
    output: Path,
    extract_workbook: Path,
    artifact_manifest: dict[str, object] | None = None,
    *,
    chart_key: str = "polar_combined",
    count: int,
) -> list[Path]:
    assets = _manifest_combined_polar_assets(artifact_manifest, chart_key=chart_key)
    checked: list[Path] = []
    if not assets:
        for directory in _candidate_dirs(output, extract_workbook):
            for prefix in _candidate_prefixes(output, extract_workbook):
                if chart_key == "polar_combined_planes":
                    combined_dirs = (directory / "polar_combined" / "e-h-plane",)
                    patterns = (
                        f"{prefix}-polar-*-GHz-e-h-plane-combined.svg",
                        f"{prefix}_polar_*_GHz_e_h_plane_combined.svg",
                    )
                else:
                    combined_dirs = (
                        directory / "polar_combined" / "azimuth-elevation",
                        directory / "polar_combined",
                    )
                    patterns = (
                        f"{prefix}-polar-*-GHz-combined.svg",
                        f"{prefix}_polar_*_GHz_combined.svg",
                    )
                for pattern in patterns:
                    for combined_dir in combined_dirs:
                        checked.append(combined_dir / pattern)
                        for candidate in sorted(combined_dir.glob(pattern)):
                            frequency = _parse_frequency_from_combined_polar_asset(candidate)
                            if frequency is not None:
                                assets.setdefault(frequency, candidate)
    if not assets:
        checked_list = ", ".join(str(path) for path in checked) if checked else "none"
        raise ValueError(
            "Missing required combined polar radiation plot assets for Netqui 1Pol. "
            f"Rerun Plots only for this project. Checked: {checked_list}"
        )
    roles = tuple(f"frequency_{index + 1}" for index in range(count))
    selected = _select_unique_frequency_assets(assets, _frequency_series_targets(extract_workbook, count), roles)
    return [selected[role] for role in roles]


def _beamwidth_polarization_suffixes(extract_workbook: Path) -> list[str]:
    try:
        ffs_summary = _load_sheet(extract_workbook, "ffs_summary")
        keys = list(dict.fromkeys(_polarization_keys_from_source_files(ffs_summary)))
    except ValueError:
        keys = []
    suffixes = [
        {"horizontal": "h", "vertical": "v"}.get(str(key).strip().lower(), "")
        for key in keys
    ]
    suffixes = [suffix for suffix in suffixes if suffix]
    suffixes.sort(key=lambda suffix: {"v": 0, "h": 1}.get(suffix, 2))
    for fallback in ("v", "h", ""):
        if fallback not in suffixes:
            suffixes.append(fallback)
    return suffixes


def _find_beamwidth_plane_asset(
    output: Path,
    extract_workbook: Path,
    plane: str,
    artifact_manifest: dict[str, object] | None = None,
) -> Path:
    checked: list[str] = []
    suffixes = _beamwidth_polarization_suffixes(extract_workbook)
    manifest_asset = _find_manifest_beamwidth_plane_asset(artifact_manifest, plane, suffixes)
    if manifest_asset is not None:
        return manifest_asset
    for suffix in suffixes:
        suffix_part = f"-{suffix}" if suffix else ""
        asset_suffix = f"-beamwidth-{plane}{suffix_part}.svg"
        checked.append(asset_suffix)
        asset = _find_optional_plot_asset(output, extract_workbook, asset_suffix)
        if asset is not None:
            return asset
    plane_label = str(plane).replace("-", " ").title()
    raise ValueError(
        f"Missing required beamwidth {plane} plot asset. Rerun Plots only for this project; "
        f"missing {plane_label} beamwidth SVG. Checked suffixes: {', '.join(checked)}"
    )


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


def _expand_template_legend_rect(rect: fitz.Rect) -> fitz.Rect:
    return fitz.Rect(
        rect.x0 - 42.0,
        rect.y0 - 18.0,
        rect.x1 + 8.0,
        rect.y1 + 8.0,
    )


def _union_rects(rects: list[fitz.Rect]) -> fitz.Rect:
    combined = fitz.Rect(rects[0])
    for rect in rects[1:]:
        combined.include_rect(rect)
    return combined


def _overlap_length(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def _separate_plot_and_legend_rects(
    plot_rect: fitz.Rect,
    legend_rect: fitz.Rect,
    *,
    gap: float = 6.0,
    min_plot_width: float = 72.0,
    min_plot_height: float = 72.0,
    preferred_orientation: str = "",
) -> tuple[fitz.Rect, fitz.Rect]:
    plot = fitz.Rect(plot_rect)
    legend = fitz.Rect(legend_rect)
    horizontal_overlap = _overlap_length(plot.x0, plot.x1, legend.x0, legend.x1)
    vertical_overlap = _overlap_length(plot.y0, plot.y1, legend.y0, legend.y1)
    if horizontal_overlap <= 0.0 or vertical_overlap <= 0.0:
        return plot, legend

    def _try_horizontal() -> bool:
        legend_is_right = ((legend.x0 + legend.x1) / 2.0) >= ((plot.x0 + plot.x1) / 2.0)
        if legend_is_right:
            proposed_x1 = min(plot.x1, legend.x0 - gap)
            if proposed_x1 - plot.x0 >= min_plot_width:
                plot.x1 = proposed_x1
                return True
        else:
            proposed_x0 = max(plot.x0, legend.x1 + gap)
            if plot.x1 - proposed_x0 >= min_plot_width:
                plot.x0 = proposed_x0
                return True
        return False

    def _try_vertical() -> bool:
        legend_is_below = ((legend.y0 + legend.y1) / 2.0) >= ((plot.y0 + plot.y1) / 2.0)
        if legend_is_below:
            proposed_y1 = min(plot.y1, legend.y0 - gap)
            if proposed_y1 - plot.y0 >= min_plot_height:
                plot.y1 = proposed_y1
                return True
        else:
            proposed_y0 = max(plot.y0, legend.y1 + gap)
            if plot.y1 - proposed_y0 >= min_plot_height:
                plot.y0 = proposed_y0
                return True
        return False

    if preferred_orientation == "horizontal":
        if _try_horizontal() or _try_vertical():
            return plot, legend
        return plot, legend
    if preferred_orientation == "vertical":
        if _try_vertical() or _try_horizontal():
            return plot, legend
        return plot, legend

    center_dx = abs(((legend.x0 + legend.x1) / 2.0) - ((plot.x0 + plot.x1) / 2.0))
    center_dy = abs(((legend.y0 + legend.y1) / 2.0) - ((plot.y0 + plot.y1) / 2.0))
    if center_dx >= center_dy:
        if _try_horizontal() or _try_vertical():
            return plot, legend
    else:
        if _try_vertical() or _try_horizontal():
            return plot, legend
    return plot, legend


def _center_rect_horizontally(rect: fitz.Rect, center_x: float) -> fitz.Rect:
    width = rect.width
    return fitz.Rect(center_x - (width / 2.0), rect.y0, center_x + (width / 2.0), rect.y1)


def _layout_split_chart_rects(kind: str, plot_rect: fitz.Rect, legend_rect: fitz.Rect) -> tuple[fitz.Rect, fitz.Rect]:
    plot = _expand_rect(fitz.Rect(plot_rect))
    legend = _expand_template_legend_rect(fitz.Rect(legend_rect))
    if kind in {"gain", "beamwidth"}:
        return _separate_plot_and_legend_rects(plot, legend, preferred_orientation="horizontal")
    if kind in {"azimuth", "elevation"}:
        plot, legend = _separate_plot_and_legend_rects(plot, legend, preferred_orientation="vertical")
        return plot, _center_rect_horizontally(legend, (plot.x0 + plot.x1) / 2.0)
    return _separate_plot_and_legend_rects(plot, legend)


def _normalize_plot_widths(replacements: list[ChartReplacement], kinds: set[str]) -> list[ChartReplacement]:
    target_replacements = [replacement for replacement in replacements if replacement.kind in kinds]
    if len(target_replacements) < 2:
        return replacements

    common_width = min(replacement.rect.width for replacement in target_replacements)
    normalized: list[ChartReplacement] = []
    for replacement in replacements:
        if replacement.kind not in kinds or abs(replacement.rect.width - common_width) <= 0.01:
            normalized.append(replacement)
            continue
        normalized.append(
            ChartReplacement(
                replacement.kind,
                fitz.Rect(replacement.rect.x0, replacement.rect.y0, replacement.rect.x0 + common_width, replacement.rect.y1),
                replacement.asset_path,
                legend_rect=replacement.legend_rect,
                legend_asset_path=replacement.legend_asset_path,
                erase_rect=replacement.erase_rect,
                legend_scale_cap=replacement.legend_scale_cap,
            )
        )
    return normalized


def _legend_group(text: str) -> str | None:
    stripped = str(text).strip()
    if re.match(r"^Gain\b", stripped):
        return "gain"
    if re.match(r"^Beamwidth\b", stripped):
        return "beamwidth"
    if "Port Pattern" in stripped:
        return "polar"
    return None


def _page_text(spans: list[TextSpan]) -> str:
    return " ".join(span.text for span in spans)


def _is_netqui_chart_page(spans: list[TextSpan], slots: list[ChartSlot]) -> bool:
    text = _page_text(spans).upper()
    return (
        len(slots) >= 4
        and "ANTENNA GAIN" in text
        and "VSWR" in text
        and "ANTENNA BEAMWIDTH" in text
        and "RADIATION PATTERNS" in text
    )


def _dedupe_chart_slots(slots: list[ChartSlot]) -> list[ChartSlot]:
    deduped: list[ChartSlot] = []
    seen: set[tuple[float, float, float, float]] = set()
    for slot in slots:
        key = tuple(round(value, 2) for value in slot.rect)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(slot)
    return deduped


def _chart_slot_rows(slots: list[ChartSlot], tolerance: float = 36.0) -> list[list[ChartSlot]]:
    rows: list[list[ChartSlot]] = []
    for slot in sorted(_dedupe_chart_slots(slots), key=lambda item: ((item.rect.y0 + item.rect.y1) / 2.0, item.rect.x0)):
        center_y = (slot.rect.y0 + slot.rect.y1) / 2.0
        if not rows:
            rows.append([slot])
            continue
        row_center = sum((item.rect.y0 + item.rect.y1) / 2.0 for item in rows[-1]) / len(rows[-1])
        if abs(center_y - row_center) <= tolerance:
            rows[-1].append(slot)
        else:
            rows.append([slot])
    return [sorted(row, key=lambda item: item.rect.x0) for row in rows]


def _align_netqui_1pol_cartesian_slots(ordered_slots: list[ChartSlot]) -> list[ChartSlot]:
    rows = _chart_slot_rows(ordered_slots)
    return align_1pol_cartesian_slots(rows, ChartSlot)


def _netqui_chart_heading_labels(kind: str) -> tuple[str, ...]:
    if kind == "gain":
        return ("ANTENNA GAIN",)
    if kind == "vswr":
        return ("VSWR",)
    if kind.startswith("beamwidth_"):
        return ("ANTENNA BEAMWIDTH",)
    if kind.startswith("radiation_"):
        return ("RADIATION PATTERNS",)
    return ()


def _netqui_heading_bottom(spans: list[TextSpan], labels: tuple[str, ...]) -> float | None:
    normalized_labels = {_normalized_span_text(label) for label in labels}
    headings = [span for span in spans if _normalized_span_text(span.text) in normalized_labels]
    if not headings:
        return None
    return max(span.bbox.y1 for span in headings)


def _compact_netqui_chart_slot_top(slot_rect: fitz.Rect, spans: list[TextSpan], kind: str) -> fitz.Rect:
    heading_bottom = _netqui_heading_bottom(spans, _netqui_chart_heading_labels(kind))
    if heading_bottom is None:
        return slot_rect
    compact_y0 = heading_bottom + NETQUI_CHART_HEADING_GAP
    if compact_y0 >= slot_rect.y0 or compact_y0 >= slot_rect.y1 - 24.0:
        return slot_rect
    if kind.startswith("radiation_"):
        return fitz.Rect(slot_rect.x0, compact_y0, slot_rect.x1, compact_y0 + slot_rect.height)
    return fitz.Rect(slot_rect.x0, compact_y0, slot_rect.x1, slot_rect.y1)


def _rfe_chart_heading_labels(kind: str) -> tuple[str, ...]:
    if kind == "gain":
        return ("ANTENNA GAIN",)
    if kind == "beamwidth":
        return ("ANTENNA BEAMWIDTH",)
    if kind.startswith("azimuth"):
        return ("AZIMUTH PATTERN",)
    if kind.startswith("elevation"):
        return ("ELEVATION PATTERN",)
    return ()


def _reserve_rfe_chart_heading_space(slot_rect: fitz.Rect, spans: list[TextSpan], kind: str) -> fitz.Rect:
    heading_bottom = _netqui_heading_bottom(spans, _rfe_chart_heading_labels(kind))
    if heading_bottom is None:
        return slot_rect
    y0 = heading_bottom + 8.0
    if y0 <= slot_rect.y0 or y0 >= slot_rect.y1 - 24.0:
        return slot_rect
    return fitz.Rect(slot_rect.x0, y0, slot_rect.x1, slot_rect.y1)


def _netqui_heading_span(spans: list[TextSpan], label: str) -> TextSpan | None:
    normalized = _normalized_span_text(label)
    return next((span for span in spans if _normalized_span_text(span.text) == normalized), None)


def _netqui_cartesian_layout_rects(kind: str, slot_rect: fitz.Rect) -> tuple[fitz.Rect, fitz.Rect]:
    if kind in {"gain", "vswr"}:
        return netqui_top_chart_rects(slot_rect)
    return netqui_beamwidth_rects(slot_rect)


def _netqui_placed_plot_bottom(
    kind: str,
    slot_rect: fitz.Rect,
    asset: Path,
    spans: list[TextSpan],
) -> float:
    compact_slot = _compact_netqui_chart_slot_top(fitz.Rect(slot_rect), spans, kind)
    plot_rect, _legend_rect = _netqui_cartesian_layout_rects(kind, compact_slot)
    return _top_aligned_svg_rect(plot_rect, asset).y1


def _netqui_shifted_heading_spans(
    page: fitz.Page,
    ordered_slots: list[ChartSlot],
    spans: list[TextSpan],
    chart_manifest: TemplateChartManifest,
    output: Path,
    extract_workbook: Path,
    artifact_manifest: dict[str, object] | None,
) -> dict[str, TextSpan]:
    if chart_manifest.slot_order == "rows":
        ordered_slots = [slot for row in _chart_slot_rows(ordered_slots) for slot in row]
        if any(slot.kind == "radiation_low" for slot in chart_manifest.slots):
            ordered_slots = _align_netqui_1pol_cartesian_slots(ordered_slots)

    shifted: dict[str, TextSpan] = {}
    span_by_title = {title: _netqui_heading_span(spans, title) for title in NETQUI_CHART_SECTION_TITLES}
    slot_by_kind = {slot.kind: slot for slot in chart_manifest.slots if slot.slot_index < len(ordered_slots)}

    def asset_for(kind: str) -> Path | None:
        slot_spec = slot_by_kind.get(kind)
        if slot_spec is None:
            return None
        return _manifest_slot_asset(slot_spec, output, extract_workbook, spans, page, artifact_manifest)

    gain_asset = asset_for("gain")
    vswr_asset = asset_for("vswr")
    top_bottoms: list[float] = []
    for kind, asset in (("gain", gain_asset), ("vswr", vswr_asset)):
        slot_spec = slot_by_kind.get(kind)
        if slot_spec is not None and asset is not None:
            top_bottoms.append(_netqui_placed_plot_bottom(kind, ordered_slots[slot_spec.slot_index].rect, asset, spans))

    beamwidth_heading = span_by_title.get("ANTENNA BEAMWIDTH")
    if top_bottoms and beamwidth_heading is not None:
        y0 = min(beamwidth_heading.bbox.y0, max(top_bottoms) + NETQUI_SECTION_GAP)
        shifted["ANTENNA BEAMWIDTH"] = _shift_text_span_y(beamwidth_heading, y0)

    spans_for_beamwidth = [
        shifted.get(_normalized_span_text(span.text), span)
        for span in spans
    ]
    beam_bottoms: list[float] = []
    for kind in ("beamwidth_e_plane", "beamwidth_h_plane"):
        slot_spec = slot_by_kind.get(kind)
        asset = asset_for(kind)
        if slot_spec is not None and asset is not None:
            beam_bottoms.append(_netqui_placed_plot_bottom(kind, ordered_slots[slot_spec.slot_index].rect, asset, spans_for_beamwidth))

    radiation_heading = span_by_title.get("RADIATION PATTERNS")
    if beam_bottoms and radiation_heading is not None:
        y0 = min(radiation_heading.bbox.y0, max(beam_bottoms) + NETQUI_SECTION_GAP)
        shifted["RADIATION PATTERNS"] = _shift_text_span_y(radiation_heading, y0)
    return shifted


def _build_netqui_chart_replacements(
    ordered_slots: list[ChartSlot],
    output: Path,
    extract_workbook: Path,
    spans: list[TextSpan],
    artifact_manifest: dict[str, object] | None = None,
) -> list[ChartReplacement]:
    rows = _chart_slot_rows(ordered_slots)
    if len(rows) < 2 or len(rows[0]) < 2 or len(rows[1]) < 2:
        raise ValueError("Netqui datasheet template does not contain the expected gain, VSWR, E-plane, and H-plane chart slots.")
    gain_slot, vswr_slot = rows[0][0], rows[0][1]
    e_plane_slot, h_plane_slot = rows[1][0], rows[1][1]
    gain_asset = _find_manifest_chart_asset(artifact_manifest, "gain") or _find_plot_asset(output, extract_workbook, "-gain.svg")
    gain_legend_asset = _legend_asset_path(gain_asset, artifact_manifest)
    gain_slot_rect = _compact_netqui_chart_slot_top(fitz.Rect(gain_slot.rect), spans, "gain")
    gain_plot_rect, gain_legend_rect = netqui_top_chart_rects(gain_slot_rect)
    replacements: list[ChartReplacement] = [
        ChartReplacement(
            "gain",
            gain_plot_rect,
            gain_asset,
            legend_rect=gain_legend_rect if gain_legend_asset.exists() else None,
            legend_asset_path=gain_legend_asset if gain_legend_asset.exists() else None,
            erase_rect=fitz.Rect(gain_slot.rect),
            legend_scale_cap=NETQUI_SIDE_LEGEND_SCALE_CAP,
        ),
    ]
    vswr_asset = _find_manifest_chart_asset(artifact_manifest, "vswr") or _find_optional_plot_asset(output, extract_workbook, "-vswr.svg")
    if vswr_asset is not None:
        vswr_legend_asset = _legend_asset_path(vswr_asset, artifact_manifest)
        vswr_slot_rect = _compact_netqui_chart_slot_top(fitz.Rect(vswr_slot.rect), spans, "vswr")
        vswr_plot_rect, vswr_legend_rect = netqui_top_chart_rects(vswr_slot_rect)
        replacements.append(
            ChartReplacement(
                "vswr",
                vswr_plot_rect,
                vswr_asset,
                legend_rect=vswr_legend_rect if vswr_legend_asset.exists() else None,
                legend_asset_path=vswr_legend_asset if vswr_legend_asset.exists() else None,
                erase_rect=fitz.Rect(vswr_slot.rect),
                legend_scale_cap=NETQUI_SIDE_LEGEND_SCALE_CAP,
            )
        )

    for slot, kind, plane in [
        (e_plane_slot, "beamwidth_e_plane", "e-plane"),
        (h_plane_slot, "beamwidth_h_plane", "h-plane"),
    ]:
        asset = _find_beamwidth_plane_asset(output, extract_workbook, plane, artifact_manifest=artifact_manifest)
        legend_asset = _legend_asset_path(asset, artifact_manifest)
        slot_rect = _compact_netqui_chart_slot_top(fitz.Rect(slot.rect), spans, kind)
        plot_rect, legend_rect = netqui_beamwidth_rects(slot_rect)
        replacements.append(
            ChartReplacement(
                kind,
                plot_rect,
                asset,
                legend_rect=legend_rect if legend_asset.exists() else None,
                legend_asset_path=legend_asset if legend_asset.exists() else None,
                erase_rect=fitz.Rect(slot.rect),
                legend_scale_cap=NETQUI_SIDE_LEGEND_SCALE_CAP,
            )
        )
    return replacements


def _manifest_slot_asset(
    slot_spec: TemplateChartSlot,
    output: Path,
    extract_workbook: Path,
    spans: list[TextSpan],
    page: fitz.Page,
    artifact_manifest: dict[str, object] | None,
    selected_asset_ids: list[str] | None = None,
) -> Path | None:
    catalog_asset = _catalog_slot_asset(slot_spec, artifact_manifest, selected_asset_ids=selected_asset_ids)
    if catalog_asset is not None:
        return catalog_asset
    if slot_spec.asset_key == "gain":
        return _find_manifest_chart_asset(artifact_manifest, "gain") or _find_plot_asset(output, extract_workbook, "-gain.svg")
    if slot_spec.asset_key == "beamwidth":
        return _find_manifest_chart_asset(artifact_manifest, "beamwidth") or _find_plot_asset(output, extract_workbook, "-beamwidth.svg")
    if slot_spec.asset_key == "beam_efficiency":
        return _find_manifest_chart_asset(artifact_manifest, "beam_efficiency") or _find_optional_plot_asset(output, extract_workbook, "-beam-efficiency.svg")
    if slot_spec.asset_key == "vswr":
        return _find_manifest_chart_asset(artifact_manifest, "vswr") or _find_optional_plot_asset(output, extract_workbook, "-vswr.svg")
    if slot_spec.asset_key == "beamwidth_plane":
        if not slot_spec.plane:
            raise ValueError(f"Template chart slot '{slot_spec.kind}' is missing a beamwidth plane.")
        return _find_beamwidth_plane_asset(output, extract_workbook, slot_spec.plane, artifact_manifest=artifact_manifest)
    if slot_spec.asset_key in {"polar_azimuth", "polar_elevation"}:
        azimuth_asset, elevation_asset = _find_polar_plot_assets(page, output, extract_workbook, spans, artifact_manifest=artifact_manifest)
        return azimuth_asset if slot_spec.asset_key == "polar_azimuth" else elevation_asset
    if slot_spec.asset_key == "polar_combined_triplet":
        role = str(slot_spec.frequency_role or "").strip().lower()
        if role not in {"low", "mid", "high"}:
            raise ValueError(f"Template chart slot '{slot_spec.kind}' is missing a combined polar frequency role.")
        return _find_combined_polar_triplet_assets(output, extract_workbook, artifact_manifest=artifact_manifest)[role]
    if slot_spec.asset_key == "polar_combined_planes_triplet":
        role = str(slot_spec.frequency_role or "").strip().lower()
        if role not in {"low", "mid", "high"}:
            raise ValueError(f"Template chart slot '{slot_spec.kind}' is missing a combined E/H polar frequency role.")
        return _find_combined_polar_triplet_assets(
            output,
            extract_workbook,
            artifact_manifest=artifact_manifest,
            chart_key="polar_combined_planes",
        )[role]
    raise ValueError(f"Unknown template chart asset key '{slot_spec.asset_key}'.")


def _catalog_slot_asset(
    slot_spec: TemplateChartSlot,
    artifact_manifest: dict[str, object] | None,
    *,
    selected_asset_ids: list[str] | None = None,
) -> Path | None:
    catalog = build_asset_catalog(artifact_manifest)
    by_id = catalog.by_id()
    if selected_asset_ids:
        candidates = [
            by_id[asset_id] for asset_id in selected_asset_ids
            if asset_id in by_id and by_id[asset_id].manifest_key == slot_spec.asset_key
        ]
    else:
        candidates = list(catalog.by_manifest_key(slot_spec.asset_key))
    if not candidates:
        return None
    if slot_spec.plane:
        wanted_plane = _normalize_technical_key(slot_spec.plane)
        candidates = [
            item for item in candidates
            if item.plane is not None and _normalize_technical_key(item.plane) == wanted_plane
        ]
    role = str(slot_spec.frequency_role or "").strip().lower()
    frequency_candidates = [item for item in candidates if item.frequency_ghz is not None]
    if role in {"low", "mid", "high"} and frequency_candidates:
        ordered = sorted(frequency_candidates, key=lambda item: float(item.frequency_ghz or 0.0))
        if role == "low":
            return ordered[0].svg_path
        if role == "high":
            return ordered[-1].svg_path
        return ordered[len(ordered) // 2].svg_path
    if candidates:
        return sorted(candidates, key=lambda item: (float(item.frequency_ghz or 0.0), item.asset_id))[0].svg_path
    return None


def _build_manifest_chart_replacements(
    page: fitz.Page,
    ordered_slots: list[ChartSlot],
    output: Path,
    extract_workbook: Path,
    chart_manifest: TemplateChartManifest,
    spans: list[TextSpan],
    artifact_manifest: dict[str, object] | None = None,
    selected_asset_ids: list[str] | None = None,
) -> list[ChartReplacement]:
    if chart_manifest.slot_order == "rows":
        ordered_slots = [slot for row in _chart_slot_rows(ordered_slots) for slot in row]
        if any(slot.kind == "radiation_low" for slot in chart_manifest.slots):
            ordered_slots = _align_netqui_1pol_cartesian_slots(ordered_slots)
    elif chart_manifest.slot_order == "first_two_then_x" and len(ordered_slots) > 2:
        ordered_slots = order_chart_slots_first_two_then_x(ordered_slots)
    replacements: list[ChartReplacement] = []
    for slot_spec in chart_manifest.slots:
        if slot_spec.slot_index >= len(ordered_slots):
            if slot_spec.required:
                raise ValueError(
                    f"Datasheet template does not contain required chart slot '{slot_spec.kind}' at index {slot_spec.slot_index}."
                )
            continue
        asset = _manifest_slot_asset(slot_spec, output, extract_workbook, spans, page, artifact_manifest, selected_asset_ids=selected_asset_ids)
        if asset is None:
            if slot_spec.required:
                raise ValueError(f"Missing required chart asset for template slot '{slot_spec.kind}'.")
            continue
        original_slot_rect = fitz.Rect(ordered_slots[slot_spec.slot_index].rect)
        slot_rect = fitz.Rect(original_slot_rect)
        if slot_spec.legend_mode in {"netqui_side", "netqui_top_side", "netqui_bottom"}:
            slot_rect = _compact_netqui_chart_slot_top(slot_rect, spans, slot_spec.kind)
        elif chart_manifest.slot_order == "first_two_then_x":
            slot_rect = _reserve_rfe_chart_heading_space(slot_rect, spans, slot_spec.kind)
        if slot_spec.legend_mode == "netqui_side":
            legend_asset = _legend_asset_path(asset, artifact_manifest)
            plot_rect, legend_rect = netqui_beamwidth_rects(slot_rect)
            replacements.append(
                ChartReplacement(
                    slot_spec.kind,
                    plot_rect,
                    asset,
                    legend_rect=legend_rect if legend_asset.exists() else None,
                    legend_asset_path=legend_asset if legend_asset.exists() else None,
                    erase_rect=original_slot_rect,
                    legend_scale_cap=NETQUI_SIDE_LEGEND_SCALE_CAP,
                )
            )
        elif slot_spec.legend_mode == "netqui_top_side":
            legend_asset = _legend_asset_path(asset, artifact_manifest)
            plot_rect, legend_rect = netqui_top_chart_rects(slot_rect)
            replacements.append(
                ChartReplacement(
                    slot_spec.kind,
                    plot_rect,
                    asset,
                    legend_rect=legend_rect if legend_asset.exists() else None,
                    legend_asset_path=legend_asset if legend_asset.exists() else None,
                    erase_rect=original_slot_rect,
                    legend_scale_cap=NETQUI_SIDE_LEGEND_SCALE_CAP,
                )
            )
        elif slot_spec.legend_mode == "netqui_bottom":
            legend_asset = _legend_asset_path(asset, artifact_manifest)
            plot_rect, legend_rect = netqui_polar_rects(slot_rect)
            replacements.append(
                ChartReplacement(
                    slot_spec.kind,
                    plot_rect,
                    asset,
                    legend_rect=legend_rect if legend_asset.exists() else None,
                    legend_asset_path=legend_asset if legend_asset.exists() else None,
                    erase_rect=original_slot_rect,
                    legend_scale_cap=NETQUI_POLAR_LEGEND_SCALE_CAP,
                )
            )
        else:
            replacements.append(ChartReplacement(slot_spec.kind, slot_rect, asset))

    auto_legend_kinds = {slot.kind for slot in chart_manifest.slots if slot.legend_mode == "auto"}
    normalize_width_kinds = set(chart_manifest.normalize_width_kinds)
    if not auto_legend_kinds:
        return _normalize_plot_widths(replacements, normalize_width_kinds) if normalize_width_kinds else replacements

    index_by_kind = {replacement.kind: idx for idx, replacement in enumerate(replacements)}
    polar_x_centers = {
        "azimuth": (replacements[index_by_kind["azimuth"]].rect.x0 + replacements[index_by_kind["azimuth"]].rect.x1) / 2.0 if "azimuth" in index_by_kind else None,
        "elevation": (replacements[index_by_kind["elevation"]].rect.x0 + replacements[index_by_kind["elevation"]].rect.x1) / 2.0 if "elevation" in index_by_kind else None,
    }
    legend_rects: dict[str, list[fitz.Rect]] = {replacement.kind: [] for replacement in replacements if replacement.kind in auto_legend_kinds}

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
        if replacement.kind not in auto_legend_kinds:
            resolved.append(replacement)
            continue
        grouped_legend_rects = legend_rects.get(replacement.kind, [])
        legend_asset_path = _legend_asset_path(replacement.asset_path, artifact_manifest)
        if grouped_legend_rects and legend_asset_path.exists():
            plot_rect, legend_rect = _layout_split_chart_rects(
                replacement.kind,
                fitz.Rect(replacement.rect),
                _union_rects(grouped_legend_rects),
            )
            resolved.append(
                ChartReplacement(
                    replacement.kind,
                    plot_rect,
                    replacement.asset_path,
                    legend_rect=legend_rect,
                    legend_asset_path=legend_asset_path,
                )
            )
            continue

        rects = [fitz.Rect(replacement.rect)] + grouped_legend_rects
        resolved.append(
            ChartReplacement(
                replacement.kind,
                _expand_rect(_union_rects(rects)),
                replacement.asset_path,
            )
        )
    return _normalize_plot_widths(resolved, normalize_width_kinds) if normalize_width_kinds else resolved


def _build_chart_replacements(
    page: fitz.Page,
    output: Path,
    extract_workbook: Path,
    *,
    artifact_manifest: dict[str, object] | None = None,
    adapter: DatasheetTemplateAdapter | None = None,
    spans_override: list[TextSpan] | None = None,
    selected_asset_ids: list[str] | None = None,
) -> list[ChartReplacement]:
    slots = _collect_chart_slots(page)
    if len(slots) < 2:
        raise ValueError("Datasheet template page 2 does not contain the expected chart image slots.")

    ordered_slots = sorted(slots, key=lambda slot: (slot.rect.y0, slot.rect.x0, slot.rect.y1, slot.rect.x1))
    spans = spans_override if spans_override is not None else _extract_page_spans(page)
    chart_manifest = adapter.manifest.chart_layout if adapter is not None and adapter.manifest is not None else None
    if chart_manifest is not None:
        return _build_manifest_chart_replacements(
            page,
            ordered_slots,
            output,
            extract_workbook,
            chart_manifest,
            spans,
            artifact_manifest=artifact_manifest,
            selected_asset_ids=selected_asset_ids,
        )

    chart_mode = adapter.chart_layout_mode if adapter is not None else ("netqui" if _is_netqui_chart_page(spans, ordered_slots) else "generic")
    if chart_mode == "netqui":
        return _build_netqui_chart_replacements(ordered_slots, output, extract_workbook, spans, artifact_manifest=artifact_manifest)

    gain_asset = _find_manifest_chart_asset(artifact_manifest, "gain") or _find_plot_asset(output, extract_workbook, "-gain.svg")
    beamwidth_asset = _find_manifest_chart_asset(artifact_manifest, "beamwidth") or _find_plot_asset(output, extract_workbook, "-beamwidth.svg")
    replacements: list[ChartReplacement] = [
        ChartReplacement("gain", fitz.Rect(ordered_slots[0].rect), gain_asset),
        ChartReplacement("beamwidth", fitz.Rect(ordered_slots[1].rect), beamwidth_asset),
    ]
    if len(ordered_slots) >= 4:
        azimuth_asset, elevation_asset = _find_polar_plot_assets(page, output, extract_workbook, spans, artifact_manifest=artifact_manifest)
        polar_slots = sorted(ordered_slots[2:4], key=lambda slot: (slot.rect.x0, slot.rect.y0, slot.rect.y1, slot.rect.x1))
        replacements.extend(
            [
                ChartReplacement("azimuth", fitz.Rect(polar_slots[0].rect), azimuth_asset),
                ChartReplacement("elevation", fitz.Rect(polar_slots[1].rect), elevation_asset),
            ]
        )

    index_by_kind = {replacement.kind: idx for idx, replacement in enumerate(replacements)}
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
        grouped_legend_rects = legend_rects.get(replacement.kind, [])
        legend_asset_path = _legend_asset_path(replacement.asset_path, artifact_manifest)
        if grouped_legend_rects and legend_asset_path.exists():
            plot_rect, legend_rect = _layout_split_chart_rects(
                replacement.kind,
                fitz.Rect(replacement.rect),
                _union_rects(grouped_legend_rects),
            )
            resolved.append(
                ChartReplacement(
                    replacement.kind,
                    plot_rect,
                    replacement.asset_path,
                    legend_rect=legend_rect,
                    legend_asset_path=legend_asset_path,
                )
            )
            continue

        rects = [fitz.Rect(replacement.rect)] + grouped_legend_rects
        resolved.append(
            ChartReplacement(
                replacement.kind,
                _expand_rect(_union_rects(rects)),
                replacement.asset_path,
            )
        )
    return resolved


def _svg_to_pdf_bytes(svg_path: Path) -> bytes:
    try:
        from reportlab.graphics import renderPDF
        from svglib.svglib import svg2rlg
    except ImportError as exc:
        raise RuntimeError(
            "svglib and reportlab are required to place SVG charts into the datasheet PDF."
        ) from exc

    drawing = svg2rlg(str(svg_path))
    if drawing is None:
        raise ValueError(f"Unable to load SVG asset '{svg_path}'.")

    return renderPDF.drawToString(drawing)


@lru_cache(maxsize=None)
def _svg_drawing_size(svg_path_str: str) -> tuple[float, float]:
    try:
        from svglib.svglib import svg2rlg
    except ImportError as exc:
        raise RuntimeError(
            "svglib is required to inspect SVG chart dimensions."
        ) from exc

    drawing = svg2rlg(svg_path_str)
    if drawing is None:
        raise ValueError(f"Unable to load SVG asset '{svg_path_str}'.")
    return float(drawing.width), float(drawing.height)


@lru_cache(maxsize=None)
def _svg_size_uses_points(svg_path_str: str) -> bool:
    try:
        text = Path(svg_path_str).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    match = re.search(r"<svg\b[^>]*\bwidth=[\"'][^\"']*pt[\"'][^>]*\bheight=[\"'][^\"']*pt[\"']", text, re.IGNORECASE)
    return match is not None


def _center_rect_with_size(container_rect: fitz.Rect, width: float, height: float) -> fitz.Rect:
    center_x = (container_rect.x0 + container_rect.x1) / 2.0
    center_y = (container_rect.y0 + container_rect.y1) / 2.0
    half_width = width / 2.0
    half_height = height / 2.0
    return fitz.Rect(center_x - half_width, center_y - half_height, center_x + half_width, center_y + half_height)


def _is_polar_radiation_replacement(kind: str) -> bool:
    return (
        kind.startswith("radiation_")
        or kind.startswith("azimuth_")
        or kind.startswith("elevation_")
    )


def _shared_side_legend_scale(replacements: list[ChartReplacement]) -> float | None:
    scales: list[float] = []
    for replacement in replacements:
        if _is_polar_radiation_replacement(replacement.kind):
            continue
        if replacement.legend_rect is None or replacement.legend_asset_path is None:
            continue
        native_width, native_height = _svg_drawing_size(str(replacement.legend_asset_path.resolve()))
        if native_width <= 0.0 or native_height <= 0.0:
            continue
        scales.append(
            min(
                replacement.legend_rect.width / native_width,
                replacement.legend_rect.height / native_height,
            )
        )
        if replacement.legend_scale_cap is not None:
            scales.append(float(replacement.legend_scale_cap))
    return min(scales) if scales else None


def _legend_target_rect(
    replacement: ChartReplacement,
    shared_side_scale: float | None,
    align_y_rect: fitz.Rect | None = None,
) -> fitz.Rect:
    if replacement.legend_rect is None or replacement.legend_asset_path is None:
        raise ValueError("Legend placement requires both a legend rect and a legend asset path.")
    container_rect = fitz.Rect(replacement.legend_rect)
    native_width, native_height = _svg_drawing_size(str(replacement.legend_asset_path.resolve()))
    if native_width <= 0.0 or native_height <= 0.0:
        return container_rect
    if shared_side_scale is not None and shared_side_scale > 0.0:
        scale = shared_side_scale
    else:
        scale = min(container_rect.width / native_width, container_rect.height / native_height)
    if replacement.legend_scale_cap is not None:
        scale = min(scale, float(replacement.legend_scale_cap))
    if replacement.legend_scale_cap is not None and not _is_polar_radiation_replacement(replacement.kind):
        height = native_height * scale
        center_source = align_y_rect if align_y_rect is not None else container_rect
        center_y = (center_source.y0 + center_source.y1) / 2.0
        return fitz.Rect(container_rect.x0, center_y - height / 2.0, container_rect.x0 + native_width * scale, center_y + height / 2.0)
    return _center_rect_with_size(container_rect, native_width * scale, native_height * scale)


def _fitted_svg_rect(target_rect: fitz.Rect, svg_path: Path, *, top_align: bool = False) -> fitz.Rect:
    native_width, native_height = _svg_drawing_size(str(svg_path.resolve()))
    if native_width <= 0.0 or native_height <= 0.0:
        return target_rect
    scale = min(target_rect.width / native_width, target_rect.height / native_height)
    width = native_width * scale
    height = native_height * scale
    x0 = target_rect.x0 + max(0.0, (target_rect.width - width) / 2.0)
    y0 = target_rect.y0 if top_align else target_rect.y0 + max(0.0, (target_rect.height - height) / 2.0)
    return fitz.Rect(x0, y0, x0 + width, y0 + height)


def _top_aligned_svg_rect(target_rect: fitz.Rect, svg_path: Path) -> fitz.Rect:
    return _fitted_svg_rect(target_rect, svg_path, top_align=True)


def _figure_size_rect(
    target_rect: fitz.Rect,
    figure_width: float,
    figure_height: float,
    default_width: float,
    default_height: float,
    *,
    top_align: bool = False,
    allow_expand: bool = False,
) -> fitz.Rect:
    if figure_width <= 0.0 or figure_height <= 0.0 or default_width <= 0.0 or default_height <= 0.0:
        return target_rect
    default_scale = min(target_rect.width / default_width, target_rect.height / default_height)
    desired_width = figure_width * default_scale
    desired_height = figure_height * default_scale
    limit_scale = 1.0 if allow_expand else min(1.0, target_rect.width / desired_width, target_rect.height / desired_height)
    width = desired_width * limit_scale
    height = desired_height * limit_scale
    x0 = target_rect.x0 + max(0.0, (target_rect.width - width) / 2.0)
    y0 = target_rect.y0 if top_align else target_rect.y0 + max(0.0, (target_rect.height - height) / 2.0)
    return fitz.Rect(x0, y0, x0 + width, y0 + height)


def _cartesian_svg_rect(
    target_rect: fitz.Rect,
    svg_path: Path,
    *,
    top_align: bool = False,
    figure_width: float | None = None,
    figure_height: float | None = None,
    allow_expand: bool = False,
) -> fitz.Rect:
    default_width = CARTESIAN_FIGURE_WIDTH_IN * 72.0
    default_height = CARTESIAN_FIGURE_HEIGHT_IN * 72.0
    if figure_width is not None and figure_height is not None:
        return _figure_size_rect(
            target_rect,
            float(figure_width) * 72.0,
            float(figure_height) * 72.0,
            default_width,
            default_height,
            top_align=top_align,
            allow_expand=allow_expand,
        )

    resolved_path = str(svg_path.resolve())
    if not _svg_size_uses_points(resolved_path):
        return _fitted_svg_rect(target_rect, svg_path, top_align=top_align)

    native_width, native_height = _svg_drawing_size(resolved_path)
    if native_width <= 0.0 or native_height <= 0.0:
        return target_rect

    if default_width <= 0.0 or default_height <= 0.0:
        return _fitted_svg_rect(target_rect, svg_path, top_align=top_align)

    default_scale = min(target_rect.width / default_width, target_rect.height / default_height)
    desired_width = native_width * default_scale
    desired_height = native_height * default_scale
    limit_scale = 1.0 if allow_expand else min(1.0, target_rect.width / desired_width, target_rect.height / desired_height)
    width = desired_width * limit_scale
    height = desired_height * limit_scale
    x0 = target_rect.x0 + max(0.0, (target_rect.width - width) / 2.0)
    y0 = target_rect.y0 if top_align else target_rect.y0 + max(0.0, (target_rect.height - height) / 2.0)
    return fitz.Rect(x0, y0, x0 + width, y0 + height)


def _polar_svg_rect(
    target_rect: fitz.Rect,
    svg_path: Path,
    *,
    top_align: bool = False,
    figure_size: float | None = None,
    allow_expand: bool = False,
) -> fitz.Rect:
    default_size = POLAR_FIGURE_SIZE_IN * 72.0
    if figure_size is not None:
        requested_size = float(figure_size) * 72.0
        return _figure_size_rect(target_rect, requested_size, requested_size, default_size, default_size, top_align=top_align, allow_expand=allow_expand)

    resolved_path = str(svg_path.resolve())
    if not _svg_size_uses_points(resolved_path):
        return _fitted_svg_rect(target_rect, svg_path, top_align=top_align)

    native_width, native_height = _svg_drawing_size(resolved_path)
    if native_width <= 0.0 or native_height <= 0.0:
        return target_rect

    if default_size <= 0.0:
        return _fitted_svg_rect(target_rect, svg_path, top_align=top_align)

    default_scale = min(target_rect.width / default_size, target_rect.height / default_size)
    desired_width = native_width * default_scale
    desired_height = native_height * default_scale
    limit_scale = 1.0 if allow_expand else min(1.0, target_rect.width / desired_width, target_rect.height / desired_height)
    width = desired_width * limit_scale
    height = desired_height * limit_scale
    x0 = target_rect.x0 + max(0.0, (target_rect.width - width) / 2.0)
    y0 = target_rect.y0 if top_align else target_rect.y0 + max(0.0, (target_rect.height - height) / 2.0)
    return fitz.Rect(x0, y0, x0 + width, y0 + height)


def _place_svg_as_vector(
    page: fitz.Page,
    target_rect: fitz.Rect,
    svg_path: Path,
    *,
    top_align: bool = False,
    keep_proportion: bool = True,
) -> None:
    pdf_bytes = _svg_to_pdf_bytes(svg_path)
    placement_rect = _fitted_svg_rect(target_rect, svg_path, top_align=top_align) if keep_proportion else target_rect
    with fitz.open("pdf", pdf_bytes) as pdf_doc:
        page.show_pdf_page(placement_rect, pdf_doc, 0, keep_proportion=keep_proportion, overlay=True)


def _is_netqui_cartesian_replacement(kind: str) -> bool:
    return kind in {"gain", "vswr", "beamwidth_e_plane", "beamwidth_h_plane"}


def _is_cartesian_replacement(kind: str) -> bool:
    return kind in {"gain", "vswr", "beamwidth", "beam_efficiency", "beamwidth_e_plane", "beamwidth_h_plane"}


def _is_polar_replacement(kind: str) -> bool:
    return (
        kind in {"azimuth", "elevation", "radiation_low", "radiation_mid", "radiation_high"}
        or kind.startswith("radiation_")
        or kind.startswith("azimuth_")
        or kind.startswith("elevation_")
    )


def _replacement_union_rect(replacement: ChartReplacement) -> fitz.Rect:
    rect = fitz.Rect(replacement.rect)
    if replacement.legend_rect is not None:
        rect.include_rect(replacement.legend_rect)
    return rect


def _chart_page_content_rect(page: fitz.Page, replacements: list[ChartReplacement]) -> fitz.Rect:
    if replacements:
        left = min(_replacement_union_rect(replacement).x0 for replacement in replacements)
        top = min(_replacement_union_rect(replacement).y0 for replacement in replacements)
        return fitz.Rect(
            max(24.0, left),
            max(36.0, top),
            page.rect.width - 24.0,
            page.rect.height - 54.0,
        )
    return fitz.Rect(36.0, 72.0, page.rect.width - 36.0, page.rect.height - 54.0)


def _chart_rows(replacements: list[ChartReplacement], tolerance: float = 42.0) -> list[list[ChartReplacement]]:
    rows: list[list[ChartReplacement]] = []
    ordered = sorted(replacements, key=lambda item: (_replacement_union_rect(item).y0, _replacement_union_rect(item).x0))
    for replacement in ordered:
        center_y = (_replacement_union_rect(replacement).y0 + _replacement_union_rect(replacement).y1) / 2.0
        if not rows:
            rows.append([replacement])
            continue
        row_center = sum((_replacement_union_rect(item).y0 + _replacement_union_rect(item).y1) / 2.0 for item in rows[-1]) / len(rows[-1])
        if abs(center_y - row_center) <= tolerance:
            rows[-1].append(replacement)
        else:
            rows.append([replacement])
    return [sorted(row, key=lambda item: _replacement_union_rect(item).x0) for row in rows]


def _chart_heading_label_for_kind(kind: str) -> str | None:
    if kind == "gain":
        return "ANTENNA GAIN"
    if kind == "vswr":
        return "VSWR"
    if kind == "beamwidth" or kind.startswith("beamwidth_"):
        return "ANTENNA BEAMWIDTH"
    if kind == "azimuth" or kind.startswith("azimuth_"):
        return "AZIMUTH PATTERN"
    if kind == "elevation" or kind.startswith("elevation_"):
        return "ELEVATION PATTERN"
    if kind.startswith("radiation_"):
        return "RADIATION PATTERNS"
    return None


def _chart_heading_spans(page: fitz.Page) -> dict[str, TextSpan]:
    labels = {
        "ANTENNA GAIN",
        "VSWR",
        "ANTENNA BEAMWIDTH",
        "AZIMUTH PATTERN",
        "ELEVATION PATTERN",
        "RADIATION PATTERNS",
    }
    return {
        normalized: span
        for span in _extract_page_spans(page)
        if (normalized := _normalized_span_text(span.text)) in labels
    }


def _fallback_chart_heading_span(text: str, x: float, y0: float) -> TextSpan:
    is_rfe_polar = text in {"AZIMUTH PATTERN", "ELEVATION PATTERN"}
    size = 8.0 if is_rfe_polar else 10.0
    color = 0xE50000 if is_rfe_polar else 0x000000
    width = max(48.0, len(text) * size * 0.56)
    return TextSpan(
        text=text,
        bbox=fitz.Rect(x, y0, x + width, y0 + size + 2.0),
        origin=(x, y0 + size),
        font=NETQUI_HEADING_FONT if not is_rfe_polar else "helv",
        size=size,
        color=color,
    )


def _position_chart_heading_span(text: str, source: TextSpan | None, x: float, y0: float) -> TextSpan:
    if source is None:
        return _fallback_chart_heading_span(text, x, y0)
    dx = x - source.bbox.x0
    dy = y0 - source.bbox.y0
    return TextSpan(
        text=text,
        bbox=fitz.Rect(source.bbox.x0 + dx, source.bbox.y0 + dy, source.bbox.x1 + dx, source.bbox.y1 + dy),
        origin=(source.origin[0] + dx, source.origin[1] + dy),
        font=source.font,
        size=source.size,
        color=source.color,
    )


def _reflow_row_heading_inputs(
    row: list[ChartReplacement],
    source_spans: dict[str, TextSpan],
    used_labels: set[str],
) -> list[tuple[str, ChartReplacement, TextSpan | None]]:
    inputs: list[tuple[str, ChartReplacement, TextSpan | None]] = []
    seen_in_row: set[str] = set()
    for replacement in row:
        label = _chart_heading_label_for_kind(replacement.kind)
        if label is None or label in seen_in_row:
            continue
        if label in used_labels and label in {"ANTENNA BEAMWIDTH", "RADIATION PATTERNS"}:
            continue
        source = source_spans.get(label)
        if source is None and label not in {"ANTENNA GAIN", "VSWR"}:
            continue
        inputs.append((label, replacement, source))
        seen_in_row.add(label)
    return inputs


def _heading_x_for_replacement(label: str, replacement: ChartReplacement, source: TextSpan | None, content_rect: fitz.Rect) -> float:
    if source is not None:
        return max(content_rect.x0, source.bbox.x0)
    return _replacement_union_rect(replacement).x0


def _requested_plot_size(
    replacement: ChartReplacement,
    *,
    cartesian_figure_width: float | None,
    cartesian_figure_height: float | None,
    polar_figure_size: float | None,
) -> tuple[float, float]:
    top_align = _is_netqui_cartesian_replacement(replacement.kind)
    if _is_cartesian_replacement(replacement.kind) and cartesian_figure_width is not None and cartesian_figure_height is not None:
        rect = _cartesian_svg_rect(
            replacement.rect,
            replacement.asset_path,
            top_align=top_align,
            figure_width=cartesian_figure_width,
            figure_height=cartesian_figure_height,
            allow_expand=True,
        )
        return rect.width, rect.height
    if _is_polar_replacement(replacement.kind) and polar_figure_size is not None:
        rect = _polar_svg_rect(
            replacement.rect,
            replacement.asset_path,
            top_align=top_align,
            figure_size=polar_figure_size,
            allow_expand=True,
        )
        size = min(rect.width, rect.height)
        return size, size
    return replacement.rect.width, replacement.rect.height


def _legend_orientation(replacement: ChartReplacement) -> str:
    if replacement.legend_rect is None:
        return ""
    plot = fitz.Rect(replacement.rect)
    legend = fitz.Rect(replacement.legend_rect)
    if legend.y0 >= plot.y1 - 1.0:
        return "bottom"
    if legend.x0 >= plot.x1 - 1.0:
        return "right"
    if legend.x1 <= plot.x0 + 1.0:
        return "left"
    if legend.y1 <= plot.y0 + 1.0:
        return "top"
    return "bottom" if _is_polar_replacement(replacement.kind) else "right"


def _legend_rect_for_plot(replacement: ChartReplacement, plot_rect: fitz.Rect) -> fitz.Rect | None:
    if replacement.legend_rect is None:
        return None
    original_plot = fitz.Rect(replacement.rect)
    original_legend = fitz.Rect(replacement.legend_rect)
    width = original_legend.width
    height = original_legend.height
    gap = 6.0
    orientation = _legend_orientation(replacement)
    if orientation == "right":
        center_y = (plot_rect.y0 + plot_rect.y1) / 2.0
        return fitz.Rect(plot_rect.x1 + gap, center_y - height / 2.0, plot_rect.x1 + gap + width, center_y + height / 2.0)
    if orientation == "left":
        center_y = (plot_rect.y0 + plot_rect.y1) / 2.0
        return fitz.Rect(plot_rect.x0 - gap - width, center_y - height / 2.0, plot_rect.x0 - gap, center_y + height / 2.0)
    if orientation == "top":
        center_x = (plot_rect.x0 + plot_rect.x1) / 2.0
        return fitz.Rect(center_x - width / 2.0, plot_rect.y0 - gap - height, center_x + width / 2.0, plot_rect.y0 - gap)
    center_x = (plot_rect.x0 + plot_rect.x1) / 2.0
    legend_width = max(width, min(plot_rect.width, max(width, original_plot.width)))
    return fitz.Rect(center_x - legend_width / 2.0, plot_rect.y1 + gap, center_x + legend_width / 2.0, plot_rect.y1 + gap + height)


def _shift_chart_replacement(replacement: ChartReplacement, dx: float, dy: float) -> ChartReplacement:
    legend_rect = None if replacement.legend_rect is None else fitz.Rect(
        replacement.legend_rect.x0 + dx,
        replacement.legend_rect.y0 + dy,
        replacement.legend_rect.x1 + dx,
        replacement.legend_rect.y1 + dy,
    )
    erase_rect = None if replacement.erase_rect is None else fitz.Rect(
        replacement.erase_rect.x0 + dx,
        replacement.erase_rect.y0 + dy,
        replacement.erase_rect.x1 + dx,
        replacement.erase_rect.y1 + dy,
    )
    return ChartReplacement(
        replacement.kind,
        fitz.Rect(replacement.rect.x0 + dx, replacement.rect.y0 + dy, replacement.rect.x1 + dx, replacement.rect.y1 + dy),
        replacement.asset_path,
        legend_rect=legend_rect,
        legend_asset_path=replacement.legend_asset_path,
        erase_rect=erase_rect,
        legend_scale_cap=replacement.legend_scale_cap,
    )


def _with_chart_rects(replacement: ChartReplacement, plot_rect: fitz.Rect, legend_rect: fitz.Rect | None) -> ChartReplacement:
    return ChartReplacement(
        replacement.kind,
        fitz.Rect(plot_rect),
        replacement.asset_path,
        legend_rect=fitz.Rect(legend_rect) if legend_rect is not None else None,
        legend_asset_path=replacement.legend_asset_path,
        erase_rect=replacement.erase_rect,
        legend_scale_cap=replacement.legend_scale_cap,
    )


def _scale_reflow_item(replacement: ChartReplacement, scale: float) -> ChartReplacement:
    if scale >= 0.999:
        return replacement
    plot = fitz.Rect(replacement.rect)
    center_x = (plot.x0 + plot.x1) / 2.0
    width = plot.width * scale
    height = plot.height * scale
    scaled_plot = fitz.Rect(center_x - width / 2.0, plot.y0, center_x + width / 2.0, plot.y0 + height)
    scaled_legend = None
    if replacement.legend_rect is not None:
        legend = fitz.Rect(replacement.legend_rect)
        orientation = _legend_orientation(replacement)
        gap = 6.0
        legend_width = legend.width * scale
        legend_height = legend.height * scale
        if orientation == "right":
            center_y = (scaled_plot.y0 + scaled_plot.y1) / 2.0
            scaled_legend = fitz.Rect(scaled_plot.x1 + gap, center_y - legend_height / 2.0, scaled_plot.x1 + gap + legend_width, center_y + legend_height / 2.0)
        elif orientation == "left":
            center_y = (scaled_plot.y0 + scaled_plot.y1) / 2.0
            scaled_legend = fitz.Rect(scaled_plot.x0 - gap - legend_width, center_y - legend_height / 2.0, scaled_plot.x0 - gap, center_y + legend_height / 2.0)
        elif orientation == "top":
            scaled_legend = fitz.Rect(center_x - legend_width / 2.0, scaled_plot.y0 - gap - legend_height, center_x + legend_width / 2.0, scaled_plot.y0 - gap)
        else:
            scaled_legend = fitz.Rect(center_x - legend_width / 2.0, scaled_plot.y1 + gap, center_x + legend_width / 2.0, scaled_plot.y1 + gap + legend_height)
    return _with_chart_rects(replacement, scaled_plot, scaled_legend)


def _fit_reflow_row_width(
    row: list[ChartReplacement],
    content_rect: fitz.Rect,
    item_gap: float,
) -> list[ChartReplacement]:
    has_side_legend = any(_legend_orientation(item) in {"left", "right"} for item in row)
    if len(row) < 3 and not has_side_legend:
        return row
    total_width = sum(_replacement_union_rect(item).width for item in row) + item_gap * (len(row) - 1)
    if total_width <= content_rect.width + 0.1:
        return row
    scale = max(0.2, min(1.0, max(24.0, content_rect.width - 12.0) / total_width))
    return [_scale_reflow_item(item, scale) for item in row]


def _clamp_rect_to_content(rect: fitz.Rect, content_rect: fitz.Rect) -> fitz.Rect:
    width = min(rect.width, content_rect.width)
    height = min(rect.height, content_rect.height)
    x0 = min(max(rect.x0, content_rect.x0), content_rect.x1 - width)
    y0 = min(max(rect.y0, content_rect.y0), content_rect.y1 - height)
    return fitz.Rect(x0, y0, x0 + width, y0 + height)


def _prepare_reflow_item(
    replacement: ChartReplacement,
    content_rect: fitz.Rect,
    *,
    cartesian_figure_width: float | None,
    cartesian_figure_height: float | None,
    polar_figure_size: float | None,
) -> ChartReplacement:
    width, height = _requested_plot_size(
        replacement,
        cartesian_figure_width=cartesian_figure_width,
        cartesian_figure_height=cartesian_figure_height,
        polar_figure_size=polar_figure_size,
    )
    legend = replacement.legend_rect
    side_legend_width = 0.0
    side_gap = 0.0
    if legend is not None and _legend_orientation(replacement) in {"left", "right"}:
        side_legend_width = legend.width
        side_gap = 6.0
    max_width = max(24.0, content_rect.width - side_legend_width - side_gap)
    max_height = max(24.0, content_rect.height - (legend.height + 6.0 if legend is not None and _legend_orientation(replacement) in {"top", "bottom"} else 0.0))
    scale = min(1.0, max_width / width if width else 1.0, max_height / height if height else 1.0)
    width *= scale
    height *= scale
    original = fitz.Rect(replacement.rect)
    center_x = (original.x0 + original.x1) / 2.0
    plot = fitz.Rect(center_x - width / 2.0, original.y0, center_x + width / 2.0, original.y0 + height)
    plot = _clamp_rect_to_content(plot, content_rect)
    return _with_chart_rects(replacement, plot, _legend_rect_for_plot(replacement, plot))


def _reflow_chart_replacements(
    page: fitz.Page,
    replacements: list[ChartReplacement],
    *,
    cartesian_figure_width: float | None,
    cartesian_figure_height: float | None,
    polar_figure_size: float | None,
    return_headings: bool = False,
) -> list[list[ChartReplacement]] | tuple[list[list[ChartReplacement]], list[list[TextSpan]]]:
    if not replacements:
        return ([], []) if return_headings else []
    if cartesian_figure_width is None and cartesian_figure_height is None and polar_figure_size is None:
        return ([replacements], [[]]) if return_headings else [replacements]
    content_rect = _chart_page_content_rect(page, replacements)
    heading_sources = _chart_heading_spans(page)
    row_gap = 16.0
    item_gap = 12.0
    chart_rows = _chart_rows(replacements)
    estimate_used_labels: set[str] = set()
    estimated_heading_height = 0.0
    estimated_plot_height = 0.0
    estimated_row_count = 0
    for row in chart_rows:
        heading_inputs = _reflow_row_heading_inputs(row, heading_sources, estimate_used_labels)
        heading_height = max((source.bbox.height if source is not None else 12.0) for _label, _replacement, source in heading_inputs) if heading_inputs else 0.0
        estimated_heading_height += heading_height + (8.0 if heading_inputs else 0.0)
        for label, _replacement, _source in heading_inputs:
            estimate_used_labels.add(label)
        prepared = _fit_reflow_row_width(
            [
                _prepare_reflow_item(
                    replacement,
                    content_rect,
                    cartesian_figure_width=cartesian_figure_width,
                    cartesian_figure_height=cartesian_figure_height,
                    polar_figure_size=polar_figure_size,
                )
                for replacement in row
            ],
            content_rect,
            item_gap,
        )
        estimated_plot_height += max((_replacement_union_rect(item).height for item in prepared), default=0.0)
        estimated_row_count += 1
    estimated_total_height = estimated_heading_height + estimated_plot_height + row_gap * max(0, estimated_row_count - 1)
    global_scale = 1.0
    if estimated_total_height > content_rect.height + 0.1:
        scalable_height = max(1.0, estimated_plot_height)
        available_plot_height = content_rect.height - estimated_heading_height - row_gap * max(0, estimated_row_count - 1) - 24.0
        candidate_scale = min(1.0, available_plot_height / scalable_height)
        if candidate_scale >= 0.75:
            global_scale = candidate_scale
    pages: list[list[ChartReplacement]] = [[]]
    page_headings: list[list[TextSpan]] = [[]]
    used_heading_labels: set[str] = set()
    current_y = content_rect.y0
    for row in chart_rows:
        heading_inputs = _reflow_row_heading_inputs(row, heading_sources, used_heading_labels)
        heading_height = max((source.bbox.height if source is not None else 12.0) for _label, _replacement, source in heading_inputs) if heading_inputs else 0.0
        row_y = current_y + heading_height + (8.0 if heading_inputs else 0.0)
        prepared = [
            _prepare_reflow_item(
                replacement,
                content_rect,
                cartesian_figure_width=cartesian_figure_width,
                cartesian_figure_height=cartesian_figure_height,
                polar_figure_size=polar_figure_size,
            )
            for replacement in row
        ]
        prepared = _fit_reflow_row_width(prepared, content_rect, item_gap)
        if global_scale < 0.999:
            prepared = [_scale_reflow_item(item, global_scale) for item in prepared]
        shifted_row: list[ChartReplacement] = []
        x_cursor = content_rect.x0
        line_bottom = row_y
        for item in prepared:
            union = _replacement_union_rect(item)
            shifted = _shift_chart_replacement(item, x_cursor - union.x0, row_y - union.y0)
            shifted_union = _replacement_union_rect(shifted)
            if shifted_row and shifted_union.x1 > content_rect.x1 + 0.1:
                row_y = line_bottom + item_gap
                shifted = _shift_chart_replacement(item, content_rect.x0 - union.x0, row_y - union.y0)
            shifted_row.append(shifted)
            shifted_union = _replacement_union_rect(shifted)
            x_cursor = shifted_union.x1 + item_gap
            line_bottom = max(line_bottom, shifted_union.y1)
        if line_bottom > content_rect.y1 + 0.1 and pages[-1]:
            pages.append([])
            page_headings.append([])
            used_heading_labels = set()
            current_y = content_rect.y0
            heading_inputs = _reflow_row_heading_inputs(row, heading_sources, used_heading_labels)
            heading_height = max((source.bbox.height if source is not None else 12.0) for _label, _replacement, source in heading_inputs) if heading_inputs else 0.0
            row_y = current_y + heading_height + (8.0 if heading_inputs else 0.0)
            shifted_row = []
            x_cursor = content_rect.x0
            line_bottom = row_y
            for item in prepared:
                union = _replacement_union_rect(item)
                shifted = _shift_chart_replacement(item, x_cursor - union.x0, row_y - union.y0)
                shifted_union = _replacement_union_rect(shifted)
                if shifted_row and shifted_union.x1 > content_rect.x1 + 0.1:
                    row_y = line_bottom + item_gap
                    shifted = _shift_chart_replacement(item, content_rect.x0 - union.x0, row_y - union.y0)
                shifted_row.append(shifted)
                shifted_union = _replacement_union_rect(shifted)
                x_cursor = shifted_union.x1 + item_gap
                line_bottom = max(line_bottom, shifted_union.y1)
        if heading_inputs and shifted_row:
            heading_y0 = max(24.0, min(_replacement_union_rect(item).y0 for item in shifted_row) - 8.0 - heading_height)
            shifted_by_kind = {item.kind: item for item in shifted_row}
            for label, source_item, source_span in heading_inputs:
                shifted_source = shifted_by_kind.get(source_item.kind, shifted_row[0])
                heading_x = _heading_x_for_replacement(label, shifted_source, source_span, content_rect)
                page_headings[-1].append(_position_chart_heading_span(label, source_span, heading_x, heading_y0))
                used_heading_labels.add(label)
        pages[-1].extend(shifted_row)
        current_y = line_bottom + row_gap
    pairs = [(page_replacements, headings) for page_replacements, headings in zip(pages, page_headings) if page_replacements]
    page_results = [page_replacements for page_replacements, _headings in pairs]
    heading_results = [headings for _page_replacements, headings in pairs]
    return (page_results, heading_results) if return_headings else page_results


def _erase_chart_replacements_from_page(page: fitz.Page, replacements: list[ChartReplacement]) -> None:
    for replacement in replacements:
        page.add_redact_annot(replacement.erase_rect or replacement.rect, fill=(1.0, 1.0, 1.0))
        if replacement.legend_rect is not None:
            page.add_redact_annot(replacement.legend_rect, fill=(1.0, 1.0, 1.0))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)


def _place_chart_replacements_on_page(
    page: fitz.Page,
    replacements: list[ChartReplacement],
    *,
    cartesian_figure_width: float | None = None,
    cartesian_figure_height: float | None = None,
    polar_figure_size: float | None = None,
    replacement_rects_are_final: bool = False,
) -> None:
    shared_side_scale = _shared_side_legend_scale(replacements)
    for replacement in replacements:
        top_align = _is_netqui_cartesian_replacement(replacement.kind)
        enforce_plot_box = replacement_rects_are_final
        if replacement_rects_are_final:
            plot_placement_rect = fitz.Rect(replacement.rect)
        elif _is_cartesian_replacement(replacement.kind):
            enforce_plot_box = cartesian_figure_width is not None and cartesian_figure_height is not None
            plot_placement_rect = _cartesian_svg_rect(
                replacement.rect,
                replacement.asset_path,
                top_align=top_align,
                figure_width=cartesian_figure_width,
                figure_height=cartesian_figure_height,
            )
        elif _is_polar_replacement(replacement.kind):
            enforce_plot_box = polar_figure_size is not None
            plot_placement_rect = _polar_svg_rect(
                replacement.rect,
                replacement.asset_path,
                top_align=top_align,
                figure_size=polar_figure_size,
            )
        else:
            plot_placement_rect = _fitted_svg_rect(replacement.rect, replacement.asset_path, top_align=top_align)
        _place_svg_as_vector(page, plot_placement_rect, replacement.asset_path, keep_proportion=not enforce_plot_box)
        if replacement.legend_rect is not None and replacement.legend_asset_path is not None:
            legend_scale = None if _is_polar_radiation_replacement(replacement.kind) else shared_side_scale
            _place_svg_as_vector(page, _legend_target_rect(replacement, legend_scale, plot_placement_rect), replacement.legend_asset_path)


def _apply_chart_replacements_to_page(
    page: fitz.Page,
    replacements: list[ChartReplacement],
    *,
    cartesian_figure_width: float | None = None,
    cartesian_figure_height: float | None = None,
    polar_figure_size: float | None = None,
) -> None:
    _erase_chart_replacements_from_page(page, replacements)
    _place_chart_replacements_on_page(
        page,
        replacements,
        cartesian_figure_width=cartesian_figure_width,
        cartesian_figure_height=cartesian_figure_height,
        polar_figure_size=polar_figure_size,
    )


def _is_custom_figure_size(value: float | None, default: float) -> bool:
    return value is not None and abs(float(value) - float(default)) > 0.001


def _placement_figure_sizes(
    cartesian_figure_width: float | None,
    cartesian_figure_height: float | None,
    polar_figure_size: float | None,
) -> tuple[float | None, float | None, float | None]:
    cartesian_is_custom = (
        _is_custom_figure_size(cartesian_figure_width, CARTESIAN_FIGURE_WIDTH_IN)
        or _is_custom_figure_size(cartesian_figure_height, CARTESIAN_FIGURE_HEIGHT_IN)
    )
    polar_is_custom = _is_custom_figure_size(polar_figure_size, POLAR_FIGURE_SIZE_IN)
    return (
        float(cartesian_figure_width) if cartesian_is_custom and cartesian_figure_width is not None else None,
        float(cartesian_figure_height) if cartesian_is_custom and cartesian_figure_height is not None else None,
        float(polar_figure_size) if polar_is_custom and polar_figure_size is not None else None,
    )


def _append_chart_continuation_page(doc: fitz.Document, after_page_index: int, source_page: fitz.Page) -> fitz.Page:
    page = doc.new_page(pno=after_page_index + 1, width=source_page.rect.width, height=source_page.rect.height)
    page.insert_text((36.0, 58.0), "CHARTS CONTINUED", fontsize=10.0, fontname="helv", color=(0.237, 0.237, 0.237))
    return page


def _redraw_chart_headings(page: fitz.Page, headings: list[TextSpan]) -> None:
    if not headings:
        return
    labels = {_normalized_span_text(heading.text) for heading in headings}
    for span in _extract_page_spans(page):
        if _normalized_span_text(span.text) in labels:
            page.add_redact_annot(_expand_rect(fitz.Rect(span.bbox), padding=1.0), fill=None)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

    registered_fonts: set[str] = set()
    for heading in headings:
        text = _normalized_span_text(heading.text)
        pdf_font_name, fontfile, _font_path = _register_pdf_font(page, heading.font, registered_fonts, required_text=text)
        page.insert_text(
            heading.origin,
            text,
            fontsize=heading.size,
            fontname=pdf_font_name,
            fontfile=fontfile,
            color=_int_color_to_rgb(heading.color),
        )


def _apply_chart_replacements_to_document(
    doc: fitz.Document,
    page_index: int,
    replacements: list[ChartReplacement],
    *,
    cartesian_figure_width: float | None = None,
    cartesian_figure_height: float | None = None,
    polar_figure_size: float | None = None,
    allow_reflow: bool = True,
) -> int:
    page = doc[page_index]
    should_reflow = allow_reflow and (
        _is_custom_figure_size(cartesian_figure_width, CARTESIAN_FIGURE_WIDTH_IN)
        or _is_custom_figure_size(cartesian_figure_height, CARTESIAN_FIGURE_HEIGHT_IN)
        or _is_custom_figure_size(polar_figure_size, POLAR_FIGURE_SIZE_IN)
    )
    if not should_reflow:
        placement_width, placement_height, placement_polar_size = _placement_figure_sizes(
            cartesian_figure_width,
            cartesian_figure_height,
            polar_figure_size,
        )
        _apply_chart_replacements_to_page(
            page,
            replacements,
            cartesian_figure_width=placement_width,
            cartesian_figure_height=placement_height,
            polar_figure_size=placement_polar_size,
        )
        return page_index
    pages, page_headings = _reflow_chart_replacements(
        page,
        replacements,
        cartesian_figure_width=cartesian_figure_width,
        cartesian_figure_height=cartesian_figure_height,
        polar_figure_size=polar_figure_size,
        return_headings=True,
    )
    if len(pages) <= 1:
        _erase_chart_replacements_from_page(page, replacements)
        _place_chart_replacements_on_page(page, pages[0] if pages else replacements, replacement_rects_are_final=True)
        if page_headings:
            _redraw_chart_headings(page, page_headings[0])
        return page_index

    _erase_chart_replacements_from_page(page, replacements)
    _place_chart_replacements_on_page(page, pages[0], replacement_rects_are_final=True)
    _redraw_chart_headings(page, page_headings[0] if page_headings else [])
    insert_after = page_index
    for index, page_replacements in enumerate(pages[1:], start=1):
        continuation = _append_chart_continuation_page(doc, insert_after, doc[page_index])
        _place_chart_replacements_on_page(continuation, page_replacements, replacement_rects_are_final=True)
        _redraw_chart_headings(continuation, page_headings[index] if index < len(page_headings) else [])
        insert_after += 1
    return insert_after


def _redraw_netqui_chart_section_titles(
    page: fitz.Page,
    draw_spans: dict[str, TextSpan],
    *,
    registered_fonts: set[str],
    font_buffer: bytes | None,
) -> None:
    if not draw_spans:
        return

    spans: list[TextSpan] = []
    for span in _extract_page_spans(page):
        normalized = _normalized_span_text(span.text)
        if normalized in NETQUI_CHART_SECTION_TITLES:
            spans.append(span)
            continue
        if span.bbox.x0 <= 70.0 and any(title.startswith(normalized) for title in NETQUI_CHART_SECTION_TITLES):
            spans.append(span)

    for span in spans:
        page.add_redact_annot(_expand_rect(fitz.Rect(span.bbox), padding=1.0), fill=None)
    if spans:
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

    for text, draw_span in draw_spans.items():
        if NETQUI_HEADING_FONT_FILE.exists():
            page.insert_font(fontname=NETQUI_HEADING_FONT, fontfile=str(NETQUI_HEADING_FONT_FILE))
            registered_fonts.add(NETQUI_HEADING_FONT)
            pdf_font_name = NETQUI_HEADING_FONT
            fontfile = str(NETQUI_HEADING_FONT_FILE)
        elif font_buffer:
            page.insert_font(fontname=NETQUI_HEADING_FONT, fontbuffer=font_buffer)
            registered_fonts.add(NETQUI_HEADING_FONT)
            pdf_font_name = NETQUI_HEADING_FONT
            fontfile = None
        else:
            pdf_font_name, fontfile, _font_path = _register_pdf_font(page, "MyriadPro-Semibold", registered_fonts, required_text=text)
        page.insert_text(
            draw_span.origin,
            text,
            fontsize=draw_span.size,
            fontname=pdf_font_name,
            fontfile=fontfile,
            color=_int_color_to_rgb(draw_span.color),
        )


def _compact_netqui_chart_sections(
    page: fitz.Page,
    adapter: DatasheetTemplateAdapter | None,
    ordered_slots: list[ChartSlot],
    output: Path,
    extract_workbook: Path,
    artifact_manifest: dict[str, object] | None,
) -> dict[str, TextSpan]:
    if adapter is None or not adapter.key.startswith("netqui") or adapter.manifest is None or adapter.manifest.chart_layout is None:
        return {}
    page_text = page.get_text("text").upper()
    if "ANTENNA GAIN" not in page_text or "ANTENNA BEAMWIDTH" not in page_text:
        return {}
    spans = _extract_page_spans(page)
    shifted = _netqui_shifted_heading_spans(
        page,
        ordered_slots,
        spans,
        adapter.manifest.chart_layout,
        output,
        extract_workbook,
        artifact_manifest,
    )
    return {
        title: shifted.get(title, span)
        for title in NETQUI_CHART_SECTION_TITLES
        if (span := _netqui_heading_span(spans, title)) is not None
    }


def _netqui_spans_with_compacted_headings(spans: list[TextSpan], draw_spans: dict[str, TextSpan]) -> list[TextSpan]:
    if not draw_spans:
        return spans
    return [draw_spans.get(_normalized_span_text(span.text), span) for span in spans]


def _netqui_six_radiation_slots(page: fitz.Page, base_slots: list[ChartSlot]) -> list[fitz.Rect]:
    source = [fitz.Rect(slot.rect) for slot in base_slots[:3]]
    if len(source) < 3:
        return source
    top = min(rect.y0 for rect in source)
    original_height = max(rect.height for rect in source)
    bottom_limit = page.rect.height - 78.0
    bottom = min(bottom_limit, top + original_height * 2.0 + 8.0)
    row_gap = 8.0
    row_height = (bottom - top - row_gap) / 2.0
    if row_height < 92.0:
        return source
    rows: list[fitz.Rect] = []
    for row_index in range(2):
        y0 = top + row_index * (row_height + row_gap)
        y1 = y0 + row_height
        for rect in source:
            rows.append(fitz.Rect(rect.x0, y0, rect.x1, y1))
    return rows


def _netqui_radiation_slots(page: fitz.Page, base_slots: list[ChartSlot], count: int) -> list[fitz.Rect]:
    source = [fitz.Rect(slot.rect) for slot in base_slots[:3]]
    if count <= 0 or not source:
        return []
    columns = min(3, len(source))
    row_count = math.ceil(count / columns)
    top = min(rect.y0 for rect in source)
    bottom_limit = page.rect.height - 78.0
    row_gap = 8.0
    native_height = max(rect.height for rect in source)
    row_height = min(native_height, (bottom_limit - top - row_gap * max(0, row_count - 1)) / max(1, row_count))
    if row_height < 90.0 and row_count > 1:
        row_count = 1
        row_height = min(native_height, bottom_limit - top)
    slots: list[fitz.Rect] = []
    for row_index in range(row_count):
        y0 = top + row_index * (row_height + row_gap)
        y1 = y0 + row_height
        if y1 > bottom_limit:
            break
        for column_index in range(columns):
            if len(slots) >= count:
                break
            rect = source[column_index]
            slots.append(fitz.Rect(rect.x0, y0, rect.x1, y1))
    return slots


def _build_netqui_1pol_placeholder_chart_replacements(
    page: fitz.Page,
    ordered_slots: list[ChartSlot],
    output: Path,
    extract_workbook: Path,
    artifact_manifest: dict[str, object] | None = None,
    selected_radiation_frequencies: list[float] | None = None,
) -> list[ChartReplacement]:
    aligned_slots = _align_netqui_1pol_cartesian_slots(ordered_slots)
    if len(aligned_slots) < 7:
        raise ValueError("Netqui 1Pol placeholder template requires at least seven chart image slots.")
    replacements = _build_manifest_chart_replacements(
        page,
        aligned_slots,
        output,
        extract_workbook,
        NETQUI_1POL_TEMPLATE_MANIFEST.chart_layout,
        _extract_page_spans(page),
        artifact_manifest=artifact_manifest,
    )
    if selected_radiation_frequencies is None:
        radiation_assets = _find_combined_polar_series_assets(
            output,
            extract_workbook,
            artifact_manifest=artifact_manifest,
            chart_key="polar_combined_planes",
            count=6,
        )
    else:
        radiation_assets = _find_selected_combined_polar_assets(
            output,
            extract_workbook,
            selected_radiation_frequencies,
            artifact_manifest,
            chart_key="polar_combined_planes",
        )
    radiation_slots = _netqui_radiation_slots(page, aligned_slots[4:7], len(radiation_assets))
    non_radiation = [replacement for replacement in replacements if not replacement.kind.startswith("radiation_")]
    for index, asset in enumerate(radiation_assets[: len(radiation_slots)]):
        legend_asset = _legend_asset_path(asset, artifact_manifest)
        plot_rect, legend_rect = netqui_polar_rects(radiation_slots[index])
        non_radiation.append(
            ChartReplacement(
                f"radiation_{index + 1}",
                plot_rect,
                asset,
                legend_rect=legend_rect if legend_asset.exists() else None,
                legend_asset_path=legend_asset if legend_asset.exists() else None,
                erase_rect=radiation_slots[index],
                legend_scale_cap=NETQUI_POLAR_LEGEND_SCALE_CAP,
            )
        )
    return non_radiation


def _append_netqui_1pol_placeholder_radiation_page(
    doc: fitz.Document,
    after_page_index: int,
    base_slots: list[ChartSlot],
    radiation_assets: list[Path],
    artifact_manifest: dict[str, object] | None,
    *,
    polar_figure_size: float | None = None,
) -> None:
    if not radiation_assets:
        return
    source = [fitz.Rect(slot.rect) for slot in base_slots[:3]]
    if len(source) < 3:
        return
    previous_page = doc[after_page_index]
    page = doc.new_page(pno=after_page_index + 1, width=previous_page.rect.width, height=previous_page.rect.height)
    page.insert_text((36.0, 60.0), "RADIATION PATTERNS", fontsize=12.0, fontname="helv", color=(0.0, 0.0, 0.0))
    page.insert_text((36.0, page.rect.height - 38.0), "01-2000 v1", fontsize=7.0, fontname="helv", color=(0.0, 0.0, 0.0))
    page.insert_text(
        (page.rect.width / 2.0 - 96.0, page.rect.height - 22.0),
        "(c) NETQUI j. s. a.     www.netqui.com      sales@netqui.com",
        fontsize=7.0,
        fontname="helv",
        color=(0.0, 0.0, 0.0),
    )
    top = 112.0
    height = max(rect.height for rect in source)
    slots = [fitz.Rect(rect.x0, top, rect.x1, top + height) for rect in source]
    replacements: list[ChartReplacement] = []
    for index, asset in enumerate(radiation_assets[:3]):
        legend_asset = _legend_asset_path(asset, artifact_manifest)
        plot_rect, legend_rect = netqui_polar_rects(slots[index])
        replacements.append(
            ChartReplacement(
                f"radiation_continued_{index + 1}",
                plot_rect,
                asset,
                legend_rect=legend_rect if legend_asset.exists() else None,
                legend_asset_path=legend_asset if legend_asset.exists() else None,
                erase_rect=slots[index],
                legend_scale_cap=NETQUI_POLAR_LEGEND_SCALE_CAP,
            )
        )
    _apply_chart_replacements_to_page(page, replacements, polar_figure_size=polar_figure_size)


def _append_netqui_radiation_pages(
    doc: fitz.Document,
    after_page_index: int,
    base_slots: list[ChartSlot],
    radiation_assets: list[Path],
    artifact_manifest: dict[str, object] | None,
    *,
    polar_figure_size: float | None = None,
) -> None:
    remaining = list(radiation_assets)
    insert_after = after_page_index
    while remaining:
        chunk, remaining = remaining[:3], remaining[3:]
        _append_netqui_1pol_placeholder_radiation_page(
            doc,
            insert_after,
            base_slots,
            chunk,
            artifact_manifest,
            polar_figure_size=polar_figure_size,
        )
        insert_after += 1


def _build_netqui_1pol_selected_chart_replacements(
    page: fitz.Page,
    ordered_slots: list[ChartSlot],
    output: Path,
    extract_workbook: Path,
    artifact_manifest: dict[str, object] | None,
    selected_radiation_frequencies: list[float],
) -> list[ChartReplacement]:
    aligned_slots = _align_netqui_1pol_cartesian_slots(ordered_slots)
    replacements = _build_manifest_chart_replacements(
        page,
        aligned_slots,
        output,
        extract_workbook,
        NETQUI_1POL_TEMPLATE_MANIFEST.chart_layout,
        _extract_page_spans(page),
        artifact_manifest=artifact_manifest,
    )
    replacements = [replacement for replacement in replacements if not replacement.kind.startswith("radiation_")]
    radiation_assets = _find_selected_combined_polar_assets(
        output,
        extract_workbook,
        selected_radiation_frequencies,
        artifact_manifest,
        chart_key="polar_combined_planes",
    )
    radiation_slots = _netqui_radiation_slots(page, aligned_slots[4:7], len(radiation_assets))
    for index, asset in enumerate(radiation_assets[: len(radiation_slots)]):
        legend_asset = _legend_asset_path(asset, artifact_manifest)
        plot_rect, legend_rect = netqui_polar_rects(radiation_slots[index])
        replacements.append(
            ChartReplacement(
                f"radiation_{index + 1}",
                plot_rect,
                asset,
                legend_rect=legend_rect if legend_asset.exists() else None,
                legend_asset_path=legend_asset if legend_asset.exists() else None,
                erase_rect=radiation_slots[index],
                legend_scale_cap=NETQUI_POLAR_LEGEND_SCALE_CAP,
            )
        )
    return replacements


def _rfe_polar_rects(slot_rect: fitz.Rect) -> tuple[fitz.Rect, fitz.Rect]:
    full = fitz.Rect(slot_rect)
    legend_height = min(max(full.height * 0.18, 20.0), 28.0)
    plot = fitz.Rect(full.x0, full.y0, full.x1, full.y1 - legend_height - 2.0)
    plot_width = min(plot.width, plot.height)
    plot_center_x = (plot.x0 + plot.x1) / 2.0
    plot = fitz.Rect(plot_center_x - plot_width / 2.0, plot.y0, plot_center_x + plot_width / 2.0, plot.y0 + plot_width)
    legend = fitz.Rect(plot.x0, full.y1 - legend_height, plot.x1, full.y1)
    return plot, legend


def _rfe_heading_span(spans: list[TextSpan], text: str) -> TextSpan | None:
    target = text.strip().upper()
    return next((span for span in spans if span.text.strip().upper() == target), None)


def _insert_rfe_heading(page: fitz.Page, text: str, x: float, y: float, source_span: TextSpan | None) -> None:
    font_name = source_span.font if source_span is not None else ("MyriadPro-Semibold" if MYRIAD_FONT_FILES["MyriadPro-Semibold"].exists() else "helv")
    font_size = float(source_span.size) if source_span is not None else 10.0
    color = _int_color_to_rgb(source_span.color) if source_span is not None else (0.9, 0.0, 0.0)
    pdf_font_name, fontfile, _font_path = _register_pdf_font(page, font_name, set(), required_text=text)
    page.insert_text((x, y), text, fontsize=font_size, fontname=pdf_font_name, fontfile=fontfile, color=color)


def _rfe_template_polar_legend_rects(spans: list[TextSpan]) -> list[fitz.Rect]:
    rects: list[fitz.Rect] = []
    for span in spans:
        text = span.text.strip()
        if "Port Pattern" not in text and not (re.search(r"\b(?:Azimuth|Elevation)\b", text, re.IGNORECASE) and re.search(r"\bGHz\b", text, re.IGNORECASE)):
            continue
        rect = fitz.Rect(span.bbox)
        rects.append(fitz.Rect(rect.x0 - 34.0, rect.y0 - 20.0, rect.x1 + 34.0, rect.y1 + 8.0))
    return rects


def _erase_page_rects(page: fitz.Page, rects: list[fitz.Rect]) -> None:
    if not rects:
        return
    for rect in rects:
        page.add_redact_annot(rect, fill=(1.0, 1.0, 1.0))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)


def _rfe_radiation_slot_pairs(page: fitz.Page, azimuth_slot: ChartSlot, elevation_slot: ChartSlot, count: int) -> list[tuple[fitz.Rect, fitz.Rect]]:
    if count <= 0:
        return []
    row_gap = 16.0
    bottom_limit = page.rect.height - 54.0
    row_top = min(azimuth_slot.rect.y0, elevation_slot.rect.y0)
    row_height = max(60.0, azimuth_slot.rect.height, elevation_slot.rect.height)
    pairs: list[tuple[fitz.Rect, fitz.Rect]] = []
    for index in range(count):
        y0 = row_top + index * (row_height + row_gap)
        y1 = y0 + row_height
        if y1 > bottom_limit:
            break
        pairs.append((
            fitz.Rect(azimuth_slot.rect.x0, y0, azimuth_slot.rect.x1, y1),
            fitz.Rect(elevation_slot.rect.x0, y0, elevation_slot.rect.x1, y1),
        ))
    return pairs


def _build_rfe_selected_chart_replacements(
    page: fitz.Page,
    ordered_slots: list[ChartSlot],
    output: Path,
    extract_workbook: Path,
    artifact_manifest: dict[str, object] | None,
    adapter: DatasheetTemplateAdapter,
    selected_radiation_frequencies: list[float],
) -> tuple[list[ChartReplacement], list[tuple[Path, Path]], list[ChartSlot]]:
    spans = _extract_page_spans(page)
    ordered_slots = order_chart_slots_first_two_then_x(ordered_slots)
    replacements = _build_manifest_chart_replacements(
        page,
        ordered_slots,
        output,
        extract_workbook,
        adapter.manifest.chart_layout,
        spans,
        artifact_manifest=artifact_manifest,
    )
    replacements = [replacement for replacement in replacements if replacement.kind not in {"azimuth", "elevation"}]
    if len(ordered_slots) < 4:
        return replacements, [], []
    azimuth_slot = ChartSlot(_reserve_rfe_chart_heading_space(ordered_slots[2].rect, spans, "azimuth"), ordered_slots[2].image_name)
    elevation_slot = ChartSlot(_reserve_rfe_chart_heading_space(ordered_slots[3].rect, spans, "elevation"), ordered_slots[3].image_name)
    pairs = _find_selected_polar_single_asset_pairs(output, extract_workbook, selected_radiation_frequencies, artifact_manifest)
    slot_pairs = _rfe_radiation_slot_pairs(page, azimuth_slot, elevation_slot, len(pairs))
    for index, ((azimuth_asset, elevation_asset), (azimuth_rect, elevation_rect)) in enumerate(zip(pairs, slot_pairs), start=1):
        for kind, asset, rect in (
            (f"azimuth_{index}", azimuth_asset, azimuth_rect),
            (f"elevation_{index}", elevation_asset, elevation_rect),
        ):
            legend_asset = _legend_asset_path(asset, artifact_manifest)
            plot_rect, legend_rect = _rfe_polar_rects(rect)
            replacements.append(
                ChartReplacement(
                    kind,
                    plot_rect,
                    asset,
                    legend_rect=legend_rect if legend_asset.exists() else None,
                    legend_asset_path=legend_asset if legend_asset.exists() else None,
                    erase_rect=rect,
                    legend_scale_cap=NETQUI_POLAR_LEGEND_SCALE_CAP,
                )
            )
    return replacements, pairs[len(slot_pairs):], [azimuth_slot, elevation_slot]


def _append_rfe_radiation_pages(
    doc: fitz.Document,
    after_page_index: int,
    base_slots: list[ChartSlot],
    remaining_pairs: list[tuple[Path, Path]],
    artifact_manifest: dict[str, object] | None,
    *,
    polar_figure_size: float | None = None,
) -> None:
    if len(base_slots) < 2:
        return
    azimuth_source, elevation_source = base_slots[0], base_slots[1]
    insert_after = after_page_index
    remaining = list(remaining_pairs)
    while remaining:
        previous_page = doc[insert_after]
        previous_spans = _extract_page_spans(previous_page)
        azimuth_heading = _rfe_heading_span(previous_spans, "AZIMUTH PATTERN")
        elevation_heading = _rfe_heading_span(previous_spans, "ELEVATION PATTERN")
        page = doc.new_page(pno=insert_after + 1, width=previous_page.rect.width, height=previous_page.rect.height)
        _insert_rfe_heading(page, "AZIMUTH PATTERN", azimuth_source.rect.x0, 50.0, azimuth_heading)
        _insert_rfe_heading(page, "ELEVATION PATTERN", elevation_source.rect.x0, 50.0, elevation_heading)
        top = 76.0
        azimuth_slot = ChartSlot(fitz.Rect(azimuth_source.rect.x0, top, azimuth_source.rect.x1, top + azimuth_source.rect.height), "")
        elevation_slot = ChartSlot(fitz.Rect(elevation_source.rect.x0, top, elevation_source.rect.x1, top + elevation_source.rect.height), "")
        slot_pairs = _rfe_radiation_slot_pairs(page, azimuth_slot, elevation_slot, len(remaining))
        if not slot_pairs:
            raise ValueError("RFE continuation page does not have enough space for selected radiation pattern plots.")
        replacements: list[ChartReplacement] = []
        for index, ((azimuth_asset, elevation_asset), (azimuth_rect, elevation_rect)) in enumerate(zip(remaining, slot_pairs), start=1):
            for kind, asset, rect in (
                (f"azimuth_continued_{index}", azimuth_asset, azimuth_rect),
                (f"elevation_continued_{index}", elevation_asset, elevation_rect),
            ):
                legend_asset = _legend_asset_path(asset, artifact_manifest)
                plot_rect, legend_rect = _rfe_polar_rects(rect)
                replacements.append(
                    ChartReplacement(
                        kind,
                        plot_rect,
                        asset,
                        legend_rect=legend_rect if legend_asset.exists() else None,
                        legend_asset_path=legend_asset if legend_asset.exists() else None,
                        erase_rect=rect,
                        legend_scale_cap=NETQUI_POLAR_LEGEND_SCALE_CAP,
                    )
                )
        pages, page_headings = _reflow_chart_replacements(
            page,
            replacements,
            cartesian_figure_width=None,
            cartesian_figure_height=None,
            polar_figure_size=polar_figure_size,
            return_headings=True,
        )
        _place_chart_replacements_on_page(page, pages[0] if pages else replacements, replacement_rects_are_final=True)
        _redraw_chart_headings(page, page_headings[0] if page_headings else [])
        for index, page_replacements in enumerate(pages[1:], start=1):
            insert_after += 1
            continuation = doc.new_page(pno=insert_after + 1, width=page.rect.width, height=page.rect.height)
            _place_chart_replacements_on_page(continuation, page_replacements, replacement_rects_are_final=True)
            _redraw_chart_headings(continuation, page_headings[index] if index < len(page_headings) else [])
        remaining = remaining[len(slot_pairs):]
        insert_after += 1


def _replace_netqui_1pol_placeholder_chart_images(
    doc: fitz.Document,
    output: Path,
    extract_workbook: Path,
    *,
    artifact_manifest: dict[str, object] | None = None,
    selected_radiation_frequencies: list[float] | None = None,
    registered_fonts: set[str] | None = None,
    netqui_heading_font_buffer: bytes | None = None,
    cartesian_figure_width: float | None = None,
    cartesian_figure_height: float | None = None,
    polar_figure_size: float | None = None,
) -> bool:
    if doc.page_count < 2:
        return False
    page = doc[1]
    slots = _collect_chart_slots(page)
    if len(slots) < 7:
        return False
    ordered_slots = sorted(slots, key=lambda slot: (slot.rect.y0, slot.rect.x0, slot.rect.y1, slot.rect.x1))
    replacements = _build_netqui_1pol_placeholder_chart_replacements(
        page,
        ordered_slots,
        output,
        extract_workbook,
        artifact_manifest=artifact_manifest,
        selected_radiation_frequencies=selected_radiation_frequencies,
    )
    last_chart_page_index = _apply_chart_replacements_to_document(
        doc,
        1,
        replacements,
        cartesian_figure_width=cartesian_figure_width,
        cartesian_figure_height=cartesian_figure_height,
        polar_figure_size=polar_figure_size,
    )
    radiation_count = sum(1 for replacement in replacements if replacement.kind.startswith("radiation_"))
    target_count = 6 if selected_radiation_frequencies is None else len(selected_radiation_frequencies)
    if radiation_count < target_count:
        if selected_radiation_frequencies is None:
            radiation_assets = _find_combined_polar_series_assets(
                output,
                extract_workbook,
                artifact_manifest=artifact_manifest,
                chart_key="polar_combined_planes",
                count=6,
            )
        else:
            radiation_assets = _find_selected_combined_polar_assets(
                output,
                extract_workbook,
                selected_radiation_frequencies,
                artifact_manifest,
                chart_key="polar_combined_planes",
            )
        aligned_slots = _align_netqui_1pol_cartesian_slots(ordered_slots)
        _append_netqui_radiation_pages(
            doc,
            last_chart_page_index,
            aligned_slots[4:7],
            radiation_assets[radiation_count:],
            artifact_manifest,
            polar_figure_size=polar_figure_size,
        )
    return True


def _replace_chart_images(
    doc: fitz.Document,
    output: Path,
    extract_workbook: Path,
    *,
    artifact_manifest: dict[str, object] | None = None,
    adapter: DatasheetTemplateAdapter | None = None,
    selected_radiation_frequencies: list[float] | None = None,
    selected_asset_ids: list[str] | None = None,
    registered_fonts: set[str] | None = None,
    netqui_heading_font_buffer: bytes | None = None,
    cartesian_figure_width: float | None = None,
    cartesian_figure_height: float | None = None,
    polar_figure_size: float | None = None,
) -> None:
    if doc.page_count < 2:
        return
    if adapter is not None and adapter.chart_layout_mode == "netqui_1pol_placeholder":
        if not _replace_netqui_1pol_placeholder_chart_images(
            doc,
            output,
            extract_workbook,
            artifact_manifest=artifact_manifest,
            selected_radiation_frequencies=selected_radiation_frequencies,
            registered_fonts=registered_fonts,
            netqui_heading_font_buffer=netqui_heading_font_buffer,
            cartesian_figure_width=cartesian_figure_width,
            cartesian_figure_height=cartesian_figure_height,
            polar_figure_size=polar_figure_size,
        ):
            raise ValueError("Netqui 1Pol placeholder template does not contain the expected chart image slots.")
        return

    chart_manifest = adapter.manifest.chart_layout if adapter is not None and adapter.manifest is not None else None
    page_index: int | None = None
    if chart_manifest is not None and chart_manifest.page_index is not None:
        if chart_manifest.page_index >= doc.page_count:
            raise ValueError(f"Datasheet template does not contain configured chart page {chart_manifest.page_index + 1}.")
        page_index = chart_manifest.page_index
        page = doc[chart_manifest.page_index]
        if len(_collect_chart_slots(page)) < chart_manifest.min_image_slots:
            raise ValueError(
                f"Datasheet template chart page does not contain the expected {chart_manifest.min_image_slots} image slots."
            )
    else:
        min_image_slots = chart_manifest.min_image_slots if chart_manifest is not None else 2
        page = None
        for index in range(1, doc.page_count):
            candidate = doc[index]
            if len(_collect_chart_slots(candidate)) >= min_image_slots:
                page = candidate
                page_index = index
                break
    if page is None:
        raise ValueError("Datasheet template does not contain the expected chart image slots.")

    if selected_radiation_frequencies is not None and adapter is not None:
        ordered_slots = sorted(_collect_chart_slots(page), key=lambda slot: (slot.rect.y0, slot.rect.x0, slot.rect.y1, slot.rect.x1))
        if adapter.chart_layout_mode == "netqui_1pol":
            replacements = _build_netqui_1pol_selected_chart_replacements(
                page,
                ordered_slots,
                output,
                extract_workbook,
                artifact_manifest,
                selected_radiation_frequencies,
            )
            last_chart_page_index = _apply_chart_replacements_to_document(
                doc,
                int(page_index or 1),
                replacements,
                cartesian_figure_width=cartesian_figure_width,
                cartesian_figure_height=cartesian_figure_height,
                polar_figure_size=polar_figure_size,
            )
            radiation_count = sum(1 for replacement in replacements if replacement.kind.startswith("radiation_"))
            radiation_assets = _find_selected_combined_polar_assets(
                output,
                extract_workbook,
                selected_radiation_frequencies,
                artifact_manifest,
                chart_key="polar_combined_planes",
            )
            if radiation_count < len(radiation_assets):
                aligned_slots = _align_netqui_1pol_cartesian_slots(ordered_slots)
                _append_netqui_radiation_pages(
                    doc,
                    last_chart_page_index,
                    aligned_slots[4:7],
                    radiation_assets[radiation_count:],
                    artifact_manifest,
                    polar_figure_size=polar_figure_size,
                )
            return
        if adapter.key in {"rfe", "generic"}:
            _erase_page_rects(page, _rfe_template_polar_legend_rects(_extract_page_spans(page)))
            replacements, remaining_pairs, base_slots = _build_rfe_selected_chart_replacements(
                page,
                ordered_slots,
                output,
                extract_workbook,
                artifact_manifest,
                adapter,
                selected_radiation_frequencies,
            )
            last_chart_page_index = _apply_chart_replacements_to_document(
                doc,
                int(page_index or 1),
                replacements,
                cartesian_figure_width=cartesian_figure_width,
                cartesian_figure_height=cartesian_figure_height,
                polar_figure_size=polar_figure_size,
            )
            if remaining_pairs:
                _append_rfe_radiation_pages(
                    doc,
                    last_chart_page_index,
                    base_slots,
                    remaining_pairs,
                    artifact_manifest,
                    polar_figure_size=polar_figure_size,
                )
            return

    ordered_slots_for_compaction = sorted(_collect_chart_slots(page), key=lambda slot: (slot.rect.y0, slot.rect.x0, slot.rect.y1, slot.rect.x1))
    draw_spans = _compact_netqui_chart_sections(
        page,
        adapter,
        ordered_slots_for_compaction,
        output,
        extract_workbook,
        artifact_manifest,
    )
    spans_override = _netqui_spans_with_compacted_headings(_extract_page_spans(page), draw_spans)
    replacements = _build_chart_replacements(
        page,
        output,
        extract_workbook,
        artifact_manifest=artifact_manifest,
        adapter=adapter,
        spans_override=spans_override,
        selected_asset_ids=selected_asset_ids,
    )
    _apply_chart_replacements_to_document(
        doc,
        int(page_index or 1),
        replacements,
        cartesian_figure_width=cartesian_figure_width,
        cartesian_figure_height=cartesian_figure_height,
        polar_figure_size=polar_figure_size,
    )
    custom_figure_size = (
        _is_custom_figure_size(cartesian_figure_width, CARTESIAN_FIGURE_WIDTH_IN)
        or _is_custom_figure_size(cartesian_figure_height, CARTESIAN_FIGURE_HEIGHT_IN)
        or _is_custom_figure_size(polar_figure_size, POLAR_FIGURE_SIZE_IN)
    )
    if draw_spans and not custom_figure_size:
        _redraw_netqui_chart_section_titles(
            page,
            draw_spans,
            registered_fonts=registered_fonts if registered_fonts is not None else set(),
            font_buffer=netqui_heading_font_buffer,
        )


def build_datasheet_pdf(
    output: Path,
    template: Path,
    extract_workbook: Path,
    technical_data_workbook: Path | None = None,
    metadata_author: str | None = None,
    radiation_frequencies_ghz: list[float] | tuple[float, ...] | None = None,
    datasheet_type: str = "auto",
    datasheet_layout: str = "auto",
    datasheet_asset_ids: str | list[str] | tuple[str, ...] | None = None,
    technical_data_sheet_name: str | int | None = None,
    technical_data_product_id: str | None = None,
    cartesian_figure_width: float | None = None,
    cartesian_figure_height: float | None = None,
    polar_figure_size: float | None = None,
) -> dict[str, str]:
    total_steps = 4 if technical_data_workbook else 3
    emit_progress("datasheet", 1, total_steps, f"Loading {extract_workbook.name}")
    template = template.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with fitz.open(template) as doc:
        context = build_render_context(
            template,
            doc,
            extract_workbook.resolve(),
            technical_data_workbook.resolve() if technical_data_workbook else None,
            output_dir=output.parent,
            datasheet_type=datasheet_type,
            datasheet_layout=datasheet_layout,
            technical_data_sheet_name=technical_data_sheet_name,
            technical_data_product_id=technical_data_product_id,
        )
        adapter = context.adapter
        model = context.model
        replacements = dict(model.performance_fields)
        tables = resolve_datasheet_tables(model.performance_fields, model.technical_entries, adapter=adapter)
        for label in FIELD_LABELS:
            if label in replacements:
                continue
            row = row_for_fixed_label(tables, label)
            if row is not None:
                replacements[label] = row.value
        now = datetime.now().astimezone()
        output_metadata = _build_pdf_metadata(doc.metadata, output, now, metadata_author=metadata_author)
        page = doc[0]
        page_spans = _extract_page_spans(page)
        slots = _find_replacement_slots(page, FIELD_LABELS, page_spans)
        registered_fonts: set[str] = set()

        next_step = 2
        if technical_data_workbook:
            emit_progress("datasheet", next_step, total_steps, f"Loading {technical_data_workbook.name}")
            replacements.update(
                _apply_technical_data(
                    doc,
                    model.technical_entries,
                    tables,
                    now,
                    adapter=adapter,
                    registered_fonts=registered_fonts,
                )
            )
            next_step += 1

        page = doc[0]
        for slot in slots.values():
            page.add_redact_annot(slot.erase_rect, fill=None)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
        layout_mode = adapter.technical_layout_mode if adapter is not None else "auto"
        if _replace_netqui_table(
            page,
            tables,
            adapter=adapter,
            registered_fonts=registered_fonts,
        ):
            pass
        else:
            table_slots_by_key: dict[str, TechnicalDataRowSlot] = {}
            for table_slot in _technical_data_row_slots(page, layout_mode=layout_mode):
                if key := _normalize_technical_key(table_slot.label):
                    table_slots_by_key[key] = table_slot
                if inferred_label := _infer_field_label_from_template_text(table_slot.label):
                    table_slots_by_key[_normalize_technical_key(inferred_label)] = table_slot
            for label in FIELD_LABELS:
                if label not in slots:
                    continue
                slot = slots[label]
                text = replacements.get(label, TECHNICAL_DATA_PLACEHOLDER)
                table_slot = table_slots_by_key.get(_normalize_technical_key(label))
                if table_slot is not None:
                    rendered_text, is_missing = _text_or_placeholder(text)
                    _insert_wrapped_text(
                        page,
                        table_slot.value_rect,
                        rendered_text,
                        origin=None,
                        font_name=table_slot.value_font_name,
                        font_size=_technical_table_font_size(table_slot.value_font_size, layout_mode),
                        color=MISSING_VALUE_COLOR if is_missing else slot.color,
                        registered_fonts=registered_fonts,
                        center_vertically=True,
                    )
                else:
                    _insert_replacement_slot_text(page, slot, text, registered_fonts=registered_fonts)
            _insert_performance_extra_rows(
                doc,
                page,
                slots,
                tables,
                adapter=adapter,
                registered_fonts=registered_fonts,
            )
            _redraw_template_table_separators(doc[0], adapter)
        emit_progress("datasheet", next_step, total_steps, "Embedding chart assets")
        selected_asset_ids = _parse_asset_ids(datasheet_asset_ids)
        selected_radiation_frequencies = _normalize_selected_radiation_frequencies(radiation_frequencies_ghz)
        selected_asset_frequencies = _radiation_frequencies_from_asset_ids(model.artifact_manifest, selected_asset_ids)
        if selected_asset_frequencies is not None:
            selected_radiation_frequencies = selected_asset_frequencies
        _replace_chart_images(
            doc,
            output,
            extract_workbook,
            artifact_manifest=model.artifact_manifest,
            adapter=adapter,
            selected_radiation_frequencies=selected_radiation_frequencies,
            selected_asset_ids=selected_asset_ids,
            registered_fonts=registered_fonts,
            netqui_heading_font_buffer=_font_buffer_for_display_font(doc, NETQUI_HEADING_FONT),
            cartesian_figure_width=cartesian_figure_width,
            cartesian_figure_height=cartesian_figure_height,
            polar_figure_size=polar_figure_size,
        )
        _update_footer_dates(doc, now, registered_fonts=registered_fonts)
        doc.set_metadata(output_metadata)
        if hasattr(doc, "set_xml_metadata"):
            doc.set_xml_metadata(_build_xmp_metadata(output_metadata, now, now))
        emit_progress("datasheet", total_steps, total_steps, f"Saving {output.name}")
        doc.save(output, garbage=3, deflate=True)

    return replacements


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a datasheet PDF from the extracted workbook.")
    parser.add_argument("output", type=Path, help="Output PDF path.")
    parser.add_argument("--template", type=Path, required=True, help="Template PDF path.")
    parser.add_argument("--extract-workbook", type=Path, required=True, help="Extracted workbook path.")
    parser.add_argument("--technical-data-workbook", type=Path, help="Technical Data Excel workbook path.")
    parser.add_argument("--metadata-author", help="Author value to write into the PDF metadata.")
    parser.add_argument("--radiation-frequencies-ghz", help="Comma-separated radiation pattern frequencies to include in GHz.")
    parser.add_argument("--datasheet-type", default="auto", help="Datasheet spec key to use, or auto.")
    parser.add_argument("--datasheet-layout", default="auto", help="Datasheet layout key to use, or auto.")
    parser.add_argument("--datasheet-asset-ids", help="Comma-separated generated image asset IDs selected for the datasheet.")
    parser.add_argument("--technical-data-sheet", help="Technical Data worksheet name or index.")
    parser.add_argument("--technical-data-product-id", help="Product ID to select from a wide Technical Data table.")
    parser.add_argument("--cartesian-figure-width", type=float, help="Current cartesian figure width in inches.")
    parser.add_argument("--cartesian-figure-height", type=float, help="Current cartesian figure height in inches.")
    parser.add_argument("--polar-figure-size", type=float, help="Current square polar figure size in inches.")
    return parser.parse_args()


def _parse_radiation_frequencies_arg(value: str | None) -> list[float] | None:
    if value is None:
        return None
    parsed: list[float] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        parsed.append(float(item))
    return _normalize_selected_radiation_frequencies(parsed) or []


def _parse_sheet_selector_arg(value: str | None) -> str | int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return text


def main() -> int:
    args = parse_args()
    try:
        replacements = build_datasheet_pdf(
            output=args.output,
            template=args.template,
            extract_workbook=args.extract_workbook,
            technical_data_workbook=args.technical_data_workbook,
            metadata_author=args.metadata_author,
            radiation_frequencies_ghz=_parse_radiation_frequencies_arg(args.radiation_frequencies_ghz),
            datasheet_type=args.datasheet_type,
            datasheet_layout=args.datasheet_layout,
            datasheet_asset_ids=args.datasheet_asset_ids,
            technical_data_sheet_name=_parse_sheet_selector_arg(args.technical_data_sheet),
            technical_data_product_id=args.technical_data_product_id,
            cartesian_figure_width=args.cartesian_figure_width,
            cartesian_figure_height=args.cartesian_figure_height,
            polar_figure_size=args.polar_figure_size,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"Wrote datasheet PDF to {args.output}")
    for label in FIELD_LABELS:
        print(f"{label}: {replacements.get(label, TECHNICAL_DATA_PLACEHOLDER)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
