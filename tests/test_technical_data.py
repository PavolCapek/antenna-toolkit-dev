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
from datasheet.models import canonical_field_key


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

    def test_loads_rfe_v2_profile_with_combined_metric_and_imperial_values(self) -> None:
        pd.DataFrame(
            [
                ["General", None, None],
                ["Product name", None, "45° Asymmetrical Horn Antenna"],
                ["Product ID", None, "AH45WB"],
                ["Performance", None, None],
                ["Polarization", None, "Dual Linear H + V"],
                ["Dimensions", None, None],
                ["Size Single Unit [mm]", "X", 560],
                [None, "Y", 450],
                [None, "Z", 190],
                ["Weight Single Unit [kg]", "Netto", 2.7],
                [None, "Brutto", 4.1],
                ["Wind", None, None],
                ["Effective Projected Area [cm²]", "Front", 271],
                [None, "Side", 1018],
                ["Wind Load [N]", "Front", 33],
                [None, "Side", 123],
                ["Wind Load at speed [km/h]", None, 160],
                ["Wind Survival [km/h]", None, 160],
                ["Technical Data", None, None],
                ["Radio Connection", None, "TwistPort Waveguide Connector"],
                ["Pole Mounting Diameter [mm]", "min", 40],
                [None, "max", 80],
                ["Temperature", "min", "-35°C"],
                [None, "max", "60°C"],
                ["Mechanical Adjustment", "Elevation", "+/- 20°"],
                [None, "Azimuth", "+/- 20°"],
            ]
        ).to_excel(self.workbook, sheet_name="Sheet1", index=False, header=False)

        entries = load_technical_data_entries(
            self.workbook,
            canonical_key_factory=canonical_field_key,
            technical_data_profile="rfe",
        )
        by_key = {entry.canonical_key: entry for entry in entries}

        self.assertEqual(by_key["antenna name"].value, "45° Asymmetrical Horn Antenna")
        self.assertEqual(by_key["product id"].value, "AH45WB")
        self.assertEqual(by_key["single unit"].value, "560 x 450 x 190 mm (22.0 x 17.7 x 7.5 inch)")
        self.assertEqual(by_key["weight"].value, "2.7 kg / 6.0 lbs - single unit\n4.1 kg / 9.0 lbs - single unit incl. package")
        self.assertEqual(by_key["pole mounting diameter"].value, "40-80 mm (1.6-3.1 inch)")
        self.assertEqual(by_key["wind load"].value, "33/123 N - Front/Side at 160 km/h (100 mph)")
        self.assertEqual(by_key["effective projected area"].value, "271/1018 cm² - Front/Side (42.0/157.8 in²)")
        self.assertEqual(by_key["temperature"].value, "-35°C to +60°C (-31°F to +140°F)")
        self.assertEqual(by_key["mechanical adjustment"].value, "+/- 20° Elevation, +/- 20° Azimuth")

    def test_rfe_v2_profile_is_not_applied_by_default(self) -> None:
        pd.DataFrame(
            [
                ["General", None, None],
                ["Product name", None, "45° Asymmetrical Horn Antenna"],
                ["Product ID", None, "AH45WB"],
                ["Performance", None, None],
                ["Polarization", None, "Dual Linear H + V"],
                ["Dimensions", None, None],
                ["Size Single Unit [mm]", "X", 560],
                [None, "Y", 450],
                [None, "Z", 190],
                ["Technical Data", None, None],
                ["Radio Connection", None, "TwistPort Waveguide Connector"],
            ]
        ).to_excel(self.workbook, sheet_name="Sheet1", index=False, header=False)

        with self.assertRaisesRegex(TechnicalDataError, "multiple product rows"):
            load_technical_data_entries(self.workbook)

    def test_rfe_v2_profile_reads_wind_speed_from_wind_load_label(self) -> None:
        pd.DataFrame(
            [
                ["General", None, None],
                ["Product name", None, "20Â° Symmetrical Horn WB"],
                ["Product ID", None, "SH20WB"],
                ["Performance", None, None],
                ["Polarization", None, "Dual Linear H + V"],
                ["Wind", None, None],
                ["Wind Load at 160km/h [N]", "Front", 83],
                [None, "Side", 66],
                ["Wind Survival [km/h]", None, 160],
                ["Dimensions", None, None],
                ["Technical Data", None, None],
            ]
        ).to_excel(self.workbook, sheet_name="Sheet1", index=False, header=False)

        entries = load_technical_data_entries(
            self.workbook,
            canonical_key_factory=canonical_field_key,
            technical_data_profile="rfe",
        )
        by_key = {entry.canonical_key: entry for entry in entries}

        self.assertEqual(by_key["wind load"].value, "83/66 N - Front/Side at 160 km/h (100 mph)")

    def test_rfe_v2_profile_defaults_wind_load_speed_to_160_kmh(self) -> None:
        pd.DataFrame(
            [
                ["General", None, None],
                ["Product name", None, "Sample Antenna"],
                ["Product ID", None, "SAMPLE"],
                ["Performance", None, None],
                ["Polarization", None, "Dual Linear H + V"],
                ["Wind", None, None],
                ["Wind Load [N]", "Front", 83],
                [None, "Side", 66],
                ["Dimensions", None, None],
                ["Technical Data", None, None],
            ]
        ).to_excel(self.workbook, sheet_name="Sheet1", index=False, header=False)

        entries = load_technical_data_entries(
            self.workbook,
            canonical_key_factory=canonical_field_key,
            technical_data_profile="rfe",
        )
        by_key = {entry.canonical_key: entry for entry in entries}

        self.assertEqual(by_key["wind load"].value, "83/66 N - Front/Side at 160 km/h (100 mph)")


if __name__ == "__main__":
    unittest.main()
