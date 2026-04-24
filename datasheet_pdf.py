#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import fitz
import pandas as pd

from datasheet_models import (
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
from datasheet_service import build_render_context
from datasheet_templates import DatasheetTemplateAdapter, TemplateChartManifest, TemplateChartSlot

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
    legend_rect: fitz.Rect | None = None
    legend_asset_path: Path | None = None
    erase_rect: fitz.Rect | None = None


@dataclass
class TechnicalDataEntry:
    label: str
    value: str


@dataclass(frozen=True)
class TechnicalDataRowSlot:
    label: str
    label_rect: fitz.Rect
    value_rect: fitz.Rect
    erase_rect: fitz.Rect
    label_font_name: str
    label_font_size: float
    label_color: tuple[float, float, float]
    value_font_name: str
    value_font_size: float
    value_origin: tuple[float, float]
    value_color: tuple[float, float, float]
    row_bottom: float
    table_right: float


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
) -> None:
    pdf_font_name, fontfile, font_path = _register_pdf_font(page, font_name, registered_fonts, required_text=text)
    font = _measurement_font(pdf_font_name, str(font_path) if font_path else None)
    lines = _wrap_text_to_width(text, font, font_size, max(1.0, rect.width))
    line_height = max(font_size * 1.2, font_size + 1.0)
    x = rect.x0 if origin is None else origin[0]
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

    netqui_bounds = _netqui_technical_data_bounds(page, spans) if layout_mode in {"auto", "netqui"} else None
    if netqui_bounds is None:
        return []

    electrical_heading, mechanical_heading, bottom_y = netqui_bounds
    sections = [
        {
            "heading": electrical_heading,
            "label_x0": 25.0,
            "label_x1": 140.0,
            "value_x": 148.5,
            "table_right": 295.0,
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
            if span.bbox.y0 > section["heading"].bbox.y1
            and span.bbox.y0 < bottom_y
            and section["label_x0"] <= span.bbox.x0 <= section["label_x1"]
            and span.bbox.x1 <= section["label_x1"] + 18.0
        ]
        labels.sort(key=lambda span: (span.bbox.y0, span.bbox.x0))
        for index, label_span in enumerate(labels):
            row_top = max(section["heading"].bbox.y1 + 1.0, label_span.bbox.y0 - 1.0)
            next_y = labels[index + 1].bbox.y0 if index + 1 < len(labels) else bottom_y - 6.0
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


def _replace_technical_table(
    doc: fitz.Document,
    entries: list[TechnicalDataEntry],
    *,
    adapter: DatasheetTemplateAdapter | None = None,
    registered_fonts: set[str],
) -> None:
    page = doc[0]
    layout_mode = adapter.technical_layout_mode if adapter is not None else "auto"
    slots = _technical_data_row_slots(page, layout_mode=layout_mode)
    if not slots:
        return
    data_by_key = _technical_data_by_key(entries)
    used_keys: set[str] = set()
    editable_slots = [
        slot
        for slot in slots
        if (key := _normalize_technical_key(slot.label))
        and key not in PERFORMANCE_FIELD_KEYS
    ]
    for slot in editable_slots:
        page.add_redact_annot(slot.erase_rect, fill=None)
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=0)

    for slot in editable_slots:
        key = _normalize_technical_key(slot.label)
        entry = data_by_key.get(key)
        if entry is not None:
            used_keys.add(key)
        text, is_missing = _text_or_placeholder(entry.value if entry is not None else "")
        _insert_wrapped_text(
            page,
            slot.value_rect,
            text,
            origin=slot.value_origin,
            font_name=slot.value_font_name,
            font_size=slot.value_font_size,
            color=MISSING_VALUE_COLOR if is_missing else slot.value_color,
            registered_fonts=registered_fonts,
        )
        page.draw_line(
            (36.638, slot.row_bottom),
            (slot.table_right, slot.row_bottom),
            color=(0.13669031858444214, 0.12195010483264923, 0.1252918243408203),
            width=0.25,
            overlay=True,
        )

    extra_entries = [
        entry
        for entry in entries
        if _normalize_technical_key(entry.label) not in used_keys
        and _normalize_technical_key(entry.label) not in TECHNICAL_DATA_RESERVED_KEYS
        and bool(str(entry.value or "").strip())
    ]
    if not extra_entries:
        return

    row_top_offset = 0.5
    row_step = _technical_data_row_step(slots)
    row_height = max(1.0, row_step - row_top_offset)
    region = _technical_data_region(page)
    bottom_limit = (region[1] - 8.0) if region else page.rect.y1 - 72.0
    y = slots[-1].row_bottom + row_top_offset
    prototype = slots[-1]
    remaining: list[TechnicalDataEntry] = []
    for entry in extra_entries:
        if y + row_height <= bottom_limit:
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
            y += row_step
        else:
            remaining.append(entry)

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
    for key, placeholder in (("antenna name", "ANTENNA NAME"), ("product id", "PRODUCT_ID_PLACEHOLDER")):
        entry = data_by_key.get(key)
        text, is_missing = _text_or_placeholder(entry.value if entry is not None else "")
        replacements[key] = text
        for page in doc:
            spans = [span for span in _extract_page_spans(page) if span.text == placeholder]
            for span in spans:
                _replace_exact_span_text(
                    page,
                    span,
                    text,
                    registered_fonts=registered_fonts,
                    color=MISSING_VALUE_COLOR if is_missing else None,
                )
    return replacements


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
    generated_at: datetime,
    *,
    adapter: DatasheetTemplateAdapter | None = None,
    registered_fonts: set[str],
) -> dict[str, str]:
    header_values = _replace_header_placeholders(doc, entries, registered_fonts=registered_fonts)
    _replace_technical_table(doc, entries, adapter=adapter, registered_fonts=registered_fonts)
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


