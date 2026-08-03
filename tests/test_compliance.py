from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from compliance.engine import Pattern, _build_rollup, analyze_pattern, mask_limits, pattern_from_rows
from compliance.standards import etsi_profiles_for_frequency, fcc_profiles_for_frequency
from compliance_report import write_workbook


def _synthetic_h_rows() -> list[tuple[float, float, complex, complex]]:
    rows: list[tuple[float, float, complex, complex]] = []
    for phi in (0.0, 90.0, 180.0, 270.0, 360.0):
        phi_rad = math.radians(phi)
        for theta in np.arange(0.0, 181.0, 1.0):
            amplitude = math.exp(-((theta / 0.7) ** 2)) + 1e-6
            rows.append(
                (
                    phi,
                    float(theta),
                    complex(amplitude * math.cos(phi_rad), 0.0),
                    complex(-amplitude * math.sin(phi_rad), 0.0),
                )
            )
    return rows


def test_mask_limits_use_last_value_at_vertical_step() -> None:
    angles = np.asarray([70.0, 99.0, 100.0, 101.0, 180.0])
    limits, valid = mask_limits(((70, -2), (100, -7), (100, -10), (180, -10)), angles)

    assert valid.all()
    assert -7 < limits[1] < -6
    assert limits[2] == -10
    assert limits[3] == -10


def test_standard_profiles_are_frequency_specific() -> None:
    assert [profile.class_name for profile in etsi_profiles_for_frequency(4.7)] == ["1", "2", "3", "4"]
    assert [profile.standard for profile in fcc_profiles_for_frequency(6000)] == ["A", "B1", "B2"]
    assert not fcc_profiles_for_frequency(4700)


def test_pattern_uses_ludwig_three_components_and_directivity() -> None:
    pattern = pattern_from_rows(Path("demo_H.ffs"), 6e9, _synthetic_h_rows())

    assert pattern.polarization == "H"
    assert pattern.polarization_basis == "port label or filename"
    assert np.nanmax(pattern.cross_directivity_dbi) < np.nanmax(pattern.co_directivity_dbi) - 100
    assert pattern.max_directivity_dbi > 20


def test_pattern_analysis_reports_etsi_and_fcc_results() -> None:
    pattern = pattern_from_rows(Path("demo_H.ffs"), 6e9, _synthetic_h_rows())
    summary, etsi_rows, fcc_rows = analyze_pattern(Path("demo_H.ffs"), "H", pattern)

    assert summary["etsi_range"] == "1 (3-14 GHz)"
    assert summary["fcc_band"] == "5925-6425 MHz"
    assert len(etsi_rows) == 4
    assert [row["standard"] for row in fcc_rows] == ["A", "B1", "B2"]
    assert all(row["beam_or_gain_pass"] for row in fcc_rows)


def test_each_failed_etsi_class_has_a_plain_language_note() -> None:
    phis = np.asarray([0.0, 90.0, 180.0, 270.0])
    thetas = np.arange(0.0, 181.0, 1.0)
    pattern = Pattern(
        frequency_hz=6e9,
        phis_deg=phis,
        thetas_deg=thetas,
        total_directivity_dbi=np.zeros((len(phis), len(thetas))),
        co_directivity_dbi=np.zeros((len(phis), len(thetas))),
        cross_directivity_dbi=np.full((len(phis), len(thetas)), -40.0),
        polarization="H",
        polarization_basis="test",
    )

    _, etsi_rows, _ = analyze_pattern(Path("demo_H.ffs"), "H", pattern)
    failed = [row for row in etsi_rows if row["status"] == "FAIL"]

    assert failed
    assert all(str(row["note"]).startswith(f"ETSI Class {row['rpe_class']} fails because") for row in failed)
    assert all("above the allowed limit" in str(row["note"]) for row in failed)
    assert all("measured" in str(row["note"]) and "limit" in str(row["note"]) for row in failed)


def test_each_failed_etsi_xpd_category_has_a_plain_language_rollup_note() -> None:
    phis = np.asarray([0.0, 90.0, 180.0, 270.0])
    thetas = np.arange(0.0, 181.0, 1.0)
    pattern = Pattern(
        frequency_hz=6e9,
        phis_deg=phis,
        thetas_deg=thetas,
        total_directivity_dbi=np.zeros((len(phis), len(thetas))),
        co_directivity_dbi=np.zeros((len(phis), len(thetas))),
        cross_directivity_dbi=np.full((len(phis), len(thetas)), -10.0),
        polarization="H",
        polarization_basis="test",
    )

    summary, etsi_rows, fcc_rows = analyze_pattern(Path("demo_H.ffs"), "H", pattern)
    rollup = _build_rollup([summary], etsi_rows, fcc_rows)
    failed_xpd = [row for row in rollup if row["family"] == "ETSI XPD" and row["status"] == "FAIL"]

    assert failed_xpd
    assert all("fails because" in str(row["note"]) for row in failed_xpd)
    assert all("below the required" in str(row["note"]) for row in failed_xpd)


def test_compliance_workbook_contains_traceable_sheets(tmp_path: Path) -> None:
    output = tmp_path / "compliance.xlsx"
    results = {
        "rollup": [{"source_file": "demo.ffs", "family": "FCC Part 101", "classification": "Standard A", "status": "PASS"}],
        "summary": [{"source_file": "demo.ffs", "frequency_ghz": 6.0, "fcc_best_standard": "A"}],
        "etsi": [
            {
                "source_file": "demo.ffs",
                "rpe_class": "3",
                "status": "FAIL",
                "note": "ETSI Class 3 fails because the co-polar azimuth pattern is 2.00 dB above the allowed limit.",
            }
        ],
        "fcc": [{"source_file": "demo.ffs", "standard": "A", "status": "PASS"}],
    }

    write_workbook(output, results, fmin_ghz=5.9, fmax_ghz=6.1)

    from openpyxl import load_workbook

    workbook = load_workbook(output, data_only=True)
    assert workbook.sheetnames == ["Antenna Rollup", "Summary", "ETSI RPE Details", "FCC Details", "Methodology"]
    methodology = dict(workbook["Methodology"].iter_rows(values_only=True))
    assert "Directivity is used" in methodology["Gain convention"]
    headers = [cell.value for cell in workbook["ETSI RPE Details"][1]]
    note_column = headers.index("Note") + 1
    assert "ETSI Class 3 fails because" in workbook["ETSI RPE Details"].cell(2, note_column).value
