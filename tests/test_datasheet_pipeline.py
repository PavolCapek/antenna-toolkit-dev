from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import fitz
import pandas as pd

from datasheet.artifacts import artifact_manifest_path, build_asset_record, load_artifact_manifest, update_artifact_manifest
from datasheet.service import build_render_context
from datasheet.specs import ChartLayoutSpec, ChartSlotSpec, DatasheetSpec, TemplateMatchSpec, load_default_datasheet_specs


class DatasheetPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.template_pdf = self.root / "Datasheet - Netqui.pdf"
        self.extract_workbook = self.root / "sample-extracted-data.xlsx"
        self.technical_workbook = self.root / "technical.xlsx"
        self.chart_svg = self.root / "odd-name.svg"
        self.chart_svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="#00ff00"/></svg>',
            encoding="utf-8",
        )
        self._write_template()
        self._write_extract_workbook()
        pd.DataFrame([["Antenna Name", "Sample"], ["Product ID", "SKU-1"]]).to_excel(
            self.technical_workbook,
            sheet_name="Sheet1",
            index=False,
            header=False,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_template(self) -> None:
        with fitz.open() as doc:
            doc.new_page()
            page = doc.new_page(width=596.0, height=842.0)
            page.insert_text((36.0, 32.0), "ANTENNA GAIN", fontsize=8, fontname="helv")
            page.insert_text((360.0, 32.0), "VSWR", fontsize=8, fontname="helv")
            page.insert_text((36.0, 260.0), "ANTENNA BEAMWIDTH", fontsize=8, fontname="helv")
            page.insert_text((36.0, 480.0), "RADIATION PATTERNS", fontsize=8, fontname="helv")
            page.insert_text((500.0, 20.0), "NETQUI", fontsize=8, fontname="helv")
            doc.save(self.template_pdf)

    def _write_extract_workbook(self) -> None:
        ffs_summary = pd.DataFrame(
            [
                {
                    "source_file": "sample.ffs",
                    "polarization": "Vertical",
                    "freq_min_GHz": 4.9,
                    "freq_max_GHz": 7.125,
                    "max_gain_dBi_in_range": 19.5,
                    "avg_azimuth_bw_3dB_deg": 20.0,
                    "avg_azimuth_bw_6dB_deg": 30.0,
                    "avg_elevation_bw_3dB_deg": 21.0,
                    "avg_elevation_bw_6dB_deg": 31.0,
                    "avg_beam_efficiency_percent": 96.0,
                    "avg_front_to_back_dB": 27.0,
                }
            ]
        )
        touchstone_summary = pd.DataFrame(
            [
                {
                    "freq_min_GHz": 4.9,
                    "freq_max_GHz": 7.125,
                    "max_vswr_in_range": 1.8,
                    "reference_impedance_ohm": 50,
                }
            ]
        )
        with pd.ExcelWriter(self.extract_workbook) as writer:
            ffs_summary.to_excel(writer, sheet_name="ffs_summary", index=False)
            touchstone_summary.to_excel(writer, sheet_name="touchstone_summary", index=False)

    def test_update_artifact_manifest_round_trips(self) -> None:
        update_artifact_manifest(
            self.root,
            "sample",
            gain=build_asset_record(self.chart_svg),
        )
        manifest_path = artifact_manifest_path(self.root, "sample")
        manifest = load_artifact_manifest(manifest_path, bookstem="sample")

        self.assertEqual(manifest["bookstem"], "sample")
        self.assertEqual(manifest["charts"]["gain"]["svg"], str(self.chart_svg.resolve()))

    def test_build_render_context_uses_template_adapter_and_manifest(self) -> None:
        update_artifact_manifest(
            self.root,
            "sample",
            gain=build_asset_record(self.chart_svg),
        )
        with fitz.open(self.template_pdf) as doc:
            context = build_render_context(
                self.template_pdf,
                doc,
                self.extract_workbook,
                self.technical_workbook,
                output_dir=self.root,
            )

        self.assertEqual(context.adapter.key, "netqui")
        self.assertIsNotNone(context.adapter.manifest)
        self.assertEqual(context.adapter.manifest.chart_layout.min_image_slots, 4)
        self.assertEqual(context.model.performance_fields["Gain"], "19.5 dBi")
        self.assertEqual(context.model.artifact_manifest["charts"]["gain"]["svg"], str(self.chart_svg.resolve()))

    def test_build_render_context_auto_detects_template_adapter_from_filename(self) -> None:
        rfe_template = self.root / "Datasheet - RFE.pdf"
        with fitz.open() as doc:
            doc.new_page(width=596.0, height=842.0)
            doc.save(rfe_template)

        with fitz.open(rfe_template) as doc:
            context = build_render_context(
                rfe_template,
                doc,
                self.extract_workbook,
                output_dir=self.root,
            )

        self.assertEqual(context.adapter.key, "rfe")
        self.assertIsNotNone(context.adapter.manifest)
        self.assertEqual(context.adapter.manifest.chart_layout.slot_order, "first_two_then_x")

    def test_default_datasheet_specs_define_template_contracts(self) -> None:
        specs = load_default_datasheet_specs()
        expected = {
            "rfe": {
                "filename_tokens": ("rfe", "rf elements"),
                "chart_layout_mode": "generic",
                "technical_layout_mode": "generic",
                "slot_order": "first_two_then_x",
                "slots": (
                    ("gain", "gain"),
                    ("beamwidth", "beamwidth"),
                    ("azimuth", "polar_azimuth"),
                    ("elevation", "polar_elevation"),
                ),
            },
            "netqui": {
                "filename_tokens": ("netqui",),
                "chart_layout_mode": "netqui",
                "technical_layout_mode": "netqui",
                "slot_order": "rows",
                "slots": (
                    ("gain", "gain"),
                    ("vswr", "vswr"),
                    ("beamwidth_e_plane", "beamwidth_plane"),
                    ("beamwidth_h_plane", "beamwidth_plane"),
                ),
            },
            "netqui_1pol": {
                "filename_tokens": ("netqui - 1pol", "netqui-1pol", "netqui_1pol"),
                "chart_layout_mode": "netqui_1pol",
                "technical_layout_mode": "netqui_1pol",
                "slot_order": "rows",
                "slots": (
                    ("gain", "gain"),
                    ("vswr", "vswr"),
                    ("beamwidth_e_plane", "beamwidth_plane"),
                    ("beamwidth_h_plane", "beamwidth_plane"),
                    ("radiation_low", "polar_combined_planes_triplet"),
                    ("radiation_mid", "polar_combined_planes_triplet"),
                    ("radiation_high", "polar_combined_planes_triplet"),
                ),
            },
        }

        for key, contract in expected.items():
            with self.subTest(key=key):
                spec = specs[key]
                self.assertEqual(spec.match.filename_tokens, contract["filename_tokens"])
                self.assertEqual(spec.chart_layout_mode, contract["chart_layout_mode"])
                self.assertEqual(spec.technical_layout_mode, contract["technical_layout_mode"])
                self.assertIsNotNone(spec.chart_layout)
                self.assertEqual(spec.chart_layout.slot_order, contract["slot_order"])
                self.assertEqual(
                    tuple((slot.kind, slot.asset_key) for slot in spec.chart_layout.slots),
                    contract["slots"],
                )

    def test_build_render_context_auto_discovers_external_matching_spec(self) -> None:
        custom_template = self.root / "Custom Export.pdf"
        with fitz.open() as doc:
            doc.new_page(width=596.0, height=842.0)
            doc.save(custom_template)
        spec = DatasheetSpec(
            key="custom",
            display_name="Custom Datasheet",
            layout_key="custom",
            match=TemplateMatchSpec(filename_tokens=("custom",)),
            chart_layout=ChartLayoutSpec(
                min_image_slots=1,
                slots=(ChartSlotSpec("beam_efficiency", 0, "beam_efficiency"),),
            ),
        )

        with fitz.open(custom_template) as doc:
            context = build_render_context(
                custom_template,
                doc,
                self.extract_workbook,
                datasheet_specs={"custom": spec},
                output_dir=self.root,
            )

        self.assertEqual(context.adapter.key, "custom")
        self.assertEqual(context.adapter.manifest.chart_layout.slots[0].asset_key, "beam_efficiency")

    def test_build_render_context_auto_discovery_does_not_override_known_adapter(self) -> None:
        spec = DatasheetSpec(
            key="custom_netqui",
            display_name="Custom Netqui",
            layout_key="custom_netqui",
            match=TemplateMatchSpec(filename_tokens=("netqui",)),
            chart_layout=ChartLayoutSpec(
                min_image_slots=1,
                slots=(ChartSlotSpec("beam_efficiency", 0, "beam_efficiency"),),
            ),
        )

        with fitz.open(self.template_pdf) as doc:
            context = build_render_context(
                self.template_pdf,
                doc,
                self.extract_workbook,
                datasheet_specs={"custom_netqui": spec},
                output_dir=self.root,
            )

        self.assertEqual(context.adapter.key, "netqui")
