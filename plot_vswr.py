#!/usr/bin/env python3
"""
plot_vswr.py  — VSWR plotting with unified styling

Matches the styling used in the user's plotting framework (plot.py):
- Global color scheme (kept from gain plot)
- Grid/axes color, minimalist spines
- Separate legend SVG with the same styling as the plot legend
- Optional smoothing and tick controls

Usage:
  python plot_vswr.py input.s1p --output vswr.svg
  python plot_vswr.py input.s2p --fmin 4.5GHz --fmax 8GHz --ymin 1 --ymax 10
  python plot_vswr.py input.s1p --x-step 0.2 --y-step 1 --smooth-window 5

Author: ChatGPT
"""

import argparse
import json
import math
from pathlib import Path
from typing import List, Tuple
import numpy as np
from plot import (
    CARTESIAN_FIGURE_HEIGHT_IN,
    CARTESIAN_FIGURE_WIDTH_IN,
    DEFAULT_PLOT_FONT_SIZE,
    DEFAULT_LEGEND_FONT_SIZE,
    DEFAULT_GRID_LINE_WIDTH,
    DEFAULT_PLOT_LINE_WIDTH,
    STACKED_LEGEND_ENTRY_SEP,
    STACKED_LEGEND_ROW_SEP,
    export_stacked_line_legend,
)
from datasheet.artifacts import (
    artifact_manifest_path,
    build_asset_record,
    load_artifact_manifest,
    save_artifact_manifest,
    update_artifact_manifest,
)
from legend_utils import apply_legend_labels, parse_legend_labels
from pipeline.atomic import StageWorkspace
from pipeline.progress import emit_progress
from plotting.cartesian import render_cartesian_plot
from plotting.common import (
    color_for_index as _color_for_index,
    parse_color_list as _parse_color_list,
    set_line_colors as _set_line_colors,
)

# ------------------ global color scheme (kept from gain plot) ------------------
DEFAULT_SOLID_COLORS = ["#2bb6f6", "#f5a623"]
SOLID_COLORS = DEFAULT_SOLID_COLORS[:]
DASHED_COLORS = SOLID_COLORS[:]  # same hues for dashed variants


class TouchstoneParseError(ValueError):
    pass

def color_for_index(style: str, idx: int) -> str:
    return _color_for_index(style, idx, SOLID_COLORS, DASHED_COLORS)


def set_line_colors(colors: list[str]) -> None:
    _set_line_colors(colors, DEFAULT_SOLID_COLORS, SOLID_COLORS, DASHED_COLORS)

# ------------------ parsing & math ------------------

def parse_freq_with_units(s: str) -> float:
    """Parse frequency strings with unit suffix to Hz. e.g., 4.5GHz, 4500MHz, 6g"""
    s = s.strip().lower().replace(" ", "")
    mult = 1.0
    if s.endswith("hz"):
        if s.endswith("khz"):
            mult = 1e3; s = s[:-3]
        elif s.endswith("mhz"):
            mult = 1e6; s = s[:-3]
        elif s.endswith("ghz"):
            mult = 1e9; s = s[:-3]
        else:
            s = s[:-2]
    elif s.endswith("k"):
        mult = 1e3; s = s[:-1]
    elif s.endswith("m"):
        mult = 1e6; s = s[:-1]
    elif s.endswith("g"):
        mult = 1e9; s = s[:-1]
    return float(s) * mult


