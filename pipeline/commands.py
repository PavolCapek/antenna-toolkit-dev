from __future__ import annotations

from pathlib import Path

from pipeline.run_context import RunContext
from pipeline.settings import PresetSettings


def _append_if_text(args: list[str], option: str, value: str) -> None:
    text = str(value or "").strip()
    if text:
        args.extend([option, text])


def _append_if_nonzero(args: list[str], option: str, value: float) -> None:
    if float(value) != 0.0:
        args.extend([option, f"{value}"])


def _append_frequency_window(args: list[str], settings: PresetSettings) -> None:
    if settings.shared_fmin > 0 and settings.shared_fmax > settings.shared_fmin:
        args.extend(["--fmin", f"{settings.shared_fmin}", "--fmax", f"{settings.shared_fmax}"])


def build_plot_command(
    *,
    python_executable: str,
    script_path: str,
    input_workbook: str | Path | None = None,
    out_dir: str | Path | None = None,
    settings: PresetSettings | None = None,
    polar_port_labels_json: str = "",
    context: RunContext | None = None,
) -> list[str]:
    if context is not None:
        input_workbook = context.beam_output
        out_dir = context.project_dir
        settings = context.settings
        polar_port_labels_json = context.polar_port_labels_json
    if input_workbook is None or out_dir is None or settings is None:
        raise ValueError("build_plot_command requires input_workbook, out_dir, and settings")
    args = [
        python_executable,
        "-u",
        script_path,
        str(input_workbook),
        "--out-dir",
        str(out_dir),
        "--grid-color",
        settings.grid_color,
        "--cartesian-grid-line-width",
        str(settings.cartesian_grid_line_width),
        "--polar-grid-line-width",
        str(settings.polar_grid_line_width),
        "--line-colors",
        ",".join([settings.plot_line_1, settings.plot_line_2]),
        "--beamwidth-db-colors",
        ",".join([settings.beamwidth_3db_color, settings.beamwidth_6db_color, settings.beamwidth_10db_color]),
        "--polar-line-colors",
        ",".join(
            [
                settings.polar_azimuth_line_1_color,
                settings.polar_azimuth_line_2_color,
                settings.polar_elevation_line_1_color,
                settings.polar_elevation_line_2_color,
            ]
        ),
        "--polar-line-styles",
        ",".join(
            [
                settings.polar_azimuth_line_1_style,
                settings.polar_azimuth_line_2_style,
                settings.polar_elevation_line_1_style,
                settings.polar_elevation_line_2_style,
            ]
        ),
        "--polar-port-labels-json",
        polar_port_labels_json,
        "--cartesian-line-width",
        str(settings.cartesian_line_width),
        "--cartesian-figure-width",
        str(settings.cartesian_figure_width),
        "--cartesian-figure-height",
        str(settings.cartesian_figure_height),
        "--polar-figure-size",
        str(settings.polar_figure_size),
        "--polar-line-width",
        str(settings.polar_line_width),
        "--cartesian-font-size",
        str(settings.cartesian_font_size),
        "--polar-font-size",
        str(settings.polar_font_size),
        "--cartesian-legend-font-size",
        str(settings.cartesian_legend_font_size),
        "--polar-legend-font-size",
        str(settings.polar_legend_font_size),
        "--rings",
        settings.rings,
        "--angle-step",
        str(settings.angle),
        "--clip-db",
        str(settings.clip),
        "--smooth-window",
        str(settings.smooth2),
        "--x-step",
        str(settings.shared_xstep),
    ]
    _append_if_text(args, "--gain-legend-labels", settings.gain_legend_labels)
    _append_if_text(args, "--beamwidth-legend-labels", settings.beamwidth_legend_labels)
    _append_if_text(args, "--beam-eff-legend-labels", settings.beam_eff_legend_labels)
    _append_if_nonzero(args, "--gain-ymin", settings.gain_ymin)
    _append_if_nonzero(args, "--gain-ymax", settings.gain_ymax)
    _append_if_nonzero(args, "--gain-y-step", settings.gain_y_step)
    _append_if_nonzero(args, "--beamwidth-ymin", settings.beamwidth_ymin)
    _append_if_nonzero(args, "--beamwidth-ymax", settings.beamwidth_ymax)
    _append_if_nonzero(args, "--beamwidth-y-step", settings.beamwidth_y_step)
    _append_if_nonzero(args, "--beam-eff-ymin", settings.beam_eff_ymin)
    _append_if_nonzero(args, "--beam-eff-ymax", settings.beam_eff_ymax)
    _append_if_nonzero(args, "--beam-eff-y-step", settings.beam_eff_y_step)
    if settings.shared_xlog:
        args.append("--x-log")
    _append_frequency_window(args, settings)
    return args


def build_vswr_command(
    *,
    python_executable: str,
    script_path: str,
    touchstone_path: str | Path | None = None,
    output_path: str | Path | None = None,
    settings: PresetSettings | None = None,
    context: RunContext | None = None,
) -> list[str]:
    if context is not None:
        touchstone_path = context.touchstone_path
        output_path = context.vswr_output
        settings = context.settings
    if touchstone_path is None or output_path is None or settings is None:
        raise ValueError("build_vswr_command requires touchstone_path, output_path, and settings")
    args = [
        python_executable,
        "-u",
        script_path,
        str(touchstone_path),
        "--output",
        str(output_path),
        "--grid-color",
        settings.grid_color,
        "--cartesian-grid-line-width",
        str(settings.cartesian_grid_line_width),
        "--line-colors",
        ",".join([settings.plot_line_1, settings.plot_line_2]),
        "--cartesian-line-width",
        str(settings.cartesian_line_width),
        "--cartesian-figure-width",
        str(settings.cartesian_figure_width),
        "--cartesian-figure-height",
        str(settings.cartesian_figure_height),
        "--cartesian-font-size",
        str(settings.cartesian_font_size),
        "--cartesian-legend-font-size",
        str(settings.cartesian_legend_font_size),
        "--x-step",
        str(settings.shared_xstep),
        "--ymin",
        str(settings.vswr_ymin),
        "--ymax",
        str(settings.vswr_ymax),
        "--y-step",
        str(settings.vswr_ystep),
        "--smooth-window",
        str(settings.vswr_smooth),
    ]
    _append_if_text(args, "--legend-labels", settings.vswr_legend_labels)
    if settings.shared_xlog:
        args.append("--x-log")
    _append_frequency_window(args, settings)
    return args
