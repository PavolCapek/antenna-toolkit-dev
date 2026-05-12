from __future__ import annotations

from studio_dirty_state_base import *


class StudioUiLayoutTests(StudioDirtyStateBase):
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
        self.window.flush_derived_paths_refresh()

        self.assertEqual(self.window.preset_save_state_indicator.text(), "Preset has unsaved changes")
        self.assertEqual(self.window.project_save_state_indicator.text(), "Project has unsaved changes")

    def test_project_unsaved_indicator_lists_added_far_field_file(self) -> None:
        self.window._add_ffs_files(["Input data/a.ffs"])
        self.app.processEvents()

        diff_items = self.window.project_save_state_indicator.diff_items()

        self.assertTrue(any(item.startswith("Far-field file added:") and item.endswith("a.ffs") for item in diff_items))

    def test_project_unsaved_indicator_diff_clears_after_save(self) -> None:
        self.window._add_ffs_files(["Input data/a.ffs"])
        self.app.processEvents()

        self.assertTrue(self.window.project_save_state_indicator.diff_items())

        self.window.save_project_changes()
        self.app.processEvents()

        self.assertEqual(self.window.project_save_state_indicator.diff_items(), [])

    def test_preset_unsaved_indicator_lists_changed_control(self) -> None:
        self.window.global_presets["Preset A"] = self.window.collect_preset_values()
        self.window.global_active_preset = "Preset A"
        self.window.project_active_preset = "Preset A"
        self.window.refresh_preset_list(select_name="Preset A")
        self.window.save_project_changes()
        self.app.processEvents()

        self.window.beam_smooth.setValue(self.window.beam_smooth.value() + 1)
        self.app.processEvents()
        self.window.flush_derived_paths_refresh()

        diff_items = self.window.preset_save_state_indicator.diff_items()

        self.assertTrue(any(item.startswith("Beam smoothing:") for item in diff_items))

    def test_clean_indicators_do_not_advertise_hover_diff_entries(self) -> None:
        self.assertEqual(self.window.project_save_state_indicator.diff_items(), [])
        self.assertEqual(self.window.preset_save_state_indicator.diff_items(), [])

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

    def test_command_left_column_is_narrower_on_desktop_layout(self) -> None:
        self.window._compact_layout = False
        self.window._apply_layout_metrics()

        self.assertEqual(self.window.command_left.maximumWidth(), 390)
        self.assertEqual(self.window.command_panel.min_card_width, 360)

    def test_configuration_changes_debounce_refresh_work(self) -> None:
        with mock.patch.object(self.window, "refresh_derived_paths") as refresh:
            for _index in range(5):
                self.window.on_project_configuration_changed()

            self.assertEqual(refresh.call_count, 0)

            self.window.flush_derived_paths_refresh()

        self.assertEqual(refresh.call_count, 1)

    def test_progress_updates_debounce_refresh_work(self) -> None:
        with mock.patch.object(self.window, "refresh_derived_paths") as refresh:
            for index in range(5):
                self.window.on_proc_progress(
                    {"stage": "beam", "current": index + 1, "total": 5, "label": "Processing sample.ffs"}
                )

            self.assertEqual(refresh.call_count, 0)

            self.window.flush_derived_paths_refresh()

        self.assertEqual(refresh.call_count, 1)

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
