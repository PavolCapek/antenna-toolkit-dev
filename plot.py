#!/usr/bin/env python3
"""
Plot generator for the provided results.xlsx layout.

Features:
- Optional frequency window via --fmin/--fmax (GHz).
  * If BOTH bounds are provided and lie within available data, cartesian plots are cropped
    and polar plots are generated only for that window.
  * If no window is given, original behavior is preserved.
  * If the requested window lies outside available data, original behavior is preserved.
- Polar outputs written to subdirectories:
  * combined overlays  → <out-dir>/polar_combined/
  * single-phi overlays (up to 2 curves) →
      <out-dir>/polar_single/azimuth/   (solid lines)
      <out-dir>/polar_single/elevation/ (dashed lines)
- Smoothing:
  * Cartesian plots use centered moving-average (--smooth-window, default 5).
  * Polar plots use a circular moving-average with the same window.
- Axis styling per earlier requests:
  * Gain y-ticks every 2 dB; x-ticks every 0.2 GHz on cartesian plots.
  * Beamwidth/efficiency axes 0–100 with 10-unit ticks.
- Color scheme unified across plots and consistent with the gain plot.

Outputs:
- <book>_gain.svg
- <book>_beamwidth.svg
- <book>_beam_efficiency.svg
- polar_combined/<book>_polar_<f>_combined.svg
- polar_single/azimuth/<book>_polar_azimuth_<f>.svg   (solid)
- polar_single/elevation/<book>_polar_elevation_<f>.svg (dashed)
"""
import argparse
from pathlib import Path
import re
import math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib import transforms as mtransforms
from matplotlib.offsetbox import AnchoredOffsetbox, DrawingArea, HPacker, TextArea, VPacker
from matplotlib.ticker import FuncFormatter, FixedFormatter, FixedLocator, NullFormatter, NullLocator
from legend_utils import (
    apply_legend_labels,
    beam_efficiency_legend_label,
    beamwidth_legend_label,
    gain_legend_label,
    parse_legend_labels,
    polarization_sort_key,
    polar_legend_label,
)

# ------------------ global color scheme ------------------
DEFAULT_SOLID_COLORS = ["#2bb6f6", "#f5a623"]  # kept from gain plot
SOLID_COLORS = DEFAULT_SOLID_COLORS[:]
DASHED_COLORS = SOLID_COLORS[:]  # same hues for dashed variants
CARTESIAN_DASH_PATTERN = [12, 7]

def color_for_index(style: str, idx: int) -> str:
    base = SOLID_COLORS if style == '-' else DASHED_COLORS
    return base[idx % len(base)] if base else None


def set_line_colors(colors: list[str]) -> None:
    clean = [c.strip() for c in colors if c and c.strip()]
    palette = clean or DEFAULT_SOLID_COLORS[:]
    SOLID_COLORS[:] = palette
    DASHED_COLORS[:] = palette[:]

# ------------------ helpers ------------------

def sanitize(s: str) -> str:
    s = re.sub(r"\s+", "_", s.strip())
    s = re.sub(r"[^A-Za-z0-9_.-]", "", s)
    return s if s else "sheet"


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


def smooth_series(y: np.ndarray, window: int) -> np.ndarray:
    if window is None or window <= 1:
        return np.asarray(y, dtype=float)
    s = pd.Series(y, dtype="float64")
    return s.rolling(window=window, center=True, min_periods=1).mean().to_numpy()


def smooth_circular(y: np.ndarray, window: int) -> np.ndarray:
    """Centered moving-average on circular sequences (polar samples).
    Wraps both ends to avoid edge attenuation.
    """
    if window is None or window <= 1:
        return np.asarray(y, dtype=float)
    y = np.asarray(y, dtype=float)
    if y.size == 0:
        return y
    w = int(max(1, window))
    pad = w // 2
    if pad == 0:
        return y
    y_pad = np.r_[y[-pad:], y, y[:pad]]
    s = pd.Series(y_pad, dtype="float64").rolling(window=w, center=True, min_periods=1).mean().to_numpy()
    return s[pad:-pad]


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


