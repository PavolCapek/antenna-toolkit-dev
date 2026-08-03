from __future__ import annotations

import unittest

from pipeline.preflight import collect_preflight_issues


class PipelinePreflightTests(unittest.TestCase):
    def test_compliance_does_not_require_shared_frequency_window(self) -> None:
        issues = collect_preflight_issues(
            stage_keys=["compliance"],
            has_active_project=True,
            enabled_ffs=["Input data/a.ffs"],
            missing_ffs_display=[],
            touchstone_selected=False,
            touchstone_ready=False,
            touchstone_display="",
            technical_data="",
            technical_data_is_url=False,
            technical_data_is_google_sheet=False,
            google_sheet_has_id=False,
            google_sheets_auth_configured=False,
            technical_data_exists=False,
            technical_data_display="",
            template_exists=False,
            template_display="",
            frequency_window_valid=False,
            beam_output_exists=False,
            extract_output_exists=False,
            extract_stage_stale=False,
            plot_output_exists=False,
            plot_stage_stale=False,
        )

        self.assertEqual(issues, [])

    def test_missing_project_blocks_with_single_message(self) -> None:
        issues = collect_preflight_issues(
            stage_keys=["beam"],
            has_active_project=False,
            enabled_ffs=[],
            missing_ffs_display=[],
            touchstone_selected=False,
            touchstone_ready=False,
            touchstone_display="",
            technical_data="",
            technical_data_is_url=False,
            technical_data_is_google_sheet=False,
            google_sheet_has_id=False,
            google_sheets_auth_configured=False,
            technical_data_exists=False,
            technical_data_display="",
            template_exists=False,
            template_display="Templates/default.pdf",
            frequency_window_valid=True,
            beam_output_exists=False,
            extract_output_exists=False,
            extract_stage_stale=False,
            plot_output_exists=False,
            plot_stage_stale=False,
        )
        self.assertEqual([issue.message for issue in issues], ["Create or select a project first."])

    def test_datasheet_checks_cover_technical_data_and_stale_outputs(self) -> None:
        issues = collect_preflight_issues(
            stage_keys=["datasheet"],
            has_active_project=True,
            enabled_ffs=["Input data/a.ffs"],
            missing_ffs_display=[],
            touchstone_selected=True,
            touchstone_ready=True,
            touchstone_display="Input data/a.s2p",
            technical_data="https://example.com/workbook.xlsx",
            technical_data_is_url=True,
            technical_data_is_google_sheet=False,
            google_sheet_has_id=False,
            google_sheets_auth_configured=False,
            technical_data_exists=False,
            technical_data_display="Input data/technical.xlsx",
            template_exists=False,
            template_display="Templates/missing.pdf",
            frequency_window_valid=True,
            beam_output_exists=True,
            extract_output_exists=True,
            extract_stage_stale=True,
            plot_output_exists=True,
            plot_stage_stale=True,
        )
        messages = [issue.message for issue in issues]
        self.assertIn("Use a Google Sheet link or a local workbook for Technical Data.", messages)
        self.assertIn("Select an available datasheet export style: Templates/missing.pdf", messages)
        self.assertIn("Rerun Extract before generating the datasheet.", messages)
        self.assertIn("Rerun Plots before generating the datasheet.", messages)


if __name__ == "__main__":
    unittest.main()
