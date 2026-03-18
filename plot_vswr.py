#!/usr/bin/env python3
"""
plot_vswr.py  — VSWR plotting with unified styling

Matches the styling used in the user's plotting framework (plot.py):
- Global color scheme (kept from gain plot)
- Grid/axes color, minimalist spines
- Legend outside the plot, custom handle length & text color
- Optional smoothing and tick controls

Usage:
  python plot_vswr.py input.s1p --output vswr.svg
  python plot_vswr.py input.s2p --fmin 4.5GHz --fmax 8GHz --ymin 1 --ymax 10
  python plot_vswr.py input.s1p --x-step 0.2 --y-step 1 --smooth-window 5

Author: ChatGPT
"""

import argparse
import math
from pathlib import Path
from typing import List, Tuple
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, FixedFormatter, FixedLocator, NullFormatter, NullLocator

# ------------------ global color scheme (kept from gain plot) ------------------
DEFAULT_SOLID_COLORS = ["#2bb6f6", "#f5a623"]
SOLID_COLORS = DEFAULT_SOLID_COLORS[:]
DASHED_COLORS = SOLID_COLORS[:]  # same hues for dashed variants

def color_for_index(style: str, idx: int) -> str:
    base = SOLID_COLORS if style == '-' else DASHED_COLORS
    return base[idx % len(base)] if base else None


def set_line_colors(colors: list[str]) -> None:
    clean = [c.strip() for c in colors if c and c.strip()]
    palette = clean or DEFAULT_SOLID_COLORS[:]
    SOLID_COLORS[:] = palette
    DASHED_COLORS[:] = palette[:]

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


def format_frequency_tick(value: float, _pos=None) -> str:
    if not np.isfinite(value):
        return ""
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    if "." not in text:
        text += ".0"
    return text


def apply_frequency_ticks(ax, ticks: np.ndarray | None, x_log: bool) -> None:
    if ticks is not None:
        ticks = np.asarray(ticks, dtype=float)
        ax.xaxis.set_major_locator(FixedLocator(ticks))
        ax.xaxis.set_major_formatter(FixedFormatter([format_frequency_tick(v) for v in ticks]))
    else:
        ax.xaxis.set_major_formatter(FuncFormatter(format_frequency_tick))
    if x_log:
        ax.xaxis.set_minor_formatter(NullFormatter())
        if ticks is not None:
            ax.xaxis.set_minor_locator(NullLocator())
        ax.get_xaxis().get_offset_text().set_visible(False)

def read_touchstone(filepath: str) -> Tuple[np.ndarray, np.ndarray, str, float, int]:
    """Return (freqs_Hz, data, fmt, z0, nports) for .s1p/.s2p Touchstone files."""
    freqs = []
    rows: List[List[float]] = []
    fmt = None
    z0 = 50.0
    f_unit = "hz"
    ext = Path(filepath).suffix.lower()
    if ext == ".s1p":
        expected_values = 2
        nports = 1
    elif ext == ".s2p":
        expected_values = 8
        nports = 2
    else:
        expected_values = None
        nports = 0

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("!"):
                continue
            if line.startswith("#"):
                parts = [p for p in line.split() if p.strip()]
                if len(parts) >= 4:
                    f_unit = parts[1].lower()
                    fmt = parts[3].upper()
                if len(parts) >= 6 and parts[4].upper() == "R":
                    try: z0 = float(parts[5])
                    except: pass
                continue
            parts = line.split()
            try:
                freqs.append(float(parts[0]))
                values = [float(x) for x in parts[1:]]
                if expected_values is None:
                    if len(values) >= 8:
                        expected_values = 8
                        nports = 2
                    elif len(values) >= 2:
                        expected_values = 2
                        nports = 1
                    else:
                        continue
                if len(values) < expected_values:
                    continue
                rows.append(values[:expected_values])
            except:  # skip malformed lines
                continue

    freqs = np.array(freqs, dtype=float)
    data  = np.array(rows, dtype=float)
    unit_map = {"hz":1.0, "khz":1e3, "mhz":1e6, "ghz":1e9}
    freqs_hz = freqs * unit_map.get(f_unit, 1.0)
    if fmt is None:
        raise ValueError("Could not detect format from header (# <unit> S <MA|RI|DB> R <Z0>)")
    if nports not in (1, 2):
        raise ValueError("Only .s1p and .s2p Touchstone files are supported.")
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

def smooth_series(y: np.ndarray, window: int) -> np.ndarray:
    """Centered moving average; window<=1 disables smoothing."""
    if window is None or window <= 1:
        return np.asarray(y, dtype=float)
    import pandas as pd
    return pd.Series(y, dtype="float64").rolling(window=window, center=True, min_periods=1).mean().to_numpy()


def parse_color_list(raw: str | None) -> list[str]:
    if not raw:
        return DEFAULT_SOLID_COLORS[:]
    return [item.strip() for item in raw.split(",") if item.strip()] or DEFAULT_SOLID_COLORS[:]


def build_step_ticks(xmin: float, xmax: float, step: float) -> np.ndarray | None:
    if step is None or not np.isfinite(step) or step <= 0:
        return None
    eps = max(abs(step), 1.0) * 1e-9
    start = math.ceil((xmin - eps) / step) * step
    ticks = np.arange(start, xmax + eps, step)
    if ticks.size == 0:
        ticks = np.array([xmin, xmax], dtype=float)
    ticks = np.round(ticks, 10)
    if not np.isclose(ticks[0], xmin, atol=eps, rtol=0.0):
        ticks = np.insert(ticks, 0, round(float(xmin), 10))
    if not np.isclose(ticks[-1], xmax, atol=eps, rtol=0.0):
        ticks = np.append(ticks, round(float(xmax), 10))
    return ticks

