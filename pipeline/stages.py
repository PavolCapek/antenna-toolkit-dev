from __future__ import annotations

from pathlib import Path
from typing import Any

from datasheet.artifacts import artifact_manifest_path
from pipeline.versions import stage_versions

STAGE_SETTING_KEYS: dict[str, tuple[str, ...]] = {
    "beam": ("smooth", "theta"),
    "extract": ("smooth", "theta", "shared_fmin", "shared_fmax"),
    "datasheet": (
        "smooth",
        "theta",
        "shared_fmin",
        "shared_fmax",
        "cartesian_figure_width",
        "cartesian_figure_height",
        "polar_figure_size",
        "datasheet_template",
        "pdf_metadata_author",
    ),
    "plot": (
        "smooth2",
        "shared_xstep",
        "shared_fmin",
        "shared_fmax",
        "shared_xlog",
        "gain_ymin",
        "gain_ymax",
        "gain_y_step",
        "beamwidth_ymin",
        "beamwidth_ymax",
        "beamwidth_y_step",
        "beam_eff_ymin",
        "beam_eff_ymax",
        "beam_eff_y_step",
        "grid_color",
        "cartesian_grid_line_width",
        "polar_grid_line_width",
        "cartesian_line_width",
        "polar_line_width",
        "cartesian_figure_width",
        "cartesian_figure_height",
        "polar_figure_size",
        "cartesian_font_size",
        "polar_font_size",
        "cartesian_legend_font_size",
        "polar_legend_font_size",
        "plot_line_1",
        "plot_line_2",
        "polar_azimuth_line_1_color",
        "polar_azimuth_line_1_style",
        "polar_azimuth_line_2_color",
        "polar_azimuth_line_2_style",
        "polar_elevation_line_1_color",
        "polar_elevation_line_1_style",
        "polar_elevation_line_2_color",
        "polar_elevation_line_2_style",
        "beamwidth_3db_color",
        "beamwidth_6db_color",
        "beamwidth_10db_color",
        "gain_legend_labels",
        "beamwidth_legend_labels",
        "beam_eff_legend_labels",
        "rings",
        "angle",
        "clip",
    ),
    "vswr": (
        "shared_xstep",
        "shared_fmin",
        "shared_fmax",
        "shared_xlog",
        "vswr_ymin",
        "vswr_ymax",
        "vswr_ystep",
        "vswr_smooth",
        "grid_color",
        "cartesian_grid_line_width",
        "cartesian_line_width",
        "cartesian_figure_width",
        "cartesian_figure_height",
        "cartesian_font_size",
        "cartesian_legend_font_size",
        "plot_line_1",
        "plot_line_2",
        "vswr_legend_labels",
    ),
}


def stage_settings_snapshot(stage_key: str, values: dict[str, Any]) -> dict[str, Any]:
    return {key: values[key] for key in STAGE_SETTING_KEYS.get(stage_key, ()) if key in values}


def stage_tool_versions(
    stage_key: str,
    *,
    plot_asset_style_version: int | None = None,
    vswr_asset_style_version: int | None = None,
    datasheet_render_version: int | None = None,
) -> dict[str, int]:
    versions = stage_versions(stage_key)
    if plot_asset_style_version is not None and stage_key in {"plot", "datasheet"}:
        versions["plot_assets"] = int(plot_asset_style_version)
    if vswr_asset_style_version is not None and stage_key in {"vswr", "datasheet"}:
        versions["vswr_assets"] = int(vswr_asset_style_version)
    if datasheet_render_version is not None and stage_key == "datasheet":
        versions["datasheet_render"] = int(datasheet_render_version)
    return versions


def stage_output_files(
    stage_key: str,
    *,
    project_dir: Path,
    beam_output: Path,
    extract_output: Path,
    datasheet_output: Path,
    vswr_output: Path,
) -> list[Path]:
    if stage_key == "beam":
        files = [beam_output]
        for folder_name in ("ant_files", "linkCalc", "netsim"):
            folder = project_dir / folder_name
            if folder.exists():
                files.extend(path for path in folder.rglob("*") if path.is_file())
        return files
    if stage_key == "extract":
        return [extract_output]
    if stage_key == "datasheet":
        return [datasheet_output]
    if stage_key == "vswr":
        return [
            vswr_output,
            vswr_output.with_name(f"{vswr_output.stem}-legend{vswr_output.suffix}"),
        ]
    if stage_key == "plot":
        stem = beam_output.stem
        files = [
            project_dir / f"{stem}-gain.svg",
            project_dir / f"{stem}-gain-legend.svg",
            project_dir / f"{stem}-beamwidth.svg",
            project_dir / f"{stem}-beamwidth-legend.svg",
            project_dir / f"{stem}-beam-efficiency.svg",
            project_dir / f"{stem}-beam-efficiency-legend.svg",
            artifact_manifest_path(project_dir, stem),
        ]
        files.extend(path for path in project_dir.glob(f"{stem}-beamwidth-*-plane-*.svg") if path.is_file())
        for folder_name in ("polar_combined", "polar_single"):
            folder = project_dir / folder_name
            if folder.exists():
                files.extend(path for path in folder.rglob("*") if path.is_file())
        return files
    return []


def stage_generated_directories(stage_key: str, *, project_dir: Path) -> list[Path]:
    if stage_key == "beam":
        return [
            project_dir / "ant_files",
            project_dir / "linkCalc",
            project_dir / "netsim",
        ]
    if stage_key == "plot":
        return [project_dir / "polar_combined", project_dir / "polar_single"]
    return []


def stage_is_applicable(
    stage_key: str,
    *,
    has_enabled_ffs: bool,
    has_touchstone: bool,
    has_technical_data: bool,
) -> bool:
    if stage_key == "beam":
        return has_enabled_ffs
    if stage_key == "extract":
        return has_enabled_ffs or has_touchstone
    if stage_key == "datasheet":
        return has_enabled_ffs and has_touchstone and has_technical_data
    if stage_key == "plot":
        return has_enabled_ffs
    if stage_key == "vswr":
        return has_touchstone
    return False


def stage_stale_detail(stage_key: str, previous_versions: object, current_versions: dict[str, int]) -> str:
    if not current_versions or previous_versions == current_versions:
        return ""
    if stage_key == "plot":
        return "App plot styling changed. Rerun Plots only."
    if stage_key == "datasheet":
        return "App plot or datasheet styling changed. Rerun Plots only, then Datasheet only."
    return "App generation rules changed. Rerun this output."