def parse_freq_ghz_from_text(txt: str):
    """Extract numeric frequency in GHz from headers like '1.0 GHz', 'f=1.0GHz',
    '1000 MHz', '2,45 GHz', or '2.45'. Return float or None.
    """
    if not isinstance(txt, str):
        return None
    t = txt.strip()
    m = re.search(r"([-+]?\d+(?:[\.,]\d+)?)\s*(g?hz|mhz)?", t, re.I)
    if not m:
        return None
    val = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower() if m.group(2) else None
    if unit is None or unit.startswith('ghz') or unit.startswith('g'):
        return val
    if unit.startswith('mhz'):
        return val / 1000.0
    return None


def format_frequency_label(txt: str) -> str:
    value_ghz = parse_freq_ghz_from_text(txt)
    if value_ghz is None:
        return str(txt)
    return f"{format_frequency_tick(value_ghz)} GHz"


def apply_freq_window(x_freq: np.ndarray, series_groups: list[list[np.ndarray]], fmin: float | None, fmax: float | None):
    """If BOTH fmin and fmax are provided and within range, mask x and aligned series.
    Return (x_new, masked_groups, did_crop: bool).
    """
    if x_freq is None or len(x_freq) == 0:
        return x_freq, series_groups, False
    if fmin is None or fmax is None:
        return x_freq, series_groups, False
    data_min = float(np.nanmin(x_freq))
    data_max = float(np.nanmax(x_freq))
    if not (fmin < fmax and fmin >= data_min and fmax <= data_max):
        return x_freq, series_groups, False
    mask = (x_freq >= fmin) & (x_freq <= fmax)
    if not np.any(mask):
        return x_freq, series_groups, False
    x_new = x_freq[mask]
    masked = []
    for group in series_groups:
        masked_group = [np.asarray(s, dtype=float)[mask] if s is not None and len(s) == len(x_freq) else s for s in group]
        masked.append(masked_group)
    return x_new, masked, True


def common_frequency_axis(freq_axes: list[np.ndarray]) -> np.ndarray | None:
    valid = [np.asarray(axis, dtype=float) for axis in freq_axes if axis is not None and len(axis)]
    if not valid:
        return None

    common = {round(float(v), 9) for v in valid[0]}
    for axis in valid[1:]:
        common &= {round(float(v), 9) for v in axis}
    if not common:
        return np.asarray([], dtype=float)

    ordered = [float(v) for v in valid[0] if round(float(v), 9) in common]
    return np.asarray(ordered, dtype=float)


def align_series_to_axis(source_x: np.ndarray, source_y: np.ndarray, target_x: np.ndarray) -> np.ndarray:
    lookup = {
        round(float(x), 9): float(y)
        for x, y in zip(np.asarray(source_x, dtype=float), np.asarray(source_y, dtype=float))
    }
    return np.asarray([lookup[round(float(x), 9)] for x in np.asarray(target_x, dtype=float)], dtype=float)


def _legend_entry_box(
    label: str,
    color: str,
    linestyle: str,
    *,
    fontsize: float,
    text_color: str,
    linewidth: float,
    entry_sep: float,
) -> VPacker:
    line_width = max(28.0, fontsize * 3.8)
    line_height = max(7.0, fontsize * 0.62)
    drawing = DrawingArea(line_width, line_height, 0, 0)
    line_y = max(linewidth / 2.0 + 0.6, line_height * 0.24)
    x0 = 2.0
    x1 = line_width - 2.0
    if linestyle == "--":
        total_width = x1 - x0
        gap = max(6.0, total_width * 0.26)
        dash_len = max(10.0, (total_width - gap) / 2.0)
        first_x1 = x0 + dash_len
        second_x0 = x1 - dash_len
        for seg_x0, seg_x1 in [(x0, first_x1), (second_x0, x1)]:
            dash = Line2D(
                [seg_x0, seg_x1],
                [line_y, line_y],
                color=color,
                lw=linewidth,
                linestyle="-",
                solid_capstyle="round",
                transform=drawing.get_transform(),
            )
            drawing.add_artist(dash)
    else:
        line = Line2D(
            [x0, x1],
            [line_y, line_y],
            color=color,
            lw=linewidth,
            linestyle="-",
            solid_capstyle="round",
            transform=drawing.get_transform(),
        )
        drawing.add_artist(line)
    text = TextArea(
        label,
        textprops={
            "color": text_color,
            "fontsize": fontsize,
            "ha": "center",
            "va": "top",
            "multialignment": "center",
        },
    )
    return VPacker(children=[drawing, text], align="center", pad=0.0, sep=entry_sep)


