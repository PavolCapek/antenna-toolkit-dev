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

- Run the test suite with `python -m pytest`.
- For focused changes, run the matching tests under `tests/`.
- Keep test updates targeted and only describe them briefly unless asked for detail.

## Working Notes

- Preserve Windows path handling and workspace-relative display paths.
- Treat `Projects/`, generated workbooks, PDFs, SVGs, and `ant_files/` outputs as generated artifacts unless a task explicitly targets them.
- Prefer small, scoped changes that follow the existing script/module style.
- After each run, provide a concise bullet-point summary.
- If committing is possible in this repository, commit completed changes automatically.
