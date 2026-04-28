from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz


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
    legend_scale_cap: float | None = None


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
