from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol, TypeVar

import fitz

NETQUI_SLOT_ORDER_ROWS = "rows"
NETQUI_SIDE_LEGEND_SCALE_CAP = 0.48
NETQUI_POLAR_LEGEND_SCALE_CAP = 0.52


class ChartSlotLike(Protocol):
    rect: fitz.Rect
    image_name: str


TChartSlot = TypeVar("TChartSlot", bound=ChartSlotLike)


def beamwidth_rects(slot_rect: fitz.Rect) -> tuple[fitz.Rect, fitz.Rect]:
    full = fitz.Rect(slot_rect)
    legend_width = min(max(full.width * 0.28, 68.0), 78.0)
    legend = fitz.Rect(full.x1 - legend_width, full.y0 + 6.0, full.x1 - 2.0, full.y1 - 6.0)
    plot = fitz.Rect(full.x0, full.y0, legend.x0 - 6.0, full.y1)
    return plot, legend


def top_chart_rects(slot_rect: fitz.Rect) -> tuple[fitz.Rect, fitz.Rect]:
    full = fitz.Rect(slot_rect)
    legend_width = min(max(full.width * 0.28, 68.0), 78.0)
    legend = fitz.Rect(full.x1 - legend_width, full.y0 + 8.0, full.x1 - 2.0, full.y1 - 8.0)
    plot = fitz.Rect(full.x0, full.y0, legend.x0 - 6.0, full.y1)
    return plot, legend


def polar_rects(slot_rect: fitz.Rect) -> tuple[fitz.Rect, fitz.Rect]:
    full = fitz.Rect(slot_rect)
    legend_height = min(max(full.height * 0.15, 20.0), 24.0)
    legend = fitz.Rect(full.x0 + 2.0, full.y1 - legend_height, full.x1 - 2.0, full.y1)
    plot_area = fitz.Rect(full.x0, full.y0, full.x1, legend.y0 - 2.0)
    plot_size = max(1.0, min(plot_area.width, plot_area.height))
    plot = fitz.Rect(
        (plot_area.x0 + plot_area.x1 - plot_size) / 2.0,
        plot_area.y0,
        (plot_area.x0 + plot_area.x1 + plot_size) / 2.0,
        plot_area.y0 + plot_size,
    )
    return plot, legend


def align_1pol_cartesian_slots(
    rows: Sequence[Sequence[TChartSlot]],
    slot_factory: Callable[[fitz.Rect, str], TChartSlot],
) -> list[TChartSlot]:
    if len(rows) < 2 or len(rows[0]) < 2 or len(rows[1]) < 2:
        return [slot for row in rows for slot in row]

    left_top, right_top = rows[0][0], rows[0][1]
    left_bottom, right_bottom = rows[1][0], rows[1][1]
    top_y0 = min(left_top.rect.y0, right_top.rect.y0)
    top_y1 = max(left_top.rect.y1, right_top.rect.y1)
    bottom_y0 = min(left_bottom.rect.y0, right_bottom.rect.y0)
    bottom_y1 = max(left_bottom.rect.y1, right_bottom.rect.y1)
    left_x0 = left_bottom.rect.x0
    left_x1 = left_bottom.rect.x1
    right_x0 = right_bottom.rect.x0
    right_x1 = right_bottom.rect.x1

    aligned = [
        slot_factory(fitz.Rect(left_x0, top_y0, left_x1, top_y1), left_top.image_name),
        slot_factory(fitz.Rect(right_x0, top_y0, right_x1, top_y1), right_top.image_name),
        slot_factory(fitz.Rect(left_x0, bottom_y0, left_x1, bottom_y1), left_bottom.image_name),
        slot_factory(fitz.Rect(right_x0, bottom_y0, right_x1, bottom_y1), right_bottom.image_name),
    ]
    for row in rows[2:]:
        aligned.extend(row)
    return aligned
