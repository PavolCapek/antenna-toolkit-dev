from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlotVisualStyle:
    plot_font_size: float = 10.5
    legend_font_size: float = 10.5
    grid_line_width: float = 0.9
    plot_line_width: float = 2.0
    legend_line_width: float = 3.0
    legend_text_color: str = "#8a949c"
    legend_column_sep: float = 16.0
    legend_row_sep: float = 24.0
    legend_entry_sep: float = 0.6
    legend_file_suffix: str = "-legend"
    legend_export_pad_x_px: float = 3.0
    legend_export_pad_top_px: float = 3.0
    legend_export_pad_bottom_px: float = 12.0
    cartesian_figure_width_in: float = 12.0
    cartesian_figure_height_in: float = 5.04
    polar_figure_size_in: float = 9.0


DEFAULT_VISUAL_STYLE = PlotVisualStyle()
DEFAULT_PLOT_FONT_SIZE = DEFAULT_VISUAL_STYLE.plot_font_size
DEFAULT_LEGEND_FONT_SIZE = DEFAULT_VISUAL_STYLE.legend_font_size
DEFAULT_GRID_LINE_WIDTH = DEFAULT_VISUAL_STYLE.grid_line_width
DEFAULT_PLOT_LINE_WIDTH = DEFAULT_VISUAL_STYLE.plot_line_width
DEFAULT_LEGEND_LINE_WIDTH = DEFAULT_VISUAL_STYLE.legend_line_width
STACKED_LEGEND_TEXT_COLOR = DEFAULT_VISUAL_STYLE.legend_text_color
STACKED_LEGEND_COLUMN_SEP = DEFAULT_VISUAL_STYLE.legend_column_sep
STACKED_LEGEND_ROW_SEP = DEFAULT_VISUAL_STYLE.legend_row_sep
STACKED_LEGEND_ENTRY_SEP = DEFAULT_VISUAL_STYLE.legend_entry_sep
LEGEND_FILE_SUFFIX = DEFAULT_VISUAL_STYLE.legend_file_suffix
LEGEND_EXPORT_PAD_X_PX = DEFAULT_VISUAL_STYLE.legend_export_pad_x_px
LEGEND_EXPORT_PAD_TOP_PX = DEFAULT_VISUAL_STYLE.legend_export_pad_top_px
LEGEND_EXPORT_PAD_BOTTOM_PX = DEFAULT_VISUAL_STYLE.legend_export_pad_bottom_px
CARTESIAN_FIGURE_WIDTH_IN = DEFAULT_VISUAL_STYLE.cartesian_figure_width_in
CARTESIAN_FIGURE_HEIGHT_IN = DEFAULT_VISUAL_STYLE.cartesian_figure_height_in
POLAR_FIGURE_SIZE_IN = DEFAULT_VISUAL_STYLE.polar_figure_size_in
