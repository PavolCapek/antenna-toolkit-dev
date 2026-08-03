# Antenna Toolkit

Windows desktop tool for processing CST Studio Suite exports:

- 3D far-field `.ffs` files
- Touchstone `.s1p` / `.s2p` S-parameter files

It generates:

- beamwidth and gain workbook `.xlsx`
- ETSI EN 302 217 / FCC Part 101 compliance workbook `.xlsx`
- extracted metrics workbook `.xlsx`
- datasheet `.pdf`
- Cartesian SVG plots
- polar SVG plots
- VSWR SVG plots
- `.ant` files for each frequency sample

## Project Layout

- [antenna_toolkit_studio.py](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/antenna_toolkit_studio.py)
  Main PySide6 Studio GUI with project management
- [studio_support.py](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/studio_support.py)
  Shared Studio runtime helpers for state, presets, path handling, and subprocess execution
- [project_store.py](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/project_store.py)
  Persistent project storage and project-scoped output paths
- [beamwidth_xlsx.py](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/beamwidth_xlsx.py)
  Reads `.ffs` files and generates the workbook and `.ant` files
- [compliance_report.py](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/compliance_report.py)
  Checks co-/cross-polar directivity against ETSI EN 302 217-4 V2.2.1 and FCC Part 101 antenna requirements
- [plot.py](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/plot.py)
  Generates gain, beamwidth, beam efficiency, and polar plots from the workbook
- [plot_vswr.py](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/plot_vswr.py)
  Generates VSWR plots from Touchstone files
- [extract_data_xlsx.py](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/extract_data_xlsx.py)
  Builds the extracted-data workbook
- [Launch Antenna Toolkit Studio.cmd](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/Launch%20Antenna%20Toolkit%20Studio.cmd)
  Double-click launcher for the Studio GUI
- `Projects/`
  Generated per-project workspaces with `project.json` and outputs

## Requirements

- Windows
- Python 3
- Packages from [requirements.txt](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/requirements.txt)
- `PySide6` for the GUI

Install dependencies:

```powershell
python -m pip install -r requirements.txt
python -m pip install PySide6
```

## Testing

Use the smallest test tier that covers the change. Avoid one broad `python -m pytest` run as the default local signal.

### Test Tiers

| Tier | Use When | Command |
| --- | --- | --- |
| Smoke | Python files changed | `python -m compileall -q <changed .py files>` |
| Targeted | Normal development loop | `python tools/test_targeted.py` |
| Quick broad | You want broad non-GUI coverage | `python -m pytest -m "not qt_slow" -q` |
| GUI targeted | Studio behavior changed | Run exact node ids or small `-k` chunks from `tools/test_targeted.py` |
| Export acceptance | Datasheet/PDF/plot-size output changed | `python -m pytest -m export_acceptance -q` |
| Release | Pre-release confidence | Split by subsystem; use `--durations=20` on slow groups |

The recommender prints commands without running them:

```powershell
python tools/test_targeted.py
python tools/test_targeted.py studio_run.py tests/test_studio_run_workflow.py
```

Studio GUI workflow tests are marked `qt_slow` and `gui_workflow`. They are valid tests, but they should usually be run by exact node id or small `-k` chunks. Do not run Qt-heavy Studio files in parallel.

For datasheet PDF export, plot sizing, and Studio size-propagation changes, use the targeted acceptance suite:

```powershell
python -m pytest -m export_acceptance -q
```

For broader release checks, run test files by subsystem instead of one long full-suite command:

```powershell
python -m pytest tests/test_datasheet_pdf.py tests/test_datasheet_visual_regression.py -q
python -m pytest tests/test_pipeline_commands.py tests/test_cartesian_plot_dimensions.py tests/test_studio_pipeline.py -q
python -m pytest tests/test_studio_dirty_state.py -q --durations=20
```

## Launching The App

The easiest way is to double-click:

- [Launch Antenna Toolkit Studio.cmd](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/Launch%20Antenna%20Toolkit%20Studio.cmd)

You can also run the GUI from a terminal:

```powershell
python antenna_toolkit_studio.py
```

## Studio Workflow

### 1. Create a project

- Create a named project from the Project workspace
- Each project stores:
  - one or more `.ffs` files
  - zero or one Touchstone file
  - the current processing and chart settings
  - the selected preset and the project's saved GUI preset library
- Project metadata is saved in:
  `Projects\<project>\project.json`

### 2. Edit the active project

- Rename the project from the Project workspace
- Add or remove `.ffs` files on the Inputs tab
- Select or clear the Touchstone file on the Inputs tab
- Change presets, smoothing, frequency ranges, y-axis ranges, and chart colors
- Click `Save project` to persist pending project and preset changes

### 3. Run processing