def add_stacked_line_legend(
    ax,
    items: list[tuple[str, str, str]],
    *,
    loc: str,
    bbox_to_anchor: tuple[float, float],
    bbox_transform,
    ncol: int = 1,
    fontsize: float = 10.5,
    text_color: str = "#8a949c",
    linewidth: float = 2.2,
    column_sep: float = 16.0,
    row_sep: float = 10.0,
    entry_sep: float = 1.0,
):
    if not items:
        return None
    entry_boxes = [
        _legend_entry_box(
            label,
            color,
            linestyle,
            fontsize=fontsize,
            text_color=text_color,
            linewidth=linewidth,
            entry_sep=entry_sep,
        )
        for label, color, linestyle in items
    ]
    rows = [
        HPacker(children=entry_boxes[index:index + ncol], align="top", pad=0.0, sep=column_sep)
        for index in range(0, len(entry_boxes), ncol)
    ]
    legend_box = VPacker(children=rows, align="center", pad=0.0, sep=row_sep)
    anchored = AnchoredOffsetbox(
        loc=loc,
        child=legend_box,
        frameon=False,
        bbox_to_anchor=bbox_to_anchor,
        bbox_transform=bbox_transform,
        borderpad=0.0,
        pad=0.0,
    )
    ax.add_artist(anchored)
    return anchored

# ------------------ plotting: cartesian ------------------

def plot_xy(x, series_list, names, out_path, y_label,
            grid_color="#6f7a81", styles=None, colors=None,
            y_min=None, y_max=None, y_step=None,
            smooth_window: int = 5, x_step: float = None, x_ticks=None, x_log: bool = False):
    fig, ax = plt.subplots(figsize=(12, 4.2), dpi=120)
    ax.set_facecolor("white")
    ax.grid(True, which="both", axis="both", color=grid_color, linewidth=0.9)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_color(grid_color)
        spine.set_linewidth(0.9)

    xmin, xmax = np.nanmin(x), np.nanmax(x)
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
        line_width = 2.2 if st_in == "--" else 2.0
        ln, = ax.plot(x, ysm, linewidth=line_width, linestyle=st_in, solid_capstyle="round", color=color_in)
        if st_in == "--":
            ln.set_dashes(CARTESIAN_DASH_PATTERN)
            ln.set_dash_capstyle("round")
        lines.append(ln)

    add_stacked_line_legend(
        ax,
        [(name, ln.get_color(), ln.get_linestyle()) for name, ln in zip(names, lines)],
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        bbox_transform=ax.transAxes,
        ncol=1,
        fontsize=10.5,
        linewidth=2.0,
        row_sep=24.0,
        entry_sep=0.6,
    )

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(out_path, format="svg", bbox_inches="tight")
    plt.close()
    return out_path

# ------------------ plotting: polar ------------------