def read_touchstone(filepath: str) -> Tuple[np.ndarray, np.ndarray, str, float, int]:
    """Return (freqs_Hz, data, fmt, z0, nports) for .s1p/.s2p Touchstone files."""
    freqs: list[float] = []
    rows: List[List[float]] = []
    fmt: str | None = None
    z0 = 50.0
    f_unit = ""
    ext = Path(filepath).suffix.lower()
    if ext == ".s1p":
        nports = 1
    elif ext == ".s2p":
        nports = 2
    else:
        raise TouchstoneParseError("Only .s1p and .s2p Touchstone files are supported.")

    record_width = 1 + (2 * nports * nports)
    pending: list[float] = []
    header_seen = False

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        for line_number, raw in enumerate(f, start=1):
            line = raw.split("!", 1)[0].strip()
            if not line:
                continue
            if line.startswith("["):
                raise TouchstoneParseError("Touchstone 2.0 syntax is not supported; use a v1-style .s1p or .s2p file.")
            if line.startswith("#"):
                if pending:
                    raise TouchstoneParseError(f"Line {line_number}: incomplete data record before option line.")
                parts = line[1:].split()
                if len(parts) != 5 or parts[3].upper() != "R":
                    raise TouchstoneParseError("Option line must be '# <unit> S <MA|RI|DB> R <impedance>'.")
                f_unit = parts[0].lower()
                if f_unit not in {"hz", "khz", "mhz", "ghz"}:
                    raise TouchstoneParseError(f"Unsupported Touchstone frequency unit: {parts[0]}")
                if parts[1].upper() != "S":
                    raise TouchstoneParseError("Only S-parameter Touchstone data is supported.")
                fmt = parts[2].upper()
                if fmt not in {"MA", "RI", "DB"}:
                    raise TouchstoneParseError(f"Unsupported Touchstone data format: {parts[2]}")
                try:
                    z0 = float(parts[4])
                except ValueError as exc:
                    raise TouchstoneParseError("Reference impedance must be numeric.") from exc
                if not math.isfinite(z0) or z0 <= 0:
                    raise TouchstoneParseError("Reference impedance must be finite and positive.")
                header_seen = True
                continue

            if not header_seen:
                raise TouchstoneParseError("Touchstone option line is missing before network data.")
            try:
                values = [float(token) for token in line.split()]
            except ValueError as exc:
                raise TouchstoneParseError(f"Line {line_number}: network data must be numeric.") from exc
            if not all(math.isfinite(value) for value in values):
                raise TouchstoneParseError(f"Line {line_number}: network data contains a non-finite value.")
            pending.extend(values)
            while len(pending) >= record_width:
                record = pending[:record_width]
                del pending[:record_width]
                freqs.append(record[0])
                rows.append(record[1:])

    if pending:
        raise TouchstoneParseError(f"Incomplete Touchstone record: expected {record_width} numeric values per sample.")
    if not header_seen or fmt is None:
        raise TouchstoneParseError("Could not detect Touchstone option line.")
    if not rows:
        raise TouchstoneParseError("Touchstone file contains no network data records.")

    freqs_array = np.asarray(freqs, dtype=float)
    data = np.asarray(rows, dtype=float)
    unit_map = {"hz":1.0, "khz":1e3, "mhz":1e6, "ghz":1e9}
    freqs_hz = freqs_array * unit_map[f_unit]
    if not np.isfinite(freqs_hz).all() or np.any(freqs_hz <= 0):
        raise TouchstoneParseError("Touchstone frequencies must be finite and positive.")
    order = np.argsort(freqs_hz, kind="stable")
    freqs_hz = freqs_hz[order]
    data = data[order]
    if np.any(np.diff(freqs_hz) == 0):
        raise TouchstoneParseError("Touchstone file contains duplicate frequencies.")
    if freqs_hz.shape[0] != data.shape[0]:
        raise TouchstoneParseError("Touchstone frequency and data row counts do not match.")
    return freqs_hz, data, fmt, z0, nports

def pair_to_complex(a: float, b: float, fmt: str) -> complex:
    """Convert (a,b) according to Touchstone fmt to complex number."""
    fmt = fmt.upper()
    if fmt == "MA":
        return a * math.e**(1j * math.radians(b))
    elif fmt == "DB":
        return (10.0**(a/20.0)) * math.e**(1j * math.radians(b))
    elif fmt == "RI":
        return complex(a, b)
    raise ValueError(f"Unsupported format: {fmt}")

def calc_vswr(gamma: np.ndarray) -> np.ndarray:
    """VSWR = (1+|Γ|)/(1-|Γ|), with |Γ| clipped below 1 for stability."""
    mag = np.abs(gamma)
    mag = np.clip(mag, 0, 0.999999)
    return (1 + mag) / (1 - mag)

