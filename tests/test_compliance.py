from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from compliance.engine import (
    Pattern,
    _build_per_frequency_results,
    _build_rollup,
    analyze_files,
    analyze_pattern,
    mask_limits,
    parse_omitted_angle_range,
    pattern_from_rows,
)
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


def test_omitted_angle_range_parser_accepts_range_single_angle_and_blank() -> None:
    assert parse_omitted_angle_range("179-180") == (179.0, 180.0)
    assert parse_omitted_angle_range("180") == (180.0, 180.0)
    assert parse_omitted_angle_range("") is None
    with pytest.raises(ValueError, match="0 <= minimum"):
        parse_omitted_angle_range("181-181")


def test_omitted_angle_range_removes_backlobe_sample_from_etsi_and_fcc_checks() -> None:
    phis = np.asarray([0.0, 90.0, 180.0, 270.0])
    thetas = np.arange(0.0, 181.0, 1.0)
    co = np.full((len(phis), len(thetas)), -40.0)
    co[:, 0] = 40.0
    co[:, -1] = -8.15
    pattern = Pattern(
        frequency_hz=6e9,
        phis_deg=phis,
        thetas_deg=thetas,
        total_directivity_dbi=co.copy(),
        co_directivity_dbi=co,
        cross_directivity_dbi=np.full_like(co, -80.0),
        polarization="H",
        polarization_basis="test",
    )

    _, strict_etsi, strict_fcc = analyze_pattern(Path("demo_H.ffs"), "H", pattern)
    _, screened_etsi, screened_fcc = analyze_pattern(
        Path("demo_H.ffs"),
        "H",
        pattern,
        omitted_angle_range=(180.0, 180.0),
    )

    strict_class2 = next(row for row in strict_etsi if row["rpe_class"] == "2")
    screened_class2 = next(row for row in screened_etsi if row["rpe_class"] == "2")
    assert strict_class2["status"] == "FAIL"
    assert strict_class2["limiting_angle_deg"] == 180.0
    assert screened_class2["status"] == "PASS"
    assert screened_class2["note"] == ""

    strict_standard_a = next(row for row in strict_fcc if row["standard"] == "A")
    screened_standard_a = next(row for row in screened_fcc if row["standard"] == "A")
    assert strict_standard_a["status"] == "FAIL"
    assert strict_standard_a["limiting_angle_deg"] == 180.0
    assert screened_standard_a["status"] == "PASS"


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


def test_file_analysis_filters_every_available_sample_to_compliance_frequency_window(monkeypatch) -> None:
    rows = _synthetic_h_rows()
    monkeypatch.setattr(
        "compliance.engine.read_ffs_broadband",
        lambda _path: {4e9: rows, 6e9: rows, 8e9: rows},
    )

    results = analyze_files(
        [Path("demo_H.ffs")],
        fmin_ghz=5.0,
        fmax_ghz=7.0,
    )

    assert [row["frequency_ghz"] for row in results["summary"]] == [6.0]


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


def test_per_frequency_results_cover_every_applicable_class_and_standard() -> None:
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
    rows = _build_per_frequency_results([summary], etsi_rows, fcc_rows)

    assert len([row for row in rows if row["family"] == "ETSI RPE"]) == 4
    assert len([row for row in rows if row["family"] == "ETSI XPD"]) == 3
    assert len([row for row in rows if row["family"] == "FCC Part 101"]) == 3
    assert all(row["frequency_ghz"] == 6.0 for row in rows)
    failed_fcc = [row for row in rows if row["family"] == "FCC Part 101" and row["status"] == "FAIL"]
    assert failed_fcc
    assert all("fails because" in str(row["note"]) for row in failed_fcc)
    assert all(row.get("limiting_component") for row in failed_fcc)


def test_per_frequency_results_keep_samples_outside_all_standard_bands() -> None:
    phis = np.asarray([0.0, 90.0, 180.0, 270.0])
    thetas = np.arange(0.0, 181.0, 1.0)
    pattern = Pattern(
        frequency_hz=500e6,
        phis_deg=phis,
        thetas_deg=thetas,
        total_directivity_dbi=np.zeros((len(phis), len(thetas))),
        co_directivity_dbi=np.zeros((len(phis), len(thetas))),
        cross_directivity_dbi=np.full((len(phis), len(thetas)), -40.0),
        polarization="H",
        polarization_basis="test",
    )

    summary, etsi_rows, fcc_rows = analyze_pattern(Path("demo_H.ffs"), "H", pattern)
    rows = _build_per_frequency_results([summary], etsi_rows, fcc_rows)

    assert {row["family"] for row in rows} == {"ETSI RPE", "ETSI XPD", "FCC Part 101"}
    assert all(row["status"] == "NOT APPLICABLE" for row in rows)
    assert all(row["frequency_ghz"] == 0.5 for row in rows)


def test_fcc_failure_note_only_mentions_available_qualification_routes() -> None:
    phis = np.asarray([0.0, 90.0, 180.0, 270.0])
    thetas = np.arange(0.0, 181.0, 1.0)
    pattern = Pattern(
        frequency_hz=2e9,
        phis_deg=phis,
        thetas_deg=thetas,
        total_directivity_dbi=np.zeros((len(phis), len(thetas))),
        co_directivity_dbi=np.zeros((len(phis), len(thetas))),
        cross_directivity_dbi=np.full((len(phis), len(thetas)), -20.0),
        polarization="H",
        polarization_basis="test",
    )

    _, _, fcc_rows = analyze_pattern(Path("demo_H.ffs"), "H", pattern)

    assert fcc_rows
    assert all("beamwidth" in str(row["failure_note"]) for row in fcc_rows)
    assert all("neither beamwidth nor directivity" not in str(row["failure_note"]) for row in fcc_rows)
    assert all(row["gain_pass"] is None for row in fcc_rows)
    assert all(row["xpd_pass"] is None for row in fcc_rows)


def test_compliance_workbook_contains_traceable_sheets(tmp_path: Path) -> None:
    output = tmp_path / "compliance.xlsx"
    results = {
        "rollup": [{"source_file": "demo.ffs", "family": "FCC Part 101", "classification": "Standard A", "status": "PASS"}],
        "per_frequency": [
            {
                "source_file": "demo.ffs",
                "frequency_ghz": 6.0,
                "family": "ETSI RPE",
                "classification": "Class 3",
                "status": "FAIL",
                "note": "ETSI Class 3 fails because the pattern exceeds the limit.",
            }
        ],
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
    assert workbook.sheetnames == [
        "Antenna Rollup",
        "Per-Frequency Results",
        "Summary",
        "ETSI RPE Details",
        "FCC Details",
        "Methodology",
    ]
    methodology = dict(workbook["Methodology"].iter_rows(values_only=True))
    assert "Directivity is used" in methodology["Gain convention"]
    assert methodology["Frequency window"] == "5.9 to 6.1 GHz"
    headers = [cell.value for cell in workbook["ETSI RPE Details"][1]]
    note_column = headers.index("Note") + 1
    assert "ETSI Class 3 fails because" in workbook["ETSI RPE Details"].cell(2, note_column).value
