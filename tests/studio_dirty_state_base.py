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
        self.window = ModernMainWindow()
        self.window.project_store = ProjectStore(Path(self.temp_dir.name))
        self.window.preset_store = qt_module.PresetFileStore(Path(self.temp_dir.name) / "Presets")
        self.window.store.delete("ui_presets")
        self.window.store.set("active_preset", "")
        self.window.store.delete(studio_module.GOOGLE_SHEETS_OAUTH_CLIENT_KEY)
        token_path = self.window.google_sheets_token_path()
        if token_path.exists():
            token_path.unlink()
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