def _netqui_beamwidth_rects(slot_rect: fitz.Rect) -> tuple[fitz.Rect, fitz.Rect]:
    full = fitz.Rect(slot_rect)
    legend_width = min(max(full.width * 0.32, 82.0), 96.0)
    legend = fitz.Rect(full.x1 - legend_width, full.y0 + 6.0, full.x1 - 2.0, full.y1 - 6.0)
    plot = fitz.Rect(full.x0, full.y0, legend.x0 - 6.0, full.y1)
    return plot, legend


def _build_netqui_chart_replacements(
    ordered_slots: list[ChartSlot],
    output: Path,
    extract_workbook: Path,
    artifact_manifest: dict[str, object] | None = None,
) -> list[ChartReplacement]:
    rows = _chart_slot_rows(ordered_slots)
    if len(rows) < 2 or len(rows[0]) < 2 or len(rows[1]) < 2:
        raise ValueError("Netqui datasheet template does not contain the expected gain, VSWR, E-plane, and H-plane chart slots.")
    gain_slot, vswr_slot = rows[0][0], rows[0][1]
    e_plane_slot, h_plane_slot = rows[1][0], rows[1][1]
    gain_asset = _find_manifest_chart_asset(artifact_manifest, "gain") or _find_plot_asset(output, extract_workbook, "-gain.svg")
    replacements: list[ChartReplacement] = [
        ChartReplacement("gain", fitz.Rect(gain_slot.rect), gain_asset),
    ]
    vswr_asset = _find_manifest_chart_asset(artifact_manifest, "vswr") or _find_optional_plot_asset(output, extract_workbook, "-vswr.svg")
    if vswr_asset is not None:
        replacements.append(ChartReplacement("vswr", fitz.Rect(vswr_slot.rect), vswr_asset))

    for slot, kind, plane in [
        (e_plane_slot, "beamwidth_e_plane", "e-plane"),
        (h_plane_slot, "beamwidth_h_plane", "h-plane"),
    ]:
        asset = _find_beamwidth_plane_asset(output, extract_workbook, plane, artifact_manifest=artifact_manifest)
        legend_asset = _legend_asset_path(asset, artifact_manifest)
        plot_rect, legend_rect = _netqui_beamwidth_rects(fitz.Rect(slot.rect))
        replacements.append(
            ChartReplacement(
                kind,
                plot_rect,
                asset,
                legend_rect=legend_rect if legend_asset.exists() else None,
                legend_asset_path=legend_asset if legend_asset.exists() else None,
                erase_rect=fitz.Rect(slot.rect),
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
) -> Path | None:
    if slot_spec.asset_key == "gain":
        return _find_manifest_chart_asset(artifact_manifest, "gain") or _find_plot_asset(output, extract_workbook, "-gain.svg")
    if slot_spec.asset_key == "beamwidth":
        return _find_manifest_chart_asset(artifact_manifest, "beamwidth") or _find_plot_asset(output, extract_workbook, "-beamwidth.svg")
    if slot_spec.asset_key == "vswr":
        return _find_manifest_chart_asset(artifact_manifest, "vswr") or _find_optional_plot_asset(output, extract_workbook, "-vswr.svg")
    if slot_spec.asset_key == "beamwidth_plane":
        if not slot_spec.plane:
            raise ValueError(f"Template chart slot '{slot_spec.kind}' is missing a beamwidth plane.")
        return _find_beamwidth_plane_asset(output, extract_workbook, slot_spec.plane, artifact_manifest=artifact_manifest)
    if slot_spec.asset_key in {"polar_azimuth", "polar_elevation"}:
        azimuth_asset, elevation_asset = _find_polar_plot_assets(page, output, extract_workbook, spans, artifact_manifest=artifact_manifest)
        return azimuth_asset if slot_spec.asset_key == "polar_azimuth" else elevation_asset
    raise ValueError(f"Unknown template chart asset key '{slot_spec.asset_key}'.")


def _build_manifest_chart_replacements(
    page: fitz.Page,
    ordered_slots: list[ChartSlot],
    output: Path,
    extract_workbook: Path,
    chart_manifest: TemplateChartManifest,
    spans: list[TextSpan],
    artifact_manifest: dict[str, object] | None = None,
) -> list[ChartReplacement]:
    if chart_manifest.slot_order == "rows":
        ordered_slots = [slot for row in _chart_slot_rows(ordered_slots) for slot in row]
    elif chart_manifest.slot_order == "first_two_then_x" and len(ordered_slots) > 2:
        ordered_slots = ordered_slots[:2] + sorted(
            ordered_slots[2:],
            key=lambda slot: (slot.rect.x0, slot.rect.y0, slot.rect.y1, slot.rect.x1),
        )
    replacements: list[ChartReplacement] = []
    for slot_spec in chart_manifest.slots:
        if slot_spec.slot_index >= len(ordered_slots):
            if slot_spec.required:
                raise ValueError(
                    f"Datasheet template does not contain required chart slot '{slot_spec.kind}' at index {slot_spec.slot_index}."
                )
            continue
        asset = _manifest_slot_asset(slot_spec, output, extract_workbook, spans, page, artifact_manifest)
        if asset is None:
            if slot_spec.required:
                raise ValueError(f"Missing required chart asset for template slot '{slot_spec.kind}'.")
            continue
        slot_rect = fitz.Rect(ordered_slots[slot_spec.slot_index].rect)
        if slot_spec.legend_mode == "netqui_side":
            legend_asset = _legend_asset_path(asset, artifact_manifest)
            plot_rect, legend_rect = _netqui_beamwidth_rects(slot_rect)
            replacements.append(
                ChartReplacement(
                    slot_spec.kind,
                    plot_rect,
                    asset,
                    legend_rect=legend_rect if legend_asset.exists() else None,
                    legend_asset_path=legend_asset if legend_asset.exists() else None,
                    erase_rect=slot_rect,
                )
            )
        else:
            replacements.append(ChartReplacement(slot_spec.kind, slot_rect, asset))

    auto_legend_kinds = {slot.kind for slot in chart_manifest.slots if slot.legend_mode == "auto"}
    if not auto_legend_kinds:
        return replacements

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
    return _normalize_plot_widths(resolved, set(chart_manifest.normalize_width_kinds))


def _build_chart_replacements(
    page: fitz.Page,
    output: Path,
    extract_workbook: Path,
    *,
    artifact_manifest: dict[str, object] | None = None,
    adapter: DatasheetTemplateAdapter | None = None,
) -> list[ChartReplacement]:
    slots = _collect_chart_slots(page)
    if len(slots) < 2:
        raise ValueError("Datasheet template page 2 does not contain the expected chart image slots.")

    ordered_slots = sorted(slots, key=lambda slot: (slot.rect.y0, slot.rect.x0, slot.rect.y1, slot.rect.x1))
    spans = _extract_page_spans(page)
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
        )

    chart_mode = adapter.chart_layout_mode if adapter is not None else ("netqui" if _is_netqui_chart_page(spans, ordered_slots) else "generic")
    if chart_mode == "netqui":
        return _build_netqui_chart_replacements(ordered_slots, output, extract_workbook, artifact_manifest=artifact_manifest)

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
    return _normalize_plot_widths(resolved, {"gain", "beamwidth"})


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