def save_polar(out_path, datasets, title,
               grid_color="#6f7a81", rings=(0,-7.5,-15,-22.5,-30),
               angle_tick_step=30, clip_db=-30.0, smooth_window: int = 5):
    """Draw one polar axes, possibly with multiple datasets.
    datasets: list of dicts {angles, series, label, linestyle}
    """
    fig = plt.figure(figsize=(9, 10), dpi=120)
    ax = plt.subplot(111, polar=True)

    ax.set_facecolor("white")
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_ylim(clip_db, 0)
    ax.set_frame_on(False)

    ring_vals = sorted(rings)
    ax.set_rticks(ring_vals)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.grid(True, linestyle="-", linewidth=0.9, color=grid_color)
    ax.tick_params(width=0.9, colors=grid_color)

    tick_angles = np.arange(0, 360, angle_tick_step)
    tick_labels = [str(int(t if t <= 180 else t - 360)) for t in tick_angles]
    ax.set_thetagrids(tick_angles, labels=tick_labels)
    for t in ax.get_xticklabels():
        t.set_color(grid_color)
        t.set_fontsize(10.5)

    # custom radial labels
    theta = np.pi/2
    dy_px = -12
    base = ax.transData
    dy_in = dy_px / fig.dpi
    offset = mtransforms.ScaledTranslation(0.0, dy_in, fig.dpi_scale_trans)
    bbox_args = dict(facecolor="white", edgecolor="none", pad=1.5)

    ax.set_yticklabels([])
    for r in ring_vals:
        ax.text(theta, r, f"{r:g}", color="#6f7a81", fontsize=10,
                ha="center", va="top", rotation=0, rotation_mode="anchor",
                transform=base + offset, bbox=bbox_args)

    legend_items: list[tuple[str, str, str]] = []
    solid_count, dashed_count = 0, 0

    for d in datasets:
        angles = np.asarray(d["angles"], dtype=float)
        s = np.asarray(d["series"], dtype=float)
        s = smooth_circular(s, smooth_window)
        s = np.maximum(s - np.nanmax(s), clip_db)
        ls = d.get("linestyle", "-")
        if ls == "-":
            idx = solid_count; solid_count += 1
        else:
            idx = dashed_count; dashed_count += 1
        color = color_for_index(ls, idx) or "black"
        ax.plot(np.deg2rad(angles), s, linewidth=2.3, solid_capstyle="round",
                linestyle=ls, color=color)
        legend_items.append((d.get("label", ""), color, ls))

    add_stacked_line_legend(
        ax,
        legend_items,
        loc="lower center",
        bbox_to_anchor=(0.5, -0.19),
        bbox_transform=ax.transAxes,
        ncol=2,
        fontsize=11.0,
        linewidth=2.3,
        column_sep=22.0,
        row_sep=10.0,
        entry_sep=0.8,
    )

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout(rect=[0, 0, 1, 0.97])
    plt.savefig(out_path, format="svg", bbox_inches="tight")
    plt.close(fig)


def resolved_axis_limits(default_min: float | None, default_max: float | None,
                         override_min: float | None, override_max: float | None) -> tuple[float | None, float | None]:
    y_min = default_min if override_min is None else float(override_min)
    y_max = default_max if override_max is None else float(override_max)
    if y_min is not None and y_max is not None and y_max <= y_min:
        return default_min, default_max
    return y_min, y_max


def resolved_tick_step(default_step: float | None, override_step: float | None) -> float | None:
    if override_step is None or float(override_step) <= 0:
        return default_step
    return float(override_step)

# ------------------ main ------------------