def parse_color_list(raw: str | None) -> list[str]:
    return _parse_color_list(raw, DEFAULT_SOLID_COLORS)

# ------------------ shared plotting utility (cartesian) ------------------

def plot_xy(x, series_list, names, out_path, y_label,
            grid_color="#6f7a81", styles=None, colors=None,
            y_min=None, y_max=None, y_step=None,
            smooth_window: int = 5, x_step: float = None, x_ticks=None,
            x_log: bool = False, x_min: float | None = None, x_max: float | None = None,
            font_size: float = DEFAULT_PLOT_FONT_SIZE, legend_font_size: float = DEFAULT_LEGEND_FONT_SIZE,
            grid_line_width: float = DEFAULT_GRID_LINE_WIDTH,
            line_width: float = DEFAULT_PLOT_LINE_WIDTH,
            figure_width: float = CARTESIAN_FIGURE_WIDTH_IN,
            figure_height: float = CARTESIAN_FIGURE_HEIGHT_IN):
    return render_cartesian_plot(
        x,
        series_list,
        names,
        out_path,
        y_label,
        export_legend=export_stacked_line_legend,
        grid_color=grid_color,
        styles=styles,
        colors=colors,
        y_min=y_min,
        y_max=y_max,
        y_step=y_step,
        smooth_window=smooth_window,
        x_step=x_step,
        x_ticks=x_ticks,
        x_log=x_log,
        x_min=x_min,
        x_max=x_max,
        font_size=font_size,
        legend_font_size=legend_font_size,
        grid_line_width=grid_line_width,
        line_width=line_width,
        legend_line_width=line_width,
        legend_row_sep=STACKED_LEGEND_ROW_SEP,
        legend_entry_sep=STACKED_LEGEND_ENTRY_SEP,
        figure_width=figure_width,
        figure_height=figure_height,
    )


def interpolate_complex_trace(freqs_hz: np.ndarray, trace: np.ndarray, target_hz: float) -> complex:
    real = np.interp(target_hz, freqs_hz, trace.real)
    imag = np.interp(target_hz, freqs_hz, trace.imag)
    return complex(real, imag)


def build_windowed_vswr_series(
    freqs_hz: np.ndarray,
    traces: list[np.ndarray],
    fmin_hz: float | None,
    fmax_hz: float | None,
) -> tuple[np.ndarray, list[np.ndarray], float, float]:
    data_min = float(np.nanmin(freqs_hz))
    data_max = float(np.nanmax(freqs_hz))
    plot_min = float(fmin_hz) if fmin_hz is not None else data_min
    plot_max = float(fmax_hz) if fmax_hz is not None else data_max
    if plot_max <= plot_min:
        raise SystemExit("The selected frequency window is invalid: fmax must be greater than fmin.")

    overlap_min = max(plot_min, data_min)
    overlap_max = min(plot_max, data_max)
    if overlap_max < overlap_min:
        raise SystemExit("The selected frequency window does not overlap the Touchstone data range.")

    inner_mask = (freqs_hz > overlap_min) & (freqs_hz < overlap_max)
    points_hz: list[float] = []
    if data_min <= overlap_min <= data_max:
        points_hz.append(float(overlap_min))
    points_hz.extend(freqs_hz[inner_mask].astype(float).tolist())
    if overlap_max > overlap_min and data_min <= overlap_max <= data_max:
        points_hz.append(float(overlap_max))

    if not points_hz:
        points_hz = [float(overlap_min)]
        if overlap_max > overlap_min:
            points_hz.append(float(overlap_max))

    x_window_hz = np.array(points_hz, dtype=float)
    x_window_hz = np.unique(np.round(x_window_hz, 6))
    series = []
    for trace in traces:
        values = np.array(
            [calc_vswr(np.array([interpolate_complex_trace(freqs_hz, trace, hz)], dtype=complex))[0] for hz in x_window_hz],
            dtype=float,
        )
        series.append(values)
    return x_window_hz / 1e9, series, plot_min / 1e9, plot_max / 1e9

