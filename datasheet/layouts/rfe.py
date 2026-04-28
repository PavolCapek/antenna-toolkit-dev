from __future__ import annotations

from typing import Protocol, TypeVar

import fitz

RFE_SLOT_ORDER_FIRST_TWO_THEN_X = "first_two_then_x"


class ChartSlotLike(Protocol):
    rect: fitz.Rect


TChartSlot = TypeVar("TChartSlot", bound=ChartSlotLike)


def order_chart_slots_first_two_then_x(ordered_slots: list[TChartSlot]) -> list[TChartSlot]:
    if len(ordered_slots) <= 2:
        return ordered_slots
    return ordered_slots[:2] + sorted(
        ordered_slots[2:],
        key=lambda slot: (slot.rect.x0, slot.rect.y0, slot.rect.y1, slot.rect.x1),
    )
