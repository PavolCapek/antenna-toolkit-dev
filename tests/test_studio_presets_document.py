from __future__ import annotations

import pytest

from studio_dirty_state_base import *


pytestmark = [pytest.mark.qt_slow, pytest.mark.gui_workflow]


class StudioPresetsDocumentTests(StudioDirtyStateBase):
    def _select_preset(self, name, values):
        self.window.global_presets[name] = values
        self.window.preset_store.save_preset(name, values)
        self.window.refresh_preset_list(select_name=name)

    def test_project_edits_and_shared_preset_saves_are_independent(self) -> None:
        original = self.window.collect_preset_values()
        self._select_preset("Preset A", original)

        self.window.beam_smooth.setValue(9)
        self.window.adf_model.setText("Project model")
        self.window.flush_derived_paths_refresh()
        self.assertTrue(self.window.has_unsaved_project_changes())
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["smooth"], original["smooth"])
        self.window.save_project_changes()
        self.assertFalse(self.window.has_unsaved_project_changes())
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["smooth"], original["smooth"])
        first_saved_settings = self.window.project_store.load_project(self.project.slug).settings
        self.assertEqual(first_saved_settings["smooth"], 9)
        self.assertEqual(first_saved_settings["adf_model"], "Project model")

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

        with mock.patch.object(self.window, "_preview_preset_changes", return_value=False):
            self.window.preset_update_action.trigger()
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["smooth"], original["smooth"])
        with mock.patch.object(self.window, "_preview_preset_changes", return_value=True):
            self.window.preset_update_action.trigger()

        self.assertTrue(self.window.has_unsaved_project_changes())
        self.assertNotIn("adf_model", self.window.preset_store.load_presets()["Preset A"])
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
        self.assertEqual(loaded_before_second_save.active_preset, "")

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

    def test_compliance_controls_round_trip_through_saved_preset(self) -> None:
        preset_name = "Compliance Preset"
        self._select_preset(preset_name, self.window.collect_preset_values())

        self.window.compliance_fmin.setValue(4.9)
        self.window.compliance_fmax.setValue(6.1)
        self.window.compliance_omit_angle_range.setText("178-180")
        self.window.compliance_sector_width.setValue(90.0)
        self.window.compliance_sector_center.setValue(5.5)
        with mock.patch.object(self.window, "_preview_preset_changes", return_value=True):
            self.window.save_preset()
        self.app.processEvents()

        loaded = self.window.preset_store.load_presets()[preset_name]
        self.assertEqual(loaded["compliance_fmin"], 4.9)
        self.assertEqual(loaded["compliance_fmax"], 6.1)
        self.assertEqual(loaded["compliance_omit_angle_range"], "178-180")
        self.assertEqual(loaded["compliance_sector_width"], 90.0)
        self.assertEqual(loaded["compliance_sector_center"], 5.5)

        self.window.compliance_fmin.setValue(0.0)
        self.window.compliance_fmax.setValue(0.0)
        self.window.compliance_omit_angle_range.setText("180-180")
        self.window.compliance_sector_width.setValue(0.0)
        self.window.compliance_sector_center.setValue(0.0)
        self.window.apply_preset_values(loaded)

        self.assertEqual(self.window.compliance_fmin.value(), 4.9)
        self.assertEqual(self.window.compliance_fmax.value(), 6.1)
        self.assertEqual(self.window.compliance_omit_angle_range.text(), "178-180")
        self.assertEqual(self.window.compliance_sector_width.value(), 90.0)
        self.assertEqual(self.window.compliance_sector_center.value(), 5.5)

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

        self.assertTrue(any("Select an available datasheet export style" in message for message in messages))

    def test_preset_preview_cancel_and_apply_preserve_project_inputs(self) -> None:
        original_preset = {"smooth": 11, "adf_model": "Shared model", "plot_line_1": "#123456"}
        self._select_preset("Preset A", original_preset)
        self.window.beam_smooth.setValue(17)
        self.window.adf_model.setText("Project model")
        self.window._add_ffs_files([{"path": "Input data/sample.ffs", "enabled": True, "port_label": "H"}])
        self.window._set_touchstone("Input data/sample.s1p")
        self.window._set_technical_data("Input data/technical.xlsx")
        before = self.window.current_project().to_dict()

        with mock.patch.object(self.window, "_preview_preset_changes", return_value=False) as preview:
            self.window.preset_apply_button.click()
        self.assertIn("Beam smoothing: 17 -> 11", preview.call_args.args[2])
        self.assertEqual(self.window.current_project().to_dict(), before)

        with (
            mock.patch.object(self.window, "_preview_preset_changes", return_value=True),
            mock.patch.object(self.window, "refresh_derived_paths", wraps=self.window.refresh_derived_paths) as refresh,
        ):
            self.window.preset_apply_button.click()
            self.window.flush_derived_paths_refresh()
        self.assertLessEqual(refresh.call_count, 2)
        self.assertEqual(self.window.beam_smooth.value(), 11)
        self.assertEqual(self.window.adf_model.text(), "Project model")
        self.assertEqual(self.window.plot_line1.color(), "#123456")
        self.assertEqual(self.window.polar_azimuth_line1.color(), "#123456")
        self.assertEqual(self.window.project_active_preset, "Preset A")
        self.assertEqual(self.window.collect_ffs_items()[0]["port_label"], "H")
        after = self.window.current_project().to_dict()
        for key in ("ffs_items", "touchstone_file", "technical_data_file", "radiation_pattern_frequencies_ghz"):
            self.assertEqual(after.get(key), before.get(key))
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"], original_preset)

        self.window.save_project_changes()
        self.window.global_presets["Preset A"]["smooth"] = 25
        self.window.refresh_project_list(select_slug=self.project.slug)
        self.assertEqual(self.window.beam_smooth.value(), 11)
        self.assertFalse(self.window.has_unsaved_project_changes())

    def test_shared_presets_can_be_selected_without_a_project(self) -> None:
        self._select_preset("Preset A", {"smooth": 11})
        self.window.project_combo.setCurrentIndex(0)
        self.window.preset_combo.setCurrentIndex(self.window.preset_combo.findData("Preset A"))
        self.assertEqual(self.window.current_preset_name(), "Preset A")
        self.assertFalse(self.window.preset_apply_button.isEnabled())
        self.assertFalse(self.window.preset_new_button.isEnabled())
        self.assertTrue(self.window.preset_rename_action.isEnabled())

    def test_save_as_preset_leaves_the_project_as_it_was(self) -> None:
        self.window.beam_smooth.setValue(13)
        self.window.adf_model.setText("Project model")
        before = self.window.current_project().to_dict()

        with mock.patch("antenna_toolkit_studio.QInputDialog.getText", return_value=("New Preset", True)):
            self.window.preset_new_button.click()

        self.assertEqual(self.window.current_project().to_dict(), before)
        new_preset = self.window.preset_store.load_presets()["New Preset"]
        self.assertEqual(new_preset["smooth"], 13)
        self.assertNotIn("adf_model", new_preset)

    def test_shared_update_preserves_unopened_linked_projects(self) -> None:
        self._select_preset("Preset A", {"smooth": 7})
        legacy = ProjectRecord(name="Legacy", slug="legacy", schema_version=7, active_preset="Preset A")
        self.window.project_store.save_project(legacy)
        self.window.beam_smooth.setValue(13)

        with mock.patch.object(self.window, "_preview_preset_changes", return_value=True):
            self.window.preset_update_action.trigger()

        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["smooth"], 13)
        self.window.refresh_project_list(select_slug=legacy.slug)
        self.assertEqual(self.window.beam_smooth.value(), 7)
        self.assertEqual(self.window.project_store.load_project(legacy.slug).settings["smooth"], 7)

    def test_opening_legacy_project_copies_embedded_settings_without_overwriting_shared_preset(self) -> None:
        self._select_preset("Preset A", {"smooth": 9})
        legacy = ProjectRecord(
            name="Legacy", slug="legacy", schema_version=7, active_preset="Preset A",
            settings={"smooth": 19}, presets={"Preset A": {"smooth": 7, "adf_model": "Legacy model"}},
        )
        self.window.project_store.save_project(legacy)
        self.window.refresh_project_list(select_slug=legacy.slug)

        self.assertEqual(self.window.beam_smooth.value(), 7)
        self.assertEqual(self.window.adf_model.text(), "Legacy model")
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["smooth"], 9)
        migrated = self.window.project_store.load_project(legacy.slug)
        self.assertGreater(migrated.schema_version, 7)
        self.assertEqual(migrated.settings["smooth"], 7)
        self.assertEqual(migrated.presets, legacy.presets)
        self.assertFalse(self.window.has_unsaved_project_changes())

    def test_switching_projects_saves_only_project_changes(self) -> None:
        self._select_preset("Preset A", {"smooth": 5})
        second = ProjectRecord(name="Second Project", slug="second_project")
        self.window.project_store.save_project(second)
        self.window.refresh_project_list(select_slug=self.project.slug)
        self.window.beam_smooth.setValue(9)

        with mock.patch("antenna_toolkit_studio.QMessageBox.question", return_value=QMessageBox.Save) as confirm:
            self.window.project_combo.setCurrentIndex(self.window.project_combo.findData(second.slug))

        confirm.assert_called_once()
        self.assertEqual(self.window.preset_store.load_presets()["Preset A"]["smooth"], 5)
        self.assertEqual(self.window.project_store.load_project(self.project.slug).settings["smooth"], 9)
        self.assertEqual(self.window.active_project_slug, second.slug)
