from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from plotting.common import apply_frequency_ticks, build_step_ticks, smooth_series


def render_cartesian_plot(
    x,
    series_list,
    names,
    out_path,
    y_label,
    *,
    export_legend: Callable,
    grid_color="#6f7a81",
    styles=None,
    colors=None,
    y_min=None,
    y_max=None,
    y_step=None,
    smooth_window: int = 5,
    x_step: float = None,
    x_ticks=None,
    x_log: bool = False,
    x_min: float | None = None,
    x_max: float | None = None,
    font_size: float,
    legend_font_size: float,
    grid_line_width: float,
    line_width: float,
    legend_line_width: float,
    legend_row_sep: float,
    legend_entry_sep: float,
    figure_width: float,
    figure_height: float,
):
    fig, ax = plt.subplots(figsize=(figure_width, figure_height), dpi=120)
    ax.set_facecolor("white")
    ax.grid(True, which="both", axis="both", color=grid_color, linewidth=grid_line_width)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_color(grid_color)
        spine.set_linewidth(grid_line_width)

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

    ax.set_xlabel("Frequency / GHz", color=grid_color, fontsize=font_size)
    ax.set_ylabel(y_label, color=grid_color, fontsize=font_size)
    ax.tick_params(colors=grid_color, labelsize=font_size, width=grid_line_width)

    lines = []
    for i, y in enumerate(series_list):
        ysm = smooth_series(np.asarray(y, dtype=float), window=smooth_window)
        st_in = styles[i] if styles and i < len(styles) else "-"
        color_in = colors[i] if colors and i < len(colors) else None
        ln, = ax.plot(x, ysm, linewidth=line_width, linestyle=st_in, solid_capstyle="round", color=color_in)
        lines.append(ln)

    legend_items = [(name, ln.get_color(), ln.get_linestyle()) for name, ln in zip(names, lines)]

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    fig.savefig(out_path, format="svg", bbox_inches="tight")
    plt.close(fig)
    legend_path = export_legend(
        legend_items,
        out_path,
        ncol=1,
        fontsize=legend_font_size,
        linewidth=legend_line_width,
        row_sep=legend_row_sep,
        entry_sep=legend_entry_sep,
    )
    return out_path, str(legend_path) if legend_path is not None else None
