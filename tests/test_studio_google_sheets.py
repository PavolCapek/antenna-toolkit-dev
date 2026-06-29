from __future__ import annotations

import pytest

from studio_dirty_state_base import *


pytestmark = [pytest.mark.qt_slow, pytest.mark.gui_workflow]


class StudioGoogleSheetsTests(StudioDirtyStateBase):
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

    def test_google_sign_in_button_shows_setup_state(self) -> None:
        self.window.refresh_derived_paths()

        self.assertEqual(self.window.google_credentials_button.text(), "Google Sign In Needed")
        self.assertIn("#d64545", self.window.google_credentials_button.styleSheet())

        client = Path(self.temp_dir.name) / "client.json"
        client.write_text("client", encoding="utf-8")
        token_path = self.window.google_sheets_token_path()
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text("token", encoding="utf-8")
        self.window.store.set(studio_module.GOOGLE_SHEETS_OAUTH_CLIENT_KEY, str(client))
        self.window.refresh_derived_paths()

        self.assertEqual(self.window.google_credentials_button.text(), "Google Sign In Ready")
        self.assertIn("#2f9e5b", self.window.google_credentials_button.styleSheet())

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

    def test_prepare_technical_data_downloads_google_sheet_to_cached_workbook(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/sheet123abc/edit"
        cached_xlsx = Path(self.temp_dir.name) / "cached-google.xlsx"
        self.window._set_technical_data(url)

        def download_sheet(_url: str) -> Path:
            pd.DataFrame([["Antenna Name", "Sample Horn"]]).to_excel(cached_xlsx, index=False, header=False)
            return cached_xlsx

        with mock.patch.object(self.window, "download_google_sheet_technical_data", side_effect=download_sheet) as download:
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
            mock.patch.object(self.window, "_run_preflight_passes", return_value=True),
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
        self.assertEqual(queued_args["datasheet"][queued_args["datasheet"].index("--technical-data-sheet") + 1], "Datasheet")

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
            mock.patch.object(self.window, "_run_preflight_passes", return_value=True),
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
        self.assertEqual(queued_args["datasheet"][queued_args["datasheet"].index("--technical-data-sheet") + 1], "Datasheet")
        self.assertEqual(queued_args["datasheet"][queued_args["datasheet"].index("--radiation-frequencies-ghz") + 1], "0.3")