def _center_rect_with_size(container_rect: fitz.Rect, width: float, height: float) -> fitz.Rect:
    center_x = (container_rect.x0 + container_rect.x1) / 2.0
    center_y = (container_rect.y0 + container_rect.y1) / 2.0
    half_width = width / 2.0
    half_height = height / 2.0
    return fitz.Rect(center_x - half_width, center_y - half_height, center_x + half_width, center_y + half_height)


def _shared_side_legend_scale(replacements: list[ChartReplacement]) -> float | None:
    scales: list[float] = []
    for replacement in replacements:
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
    return min(scales) if scales else None


def _legend_target_rect(replacement: ChartReplacement, shared_side_scale: float | None) -> fitz.Rect:
    if replacement.legend_rect is None or replacement.legend_asset_path is None:
        raise ValueError("Legend placement requires both a legend rect and a legend asset path.")
    container_rect = fitz.Rect(replacement.legend_rect)
    native_width, native_height = _svg_drawing_size(str(replacement.legend_asset_path.resolve()))
    if native_width <= 0.0 or native_height <= 0.0:
        return container_rect
    if shared_side_scale is not None and shared_side_scale > 0.0:
        return _center_rect_with_size(container_rect, native_width * shared_side_scale, native_height * shared_side_scale)
    scale = min(container_rect.width / native_width, container_rect.height / native_height)
    return _center_rect_with_size(container_rect, native_width * scale, native_height * scale)


