from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz
import pandas as pd

from datasheet_pdf import build_datasheet_pdf, build_replacements_from_workbook


FIELD_ROWS = [
    ("Frequency Range", "4900 - 7125 MHz"),
    ("Gain", "16 dBi"),
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
        self._write_template_pdf()
        self._write_extract_workbook()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_template_pdf(self) -> None:
        with fitz.open() as doc:
            page = doc.new_page()
            y = 72.0
            for label, value in FIELD_ROWS:
                page.insert_text((38.0, y), label, fontsize=7, fontname="helv", color=(0.14, 0.12, 0.12))
                page.insert_text((260.0, y), value, fontsize=7, fontname="helv", color=(0.25, 0.25, 0.25))
                y += 18.0
            doc.save(self.template_pdf)

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
        self.assertEqual(replacements["Gain"], "19 dBi")
        self.assertEqual(replacements["Azimuth Beam Width -3 dB/-6dB"], "H 20°, V 20° / H 30°, V 29°")
        self.assertEqual(replacements["Elevation Beam Width -3 dB/-6dB"], "H 20°, V 20° / H 29°, V 30°")
        self.assertEqual(replacements["Beam Efficiency"], "98 %*")
        self.assertEqual(replacements["Front-to-Back Ratio"], "28 dB")
        self.assertEqual(replacements["VSWR"], "<1.92")
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
        self.assertIn("19 dBi", text)
        self.assertIn("H 20°, V 20° / H 30°, V 29°", text)
        self.assertIn("H 20°, V 20° / H 29°, V 30°", text)
        self.assertIn("98 %*", text)
        self.assertIn("28 dB", text)
        self.assertIn("<1.92", text)
        self.assertNotIn("16 dBi", text)


if __name__ == "__main__":
    unittest.main()
