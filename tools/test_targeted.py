#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def _repo_changed_files(base: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", base],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]


def _add(commands: list[str], command: str) -> None:
    if command not in commands:
        commands.append(command)


def _py_files(paths: list[str]) -> list[str]:
    return [path for path in paths if path.endswith(".py") and Path(path).exists()]


def recommended_commands(paths: list[str]) -> list[str]:
    normalized = [path.replace("\\", "/") for path in paths]
    commands: list[str] = []
    py_files = _py_files(normalized)
    if py_files:
        _add(commands, "python -m compileall -q " + " ".join(py_files))

    touched = set(normalized)

    def any_touched(*prefixes_or_files: str) -> bool:
        return any(
            path == item or path.startswith(item.rstrip("/") + "/")
            for path in touched
            for item in prefixes_or_files
        )

    if any_touched("studio_run.py"):
        _add(
            commands,
            "python -m pytest "
            "tests/test_studio_run_workflow.py::StudioRunWorkflowTests::test_run_full_shows_progress_before_preparing_technical_data "
            "tests/test_studio_run_workflow.py::StudioRunWorkflowTests::test_running_progress_updates_summary_and_stage_rows -q",
        )
    if any_touched("antenna_toolkit_studio.py", "studio_support.py", "studio_runtime.py", "project_store.py"):
        _add(
            commands,
            "python -m pytest tests/test_studio_run_workflow.py -q "
            "-k \"preflight or validate or needed or running_progress\"",
        )
    if any_touched("tests/test_studio_run_workflow.py"):
        _add(
            commands,
            "python -m pytest tests/test_studio_run_workflow.py::StudioRunWorkflowTests::test_run_full_shows_progress_before_preparing_technical_data -q",
        )
    if any_touched("tests/test_studio_ui_layout.py"):
        _add(
            commands,
            "python -m pytest tests/test_studio_ui_layout.py::StudioUiLayoutTests::test_progress_updates_debounce_refresh_work -q",
        )
    if any_touched("tests/test_studio_google_sheets.py"):
        _add(commands, "python -m pytest tests/test_studio_google_sheets.py -q -k \"google_sheet or run_full\"")

    if any_touched("plot.py", "plot_vswr.py", "plotting"):
        _add(
            commands,
            "python -m pytest tests/test_plot_legend_export.py tests/test_cartesian_plot_dimensions.py tests/test_plot_beamwidth_planes.py -q",
        )
    if any_touched("beamwidth_xlsx.py", "extract_data_xlsx.py", "pipeline/progress.py"):
        _add(commands, "python -m pytest tests/test_progress_reporting.py tests/test_beam_efficiency_mask.py -q")
    if any_touched("pipeline"):
        _add(
            commands,
            "python -m pytest tests/test_pipeline_commands.py tests/test_pipeline_preflight.py tests/test_studio_pipeline.py -q",
        )
    if any_touched("datasheet_pdf.py", "datasheet"):
        _add(
            commands,
            "python -m pytest tests/test_datasheet_pdf.py tests/test_datasheet_pipeline.py tests/test_technical_data.py -q",
        )
    if any_touched("datasheet_pdf.py", "plot.py", "plot_vswr.py", "plotting", "datasheet/layouts"):
        _add(commands, "python -m pytest -m export_acceptance -q")
    if any_touched("legend_utils.py"):
        _add(commands, "python -m pytest tests/test_legend_utils.py -q")
    if any_touched("requirements.txt", "pytest.ini"):
        _add(commands, "python -m pytest --collect-only -q")

    if not commands:
        _add(commands, "python -m pytest -m \"not qt_slow\" -q")
    return commands


def main() -> int:
    parser = argparse.ArgumentParser(description="Print targeted test commands for changed files.")
    parser.add_argument("files", nargs="*", help="Changed files. If omitted, uses git diff against --base.")
    parser.add_argument("--base", default="HEAD", help="Git base for auto-detecting changed files. Default: HEAD.")
    args = parser.parse_args()

    files = [item.replace("\\", "/") for item in args.files] if args.files else _repo_changed_files(args.base)
    if files:
        print("Changed files:")
        for path in files:
            print(f"- {path}")
    else:
        print(f"No changed files detected against {args.base}.")
    print()
    print("Recommended commands:")
    for command in recommended_commands(files):
        print(command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
