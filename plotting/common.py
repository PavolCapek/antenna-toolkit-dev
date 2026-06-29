from __future__ import annotations

import math

import numpy as np
import pandas as pd
from matplotlib.ticker import FixedFormatter, FixedLocator, FuncFormatter, NullFormatter, NullLocator


def color_for_index(style: str, idx: int, solid_colors: list[str], dashed_colors: list[str]) -> str | None:
    base = solid_colors if style == "-" else dashed_colors
    return base[idx % len(base)] if base else None


def set_line_colors(colors: list[str], default_colors: list[str], solid_colors: list[str], dashed_colors: list[str]) -> None:
    clean = [c.strip() for c in colors if c and c.strip()]
    palette = clean or default_colors[:]
    solid_colors[:] = palette
    dashed_colors[:] = palette[:]


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
    return pd.Series(y, dtype="float64").rolling(window=window, center=True, min_periods=1).mean().to_numpy()


def parse_color_list(raw: str | None, default: list[str]) -> list[str]:
    fallback = default[:]
    if not raw:
        return fallback
    return [item.strip() for item in raw.split(",") if item.strip()] or fallback


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