# ------------------ main ------------------

def main():
    p = argparse.ArgumentParser(description="Generate an SVG VSWR plot from a .s1p or .s2p file (styled).")
    p.add_argument("input", help="Input .s1p or .s2p path")
    p.add_argument("--output", default=None, help="Output SVG filename or path (default: <input_basename>-vswr.svg)")
    p.add_argument("--out-dir", default=None, help="Directory to save the output file")
    p.add_argument("--fmin", type=float, default=None, help="Min frequency in GHz (e.g., 4.5)")
    p.add_argument("--fmax", type=float, default=None, help="Max frequency in GHz (e.g., 8)")
    p.add_argument("--ymin", type=float, default=None, help="Y-axis min (e.g., 1)")
    p.add_argument("--ymax", type=float, default=None, help="Y-axis max (e.g., 10)")
    p.add_argument("--y-step", type=float, default=None, help="Y tick step")
    p.add_argument("--x-step", type=float, default=None, help="X tick step in GHz")
    p.add_argument("--x-log", action="store_true", help="Use logarithmic scaling on the x-axis.")
    p.add_argument("--smooth-window", type=int, default=5, help="Centered moving-average window (points). Use 1 to disable.")
    p.add_argument("--grid-color", default="#6f7a81", help="Grid/axis color (hex).")
    p.add_argument("--grid-line-width", type=float, default=None, help=argparse.SUPPRESS)
    p.add_argument("--cartesian-grid-line-width", type=float, default=None, help="Line width used for VSWR grid lines, axes, and tick marks.")
    p.add_argument("--line-colors", default=None, help="Comma-separated colors for the port traces.")
    p.add_argument("--line-width", type=float, default=None, help=argparse.SUPPRESS)
    p.add_argument("--cartesian-line-width", type=float, default=None, help="Line width used for VSWR traces and legend.")
    p.add_argument("--cartesian-figure-width", type=float, default=None, help="Figure width in inches for the VSWR plot.")
    p.add_argument("--cartesian-figure-height", type=float, default=None, help="Figure height in inches for the VSWR plot.")
    p.add_argument("--font-size", type=float, default=None, help=argparse.SUPPRESS)
    p.add_argument("--cartesian-font-size", type=float, default=None, help="Base font size used for VSWR labels and tick labels.")
    p.add_argument("--legend-font-size", type=float, default=None, help=argparse.SUPPRESS)
    p.add_argument("--cartesian-legend-font-size", type=float, default=None, help="Font size used for the exported VSWR legend.")
    p.add_argument("--legend-labels", default=None, help="Comma-separated legend overrides for VSWR traces, in plotted series order.")
    args = p.parse_args()

    set_line_colors(parse_color_list(args.line_colors))
    cartesian_grid_line_width = float(args.cartesian_grid_line_width if args.cartesian_grid_line_width is not None else (args.grid_line_width if args.grid_line_width is not None else DEFAULT_GRID_LINE_WIDTH))
    cartesian_line_width = float(args.cartesian_line_width if args.cartesian_line_width is not None else (args.line_width if args.line_width is not None else DEFAULT_PLOT_LINE_WIDTH))
    cartesian_figure_width = float(args.cartesian_figure_width if args.cartesian_figure_width is not None else CARTESIAN_FIGURE_WIDTH_IN)
    cartesian_figure_height = float(args.cartesian_figure_height if args.cartesian_figure_height is not None else CARTESIAN_FIGURE_HEIGHT_IN)
    cartesian_font_size = float(args.cartesian_font_size if args.cartesian_font_size is not None else (args.font_size if args.font_size is not None else DEFAULT_PLOT_FONT_SIZE))
    cartesian_legend_font_size = float(args.cartesian_legend_font_size if args.cartesian_legend_font_size is not None else (args.legend_font_size if args.legend_font_size is not None else DEFAULT_LEGEND_FONT_SIZE))

    freqs_hz, data, fmt, z0, nports = read_touchstone(args.input)
    traces = [
        np.array([pair_to_complex(r[0], r[1], fmt) for r in data], dtype=complex)
    ]
    names = ["Port 1 (S11)"]
    if nports >= 2:
        traces.append(np.array([pair_to_complex(r[6], r[7], fmt) for r in data], dtype=complex))
        names.append("Port 2 (S22)")
    names = apply_legend_labels(names, parse_legend_labels(args.legend_labels))

    # Determine default filename
    in_path = Path(args.input)
    if args.output is None:
        out_file = in_path.stem + "-vswr.svg"
        out_path = (Path(args.out_dir) / out_file) if args.out_dir else in_path.with_name(out_file)
    else:
        output_path = Path(args.output)
        if args.out_dir:
            out_path = Path(args.out_dir) / output_path.name
        elif output_path.is_absolute() or output_path.parent != Path("."):
            out_path = output_path
        else:
            out_path = in_path.with_name(output_path.name)
    final_out_path = out_path.resolve()
    final_out_path.parent.mkdir(parents=True, exist_ok=True)
    stage = StageWorkspace(final_out_path.parent, "vswr")
    out_path = stage.path(final_out_path.name)

    # Frequency range
    fmin_hz = args.fmin * 1e9 if args.fmin is not None else None
    fmax_hz = args.fmax * 1e9 if args.fmax is not None else None
    f_plot, series, x_axis_min, x_axis_max = build_windowed_vswr_series(freqs_hz, traces, fmin_hz, fmax_hz)
    styles = ["-"] * len(series)
    colors = [color_for_index("-", i) for i in range(len(series))]

    emit_progress("vswr", 1, 2, f"Rendering {out_path.name}")
    out_path, legend_path = plot_xy(
        f_plot,
        series,
        names,
        out_path,
        y_label="VSWR",
        grid_color=args.grid_color,
        styles=styles,
        colors=colors,
        y_min=args.ymin,
        y_max=args.ymax,
        y_step=args.y_step,
        smooth_window=args.smooth_window,
        x_step=args.x_step,
        x_log=args.x_log,
        x_min=x_axis_min,
        x_max=x_axis_max,
        font_size=cartesian_font_size,
        legend_font_size=cartesian_legend_font_size,
        grid_line_width=cartesian_grid_line_width,
        line_width=cartesian_line_width,
        figure_width=cartesian_figure_width,
        figure_height=cartesian_figure_height,
    )
    emit_progress("vswr", 2, 2, f"Saving {out_path.name}")
    bookstem = out_path.stem[:-5] if out_path.stem.endswith("-vswr") else out_path.stem
    update_artifact_manifest(
        out_path.parent,
        bookstem,
        vswr=build_asset_record(out_path, legend_path=legend_path),
    )
    staged_manifest_path = artifact_manifest_path(out_path.parent, bookstem)
    staged_manifest = load_artifact_manifest(staged_manifest_path, bookstem=bookstem)
    final_manifest_path = artifact_manifest_path(final_out_path.parent, bookstem)
    merged_manifest = load_artifact_manifest(final_manifest_path, bookstem=bookstem)
    merged_manifest.setdefault("charts", {})["vswr"] = staged_manifest.get("charts", {}).get("vswr")
    merged_text = json.dumps(merged_manifest).replace(str(stage.root), str(final_out_path.parent))
    save_artifact_manifest(staged_manifest_path, json.loads(merged_text))
    required = [final_out_path.name]
    final_legend_path = None
    if legend_path:
        final_legend_path = final_out_path.parent / Path(legend_path).name
        required.append(Path(legend_path).name)
    required.append(staged_manifest_path.name)
    obsolete = []
    expected_legend = final_out_path.with_name(f"{final_out_path.stem}-legend{final_out_path.suffix}")
    if final_legend_path is None and expected_legend.exists():
        obsolete.append(expected_legend.name)
    stage.publish(required, obsolete=obsolete)
    print(f"Saved: {final_out_path}")
    if final_legend_path:
        print(f"Saved: {final_legend_path}")

if __name__ == "__main__":
    main()
