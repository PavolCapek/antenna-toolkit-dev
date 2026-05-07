from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from datasheet.technical_data import (
    GoogleSheetTechnicalDataSource,
    LocalTechnicalDataSource,
    TechnicalDataError,
    load_technical_data_entries,
)


class TechnicalDataParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.workbook = self.root / "technical.xlsx"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_loads_named_sheet_with_section_label_value_rows(self) -> None:
        with pd.ExcelWriter(self.workbook) as writer:
            pd.DataFrame([["Ignore", "Me"]]).to_excel(writer, sheet_name="Intro", index=False, header=False)
            pd.DataFrame(
                [
                    ["Section", "Label", "Value"],
                    ["Technical Data", "Antenna Name", "Sample Horn"],
                    ["Mechanical Data", "Weight", "2 kg"],
                ]
            ).to_excel(writer, sheet_name="Technical", index=False, header=False)

        entries = load_technical_data_entries(self.workbook, sheet_name="Technical")

        self.assertEqual([(entry.section, entry.label, entry.value) for entry in entries], [
            ("Technical Data", "Antenna Name", "Sample Horn"),
            ("Mechanical Data", "Weight", "2 kg"),
        ])

    def test_preserves_unknown_section_names_for_future_layouts(self) -> None:
        pd.DataFrame(
            [
                ["Section", "Label", "Value"],
                ["Environmental", "Wind load", "120 km/h"],
                ["Compliance", "Standard", "ETSI"],
            ]
        ).to_excel(self.workbook, sheet_name="Sheet1", index=False, header=False)

        entries = load_technical_data_entries(self.workbook)

        self.assertEqual([entry.section for entry in entries], ["Environmental", "Compliance"])

    def test_loads_wide_single_product_table(self) -> None:
        pd.DataFrame(
            [
                ["Product ID", "Antenna Name", "RF Connection", "Weight"],
                ["SH123", "Sample Horn", "N female", "2 kg"],
            ]
        ).to_excel(self.workbook, sheet_name="Sheet1", index=False, header=False)

        entries = load_technical_data_entries(self.workbook)
        by_label = {entry.label: entry.value for entry in entries}

        self.assertEqual(by_label["Product ID"], "SH123")
        self.assertEqual(by_label["Antenna Name"], "Sample Horn")
        self.assertEqual(by_label["RF Connection"], "N female")

    def test_wide_multi_product_table_requires_product_id(self) -> None:
        pd.DataFrame(
            [
                ["Product ID", "Antenna Name", "RF Connection"],
                ["SH123", "Sample Horn", "N female"],
                ["LPDA1", "LPDA", "SMA"],
            ]
        ).to_excel(self.workbook, sheet_name="Sheet1", index=False, header=False)

        with self.assertRaisesRegex(TechnicalDataError, "multiple product rows"):
            load_technical_data_entries(self.workbook)

        selected = load_technical_data_entries(self.workbook, product_id="LPDA1")
        by_label = {entry.label: entry.value for entry in selected}
        self.assertEqual(by_label["Antenna Name"], "LPDA")

    def test_rejects_unsupported_local_file_type(self) -> None:
        path = self.root / "technical.xls"
        path.write_text("not really excel", encoding="utf-8")

        with self.assertRaisesRegex(TechnicalDataError, "Legacy .xls"):
            LocalTechnicalDataSource(path).prepare_workbook()

    def test_google_sheet_source_uses_downloader_and_validates_cache(self) -> None:
        def downloader(_url: str, output: Path) -> Path:
            pd.DataFrame([["Antenna Name", "Sample Horn"]]).to_excel(output, index=False, header=False)
            return output

        source = GoogleSheetTechnicalDataSource("https://docs.google.com/spreadsheets/d/demo/edit", self.workbook, downloader)

        prepared = source.prepare_workbook()
        entries = load_technical_data_entries(prepared)

        self.assertEqual(prepared, self.workbook.resolve())
        self.assertEqual(entries[0].label, "Antenna Name")
        self.assertEqual(entries[0].value, "Sample Horn")


if __name__ == "__main__":
    unittest.main()
