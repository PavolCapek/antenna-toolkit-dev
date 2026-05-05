from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from datasheet_pdf import (
    _build_chart_replacements,
    _build_netqui_1pol_selected_chart_replacements,
    _build_rfe_selected_chart_replacements,
    _collect_chart_slots,
    _extract_page_spans,
    _legend_target_rect,
    _reflow_chart_replacements,
    _shared_side_legend_scale,
    build_datasheet_pdf,
)
from datasheet.templates import resolve_template_adapter


REPO_ROOT = Path(__file__).resolve().parent.parent


def _require_paths(testcase: unittest.TestCase, paths: list[Path]) -> None:
    missing = [path for path in paths if not path.exists()]
    if missing:
        testcase.skipTest("Missing real-template visual regression fixture: " + ", ".join(str(path) for path in missing))


def _non_white_ratio(page: fitz.Page, rect: fitz.Rect, *, scale: float = 1.0) -> float:
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
    if not pix.samples:
        return 0.0
    non_white = 0
    total = pix.width * pix.height
    for offset in range(0, len(pix.samples), pix.n):
        red, green, blue = pix.samples[offset : offset + 3]
        if min(red, green, blue) < 245:
            non_white += 1
    return non_white / max(total, 1)


def _span_for_text(page: fitz.Page, text: str) -> fitz.Rect:
    for span in _extract_page_spans(page):
        if span.text == text:
            return fitz.Rect(span.bbox)
    raise AssertionError(f"Text not found in rendered page: {text}")


def _font_size_for_text(page: fitz.Page, text: str) -> float:
    for span in _extract_page_spans(page):
        if span.text == text:
            return span.size
    raise AssertionError(f"Text not found in rendered page: {text}")


def _horizontal_table_segments(page: fitz.Page) -> list[tuple[float, float, float]]:
    segments: list[tuple[float, float, float]] = []
    for drawing in page.get_drawings():
        for item in drawing.get("items", []):
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            if abs(p1.y - p2.y) > 0.3:
                continue
            if not (400.0 <= p1.y <= 610.0):
                continue
            if abs(p2.x - p1.x) <= 40.0:
                continue
            segments.append((round(min(p1.x, p2.x), 2), round(max(p1.x, p2.x), 2), round(p1.y, 2)))
    return segments


def _has_left_table_line_below(page: fitz.Page, text: str) -> bool:
    span = _span_for_text(page, text)
    for x0, x1, y in _horizontal_table_segments(page):
        if not (span.y1 <= y <= span.y1 + 8.0):
            continue
        if x0 <= 40.0 and x1 >= 275.0:
            return True
    return False


class DatasheetVisualRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_rfe_real_template_keeps_polar_plots_in_expected_slots(self) -> None:
        template = REPO_ROOT / "Templates" / "Datasheet - RFE.pdf"
        project_dir = REPO_ROOT / "Projects" / "AH60WB"
        extract_workbook = project_dir / "AH60WB-extracted-data.xlsx"
        _require_paths(
            self,
            [
                template,
                extract_workbook,
                project_dir / "AH60WB-gain.svg",
                project_dir / "AH60WB-beamwidth.svg",
                project_dir / "polar_single" / "azimuth",
                project_dir / "polar_single" / "elevation",
            ],
        )
        output = self.output_dir / "ah60wb-rfe.pdf"

        build_datasheet_pdf(output, template, extract_workbook)

        with fitz.open(output) as rendered_doc, fitz.open(template) as template_doc:
            adapter = resolve_template_adapter(template, template_doc)
            replacements = _build_chart_replacements(
                template_doc[1],
                output,
                extract_workbook,
                adapter=adapter,
            )
            by_kind = {replacement.kind: replacement for replacement in replacements}
            page = rendered_doc[1]
            azimuth_title = _span_for_text(page, "AZIMUTH PATTERN")
            elevation_title = _span_for_text(page, "ELEVATION PATTERN")

            self.assertLess(by_kind["azimuth"].rect.x0, by_kind["elevation"].rect.x0)
            self.assertIn("polar-azimuth", by_kind["azimuth"].asset_path.name)
            self.assertIn("polar-elevation", by_kind["elevation"].asset_path.name)
            self.assertLess(azimuth_title.x0, elevation_title.x0)
            self.assertGreater(_non_white_ratio(page, by_kind["azimuth"].rect), 0.03)
            self.assertGreater(_non_white_ratio(page, by_kind["elevation"].rect), 0.03)

    def test_rfe_selected_radiation_reserves_heading_space_and_equalizes_cartesian_widths(self) -> None:
        template = REPO_ROOT / "Templates" / "Datasheet - RFE.pdf"
        project_dir = REPO_ROOT / "Projects" / "AH60WB"
        extract_workbook = project_dir / "AH60WB-extracted-data.xlsx"
        _require_paths(
            self,
            [
                template,
                extract_workbook,
                project_dir / "AH60WB-gain.svg",
                project_dir / "AH60WB-beamwidth.svg",
                project_dir / "polar_single" / "azimuth" / "AH60WB-polar-azimuth-5.500-GHz.svg",
                project_dir / "polar_single" / "elevation" / "AH60WB-polar-elevation-5.500-GHz.svg",
            ],
        )

        with fitz.open(template) as template_doc:
            adapter = resolve_template_adapter(template, template_doc)
            page = template_doc[1]
            ordered_slots = sorted(_collect_chart_slots(page), key=lambda slot: (slot.rect.y0, slot.rect.x0, slot.rect.y1, slot.rect.x1))
            replacements, _remaining_pairs, _base_slots = _build_rfe_selected_chart_replacements(
                page,
                ordered_slots,
                self.output_dir / "rfe.pdf",
                extract_workbook,
                None,
                adapter,
                [5.5],
            )
            by_kind = {replacement.kind: replacement for replacement in replacements}
            gain_title = _span_for_text(page, "ANTENNA GAIN")
            beamwidth_title = _span_for_text(page, "ANTENNA BEAMWIDTH")
            azimuth_title = _span_for_text(page, "AZIMUTH PATTERN")
            elevation_title = _span_for_text(page, "ELEVATION PATTERN")
            _planned_pages, planned_headings = _reflow_chart_replacements(
                page,
                replacements,
                cartesian_figure_width=18.0,
                cartesian_figure_height=8.0,
                polar_figure_size=12.0,
                return_headings=True,
            )
            planned_by_text = {heading.text: heading for heading in planned_headings[0]}

            self.assertAlmostEqual(by_kind["gain"].rect.width, by_kind["beamwidth"].rect.width, delta=0.01)
            self.assertGreater(by_kind["beamwidth"].rect.y0, beamwidth_title.y1)
            self.assertGreater(by_kind["azimuth_1"].rect.y0, azimuth_title.y1)
            self.assertGreater(by_kind["elevation_1"].rect.y0, elevation_title.y1)
            self.assertAlmostEqual(by_kind["azimuth_1"].rect.height, by_kind["elevation_1"].rect.height, delta=0.01)
            self.assertAlmostEqual(planned_by_text["ANTENNA GAIN"].bbox.x0, gain_title.x0, delta=0.1)
            self.assertAlmostEqual(planned_by_text["ANTENNA BEAMWIDTH"].bbox.x0, beamwidth_title.x0, delta=0.1)
            self.assertAlmostEqual(planned_by_text["AZIMUTH PATTERN"].bbox.x0, azimuth_title.x0, delta=0.1)

    def test_netqui_1pol_selected_radiation_stays_on_template_page_with_custom_figure_sizes(self) -> None:
        template = REPO_ROOT / "Templates" / "Datasheet - Netqui - 1Pol.pdf"
        project_dir = REPO_ROOT / "Projects" / "LPDA_0_3_3"
        extract_workbook = project_dir / "LPDA_0_3_3-extracted-data.xlsx"
        _require_paths(
            self,
            [
                template,
                extract_workbook,
                project_dir / "LPDA_0_3_3-gain.svg",
                project_dir / "LPDA_0_3_3-vswr.svg",
                project_dir / "LPDA_0_3_3-beamwidth-e-plane.svg",
                project_dir / "LPDA_0_3_3-beamwidth-h-plane.svg",
                project_dir / "polar_combined" / "e-h-plane" / "LPDA_0_3_3-polar-2.000-GHz-e-h-plane-combined.svg",
            ],
        )
        output = self.output_dir / "lpda-netqui-1pol-six-radiation.pdf"
        selected = [0.3, 0.5, 0.7, 1.0, 1.5, 2.0]

        build_datasheet_pdf(
            output,
            template,
            extract_workbook,
            radiation_frequencies_ghz=selected,
            cartesian_figure_width=18.0,
            cartesian_figure_height=8.0,
            polar_figure_size=12.0,
        )

        with fitz.open(output) as rendered_doc, fitz.open(template) as template_doc:
            adapter = resolve_template_adapter(template, template_doc)
            page = template_doc[1]
            ordered_slots = sorted(_collect_chart_slots(page), key=lambda slot: (slot.rect.y0, slot.rect.x0, slot.rect.y1, slot.rect.x1))
            replacements = _build_netqui_1pol_selected_chart_replacements(
                page,
                ordered_slots,
                output,
                extract_workbook,
                None,
                selected,
            )
            radiation = [replacement for replacement in replacements if replacement.kind.startswith("radiation_")]
            small_pages, _small_headings = _reflow_chart_replacements(
                page,
                replacements,
                cartesian_figure_width=18.0,
                cartesian_figure_height=8.0,
                polar_figure_size=7.0,
                return_headings=True,
            )
            large_pages, _large_headings = _reflow_chart_replacements(
                page,
                replacements,
                cartesian_figure_width=18.0,
                cartesian_figure_height=8.0,
                polar_figure_size=12.0,
                return_headings=True,
            )
            small_radiation = [replacement for replacement in small_pages[0] if replacement.kind.startswith("radiation_")]
            large_radiation = [replacement for replacement in large_pages[0] if replacement.kind.startswith("radiation_")]

            self.assertNotIn("CHARTS CONTINUED", "\n".join(page.get_text("text") for page in rendered_doc))
            self.assertEqual(rendered_doc.page_count, template_doc.page_count)
            self.assertEqual(len(radiation), 6)
            self.assertLess(radiation[2].rect.y0, radiation[3].rect.y0)
            self.assertGreater(large_radiation[0].rect.height, small_radiation[0].rect.height)
            self.assertIn("RADIATION PATTERNS", rendered_doc[1].get_text("text"))

    def test_netqui_real_template_keeps_frequency_value_visible_with_technical_data(self) -> None:
        template = REPO_ROOT / "Templates" / "Datasheet - Netqui.pdf"
        project_dir = REPO_ROOT / "Projects" / "LPDA_0_3_3"
        extract_workbook = project_dir / "LPDA_0_3_3-extracted-data.xlsx"
        technical_workbook = REPO_ROOT / "Input data" / "Technical Data.xlsx"
        _require_paths(
            self,
            [
                template,
                extract_workbook,
                technical_workbook,
                project_dir / "LPDA_0_3_3-gain.svg",
                project_dir / "LPDA_0_3_3-beamwidth-e-plane.svg",
                project_dir / "LPDA_0_3_3-beamwidth-h-plane.svg",
            ],
        )
        output = self.output_dir / "lpda-netqui.pdf"

        build_datasheet_pdf(output, template, extract_workbook, technical_workbook)

        with fitz.open(output) as doc:
            page = doc[0]
            text = page.get_text("text")
            frequency_label = _span_for_text(page, "Frequency Range")
            frequency_value = _span_for_text(page, "300 - 3000 MHz")

            self.assertIn("300 - 3000 MHz", text)
            self.assertIn("text_placeholder", text)
            self.assertGreater(frequency_value.x0, frequency_label.x1)
            self.assertAlmostEqual(frequency_value.y0, frequency_label.y0, delta=2.0)
            self.assertGreater(_non_white_ratio(page, frequency_value + (-1, -1, 1, 1), scale=2.0), 0.01)

    def test_netqui_1pol_real_template_keeps_table_lines_and_all_chart_slots(self) -> None:
        template = REPO_ROOT / "Templates" / "Datasheet - Netqui - 1Pol.pdf"
        project_dir = REPO_ROOT / "Projects" / "LPDA_0_3_3"
        extract_workbook = project_dir / "LPDA_0_3_3-extracted-data.xlsx"
        technical_workbook = REPO_ROOT / "Input data" / "Technical Data.xlsx"
        _require_paths(
            self,
            [
                template,
                extract_workbook,
                technical_workbook,
                project_dir / "LPDA_0_3_3-gain.svg",
                project_dir / "LPDA_0_3_3-vswr.svg",
                project_dir / "LPDA_0_3_3-beamwidth-e-plane.svg",
                project_dir / "LPDA_0_3_3-beamwidth-h-plane.svg",
                project_dir / "polar_combined",
            ],
        )
        output = self.output_dir / "lpda-netqui-1pol.pdf"

        build_datasheet_pdf(output, template, extract_workbook, technical_workbook)

        with fitz.open(output) as rendered_doc, fitz.open(template) as template_doc:
            adapter = resolve_template_adapter(template, template_doc)
            self.assertEqual(adapter.key, "netqui_1pol")
            replacements = _build_chart_replacements(
                template_doc[1],
                output,
                extract_workbook,
                adapter=adapter,
            )
            page_one = rendered_doc[0]
            page_two = rendered_doc[1]
            text = page_one.get_text("text")

            self.assertIn("300 - 3000 MHz", text)
            self.assertIn("text_placeholder", text)
            self.assertTrue(_has_left_table_line_below(page_one, "VSWR"))
            self.assertTrue(_has_left_table_line_below(page_one, "Nominal Impedance"))
            self.assertTrue(_has_left_table_line_below(page_one, "Beamwidth H plane."))
            table_segments = _horizontal_table_segments(page_one)
            self.assertEqual(len(table_segments), len(set(table_segments)))
            self.assertFalse([segment for segment in table_segments if segment[0] < 40.0 and segment[1] > 500.0])
            self.assertFalse([segment for segment in table_segments if segment[2] > 565.0])
            self.assertFalse([segment for segment in table_segments if segment[0] < 285.0 and segment[1] > 295.0])
            self.assertEqual(len(replacements), 7)
            shared_legend_scale = _shared_side_legend_scale(replacements)
            for replacement in replacements:
                self.assertGreater(_non_white_ratio(page_two, replacement.erase_rect or replacement.rect), 0.01)
                if replacement.kind in {"gain", "vswr"} or replacement.kind.startswith("radiation_"):
                    self.assertIsNotNone(replacement.legend_rect)
                    self.assertGreater(_non_white_ratio(page_two, _legend_target_rect(replacement, shared_legend_scale)), 0.01)

    def test_netqui_1pol_wraps_long_table_values_inside_value_column(self) -> None:
        template = REPO_ROOT / "Templates" / "Datasheet - Netqui - 1Pol.pdf"
        project_dir = REPO_ROOT / "Projects" / "TWB_DQ_47_26"
        extract_workbook = project_dir / "TWB_DQ_47_26-extracted-data.xlsx"
        technical_workbook = REPO_ROOT / "Input data" / "Technical Data - TWB-DQ-47-26.xlsx"
        _require_paths(
            self,
            [
                template,
                extract_workbook,
                technical_workbook,
                project_dir / "TWB_DQ_47_26-gain.svg",
                project_dir / "TWB_DQ_47_26-vswr.svg",
                project_dir / "TWB_DQ_47_26-beamwidth-e-plane.svg",
                project_dir / "TWB_DQ_47_26-beamwidth-h-plane.svg",
                project_dir / "polar_combined",
            ],
        )
        output = self.output_dir / "twb-dq-netqui-1pol.pdf"

        build_datasheet_pdf(output, template, extract_workbook, technical_workbook)

        with fitz.open(output) as doc:
            page = doc[0]
            text = page.get_text("text")
            self.assertIn("~4,2 kg (Total for the inseparable", text)
            self.assertIn("pair, including bracket and radome)", text)
            self.assertIn("2x N-type Female (RP-SMA for", text)
            self.assertIn("prototypes)", text)
            self.assertIn("Custom Quick-Release Slide Mount", text)
            self.assertIn("(for 80x40 mm profiles)", text)

            weight = _span_for_text(page, "Weight")
            first_weight_line = _span_for_text(page, "~4,2 kg (Total for the inseparable")
            wrapped_weight = _span_for_text(page, "pair, including bracket and radome)")
            self.assertGreater(first_weight_line.x0, weight.x1)
            self.assertGreater(wrapped_weight.x0, weight.x1)
            self.assertGreater(wrapped_weight.y0, first_weight_line.y0)
            self.assertLess(wrapped_weight.x1, 548.0)
            self.assertNotIn("Dimensions (H x W", text)

            electrical_font_size = _font_size_for_text(page, "4400 - 5000 MHz")
            mechanical_font_size = _font_size_for_text(page, "Aluminium, ABS")
            self.assertAlmostEqual(electrical_font_size, mechanical_font_size, places=2)


if __name__ == "__main__":
    unittest.main()
