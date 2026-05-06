from __future__ import annotations

import unittest
from pathlib import Path

from datasheet.asset_catalog import build_asset_catalog


class DatasheetAssetCatalogTests(unittest.TestCase):
    def test_catalog_builds_stable_items_from_current_manifest_keys(self) -> None:
        root = Path("C:/tmp/catalog")
        manifest = {
            "schema_version": 1,
            "bookstem": "sample",
            "charts": {
                "gain": {"svg": str(root / "sample-gain.svg"), "legend_svg": str(root / "sample-gain-legend.svg")},
                "beamwidth": {"svg": str(root / "sample-beamwidth.svg")},
                "beam_efficiency": {"svg": str(root / "sample-beam-efficiency.svg")},
                "vswr": {"svg": str(root / "sample-vswr.svg")},
                "beamwidth_planes": [
                    {
                        "svg": str(root / "sample-beamwidth-e-plane-h.svg"),
                        "legend_svg": str(root / "sample-beamwidth-e-plane-h-legend.svg"),
                        "plane": "e-plane",
                        "polarization": "H",
                    }
                ],
                "polar_combined": [
                    {
                        "svg": str(root / "sample-polar-4.900-GHz-combined.svg"),
                        "legend_svg": str(root / "sample-polar-4.900-GHz-combined-legend.svg"),
                        "frequency_ghz": 4.9,
                    }
                ],
                "polar_combined_planes": [
                    {
                        "svg": str(root / "sample-polar-7.125-GHz-e-h-plane-combined.svg"),
                        "legend_svg": str(root / "sample-polar-7.125-GHz-e-h-plane-combined-legend.svg"),
                        "plane_mode": "e-h-plane",
                        "frequency_ghz": 7.125,
                    }
                ],
                "polar_single": [
                    {
                        "svg": str(root / "sample-polar-azimuth-5.500-GHz.svg"),
                        "legend_svg": str(root / "sample-polar-azimuth-5.500-GHz-legend.svg"),
                        "plane": "azimuth",
                        "frequency_ghz": 5.5,
                    }
                ],
                "polar_planes": [
                    {
                        "svg": str(root / "sample-polar-h-plane-5.500-GHz.svg"),
                        "plane": "h-plane",
                        "frequency_ghz": 5.5,
                    }
                ],
            },
        }

        catalog = build_asset_catalog(manifest)
        by_id = catalog.by_id()

        self.assertEqual(
            sorted(by_id),
            [
                "beam_efficiency",
                "beamwidth",
                "beamwidth_planes__e-plane__h",
                "gain",
                "polar_combined__4p9ghz",
                "polar_combined_planes__e-h-plane__7p125ghz",
                "polar_planes__h-plane__5p5ghz",
                "polar_single__azimuth__5p5ghz",
                "vswr",
            ],
        )
        self.assertEqual(by_id["gain"].label, "Gain")
        self.assertEqual(by_id["gain"].chart_family, "gain")
        self.assertEqual(by_id["gain"].manifest_key, "gain")
        self.assertEqual(by_id["gain"].svg_path, root / "sample-gain.svg")
        self.assertEqual(by_id["gain"].legend_path, root / "sample-gain-legend.svg")
        self.assertEqual(by_id["beamwidth_planes__e-plane__h"].chart_family, "beamwidth")
        self.assertEqual(by_id["beamwidth_planes__e-plane__h"].plane, "e-plane")
        self.assertEqual(by_id["beamwidth_planes__e-plane__h"].polarization, "H")
        self.assertEqual(by_id["polar_single__azimuth__5p5ghz"].chart_family, "polar")
        self.assertEqual(by_id["polar_single__azimuth__5p5ghz"].frequency_ghz, 5.5)
        self.assertEqual(by_id["polar_combined_planes__e-h-plane__7p125ghz"].plane, "e-h-plane")
        self.assertEqual(catalog.by_manifest_key("polar_single"), (by_id["polar_single__azimuth__5p5ghz"],))

    def test_catalog_preserves_labels_and_legacy_legend_path_alias(self) -> None:
        manifest = {
            "charts": {
                "gain": {
                    "label": "Peak Gain",
                    "svg": "gain.svg",
                    "legend": "gain-legend.svg",
                },
                "beamwidth": None,
                "polar_single": [
                    {"legend_svg": "missing-svg-is-ignored.svg", "plane": "azimuth", "frequency_ghz": 5.5}
                ],
            }
        }

        catalog = build_asset_catalog(manifest)

        self.assertEqual(len(catalog.items), 1)
        self.assertEqual(catalog.items[0].asset_id, "gain")
        self.assertEqual(catalog.items[0].label, "Peak Gain")
        self.assertEqual(catalog.items[0].legend_path, Path("gain-legend.svg"))
        self.assertEqual(catalog.items[0].source_record["legend"], "gain-legend.svg")


if __name__ == "__main__":
    unittest.main()
