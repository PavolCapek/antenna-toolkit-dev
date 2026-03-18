# Antenna Toolkit

Windows desktop tool for processing CST Studio Suite exports:

- 3D far-field `.ffs` files
- Touchstone `.s1p` / `.s2p` S-parameter files

It generates:

- beamwidth and gain workbook `.xlsx`
- extracted metrics workbook `.xlsx`
- Cartesian SVG plots
- polar SVG plots
- VSWR SVG plots
- `.ant` files for each frequency sample

## Project Layout

- [antenna_toolkit_studio.py](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/antenna_toolkit_studio.py)
  Main PySide6 Studio GUI with project management
- [project_store.py](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/project_store.py)
  Persistent project storage and project-scoped output paths
- [antenna_toolkit_qt.py](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/antenna_toolkit_qt.py)
  Legacy PySide6 GUI
- [beamwidth_xlsx.py](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/beamwidth_xlsx.py)
  Reads `.ffs` files and generates the workbook and `.ant` files
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

## Launching The App

The easiest way is to double-click:

- [Launch Antenna Toolkit Studio.cmd](/C:/Users/capek/OneDrive/Documents/Git/antenna-toolkit-dev/Launch%20Antenna%20Toolkit%20Studio.cmd)

You can also run the GUI from a terminal:

```powershell
python antenna_toolkit_studio.py
```

## Studio Workflow

### 1. Create a project

- Create a named project from the Project workspace card
- Each project stores:
  - one or more `.ffs` files
  - zero or one Touchstone file
  - the current processing and chart settings
- Project metadata is saved in:
  `Projects\<project>\project.json`

### 2. Edit the active project

- Add or remove `.ffs` files
- Select or clear the Touchstone file
- Change smoothing, frequency ranges, y-axis ranges, and chart colors
- Changes are saved back into the selected project automatically

### 3. Run processing

- Workbook, extract, plot, VSWR, and full-pipeline actions all write into the active project directory
- Derived output paths are:
  - `Projects\<project>\<project>.xlsx`
  - `Projects\<project>\<project>_extracted_data.xlsx`
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
  SH60WB_extracted_data.xlsx
  SH60WB_gain.svg
  SH60WB_beamwidth.svg
  SH60WB_beam_efficiency.svg
  SH60WB_vswr.svg
  ant_files\
  polar_combined\
  polar_single\
```

## Workbook Contents

The generated `.xlsx` contains:

- one data sheet per input `.ffs`
- one `phi0` radiation sheet per input `.ffs`
- one `phi90` radiation sheet per input `.ffs`
- one global `summary` sheet

Numeric cells are written as real numbers, not strings.

## Command-Line Usage

Generate workbook from `.ffs`:

```powershell
python beamwidth_xlsx.py "Projects\SH60WB\SH60WB.xlsx" "Input data\SH60WB_Horizontal.ffs" "Input data\SH60WB_Vertical.ffs" --smooth 5 --theta-window 8
```

Generate plots from workbook:

```powershell
python plot.py "Projects\SH60WB\SH60WB.xlsx" --out-dir "Projects\SH60WB" --fmin 4.8 --fmax 6.2 --x-step 0.2
```

Generate VSWR plot:

```powershell
python plot_vswr.py "Input data\SH60WB.s2p" --output "Projects\SH60WB\SH60WB_vswr.svg" --fmin 4.8 --fmax 6.2 --x-step 0.2
```

## Notes

- Studio project names are explicit and persistent
- Missing output directories are created automatically
- The x-axis lower bound is kept inside the selected frequency window instead of expanding below `fmin`
- The sample files in `Input data/` can be used as a reference test case
