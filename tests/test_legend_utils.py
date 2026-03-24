from __future__ import annotations

import unittest

from legend_utils import (
    apply_legend_labels,
    beamwidth_legend_label,
    detect_polarization,
    gain_legend_label,
    parse_legend_labels,
    polar_legend_label,
    polarization_sort_key,
)


class LegendUtilsTests(unittest.TestCase):
    def test_parse_legend_labels_preserves_positions(self) -> None:
        self.assertEqual(parse_legend_labels("Alpha, ,Gamma"), ["Alpha", "", "Gamma"])

    def test_apply_legend_labels_overrides_only_non_empty_entries(self) -> None:
        resolved = apply_legend_labels(
            ["Gain A", "Gain B", "Gain C"],
            ["Horizontal", "", "Combined"],
        )

        self.assertEqual(resolved, ["Horizontal", "Gain B", "Combined"])

    def test_detect_polarization_handles_horizontal_and_vertical_sheet_names(self) -> None:
        self.assertEqual(detect_polarization("SH30WB_Horizontal"), "H")
        self.assertEqual(detect_polarization("LPDA-03-3_Vertical"), "V")

    def test_polarization_sort_key_prioritizes_horizontal_then_vertical(self) -> None:
        names = ["Example_Vertical", "Example_Unknown", "Example_Horizontal"]

        self.assertEqual(sorted(names, key=polarization_sort_key), ["Example_Horizontal", "Example_Vertical", "Example_Unknown"])

    def test_default_gain_and_beamwidth_labels_match_requested_format(self) -> None:
        self.assertEqual(gain_legend_label("SH30WB_Horizontal"), "Gain H (IEEE)")
        self.assertEqual(gain_legend_label("SH30WB_Vertical"), "Gain V (IEEE)")
        self.assertEqual(beamwidth_legend_label("SH30WB_Horizontal", "Azimuth"), "Beamwidth Azimuth H -6 dB")
        self.assertEqual(beamwidth_legend_label("SH30WB_Vertical", "Elevation"), "Beamwidth Elevation V -6 dB")

    def test_default_polar_label_includes_plane_and_frequency(self) -> None:
        self.assertEqual(
            polar_legend_label("SH30WB_Horizontal", "Azimuth", "5.5 GHz"),
            "H - Port Pattern Azimuth 5.5 GHz",
        )
        self.assertEqual(
            polar_legend_label("SH30WB_Vertical", "Elevation", "5.5 GHz"),
            "V - Port Pattern Elevation 5.5 GHz",
        )


if __name__ == "__main__":
    unittest.main()