def main():
    parser = argparse.ArgumentParser(description=(
        "Create Gain, Beamwidth, Beam Efficiency plots and polar plots from results.xlsx-like workbooks"
    ))
    parser.add_argument("input_xlsx", help="Path to Excel .xlsx file")
    parser.add_argument("--out-dir", default=None, help="Directory to write SVGs.")
    parser.add_argument("--grid-color", default="#6f7a81", help="Grid/axis color (hex).")
    parser.add_argument("--rings", default="0,-7.5,-15,-22.5,-30", help="Comma-separated ring values (dB) for polar.")
    parser.add_argument("--angle-step", type=int, default=30, help="Angular tick step for polar (deg).")
    parser.add_argument("--clip-db", type=float, default=-30.0, help="Lower dB limit for polar (clip).")
    parser.add_argument("--smooth-window", type=int, default=5, help="Moving-average window (points). Use 1 to disable.")
    parser.add_argument("--x-step", type=float, default=None, help="Optional x tick step for cartesian plots (GHz).")
    parser.add_argument("--x-log", action="store_true", help="Use logarithmic scaling on the x-axis for cartesian plots.")
    parser.add_argument("--line-colors", default=None, help="Comma-separated line colors applied across the plots.")
    parser.add_argument("--fmin", type=float, default=None, help="Lower bound of frequency window in GHz (inclusive).")
    parser.add_argument("--fmax", type=float, default=None, help="Upper bound of frequency window in GHz (inclusive).")
    parser.add_argument("--gain-ymin", type=float, default=None, help="Optional lower y-axis limit for the gain plot.")
    parser.add_argument("--gain-ymax", type=float, default=None, help="Optional upper y-axis limit for the gain plot.")
    parser.add_argument("--beamwidth-ymin", type=float, default=None, help="Optional lower y-axis limit for the beamwidth plot.")
    parser.add_argument("--beamwidth-ymax", type=float, default=None, help="Optional upper y-axis limit for the beamwidth plot.")
    parser.add_argument("--beam-eff-ymin", type=float, default=None, help="Optional lower y-axis limit for the beam efficiency plot.")
    parser.add_argument("--beam-eff-ymax", type=float, default=None, help="Optional upper y-axis limit for the beam efficiency plot.")
    parser.add_argument("--gain-y-step", type=float, default=None, help="Optional y-axis tick step for the gain plot.")
    parser.add_argument("--beamwidth-y-step", type=float, default=None, help="Optional y-axis tick step for the beamwidth plot.")
    parser.add_argument("--beam-eff-y-step", type=float, default=None, help="Optional y-axis tick step for the beam efficiency plot.")
    parser.add_argument(
        "--gain-legend-labels",
        default=None,
        help="Comma-separated legend overrides for gain traces, in plotted series order.",
    )
    parser.add_argument(
        "--beamwidth-legend-labels",
        default=None,
        help="Comma-separated legend overrides for beamwidth traces, in plotted series order.",
    )
    parser.add_argument(
        "--beam-eff-legend-labels",
        default=None,
        help="Comma-separated legend overrides for beam efficiency traces, in plotted series order.",
    )
    args = parser.parse_args()

    set_line_colors(parse_color_list(args.line_colors))
    gain_legend_labels = parse_legend_labels(args.gain_legend_labels)
    beamwidth_legend_labels = parse_legend_labels(args.beamwidth_legend_labels)
    beam_eff_legend_labels = parse_legend_labels(args.beam_eff_legend_labels)

    xls = pd.ExcelFile(args.input_xlsx)
    sheet_names = xls.sheet_names
    bookstem = Path(args.input_xlsx).stem
    out_dir = Path(args.out_dir) if args.out_dir else Path(args.input_xlsx).resolve().parent
    out_dir.mkdir(parents=True, exist_ok=True)
    rings = tuple(float(x) for x in args.rings.split(","))

    # collect polar pattern sheets
    polar_sheets = [s for s in sheet_names if s.lower().endswith("_phi0") or s.lower().endswith("_phi90")]

    def base_of(name: str) -> str:
        low = name.lower()
        if low.endswith("_phi0"): return name[:-5]
        if low.endswith("_phi90"): return name[:-6]
        return name

    grouped: dict[str, dict[str, pd.DataFrame]] = {}
    for s in polar_sheets:
        base = base_of(s)
        grouped.setdefault(base, {})
        if s.lower().endswith("_phi0"):
            grouped[base]['phi0'] = xls.parse(s)
        else:
            grouped[base]['phi90'] = xls.parse(s)

    # collect summary sheets for cartesian plots
    summary_sheets = sorted((s for s in sheet_names if s not in polar_sheets), key=polarization_sort_key)

    gain_series, gain_names, gain_freqs = [], [], []
    bw_series, bw_names, bw_styles, bw_freqs = [], [], [], []
    be_series, be_names, be_freqs = [], [], []
    summary_frames: list[tuple[str, pd.DataFrame]] = []

    for sheet in summary_sheets:
        df = xls.parse(sheet)
        summary_frames.append((sheet, df))
        if not set(["freq_GHz", "phi_cut_deg"]).issubset(df.columns):
            continue
        sel0 = df[df["phi_cut_deg"] == 0]
        if "max_gain_dBi" in df.columns and not sel0.empty:
            gain_freqs.append(sel0["freq_GHz"].to_numpy(dtype=float))
            gain_series.append(sel0["max_gain_dBi"].to_numpy(dtype=float))
            gain_names.append(gain_legend_label(sheet))

        if "eta_beam_percent" in df.columns and not sel0.empty:
            be_freqs.append(sel0["freq_GHz"].to_numpy(dtype=float))
            be_series.append(sel0["eta_beam_percent"].to_numpy(dtype=float))
            be_names.append(beam_efficiency_legend_label(sheet))

    for phi, label_suffix, style in [(0, "Azimuth", "-"), (90, "Elevation", "--")]:
        for sheet, df in summary_frames:
            if not set(["freq_GHz", "phi_cut_deg", "beamwidth_6dB_2sided_deg"]).issubset(df.columns):
                continue
            sel = df[df["phi_cut_deg"] == phi]
            if sel.empty:
                continue
            bw_freqs.append(sel["freq_GHz"].to_numpy(dtype=float))
            bw_series.append(sel["beamwidth_6dB_2sided_deg"].to_numpy(dtype=float))
            bw_names.append(beamwidth_legend_label(sheet, label_suffix))
            bw_styles.append(style)

    # Gain plot
    if gain_series:
        series_g_raw = gain_series[:2]
        freq_g_raw = gain_freqs[:2]
        names_g = apply_legend_labels(gain_names[:2], gain_legend_labels)
        freq_g = common_frequency_axis(freq_g_raw)
        if freq_g is None or len(freq_g) == 0:
            print("Skipped gain plot: no common frequency axis across gain series.")
        else:
            series_g = [align_series_to_axis(x, y, freq_g) for x, y in zip(freq_g_raw, series_g_raw)]
            freq_g, masked_groups, _ = apply_freq_window(freq_g, [series_g], args.fmin, args.fmax)
            series_g = masked_groups[0]
            if len(freq_g) == 0 or not series_g:
                print("Skipped gain plot: selected frequency window left no samples.")
            else:
                data_max = float(np.nanmax([np.nanmax(s) for s in series_g]))
                y_min, y_max = resolved_axis_limits(
                    0.0,
                    max(20.0, float(5 * math.ceil(max(0.0, data_max) / 5.0))),
                    args.gain_ymin,
                    args.gain_ymax,
                )
                styles_g = ["-"] * len(series_g)
                colors_g = [color_for_index("-", i) for i in range(len(series_g))]
                out_gain = str(out_dir / f"{bookstem}_gain.svg")
                plot_xy(freq_g, series_g, names_g, out_gain, y_label="Gain / dBi",
                        styles=styles_g, colors=colors_g,
                        grid_color=args.grid_color, y_min=y_min, y_max=y_max,
                        y_step=resolved_tick_step(2.0, args.gain_y_step),
                        smooth_window=args.smooth_window, x_step=args.x_step, x_log=args.x_log)
                print(out_gain)

    # Beamwidth
    if bw_series:
        freq_bw = common_frequency_axis(bw_freqs)
        if freq_bw is None or len(freq_bw) == 0:
            print("Skipped beamwidth plot: no common frequency axis across beamwidth series.")
        else:
            bw_series_aligned = [align_series_to_axis(x, y, freq_bw) for x, y in zip(bw_freqs, bw_series)]
            freq_bw, masked_groups, _ = apply_freq_window(freq_bw, [bw_series_aligned], args.fmin, args.fmax)
            bw_series_aligned = masked_groups[0]
            if len(freq_bw) == 0 or not bw_series_aligned:
                print("Skipped beamwidth plot: selected frequency window left no samples.")
            else:
                out_bw = str(out_dir / f"{bookstem}_beamwidth.svg")
                bw_plot_names = apply_legend_labels(bw_names, beamwidth_legend_labels)
                bw_colors, solid_count, dashed_count = [], 0, 0
                for st in bw_styles:
                    if st == '-':
                        bw_colors.append(color_for_index('-', solid_count)); solid_count += 1
                    else:
                        bw_colors.append(color_for_index('--', dashed_count)); dashed_count += 1
                y_min, y_max = resolved_axis_limits(0.0, 100.0, args.beamwidth_ymin, args.beamwidth_ymax)
                plot_xy(freq_bw, bw_series_aligned, bw_plot_names, out_bw, y_label="Beamwidth / deg",
                        styles=bw_styles, colors=bw_colors, grid_color=args.grid_color,
                        y_min=y_min, y_max=y_max,
                        y_step=resolved_tick_step(10.0, args.beamwidth_y_step),
                        smooth_window=args.smooth_window, x_step=args.x_step, x_log=args.x_log)
                print(out_bw)

    # Beam efficiency
    if be_series:
        freq_be = common_frequency_axis(be_freqs)
        if freq_be is None or len(freq_be) == 0:
            print("Skipped beam efficiency plot: no common frequency axis across beam efficiency series.")
        else:
            be_series_aligned = [align_series_to_axis(x, y, freq_be) for x, y in zip(be_freqs, be_series)]
            freq_be, masked_groups, _ = apply_freq_window(freq_be, [be_series_aligned], args.fmin, args.fmax)
            be_series_aligned = masked_groups[0]
            if len(freq_be) == 0 or not be_series_aligned:
                print("Skipped beam efficiency plot: selected frequency window left no samples.")
            else:
                out_be = str(out_dir / f"{bookstem}_beam_efficiency.svg")
                be_styles = ["-"] * len(be_series_aligned)
                be_colors = [color_for_index("-", i) for i in range(len(be_series_aligned))]
                be_plot_names = apply_legend_labels(be_names, beam_eff_legend_labels)
                y_min, y_max = resolved_axis_limits(0.0, 100.0, args.beam_eff_ymin, args.beam_eff_ymax)
                plot_xy(freq_be, be_series_aligned, be_plot_names, out_be, y_label="Beam Efficiency / %",
                        styles=be_styles, colors=be_colors,
                        grid_color=args.grid_color, y_min=y_min, y_max=y_max,
                        y_step=resolved_tick_step(10.0, args.beam_eff_y_step),
                        smooth_window=args.smooth_window, x_step=args.x_step, x_log=args.x_log)
                print(out_be)

    # ----------- Polar plots -----------
    def get_angle_and_freqs(df: pd.DataFrame):
        first = str(df.columns[0]).strip().lower()
        looks_like_theta = ("theta" in first and "deg" in first) or (first == "angle")
        if not looks_like_theta:
            return None, []
        angles = pd.to_numeric(df.iloc[:, 0], errors="coerce").to_numpy()
        freq_cols = [c for c in df.columns[1:] if isinstance(c, str)]
        return angles, freq_cols

    all_freq_cols = set()
    angles_map = {}
    for base, sides in grouped.items():
        for phi_key, df in sides.items():
            angles, cols = get_angle_and_freqs(df)
            if angles is None:
                continue
            angles_map[(base, phi_key)] = angles
            for c in cols:
                all_freq_cols.add(c)

    # available polar window
    numeric_freqs = [(c, parse_freq_ghz_from_text(c)) for c in all_freq_cols]
    just_vals = [v for (_, v) in numeric_freqs if v is not None]
    avail_min, avail_max = (min(just_vals), max(just_vals)) if just_vals else (None, None)

    def polar_cols_iter():
        if args.fmin is None or args.fmax is None:
            for c in sorted(all_freq_cols):
                yield c
            return
        if avail_min is None or avail_max is None or not (args.fmin < args.fmax and args.fmin >= avail_min and args.fmax <= avail_max):
            for c in sorted(all_freq_cols):
                yield c
            return
        for c, val in sorted(numeric_freqs, key=lambda x: (x[1] is None, x[1])):
            if val is None:
                continue
            if args.fmin <= val <= args.fmax:
                yield c

    # build datasets for a given phi across bases, limit to 2 curves, and with chosen linestyle
    def build_phi_datasets(freq_col: str, phi_key: str, linestyle: str):
        datasets = []
        plane = "Azimuth" if phi_key == "phi0" else "Elevation"
        frequency_label = format_frequency_label(freq_col)
        count = 0
        for base in sorted(grouped.keys(), key=polarization_sort_key):
            df = grouped[base].get(phi_key)
            if df is None or freq_col not in df.columns:
                continue
            series = pd.to_numeric(df[freq_col], errors="coerce").to_numpy()
            if np.all(np.isnan(series)):
                continue
            angles = angles_map.get((base, phi_key))
            if angles is None:
                continue
            datasets.append({
                "angles": angles,
                "series": series,
                "label": polar_legend_label(base, plane, frequency_label),
                "linestyle": linestyle,
            })
            count += 1
            if count >= 2:
                break
        return datasets

    for freq_col in polar_cols_iter():
        frequency_label = format_frequency_label(freq_col)
        # Combined (Az solid, El dashed)
        datasets_combined = []
        for phi_key, label_suffix, linestyle in [("phi0", "Azimuth", "-"), ("phi90", "Elevation", "--")]:
            for base in sorted(grouped.keys(), key=polarization_sort_key):
                df = grouped[base].get(phi_key)
                if df is None or freq_col not in df.columns:
                    continue
                series = pd.to_numeric(df[freq_col], errors="coerce").to_numpy()
                if np.all(np.isnan(series)):
                    continue
                angles = angles_map.get((base, phi_key))
                if angles is None:
                    continue
                datasets_combined.append({
                    "angles": angles,
                    "series": series,
                    "label": polar_legend_label(base, label_suffix, frequency_label),
                    "linestyle": linestyle,
                })
        if datasets_combined:
            title = f"Polar patterns @ {freq_col}"
            out_name_c = f"{bookstem}_polar_{sanitize(freq_col)}_combined.svg"
            out_path_c = str(out_dir / "polar_combined" / out_name_c)
            save_polar(out_path_c, datasets_combined, title,
                       grid_color=args.grid_color, rings=rings,
                       angle_tick_step=args.angle_step, clip_db=args.clip_db,
                       smooth_window=args.smooth_window)
            print(out_path_c)

        # Single-phi: Azimuth (solid)
        ds_az = build_phi_datasets(freq_col, "phi0", linestyle='-')
        if ds_az:
            title_az = f"Azimuth (φ=0°) @ {freq_col}"
            out_name_az = f"{bookstem}_polar_azimuth_{sanitize(freq_col)}.svg"
            out_path_az = str(out_dir / "polar_single" / "azimuth" / out_name_az)
            save_polar(out_path_az, ds_az, title_az,
                       grid_color=args.grid_color, rings=rings,
                       angle_tick_step=args.angle_step, clip_db=args.clip_db,
                       smooth_window=args.smooth_window)
            print(out_path_az)

        # Single-phi: Elevation (dashed)
        ds_el = build_phi_datasets(freq_col, "phi90", linestyle='--')
        if ds_el:
            title_el = f"Elevation (φ=90°) @ {freq_col}"
            out_name_el = f"{bookstem}_polar_elevation_{sanitize(freq_col)}.svg"
            out_path_el = str(out_dir / "polar_single" / "elevation" / out_name_el)
            save_polar(out_path_el, ds_el, title_el,
                       grid_color=args.grid_color, rings=rings,
                       angle_tick_step=args.angle_step, clip_db=args.clip_db,
                       smooth_window=args.smooth_window)
            print(out_path_el)

if __name__ == "__main__":
    main()
