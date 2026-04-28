from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import fitz
import pandas as pd

from datasheet.artifacts import build_asset_record, load_artifact_manifest, update_artifact_manifest
from datasheet_pdf import (
    ChartReplacement,
    _build_chart_replacements,
    _find_combined_polar_triplet_assets,
    _legend_target_rect,
    _layout_split_chart_rects,
    _find_beamwidth_plane_asset,
    _normalize_plot_widths,
    _redraw_template_table_separators,
    _separate_plot_and_legend_rects,
    _shared_side_legend_scale,
    _svg_to_pdf_bytes,
    _extract_page_spans,
    _replace_exact_span_text,
    build_datasheet_pdf,
    build_replacements_from_workbook,
    load_technical_data_workbook,
)
from datasheet.templates import NETQUI_1POL_TEMPLATE_ADAPTER, NETQUI_TEMPLATE_ADAPTER, RFE_TEMPLATE_ADAPTER, resolve_template_adapter


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
        self.technical_workbook = self.root / "technical.xlsx"
        self.output_pdf = self.root / "output.pdf"
        self.gain_svg = self.root / "extract-gain.svg"
        self.gain_legend_svg = self.root / "extract-gain-legend.svg"
        self.vswr_svg = self.root / "extract-vswr.svg"
        self.vswr_legend_svg = self.root / "extract-vswr-legend.svg"
        self.beamwidth_svg = self.root / "extract-beamwidth.svg"
        self.beamwidth_legend_svg = self.root / "extract-beamwidth-legend.svg"
        self.beamwidth_e_plane_h_svg = self.root / "extract-beamwidth-e-plane-h.svg"
        self.beamwidth_e_plane_h_legend_svg = self.root / "extract-beamwidth-e-plane-h-legend.svg"
        self.beamwidth_h_plane_h_svg = self.root / "extract-beamwidth-h-plane-h.svg"
        self.beamwidth_h_plane_h_legend_svg = self.root / "extract-beamwidth-h-plane-h-legend.svg"
        self.manifest_gain_svg = self.root / "manifest-gain.svg"
        self.manifest_gain_legend_svg = self.root / "manifest-gain-legend.svg"
        self.manifest_beamwidth_svg = self.root / "manifest-beamwidth.svg"
        self.manifest_beamwidth_legend_svg = self.root / "manifest-beamwidth-legend.svg"
        self.manifest_azimuth_svg = self.root / "manifest-azimuth.svg"
        self.manifest_azimuth_legend_svg = self.root / "manifest-azimuth-legend.svg"
        self.manifest_elevation_svg = self.root / "manifest-elevation.svg"
        self.manifest_elevation_legend_svg = self.root / "manifest-elevation-legend.svg"
        self.polar_azimuth_dir = self.root / "polar_single" / "azimuth"
        self.polar_elevation_dir = self.root / "polar_single" / "elevation"
        self.azimuth_svg = self.polar_azimuth_dir / "extract-polar-azimuth-5.500-GHz.svg"
        self.azimuth_legend_svg = self.polar_azimuth_dir / "extract-polar-azimuth-5.500-GHz-legend.svg"
        self.elevation_svg = self.polar_elevation_dir / "extract-polar-elevation-5.500-GHz.svg"
        self.elevation_legend_svg = self.polar_elevation_dir / "extract-polar-elevation-5.500-GHz-legend.svg"
        self.polar_combined_dir = self.root / "polar_combined"
        self.combined_low_svg = self.polar_combined_dir / "extract-polar-4.900-GHz-combined.svg"
        self.combined_low_legend_svg = self.polar_combined_dir / "extract-polar-4.900-GHz-combined-legend.svg"
        self.combined_mid_svg = self.polar_combined_dir / "extract-polar-6.000-GHz-combined.svg"
        self.combined_mid_legend_svg = self.polar_combined_dir / "extract-polar-6.000-GHz-combined-legend.svg"
        self.combined_high_svg = self.polar_combined_dir / "extract-polar-7.125-GHz-combined.svg"
        self.combined_high_legend_svg = self.polar_combined_dir / "extract-polar-7.125-GHz-combined-legend.svg"
        self.polar_combined_eh_dir = self.polar_combined_dir / "e-h-plane"
        self.combined_eh_low_svg = self.polar_combined_eh_dir / "extract-polar-4.900-GHz-e-h-plane-combined.svg"
        self.combined_eh_low_legend_svg = self.polar_combined_eh_dir / "extract-polar-4.900-GHz-e-h-plane-combined-legend.svg"
        self.combined_eh_mid_svg = self.polar_combined_eh_dir / "extract-polar-6.000-GHz-e-h-plane-combined.svg"
        self.combined_eh_mid_legend_svg = self.polar_combined_eh_dir / "extract-polar-6.000-GHz-e-h-plane-combined-legend.svg"
        self.combined_eh_high_svg = self.polar_combined_eh_dir / "extract-polar-7.125-GHz-e-h-plane-combined.svg"
        self.combined_eh_high_legend_svg = self.polar_combined_eh_dir / "extract-polar-7.125-GHz-e-h-plane-combined-legend.svg"
        self.page2_gain_rect = fitz.Rect(24.0, 120.0, 324.0, 240.0)
        self.page2_beamwidth_rect = fitz.Rect(24.0, 280.0, 324.0, 400.0)
        self.page2_azimuth_rect = fitz.Rect(24.0, 460.0, 164.0, 600.0)
        self.page2_elevation_rect = fitz.Rect(204.0, 460.0, 344.0, 600.0)
        self._write_svg(self.gain_svg, "#00ff00", width=300, height=120)
        self._write_svg(self.gain_legend_svg, "#ffffff", width=140, height=70)
        self._write_svg(self.vswr_svg, "#ff8800", width=300, height=120)
        self._write_svg(self.vswr_legend_svg, "#ffffff", width=90, height=70)
        self._write_svg(self.beamwidth_svg, "#ffff00", width=300, height=120)
        self._write_svg(self.beamwidth_legend_svg, "#ffffff", width=180, height=110)
        self._write_svg(self.beamwidth_e_plane_h_svg, "#990000", width=300, height=120)
        self._write_svg(self.beamwidth_e_plane_h_legend_svg, "#ffffff", width=90, height=130)
        self._write_svg(self.beamwidth_h_plane_h_svg, "#111111", width=300, height=120)
        self._write_svg(self.beamwidth_h_plane_h_legend_svg, "#ffffff", width=90, height=130)
        self._write_svg(self.manifest_gain_svg, "#228833", width=300, height=120)
        self._write_svg(self.manifest_gain_legend_svg, "#ffffff", width=140, height=70)
        self._write_svg(self.manifest_beamwidth_svg, "#ddcc33", width=300, height=120)
        self._write_svg(self.manifest_beamwidth_legend_svg, "#ffffff", width=180, height=110)
        self._write_svg(self.manifest_azimuth_svg, "#0099cc", width=140, height=140)
        self._write_svg(self.manifest_azimuth_legend_svg, "#ffffff", width=150, height=70)
        self._write_svg(self.manifest_elevation_svg, "#cc33aa", width=140, height=140)
        self._write_svg(self.manifest_elevation_legend_svg, "#ffffff", width=150, height=70)
        self._write_svg(self.azimuth_svg, "#00ffff", width=140, height=140)
        self._write_svg(self.azimuth_legend_svg, "#ffffff", width=150, height=70)
        self._write_svg(self.elevation_svg, "#ff00ff", width=140, height=140)
        self._write_svg(self.elevation_legend_svg, "#ffffff", width=150, height=70)
        self._write_svg(self.combined_low_svg, "#11aaee", width=140, height=140)
        self._write_svg(self.combined_low_legend_svg, "#ffffff", width=150, height=70)
        self._write_svg(self.combined_mid_svg, "#22bb88", width=140, height=140)
        self._write_svg(self.combined_mid_legend_svg, "#ffffff", width=150, height=70)
        self._write_svg(self.combined_high_svg, "#aa44dd", width=140, height=140)
        self._write_svg(self.combined_high_legend_svg, "#ffffff", width=150, height=70)
        self._write_svg(self.combined_eh_low_svg, "#1188ee", width=140, height=140)
        self._write_svg(self.combined_eh_low_legend_svg, "#ffffff", width=150, height=70)
        self._write_svg(self.combined_eh_mid_svg, "#228866", width=140, height=140)
        self._write_svg(self.combined_eh_mid_legend_svg, "#ffffff", width=150, height=70)
        self._write_svg(self.combined_eh_high_svg, "#8844dd", width=140, height=140)
        self._write_svg(self.combined_eh_high_legend_svg, "#ffffff", width=150, height=70)
        self._write_template_pdf()
        self._write_extract_workbook()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_template_pdf(
        self,
        value_fontname: str = "helv",
        value_fontfile: str | None = None,
        reverse_polar_slot_order: bool = False,
        add_legend_handles: bool = False,
        add_technical_data: bool = False,
        metadata: dict[str, str] | None = None,
        xml_metadata: str | None = None,
        field_rows: list[tuple[str, str]] | None = None,
    ) -> None:
        with fitz.open() as doc:
            page = doc.new_page()
            if add_technical_data:
                page.insert_text((34.0, 48.0), "Product Datasheet", fontsize=12, fontname="helv", color=(0.14, 0.12, 0.12))
                page.insert_text((34.0, 66.0), "Product ID:", fontsize=8, fontname="helv", color=(0.14, 0.12, 0.12))
                page.insert_text((80.0, 66.0), "PRODUCT_ID_PLACEHOLDER", fontsize=7, fontname="helv", color=(0.14, 0.12, 0.12))
                page.insert_text((34.0, 96.0), "ANTENNA NAME", fontsize=18, fontname="helv", color=(0.14, 0.12, 0.12))
                page.insert_text((36.0, 158.0), "TECHNICAL DATA", fontsize=8, fontname="helv", color=(0.14, 0.12, 0.12))
                tech_rows = [
                    ("Radio Connection", "Template connector"),
                    ("Antenna Type", "Template type"),
                    ("Materials", "Template material"),
                    ("Enviromental", "Template IP"),
                ]
                tech_y = 174.0
                for label, value in tech_rows:
                    page.insert_text((38.0, tech_y), label, fontsize=7, fontname="helv", color=(0.14, 0.12, 0.12))
                    page.insert_text((140.0, tech_y), value, fontsize=7, fontname="helv", color=(0.25, 0.25, 0.25))
                    page.draw_line((36.638, tech_y + 6.0), (299.0, tech_y + 6.0), color=(0.14, 0.12, 0.12), width=0.25)
                    tech_y += 12.0
                page.insert_text((36.0, 300.0), "PERFORMANCE", fontsize=8, fontname="helv", color=(0.14, 0.12, 0.12))
                y = 316.0
            else:
                y = 72.0
            for label, value in field_rows or FIELD_ROWS:
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
            if add_technical_data:
                page.insert_text((36.0, 780.0), "1/2 ANTENNA NAME Rev 09-2025", fontsize=7, fontname="helv", color=(0.14, 0.12, 0.12))
            charts_page = doc.new_page()
            red_pix = self._svg_pixmap("#ff0000", 300, 120)
            blue_pix = self._svg_pixmap("#0000ff", 300, 120)
            cyan_pix = self._svg_pixmap("#00ffff", 140, 140)
            magenta_pix = self._svg_pixmap("#ff00ff", 140, 140)
            charts_page.insert_image(self.page2_gain_rect, pixmap=red_pix, keep_proportion=True)
            charts_page.insert_image(self.page2_beamwidth_rect, pixmap=blue_pix, keep_proportion=True)
            polar_slots = [
                (self.page2_azimuth_rect, cyan_pix),
                (fitz.Rect(self.page2_elevation_rect), magenta_pix),
            ]
            if reverse_polar_slot_order:
                adjusted_elevation_rect = fitz.Rect(self.page2_elevation_rect)
                adjusted_elevation_rect.y0 -= 1.0
                adjusted_elevation_rect.y1 -= 1.0
                polar_slots = [
                    (adjusted_elevation_rect, magenta_pix),
                    (self.page2_azimuth_rect, cyan_pix),
                ]
            for rect, pixmap in polar_slots:
                charts_page.insert_image(rect, pixmap=pixmap, keep_proportion=True)
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
            if add_technical_data:
                charts_page.insert_text((36.0, 780.0), "2/2 ANTENNA NAME Rev 09-2025", fontsize=7, fontname="helv", color=(0.14, 0.12, 0.12))
            if add_legend_handles:
                charts_page.draw_line((337.0, 172.0), (353.0, 172.0), color=(0.17, 0.71, 0.96), width=2.0)
                charts_page.draw_line((337.0, 330.0), (353.0, 330.0), color=(0.17, 0.71, 0.96), width=2.0)
                charts_page.draw_line((95.0, 608.0), (111.0, 608.0), color=(0.17, 0.71, 0.96), width=2.0)
            if metadata is not None:
                doc.set_metadata(metadata)
            if xml_metadata is not None and hasattr(doc, "set_xml_metadata"):
                doc.set_xml_metadata(xml_metadata)
            doc.save(self.template_pdf)

    def _write_netqui_chart_template_pdf(self) -> tuple[fitz.Rect, fitz.Rect, fitz.Rect, fitz.Rect]:
        with fitz.open() as doc:
            doc.new_page()
            page = doc.new_page(width=596.0, height=842.0)
            red_pix = self._svg_pixmap("#ff0000", 300, 120)
            gray_pix = self._svg_pixmap("#808080", 300, 120)
            black_pix = self._svg_pixmap("#000000", 300, 120)
            polar_pix = self._svg_pixmap("#00ffff", 140, 140)
            gain_rect = fitz.Rect(42.75, 51.50, 263.25, 218.00)
            vswr_rect = fitz.Rect(266.25, 50.75, 486.75, 218.00)
            e_plane_rect = fitz.Rect(42.75, 278.94, 293.25, 449.19)
            h_plane_rect = fitz.Rect(296.25, 278.94, 549.00, 449.19)
            polar_rects = [
                fitz.Rect(42.75, 498.15, 209.25, 648.90),
                fitz.Rect(212.25, 496.65, 378.00, 648.90),
                fitz.Rect(381.00, 495.90, 543.75, 648.90),
            ]
            for rect, pixmap in [
                (gain_rect, red_pix),
                (vswr_rect, gray_pix),
                (e_plane_rect, black_pix),
                (h_plane_rect, black_pix),
                *[(rect, polar_pix) for rect in polar_rects],
            ]:
                page.insert_image(rect, pixmap=pixmap, keep_proportion=True)
            page.insert_text((36.0, 32.0), "ANTENNA GAIN", fontsize=8, fontname="helv")
            page.insert_text((360.0, 32.0), "VSWR", fontsize=8, fontname="helv")
            page.insert_text((36.0, 260.0), "ANTENNA BEAMWIDTH", fontsize=8, fontname="helv")
            page.insert_text((36.0, 480.0), "RADIATION PATTERNS", fontsize=8, fontname="helv")
            doc.save(self.template_pdf)
        return gain_rect, vswr_rect, e_plane_rect, h_plane_rect

    def _write_netqui_technical_template_pdf(self) -> None:
        with fitz.open() as doc:
            page = doc.new_page(width=596.0, height=842.0)
            page.insert_text((42.8, 45.8), "RUGGED LOG-PERIODIC ANTENNA", fontsize=18.0, fontname="helv", color=(0.14, 0.12, 0.12))
            page.insert_text((42.8, 89.7), "SKU: RLP-F-33-A", fontsize=12.0, fontname="helv", color=(0.14, 0.12, 0.12))
            page.insert_text((41.2, 414.5), "ELECTRICAL DATA", fontsize=10.0, fontname="helv", color=(0.14, 0.12, 0.12))
            page.insert_text((302.2, 414.5), "MECHANICAL DATA", fontsize=10.0, fontname="helv", color=(0.14, 0.12, 0.12))
            left_rows = [
                ("Antenna Type", "Log-periodic Antenna", 439.7),
                ("Frequency Range", "300 - 3000 MHZ", 453.3),
                ("Polarization", "Single linear, Vertical", 467.0),
                ("Gain", "9.5 dBi", 480.6),
                ("Beamwidth E plane.", "55/75/95 deg (-3/-6/-10 dB)", 494.2),
                ("Beamwidth H plane.", "80/100/130 deg (-3/-6/-10 dB)", 507.8),
                ("VSWR", "<1.5", 521.4),
                ("Nominal Impedance", "50 ohm", 535.0),
                ("Max Input Power", "150W", 548.7),
            ]
            for label, value, y in left_rows:
                page.insert_text((41.2, y), label, fontsize=10.0, fontname="helv", color=(0.14, 0.12, 0.12))
                page.insert_text((148.5, y), value, fontsize=10.0, fontname="helv", color=(0.25, 0.25, 0.25))
            right_rows = [
                ("Dimensions (LxWxD)", "1142 x 200 x 618 mm", 439.7),
                ("Weight", "6.7 kg", 453.3),
                ("RF Connection", "N female", 467.0),
                ("Pole Mounting Diameter", "60 - 120 mm", 480.6),
                ("Material", "Aluminium, ABS, ABS+PMMA", 494.2),
                ("Wind Survival", "180 km/h", 521.4),
            ]
            for label, value, y in right_rows:
                page.insert_text((302.2, y), label, fontsize=10.0, fontname="helv", color=(0.14, 0.12, 0.12))
                page.insert_text((433.5, y), value, fontsize=10.0, fontname="helv", color=(0.25, 0.25, 0.25))
            page.insert_text((35.0, 585.0), "DIMMENSIONS", fontsize=10.0, fontname="helv", color=(0.14, 0.12, 0.12))

            charts_page = doc.new_page(width=596.0, height=842.0)
            red_pix = self._svg_pixmap("#ff0000", 300, 120)
            gray_pix = self._svg_pixmap("#808080", 300, 120)
            black_pix = self._svg_pixmap("#000000", 300, 120)
            polar_pix = self._svg_pixmap("#00ffff", 140, 140)
            gain_rect = fitz.Rect(42.75, 51.50, 263.25, 218.00)
            vswr_rect = fitz.Rect(266.25, 50.75, 486.75, 218.00)
            e_plane_rect = fitz.Rect(42.75, 278.94, 293.25, 449.19)
            h_plane_rect = fitz.Rect(296.25, 278.94, 549.00, 449.19)
            polar_rects = [
                fitz.Rect(42.75, 498.15, 209.25, 648.90),
                fitz.Rect(212.25, 496.65, 378.00, 648.90),
                fitz.Rect(381.00, 495.90, 543.75, 648.90),
            ]
            for rect, pixmap in [
                (gain_rect, red_pix),
                (vswr_rect, gray_pix),
                (e_plane_rect, black_pix),
                (h_plane_rect, black_pix),
                *[(rect, polar_pix) for rect in polar_rects],
            ]:
                charts_page.insert_image(rect, pixmap=pixmap, keep_proportion=True)
            charts_page.insert_text((36.0, 32.0), "ANTENNA GAIN", fontsize=8, fontname="helv")
            charts_page.insert_text((360.0, 32.0), "VSWR", fontsize=8, fontname="helv")
            charts_page.insert_text((36.0, 260.0), "ANTENNA BEAMWIDTH", fontsize=8, fontname="helv")
            charts_page.insert_text((36.0, 480.0), "RADIATION PATTERNS", fontsize=8, fontname="helv")
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

    def _count_colored_runs(
        self,
        pix: fitz.Pixmap,
        *,
        y: int,
        rgb_min: tuple[int, int, int],
        rgb_max: tuple[int, int, int],
    ) -> int:
        y = max(0, min(pix.height - 1, y))
        runs = 0
        in_run = False
        for x in range(pix.width):
            offset = (y * pix.width + x) * pix.n
            red = pix.samples[offset]
            green = pix.samples[offset + 1]
            blue = pix.samples[offset + 2]
            is_match = (
                rgb_min[0] <= red <= rgb_max[0]
                and rgb_min[1] <= green <= rgb_max[1]
                and rgb_min[2] <= blue <= rgb_max[2]
            )
            if is_match and not in_run:
                runs += 1
                in_run = True
            elif not is_match:
                in_run = False
        return runs

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

    def _write_technical_workbook(self, rows: list[tuple[object, object]]) -> None:
        pd.DataFrame(rows).to_excel(self.technical_workbook, sheet_name="Sheet1", index=False, header=False)

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

    def test_build_replacements_from_workbook_handles_single_far_field_summary(self) -> None:
        ffs_summary = pd.DataFrame(
            [
                {
                    "source_file": "TWB-DQ-47-26.ffs",
                    "polarization": "TWB-DQ-47-26",
                    "points_used": 7,
                    "freq_min_GHz": 4.4,
                    "freq_max_GHz": 5.0,
                    "max_gain_dBi_in_range": 26.1959,
                    "avg_gain_dBi_in_range": 25.7641,
                    "avg_azimuth_bw_3dB_deg": 8.1437,
                    "avg_azimuth_bw_6dB_deg": 11.3822,
                    "avg_elevation_bw_3dB_deg": 7.3283,
                    "avg_elevation_bw_6dB_deg": 10.0008,
                    "avg_beam_efficiency_percent": 60.7781,
                    "avg_front_to_back_dB": 32.3559,
                }
            ]
        )
        touchstone_summary = pd.DataFrame(
            [
                {
                    "touchstone_file": "TWB-DQ-47-26.s1p",
                    "port": "Port 1",
                    "points_used": 201,
                    "freq_min_GHz": 4.4,
                    "freq_max_GHz": 5.0,
                    "max_vswr_in_range": 3.1332,
                    "avg_vswr_in_range": 1.7272,
                    "reference_impedance_ohm": 50,
                }
            ]
        )
        with pd.ExcelWriter(self.extract_workbook) as writer:
            ffs_summary.to_excel(writer, sheet_name="ffs_summary", index=False)
            touchstone_summary.to_excel(writer, sheet_name="touchstone_summary", index=False)

        replacements = build_replacements_from_workbook(self.extract_workbook)

        self.assertEqual(replacements["Azimuth Beam Width -3 dB/-6dB"], "8\N{DEGREE SIGN} / 11\N{DEGREE SIGN}")
        self.assertEqual(replacements["Elevation Beam Width -3 dB/-6dB"], "7\N{DEGREE SIGN} / 10\N{DEGREE SIGN}")
        self.assertEqual(replacements["Polarization"], "Single Polarization")

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

    def test_extract_page_spans_uses_text_only_extraction(self) -> None:
        class FakePage:
            def __init__(self) -> None:
                self.kind: str | None = None
                self.kwargs: dict[str, object] = {}

            def get_text(self, kind: str, **kwargs: object) -> dict[str, object]:
                self.kind = kind
                self.kwargs = kwargs
                return {
                    "blocks": [
                        {
                            "lines": [
                                {
                                    "spans": [
                                        {
                                            "text": "Value",
                                            "bbox": (1.0, 2.0, 3.0, 4.0),
                                            "origin": (1.0, 4.0),
                                            "font": "helv",
                                            "size": 7.0,
                                            "color": 0,
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }

        page = FakePage()

        spans = _extract_page_spans(page)  # type: ignore[arg-type]

        self.assertEqual(page.kind, "dict")
        self.assertEqual(page.kwargs.get("flags"), fitz.TEXTFLAGS_TEXT)
        self.assertEqual([span.text for span in spans], ["Value"])

    def test_load_technical_data_workbook_reads_first_sheet_key_value_rows(self) -> None:
        self._write_technical_workbook(
            [
                ("Antenna Name", "Sample Horn"),
                ("Product ID", "SH123"),
                ("", "ignored"),
                ("Radio Connection", "Old connector"),
                ("Radio Connection", "New connector"),
                ("Antenna Type", None),
            ]
        )

        entries = load_technical_data_workbook(self.technical_workbook)
        by_label = {entry.label: entry.value for entry in entries}

        self.assertEqual(by_label["Antenna Name"], "Sample Horn")
        self.assertEqual(by_label["Product ID"], "SH123")
        self.assertEqual(by_label["Radio Connection"], "New connector")
        self.assertEqual(by_label["Antenna Type"], "")
        self.assertNotIn("", by_label)

    def test_load_technical_data_workbook_accepts_label_only_rows(self) -> None:
        pd.DataFrame(["Antenna Name", "Product ID", "Radio Connection"]).to_excel(
            self.technical_workbook,
            sheet_name="Sheet1",
            index=False,
            header=False,
        )

        entries = load_technical_data_workbook(self.technical_workbook)
        by_label = {entry.label: entry.value for entry in entries}

        self.assertEqual(by_label["Antenna Name"], "")
        self.assertEqual(by_label["Product ID"], "")
        self.assertEqual(by_label["Radio Connection"], "")

    def test_build_datasheet_pdf_populates_technical_data_and_marks_missing_values(self) -> None:
        self._write_template_pdf(add_technical_data=True)
        self._write_technical_workbook(
            [
                ("Antenna Name", "Sample Horn"),
                ("Product ID", "SH123"),
                ("Radio Connection", "Waveguide input"),
                ("Antenna Type", ""),
                ("Custom Field", "Custom Value"),
            ]
        )

        replacements = build_datasheet_pdf(
            output=self.output_pdf,
            template=self.template_pdf,
            extract_workbook=self.extract_workbook,
            technical_data_workbook=self.technical_workbook,
        )

        self.assertEqual(replacements["Antenna Name"], "Sample Horn")
        self.assertEqual(replacements["Product ID"], "SH123")
        with fitz.open(self.output_pdf) as doc:
            page = doc[0]
            page_text = page.get_text()
            placeholder_spans = [
                span
                for block in page.get_text("dict").get("blocks", [])
                for line in block.get("lines", [])
                for span in line.get("spans", [])
                if str(span.get("text", "")).strip() == "text_placeholder"
            ]
            custom_span = next(span for span in _extract_page_spans(page) if span.text == "Custom Field")
            line_ys = sorted(
                {
                    round(drawing["rect"].y0, 3)
                    for drawing in page.get_drawings()
                    if drawing.get("rect")
                    and abs(drawing["rect"].y1 - drawing["rect"].y0) <= 0.2
                    and 35.0 <= drawing["rect"].x0 <= 38.0
                    and drawing["rect"].x1 >= 250.0
                }
            )
            previous_line = max(y for y in line_ys if y < custom_span.origin[1])
            custom_bottom_line = min(y for y in line_ys if y > custom_span.bbox.y1)

        self.assertIn("Sample Horn", page_text)
        self.assertIn("SH123", page_text)
        self.assertIn("Waveguide input", page_text)
        self.assertIn("Custom Field", page_text)
        self.assertIn("Custom Value", page_text)
        self.assertIn("text_placeholder", page_text)
        self.assertIn(f"1/2 Sample Horn Rev {datetime.now().strftime('%m-%Y')}", page_text)
        self.assertNotIn("Rev 09-2025", page_text)
        self.assertTrue(placeholder_spans)
        self.assertTrue(any(((span["color"] >> 16) & 0xFF) > 180 for span in placeholder_spans))
        self.assertNotIn("Template connector", page_text)
        self.assertAlmostEqual(custom_bottom_line - previous_line, 12.0, places=1)

    def test_build_datasheet_pdf_matches_alternate_performance_labels(self) -> None:
        self._write_template_pdf(
            field_rows=[
                ("Frequency Range", "Old frequency"),
                ("Nominal Gain", "Old gain"),
                ("Beamwidth H plane.", "Old H-plane beamwidth"),
                ("Beamwidth E plane.", "Old E-plane beamwidth"),
                ("VSWR", "Old VSWR"),
                ("Polarization", "Old polarization"),
                ("Nominal Impedance", "Old impedance"),
            ]
        )

        build_datasheet_pdf(
            output=self.output_pdf,
            template=self.template_pdf,
            extract_workbook=self.extract_workbook,
        )

        with fitz.open(self.output_pdf) as doc:
            page_text = doc[0].get_text()

        self.assertIn("4900 - 7125 MHz", page_text)
        self.assertIn("19.5 dBi", page_text)
        self.assertIn("H 20°, V 20° / H 30°, V 29°", page_text)
        self.assertIn("H 20°, V 20° / H 29°, V 30°", page_text)
        self.assertIn("<1.9", page_text)
        self.assertIn("Dual Linear H + V", page_text)
        self.assertIn("50 Ohm", page_text)
        self.assertNotIn("Old gain", page_text)

    def test_build_datasheet_pdf_netqui_template_marks_missing_technical_values(self) -> None:
        self._write_netqui_technical_template_pdf()
        self._write_technical_workbook(
            [
                ("Antenna Name", ""),
                ("Product ID", ""),
                ("Antenna Type", ""),
                ("Dimensions (LxWxD)", ""),
                ("Weight", ""),
            ]
        )

        build_datasheet_pdf(
            output=self.output_pdf,
            template=self.template_pdf,
            extract_workbook=self.extract_workbook,
            technical_data_workbook=self.technical_workbook,
        )

        with fitz.open(self.output_pdf) as doc:
            page_text = doc[0].get_text()

        self.assertIn("text_placeholder", page_text)
        self.assertIn("4900 - 7125 MHz", page_text)
        self.assertIn("19.5 dBi", page_text)
        self.assertIn("50 Ohm", page_text)
        self.assertIn("Dual Linear H + V", page_text)
        self.assertNotIn("Log-periodic Antenna", page_text)
        self.assertNotIn("1142 x 200 x 618 mm", page_text)
        self.assertNotIn("6.7 kg", page_text)

    def test_exact_span_replacement_does_not_paint_white_background(self) -> None:
        with fitz.open() as doc:
            page = doc.new_page(width=200.0, height=80.0)
            page.draw_line((172.0, 36.0), (182.0, 36.0), color=(0.55, 0.55, 0.55), width=2.0)
            page.draw_rect(fitz.Rect(115.0, 28.0, 185.0, 44.0), color=None, fill=(1.0, 1.0, 1.0))
            page.draw_rect(fitz.Rect(125.0, 32.0, 170.0, 40.0), color=None, fill=(0.95, 0.55, 0.51))
            page.insert_text((20.0, 40.0), "PRODUCT_ID_PLACEHOLDER", fontsize=12.0, fontname="helv", color=(0, 0, 0))
            span = next(span for span in _extract_page_spans(page) if span.text == "PRODUCT_ID_PLACEHOLDER")

            _replace_exact_span_text(page, span, "SH123", registered_fonts=set())
            colored_artifacts = [
                drawing
                for drawing in page.get_drawings()
                if drawing.get("fill")
                and tuple(round(component, 2) for component in drawing["fill"][:3]) == (0.95, 0.55, 0.51)
            ]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)

        self.assertFalse(colored_artifacts)
        found_preserved_line = False
        for y in range(int(33 * 2), int(39 * 2)):
            for x in range(int(172 * 2), int(182 * 2)):
                offset = (y * pix.width + x) * pix.n
                red, green, blue = pix.samples[offset : offset + 3]
                if max(red, green, blue) < 180:
                    found_preserved_line = True
                    break
            if found_preserved_line:
                break
        self.assertTrue(found_preserved_line)

    def test_build_datasheet_pdf_inserts_continuation_page_before_chart_page(self) -> None:
        self._write_template_pdf(add_technical_data=True)
        rows = [
            ("Antenna Name", "Sample Horn"),
            ("Product ID", "SH123"),
            ("Radio Connection", "Waveguide input"),
        ]
        rows.extend((f"Extra Field {index}", f"Extra Value {index}") for index in range(1, 18))
        self._write_technical_workbook(rows)

        build_datasheet_pdf(
            output=self.output_pdf,
            template=self.template_pdf,
            extract_workbook=self.extract_workbook,
            technical_data_workbook=self.technical_workbook,
        )

        with fitz.open(self.output_pdf) as doc:
            self.assertEqual(doc.page_count, 3)
            self.assertIn("TECHNICAL DATA", doc[1].get_text())
            self.assertIn("Extra Field 17", doc[1].get_text())
            chart_text = doc[2].get_text()
            gain_rgb = self._pixel_rgb(doc[2], self.page2_gain_rect.tl + fitz.Point(self.page2_gain_rect.width / 2.0, self.page2_gain_rect.height / 2.0))

        self.assertNotIn("Gain H (IEEE)", chart_text)
        self.assertGreater(gain_rgb[1], 200)

    def test_build_datasheet_pdf_updates_pdf_metadata(self) -> None:
        self.output_pdf = self.root / "SH60WB_datasheet.pdf"
        self._write_template_pdf(
            metadata={
                "title": "AH60WB Datasheet",
                "author": "RF elements",
                "subject": "Legacy datasheet subject",
                "keywords": "wideband, horn",
                "creator": "Adobe InDesign 18.2 (Windows)",
                "producer": "Adobe PDF Library 17.0",
                "creationDate": "D:20241015155652+02'00'",
                "modDate": "D:20250902102701+02'00'",
                "trapped": "False",
            },
            xml_metadata=(
                '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
                '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
                "  <rdf:RDF xmlns:rdf=\"http://www.w3.org/1999/02/22-rdf-syntax-ns#\">\n"
                "    <rdf:Description rdf:about=\"\" xmlns:dc=\"http://purl.org/dc/elements/1.1/\">\n"
                "      <dc:title><rdf:Alt><rdf:li xml:lang=\"x-default\">AH60WB Datasheet</rdf:li></rdf:Alt></dc:title>\n"
                "    </rdf:Description>\n"
                "  </rdf:RDF>\n"
                "</x:xmpmeta>\n"
                '<?xpacket end="w"?>'
            ),
        )

        build_datasheet_pdf(
            output=self.output_pdf,
            template=self.template_pdf,
            extract_workbook=self.extract_workbook,
        )

        with fitz.open(self.output_pdf) as doc:
            metadata = doc.metadata
            xml_metadata = doc.get_xml_metadata() if hasattr(doc, "get_xml_metadata") else ""

        self.assertEqual(metadata["title"], "SH60WB Datasheet")
        self.assertEqual(metadata["subject"], "SH60WB Datasheet")
        self.assertEqual(metadata["author"], "RF elements")
        self.assertIn("SH60WB", metadata["keywords"])
        self.assertIn("datasheet", metadata["keywords"].lower())
        self.assertEqual(metadata["creator"], "Antenna Toolkit")
        self.assertEqual(metadata["producer"], "Antenna Toolkit (PyMuPDF)")
        self.assertEqual(metadata["creationDate"], "D:20241015155652+02'00'")
        self.assertNotEqual(metadata["modDate"], "D:20250902102701+02'00'")
        self.assertIn("SH60WB Datasheet", xml_metadata)
        self.assertNotIn("AH60WB Datasheet", xml_metadata)

    def test_build_datasheet_pdf_uses_metadata_author_override(self) -> None:
        self._write_template_pdf(
            metadata={
                "title": "AH60WB Datasheet",
                "author": "Template Author",
                "subject": "",
                "keywords": "",
                "creator": "Adobe InDesign 18.2 (Windows)",
                "producer": "Adobe PDF Library 17.0",
                "creationDate": "D:20241015155652+02'00'",
                "modDate": "D:20250902102701+02'00'",
            }
        )

        build_datasheet_pdf(
            output=self.output_pdf,
            template=self.template_pdf,
            extract_workbook=self.extract_workbook,
            metadata_author="Custom Author",
        )

        with fitz.open(self.output_pdf) as doc:
            metadata = doc.metadata
            xml_metadata = doc.get_xml_metadata() if hasattr(doc, "get_xml_metadata") else ""

        self.assertEqual(metadata["author"], "Custom Author")
        self.assertIn("Custom Author", xml_metadata)
        self.assertNotIn("Template Author", xml_metadata)

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

    def test_build_datasheet_pdf_keeps_azimuth_left_and_elevation_right(self) -> None:
        self._write_template_pdf(reverse_polar_slot_order=True)

        build_datasheet_pdf(
            output=self.output_pdf,
            template=self.template_pdf,
            extract_workbook=self.extract_workbook,
        )

        with fitz.open(self.output_pdf) as doc:
            page = doc[1]
            azimuth_rgb = self._pixel_rgb(page, self.page2_azimuth_rect.tl + fitz.Point(self.page2_azimuth_rect.width / 2.0, self.page2_azimuth_rect.height / 2.0))
            elevation_rgb = self._pixel_rgb(page, self.page2_elevation_rect.tl + fitz.Point(self.page2_elevation_rect.width / 2.0, self.page2_elevation_rect.height / 2.0))

        self.assertGreater(azimuth_rgb[1], 200)
        self.assertGreater(azimuth_rgb[2], 200)
        self.assertGreater(elevation_rgb[0], 200)
        self.assertGreater(elevation_rgb[2], 200)

    def test_build_datasheet_pdf_removes_template_legend_handles(self) -> None:
        self._write_template_pdf(add_legend_handles=True)

        build_datasheet_pdf(
            output=self.output_pdf,
            template=self.template_pdf,
            extract_workbook=self.extract_workbook,
        )

        with fitz.open(self.output_pdf) as doc:
            page = doc[1]
            gain_handle_rgb = self._pixel_rgb(page, fitz.Point(345.0, 172.0))
            beamwidth_handle_rgb = self._pixel_rgb(page, fitz.Point(345.0, 330.0))
            polar_handle_rgb = self._pixel_rgb(page, fitz.Point(103.0, 608.0))

        for rgb in (gain_handle_rgb, beamwidth_handle_rgb, polar_handle_rgb):
            self.assertGreater(min(rgb), 220)

    def test_separate_plot_and_legend_rects_shrinks_plot_when_legend_is_on_the_right(self) -> None:
        plot_rect = fitz.Rect(24.0, 120.0, 380.0, 240.0)
        legend_rect = fitz.Rect(300.0, 150.0, 420.0, 220.0)

        adjusted_plot, adjusted_legend = _separate_plot_and_legend_rects(plot_rect, legend_rect)

        self.assertLessEqual(adjusted_plot.x1, adjusted_legend.x0 - 5.9)
        self.assertEqual(adjusted_plot.y0, plot_rect.y0)
        self.assertEqual(adjusted_plot.y1, plot_rect.y1)

    def test_separate_plot_and_legend_rects_shrinks_plot_when_legend_is_below(self) -> None:
        plot_rect = fitz.Rect(24.0, 120.0, 240.0, 320.0)
        legend_rect = fitz.Rect(60.0, 270.0, 220.0, 360.0)

        adjusted_plot, adjusted_legend = _separate_plot_and_legend_rects(plot_rect, legend_rect)

        self.assertLessEqual(adjusted_plot.y1, adjusted_legend.y0 - 5.9)
        self.assertEqual(adjusted_plot.x0, plot_rect.x0)
        self.assertEqual(adjusted_plot.x1, plot_rect.x1)

    def test_layout_split_chart_rects_prefers_horizontal_for_gain_and_beamwidth(self) -> None:
        gain_plot, gain_legend = _layout_split_chart_rects(
            "gain",
            fitz.Rect(24.0, 120.0, 324.0, 240.0),
            fitz.Rect(360.0, 180.0, 420.0, 212.0),
        )
        beam_plot, beam_legend = _layout_split_chart_rects(
            "beamwidth",
            fitz.Rect(24.0, 280.0, 324.0, 400.0),
            fitz.Rect(360.0, 338.0, 438.0, 390.0),
        )

        self.assertLessEqual(gain_plot.x1, gain_legend.x0 - 5.9)
        self.assertLessEqual(beam_plot.x1, beam_legend.x0 - 5.9)
        self.assertAlmostEqual(gain_plot.width, beam_plot.width, delta=0.5)

    def test_layout_split_chart_rects_centers_polar_legend_below_plot(self) -> None:
        plot_rect, legend_rect = _layout_split_chart_rects(
            "azimuth",
            fitz.Rect(24.0, 460.0, 164.0, 600.0),
            fitz.Rect(28.0, 616.0, 162.0, 640.0),
        )

        self.assertLessEqual(plot_rect.y1, legend_rect.y0 - 5.9)
        self.assertAlmostEqual((plot_rect.x0 + plot_rect.x1) / 2.0, (legend_rect.x0 + legend_rect.x1) / 2.0, delta=0.5)

    def test_build_chart_replacements_keep_gain_and_beamwidth_same_width_and_center_polar_legends(self) -> None:
        with fitz.open(self.template_pdf) as doc:
            replacements = _build_chart_replacements(doc[1], self.output_pdf, self.extract_workbook)

        by_kind = {replacement.kind: replacement for replacement in replacements}

        self.assertAlmostEqual(by_kind["gain"].rect.width, by_kind["beamwidth"].rect.width, delta=0.5)
        assert by_kind["gain"].legend_rect is not None
        assert by_kind["beamwidth"].legend_rect is not None
        assert by_kind["azimuth"].legend_rect is not None
        assert by_kind["elevation"].legend_rect is not None
        self.assertLessEqual(by_kind["gain"].rect.x1, by_kind["gain"].legend_rect.x0 - 5.9)
        self.assertLessEqual(by_kind["beamwidth"].rect.x1, by_kind["beamwidth"].legend_rect.x0 - 5.9)
        self.assertAlmostEqual(
            (by_kind["azimuth"].rect.x0 + by_kind["azimuth"].rect.x1) / 2.0,
            (by_kind["azimuth"].legend_rect.x0 + by_kind["azimuth"].legend_rect.x1) / 2.0,
            delta=0.5,
        )
        self.assertAlmostEqual(
            (by_kind["elevation"].rect.x0 + by_kind["elevation"].rect.x1) / 2.0,
            (by_kind["elevation"].legend_rect.x0 + by_kind["elevation"].legend_rect.x1) / 2.0,
            delta=0.5,
        )

    def test_rfe_template_manifest_keeps_azimuth_left_and_elevation_right(self) -> None:
        self._write_template_pdf(reverse_polar_slot_order=True)

        with fitz.open(self.template_pdf) as doc:
            replacements = _build_chart_replacements(
                doc[1],
                self.output_pdf,
                self.extract_workbook,
                adapter=RFE_TEMPLATE_ADAPTER,
            )

        by_kind = {replacement.kind: replacement for replacement in replacements}
        self.assertLess(by_kind["azimuth"].rect.x0, by_kind["elevation"].rect.x0)
        self.assertEqual(by_kind["azimuth"].asset_path, self.azimuth_svg)
        self.assertEqual(by_kind["elevation"].asset_path, self.elevation_svg)

    def test_netqui_template_uses_e_and_h_plane_beamwidth_slots(self) -> None:
        self._write_netqui_chart_template_pdf()

        with fitz.open(self.template_pdf) as doc:
            replacements = _build_chart_replacements(doc[1], self.output_pdf, self.extract_workbook)

        by_kind = {replacement.kind: replacement for replacement in replacements}
        self.assertEqual(by_kind["gain"].asset_path, self.gain_svg)
        self.assertEqual(by_kind["vswr"].asset_path, self.vswr_svg)
        self.assertEqual(by_kind["beamwidth_e_plane"].asset_path, self.beamwidth_e_plane_h_svg)
        self.assertEqual(by_kind["beamwidth_h_plane"].asset_path, self.beamwidth_h_plane_h_svg)
        self.assertLess(by_kind["gain"].rect.x0, by_kind["vswr"].rect.x0)
        self.assertEqual(by_kind["gain"].legend_asset_path, self.gain_legend_svg)
        self.assertEqual(by_kind["vswr"].legend_asset_path, self.vswr_legend_svg)
        self.assertLess(by_kind["gain"].rect.x1, by_kind["gain"].legend_rect.x0)
        self.assertLess(by_kind["vswr"].rect.x1, by_kind["vswr"].legend_rect.x0)
        self.assertLess(by_kind["beamwidth_e_plane"].erase_rect.x0, by_kind["beamwidth_h_plane"].erase_rect.x0)
        self.assertLess(by_kind["beamwidth_e_plane"].rect.x1, by_kind["beamwidth_e_plane"].legend_rect.x0)
        self.assertLess(by_kind["beamwidth_h_plane"].rect.x1, by_kind["beamwidth_h_plane"].legend_rect.x0)
        self.assertEqual(by_kind["beamwidth_e_plane"].legend_asset_path, self.beamwidth_e_plane_h_legend_svg)
        self.assertEqual(by_kind["beamwidth_h_plane"].legend_asset_path, self.beamwidth_h_plane_h_legend_svg)

    def test_netqui_template_manifest_assigns_fixed_chart_slots(self) -> None:
        gain_rect, vswr_rect, e_plane_rect, h_plane_rect = self._write_netqui_chart_template_pdf()

        with fitz.open(self.template_pdf) as doc:
            replacements = _build_chart_replacements(
                doc[1],
                self.output_pdf,
                self.extract_workbook,
                adapter=NETQUI_TEMPLATE_ADAPTER,
            )

        by_kind = {replacement.kind: replacement for replacement in replacements}
        self.assertEqual(by_kind["gain"].asset_path, self.gain_svg)
        self.assertEqual(by_kind["vswr"].asset_path, self.vswr_svg)
        self.assertEqual(by_kind["beamwidth_e_plane"].asset_path, self.beamwidth_e_plane_h_svg)
        self.assertEqual(by_kind["beamwidth_h_plane"].asset_path, self.beamwidth_h_plane_h_svg)
        self.assertAlmostEqual(by_kind["gain"].rect.x0, gain_rect.x0, delta=0.1)
        self.assertAlmostEqual(by_kind["gain"].erase_rect.x1, gain_rect.x1, delta=0.1)
        self.assertLess(by_kind["gain"].rect.x1, by_kind["gain"].legend_rect.x0)
        self.assertEqual(by_kind["gain"].legend_asset_path, self.gain_legend_svg)
        self.assertAlmostEqual(by_kind["vswr"].rect.x0, vswr_rect.x0, delta=0.1)
        self.assertAlmostEqual(by_kind["vswr"].erase_rect.x1, vswr_rect.x1, delta=0.1)
        self.assertLess(by_kind["vswr"].rect.x1, by_kind["vswr"].legend_rect.x0)
        self.assertEqual(by_kind["vswr"].legend_asset_path, self.vswr_legend_svg)
        self.assertAlmostEqual(by_kind["beamwidth_e_plane"].erase_rect.x0, e_plane_rect.x0, delta=0.1)
        self.assertAlmostEqual(by_kind["beamwidth_h_plane"].erase_rect.x0, h_plane_rect.x0, delta=0.1)

    def test_netqui_1pol_template_resolves_before_generic_netqui(self) -> None:
        template_path = self.root / "Datasheet - Netqui - 1Pol.pdf"
        self._write_netqui_chart_template_pdf()
        self.template_pdf.replace(template_path)

        with fitz.open(template_path) as doc:
            adapter = resolve_template_adapter(template_path, doc)

        self.assertEqual(adapter.key, "netqui_1pol")

    def test_netqui_separator_redraw_does_not_join_blank_bottom_rules(self) -> None:
        self._write_netqui_technical_template_pdf()
        with fitz.open(self.template_pdf) as doc:
            page = doc[0]
            y = 570.0
            page.draw_line((36.638, y), (138.0, y), color=(0.14, 0.12, 0.12), width=0.25)
            page.draw_line((138.4, y), (300.0, y), color=(0.14, 0.12, 0.12), width=0.25)

            _redraw_template_table_separators(page, NETQUI_1POL_TEMPLATE_ADAPTER)

            joined = [
                drawing
                for drawing in page.get_drawings()
                if (rect := drawing.get("rect")) is not None
                and abs(float(rect.y0) - y) <= 0.2
                and float(rect.x0) <= 37.0
                and float(rect.x1) >= 299.0
            ]

        self.assertFalse(joined)

    def test_netqui_1pol_manifest_assigns_seven_chart_slots(self) -> None:
        self._write_netqui_chart_template_pdf()
        update_artifact_manifest(
            self.root,
            "extract",
            gain=build_asset_record(self.gain_svg, legend_path=self.gain_legend_svg),
            vswr=build_asset_record(self.vswr_svg),
            beamwidth_planes=[
                build_asset_record(self.beamwidth_e_plane_h_svg, legend_path=self.beamwidth_e_plane_h_legend_svg, plane="e-plane", polarization="H"),
                build_asset_record(self.beamwidth_h_plane_h_svg, legend_path=self.beamwidth_h_plane_h_legend_svg, plane="h-plane", polarization="H"),
            ],
            polar_combined=[
                build_asset_record(self.combined_low_svg, legend_path=self.combined_low_legend_svg, frequency_ghz=4.9),
                build_asset_record(self.combined_mid_svg, legend_path=self.combined_mid_legend_svg, frequency_ghz=6.0),
                build_asset_record(self.combined_high_svg, legend_path=self.combined_high_legend_svg, frequency_ghz=7.125),
            ],
            polar_combined_planes=[
                build_asset_record(self.combined_eh_low_svg, legend_path=self.combined_eh_low_legend_svg, frequency_ghz=4.9, plane_mode="e-h-plane"),
                build_asset_record(self.combined_eh_mid_svg, legend_path=self.combined_eh_mid_legend_svg, frequency_ghz=6.0, plane_mode="e-h-plane"),
                build_asset_record(self.combined_eh_high_svg, legend_path=self.combined_eh_high_legend_svg, frequency_ghz=7.125, plane_mode="e-h-plane"),
            ],
        )
        manifest = load_artifact_manifest(self.root / "extract-artifacts.json", bookstem="extract")

        with fitz.open(self.template_pdf) as doc:
            replacements = _build_chart_replacements(
                doc[1],
                self.output_pdf,
                self.extract_workbook,
                adapter=NETQUI_1POL_TEMPLATE_ADAPTER,
                artifact_manifest=manifest,
            )

        by_kind = {replacement.kind: replacement for replacement in replacements}
        self.assertEqual(len(replacements), 7)
        self.assertEqual(by_kind["gain"].asset_path, self.gain_svg)
        self.assertEqual(by_kind["vswr"].asset_path, self.vswr_svg)
        self.assertEqual(by_kind["beamwidth_e_plane"].asset_path, self.beamwidth_e_plane_h_svg)
        self.assertEqual(by_kind["beamwidth_h_plane"].asset_path, self.beamwidth_h_plane_h_svg)
        self.assertEqual(by_kind["radiation_low"].asset_path, self.combined_eh_low_svg)
        self.assertEqual(by_kind["radiation_mid"].asset_path, self.combined_eh_mid_svg)
        self.assertEqual(by_kind["radiation_high"].asset_path, self.combined_eh_high_svg)
        self.assertEqual(by_kind["radiation_low"].legend_asset_path, self.combined_eh_low_legend_svg)
        self.assertEqual(by_kind["radiation_mid"].legend_asset_path, self.combined_eh_mid_legend_svg)
        self.assertEqual(by_kind["radiation_high"].legend_asset_path, self.combined_eh_high_legend_svg)
        self.assertLess(by_kind["radiation_low"].rect.y1, by_kind["radiation_low"].legend_rect.y0)
        self.assertAlmostEqual(by_kind["gain"].rect.x0, by_kind["beamwidth_e_plane"].rect.x0, delta=0.01)
        self.assertAlmostEqual(by_kind["gain"].rect.x1, by_kind["beamwidth_e_plane"].rect.x1, delta=0.01)
        self.assertAlmostEqual(by_kind["gain"].legend_rect.x0, by_kind["beamwidth_e_plane"].legend_rect.x0, delta=0.01)
        self.assertAlmostEqual(by_kind["vswr"].rect.x0, by_kind["beamwidth_h_plane"].rect.x0, delta=0.01)
        self.assertAlmostEqual(by_kind["vswr"].rect.x1, by_kind["beamwidth_h_plane"].rect.x1, delta=0.01)
        self.assertAlmostEqual(by_kind["vswr"].legend_rect.x0, by_kind["beamwidth_h_plane"].legend_rect.x0, delta=0.01)
        self.assertAlmostEqual(by_kind["gain"].rect.y0, by_kind["vswr"].rect.y0, delta=0.01)
        self.assertAlmostEqual(by_kind["beamwidth_e_plane"].rect.y0, by_kind["beamwidth_h_plane"].rect.y0, delta=0.01)

    def test_netqui_1pol_frequency_triplet_uses_closest_unique_combined_assets(self) -> None:
        with pd.ExcelWriter(self.extract_workbook) as writer:
            pd.DataFrame(
                [
                    {
                        "source_file": "sample.ffs",
                        "polarization": "Vertical",
                        "freq_min_GHz": 0.3,
                        "freq_max_GHz": 3.0,
                    }
                ]
            ).to_excel(writer, sheet_name="ffs_summary", index=False)
        assets = [
            (self.root / "polar_combined" / "extract-polar-0.300-GHz-combined.svg", 0.3),
            (self.root / "polar_combined" / "extract-polar-1.400-GHz-combined.svg", 1.4),
            (self.root / "polar_combined" / "extract-polar-1.700-GHz-combined.svg", 1.7),
            (self.root / "polar_combined" / "extract-polar-3.000-GHz-combined.svg", 3.0),
        ]
        for path, _frequency in assets:
            self._write_svg(path, "#2266aa", width=140, height=140)
        update_artifact_manifest(
            self.root,
            "extract",
            polar_combined=[build_asset_record(path, frequency_ghz=frequency) for path, frequency in assets],
        )
        manifest = load_artifact_manifest(self.root / "extract-artifacts.json", bookstem="extract")

        triplet = _find_combined_polar_triplet_assets(self.output_pdf, self.extract_workbook, manifest)

        self.assertEqual(triplet["low"], assets[0][0])
        self.assertEqual(triplet["mid"], assets[2][0])
        self.assertEqual(triplet["high"], assets[3][0])

    def test_build_chart_replacements_prefers_artifact_manifest_assets(self) -> None:
        manifest_gain_legend = self.root / "manifest-legends" / "gain-key.svg"
        manifest_beamwidth_legend = self.root / "manifest-legends" / "beamwidth-key.svg"
        manifest_azimuth_legend = self.root / "manifest-legends" / "azimuth-key.svg"
        manifest_elevation_legend = self.root / "manifest-legends" / "elevation-key.svg"
        for path in (manifest_gain_legend, manifest_beamwidth_legend, manifest_azimuth_legend, manifest_elevation_legend):
            self._write_svg(path, "#ffffff", width=140, height=70)
        update_artifact_manifest(
            self.root,
            "extract",
            gain=build_asset_record(self.manifest_gain_svg, legend_path=manifest_gain_legend),
            beamwidth=build_asset_record(self.manifest_beamwidth_svg, legend_path=manifest_beamwidth_legend),
            polar_single=[
                build_asset_record(self.manifest_azimuth_svg, legend_path=manifest_azimuth_legend, plane="azimuth", frequency_ghz=5.5),
                build_asset_record(self.manifest_elevation_svg, legend_path=manifest_elevation_legend, plane="elevation", frequency_ghz=5.5),
            ],
        )
        manifest = load_artifact_manifest(self.root / "extract-artifacts.json", bookstem="extract")

        with fitz.open(self.template_pdf) as doc:
            replacements = _build_chart_replacements(
                doc[1],
                self.output_pdf,
                self.extract_workbook,
                artifact_manifest=manifest,
            )

        by_kind = {replacement.kind: replacement for replacement in replacements}
        self.assertEqual(by_kind["gain"].asset_path, self.manifest_gain_svg)
        self.assertEqual(by_kind["beamwidth"].asset_path, self.manifest_beamwidth_svg)
        self.assertEqual(by_kind["azimuth"].asset_path, self.manifest_azimuth_svg)
        self.assertEqual(by_kind["elevation"].asset_path, self.manifest_elevation_svg)
        self.assertEqual(by_kind["gain"].legend_asset_path, manifest_gain_legend)
        self.assertEqual(by_kind["beamwidth"].legend_asset_path, manifest_beamwidth_legend)
        self.assertEqual(by_kind["azimuth"].legend_asset_path, manifest_azimuth_legend)
        self.assertEqual(by_kind["elevation"].legend_asset_path, manifest_elevation_legend)

    def test_missing_beamwidth_plane_asset_reports_plots_only_rerun(self) -> None:
        self.beamwidth_e_plane_h_svg.unlink()

        with self.assertRaisesRegex(ValueError, "Rerun Plots only.*missing E Plane beamwidth SVG"):
            _find_beamwidth_plane_asset(self.output_pdf, self.extract_workbook, "e-plane")

    def test_normalize_plot_widths_equalizes_gain_and_beamwidth(self) -> None:
        replacements = [
            ChartReplacement(
                "gain",
                fitz.Rect(10.0, 20.0, 210.0, 120.0),
                self.gain_svg,
                legend_rect=fitz.Rect(220.0, 30.0, 300.0, 90.0),
                legend_asset_path=self.gain_legend_svg,
            ),
            ChartReplacement(
                "beamwidth",
                fitz.Rect(12.0, 140.0, 172.0, 240.0),
                self.beamwidth_svg,
                legend_rect=fitz.Rect(182.0, 150.0, 292.0, 230.0),
                legend_asset_path=self.beamwidth_legend_svg,
            ),
        ]

        normalized = _normalize_plot_widths(replacements, {"gain", "beamwidth"})
        by_kind = {replacement.kind: replacement for replacement in normalized}

        self.assertAlmostEqual(by_kind["gain"].rect.width, by_kind["beamwidth"].rect.width, delta=0.01)
        self.assertEqual(by_kind["gain"].rect.x0, 10.0)
        self.assertEqual(by_kind["beamwidth"].rect.x0, 12.0)
        self.assertLessEqual(by_kind["gain"].rect.x1, replacements[0].legend_rect.x0)
        self.assertLessEqual(by_kind["beamwidth"].rect.x1, replacements[1].legend_rect.x0)

    def test_gain_and_beamwidth_side_legends_share_the_same_scale(self) -> None:
        with fitz.open(self.template_pdf) as doc:
            replacements = _build_chart_replacements(doc[1], self.output_pdf, self.extract_workbook)

        by_kind = {replacement.kind: replacement for replacement in replacements}
        shared_scale = _shared_side_legend_scale(replacements)

        self.assertIsNotNone(shared_scale)
        gain_target = _legend_target_rect(by_kind["gain"], shared_scale)
        beamwidth_target = _legend_target_rect(by_kind["beamwidth"], shared_scale)

        gain_scale = min(gain_target.width / 140.0, gain_target.height / 70.0)
        beamwidth_scale = min(beamwidth_target.width / 180.0, beamwidth_target.height / 110.0)

        self.assertAlmostEqual(gain_scale, beamwidth_scale, delta=0.01)
        self.assertLessEqual(gain_target.width, by_kind["gain"].legend_rect.width)
        self.assertLessEqual(gain_target.height, by_kind["gain"].legend_rect.height)
        self.assertLessEqual(beamwidth_target.width, by_kind["beamwidth"].legend_rect.width)
        self.assertLessEqual(beamwidth_target.height, by_kind["beamwidth"].legend_rect.height)

    def test_polar_legends_use_same_scale_as_cartesian_legends(self) -> None:
        with fitz.open(self.template_pdf) as doc:
            replacements = _build_chart_replacements(doc[1], self.output_pdf, self.extract_workbook)

        by_kind = {replacement.kind: replacement for replacement in replacements}
        shared_scale = _shared_side_legend_scale(replacements)

        self.assertIsNotNone(shared_scale)
        beamwidth_target = _legend_target_rect(by_kind["beamwidth"], shared_scale)
        azimuth_target = _legend_target_rect(by_kind["azimuth"], shared_scale)

        beamwidth_scale = min(beamwidth_target.width / 180.0, beamwidth_target.height / 110.0)
        azimuth_scale = min(azimuth_target.width / 150.0, azimuth_target.height / 70.0)

        self.assertAlmostEqual(beamwidth_scale, azimuth_scale, delta=0.01)
        self.assertLessEqual(azimuth_target.width, by_kind["azimuth"].legend_rect.width)
        self.assertLessEqual(azimuth_target.height, by_kind["azimuth"].legend_rect.height)

    def test_svg_to_pdf_bytes_preserves_dashed_strokes(self) -> None:
        dashed_svg = self.root / "dashed.svg"
        dashed_svg.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="80" viewBox="0 0 240 80">'
                '<rect x="0" y="0" width="240" height="80" fill="#ffffff"/>'
                '<line x1="20" y1="24" x2="220" y2="24" stroke="#2bb3f3" stroke-width="8"/>'
                '<line x1="20" y1="56" x2="220" y2="56" stroke="#2bb3f3" stroke-width="8" stroke-dasharray="24 18"/>'
                "</svg>"
            ),
            encoding="utf-8",
        )

        pdf_bytes = _svg_to_pdf_bytes(dashed_svg)
        with fitz.open("pdf", pdf_bytes) as doc:
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False)

        solid_runs = self._count_colored_runs(
            pix,
            y=96,
            rgb_min=(0, 120, 180),
            rgb_max=(120, 255, 255),
        )
        dashed_runs = self._count_colored_runs(
            pix,
            y=224,
            rgb_min=(0, 120, 180),
            rgb_max=(120, 255, 255),
        )

        self.assertEqual(solid_runs, 1)
        self.assertGreaterEqual(dashed_runs, 3)

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
