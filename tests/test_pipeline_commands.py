from __future__ import annotations

import unittest
from pathlib import Path

from pipeline.commands import build_plot_command, build_vswr_command
from pipeline.run_context import RunContext
from pipeline.settings import PresetSettings


class PipelineCommandTests(unittest.TestCase):
    def test_preset_settings_normalize_legacy_plot_keys(self) -> None:
        settings = PresetSettings.from_mapping(
            {
                "plot_line_width": 3.5,
                "plot_grid_line_width": 1.25,
                "plot_font_size": 12,
                "plot_legend_font_size": 9,
                "plot_line_1": "#abcdef",
                "plot_line_2": "#123456",
            }
        )

        self.assertEqual(settings.cartesian_line_width, 3.5)
        self.assertEqual(settings.polar_line_width, 3.5)
        self.assertEqual(settings.cartesian_grid_line_width, 1.25)
        self.assertEqual(settings.polar_grid_line_width, 1.25)
        self.assertEqual(settings.cartesian_font_size, 12.0)
        self.assertEqual(settings.polar_font_size, 12.0)
        self.assertEqual(settings.cartesian_legend_font_size, 9.0)
        self.assertEqual(settings.polar_legend_font_size, 9.0)
        self.assertEqual(settings.polar_azimuth_line_1_color, "#abcdef")
        self.assertEqual(settings.polar_elevation_line_2_color, "#123456")

    def test_plot_command_uses_typed_settings(self) -> None:
        settings = PresetSettings(
            plot_line_1="#111111",
            plot_line_2="#222222",
            beamwidth_3db_color="#333333",
            beamwidth_6db_color="#444444",
            beamwidth_10db_color="#555555",
            polar_azimuth_line_1_color="#666666",
            polar_azimuth_line_2_color="#777777",
            polar_elevation_line_1_color="#888888",
            polar_elevation_line_2_color="#999999",
            polar_azimuth_line_1_style="dashed",
            polar_azimuth_line_2_style="solid",
            polar_elevation_line_1_style="solid",
            polar_elevation_line_2_style="dashed",
            cartesian_figure_width=9.25,
            cartesian_figure_height=3.75,
            polar_figure_size=7.5,
            shared_fmin=0.3,
            shared_fmax=3.0,
            shared_xlog=True,
            gain_legend_labels="Gain A",
        )

        command = build_plot_command(
            python_executable="python",
            script_path="plot.py",
            input_workbook="input.xlsx",
            out_dir="out",
            settings=settings,
            polar_port_labels_json='{"file.ffs":"H"}',
        )

        self.assertEqual(command[command.index("--cartesian-figure-width") + 1], "9.25")
        self.assertEqual(command[command.index("--cartesian-figure-height") + 1], "3.75")
        self.assertEqual(command[command.index("--polar-figure-size") + 1], "7.5")
        self.assertEqual(command[command.index("--polar-line-colors") + 1], "#666666,#777777,#888888,#999999")
        self.assertEqual(command[command.index("--polar-line-styles") + 1], "dashed,solid,solid,dashed")
        self.assertEqual(command[command.index("--beamwidth-db-colors") + 1], "#333333,#444444,#555555")
        self.assertEqual(command[command.index("--polar-port-labels-json") + 1], '{"file.ffs":"H"}')
        self.assertIn("--x-log", command)
        self.assertEqual(command[command.index("--fmin") + 1], "0.3")
        self.assertEqual(command[command.index("--gain-legend-labels") + 1], "Gain A")

    def test_vswr_command_uses_typed_settings(self) -> None:
        settings = PresetSettings(
            plot_line_1="#111111",
            plot_line_2="#222222",
            cartesian_figure_width=9.25,
            cartesian_figure_height=3.75,
            vswr_ymin=1.0,
            vswr_ymax=4.0,
            vswr_ystep=0.5,
            vswr_smooth=7,
            vswr_legend_labels="Port 1",
        )

        command = build_vswr_command(
            python_executable="python",
            script_path="plot_vswr.py",
            touchstone_path="input.s1p",
            output_path="out.svg",
            settings=settings,
        )

        self.assertEqual(command[command.index("--cartesian-figure-width") + 1], "9.25")
        self.assertEqual(command[command.index("--cartesian-figure-height") + 1], "3.75")
        self.assertEqual(command[command.index("--line-colors") + 1], "#111111,#222222")
        self.assertEqual(command[command.index("--ymax") + 1], "4.0")
        self.assertEqual(command[command.index("--smooth-window") + 1], "7")
        self.assertEqual(command[command.index("--legend-labels") + 1], "Port 1")

    def test_commands_accept_run_context(self) -> None:
        settings = PresetSettings(plot_line_1="#101010", plot_line_2="#202020")
        context = RunContext(
            project_slug="demo",
            project_dir=Path("project"),
            beam_output=Path("project/demo.xlsx"),
            extract_output=Path("project/demo-extracted-data.xlsx"),
            datasheet_output=Path("project/demo-datasheet.pdf"),
            vswr_output=Path("project/demo-vswr.svg"),
            settings=settings,
            polar_port_labels_json='{"one.ffs":"P1"}',
            touchstone_path="Input data/demo.s2p",
        )

        plot_command = build_plot_command(
            python_executable="python",
            script_path="plot.py",
            context=context,
        )
        self.assertIn(str(context.beam_output), plot_command)
        self.assertIn("project", plot_command)
        self.assertEqual(plot_command[plot_command.index("--polar-port-labels-json") + 1], '{"one.ffs":"P1"}')

        vswr_command = build_vswr_command(
            python_executable="python",
            script_path="plot_vswr.py",
            context=context,
        )
        self.assertIn("Input data/demo.s2p", vswr_command)
        self.assertIn(str(context.vswr_output), vswr_command)


if __name__ == "__main__":
    unittest.main()
