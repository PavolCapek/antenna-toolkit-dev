from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from datasheet.specs import DatasheetSpecError, load_datasheet_spec, load_default_datasheet_specs


class DatasheetSpecTests(unittest.TestCase):
    def test_default_specs_load_current_compatibility_layouts(self) -> None:
        specs = load_default_datasheet_specs()

        self.assertIn("rfe", specs)
        self.assertIn("netqui", specs)
        self.assertIn("netqui_1pol", specs)
        self.assertIn("netqui_1pol_placeholder", specs)
        self.assertEqual(specs["rfe"].chart_layout.slot_order, "first_two_then_x")
        self.assertEqual(specs["netqui_1pol"].chart_layout.min_image_slots, 7)
        self.assertEqual(specs["netqui"].table.aliases[0].canonical_key, "frequency range")

    def test_json_spec_validation_reports_missing_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text(json.dumps({"key": "broken"}), encoding="utf-8")

            with self.assertRaisesRegex(DatasheetSpecError, "display_name"):
                load_datasheet_spec(path)

    def test_json_spec_loads_chart_slots_and_match_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "custom.json"
            path.write_text(
                json.dumps(
                    {
                        "key": "custom",
                        "display_name": "Custom Datasheet",
                        "layout_key": "custom_layout",
                        "match": {"filename_tokens": ["custom"]},
                        "chart_layout": {
                            "min_image_slots": 1,
                            "slots": [{"kind": "gain", "slot_index": 0, "asset_key": "gain"}],
                        },
                    }
                ),
                encoding="utf-8",
            )

            spec = load_datasheet_spec(path)

        self.assertEqual(spec.key, "custom")
        self.assertEqual(spec.layout_key, "custom_layout")
        self.assertEqual(spec.match.filename_tokens, ("custom",))
        self.assertEqual(spec.chart_layout.slots[0].asset_key, "gain")


if __name__ == "__main__":
    unittest.main()
