from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreflightIssue:
    code: str
    message: str


def collect_preflight_issues(
    *,
    stage_keys: list[str],
    has_active_project: bool,
    enabled_ffs: list[str],
    missing_ffs_display: list[str],
    touchstone_selected: bool,
    touchstone_ready: bool,
    touchstone_display: str,
    technical_data: str,
    technical_data_is_url: bool,
    technical_data_is_google_sheet: bool,
    google_sheet_has_id: bool,
    google_sheets_auth_configured: bool,
    technical_data_exists: bool,
    technical_data_display: str,
    template_exists: bool,
    template_display: str,
    frequency_window_valid: bool,
    beam_output_exists: bool,
    extract_output_exists: bool,
    extract_stage_stale: bool,
    plot_output_exists: bool,
    plot_stage_stale: bool,
) -> list[PreflightIssue]:
    if not has_active_project:
        return [PreflightIssue("missing_project", "Create or select a project first.")]

    requested = set(stage_keys)
    needs_ffs = bool(requested & {"beam", "extract", "plot", "datasheet"})
    needs_frequency = bool(requested & {"extract", "plot", "vswr", "datasheet"})
    needs_touchstone = bool(requested & {"vswr", "datasheet"})
    needs_technical_data = "datasheet" in requested
    needs_template = "datasheet" in requested

    issues: list[PreflightIssue] = []

    if needs_ffs and not enabled_ffs:
        issues.append(PreflightIssue("missing_ffs", "Add at least one enabled .ffs file."))
    if missing_ffs_display and (needs_ffs or "extract" in requested):
        sample = ", ".join(missing_ffs_display[:3])
        more = " ..." if len(missing_ffs_display) > 3 else ""
        issues.append(PreflightIssue("missing_ffs_path", f"Fix or disable missing .ffs files: {sample}{more}"))

    if needs_touchstone and not touchstone_selected:
        issues.append(PreflightIssue("missing_touchstone", "Select a Touchstone .s1p or .s2p file."))
    elif touchstone_selected and not touchstone_ready and ("extract" in requested or needs_touchstone):
        issues.append(PreflightIssue("invalid_touchstone", f"Fix the missing Touchstone file: {touchstone_display}"))

    if "extract" in requested and not enabled_ffs and not touchstone_ready:
        issues.append(
            PreflightIssue(
                "extract_inputs_missing",
                "Extract needs at least one valid .ffs file or a valid Touchstone file.",
            )
        )

    if needs_technical_data:
        if not technical_data:
            issues.append(PreflightIssue("missing_technical_data", "Select a Technical Data workbook or Google Sheet."))
        elif technical_data_is_url and not technical_data_is_google_sheet:
            issues.append(
                PreflightIssue(
                    "invalid_technical_data_url",
                    "Use a Google Sheet link or a local workbook for Technical Data.",
                )
            )
        elif technical_data_is_google_sheet:
            if not google_sheet_has_id:
                issues.append(
                    PreflightIssue(
                        "google_sheet_missing_id",
                        "The selected Google Sheet URL is missing a spreadsheet ID.",
                    )
                )
            elif not google_sheets_auth_configured:
                issues.append(
                    PreflightIssue(
                        "google_sheet_auth_required",
                        "Sign in to Google Sheets before generating the datasheet.",
                    )
                )
        elif not technical_data_exists:
            issues.append(
                PreflightIssue(
                    "missing_technical_data_file",
                    f"Fix the missing Technical Data workbook: {technical_data_display}",
                )
            )

    if needs_template and not template_exists:
        issues.append(
            PreflightIssue(
                "missing_template",
                f"Select an available datasheet export style: {template_display}",
            )
        )

    if needs_frequency and not frequency_window_valid:
        issues.append(PreflightIssue("invalid_frequency_window", "Set a valid shared frequency window or clear it."))

    if "plot" in requested and not beam_output_exists and "beam" not in requested:
        issues.append(PreflightIssue("missing_beam_output", "Generate the workbook before running Plots."))

    if "datasheet" in requested:
        if not extract_output_exists and "extract" not in requested:
            issues.append(
                PreflightIssue(
                    "missing_extract_output",
                    "Generate the extract workbook before generating the datasheet.",
                )
            )
        elif "extract" not in requested and extract_stage_stale:
            issues.append(PreflightIssue("stale_extract_output", "Rerun Extract before generating the datasheet."))
        if not plot_output_exists and "plot" not in requested:
            issues.append(PreflightIssue("missing_plot_output", "Generate plots before generating the datasheet."))
        elif "plot" not in requested and plot_stage_stale:
            issues.append(PreflightIssue("stale_plot_output", "Rerun Plots before generating the datasheet."))

    return issues
