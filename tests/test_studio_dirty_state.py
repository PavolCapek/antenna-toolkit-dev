from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog

import studio_support as qt_module
import antenna_toolkit_studio as studio_module
from antenna_toolkit_studio import ModernMainWindow, StepperField, read_ffs_frequency_headers
from studio_support import DEFAULT_COLOR_OPTIONS
from project_store import ProjectRecord, ProjectStore


class StudioDirtyStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.window = ModernMainWindow()
        self.window.project_store = ProjectStore(Path(self.temp_dir.name))
        self.window.preset_store = qt_module.PresetFileStore(Path(self.temp_dir.name) / "Presets")
        self.window.store.delete("ui_presets")
        self.window.store.set("active_preset", "")
        self.window.global_presets = {}
        self.window.global_active_preset = ""
        self.window.refresh_project_list(select_slug="")
        self.window._reset_to_default_state()
        self.project = ProjectRecord(
            name="Dirty Project",
            slug="dirty_project",
            settings={},
            presets={},
            active_preset="",
            run_state={},
        )
        self.window.project_store.save_project(self.project)
        self.window.refresh_project_list(select_slug=self.project.slug)
        self.app.processEvents()

    def tearDown(self) -> None:
        with mock.patch("antenna_toolkit_studio.QMessageBox.question", return_value=QMessageBox.Discard):
            self.window.close()
        self.temp_dir.cleanup()

    def test_starts_clean_and_save_button_tracks_project_changes(self) -> None:
        self.assertFalse(self.window.has_unsaved_project_changes())
        self.assertFalse(self.window.project_save_button.isEnabled())
        self.assertEqual(self.window.project_save_state_indicator.text(), "Project saved")

        self.window._add_ffs_files(["Input data/a.ffs"])
        self.app.processEvents()

        self.assertTrue(self.window.has_unsaved_project_changes())
        self.assertTrue(self.window.project_save_button.isEnabled())
        self.assertTrue(self.window.project_name.text().endswith("*"))
        self.assertEqual(self.window.project_save_state_indicator.text(), "Project has unsaved changes")

        self.window.save_project_changes()
        self.app.processEvents()

        self.assertFalse(self.window.has_unsaved_project_changes())
        self.assertFalse(self.window.project_save_button.isEnabled())
        self.assertFalse(self.window.project_name.text().endswith("*"))
        self.assertEqual(self.window.project_save_state_indicator.text(), "Project saved")

    def test_workspace_status_indicators_replace_summary_badges(self) -> None:
        self.assertFalse(hasattr(self.window, "count_badge"))
        self.assertFalse(hasattr(self.window, "preset_badge"))
        self.assertEqual(self.window.project_save_state_indicator.text(), "Project saved")
        self.assertEqual(self.window.preset_save_state_indicator.text(), "No preset selected")

        self.window.global_presets["Preset A"] = self.window.collect_preset_values()
        self.window.global_active_preset = "Preset A"
        self.window.project_active_preset = "Preset A"
        self.window.refresh_preset_list(select_name="Preset A")
        self.window.save_project_changes()
        self.app.processEvents()

        self.assertEqual(self.window.preset_save_state_indicator.text(), "Preset saved")

        self.window.beam_smooth.setValue(self.window.beam_smooth.value() + 1)
        self.app.processEvents()

        self.assertEqual(self.window.preset_save_state_indicator.text(), "Preset has unsaved changes")
        self.assertEqual(self.window.project_save_state_indicator.text(), "Project saved")

    def test_style_color_selectors_share_palette_with_previews(self) -> None:
        selectors = [
            self.window.plot_grid,
            self.window.plot_line1,
            self.window.plot_line2,
            self.window.polar_azimuth_line1.color_selector,
            self.window.polar_azimuth_line2.color_selector,
            self.window.polar_elevation_line1.color_selector,
            self.window.polar_elevation_line2.color_selector,
            self.window.beamwidth_3db_color,
            self.window.beamwidth_6db_color,
            self.window.beamwidth_10db_color,
        ]
        expected_colors = [color for _name, color in DEFAULT_COLOR_OPTIONS]

        for selector in selectors:
            combo = selector.combo
            self.assertEqual([combo.itemData(i) for i in range(combo.count() - 1)], expected_colors)
            self.assertTrue(all(not combo.itemIcon(i).isNull() for i in range(combo.count())))

    def test_active_global_preset_loads_clean_on_reset(self) -> None:
        preset = self.window.collect_preset_values()
        preset["smooth"] = 9
        self.window.global_presets["Startup Preset"] = preset
        self.window.global_active_preset = "Startup Preset"

        self.window._reset_to_default_state(clear_persisted_project=False)
        self.app.processEvents()

        self.assertEqual(self.window.current_preset_name(), "Startup Preset")
        self.assertEqual(self.window.beam_smooth.value(), 9)
        self.assertFalse(self.window.has_unsaved_preset_changes())
        self.assertEqual(self.window.preset_save_state_indicator.text(), "Preset saved")

    def test_legacy_preset_missing_default_keys_loads_clean(self) -> None:
        preset = self.window.collect_preset_values()
        preset.pop("cartesian_figure_width")
        preset.pop("cartesian_figure_height")
        preset.pop("polar_azimuth_line_1_color")
        preset["plot_line_1"] = preset["plot_line_1"].lower()
        self.window.global_presets["Legacy Preset"] = preset
        self.window.global_active_preset = "Legacy Preset"

        self.window._reset_to_default_state(clear_persisted_project=False)
        self.app.processEvents()

        self.assertFalse(self.window.has_unsaved_preset_changes())
        self.assertEqual(self.window.preset_save_state_indicator.text(), "Preset saved")

    def test_ffs_port_label_is_project_only_and_marks_dirty(self) -> None:
        ffs_path = Path(self.temp_dir.name) / "sample_H.ffs"
        ffs_path.write_text("ffs", encoding="utf-8")
        self.window._add_ffs_files([str(ffs_path)])
        self.app.processEvents()

        self.assertEqual(self.window.collect_ffs_items()[0]["port_label"], "H")
        self.window.save_project_changes()
        self.assertFalse(self.window.has_unsaved_project_changes())

        self.window.ffs_list.item(0).setSelected(True)
        self.app.processEvents()
        self.assertTrue(self.window.ffs_port_label_field.isEnabled())
        self.assertEqual(self.window.ffs_port_label_field.text(), "H")
        self.window.ffs_port_label_field.setText("Port 1")
        self.window.update_selected_ffs_port_label("Port 1")
        self.app.processEvents()

        self.assertTrue(self.window.has_unsaved_project_changes())
        self.assertEqual(self.window.collect_ffs_items()[0]["port_label"], "Port 1")
        self.assertNotIn("port_label", self.window.collect_preset_values())

        self.window.save_project_changes()
        loaded = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(loaded.ffs_items[0]["port_label"], "Port 1")

    def test_radiation_frequency_checklist_is_project_only_and_marks_datasheet_stale(self) -> None:
        ffs_path = Path(self.temp_dir.name) / "sample.ffs"
        ffs_path.write_text(
            "\n".join(
                [
                    "// #Frequencies",
                    "3",
                    "Radiated/Accepted/Stimulated Power",
                    "0.1",
                    "0.2",
                    "0.3",
                    "0.3e9",
                    "",
                    "0.1",
                    "0.2",
                    "0.3",
                    "1.5e9",
                    "",
                    "0.1",
                    "0.2",
                    "0.3",
                    "3.0e9",
                ]
            ),
            encoding="utf-8",
        )
        self.window._add_ffs_files([str(ffs_path)])
        self.window.refresh_radiation_frequency_list()
        self.app.processEvents()

        self.assertEqual(self.window.radiation_frequency_list.count(), 3)
        self.assertIsNone(self.window._project_radiation_frequencies)
        self.assertEqual(self.window.selected_radiation_frequencies(), [1.5])
        self.window.save_project_changes()
        self.assertNotIn("radiation_pattern_frequencies_ghz", self.window.collect_preset_values())
        initial_snapshot = self.window._current_stage_snapshot("datasheet")

        self.window.radiation_frequency_list.item(0).setCheckState(Qt.Checked)
        self.app.processEvents()

        self.assertTrue(self.window.has_unsaved_project_changes())
        self.assertEqual(self.window.selected_radiation_frequencies(), [0.3, 1.5])
        self.assertNotEqual(initial_snapshot["radiation_pattern_frequencies_ghz"], self.window._current_stage_snapshot("datasheet")["radiation_pattern_frequencies_ghz"])
        self.window.save_project_changes()
        loaded = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(loaded.radiation_pattern_frequencies_ghz, [0.3, 1.5])

    def test_run_preflight_reports_all_full_pipeline_blockers(self) -> None:
        missing_ffs = Path(self.temp_dir.name) / "missing.ffs"
        self.window._add_ffs_files([str(missing_ffs)])
        self.window.shared_fmin.setValue(6.0)
        self.window.shared_fmax.setValue(5.0)
        self.app.processEvents()

        messages = self.window._run_preflight_messages(["beam", "extract", "plot", "vswr", "datasheet"])

        self.assertTrue(any("missing .ffs" in message for message in messages))
        self.assertTrue(any("Touchstone" in message for message in messages))
        self.assertTrue(any("Technical Data" in message for message in messages))
        self.assertTrue(any("frequency window" in message for message in messages))
        self.assertGreaterEqual(len(messages), 4)

    def test_validate_project_shows_dry_run_report(self) -> None:
        with mock.patch("antenna_toolkit_studio.QMessageBox.information") as info:
            self.window.validate_project()

        info.assert_called_once()
        _parent, title, report = info.call_args.args
        self.assertEqual(title, "Validate Project")
        self.assertIn("Overall preflight", report)
        self.assertIn("Stage readiness", report)
        self.assertIn("Workbook", report)

    def test_run_button_shows_preflight_warning_without_starting(self) -> None:
        with mock.patch("antenna_toolkit_studio.QMessageBox.warning") as warning:
            self.window.run_beam()

        warning.assert_called_once()
        self.assertFalse(self.window.proc.queue)
        self.assertIsNone(self.window.proc.running_cmd)

    def test_needed_rerun_prefers_latest_failed_stage(self) -> None:
        self.window.project_run_state = {
            "stages": {
                "beam": {
                    "status": "failed",
                    "last_finished_at": "2026-04-30T10:00:00Z",
                },
                "plot": {
                    "status": "failed",
                    "last_finished_at": "2026-04-30T11:00:00Z",
                },
            }
        }

        self.assertEqual(self.window._latest_failed_stage_key(), "plot")

    def test_run_needed_outputs_queues_only_needed_stages(self) -> None:
        with (
            mock.patch.object(self.window, "_needed_rerun_stage_keys", return_value=["beam", "plot"]),
            mock.patch.object(self.window, "_run_preflight_passes", return_value=True),
            mock.patch.object(self.window, "_save_project_if_dirty"),
            mock.patch.object(self.window, "_enqueue_stage") as enqueue,
        ):
            self.window.run_needed_outputs()

        self.assertEqual([call.args[0] for call in enqueue.call_args_list], ["beam", "plot"])

    def test_clear_generated_files_refreshes_ready_stage_pills(self) -> None:
        ffs_path = Path(self.temp_dir.name) / "sample.ffs"
        ffs_path.write_text("ffs", encoding="utf-8")
        self.window._add_ffs_files([str(ffs_path)])
        self.window.save_project_changes()
        beam_output = self.window.deduced_beam_output()
        beam_output.parent.mkdir(parents=True, exist_ok=True)
        beam_output.write_text("workbook", encoding="utf-8")
        stage_state = self.window._stage_state("beam")
        stage_state["status"] = "success"
        stage_state["last_success_at"] = "2026-04-30T12:00:00Z"
        stage_state["snapshot"] = self.window._current_stage_snapshot("beam")

        self.window.refresh_derived_paths()
        self.app.processEvents()
        self.assertEqual(self.window.stage_chip_labels["beam"].text(), "Ready")

        with mock.patch("antenna_toolkit_studio.QMessageBox.question", return_value=QMessageBox.Yes):
            self.window.delete_all_outputs()
        self.app.processEvents()

        self.assertFalse(beam_output.exists())
        self.assertEqual(self.window.stage_chip_labels["beam"].text(), "Waiting")

    def test_needed_rerun_combines_failed_and_stale_with_skip_summary(self) -> None:
        self.window.project_run_state = {
            "stages": {
                "beam": {
                    "status": "success",
                    "last_success_at": "2026-04-30T09:00:00Z",
                    "snapshot": self.window._current_stage_snapshot("beam"),
                },
                "plot": {
                    "status": "failed",
                    "last_finished_at": "2026-04-30T11:00:00Z",
                },
                "vswr": {
                    "status": "success",
                    "last_success_at": "2026-04-30T09:00:00Z",
                    "snapshot": self.window._current_stage_snapshot("vswr"),
                },
            }
        }
        with (
            mock.patch.object(self.window, "_stale_stage_keys", return_value=["vswr"]),
            mock.patch.object(self.window, "_stage_is_applicable", return_value=True),
            mock.patch.object(self.window, "_stage_output_exists", return_value=True),
            mock.patch.object(self.window, "_stage_is_stale", side_effect=lambda key: key == "vswr"),
        ):
            self.assertEqual(self.window._needed_rerun_stage_keys(), ["plot", "vswr"])
            summary = self.window._recovery_plan_text()

        self.assertIn("failed: Plots", summary)
        self.assertIn("stale: VSWR", summary)
        self.assertIn("skip current outputs", summary)
        self.assertIn("Workbook", summary)

    def test_ffs_frequency_header_reader_uses_frequency_field_not_power_values(self) -> None:
        ffs_path = Path(self.temp_dir.name) / "cst.ffs"
        ffs_path.write_text(
            "\n".join(
                [
                    "// CST Farfield Source File",
                    "// #Frequencies",
                    "3",
                    "",
                    "// Radiated/Accepted/Stimulated Power , Frequency",
                    "4.378965e-01",
                    "4.499397e-01",
                    "5.000000e-01",
                    "4.700000e+09",
                    "",
                    "4.816199e-01",
                    "4.947527e-01",
                    "5.000000e-01",
                    "4.800000e+09",
                    "",
                    "4.644630e-01",
                    "4.721338e-01",
                    "5.000000e-01",
                    "4.900000e+09",
                ]
            ),
            encoding="utf-8",
        )

        self.assertEqual(read_ffs_frequency_headers(ffs_path), [4.7, 4.8, 4.9])

    def test_command_left_column_is_narrower_on_desktop_layout(self) -> None:
        self.window._compact_layout = False
        self.window._apply_layout_metrics()

        self.assertEqual(self.window.command_left.maximumWidth(), 390)
        self.assertEqual(self.window.command_panel.min_card_width, 360)

    def test_preset_changes_require_project_save(self) -> None:
        self.window.global_presets["Preset A"] = self.window.collect_preset_values()
        self.window.global_active_preset = "Preset A"
        self.window.project_active_preset = "Preset A"
        self.window._persist_global_presets()
        self.window.refresh_preset_list(select_name="Preset A")
        self.window._mark_project_dirty()
        self.app.processEvents()

        self.assertTrue(self.window.has_unsaved_project_changes())
        self.assertIn("Preset A", self.window.preset_store.load_presets())
        loaded_before_save = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(loaded_before_save.presets, {})
        self.assertEqual(loaded_before_save.active_preset, "")

        self.window.save_project_changes()
        self.app.processEvents()

        loaded_after_save = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(loaded_after_save.presets, {})
        self.assertEqual(loaded_after_save.active_preset, "Preset A")
        first_saved_settings = dict(loaded_after_save.settings)
        self.assertEqual(first_saved_settings, {})

        self.window.beam_smooth.setValue(self.window.beam_smooth.value() + 1)
        self.app.processEvents()

        self.assertFalse(self.window.has_unsaved_project_changes())
        self.assertTrue(self.window.has_unsaved_preset_changes())
        self.assertEqual(self.window.project_save_state_indicator.text(), "Project saved")
        self.assertEqual(self.window.preset_save_state_indicator.text(), "Preset has unsaved changes")

        self.window.cartesian_grid_line_width.setValue(1.4)
        self.window.polar_grid_line_width.setValue(1.1)
        self.window.cartesian_line_width.setValue(3.4)
        self.window.cartesian_figure_width.setValue(10.5)
        self.window.cartesian_figure_height.setValue(4.2)
        self.window.polar_line_width.setValue(2.8)
        self.window.cartesian_font_size.setValue(12.5)
        self.window.polar_font_size.setValue(11.5)
        self.window.cartesian_legend_font_size.setValue(14.0)
        self.window.polar_legend_font_size.setValue(13.0)
        self.window.polar_azimuth_line1.set_color("#101010")
        self.window.polar_azimuth_line1.set_style("dashed")
        self.window.polar_azimuth_line2.set_color("#202020")
        self.window.polar_azimuth_line2.set_style("solid")
        self.window.polar_elevation_line1.set_color("#303030")
        self.window.polar_elevation_line1.set_style("solid")
        self.window.polar_elevation_line2.set_color("#404040")
        self.window.polar_elevation_line2.set_style("dashed")
        self.window.pdf_metadata_author.setText("Custom Datasheet Author")
        self.app.processEvents()

        self.window.save_preset()
        self.app.processEvents()

        self.assertFalse(self.window.has_unsaved_project_changes())
        self.assertFalse(self.window.has_unsaved_preset_changes())
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["smooth"], self.window.beam_smooth.value())
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["cartesian_grid_line_width"], 1.4)
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["polar_grid_line_width"], 1.1)
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["cartesian_line_width"], 3.4)
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["cartesian_figure_width"], 10.5)
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["cartesian_figure_height"], 4.2)
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["polar_line_width"], 2.8)
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["cartesian_font_size"], 12.5)
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["polar_font_size"], 11.5)
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["cartesian_legend_font_size"], 14.0)
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["polar_legend_font_size"], 13.0)
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["polar_azimuth_line_1_color"], "#101010")
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["polar_azimuth_line_1_style"], "dashed")
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["polar_azimuth_line_2_color"], "#202020")
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["polar_azimuth_line_2_style"], "solid")
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["polar_elevation_line_1_color"], "#303030")
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["polar_elevation_line_1_style"], "solid")
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["polar_elevation_line_2_color"], "#404040")
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["polar_elevation_line_2_style"], "dashed")
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["datasheet_template"], "Datasheet - RFE.pdf")
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["pdf_metadata_author"], "Custom Datasheet Author")
        self.window.cartesian_figure_width.setValue(12.0)
        self.window.cartesian_figure_height.setValue(5.04)
        self.window.apply_preset_values(self.window.preset_store.load_presets()["Preset A"])
        self.assertEqual(self.window.cartesian_figure_width.value(), 10.5)
        self.assertEqual(self.window.cartesian_figure_height.value(), 4.2)
        self.assertEqual(self.window.polar_azimuth_line1.color(), "#101010")
        self.assertEqual(self.window.polar_azimuth_line1.style(), "dashed")
        self.assertEqual(self.window.polar_elevation_line2.color(), "#404040")
        self.assertEqual(self.window.polar_elevation_line2.style(), "dashed")
        loaded_before_second_save = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(loaded_before_second_save.presets, {})
        self.assertEqual(loaded_before_second_save.settings, first_saved_settings)
        self.assertEqual(loaded_before_second_save.active_preset, "Preset A")

    def test_document_tab_contains_preset_backed_author_field(self) -> None:
        tabs = [self.window.workflow_tabs.tabText(index) for index in range(self.window.workflow_tabs.count())]

        self.assertEqual(tabs, ["Inputs", "Processing", "Style", "Document", "Run"])
        self.assertGreaterEqual(self.window.datasheet_template_combo.findData("Datasheet - RFE.pdf"), 0)
        self.assertEqual(self.window.collect_preset_values()["datasheet_template"], "Datasheet - RFE.pdf")
        self.assertEqual(self.window.collect_preset_values()["pdf_metadata_author"], "RF elements")
        self.window.pdf_metadata_author.setText("Preset Author")
        self.assertEqual(self.window.collect_preset_values()["pdf_metadata_author"], "Preset Author")

    def test_datasheet_template_selection_is_preset_backed_and_marks_snapshot_stale(self) -> None:
        default_template = Path(self.temp_dir.name) / "Datasheet - RFE.pdf"
        alternate_template = Path(self.temp_dir.name) / "Alternate Style.pdf"
        default_template.write_text("default", encoding="utf-8")
        alternate_template.write_text("alternate", encoding="utf-8")
        options = [
            ("Datasheet - RFE.pdf", default_template),
            ("Alternate Style.pdf", alternate_template),
        ]
        with mock.patch.object(self.window, "_datasheet_template_options", return_value=options):
            self.window.refresh_datasheet_template_options("Datasheet - RFE.pdf")
            initial_snapshot = self.window._current_stage_snapshot("datasheet")
            self.window.refresh_datasheet_template_options("Alternate Style.pdf")
            changed_snapshot = self.window._current_stage_snapshot("datasheet")

        self.assertEqual(self.window.collect_preset_values()["datasheet_template"], "Alternate Style.pdf")
        self.assertNotEqual(initial_snapshot["settings"]["datasheet_template"], changed_snapshot["settings"]["datasheet_template"])
        self.assertNotEqual(initial_snapshot["template_pdf"]["path"], changed_snapshot["template_pdf"]["path"])

    def test_missing_datasheet_template_is_reported(self) -> None:
        self.window.apply_preset_values({"datasheet_template": "Missing Style.pdf"})
        self.app.processEvents()

        messages = self.window._validation_messages()

        self.assertTrue(any("Selected datasheet template is missing" in message for message in messages))

    def test_google_sheet_url_helpers_parse_supported_links(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/sheet123abc/edit#gid=42"

        self.assertTrue(studio_module.is_google_sheet_url(url))
        self.assertEqual(studio_module.extract_google_sheet_id(url), "sheet123abc")
        self.assertEqual(
            studio_module.google_sheet_export_url("sheet123abc"),
            "https://docs.google.com/spreadsheets/d/sheet123abc/export?format=xlsx",
        )

    def test_google_sheet_technical_data_source_is_saved_as_url(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/sheet123abc/edit#gid=0"

        self.window._set_technical_data(url)
        self.window.save_project_changes()
        loaded = self.window.project_store.load_project(self.project.slug)

        self.assertEqual(self.window.selected_technical_data(), url)
        self.assertEqual(loaded.technical_data_file, url)

    def test_google_sheet_without_sign_in_is_reported(self) -> None:
        self.window._set_technical_data("https://docs.google.com/spreadsheets/d/sheet123abc/edit")

        messages = self.window._validation_messages()

        self.assertTrue(any("Google Sheets sign-in is required" in message for message in messages))

    def test_google_sheet_cached_workbook_changes_datasheet_snapshot(self) -> None:
        self.window._set_technical_data("https://docs.google.com/spreadsheets/d/sheet123abc/edit")
        cache_path = self.window.technical_data_cache_path()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("one", encoding="utf-8")

        first_snapshot = self.window._current_stage_snapshot("datasheet")
        cache_path.write_text("larger content", encoding="utf-8")
        second_snapshot = self.window._current_stage_snapshot("datasheet")

        self.assertEqual(first_snapshot["technical_data"]["source"], self.window.selected_technical_data())
        self.assertNotEqual(
            first_snapshot["technical_data"]["cached_xlsx"]["size"],
            second_snapshot["technical_data"]["cached_xlsx"]["size"],
        )

    def test_old_plot_asset_snapshot_marks_plot_outputs_stale(self) -> None:
        ffs_path = Path(self.temp_dir.name) / "sample.ffs"
        ffs_path.write_text("ffs", encoding="utf-8")
        self.window._add_ffs_files([{"path": str(ffs_path), "enabled": True, "port_label": "Port 1"}])
        project_dir = self.window.project_results_dir()
        stem = self.window.deduced_beam_output().stem
        for suffix in (
            "gain",
            "gain-legend",
            "beamwidth",
            "beamwidth-legend",
            "beam-efficiency",
            "beam-efficiency-legend",
        ):
            path = project_dir / f"{stem}-{suffix}.svg"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("<svg />", encoding="utf-8")
        artifact_manifest = project_dir / f"{stem}-artifacts.json"
        artifact_manifest.write_text("{}", encoding="utf-8")

        legacy_snapshot = dict(self.window._current_stage_snapshot("plot"))
        legacy_snapshot.pop("tool_versions", None)
        self.window._stage_state("plot").update(
            {
                "status": "success",
                "last_success_at": "2026-04-24T12:00:00+00:00",
                "snapshot": legacy_snapshot,
            }
        )

        self.assertTrue(self.window._stage_is_stale("plot"))
        self.assertEqual(self.window._stage_stale_detail("plot"), "App plot styling changed. Rerun Plots only.")
        self.window.refresh_derived_paths()
        self.app.processEvents()
        self.assertEqual(self.window.stage_status_labels["plot"].text(), "App plot styling changed. Rerun Plots only.")

    def test_successful_plot_and_datasheet_snapshots_include_tool_versions(self) -> None:
        ffs_path = Path(self.temp_dir.name) / "sample.ffs"
        s2p_path = Path(self.temp_dir.name) / "sample.s2p"
        technical_path = Path(self.temp_dir.name) / "technical.xlsx"
        for path, content in (
            (ffs_path, "ffs"),
            (s2p_path, "s2p"),
            (technical_path, "xlsx"),
            (self.window.deduced_beam_output(), "beam"),
            (self.window.deduced_extract_output(), "extract"),
            (self.window.deduced_datasheet_output(), "pdf"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        self.window._add_ffs_files([{"path": str(ffs_path), "enabled": True, "port_label": "Port 1"}])
        self.window._set_touchstone(str(s2p_path))
        self.window._set_technical_data(str(technical_path))
        for path in self.window._stage_output_files("plot"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("<svg />", encoding="utf-8")

        plot_args = [studio_module.SCRIPT_PLOT]
        self.window.on_proc_step_started(plot_args, "plot.py")
        self.window.on_proc_step_finished(plot_args, 0, None)
        plot_snapshot = self.window._stage_state("plot")["snapshot"]

        self.assertEqual(
            plot_snapshot["tool_versions"]["plot_assets"],
            studio_module.PLOT_ASSET_STYLE_VERSION,
        )
        self.assertFalse(self.window._stage_is_stale("plot"))

        datasheet_args = [studio_module.SCRIPT_DATASHEET]
        self.window.on_proc_step_started(datasheet_args, "datasheet_pdf.py")
        self.window.on_proc_step_finished(datasheet_args, 0, None)
        datasheet_snapshot = self.window._stage_state("datasheet")["snapshot"]

        self.assertEqual(
            datasheet_snapshot["tool_versions"]["plot_assets"],
            studio_module.PLOT_ASSET_STYLE_VERSION,
        )
        self.assertEqual(
            datasheet_snapshot["tool_versions"]["datasheet_render"],
            studio_module.DATASHEET_RENDER_VERSION,
        )
        self.assertFalse(self.window._stage_is_stale("datasheet"))

    def test_prepare_technical_data_downloads_google_sheet_to_cached_workbook(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/sheet123abc/edit"
        cached_xlsx = Path(self.temp_dir.name) / "cached-google.xlsx"
        self.window._set_technical_data(url)

        with mock.patch.object(self.window, "download_google_sheet_technical_data", return_value=cached_xlsx) as download:
            result = self.window.prepare_technical_data_workbook()

        download.assert_called_once_with(url)
        self.assertEqual(result, str(cached_xlsx))

    def test_google_sign_in_always_allows_selecting_client_json(self) -> None:
        old_client = Path(self.temp_dir.name) / "old_client.json"
        new_client = Path(self.temp_dir.name) / "new_client.json"
        old_client.write_text("old", encoding="utf-8")
        new_client.write_text("new", encoding="utf-8")
        self.window.store.set(studio_module.GOOGLE_SHEETS_OAUTH_CLIENT_KEY, str(old_client))

        with (
            mock.patch("antenna_toolkit_studio.QFileDialog.getOpenFileName", return_value=(str(new_client), "JSON (*.json)")),
            mock.patch.object(self.window, "_ensure_google_sheets_credentials") as ensure_credentials,
        ):
            self.window.configure_google_sheet_credentials()

        ensure_credentials.assert_called_once_with(interactive=True)
        self.assertEqual(self.window.google_sheets_oauth_client_path(), new_client)

    def test_google_sign_in_cancel_reuses_existing_client_json(self) -> None:
        existing_client = Path(self.temp_dir.name) / "existing_client.json"
        existing_client.write_text("client", encoding="utf-8")
        self.window.store.set(studio_module.GOOGLE_SHEETS_OAUTH_CLIENT_KEY, str(existing_client))

        with (
            mock.patch("antenna_toolkit_studio.QFileDialog.getOpenFileName", return_value=("", "")),
            mock.patch.object(self.window, "_ensure_google_sheets_credentials") as ensure_credentials,
        ):
            self.window.configure_google_sheet_credentials()

        ensure_credentials.assert_called_once_with(interactive=True)
        self.assertEqual(self.window.google_sheets_oauth_client_path(), existing_client)

    def test_global_presets_remain_available_without_or_across_projects(self) -> None:
        self.window.global_presets["Preset A"] = self.window.collect_preset_values()
        self.window.global_active_preset = "Preset A"
        self.window.project_active_preset = "Preset A"
        self.window._persist_global_presets()
        self.window.refresh_preset_list(select_name="Preset A")
        self.window.save_project_changes()
        self.app.processEvents()

        self.window.project_combo.setCurrentIndex(0)
        self.app.processEvents()

        self.assertTrue(self.window.preset_combo.isEnabled())
        self.assertGreaterEqual(self.window.preset_combo.findData("Preset A"), 0)
        self.assertEqual(self.window.current_preset_name(), "Preset A")

        second = ProjectRecord(
            name="Second Project",
            slug="second_project",
            settings={},
            presets={},
            active_preset="",
            run_state={},
        )
        self.window.project_store.save_project(second)
        self.window.refresh_project_list(select_slug=second.slug)
        self.app.processEvents()

        self.assertEqual(self.window.active_project_slug, second.slug)
        self.assertGreaterEqual(self.window.preset_combo.findData("Preset A"), 0)
        self.assertEqual(self.window.current_preset_name(), "")
        self.assertEqual(self.window.project_store.load_project(second.slug).active_preset, "")
        self.assertEqual(self.window.project_store.load_project(second.slug).settings, {})

    def test_switching_projects_applies_each_projects_selected_preset(self) -> None:
        preset_a = dict(self.window.collect_preset_values())
        preset_a["smooth"] = 7
        preset_b = dict(self.window.collect_preset_values())
        preset_b["smooth"] = 11
        self.window.global_presets = {"Preset A": preset_a, "Preset B": preset_b}
        self.window.global_active_preset = "Preset A"
        self.window._persist_global_presets()

        project_a = ProjectRecord(name="Preset A Project", slug="preset_a_project", active_preset="Preset A")
        project_b = ProjectRecord(name="Preset B Project", slug="preset_b_project", active_preset="Preset B")
        self.window.project_store.save_project(project_a)
        self.window.project_store.save_project(project_b)

        self.window.refresh_project_list(select_slug=project_a.slug)
        self.app.processEvents()
        self.assertEqual(self.window.current_preset_name(), "Preset A")
        self.assertEqual(self.window.beam_smooth.value(), 7)

        self.window.refresh_project_list(select_slug=project_b.slug)
        self.app.processEvents()
        self.assertEqual(self.window.current_preset_name(), "Preset B")
        self.assertEqual(self.window.beam_smooth.value(), 11)

    def test_switching_presets_prompts_to_save_or_cancel_preset_changes(self) -> None:
        preset_a = dict(self.window.collect_preset_values())
        preset_b = dict(self.window.collect_preset_values())
        preset_a["smooth"] = 5
        preset_b["smooth"] = 11
        self.window.global_presets = {"Preset A": preset_a, "Preset B": preset_b}
        self.window.project_active_preset = "Preset A"
        self.window.global_active_preset = "Preset A"
        self.window._persist_global_presets()
        self.window.refresh_preset_list(select_name="Preset A")
        self.window.apply_preset_values(preset_a)
        self.window.save_project_changes()
        self.app.processEvents()

        self.window.beam_smooth.setValue(9)
        self.app.processEvents()
        self.assertTrue(self.window.has_unsaved_preset_changes())

        with mock.patch("antenna_toolkit_studio.QMessageBox.question", return_value=QMessageBox.Cancel):
            self.window.preset_combo.setCurrentIndex(self.window.preset_combo.findData("Preset B"))
        self.app.processEvents()

        self.assertEqual(self.window.current_preset_name(), "Preset A")
        self.assertEqual(self.window.beam_smooth.value(), 9)
        self.assertEqual(self.window.global_presets["Preset A"]["smooth"], 5)

        with mock.patch("antenna_toolkit_studio.QMessageBox.question", return_value=QMessageBox.Save):
            self.window.preset_combo.setCurrentIndex(self.window.preset_combo.findData("Preset B"))
        self.app.processEvents()

        self.assertEqual(self.window.global_presets["Preset A"]["smooth"], 9)
        self.assertEqual(self.window.current_preset_name(), "Preset B")
        self.assertEqual(self.window.beam_smooth.value(), 11)

    def test_switching_presets_batches_refresh_work(self) -> None:
        preset_a = dict(self.window.collect_preset_values())
        preset_b = dict(self.window.collect_preset_values())
        preset_b.update({
            "smooth": 11,
            "theta": 12.0,
            "smooth2": 9,
            "shared_xstep": 0.5,
            "gain_ymax": 18.0,
            "beamwidth_ymax": 140.0,
            "vswr_ymax": 5.0,
            "cartesian_line_width": 3.0,
            "polar_line_width": 3.0,
            "plot_line_1": "#123456",
            "plot_line_2": "#654321",
            "gain_legend_labels": "A,B",
        })
        self.window.global_presets = {"Preset A": preset_a, "Preset B": preset_b}
        self.window.project_active_preset = "Preset A"
        self.window.global_active_preset = "Preset A"
        self.window._persist_global_presets()
        self.window.refresh_preset_list(select_name="Preset A")
        self.window.apply_preset_values(preset_a)
        self.app.processEvents()

        with mock.patch.object(self.window, "refresh_derived_paths", wraps=self.window.refresh_derived_paths) as refresh:
            self.window.preset_combo.setCurrentIndex(self.window.preset_combo.findData("Preset B"))
            self.app.processEvents()

        self.assertEqual(self.window.current_preset_name(), "Preset B")
        self.assertEqual(self.window.beam_smooth.value(), 11)
        self.assertLessEqual(refresh.call_count, 2)

    def test_configuration_changes_debounce_refresh_work(self) -> None:
        with mock.patch.object(self.window, "refresh_derived_paths") as refresh:
            for _index in range(5):
                self.window.on_project_configuration_changed()

            self.assertEqual(refresh.call_count, 0)

            self.window.flush_derived_paths_refresh()

        self.assertEqual(refresh.call_count, 1)

    def test_switching_projects_can_save_dirty_preset_and_project(self) -> None:
        preset_a = dict(self.window.collect_preset_values())
        preset_a["smooth"] = 5
        self.window.global_presets = {"Preset A": preset_a}
        self.window.project_active_preset = "Preset A"
        self.window.global_active_preset = "Preset A"
        self.window._persist_global_presets()
        self.window.refresh_preset_list(select_name="Preset A")
        self.window.apply_preset_values(preset_a)
        self.window.save_project_changes()
        self.app.processEvents()

        second = ProjectRecord(name="Second Project", slug="second_project")
        self.window.project_store.save_project(second)
        self.window.refresh_project_list(select_slug=self.project.slug)
        self.window.beam_smooth.setValue(9)
        self.window._add_ffs_files(["Input data/a.ffs"])
        self.app.processEvents()

        with mock.patch("antenna_toolkit_studio.QMessageBox.question", side_effect=[QMessageBox.Save, QMessageBox.Save]):
            self.window.project_combo.setCurrentIndex(self.window.project_combo.findData(second.slug))
        self.app.processEvents()

        saved_first = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(self.window.global_presets["Preset A"]["smooth"], 9)
        self.assertEqual(saved_first.settings, {})
        self.assertEqual(saved_first.ffs_items[0]["path"], "Input data/a.ffs")
        self.assertEqual(self.window.active_project_slug, second.slug)

    def test_exit_prompt_can_save_or_cancel_dirty_project(self) -> None:
        self.window._add_ffs_files(["Input data/a.ffs"])
        self.app.processEvents()

        with mock.patch("antenna_toolkit_studio.QMessageBox.question", return_value=QMessageBox.Save):
            confirmed = self.window._confirm_pending_project_changes("exiting")
        self.assertTrue(confirmed)
        self.assertFalse(self.window.has_unsaved_project_changes())

        self.window._add_ffs_files(["Input data/b.ffs"])
        self.app.processEvents()

        with mock.patch("antenna_toolkit_studio.QMessageBox.question", return_value=QMessageBox.Cancel):
            confirmed = self.window._confirm_pending_project_changes("exiting")
        self.assertFalse(confirmed)
        self.assertTrue(self.window.has_unsaved_project_changes())

    def test_helper_buttons_are_not_tab_stops(self) -> None:
        beam_field = next(field for field in self.window.findChildren(StepperField) if field.spinbox is self.window.beam_smooth)
        self.assertEqual(beam_field.minus.focusPolicy(), Qt.NoFocus)
        self.assertEqual(beam_field.plus.focusPolicy(), Qt.NoFocus)
        self.assertIs(beam_field.focusProxy(), beam_field.spinbox)

        self.assertEqual(self.window.plot_grid.prev_btn.focusPolicy(), Qt.NoFocus)
        self.assertEqual(self.window.plot_grid.next_btn.focusPolicy(), Qt.NoFocus)
        self.assertIs(self.window.plot_grid.focusProxy(), self.window.plot_grid.combo)

    def test_restore_geometry_uses_saved_window_size(self) -> None:
        self.window.store.set("window_width", 1234)
        self.window.store.set("window_height", 777)
        self.window.resize(900, 900)

        self.window._restore_geometry()
        self.app.processEvents()

        self.assertEqual(self.window.width(), 1234)
        self.assertEqual(self.window.height(), 777)

    def test_startup_restores_last_active_project(self) -> None:
        temp_root = tempfile.TemporaryDirectory()
        root = Path(temp_root.name)
        state_path = root / ".nova_qt_studio_state.json"
        project_store = ProjectStore(root)
        project = ProjectRecord(
            name="Restored Project",
            slug="restored_project",
            settings={},
            presets={},
            active_preset="",
            run_state={},
        )
        project_store.save_project(project)
        state_path.write_text(json.dumps({"active_project": project.slug, "theme": "dark"}), encoding="utf-8")

        with (
            mock.patch.object(studio_module, "THIS_DIR", root),
            mock.patch.object(studio_module, "STATE_FILE", state_path),
        ):
            restored = studio_module.ModernMainWindow()
            self.app.processEvents()
            try:
                self.assertEqual(restored.active_project_slug, project.slug)
                self.assertEqual(restored.project_combo.currentData(), project.slug)
            finally:
                with mock.patch("antenna_toolkit_studio.QMessageBox.question", return_value=QMessageBox.Discard):
                    restored.close()
        temp_root.cleanup()

    def test_state_file_migrates_from_legacy_workspace_location(self) -> None:
        temp_root = tempfile.TemporaryDirectory()
        appdata_root = tempfile.TemporaryDirectory()
        legacy_path = Path(temp_root.name) / ".nova_qt_studio_state.json"
        legacy_path.write_text(json.dumps({"ui_presets": {"Preset A": {"smooth": 7}}}), encoding="utf-8")

        with mock.patch.dict(os.environ, {"APPDATA": appdata_root.name}, clear=False):
            state_path = qt_module.resolve_state_file(".nova_qt_studio_state.json", legacy_path)

        self.assertTrue(state_path.exists())
        store = qt_module.Persist(state_path)
        with mock.patch.object(qt_module, "THIS_DIR", Path(temp_root.name)):
            preset_store = qt_module.PresetFileStore(
                qt_module.preset_storage_dir(state_path),
                qt_module.legacy_preset_storage_dirs(state_path),
            )
            migrated = preset_store.migrate_from_state(store)

        self.assertEqual(migrated["Preset A"]["smooth"], 7)
        self.assertEqual(store.get("ui_presets", {}), {})

        temp_root.cleanup()
        appdata_root.cleanup()

    def test_theme_selector_supports_additional_themes_and_persists_selection(self) -> None:
        self.assertEqual(self.window.theme_selector.count(), 5)
        theme_index = self.window.theme_selector.findData("sage")

        self.assertGreaterEqual(theme_index, 0)

        self.window.theme_selector.setCurrentIndex(theme_index)
        self.app.processEvents()

        self.assertEqual(self.window.theme, "sage")
        self.assertEqual(self.window.store.get("theme"), "sage")
        self.assertEqual(self.window.theme_selector.currentText(), "Sage")
        self.assertGreaterEqual(QApplication.font().pointSizeF(), 10.0)

    def test_compact_layout_collapses_secondary_command_details(self) -> None:
        with (
            mock.patch.object(self.window, "_screen_available_height", return_value=1200),
            mock.patch.object(self.window, "_available_window_width", return_value=1300),
        ):
            self.window._update_layout_mode(force=True)
        self.app.processEvents()

        self.assertTrue(self.window._compact_layout)
        self.assertTrue(self.window.brand_subtitle.isHidden())
        self.assertTrue(self.window.run_help_label.isHidden())
        self.assertFalse(self.window.pipeline_details_toggle.isHidden())
        self.assertTrue(self.window.pipeline_details.isHidden())
        self.assertEqual(self.window.ffs_list.minimumHeight(), 140)
        self.assertGreaterEqual(QApplication.font().pointSizeF(), 10.0)

        with (
            mock.patch.object(self.window, "_screen_available_height", return_value=1440),
            mock.patch.object(self.window, "_available_window_width", return_value=1600),
        ):
            self.window._update_layout_mode(force=True)
        self.app.processEvents()

        self.assertFalse(self.window._compact_layout)
        self.assertFalse(self.window.brand_subtitle.isHidden())
        self.assertFalse(self.window.run_help_label.isHidden())
        self.assertTrue(self.window.pipeline_details_toggle.isHidden())
        self.assertFalse(self.window.pipeline_details.isHidden())
        self.assertEqual(self.window.ffs_list.minimumHeight(), 170)

    def test_pipeline_buttons_include_recovery_action(self) -> None:
        labels = [button.text() for button in self.window.hero_actions._buttons]

        self.assertEqual(labels, ["Run Full Pipeline", "Run Needed Only", "Validate Project", "Clear Generated Files"])
        self.assertFalse(self.window.btn_run_needed.isVisible())

    def test_pipeline_stage_list_gates_actions_by_output_state(self) -> None:
        self.assertEqual(set(self.window.stage_open_buttons.keys()), {"beam", "extract", "datasheet", "plot", "vswr"})
        self.assertEqual(set(self.window.stage_timestamp_labels.keys()), {"beam", "extract", "datasheet", "plot", "vswr"})
        self.assertEqual(set(self.window.stage_chip_labels.keys()), {"beam", "extract", "datasheet", "plot", "vswr"})
        self.assertEqual(set(self.window.stage_more_buttons.keys()), {"beam", "extract", "datasheet", "plot", "vswr"})

        with (
            mock.patch.object(self.window, "_stage_output_exists", return_value=False),
            mock.patch.object(self.window, "_stage_output_any_exists", return_value=False),
            mock.patch.object(self.window, "_stage_is_applicable", return_value=True),
        ):
            self.window.refresh_derived_paths()
            self.app.processEvents()
            self.assertTrue(all(button.isHidden() for button in self.window.stage_open_buttons.values()))
            self.assertTrue(all(button.isEnabled() for button in self.window.stage_rerun_buttons.values()))
            self.assertTrue(all(not button.isHidden() for button in self.window.stage_rerun_buttons.values()))
            self.assertTrue(all(not button.isHidden() for button in self.window.stage_more_buttons.values()))
            self.assertTrue(all(not button.isEnabled() for button in self.window.stage_more_buttons.values()))
            self.assertTrue(all(not action.isEnabled() for action in self.window.stage_reveal_actions.values()))
            self.assertTrue(all(not action.isEnabled() for action in self.window.stage_delete_actions.values()))

        with (
            mock.patch.object(self.window, "_stage_output_exists", side_effect=lambda stage_key: stage_key == "beam"),
            mock.patch.object(self.window, "_stage_output_any_exists", side_effect=lambda stage_key: stage_key == "beam"),
            mock.patch.object(self.window, "_stage_is_applicable", return_value=True),
        ):
            self.window.refresh_derived_paths()
            self.app.processEvents()
            self.assertFalse(self.window.stage_open_buttons["beam"].isHidden())
            self.assertTrue(self.window.stage_open_buttons["beam"].isEnabled())
            self.assertTrue(self.window.stage_more_buttons["beam"].isEnabled())
            self.assertTrue(self.window.stage_reveal_actions["beam"].isEnabled())
            self.assertTrue(self.window.stage_delete_actions["beam"].isEnabled())
            self.assertTrue(self.window.stage_open_buttons["extract"].isHidden())
            self.assertFalse(self.window.stage_more_buttons["extract"].isEnabled())
            self.assertFalse(self.window.stage_reveal_actions["extract"].isEnabled())
            self.assertFalse(self.window.stage_delete_actions["extract"].isEnabled())
            self.assertTrue(self.window.stage_open_buttons["datasheet"].isHidden())
            self.assertTrue(self.window.stage_open_buttons["plot"].isHidden())
            self.assertTrue(self.window.stage_open_buttons["vswr"].isHidden())

        with (
            mock.patch.object(self.window, "_stage_output_exists", return_value=False),
            mock.patch.object(self.window, "_stage_output_any_exists", return_value=False),
            mock.patch.object(self.window, "_stage_is_applicable", side_effect=lambda stage_key: stage_key != "vswr"),
        ):
            self.window.refresh_derived_paths()
            self.app.processEvents()
            self.assertTrue(self.window.stage_rerun_buttons["vswr"].isHidden())
            self.assertTrue(self.window.stage_more_buttons["vswr"].isHidden())
            self.assertEqual(self.window.stage_status_labels["vswr"].text(), "Not configured for this project.")
            self.assertEqual(self.window.stage_timestamp_labels["vswr"].text(), "Generated: not applicable")
            self.assertEqual(self.window.stage_chip_labels["vswr"].text(), "Off")

    def test_run_full_queues_datasheet_stage(self) -> None:
        ffs_path = Path(self.temp_dir.name) / "sample.ffs"
        s2p_path = Path(self.temp_dir.name) / "sample.s2p"
        technical_data_path = Path(self.temp_dir.name) / "technical.xlsx"
        ffs_path.write_text(
            "// #Frequencies\n2\nRadiated/Accepted/Stimulated Power\n0.1\n0.2\n0.3\n4.9e9\n\n0.1\n0.2\n0.3\n6.0e9\n",
            encoding="utf-8",
        )
        s2p_path.write_text("s2p", encoding="utf-8")
        technical_data_path.write_text("xlsx", encoding="utf-8")
        self.window._add_ffs_files([{"path": str(ffs_path), "enabled": True, "port_label": "Port 1"}])
        self.window.refresh_radiation_frequency_list()
        self.window._set_radiation_frequency_selection([4.9, 6.0])
        self.window._set_touchstone(str(s2p_path))
        self.window._set_technical_data(str(technical_data_path))
        self.window.pdf_metadata_author.setText("Pipeline Author")
        self.window.cartesian_figure_width.setValue(9.75)
        self.window.cartesian_figure_height.setValue(4.5)
        self.window.polar_figure_size.setValue(7.75)
        self.window.polar_azimuth_line1.set_color("#111111")
        self.window.polar_azimuth_line1.set_style("solid")
        self.window.polar_azimuth_line2.set_color("#222222")
        self.window.polar_azimuth_line2.set_style("dashed")
        self.window.polar_elevation_line1.set_color("#333333")
        self.window.polar_elevation_line1.set_style("dashed")
        self.window.polar_elevation_line2.set_color("#444444")
        self.window.polar_elevation_line2.set_style("solid")
        self.app.processEvents()

        queued: list[str] = []
        queued_args: dict[str, list[str]] = {}

        with (
            mock.patch.object(self.window, "_save_project_if_dirty"),
            mock.patch.object(
                self.window,
                "_enqueue_stage",
                side_effect=lambda stage_key, args: (queued.append(stage_key), queued_args.setdefault(stage_key, args)),
            ),
        ):
            self.window.run_full()

        self.assertEqual(queued, ["beam", "extract", "plot", "vswr", "datasheet"])
        self.assertIn("--beamwidth-db-colors", queued_args["plot"])
        self.assertEqual(queued_args["plot"][queued_args["plot"].index("--cartesian-figure-width") + 1], "9.75")
        self.assertEqual(queued_args["plot"][queued_args["plot"].index("--cartesian-figure-height") + 1], "4.5")
        self.assertEqual(queued_args["plot"][queued_args["plot"].index("--polar-figure-size") + 1], "7.75")
        self.assertEqual(queued_args["plot"][queued_args["plot"].index("--polar-line-colors") + 1], "#111111,#222222,#333333,#444444")
        self.assertEqual(queued_args["plot"][queued_args["plot"].index("--polar-line-styles") + 1], "solid,dashed,dashed,solid")
        self.assertIn("--polar-port-labels-json", queued_args["plot"])
        plot_port_labels = json.loads(queued_args["plot"][queued_args["plot"].index("--polar-port-labels-json") + 1])
        self.assertIn("sample", plot_port_labels)
        self.assertEqual(plot_port_labels["sample"], "Port 1")
        self.assertEqual(queued_args["vswr"][queued_args["vswr"].index("--cartesian-figure-width") + 1], "9.75")
        self.assertEqual(queued_args["vswr"][queued_args["vswr"].index("--cartesian-figure-height") + 1], "4.5")
        self.assertIn("--template", queued_args["datasheet"])
        self.assertEqual(Path(queued_args["datasheet"][queued_args["datasheet"].index("--template") + 1]).name, "Datasheet - RFE.pdf")
        self.assertIn("--metadata-author", queued_args["datasheet"])
        self.assertEqual(queued_args["datasheet"][queued_args["datasheet"].index("--metadata-author") + 1], "Pipeline Author")
        self.assertEqual(queued_args["datasheet"][queued_args["datasheet"].index("--cartesian-figure-width") + 1], "9.75")
        self.assertEqual(queued_args["datasheet"][queued_args["datasheet"].index("--cartesian-figure-height") + 1], "4.5")
        self.assertEqual(queued_args["datasheet"][queued_args["datasheet"].index("--polar-figure-size") + 1], "7.75")
        self.assertEqual(queued_args["datasheet"][queued_args["datasheet"].index("--radiation-frequencies-ghz") + 1], "4.9,6")

    def test_run_plot_passes_beamwidth_db_colors(self) -> None:
        beam_output = self.window.deduced_beam_output()
        beam_output.parent.mkdir(parents=True, exist_ok=True)
        beam_output.write_text("xlsx", encoding="utf-8")
        ffs_path = Path(self.temp_dir.name) / "plot_sample.ffs"
        ffs_path.write_text("ffs", encoding="utf-8")
        self.window._add_ffs_files([{"path": str(ffs_path), "enabled": True, "port_label": "+45"}])
        self.window.beamwidth_3db_color.set_color("#aa0000")
        self.window.beamwidth_6db_color.set_color("#777777")
        self.window.beamwidth_10db_color.set_color("#111111")
        self.window.cartesian_figure_width.setValue(9.25)
        self.window.cartesian_figure_height.setValue(3.75)
        self.window.polar_figure_size.setValue(6.5)
        self.window.polar_azimuth_line1.set_color("#121212")
        self.window.polar_azimuth_line1.set_style("dashed")
        self.window.polar_azimuth_line2.set_color("#232323")
        self.window.polar_azimuth_line2.set_style("solid")
        self.window.polar_elevation_line1.set_color("#343434")
        self.window.polar_elevation_line1.set_style("solid")
        self.window.polar_elevation_line2.set_color("#454545")
        self.window.polar_elevation_line2.set_style("dashed")
        self.app.processEvents()

        queued: list[str] = []
        queued_args: dict[str, list[str]] = {}

        with (
            mock.patch.object(self.window, "_save_project_if_dirty"),
            mock.patch.object(
                self.window,
                "_enqueue_stage",
                side_effect=lambda stage_key, args: (queued.append(stage_key), queued_args.setdefault(stage_key, args)),
            ),
        ):
            self.window.run_plot()

        self.assertEqual(queued, ["plot"])
        plot_args = queued_args["plot"]
        self.assertIn("--beamwidth-db-colors", plot_args)
        self.assertEqual(
            plot_args[plot_args.index("--beamwidth-db-colors") + 1],
            "#aa0000,#777777,#111111",
        )
        self.assertEqual(plot_args[plot_args.index("--cartesian-figure-width") + 1], "9.25")
        self.assertEqual(plot_args[plot_args.index("--cartesian-figure-height") + 1], "3.75")
        self.assertEqual(plot_args[plot_args.index("--polar-figure-size") + 1], "6.5")
        self.assertEqual(plot_args[plot_args.index("--polar-line-colors") + 1], "#121212,#232323,#343434,#454545")
        self.assertEqual(plot_args[plot_args.index("--polar-line-styles") + 1], "dashed,solid,solid,dashed")
        self.assertIn("--polar-port-labels-json", plot_args)
        port_labels = json.loads(plot_args[plot_args.index("--polar-port-labels-json") + 1])
        self.assertEqual(port_labels["plot_sample"], "+45")
        snapshot = self.window._stage_settings_snapshot("plot")
        self.assertEqual(snapshot["polar_figure_size"], 6.5)
        self.assertEqual(snapshot["polar_azimuth_line_1_color"], "#121212")
        self.assertEqual(snapshot["polar_elevation_line_2_style"], "dashed")
        self.assertEqual(self.window._current_stage_snapshot("plot")["ffs_items"][0]["port_label"], "+45")

    def test_run_full_uses_cached_google_sheet_workbook_for_datasheet(self) -> None:
        ffs_path = Path(self.temp_dir.name) / "sample.ffs"
        s2p_path = Path(self.temp_dir.name) / "sample.s2p"
        cached_xlsx = Path(self.temp_dir.name) / "cached-google.xlsx"
        ffs_path.write_text("ffs", encoding="utf-8")
        s2p_path.write_text("s2p", encoding="utf-8")
        cached_xlsx.write_text("xlsx", encoding="utf-8")
        self.window._add_ffs_files([str(ffs_path)])
        self.window._set_touchstone(str(s2p_path))
        self.window._set_technical_data("https://docs.google.com/spreadsheets/d/sheet123abc/edit")
        self.app.processEvents()

        queued: list[str] = []
        queued_args: dict[str, list[str]] = {}

        with (
            mock.patch.object(self.window, "_save_project_if_dirty"),
            mock.patch.object(self.window, "prepare_technical_data_workbook", return_value=str(cached_xlsx)),
            mock.patch.object(
                self.window,
                "_enqueue_stage",
                side_effect=lambda stage_key, args: (queued.append(stage_key), queued_args.setdefault(stage_key, args)),
            ),
        ):
            self.window.run_full()

        self.assertEqual(queued[-1], "datasheet")
        self.assertEqual(
            queued_args["datasheet"][queued_args["datasheet"].index("--technical-data-workbook") + 1],
            str(cached_xlsx),
        )

    def test_run_datasheet_uses_cached_google_sheet_workbook(self) -> None:
        ffs_path = Path(self.temp_dir.name) / "sample.ffs"
        s2p_path = Path(self.temp_dir.name) / "sample.s2p"
        cached_xlsx = Path(self.temp_dir.name) / "cached-google.xlsx"
        ffs_path.write_text(
            "// #Frequencies\n1\nRadiated/Accepted/Stimulated Power\n0.1\n0.2\n0.3\n0.3e9\n",
            encoding="utf-8",
        )
        s2p_path.write_text("s2p", encoding="utf-8")
        cached_xlsx.write_text("xlsx", encoding="utf-8")
        self.window.deduced_extract_output().parent.mkdir(parents=True, exist_ok=True)
        self.window.deduced_extract_output().write_text("extract", encoding="utf-8")
        self.window._add_ffs_files([str(ffs_path)])
        self.window.refresh_radiation_frequency_list()
        self.window._set_radiation_frequency_selection([0.3])
        self.window._set_touchstone(str(s2p_path))
        self.window._set_technical_data("https://docs.google.com/spreadsheets/d/sheet123abc/edit")
        self.app.processEvents()

        queued_args: dict[str, list[str]] = {}

        with (
            mock.patch.object(self.window, "_stage_is_stale", return_value=False),
            mock.patch.object(self.window, "_stage_output_exists", return_value=True),
            mock.patch.object(self.window, "_save_project_if_dirty"),
            mock.patch.object(self.window, "prepare_technical_data_workbook", return_value=str(cached_xlsx)),
            mock.patch.object(
                self.window,
                "_enqueue_stage",
                side_effect=lambda stage_key, args: queued_args.setdefault(stage_key, args),
            ),
        ):
            self.window.run_datasheet()

        self.assertEqual(
            queued_args["datasheet"][queued_args["datasheet"].index("--technical-data-workbook") + 1],
            str(cached_xlsx),
        )
        self.assertEqual(queued_args["datasheet"][queued_args["datasheet"].index("--radiation-frequencies-ghz") + 1], "0.3")

    def test_running_progress_updates_summary_and_stage_rows(self) -> None:
        with mock.patch.object(self.window.proc, "enqueue"):
            self.window._enqueue_stage("beam", ["python", "beamwidth_xlsx.py"])
            self.window._enqueue_stage("extract", ["python", "extract_data_xlsx.py"])

        self.window.on_proc_step_started(["beamwidth_xlsx.py"], "python beamwidth_xlsx.py")
        self.window.on_proc_progress(
            {"stage": "beam", "current": 2, "total": 5, "label": "Processing sample.ffs"}
        )
        self.app.processEvents()

        self.assertEqual(self.window.stage_status_labels["beam"].text(), "Running (2/5 | Processing sample.ffs)")
        self.assertEqual(self.window.stage_timestamp_labels["beam"].text(), "Generated: in progress")
        self.assertEqual(self.window.stage_chip_labels["beam"].text(), "Running")
        self.assertEqual(self.window.busy.maximum(), 100)
        self.assertEqual(self.window.busy.value(), 20)
        self.assertFalse(self.window.btn_cancel.isHidden())
        self.assertFalse(self.window.readiness_action.isVisible())

    def test_stage_chip_styles_use_distinct_semantic_colors(self) -> None:
        ready_style = self.window._stage_chip_style("ready")
        running_style = self.window._stage_chip_style("running")
        failed_style = self.window._stage_chip_style("failed")
        muted_style = self.window._stage_chip_style("muted")

        self.assertIn("rgba(47, 158, 91", ready_style)
        self.assertIn("rgba(47, 128, 237", running_style)
        self.assertIn("rgba(214, 69, 69", failed_style)
        self.assertIn("rgba(102, 117, 138", muted_style)
        self.assertNotEqual(ready_style, running_style)

    def test_delete_all_outputs_action_only_clears_generated_artifacts(self) -> None:
        beam_output = self.window.deduced_beam_output()
        extract_output = self.window.deduced_extract_output()
        datasheet_output = self.window.deduced_datasheet_output()
        vswr_output = self.window.deduced_vswr_output()
        project_dir = self.window.project_results_dir()
        project_file = self.window.current_project().project_file(Path(self.temp_dir.name))
        ant_output = project_dir / "ant_files" / f"{beam_output.stem}-5_8GHz.ant"
        polar_combined_output = project_dir / "polar_combined" / f"{beam_output.stem}-polar-5_8ghz-combined.svg"
        polar_combined_legend = project_dir / "polar_combined" / f"{beam_output.stem}-polar-5_8ghz-combined-legend.svg"
        polar_az_output = project_dir / "polar_single" / "azimuth" / f"{beam_output.stem}-polar-azimuth-5_8ghz.svg"
        polar_el_output = project_dir / "polar_single" / "elevation" / f"{beam_output.stem}-polar-elevation-5_8ghz.svg"
        polar_e_plane_output = project_dir / "polar_single" / "e-plane" / f"{beam_output.stem}-polar-e-plane-5_8ghz.svg"
        polar_h_plane_output = project_dir / "polar_single" / "h-plane" / f"{beam_output.stem}-polar-h-plane-5_8ghz.svg"
        beamwidth_e_plane_output = project_dir / f"{beam_output.stem}-beamwidth-e-plane-h.svg"
        beamwidth_e_plane_legend = project_dir / f"{beam_output.stem}-beamwidth-e-plane-h-legend.svg"
        artifact_manifest = project_dir / f"{beam_output.stem}-artifacts.json"
        project_dir.mkdir(parents=True, exist_ok=True)
        for path in (
            beam_output,
            extract_output,
            datasheet_output,
            vswr_output,
            vswr_output.with_name(f"{vswr_output.stem}-legend{vswr_output.suffix}"),
            project_dir / f"{beam_output.stem}-gain.svg",
            project_dir / f"{beam_output.stem}-gain-legend.svg",
            project_dir / f"{beam_output.stem}-beamwidth.svg",
            project_dir / f"{beam_output.stem}-beamwidth-legend.svg",
            beamwidth_e_plane_output,
            beamwidth_e_plane_legend,
            project_dir / f"{beam_output.stem}-beam-efficiency.svg",
            project_dir / f"{beam_output.stem}-beam-efficiency-legend.svg",
            ant_output,
            polar_combined_output,
            polar_combined_legend,
            polar_az_output,
            polar_el_output,
            polar_e_plane_output,
            polar_h_plane_output,
            artifact_manifest,
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("generated", encoding="utf-8")
        untouched = project_dir / "notes.txt"
        untouched.write_text("keep", encoding="utf-8")

        self.window.refresh_derived_paths()
        self.app.processEvents()
        self.assertTrue(self.window.project_delete_outputs_action.isEnabled())
        self.assertTrue(self.window.btn_clear_outputs.isEnabled())

        with mock.patch("antenna_toolkit_studio.QMessageBox.question", return_value=QMessageBox.Yes):
            self.window.delete_all_outputs()
        self.app.processEvents()

        self.assertFalse(beam_output.exists())
        self.assertFalse(extract_output.exists())
        self.assertFalse(datasheet_output.exists())
        self.assertFalse(vswr_output.exists())
        self.assertFalse(ant_output.exists())
        self.assertFalse(polar_combined_output.exists())
        self.assertFalse(polar_combined_legend.exists())
        self.assertFalse(polar_az_output.exists())
        self.assertFalse(polar_el_output.exists())
        self.assertFalse(polar_e_plane_output.exists())
        self.assertFalse(polar_h_plane_output.exists())
        self.assertFalse(beamwidth_e_plane_output.exists())
        self.assertFalse(beamwidth_e_plane_legend.exists())
        self.assertFalse(artifact_manifest.exists())
        self.assertFalse((project_dir / "ant_files").exists())
        self.assertFalse((project_dir / "polar_combined").exists())
        self.assertFalse((project_dir / "polar_single").exists())
        self.assertTrue(project_file.exists())
        self.assertTrue(untouched.exists())
        self.assertEqual(self.window._stage_state("beam").get("status"), "waiting")
        self.assertFalse(self.window.project_delete_outputs_action.isEnabled())
        self.assertFalse(self.window.btn_clear_outputs.isEnabled())

    def test_cancel_run_clears_live_progress(self) -> None:
        with mock.patch.object(self.window.proc, "enqueue"):
            self.window._enqueue_stage("beam", ["python", "beamwidth_xlsx.py"])

        self.window.proc.running_cmd = ["python", "beamwidth_xlsx.py"]
        self.window.on_proc_step_started(["beamwidth_xlsx.py"], "python beamwidth_xlsx.py")
        self.window.on_proc_progress(
            {"stage": "beam", "current": 1, "total": 2, "label": "Processing sample.ffs"}
        )

        with mock.patch.object(self.window.proc, "stop"):
            self.window.cancel_run()
        self.app.processEvents()

        self.assertEqual(self.window._live_run_total_stages, 0)
        self.assertEqual(self.window._live_run_completed_stages, 0)
        self.assertEqual(self.window._stage_state("beam").get("status"), "cancelled")
        self.assertNotIn("running", self.window.stage_status_labels["beam"].text().lower())
        self.assertTrue(self.window.btn_cancel.isHidden())

    def test_create_project_starts_blank_until_user_saves_inputs(self) -> None:
        self.window._add_ffs_files(["Input data/a.ffs"])
        self.window._set_touchstone("Input data/a.s2p")
        self.window._set_technical_data("Input data/tech.xlsx")
        self.window.beam_smooth.setValue(11)
        self.window.save_project_changes()
        self.app.processEvents()

        with (
            mock.patch("antenna_toolkit_studio.ProjectDialog.exec", return_value=QDialog.Accepted),
            mock.patch("antenna_toolkit_studio.ProjectDialog.project_name", return_value="Fresh Project"),
        ):
            self.window.create_project()
        self.app.processEvents()

        loaded = self.window.project_store.load_project("Fresh_Project")

        self.assertEqual(self.window.active_project_slug, "Fresh_Project")
        self.assertEqual(self.window.ffs_list.count(), 0)
        self.assertEqual(self.window.s2p_field.text(), "")
        self.assertEqual(self.window.technical_data_field.text(), "")
        self.assertEqual(loaded.ffs_items, [])
        self.assertEqual(loaded.touchstone_file, "")
        self.assertEqual(loaded.technical_data_file, "")
        self.assertEqual(loaded.presets, {})
        self.assertEqual(loaded.active_preset, "")
        self.assertEqual(loaded.settings, {})

    def test_edit_project_renames_project_and_keeps_saved_inputs(self) -> None:
        self.window._add_ffs_files(["Input data/a.ffs"])
        self.window._set_touchstone("Input data/a.s2p")
        self.window._set_technical_data("Input data/tech.xlsx")
        self.window.save_project_changes()
        project_dir = self.window.project_store.projects_dir / self.project.slug
        (project_dir / "dirty_project.xlsx").write_text("workbook", encoding="utf-8")
        self.app.processEvents()

        with (
            mock.patch("antenna_toolkit_studio.ProjectDialog.exec", return_value=QDialog.Accepted),
            mock.patch("antenna_toolkit_studio.ProjectDialog.project_name", return_value="Renamed Project"),
        ):
            self.window.edit_project()
        self.app.processEvents()

        loaded = self.window.project_store.load_project("Renamed_Project")

        self.assertEqual(self.window.active_project_slug, "Renamed_Project")
        self.assertEqual(loaded.ffs_items, [{"path": "Input data/a.ffs", "enabled": True, "port_label": ""}])
        self.assertEqual(loaded.touchstone_file, "Input data/a.s2p")
        self.assertEqual(loaded.technical_data_file, "Input data/tech.xlsx")
        self.assertTrue((self.window.project_store.projects_dir / "Renamed_Project" / "Renamed_Project.xlsx").exists())


if __name__ == "__main__":
    unittest.main()
