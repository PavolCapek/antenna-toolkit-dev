from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from project_store import (
    CURRENT_PROJECT_SCHEMA_VERSION,
    ProjectRecord,
    ProjectStore,
    PROJECT_FILE_NAME,
    resolve_project_path,
    serialize_workspace_path,
)


class ProjectStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.store = ProjectStore(self.root)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_migrates_legacy_project_payload(self) -> None:
        payload = {
            "name": "Legacy Dish",
            "slug": "legacy_dish",
            "ffs_files": ["Input data/a.ffs", "Input data/b.ffs"],
            "touchstone_file": "Input data/a.s2p",
            "technical_data_file": "Input data/tech.xlsx",
            "settings": {"smooth": 5},
            "presets": {"Default": {"smooth": 5}},
            "active_preset": "Default",
            "run_metadata": {"history": [{"action": "imported"}]},
        }

        project = ProjectRecord.from_dict(payload)

        self.assertEqual(project.schema_version, 1)
        self.assertEqual(
            project.ffs_items,
            [
                {"path": "Input data/a.ffs", "enabled": True},
                {"path": "Input data/b.ffs", "enabled": True},
            ],
        )
        self.assertEqual(project.run_state["history"][0]["action"], "imported")
        self.assertEqual(project.technical_data_file, "Input data/tech.xlsx")

    def test_save_and_load_preserves_active_preset_and_run_state(self) -> None:
        project = ProjectRecord(
            name="Dish A",
            slug="dish_a",
            ffs_items=[{"path": "Input data/a.ffs", "enabled": True}],
            touchstone_file="Input data/a.s2p",
            technical_data_file="Input data/tech.xlsx",
            settings={"smooth": 7, "grid_color": "#4b5563"},
            presets={"Tight": {"smooth": 7, "grid_color": "#4b5563"}},
            active_preset="Tight",
            run_state={"history": [{"action": "created"}], "stages": {"beam": {"status": "success"}}},
        )

        self.store.save_project(project)
        loaded = self.store.load_project("dish_a")

        self.assertEqual(loaded.schema_version, CURRENT_PROJECT_SCHEMA_VERSION)
        self.assertEqual(loaded.active_preset, "Tight")
        self.assertEqual(loaded.technical_data_file, "Input data/tech.xlsx")
        self.assertEqual(loaded.settings, {"smooth": 7, "grid_color": "#4b5563"})
        self.assertEqual(loaded.presets, {"Tight": {"smooth": 7, "grid_color": "#4b5563"}})
        self.assertEqual(loaded.run_state["stages"]["beam"]["status"], "success")

    def test_duplicate_export_and_import_bundle(self) -> None:
        project = ProjectRecord(
            name="Dish B",
            slug="dish_b",
            ffs_items=[{"path": "Input data/b.ffs", "enabled": False}],
            touchstone_file="Input data/b.s2p",
            technical_data_file="Input data/b-tech.xlsx",
            settings={"smooth": 3},
            presets={"Loose": {"smooth": 3}},
            active_preset="Loose",
            run_state={"history": [{"action": "created"}]},
        )
        project_dir = self.store.save_project(project)
        (project_dir / "dish_b.xlsx").write_text("workbook", encoding="utf-8")

        duplicate = self.store.duplicate_project("dish_b", "Dish B Copy")
        self.assertEqual(duplicate.slug, "Dish_B_Copy")
        self.assertEqual(duplicate.technical_data_file, "Input data/b-tech.xlsx")
        self.assertEqual(duplicate.run_state["history"][0]["action"], "duplicated")
        self.assertTrue((duplicate.project_dir(self.root) / "Dish_B_Copy.xlsx").exists())

        bundle_path = self.root / "exports" / "dish_b.zip"
        self.store.export_project_bundle("dish_b", bundle_path)
        self.assertTrue(bundle_path.exists())

        imported = self.store.import_project_bundle(bundle_path)
        self.assertNotEqual(imported.slug, "dish_b")
        self.assertTrue((imported.project_dir(self.root) / f"{imported.slug}.xlsx").exists())
        self.assertEqual(imported.run_state["history"][0]["action"], "imported")

    def test_output_paths_are_derived_from_project_slug(self) -> None:
        project = ProjectRecord(name="Dish C", slug="dish_c")

        self.assertEqual(project.project_file(self.root), self.root / "Projects" / "dish_c" / PROJECT_FILE_NAME)
        self.assertEqual(project.workbook_path(self.root), self.root / "Projects" / "dish_c" / "dish_c.xlsx")
        self.assertEqual(project.extract_path(self.root), self.root / "Projects" / "dish_c" / "dish_c-extracted-data.xlsx")
        self.assertEqual(project.datasheet_path(self.root), self.root / "Projects" / "dish_c" / "dish_c-datasheet.pdf")
        self.assertEqual(project.vswr_path(self.root), self.root / "Projects" / "dish_c" / "dish_c-vswr.svg")

    def test_project_json_written_with_current_schema(self) -> None:
        project = ProjectRecord(name="Dish D", slug="dish_d")

        project_dir = self.store.save_project(project)
        payload = json.loads((project_dir / PROJECT_FILE_NAME).read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], CURRENT_PROJECT_SCHEMA_VERSION)
        self.assertIn("technical_data_file", payload)
        self.assertIn("settings", payload)
        self.assertIn("presets", payload)

    def test_google_sheet_url_paths_are_preserved(self) -> None:
        url = "https://docs.google.com/spreadsheets/d/sheet123/edit#gid=0"

        self.assertEqual(serialize_workspace_path(self.root, url), url)
        self.assertEqual(resolve_project_path(self.root, url), url)

    def test_rename_updates_slugged_outputs(self) -> None:
        project = ProjectRecord(name="Dish E", slug="dish_e")

        project_dir = self.store.save_project(project)
        (project_dir / "dish_e.xlsx").write_text("workbook", encoding="utf-8")

        renamed = ProjectRecord(name="Dish E Prime", slug="dish_e_prime")
        renamed_dir = self.store.save_project(renamed, previous_slug="dish_e")

        self.assertTrue((renamed_dir / "dish_e_prime.xlsx").exists())
        self.assertFalse((renamed_dir / "dish_e.xlsx").exists())

    def test_import_bundle_rejects_unsafe_paths(self) -> None:
        bundle_path = self.root / "exports" / "unsafe.zip"
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"name": "Unsafe", "slug": "unsafe"}

        import zipfile

        with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("unsafe/project.json", json.dumps(payload))
            archive.writestr("unsafe/../../outside.txt", "owned")

        with self.assertRaises(ValueError):
            self.store.import_project_bundle(bundle_path)

        self.assertFalse((self.root / "outside.txt").exists())


if __name__ == "__main__":
    unittest.main()
