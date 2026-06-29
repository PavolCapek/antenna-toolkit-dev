from __future__ import annotations

import pytest

from studio_dirty_state_base import *


pytestmark = [pytest.mark.qt_slow, pytest.mark.gui_workflow]


class StudioProjectStateTests(StudioDirtyStateBase):
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

    def test_radiation_frequency_headers_are_cached_until_file_changes(self) -> None:
        ffs_path = Path(self.temp_dir.name) / "cached.ffs"
        ffs_path.write_text("freq = 1 GHz\n", encoding="utf-8")
        self.window._add_ffs_files([str(ffs_path)])
        self.window._ffs_frequency_cache = {}

        with mock.patch("antenna_toolkit_studio.read_ffs_frequency_headers", return_value=[1.0]) as reader:
            self.assertEqual(self.window._available_radiation_frequencies(), [1.0])
            self.assertEqual(self.window._available_radiation_frequencies(), [1.0])

        reader.assert_called_once()

        ffs_path.write_text("freq = 2 GHz\nchanged\n", encoding="utf-8")
        with mock.patch("antenna_toolkit_studio.read_ffs_frequency_headers", return_value=[2.0]) as reader:
            self.assertEqual(self.window._available_radiation_frequencies(), [2.0])

        reader.assert_called_once()

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

    def test_duplicate_project_saves_dirty_project_before_copying(self) -> None:
        self.window._add_ffs_files(["Input data/a.ffs"])
        self.app.processEvents()

        with (
            mock.patch("antenna_toolkit_studio.QMessageBox.question", return_value=QMessageBox.Save),
            mock.patch("antenna_toolkit_studio.QInputDialog.getText", return_value=("Saved Copy", True)),
            mock.patch("antenna_toolkit_studio.QMessageBox.information"),
        ):
            self.window.duplicate_project()
        self.app.processEvents()

        duplicate = self.window.project_store.load_project("Saved_Copy")
        original = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(original.ffs_items, [{"path": "Input data/a.ffs", "enabled": True, "port_label": ""}])
        self.assertEqual(duplicate.ffs_items, original.ffs_items)
        self.assertEqual(self.window.active_project_slug, "Saved_Copy")

    def test_export_project_can_discard_dirty_project_before_exporting(self) -> None:
        self.window._add_ffs_files(["Input data/a.ffs"])
        bundle_path = Path(self.temp_dir.name) / "dirty_project_bundle.zip"
        self.app.processEvents()

        with (
            mock.patch("antenna_toolkit_studio.QMessageBox.question", return_value=QMessageBox.Discard),
            mock.patch("antenna_toolkit_studio.QFileDialog.getSaveFileName", return_value=(str(bundle_path), "ZIP (*.zip)")),
            mock.patch.object(self.window.project_store, "export_project_bundle", wraps=self.window.project_store.export_project_bundle) as export_bundle,
            mock.patch("antenna_toolkit_studio.QMessageBox.information"),
        ):
            self.window.export_project_bundle()
        self.app.processEvents()

        export_bundle.assert_called_once()
        saved = self.window.project_store.load_project(self.project.slug)
        self.assertEqual(saved.ffs_items, [])
        self.assertTrue(self.window.has_unsaved_project_changes())
        self.assertTrue(bundle_path.exists())

    def test_import_project_cancel_keeps_dirty_project_and_skips_file_picker(self) -> None:
        self.window._add_ffs_files(["Input data/a.ffs"])
        self.app.processEvents()

        with (
            mock.patch("antenna_toolkit_studio.QMessageBox.question", return_value=QMessageBox.Cancel),
            mock.patch("antenna_toolkit_studio.QFileDialog.getOpenFileName") as open_file,
        ):
            self.window.import_project_bundle()
        self.app.processEvents()

        open_file.assert_not_called()
        self.assertTrue(self.window.has_unsaved_project_changes())
        self.assertEqual(self.window.active_project_slug, self.project.slug)

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

    def test_persist_skips_unchanged_writes(self) -> None:
        state_path = Path(self.temp_dir.name) / "state.json"
        store = qt_module.Persist(state_path)

        with mock.patch.object(store, "save", wraps=store.save) as save:
            store.set("theme", "light")
            store.set("theme", "light")
            store.set("theme", "dark")

        self.assertEqual(save.call_count, 2)
        self.assertEqual(store.get("theme"), "dark")
