from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog

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
        self.assertTrue(self.window.project_badge.text().endswith("*"))

        self.window.save_project_changes()
        self.app.processEvents()

        self.assertFalse(self.window.has_unsaved_project_changes())
        self.assertFalse(self.window.project_save_button.isEnabled())
        self.assertFalse(self.window.project_badge.text().endswith("*"))

    def test_preset_changes_require_project_save(self) -> None:
        with mock.patch("antenna_toolkit_studio.QInputDialog.getText", return_value=("Preset A", True)):
            self.window.create_preset()
        self.app.processEvents()

        self.assertTrue(self.window.has_unsaved_project_changes())
        loaded_before_save = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(loaded_before_save.presets, {})

        self.window.save_project_changes()
        self.app.processEvents()

        loaded_after_save = self.window.project_store.load_project(self.project.slug)
        self.assertIn("Preset A", loaded_after_save.presets)

        self.window.beam_smooth.setValue(self.window.beam_smooth.value() + 1)
        self.app.processEvents()
        self.window.save_preset()
        self.app.processEvents()

        self.assertTrue(self.window.has_unsaved_project_changes())
        loaded_before_second_save = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(loaded_before_second_save.presets["Preset A"]["smooth"], self.project.settings["smooth"])

        self.window.save_project_changes()
        self.app.processEvents()

        loaded_after_second_save = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(loaded_after_second_save.presets["Preset A"]["smooth"], self.window.beam_smooth.value())

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

    def test_theme_selector_supports_additional_themes_and_persists_selection(self) -> None:
        self.assertEqual(self.window.theme_selector.count(), 5)
        theme_index = self.window.theme_selector.findData("sage")

        self.assertGreaterEqual(theme_index, 0)

        self.window.theme_selector.setCurrentIndex(theme_index)
        self.app.processEvents()

        self.assertEqual(self.window.theme, "sage")
        self.assertEqual(self.window.store.get("theme"), "sage")
        self.assertEqual(self.window.theme_selector.currentText(), "Sage")
        self.assertGreaterEqual(QApplication.font().pointSizeF(), 11.0)

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
