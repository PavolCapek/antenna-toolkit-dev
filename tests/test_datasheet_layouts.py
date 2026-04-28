from __future__ import annotations

import unittest
from dataclasses import dataclass

import fitz

from datasheet.layouts.netqui_1pol import align_1pol_cartesian_slots, beamwidth_rects, top_chart_rects
from datasheet.layouts.rfe import order_chart_slots_first_two_then_x
from datasheet.templates import NETQUI_1POL_TEMPLATE_ADAPTER, RFE_TEMPLATE_ADAPTER


@dataclass(frozen=True)
class Slot:
    rect: fitz.Rect
    image_name: str


class DatasheetLayoutTests(unittest.TestCase):
    def test_netqui_1pol_cartesian_slots_align_to_square_grid_columns(self) -> None:
        rows = [
            [Slot(fitz.Rect(40, 50, 260, 220), "gain"), Slot(fitz.Rect(270, 48, 490, 220), "vswr")],
            [Slot(fitz.Rect(40, 280, 292, 450), "e"), Slot(fitz.Rect(296, 280, 548, 450), "h")],
            [Slot(fitz.Rect(40, 500, 200, 650), "low")],
        ]

        aligned = align_1pol_cartesian_slots(rows, Slot)

        self.assertEqual(aligned[0].rect.x0, aligned[2].rect.x0)
        self.assertEqual(aligned[0].rect.x1, aligned[2].rect.x1)
        self.assertEqual(aligned[1].rect.x0, aligned[3].rect.x0)
        self.assertEqual(aligned[1].rect.x1, aligned[3].rect.x1)
        self.assertEqual(aligned[0].rect.y0, aligned[1].rect.y0)
        self.assertEqual(aligned[2].rect.y0, aligned[3].rect.y0)
        self.assertEqual(aligned[4].image_name, "low")

    def test_netqui_cartesian_legend_lanes_are_consistent(self) -> None:
        top_plot, top_legend = top_chart_rects(fitz.Rect(40, 50, 292, 220))
        beam_plot, beam_legend = beamwidth_rects(fitz.Rect(40, 280, 292, 450))

        self.assertAlmostEqual(top_plot.x1, beam_plot.x1, delta=0.01)
        self.assertAlmostEqual(top_legend.x0, beam_legend.x0, delta=0.01)

    def test_rfe_orders_polar_slots_by_column_after_cartesian_slots(self) -> None:
        slots = [
            Slot(fitz.Rect(50, 50, 200, 150), "gain"),
            Slot(fitz.Rect(50, 180, 200, 280), "beamwidth"),
            Slot(fitz.Rect(300, 300, 400, 400), "elevation"),
            Slot(fitz.Rect(100, 300, 200, 400), "azimuth"),
        ]

        ordered = order_chart_slots_first_two_then_x(slots)

        self.assertEqual([slot.image_name for slot in ordered], ["gain", "beamwidth", "azimuth", "elevation"])

    def test_current_template_manifests_reference_named_layout_modes(self) -> None:
        self.assertEqual(NETQUI_1POL_TEMPLATE_ADAPTER.manifest.chart_layout.slot_order, "rows")
        self.assertEqual(RFE_TEMPLATE_ADAPTER.manifest.chart_layout.slot_order, "first_two_then_x")


if __name__ == "__main__":
    unittest.main()