def _place_svg_as_vector(page: fitz.Page, target_rect: fitz.Rect, svg_path: Path) -> None:
    pdf_bytes = _svg_to_pdf_bytes(svg_path)
    with fitz.open("pdf", pdf_bytes) as pdf_doc:
        page.show_pdf_page(target_rect, pdf_doc, 0, keep_proportion=True, overlay=True)


def _replace_chart_images(
    doc: fitz.Document,
    output: Path,
    extract_workbook: Path,
    *,
    artifact_manifest: dict[str, object] | None = None,
    adapter: DatasheetTemplateAdapter | None = None,
) -> None:
    if doc.page_count < 2:
        return

    chart_manifest = adapter.manifest.chart_layout if adapter is not None and adapter.manifest is not None else None
    if chart_manifest is not None and chart_manifest.page_index is not None:
        if chart_manifest.page_index >= doc.page_count:
            raise ValueError(f"Datasheet template does not contain configured chart page {chart_manifest.page_index + 1}.")
        page = doc[chart_manifest.page_index]
        if len(_collect_chart_slots(page)) < chart_manifest.min_image_slots:
            raise ValueError(
                f"Datasheet template chart page does not contain the expected {chart_manifest.min_image_slots} image slots."
            )
    else:
        min_image_slots = chart_manifest.min_image_slots if chart_manifest is not None else 2
        page = next((candidate for candidate in doc[1:] if len(_collect_chart_slots(candidate)) >= min_image_slots), None)
    if page is None:
        raise ValueError("Datasheet template does not contain the expected chart image slots.")
    replacements = _build_chart_replacements(
        page,
        output,
        extract_workbook,
        artifact_manifest=artifact_manifest,
        adapter=adapter,
    )
    for replacement in replacements:
        page.add_redact_annot(replacement.erase_rect or replacement.rect, fill=(1.0, 1.0, 1.0))
        if replacement.legend_rect is not None:
            page.add_redact_annot(replacement.legend_rect, fill=(1.0, 1.0, 1.0))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)
    shared_side_scale = _shared_side_legend_scale(replacements)
    for replacement in replacements:
        _place_svg_as_vector(page, replacement.rect, replacement.asset_path)
        if replacement.legend_rect is not None and replacement.legend_asset_path is not None:
            _place_svg_as_vector(page, _legend_target_rect(replacement, shared_side_scale), replacement.legend_asset_path)


def build_datasheet_pdf(
    output: Path,
    template: Path,
    extract_workbook: Path,
    technical_data_workbook: Path | None = None,
    metadata_author: str | None = None,
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
        )
        adapter = context.adapter
        model = context.model
        replacements = dict(model.performance_fields)
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
        for label in FIELD_LABELS:
            if label not in slots:
                continue
            slot = slots[label]
            text = replacements[label]
            _insert_replacement_slot_text(page, slot, text, registered_fonts=registered_fonts)

        _redraw_split_table_separators(doc[0])
        emit_progress("datasheet", next_step, total_steps, "Embedding chart assets")
        _replace_chart_images(
            doc,
            output,
            extract_workbook,
            artifact_manifest=model.artifact_manifest,
            adapter=adapter,
        )
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        replacements = build_datasheet_pdf(
            output=args.output,
            template=args.template,
            extract_workbook=args.extract_workbook,
            technical_data_workbook=args.technical_data_workbook,
            metadata_author=args.metadata_author,
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
