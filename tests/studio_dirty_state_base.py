from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
import pandas as pd
import pytest

import studio_support as qt_module
import antenna_toolkit_studio as studio_module
from antenna_toolkit_studio import ModernMainWindow, StepperField, read_ffs_frequency_headers
from studio_support import DEFAULT_COLOR_OPTIONS
from project_store import ProjectRecord, ProjectStore




class StudioDirtyStateBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        app_state = mock.patch.object(studio_module, "app_state_dir", return_value=root)
        app_state.start()
        self.addCleanup(app_state.stop)
        with (
            mock.patch.object(studio_module, "STATE_FILE", root / "studio-state.json"),
            mock.patch.object(studio_module, "ProjectStore", return_value=ProjectStore(root)),
            mock.patch.object(studio_module, "preset_storage_dir", return_value=root / "Presets"),
            mock.patch.object(studio_module, "legacy_preset_storage_dirs", return_value=[]),
        ):
            self.window = ModernMainWindow()
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
        self.window.deleteLater()
        self.app.sendPostedEvents(self.window, QEvent.Type.DeferredDelete)
        self.temp_dir.cleanup()
