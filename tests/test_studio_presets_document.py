from __future__ import annotations

import pytest

from studio_dirty_state_base import *


pytestmark = [pytest.mark.qt_slow, pytest.mark.gui_workflow]


class StudioPresetsDocumentTests(StudioDirtyStateBase):
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

    def test_preset_changes_do_not_dirty_saved_project(self) -> None:
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
        self.assertEqual(loaded_after_save.settings, {})
        first_saved_settings = dict(loaded_after_save.settings)
        self.assertNotIn("datasheet_type", first_saved_settings)
        self.assertNotIn("technical_data_sheet_name", first_saved_settings)

        self.window.beam_smooth.setValue(self.window.beam_smooth.value() + 1)
        self.app.processEvents()
        self.window.flush_derived_paths_refresh()

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
        self.assertNotIn("datasheet_type", self.window.collect_preset_values())
        self.assertNotIn("datasheet_layout", self.window.collect_preset_values())
        self.assertNotIn("datasheet_asset_ids", self.window.collect_preset_values())
        self.assertNotIn("technical_data_sheet_name", self.window.collect_preset_values())
        self.assertNotIn("technical_data_product_id", self.window.collect_preset_values())
        self.assertEqual(self.window.collect_preset_values()["pdf_metadata_author"], "RF elements")
        self.window.pdf_metadata_author.setText("Preset Author")
        self.assertEqual(self.window.collect_preset_values()["pdf_metadata_author"], "Preset Author")

    def test_compliance_controls_are_editable_and_preset_backed(self) -> None:
        self.assertEqual(self.window.compliance_fmin.value(), 0.0)
        self.assertEqual(self.window.compliance_fmax.value(), 0.0)
        self.assertEqual(self.window.compliance_omit_angle_range.text(), "180-180")
        self.assertEqual(self.window.compliance_sector_width.value(), 0.0)
        self.assertEqual(self.window.compliance_sector_center.value(), 0.0)
        initial_snapshot = self.window._current_stage_snapshot("compliance")

        self.window.compliance_fmin.setValue(4.9)
        self.window.compliance_fmax.setValue(6.1)
        self.window.compliance_omit_angle_range.setText("178-180")
        self.window.compliance_sector_width.setValue(90.0)
        self.window.compliance_sector_center.setValue(5.5)
        changed_snapshot = self.window._current_stage_snapshot("compliance")

        self.assertEqual(self.window.collect_preset_values()["compliance_fmin"], 4.9)
        self.assertEqual(self.window.collect_preset_values()["compliance_fmax"], 6.1)
        self.assertEqual(
            self.window.collect_preset_values()["compliance_omit_angle_range"],
            "178-180",
        )
        self.assertEqual(self.window.collect_preset_values()["compliance_sector_width"], 90.0)
        self.assertEqual(self.window.collect_preset_values()["compliance_sector_center"], 5.5)
        self.assertNotEqual(initial_snapshot["settings"], changed_snapshot["settings"])
        self.window.apply_preset_values(
            {
                "compliance_fmin": 5.0,
                "compliance_fmax": 6.0,
                "compliance_omit_angle_range": "179-180",
                "compliance_sector_width": 120.0,
                "compliance_sector_center": 5.6,
            }
        )
        self.assertEqual(self.window.compliance_fmin.value(), 5.0)
        self.assertEqual(self.window.compliance_fmax.value(), 6.0)
        self.assertEqual(self.window.compliance_omit_angle_range.text(), "179-180")
        self.assertEqual(self.window.compliance_sector_width.value(), 120.0)
        self.assertEqual(self.window.compliance_sector_center.value(), 5.6)

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

    def test_project_load_does_not_overlay_saved_settings_on_selected_preset(self) -> None:
        preset = dict(self.window.collect_preset_values())
        preset["cartesian_figure_width"] = 15.0
        preset["cartesian_figure_height"] = 8.0
        stale_settings = dict(preset)
        stale_settings["cartesian_figure_width"] = 12.0
        stale_settings["cartesian_figure_height"] = 7.0
        self.window.global_presets = {"Preset A": preset}
        self.window.global_active_preset = "Preset A"
        self.window._persist_global_presets()

        project = ProjectRecord(
            name="Preset Snapshot Project",
            slug="preset_snapshot_project",
            settings=stale_settings,
            presets={},
            active_preset="Preset A",
            run_state={},
        )
        self.window.project_store.save_project(project)

        self.window.refresh_project_list(select_slug=project.slug)
        self.app.processEvents()

        self.assertEqual(self.window.current_preset_name(), "Preset A")
        self.assertEqual(self.window.cartesian_figure_width.value(), 15.0)
        self.assertEqual(self.window.cartesian_figure_height.value(), 8.0)
        self.assertFalse(self.window.has_unsaved_preset_changes())
        self.assertEqual(self.window.preset_save_state_indicator.text(), "Preset saved")

    def test_manual_project_settings_still_dirty_project_without_selected_preset(self) -> None:
        self.window.project_active_preset = ""
        self.window.global_active_preset = ""
        self.window.refresh_preset_list(select_name="")
        self.window.save_project_changes()
        self.app.processEvents()

        self.window.beam_smooth.setValue(self.window.beam_smooth.value() + 1)
        self.app.processEvents()
        self.window.flush_derived_paths_refresh()

        self.assertTrue(self.window.has_unsaved_project_changes())
        self.assertFalse(self.window.has_unsaved_preset_changes())

        self.window.save_project_changes()
        loaded = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(loaded.active_preset, "")
        self.assertEqual(loaded.settings["smooth"], self.window.beam_smooth.value())

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
        self.assertEqual(saved_first.active_preset, "Preset A")
        self.assertEqual(saved_first.settings, {})
        self.assertEqual(saved_first.ffs_items[0]["path"], "Input data/a.ffs")
        self.assertEqual(self.window.active_project_slug, second.slug)
