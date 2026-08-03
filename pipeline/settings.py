from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from studio_support import DEFAULT_BEAMWIDTH_DB_COLORS, DEFAULT_GRID_COLOR, DEFAULT_LINE_COLORS

DEFAULT_DATASHEET_TEMPLATE_NAME = "Datasheet - RFE.pdf"
DEFAULT_PDF_METADATA_AUTHOR = "RF elements"


def _float_value(values: dict[str, Any], key: str, default: float) -> float:
    try:
        return float(values.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _int_value(values: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(values.get(key, default))
    except (TypeError, ValueError):
        return int(default)


def _bool_value(values: dict[str, Any], key: str, default: bool) -> bool:
    value = values.get(key, default)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _str_value(values: dict[str, Any], key: str, default: str) -> str:
    return str(values.get(key, default) or "").strip()


def _legacy_value(values: dict[str, Any], primary: str, legacy: str, default: Any) -> Any:
    if primary in values:
        return values[primary]
    if legacy in values:
        return values[legacy]
    return default


def _legacy_float(values: dict[str, Any], primary: str, legacy: str, default: float) -> float:
    try:
        return float(_legacy_value(values, primary, legacy, default))
    except (TypeError, ValueError):
        return float(default)


@dataclass(frozen=True)
class PresetSettings:
    smooth: int = 5
    theta: float = 8.0
    smooth2: int = 5
    shared_xstep: float = 0.2
    shared_fmin: float = 0.0
    shared_fmax: float = 0.0
    shared_xlog: bool = False
    gain_ymin: float = 0.0
    gain_ymax: float = 0.0
    gain_y_step: float = 0.0
    beamwidth_ymin: float = 0.0
    beamwidth_ymax: float = 0.0
    beamwidth_y_step: float = 0.0
    beam_eff_ymin: float = 0.0
    beam_eff_ymax: float = 0.0
    beam_eff_y_step: float = 0.0
    vswr_ymin: float = 1.0
    vswr_ymax: float = 10.0
    vswr_ystep: float = 1.0
    vswr_smooth: int = 5
    compliance_fmin: float = 0.0
    compliance_fmax: float = 0.0
    compliance_omit_angle_range: str = "180-180"
    grid_color: str = DEFAULT_GRID_COLOR
    cartesian_grid_line_width: float = 0.9
    polar_grid_line_width: float = 0.9
    cartesian_line_width: float = 2.0
    cartesian_figure_width: float = 12.0
    cartesian_figure_height: float = 5.04
    polar_figure_size: float = 9.0
    polar_line_width: float = 2.0
    cartesian_font_size: float = 10.5
    polar_font_size: float = 10.5
    cartesian_legend_font_size: float = 10.5
    polar_legend_font_size: float = 10.5
    plot_line_1: str = DEFAULT_LINE_COLORS[0][1]
    plot_line_2: str = DEFAULT_LINE_COLORS[1][1]
    polar_azimuth_line_1_color: str = DEFAULT_LINE_COLORS[0][1]
    polar_azimuth_line_1_style: str = "solid"
    polar_azimuth_line_2_color: str = DEFAULT_LINE_COLORS[1][1]
    polar_azimuth_line_2_style: str = "solid"
    polar_elevation_line_1_color: str = DEFAULT_LINE_COLORS[0][1]
    polar_elevation_line_1_style: str = "dashed"
    polar_elevation_line_2_color: str = DEFAULT_LINE_COLORS[1][1]
    polar_elevation_line_2_style: str = "dashed"
    beamwidth_3db_color: str = DEFAULT_BEAMWIDTH_DB_COLORS[0][1]
    beamwidth_6db_color: str = DEFAULT_BEAMWIDTH_DB_COLORS[1][1]
    beamwidth_10db_color: str = DEFAULT_BEAMWIDTH_DB_COLORS[2][1]
    gain_legend_labels: str = ""
    beamwidth_legend_labels: str = ""
    beam_eff_legend_labels: str = ""
    vswr_legend_labels: str = ""
    datasheet_template: str = DEFAULT_DATASHEET_TEMPLATE_NAME
    pdf_metadata_author: str = DEFAULT_PDF_METADATA_AUTHOR
    rings: str = "0,-7.5,-15,-22.5,-30"
    angle: int = 30
    clip: float = -30.0

    @classmethod
    def from_mapping(cls, values: dict[str, Any] | None) -> "PresetSettings":
        source = dict(values or {})
        defaults = cls()
        default_map = asdict(defaults)
        return cls(
            smooth=_int_value(source, "smooth", defaults.smooth),
            theta=_float_value(source, "theta", defaults.theta),
            smooth2=_int_value(source, "smooth2", defaults.smooth2),
            shared_xstep=_float_value(source, "shared_xstep", defaults.shared_xstep),
            shared_fmin=_float_value(source, "shared_fmin", defaults.shared_fmin),
            shared_fmax=_float_value(source, "shared_fmax", defaults.shared_fmax),
            shared_xlog=_bool_value(source, "shared_xlog", defaults.shared_xlog),
            gain_ymin=_float_value(source, "gain_ymin", defaults.gain_ymin),
            gain_ymax=_float_value(source, "gain_ymax", defaults.gain_ymax),
            gain_y_step=_float_value(source, "gain_y_step", defaults.gain_y_step),
            beamwidth_ymin=_float_value(source, "beamwidth_ymin", defaults.beamwidth_ymin),
            beamwidth_ymax=_float_value(source, "beamwidth_ymax", defaults.beamwidth_ymax),
            beamwidth_y_step=_float_value(source, "beamwidth_y_step", defaults.beamwidth_y_step),
            beam_eff_ymin=_float_value(source, "beam_eff_ymin", defaults.beam_eff_ymin),
            beam_eff_ymax=_float_value(source, "beam_eff_ymax", defaults.beam_eff_ymax),
            beam_eff_y_step=_float_value(source, "beam_eff_y_step", defaults.beam_eff_y_step),
            vswr_ymin=_float_value(source, "vswr_ymin", defaults.vswr_ymin),
            vswr_ymax=_float_value(source, "vswr_ymax", defaults.vswr_ymax),
            vswr_ystep=_float_value(source, "vswr_ystep", defaults.vswr_ystep),
            vswr_smooth=_int_value(source, "vswr_smooth", defaults.vswr_smooth),
            compliance_fmin=_float_value(source, "compliance_fmin", defaults.compliance_fmin),
            compliance_fmax=_float_value(source, "compliance_fmax", defaults.compliance_fmax),
            compliance_omit_angle_range=_str_value(
                source,
                "compliance_omit_angle_range",
                defaults.compliance_omit_angle_range,
            ),
            grid_color=_str_value(source, "grid_color", defaults.grid_color),
            cartesian_grid_line_width=_legacy_float(source, "cartesian_grid_line_width", "plot_grid_line_width", default_map["cartesian_grid_line_width"]),
            polar_grid_line_width=_legacy_float(source, "polar_grid_line_width", "plot_grid_line_width", default_map["polar_grid_line_width"]),
            cartesian_line_width=_legacy_float(source, "cartesian_line_width", "plot_line_width", default_map["cartesian_line_width"]),
            cartesian_figure_width=_float_value(source, "cartesian_figure_width", defaults.cartesian_figure_width),
            cartesian_figure_height=_float_value(source, "cartesian_figure_height", defaults.cartesian_figure_height),
            polar_figure_size=_float_value(source, "polar_figure_size", defaults.polar_figure_size),
            polar_line_width=_legacy_float(source, "polar_line_width", "plot_line_width", default_map["polar_line_width"]),
            cartesian_font_size=_legacy_float(source, "cartesian_font_size", "plot_font_size", default_map["cartesian_font_size"]),
            polar_font_size=_legacy_float(source, "polar_font_size", "plot_font_size", default_map["polar_font_size"]),
            cartesian_legend_font_size=_legacy_float(source, "cartesian_legend_font_size", "plot_legend_font_size", default_map["cartesian_legend_font_size"]),
            polar_legend_font_size=_legacy_float(source, "polar_legend_font_size", "plot_legend_font_size", default_map["polar_legend_font_size"]),
            plot_line_1=_str_value(source, "plot_line_1", defaults.plot_line_1),
            plot_line_2=_str_value(source, "plot_line_2", defaults.plot_line_2),
            polar_azimuth_line_1_color=_str_value(source, "polar_azimuth_line_1_color", _str_value(source, "plot_line_1", defaults.polar_azimuth_line_1_color)),
            polar_azimuth_line_1_style=_str_value(source, "polar_azimuth_line_1_style", defaults.polar_azimuth_line_1_style),
            polar_azimuth_line_2_color=_str_value(source, "polar_azimuth_line_2_color", _str_value(source, "plot_line_2", defaults.polar_azimuth_line_2_color)),
            polar_azimuth_line_2_style=_str_value(source, "polar_azimuth_line_2_style", defaults.polar_azimuth_line_2_style),
            polar_elevation_line_1_color=_str_value(source, "polar_elevation_line_1_color", _str_value(source, "plot_line_1", defaults.polar_elevation_line_1_color)),
            polar_elevation_line_1_style=_str_value(source, "polar_elevation_line_1_style", defaults.polar_elevation_line_1_style),
            polar_elevation_line_2_color=_str_value(source, "polar_elevation_line_2_color", _str_value(source, "plot_line_2", defaults.polar_elevation_line_2_color)),
            polar_elevation_line_2_style=_str_value(source, "polar_elevation_line_2_style", defaults.polar_elevation_line_2_style),
            beamwidth_3db_color=_str_value(source, "beamwidth_3db_color", defaults.beamwidth_3db_color),
            beamwidth_6db_color=_str_value(source, "beamwidth_6db_color", defaults.beamwidth_6db_color),
            beamwidth_10db_color=_str_value(source, "beamwidth_10db_color", defaults.beamwidth_10db_color),
            gain_legend_labels=_str_value(source, "gain_legend_labels", defaults.gain_legend_labels),
            beamwidth_legend_labels=_str_value(source, "beamwidth_legend_labels", defaults.beamwidth_legend_labels),
            beam_eff_legend_labels=_str_value(source, "beam_eff_legend_labels", defaults.beam_eff_legend_labels),
            vswr_legend_labels=_str_value(source, "vswr_legend_labels", defaults.vswr_legend_labels),
            datasheet_template=_str_value(source, "datasheet_template", defaults.datasheet_template),
            pdf_metadata_author=_str_value(source, "pdf_metadata_author", defaults.pdf_metadata_author),
            rings=_str_value(source, "rings", defaults.rings),
            angle=_int_value(source, "angle", defaults.angle),
            clip=_float_value(source, "clip", defaults.clip),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def default_preset_settings() -> dict[str, object]:
    return PresetSettings().to_dict()
