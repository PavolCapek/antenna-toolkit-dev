from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz

from datasheet_pdf import _build_chart_replacements, _extract_page_spans, build_datasheet_pdf
from datasheet_templates import resolve_template_adapter


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


if __name__ == "__main__":
    unittest.main()
