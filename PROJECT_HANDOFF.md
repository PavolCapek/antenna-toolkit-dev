# Antenna Toolkit handoff

## Setup

This Windows PySide6 app processes CST far-field `.ffs` exports and Touchstone `.s1p`/`.s2p` files. Create a `.venv`, install `requirements.txt` plus `PySide6` and `pytest`, then run `.venv\Scripts\python.exe antenna_toolkit_studio.py`. Local inputs and project outputs are kept under `Input data/` and `Projects/` and may need to be supplied separately on a new machine.

## Pipeline

- `antenna_toolkit_studio.py` and `studio_run.py` manage projects and queue stages. `pipeline/commands.py` builds CLI arguments, while `pipeline/stages.py` and `pipeline/versions.py` track which outputs need to be regenerated.
- `beamwidth_xlsx.py` builds the beam workbook and pattern exports. `adf_export.py` writes one NSMA ADF envelope per project under `radiaiton pattern files/adf/`. The Standards Compliance min/max fields select the included samples in GHz. A zero bound is unrestricted. ADF gain headers use directivity, and frequency headers report the actual included band in MHz.
- `compliance_report.py` generates ETSI/FCC results. `extract_data_xlsx.py` summarizes far-field and Touchstone metrics. `plot.py` and `plot_vswr.py` generate chart assets.
- `datasheet_pdf.py` assembles template PDFs from the Extract workbook, plot assets, and technical data. `datasheet/models.py` formats performance fields. A cut without a downward threshold crossing can leave a beamwidth blank in Extract. The datasheet shows `N/A` for that individual value and retains the other thresholds and polarizations.

## Verification

Run `python tools/test_targeted.py` for relevant checks and `python -m pytest -m export_acceptance -q` for export changes. Keep Qt workflow tests targeted and run them sequentially. Use Studio’s Run tab and console to identify the failed stage, then **Run Failed Stage** to verify a fix against the same project inputs.
