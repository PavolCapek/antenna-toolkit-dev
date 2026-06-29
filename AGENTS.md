# Repository Guidelines

- This is a Windows Python desktop project for processing CST `.ffs` files and Touchstone `.s1p`/`.s2p` files.
- Main GUI entry point: `antenna_toolkit_studio.py`.
- CLI/data-generation modules include `beamwidth_xlsx.py`, `extract_data_xlsx.py`, `datasheet_pdf.py`, `plot.py`, and `plot_vswr.py`.
- Shared GUI, project, pipeline, datasheet, and plotting logic lives in `studio_*.py`, `project_store.py`, `pipeline/`, `datasheet/`, and `plotting/`.

## Setup

- Install dependencies with `python -m pip install -r requirements.txt`.
- Install `PySide6` separately if the GUI is needed: `python -m pip install PySide6`.
- Run the app with `python antenna_toolkit_studio.py` or the Windows launcher.

## Testing

- Start with the smallest useful signal. For most changes, ask the helper for targeted commands:
  `python tools/test_targeted.py`.
- For a known file set, pass files directly, for example:
  `python tools/test_targeted.py studio_run.py tests/test_studio_run_workflow.py`.
- Prefer exact test node ids or small `-k` chunks for GUI work. Avoid broad Qt-heavy file runs as the default.
- Do not run Qt-heavy Studio test files in parallel. They are marked `qt_slow` / `gui_workflow` because they can time out when run whole or side-by-side.
- For quick broad checks that should skip slow GUI workflows, use:
  `python -m pytest -m "not qt_slow" -q`.
- Prefer the targeted export acceptance suite for datasheet/PDF/plot-size work:
  `python -m pytest -m export_acceptance -q`.
- If that passes and the change is broader, run the matching test files under `tests/`.
- Avoid using one full `python -m pytest` run as the default signal; it is slow enough to time out locally. For release-level checks, split the suite by file or subsystem and use `--durations=20` on slow groups.
- Keep test updates targeted and only describe them briefly unless asked for detail.

## Working Notes

- Preserve Windows path handling and workspace-relative display paths.
- Treat `Projects/`, generated workbooks, PDFs, SVGs, and `ant_files/` outputs as generated artifacts unless a task explicitly targets them.
- Prefer small, scoped changes that follow the existing script/module style.
- After each run, provide a concise bullet-point summary.
- If committing is possible in this repository, commit completed changes automatically.
