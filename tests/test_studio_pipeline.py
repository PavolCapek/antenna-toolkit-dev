from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pytest

from pipeline.stages import (
    stage_generated_directories,
    stage_is_applicable,
    stage_output_files,
    stage_settings_snapshot,
    stage_stale_detail,
    stage_tool_versions,
)


class StudioPipelineTests(unittest.TestCase):
    @pytest.mark.export_acceptance
    def test_stage_settings_snapshot_filters_by_stage(self) -> None:
        values = {
            "smooth": 5,
            "theta": 8,
            "grid_color": "#aaaaaa",
            "polar_figure_size": 7.5,
            "polar_line_width": 3,
            "vswr_ymax": 4,
            "compliance_fmin": 4.9,
            "compliance_fmax": 6.1,
            "compliance_omit_angle_range": "180-180",
            "compliance_sector_width": 90.0,
            "compliance_sector_center": 6.0,
            "unrelated": "ignored",
        }

        self.assertEqual(stage_settings_snapshot("beam", values), {"smooth": 5, "theta": 8})
        self.assertIn("grid_color", stage_settings_snapshot("plot", values))
        self.assertIn("polar_figure_size", stage_settings_snapshot("plot", values))
        self.assertIn("polar_figure_size", stage_settings_snapshot("datasheet", values))
        self.assertNotIn("unrelated", stage_settings_snapshot("plot", values))
        self.assertIn("vswr_ymax", stage_settings_snapshot("vswr", values))
        self.assertEqual(
            stage_settings_snapshot("compliance", values),
            {
                "compliance_fmin": 4.9,
                "compliance_fmax": 6.1,
                "compliance_omit_angle_range": "180-180",
                "compliance_sector_width": 90.0,
                "compliance_sector_center": 6.0,
            },
        )

    def test_stage_output_files_include_generated_plot_assets_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project_dir = Path(temp)
            beam_output = project_dir / "Demo.xlsx"
            polar_file = project_dir / "polar_combined" / "x.svg"
            polar_file.parent.mkdir()
            polar_file.write_text("svg", encoding="utf-8")
            plane_file = project_dir / "Demo-beamwidth-e-plane-h.svg"
            plane_file.write_text("svg", encoding="utf-8")

            files = stage_output_files(
                "plot",
                project_dir=project_dir,
                beam_output=beam_output,
                extract_output=project_dir / "extract.xlsx",
                datasheet_output=project_dir / "datasheet.pdf",
                vswr_output=project_dir / "vswr.svg",
            )

        names = {path.name for path in files}
        self.assertIn("Demo-gain.svg", names)
        self.assertIn("Demo-artifacts.json", names)
        self.assertIn("Demo-beamwidth-e-plane-h.svg", names)
        self.assertIn("x.svg", names)

    def test_stage_generated_directories_and_applicability(self) -> None:
        project_dir = Path("project")

        self.assertEqual(
            stage_generated_directories("beam", project_dir=project_dir),
            [
                project_dir / "radiaiton pattern files",
                project_dir / "ant_files",
                project_dir / "linkCalc",
                project_dir / "netsim",
            ],
        )
        self.assertEqual(
            stage_generated_directories("plot", project_dir=project_dir),
            [project_dir / "polar_combined", project_dir / "polar_single"],
        )
        self.assertTrue(stage_is_applicable("datasheet", has_enabled_ffs=True, has_touchstone=True, has_technical_data=True))
        self.assertFalse(stage_is_applicable("datasheet", has_enabled_ffs=True, has_touchstone=False, has_technical_data=True))
        self.assertTrue(stage_is_applicable("vswr", has_enabled_ffs=False, has_touchstone=True, has_technical_data=False))
        self.assertTrue(stage_is_applicable("compliance", has_enabled_ffs=True, has_touchstone=False, has_technical_data=False))

    def test_compliance_stage_has_output_and_version(self) -> None:
        project_dir = Path("project")
        compliance_output = project_dir / "demo-compliance.xlsx"
        files = stage_output_files(
            "compliance",
            project_dir=project_dir,
            beam_output=project_dir / "demo.xlsx",
            extract_output=project_dir / "extract.xlsx",
            datasheet_output=project_dir / "datasheet.pdf",
            vswr_output=project_dir / "vswr.svg",
            compliance_output=compliance_output,
        )

        self.assertEqual(
            files,
            [compliance_output, project_dir / "demo-compliance-evidence.pdf"],
        )
        self.assertEqual(stage_tool_versions("compliance")["compliance_rules"], 7)

    def test_stage_tool_versions_and_stale_detail(self) -> None:
        versions = stage_tool_versions("datasheet", plot_asset_style_version=3, datasheet_render_version=2)

        self.assertEqual(versions["plot_assets"], 3)
        self.assertEqual(versions["datasheet_render"], 2)
        self.assertIn("beam_data", versions)
        self.assertIn("extract_data", versions)
        self.assertIn("touchstone_parser", versions)
        self.assertIn("vswr_assets", versions)
        self.assertEqual(stage_stale_detail("plot", {"plot_assets": 2}, {"plot_assets": 3}), "App plot styling changed. Rerun Plots only.")
        self.assertEqual(stage_stale_detail("plot", {"plot_assets": 3}, {"plot_assets": 3}), "")


if __name__ == "__main__":
    unittest.main()
