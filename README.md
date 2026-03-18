# Antenna Toolkit

Windows desktop tool for processing CST Studio Suite exports:

- 3D far-field `.ffs` files
- Touchstone `.s2p` S-parameter files

It generates:

- beamwidth and gain workbook `.xlsx`
- Cartesian SVG plots
- polar SVG plots
- VSWR SVG plots
- `.ant` files for each frequency sample

## Project Layout

- [antenna_toolkit_qt.py](/C:/Users/capek/OneDrive/Documents/antenna_toolkit_dev/antenna_toolkit_qt.py)
  Main PySide6 GUI
- [beamwidth_xlsx.py](/C:/Users/capek/OneDrive/Documents/antenna_toolkit_dev/beamwidth_xlsx.py)
  Reads `.ffs` files and generates the workbook and `.ant` files
- [plot.py](/C:/Users/capek/OneDrive/Documents/antenna_toolkit_dev/plot.py)
  Generates gain, beamwidth, beam efficiency, and polar plots from the workbook
- [plot_vswr.py](/C:/Users/capek/OneDrive/Documents/antenna_toolkit_dev/plot_vswr.py)
  Generates VSWR plots from `.s2p`
- [Input data](/C:/Users/capek/OneDrive/Documents/antenna_toolkit_dev/Input%20data)
  Example CST exports
- [Results](/C:/Users/capek/OneDrive/Documents/antenna_toolkit_dev/Results)
  Generated output files
- [Launch Antenna Toolkit.cmd](/C:/Users/capek/OneDrive/Documents/antenna_toolkit_dev/Launch%20Antenna%20Toolkit.cmd)
  Double-click launcher for the GUI

## Requirements

- Windows
- Python 3
- Packages from [requirements.txt](/C:/Users/capek/OneDrive/Documents/antenna_toolkit_dev/requirements.txt)
- `PySide6` for the GUI

Install dependencies:

```powershell
python -m pip install -r requirements.txt
python -m pip install PySide6
```

## Launching The App

The easiest way is to double-click:

- [Launch Antenna Toolkit.cmd](/C:/Users/capek/OneDrive/Documents/antenna_toolkit_dev/Launch%20Antenna%20Toolkit.cmd)

A Desktop shortcut can also point to that launcher.

You can also run the GUI from a terminal:

```powershell
python antenna_toolkit_qt.py
```

## GUI Workflow

### 1. Far-field export

- Add one or more `.ffs` files
- The app automatically deduces the project name from the selected far-field files
- The workbook path is auto-derived as:
  `Results\<project>\<project>.xlsx`

### 2. Plots from Excel

- Uses the derived workbook automatically
- Saves SVG plots into:
  `Results\<project>\`
- Supports:
  - `fmin` / `fmax`
  - x tick step
  - smoothing
  - grid color
  - manual line colors with preset defaults

### 3. VSWR

- Select one `.s2p` file
- The output SVG is auto-derived in the same project result folder
- Supports:
  - `fmin` / `fmax`
  - x/y limits
  - x/y tick steps
  - smoothing
  - grid color
  - manual line colors with preset defaults

### 4. Full pipeline

The toolbar action `Run FULL pipeline` does:

1. Generate the `.xlsx` workbook from the selected `.ffs` files
2. Generate plots from that workbook

VSWR is run separately from the VSWR section because it depends on the selected `.s2p` file.

## Path Behavior

The GUI displays workspace-relative paths where possible, for example:

- `Input data\SH60WB_Horizontal.ffs`
- `Results\SH60WB\SH60WB.xlsx`

Internally, the app resolves these to real absolute filesystem paths before running the scripts.

## Output Structure

For a project named `SH60WB`, output is written to:

```text
Results\SH60WB\
  SH60WB.xlsx
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
python beamwidth_xlsx.py "Results\SH60WB\SH60WB.xlsx" "Input data\SH60WB_Horizontal.ffs" "Input data\SH60WB_Vertical.ffs" --smooth 5 --theta-window 8
```

Generate plots from workbook:

```powershell
python plot.py "Results\SH60WB\SH60WB.xlsx" --out-dir "Results\SH60WB" --fmin 4.8 --fmax 6.2 --x-step 0.2
```

Generate VSWR plot:

```powershell
python plot_vswr.py "Input data\SH60WB.s2p" --output "Results\SH60WB\SH60WB_vswr.svg" --fmin 4.8 --fmax 6.2 --x-step 0.2
```

## Notes

- Project-name deduction is based primarily on the selected `.ffs` files
- Missing output directories are created automatically
- The x-axis lower bound is kept inside the selected frequency window instead of expanding below `fmin`
- The sample files in [Input data](/C:/Users/capek/OneDrive/Documents/antenna_toolkit_dev/Input%20data) can be used as a reference test case