# ------------------ shared plotting utility (cartesian) ------------------

def plot_xy(x, series_list, names, out_path, y_label,
            grid_color="#6f7a81", styles=None, colors=None,
            y_min=None, y_max=None, y_step=None,
            smooth_window: int = 5, x_step: float = None, x_ticks=None,
            x_log: bool = False, x_min: float | None = None, x_max: float | None = None):
    fig, ax = plt.subplots(figsize=(12, 4.2), dpi=120)
    ax.set_facecolor("white")
    ax.grid(True, which="both", axis="both", color=grid_color, linewidth=0.9)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_color(grid_color)
        spine.set_linewidth(0.9)

    xmin = float(x_min) if x_min is not None else float(np.nanmin(x))
    xmax = float(x_max) if x_max is not None else float(np.nanmax(x))
    if x_log:
        ax.set_xscale("log")
    ax.set_xlim(xmin, xmax)
    ticks = None
    if x_ticks is not None:
        ticks = np.asarray(x_ticks, dtype=float)
    elif x_step is not None and np.isfinite(xmin) and np.isfinite(xmax):
        ticks = build_step_ticks(float(xmin), float(xmax), float(x_step))
    apply_frequency_ticks(ax, ticks, x_log)
    ax.set_xlim(xmin, xmax)

    if y_min is not None and y_max is not None:
        ax.set_ylim(y_min, y_max)
    if y_step is not None and y_min is not None and y_max is not None:
        ax.set_yticks(np.arange(y_min, y_max + 1e-9, y_step))

    ax.set_xlabel("Frequency / GHz", color=grid_color)
    ax.set_ylabel(y_label, color=grid_color)
    ax.tick_params(colors=grid_color)

    lines = []
    for i, y in enumerate(series_list):
        ysm = smooth_series(np.asarray(y, dtype=float), window=smooth_window)
        st_in = styles[i] if styles and i < len(styles) else "-"
        color_in = colors[i] if colors and i < len(colors) else None
        ln, = ax.plot(x, ysm, linewidth=2.0, linestyle=st_in, solid_capstyle="round", color=color_in)
        lines.append(ln)

    # legend with explicit dash preview (even though VSWR lines are solid, we keep consistency)
    handles = []
    for ln in lines:
        st = ln.get_linestyle()
        c = ln.get_color()
        if st == "--":
            h = Line2D([0],[0], color=c, lw=2.0, linestyle='-', dashes=[8,6,8,6,8,6], dash_capstyle="round")
        else:
            h = Line2D([0],[0], color=c, lw=2.0, linestyle='-')
        handles.append(h)

    leg = ax.legend(handles, names, loc="center left", bbox_to_anchor=(1.02, 0.5),
                    frameon=False, handlelength=7, handletextpad=1.0)
    for text in leg.get_texts():
        text.set_color("#8a949c")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(out_path, format="svg", bbox_inches="tight")
    plt.close()
    return out_path


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
    p.add_argument("--output", default=None, help="Output SVG filename or path (default: <input_basename>_vswr.svg)")
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
    p.add_argument("--line-colors", default=None, help="Comma-separated colors for the port traces.")
    args = p.parse_args()

    set_line_colors(parse_color_list(args.line_colors))

    freqs_hz, data, fmt, z0, nports = read_touchstone(args.input)
    traces = [
        np.array([pair_to_complex(r[0], r[1], fmt) for r in data], dtype=complex)
    ]
    names = ["Port 1 (S11)"]
    if nports >= 2:
        traces.append(np.array([pair_to_complex(r[6], r[7], fmt) for r in data], dtype=complex))
        names.append("Port 2 (S22)")

    # Determine default filename
    in_path = Path(args.input)
    if args.output is None:
        out_file = in_path.stem + "_vswr.svg"
        out_path = (Path(args.out_dir) / out_file) if args.out_dir else in_path.with_name(out_file)
    else:
        output_path = Path(args.output)
        if args.out_dir:
            out_path = Path(args.out_dir) / output_path.name
        elif output_path.is_absolute() or output_path.parent != Path("."):
            out_path = output_path
        else:
            out_path = in_path.with_name(output_path.name)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Frequency range
    fmin_hz = args.fmin * 1e9 if args.fmin is not None else None
    fmax_hz = args.fmax * 1e9 if args.fmax is not None else None
    f_plot, series, x_axis_min, x_axis_max = build_windowed_vswr_series(freqs_hz, traces, fmin_hz, fmax_hz)
    styles = ["-"] * len(series)
    colors = [color_for_index("-", i) for i in range(len(series))]

    plot_xy(
        f_plot, series, names, out_path, y_label="VSWR",
        grid_color=args.grid_color, styles=styles, colors=colors,
        y_min=args.ymin, y_max=args.ymax, y_step=args.y_step,
        smooth_window=args.smooth_window, x_step=args.x_step, x_log=args.x_log,
        x_min=x_axis_min, x_max=x_axis_max,
    )
    print(f"Saved: {out_path}")

if __name__ == "__main__":
    main()
