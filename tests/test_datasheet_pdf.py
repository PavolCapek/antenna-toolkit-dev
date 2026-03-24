from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz
import pandas as pd

from datasheet_pdf import build_datasheet_pdf, build_replacements_from_workbook


REPO_ROOT = Path(__file__).resolve().parent.parent
MYRIAD_REGULAR = REPO_ROOT / "Fonts" / "Myriad Pro" / "MYRIADPRO-REGULAR.OTF"


FIELD_ROWS = [
    ("Frequency Range", "4900 - 7125 MHz"),
    ("Gain", "16.0 dBi"),
    ("Azimuth Beam Width -3 dB/-6dB", "H 42\N{DEGREE SIGN}, V 42\N{DEGREE SIGN} / H 63\N{DEGREE SIGN}, V 63\N{DEGREE SIGN}"),
    ("Elevation Beam Width -3 dB/-6dB", "H 16\N{DEGREE SIGN}, V 17\N{DEGREE SIGN} / H 26\N{DEGREE SIGN}, V 25\N{DEGREE SIGN}"),
    ("Beam Efficiency", "96 %*"),
    ("Front-to-Back Ratio", "27 dB"),
    ("VSWR", "<1.8"),
    ("Polarization", "Dual Linear H + V"),
    ("Impedance", "50 Ohm"),
]


class DatasheetPdfTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.template_pdf = self.root / "template.pdf"
        self.extract_workbook = self.root / "extract.xlsx"
        self.output_pdf = self.root / "output.pdf"
        self.gain_svg = self.root / "extract_gain.svg"
        self.beamwidth_svg = self.root / "extract_beamwidth.svg"
        self.polar_azimuth_dir = self.root / "polar_single" / "azimuth"
        self.polar_elevation_dir = self.root / "polar_single" / "elevation"
        self.azimuth_svg = self.polar_azimuth_dir / "extract_polar_azimuth_5.500_GHz.svg"
        self.elevation_svg = self.polar_elevation_dir / "extract_polar_elevation_5.500_GHz.svg"
        self.page2_gain_rect = fitz.Rect(24.0, 120.0, 324.0, 240.0)
        self.page2_beamwidth_rect = fitz.Rect(24.0, 280.0, 324.0, 400.0)
        self.page2_azimuth_rect = fitz.Rect(24.0, 460.0, 164.0, 600.0)
        self.page2_elevation_rect = fitz.Rect(204.0, 460.0, 344.0, 600.0)
        self._write_svg(self.gain_svg, "#00ff00", width=300, height=120)
        self._write_svg(self.beamwidth_svg, "#ffff00", width=300, height=120)
        self._write_svg(self.azimuth_svg, "#00ffff", width=140, height=140)
        self._write_svg(self.elevation_svg, "#ff00ff", width=140, height=140)
        self._write_template_pdf()
        self._write_extract_workbook()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_template_pdf(self, value_fontname: str = "helv", value_fontfile: str | None = None) -> None:
        with fitz.open() as doc:
            page = doc.new_page()
            y = 72.0
            for label, value in FIELD_ROWS:
                page.insert_text((38.0, y), label, fontsize=7, fontname="helv", color=(0.14, 0.12, 0.12))
                kwargs = {
                    "fontsize": 7,
                    "fontname": value_fontname,
                    "color": (0.25, 0.25, 0.25),
                }
                if value_fontfile:
                    kwargs["fontfile"] = value_fontfile
                page.insert_text((260.0, y), value, **kwargs)
                y += 18.0
            charts_page = doc.new_page()
            red_pix = self._svg_pixmap("#ff0000", 300, 120)
            blue_pix = self._svg_pixmap("#0000ff", 300, 120)
            cyan_pix = self._svg_pixmap("#00ffff", 140, 140)
            magenta_pix = self._svg_pixmap("#ff00ff", 140, 140)
            charts_page.insert_image(self.page2_gain_rect, pixmap=red_pix, keep_proportion=True)
            charts_page.insert_image(self.page2_beamwidth_rect, pixmap=blue_pix, keep_proportion=True)
            charts_page.insert_image(self.page2_azimuth_rect, pixmap=cyan_pix, keep_proportion=True)
            charts_page.insert_image(self.page2_elevation_rect, pixmap=magenta_pix, keep_proportion=True)
            charts_page.insert_text((360.0, 180.0), "Gain H (IEEE)", fontsize=7, fontname="helv")
            charts_page.insert_text((360.0, 196.0), "Gain V (IEEE)", fontsize=7, fontname="helv")
            charts_page.insert_text((360.0, 338.0), "Beamwidth Azimuth H -6 dB", fontsize=7, fontname="helv")
            charts_page.insert_text((360.0, 354.0), "Beamwidth Azimuth V -6 dB", fontsize=7, fontname="helv")
            charts_page.insert_text((360.0, 370.0), "Beamwidth Elevation H -6 dB", fontsize=7, fontname="helv")
            charts_page.insert_text((360.0, 386.0), "Beamwidth Elevation V -6 dB", fontsize=7, fontname="helv")
            charts_page.insert_text((28.0, 616.0), "H - Port Pattern Azimuth 5.5 GHz", fontsize=7, fontname="helv")
            charts_page.insert_text((28.0, 632.0), "V - Port Pattern Azimuth 5.5 GHz", fontsize=7, fontname="helv")
            charts_page.insert_text((208.0, 616.0), "H - Port Pattern Elevation 5.5 GHz", fontsize=7, fontname="helv")
            charts_page.insert_text((208.0, 632.0), "V - Port Pattern Elevation 5.5 GHz", fontsize=7, fontname="helv")
            doc.save(self.template_pdf)

    def _write_svg(self, path: Path, fill: str, width: int, height: int) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
                f'viewBox="0 0 {width} {height}">'
                f'<rect x="0" y="0" width="{width}" height="{height}" fill="{fill}"/>'
                "</svg>"
            ),
            encoding="utf-8",
        )

    def _svg_pixmap(self, fill: str, width: int, height: int) -> fitz.Pixmap:
        svg_path = self.root / f"tmp_{fill.strip('#')}_{width}x{height}.svg"
        self._write_svg(svg_path, fill, width, height)
        with fitz.open(svg_path) as doc:
            return doc[0].get_pixmap(alpha=False)

    def _pixel_rgb(self, page: fitz.Page, point: fitz.Point) -> tuple[int, int, int]:
        pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
        width = pix.width
        height = pix.height
        x = max(0, min(width - 1, int(point.x)))
        y = max(0, min(height - 1, int(point.y)))
        offset = (y * width + x) * pix.n
        samples = pix.samples
        return (samples[offset], samples[offset + 1], samples[offset + 2])

    def _write_extract_workbook(self) -> None:
        ffs_summary = pd.DataFrame(
            [
                {
                    "source_file": "sample_h.ffs",
                    "polarization": "Horizontal",
                    "points_used": 24,
                    "freq_min_GHz": 4.9,
                    "freq_max_GHz": 7.125,
                    "max_gain_dBi_in_range": 19.4676,
                    "avg_gain_dBi_in_range": 18.4587,
                    "avg_azimuth_bw_3dB_deg": 20.3992,
                    "avg_azimuth_bw_6dB_deg": 30.2033,
                    "avg_elevation_bw_3dB_deg": 20.2844,
                    "avg_elevation_bw_6dB_deg": 28.9986,
                    "avg_beam_efficiency_percent": 98.3847,
                    "avg_front_to_back_dB": 28.2308,
                },
                {
                    "source_file": "sample_v.ffs",
                    "polarization": "Vertical",
                    "points_used": 24,
                    "freq_min_GHz": 4.9,
                    "freq_max_GHz": 7.125,
                    "max_gain_dBi_in_range": 19.4470,
                    "avg_gain_dBi_in_range": 18.4582,
                    "avg_azimuth_bw_3dB_deg": 20.2901,
                    "avg_azimuth_bw_6dB_deg": 29.0035,
                    "avg_elevation_bw_3dB_deg": 20.3714,
                    "avg_elevation_bw_6dB_deg": 30.1488,
                    "avg_beam_efficiency_percent": 98.4032,
                    "avg_front_to_back_dB": 28.2327,
                },
            ]
        )
        touchstone_summary = pd.DataFrame(
            [
                {
                    "touchstone_file": "sample.s2p",
                    "port": "Port 1",
                    "points_used": 576,
                    "freq_min_GHz": 4.9,
                    "freq_max_GHz": 7.125,
                    "max_vswr_in_range": 1.7050,
                    "avg_vswr_in_range": 1.2393,
                    "avg_impedance_real_ohm": 43.9696,
                    "avg_impedance_imag_ohm": -0.4488,
                    "avg_impedance_magnitude_ohm": 44.4315,
                    "reference_impedance_ohm": 50,
                },
                {
                    "touchstone_file": "sample.s2p",
                    "port": "Port 2",
                    "points_used": 576,
                    "freq_min_GHz": 4.9,
                    "freq_max_GHz": 7.125,
                    "max_vswr_in_range": 1.9161,
                    "avg_vswr_in_range": 1.2734,
                    "avg_impedance_real_ohm": 45.4613,
                    "avg_impedance_imag_ohm": -1.2152,
                    "avg_impedance_magnitude_ohm": 46.2532,
                    "reference_impedance_ohm": 50,
                },
            ]
        )
        with pd.ExcelWriter(self.extract_workbook) as writer:
            ffs_summary.to_excel(writer, sheet_name="ffs_summary", index=False)
            touchstone_summary.to_excel(writer, sheet_name="touchstone_summary", index=False)

    def test_build_replacements_from_workbook(self) -> None:
        replacements = build_replacements_from_workbook(self.extract_workbook)

        self.assertEqual(replacements["Frequency Range"], "4900 - 7125 MHz")
        self.assertEqual(replacements["Gain"], "19.5 dBi")
        self.assertEqual(replacements["Azimuth Beam Width -3 dB/-6dB"], "H 20°, V 20° / H 30°, V 29°")
        self.assertEqual(replacements["Elevation Beam Width -3 dB/-6dB"], "H 20°, V 20° / H 29°, V 30°")
        self.assertEqual(replacements["Beam Efficiency"], "98 %*")
        self.assertEqual(replacements["Front-to-Back Ratio"], "28 dB")
        self.assertEqual(replacements["VSWR"], "<1.9")
        self.assertEqual(replacements["Polarization"], "Dual Linear H + V")
        self.assertEqual(replacements["Impedance"], "50 Ohm")

    def test_build_datasheet_pdf_replaces_template_values(self) -> None:
        build_datasheet_pdf(
            output=self.output_pdf,
            template=self.template_pdf,
            extract_workbook=self.extract_workbook,
        )

        self.assertTrue(self.output_pdf.exists())
        with fitz.open(self.output_pdf) as doc:
            text = doc[0].get_text()

        self.assertIn("4900 - 7125 MHz", text)
        self.assertIn("19.5 dBi", text)
        self.assertIn("H 20°, V 20° / H 30°, V 29°", text)
        self.assertIn("H 20°, V 20° / H 29°, V 30°", text)
        self.assertIn("98 %*", text)
        self.assertIn("28 dB", text)
        self.assertIn("<1.9", text)
        self.assertNotIn("16.0 dBi", text)

    def test_build_datasheet_pdf_replaces_gain_and_beamwidth_images(self) -> None:
        build_datasheet_pdf(
            output=self.output_pdf,
            template=self.template_pdf,
            extract_workbook=self.extract_workbook,
        )

        with fitz.open(self.output_pdf) as doc:
            page = doc[1]
            gain_rgb = self._pixel_rgb(page, self.page2_gain_rect.tl + fitz.Point(self.page2_gain_rect.width / 2.0, self.page2_gain_rect.height / 2.0))
            beamwidth_rgb = self._pixel_rgb(page, self.page2_beamwidth_rect.tl + fitz.Point(self.page2_beamwidth_rect.width / 2.0, self.page2_beamwidth_rect.height / 2.0))
            azimuth_rgb = self._pixel_rgb(page, self.page2_azimuth_rect.tl + fitz.Point(self.page2_azimuth_rect.width / 2.0, self.page2_azimuth_rect.height / 2.0))
            elevation_rgb = self._pixel_rgb(page, self.page2_elevation_rect.tl + fitz.Point(self.page2_elevation_rect.width / 2.0, self.page2_elevation_rect.height / 2.0))
            page2_text = page.get_text()
            page2_images = page.get_images(full=True)

        self.assertGreater(gain_rgb[1], 200)
        self.assertLess(gain_rgb[0], 80)
        self.assertGreater(beamwidth_rgb[0], 200)
        self.assertGreater(beamwidth_rgb[1], 200)
        self.assertGreater(azimuth_rgb[1], 200)
        self.assertGreater(azimuth_rgb[2], 200)
        self.assertGreater(elevation_rgb[0], 200)
        self.assertGreater(elevation_rgb[2], 200)
        self.assertNotIn("Gain H (IEEE)", page2_text)
        self.assertNotIn("Beamwidth Azimuth H -6 dB", page2_text)
        self.assertNotIn("Port Pattern Azimuth 5.5 GHz", page2_text)
        self.assertEqual(page2_images, [])

    def test_build_replacements_from_workbook_derives_polarization_from_source_file(self) -> None:
        ffs_summary = pd.DataFrame(
            [
                {
                    "source_file": "sample_h.ffs",
                    "polarization": "Unknown",
                    "points_used": 24,
                    "freq_min_GHz": 4.9,
                    "freq_max_GHz": 7.125,
                    "max_gain_dBi_in_range": 19.4676,
                    "avg_gain_dBi_in_range": 18.4587,
                    "avg_azimuth_bw_3dB_deg": 20.3992,
                    "avg_azimuth_bw_6dB_deg": 30.2033,
                    "avg_elevation_bw_3dB_deg": 20.2844,
                    "avg_elevation_bw_6dB_deg": 28.9986,
                    "avg_beam_efficiency_percent": 98.3847,
                    "avg_front_to_back_dB": 28.2308,
                },
                {
                    "source_file": "sample_v.ffs",
                    "polarization": "Also Wrong",
                    "points_used": 24,
                    "freq_min_GHz": 4.9,
                    "freq_max_GHz": 7.125,
                    "max_gain_dBi_in_range": 19.4470,
                    "avg_gain_dBi_in_range": 18.4582,
                    "avg_azimuth_bw_3dB_deg": 20.2901,
                    "avg_azimuth_bw_6dB_deg": 29.0035,
                    "avg_elevation_bw_3dB_deg": 20.3714,
                    "avg_elevation_bw_6dB_deg": 30.1488,
                    "avg_beam_efficiency_percent": 98.4032,
                    "avg_front_to_back_dB": 28.2327,
                },
            ]
        )
        touchstone_summary = pd.DataFrame(
            [
                {
                    "touchstone_file": "sample.s2p",
                    "port": "Port 1",
                    "points_used": 576,
                    "freq_min_GHz": 4.9,
                    "freq_max_GHz": 7.125,
                    "max_vswr_in_range": 1.9161,
                    "avg_vswr_in_range": 1.2734,
                    "avg_impedance_real_ohm": 45.4613,
                    "avg_impedance_imag_ohm": -1.2152,
                    "avg_impedance_magnitude_ohm": 46.2532,
                    "reference_impedance_ohm": 50,
                }
            ]
        )
        with pd.ExcelWriter(self.extract_workbook) as writer:
            ffs_summary.to_excel(writer, sheet_name="ffs_summary", index=False)
            touchstone_summary.to_excel(writer, sheet_name="touchstone_summary", index=False)

        replacements = build_replacements_from_workbook(self.extract_workbook)

        self.assertEqual(replacements["Polarization"], "Dual Linear H + V")
        self.assertEqual(replacements["Gain"], "19.5 dBi")

    def test_build_datasheet_pdf_uses_myriad_font_for_myriad_template(self) -> None:
        self.assertTrue(MYRIAD_REGULAR.exists(), f"Missing test font: {MYRIAD_REGULAR}")
        self._write_template_pdf(value_fontname="MyriadPro-Regular", value_fontfile=str(MYRIAD_REGULAR))

        build_datasheet_pdf(
            output=self.output_pdf,
            template=self.template_pdf,
            extract_workbook=self.extract_workbook,
        )

        matched = {}
        with fitz.open(self.output_pdf) as doc:
            page = doc[0]
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = str(span.get("text", "")).strip()
                        if text in {
                            "19.5 dBi",
                            "98 %*",
                            "28 dB",
                            "<1.9",
                            "50 Ohm",
                            "H 20°, V 20° / H 30°, V 29°",
                            "H 20°, V 20° / H 29°, V 30°",
                        }:
                            matched[text] = str(span.get("font", ""))

        self.assertEqual(matched["19.5 dBi"], "MyriadPro-Regular")
        self.assertEqual(matched["98 %*"], "MyriadPro-Regular")
        self.assertEqual(matched["28 dB"], "MyriadPro-Regular")
        self.assertEqual(matched["<1.9"], "MyriadPro-Regular")
        self.assertEqual(matched["50 Ohm"], "MyriadPro-Regular")
        self.assertEqual(matched["H 20°, V 20° / H 30°, V 29°"], "MyriadPro-Regular")
        self.assertEqual(matched["H 20°, V 20° / H 29°, V 30°"], "MyriadPro-Regular")


if __name__ == "__main__":
    unittest.main()
