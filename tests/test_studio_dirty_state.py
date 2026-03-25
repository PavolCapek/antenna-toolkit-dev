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

import antenna_toolkit_studio as studio_module
from antenna_toolkit_studio import ModernMainWindow, StepperField
from project_store import ProjectRecord, ProjectStore


class StudioDirtyStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.window = ModernMainWindow()
        self.window.project_store = ProjectStore(Path(self.temp_dir.name))
        self.window.store.set("ui_presets", {})
        self.window.store.set("active_preset", "")
        self.window.global_presets = {}
        self.window.global_active_preset = ""
        self.window.refresh_project_list(select_slug="")
        self.window._reset_to_default_state()
        self.project = ProjectRecord(
            name="Dirty Project",
            slug="dirty_project",
            settings=self.window.collect_preset_values(),
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

        self.window.beam_smooth.setValue(self.window.beam_smooth.value() + 1)
        self.app.processEvents()

        self.assertTrue(self.window.has_unsaved_project_changes())
        self.assertTrue(self.window.project_save_button.isEnabled())
        self.assertTrue(self.window.project_name.text().endswith("*"))

        self.window.save_project_changes()
        self.app.processEvents()

        self.assertFalse(self.window.has_unsaved_project_changes())
        self.assertFalse(self.window.project_save_button.isEnabled())
        self.assertFalse(self.window.project_name.text().endswith("*"))

    def test_preset_changes_require_project_save(self) -> None:
        self.window.global_presets["Preset A"] = self.window.collect_preset_values()
        self.window.global_active_preset = "Preset A"
        self.window.project_active_preset = "Preset A"
        self.window._persist_global_presets()
        self.window.refresh_preset_list(select_name="Preset A")
        self.window._mark_project_dirty()
        self.app.processEvents()

        self.assertTrue(self.window.has_unsaved_project_changes())
        self.assertIn("Preset A", self.window.store.get("ui_presets", {}))
        loaded_before_save = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(loaded_before_save.presets, {})
        self.assertEqual(loaded_before_save.active_preset, "")

        self.window.save_project_changes()
        self.app.processEvents()

        loaded_after_save = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(loaded_after_save.presets, {})
        self.assertEqual(loaded_after_save.active_preset, "Preset A")

        self.window.beam_smooth.setValue(self.window.beam_smooth.value() + 1)
        self.app.processEvents()
        self.window.save_preset()
        self.app.processEvents()

        self.assertTrue(self.window.has_unsaved_project_changes())
        self.assertEqual(self.window.store.get("ui_presets", {})["Preset A"]["smooth"], self.window.beam_smooth.value())
        loaded_before_second_save = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(loaded_before_second_save.presets, {})
        self.assertEqual(loaded_before_second_save.settings["smooth"], self.project.settings["smooth"])

        self.window.save_project_changes()
        self.app.processEvents()

        loaded_after_second_save = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(loaded_after_second_save.presets, {})
        self.assertEqual(loaded_after_second_save.active_preset, "Preset A")
        self.assertEqual(loaded_after_second_save.settings["smooth"], self.window.beam_smooth.value())

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
            settings=self.window._default_project_settings(),
            presets={},
            active_preset="",
            run_state={},
        )
        self.window.project_store.save_project(second)
        self.window.refresh_project_list(select_slug=second.slug)
        self.app.processEvents()

        self.assertEqual(self.window.active_project_slug, second.slug)
        self.assertGreaterEqual(self.window.preset_combo.findData("Preset A"), 0)
        self.assertEqual(self.window.project_store.load_project(second.slug).active_preset, "")

    def test_exit_prompt_can_save_or_cancel_dirty_project(self) -> None:
        self.window.beam_smooth.setValue(self.window.beam_smooth.value() + 1)
        self.app.processEvents()

        with mock.patch("antenna_toolkit_studio.QMessageBox.question", return_value=QMessageBox.Save):
            confirmed = self.window._confirm_pending_project_changes("exiting")
        self.assertTrue(confirmed)
        self.assertFalse(self.window.has_unsaved_project_changes())

        self.window.beam_smooth.setValue(self.window.beam_smooth.value() + 1)
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
            settings=self.window._default_project_settings(),
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
        with mock.patch.object(self.window, "_screen_available_height", return_value=1200):
            self.window._update_layout_mode(force=True)
        self.app.processEvents()

        self.assertTrue(self.window._compact_layout)
        self.assertTrue(self.window.brand_subtitle.isHidden())
        self.assertTrue(self.window.run_help_label.isHidden())
        self.assertFalse(self.window.pipeline_details_toggle.isHidden())
        self.assertTrue(self.window.pipeline_details.isHidden())
        self.assertEqual(self.window.ffs_list.minimumHeight(), 140)
        self.assertGreaterEqual(QApplication.font().pointSizeF(), 10.0)

        with mock.patch.object(self.window, "_screen_available_height", return_value=1440):
            self.window._update_layout_mode(force=True)
        self.app.processEvents()

        self.assertFalse(self.window._compact_layout)
        self.assertFalse(self.window.brand_subtitle.isHidden())
        self.assertFalse(self.window.run_help_label.isHidden())
        self.assertTrue(self.window.pipeline_details_toggle.isHidden())
        self.assertFalse(self.window.pipeline_details.isHidden())
        self.assertEqual(self.window.ffs_list.minimumHeight(), 170)

    def test_pipeline_buttons_show_only_full_and_cancel(self) -> None:
        labels = [button.text() for button in self.window.hero_actions._buttons]

        self.assertEqual(labels, ["Run Full Pipeline", "Cancel Run", "Manual runs"])
        run_actions = [action.text() for action in self.window.run_more_menu.actions()]
        self.assertEqual(
            run_actions,
            [
                "Workbook only",
                "Extract data",
                "Generate datasheet PDF",
                "Plots only",
                "VSWR only",
            ],
        )

    def test_run_full_queues_datasheet_stage(self) -> None:
        ffs_path = Path(self.temp_dir.name) / "sample.ffs"
        s2p_path = Path(self.temp_dir.name) / "sample.s2p"
        ffs_path.write_text("ffs", encoding="utf-8")
        s2p_path.write_text("s2p", encoding="utf-8")
        self.window._add_ffs_files([str(ffs_path)])
        self.window._set_touchstone(str(s2p_path))
        self.app.processEvents()

        queued: list[str] = []

        with (
            mock.patch.object(self.window, "_save_project_if_dirty"),
            mock.patch.object(self.window, "_enqueue_stage", side_effect=lambda stage_key, args: queued.append(stage_key)),
        ):
            self.window.run_full()

        self.assertEqual(queued, ["beam", "extract", "datasheet", "plot", "vswr"])

    def test_create_project_starts_blank_until_user_saves_inputs(self) -> None:
        self.window._add_ffs_files(["Input data/a.ffs"])
        self.window._set_touchstone("Input data/a.s2p")
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
        self.assertEqual(loaded.ffs_items, [])
        self.assertEqual(loaded.touchstone_file, "")
        self.assertEqual(loaded.presets, {})
        self.assertEqual(loaded.active_preset, "")
        self.assertEqual(loaded.settings["smooth"], 5)

    def test_edit_project_renames_project_and_keeps_saved_inputs(self) -> None:
        self.window._add_ffs_files(["Input data/a.ffs"])
        self.window._set_touchstone("Input data/a.s2p")
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
        self.assertEqual(loaded.ffs_items, [{"path": "Input data/a.ffs", "enabled": True}])
        self.assertEqual(loaded.touchstone_file, "Input data/a.s2p")
        self.assertTrue((self.window.project_store.projects_dir / "Renamed_Project" / "Renamed_Project.xlsx").exists())


if __name__ == "__main__":
    unittest.main()