- Workbook, extract, datasheet PDF, plot, VSWR, and full-pipeline actions all write into the active project directory
- Derived output paths are:
  - `Projects\<project>\<project>.xlsx`
  - `Projects\<project>\<project>_extracted_data.xlsx`
  - `Projects\<project>\<project>_datasheet.pdf`
  - `Projects\<project>\<project>_vswr.svg`

### 4. Delete a project

- Deleting a project removes its full `Projects\<project>\` directory, including generated results

## Path Behavior

The GUI displays workspace-relative paths where possible, for example:

- `Input data\SH60WB_Horizontal.ffs`
- `Projects\SH60WB\SH60WB.xlsx`

Internally, the app resolves these to real absolute filesystem paths before running the scripts.

## Output Structure

For a project named `SH60WB`, output is written to:

```text
Projects\SH60WB\
  project.json
  SH60WB.xlsx
  SH60WB-compliance.xlsx
  SH60WB_extracted_data.xlsx
  SH60WB_datasheet.pdf
  SH60WB_gain.svg
  SH60WB_beamwidth.svg
  SH60WB_beam_efficiency.svg
  SH60WB_vswr.svg
  radiaiton pattern files\
    ant_files\
    linkCalc\
    netsim\
  polar_combined\
  polar_single\
```

`radiaiton pattern files\linkCalc\` contains one headerless `.ffs` file per
enabled far-field input and frequency sample. Each UTF-8 row is space-separated
`phi`, `theta`, and absolute total-field directivity in dBi, and filenames use
`<source-stem>-<frequencyGHz>.ffs`.

`radiaiton pattern files\netsim\` contains one extensionless JSON antenna file
per enabled far-field input. Each file retains its UUID across reruns and stores
every source frequency in MHz as a 361-by-181 gain matrix (phi rows 0..360
degrees, theta columns 0..180 degrees). Coarser source grids are interpolated
to one-degree spacing.

## Workbook Contents

The generated `.xlsx` contains:

- one data sheet per input `.ffs`
- one `phi0` radiation sheet per input `.ffs`
- one `phi90` radiation sheet per input `.ffs`
- one global `summary` sheet

Numeric cells are written as real numbers, not strings.

## Standards Compliance

The Compliance stage evaluates every enabled `.ffs` file and every frequency in
the shared frequency window. Its workbook contains:

- a per-frequency summary with the best ETSI RPE class, ETSI XPD category, and FCC performance standard passed
- an antenna rollup showing which classifications pass at every checked frequency in each applicable band
- a row for every applicable ETSI RPE class with co-/cross-polar pass state, limiting angle, and margin
- a row for every applicable FCC A/B/B1/B2 or band requirement with beamwidth, directivity, suppression, and XPD evidence
- a methodology sheet identifying the rule editions, source links, coordinate convention, and limitations

The checker uses Ludwig-3 co-/cross-polar components and treats directivity as
gain for all standards comparisons. This is an engineering pre-compliance
assessment from simulation or supplied pattern data, not an accredited
measurement report or regulatory certification.

## Command-Line Usage

Generate workbook from `.ffs`:

```powershell
python beamwidth_xlsx.py "Projects\SH60WB\SH60WB.xlsx" "Input data\SH60WB_Horizontal.ffs" "Input data\SH60WB_Vertical.ffs" --smooth 5 --theta-window 8
```

Generate the ETSI/FCC compliance workbook:

```powershell
python compliance_report.py "Projects\SH60WB\SH60WB-compliance.xlsx" "Input data\SH60WB_Horizontal.ffs" "Input data\SH60WB_Vertical.ffs" --fmin 4.8 --fmax 6.2
```

Generate plots from workbook:

```powershell
python plot.py "Projects\SH60WB\SH60WB.xlsx" --out-dir "Projects\SH60WB" --fmin 4.8 --fmax 6.2 --x-step 0.2 --gain-legend-labels "Horizontal,Vertical" --beamwidth-legend-labels "Horizontal Azimuth,Horizontal Elevation,Vertical Azimuth,Vertical Elevation"
```

Generate VSWR plot:

```powershell
python plot_vswr.py "Input data\SH60WB.s2p" --output "Projects\SH60WB\SH60WB_vswr.svg" --fmin 4.8 --fmax 6.2 --x-step 0.2 --legend-labels "Port A,Port B"
```

Generate datasheet PDF:

```powershell
python datasheet_pdf.py "Projects\SH60WB\SH60WB_datasheet.pdf" --template "Datasheet.pdf" --extract-workbook "Projects\SH60WB\SH60WB_extracted_data.xlsx"
```

## Notes

- Studio project names are explicit and persistent
- Missing output directories are created automatically
- The x-axis lower bound is kept inside the selected frequency window instead of expanding below `fmin`
- The sample files in `Input data/` can be used as a reference test case
