from __future__ import annotations

import json
import stat
import sys
import zipfile
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
from openpyxl import Workbook

import beamwidth_xlsx
import plot as plot_module
from beamwidth_xlsx import FFSParseError, build_input_output_map, read_ffs_broadband
from extract_data_xlsx import beam_workbook_is_fresh, filter_rows_by_range
from pipeline.atomic import AtomicPublishError, StageWorkspace
from plot_vswr import TouchstoneParseError, read_touchstone
from project_store import ProjectStore
from studio_support import Proc
from workbook_metadata import build_workbook_manifest, write_workbook_manifest
from datasheet.artifacts import load_artifact_manifest, rebase_artifact_paths


def test_frequency_filter_returns_empty_when_window_has_no_overlap() -> None:
    rows = [{"freq_GHz": 5.0}, {"freq_GHz": 6.0}]

    selected, used_min, used_max = filter_rows_by_range(rows, 10.0, 11.0)

    assert selected == []
    assert used_min is None
    assert used_max is None


def test_frequency_filter_keeps_inclusive_boundaries() -> None:
    rows = [{"freq_GHz": 5.0}, {"freq_GHz": 6.0}, {"freq_GHz": 7.0}]

    selected, used_min, used_max = filter_rows_by_range(rows, 5.0, 7.0)

    assert selected == rows
    assert used_min == 5.0
    assert used_max == 7.0


def test_plot_frequency_window_never_falls_back_to_all_samples() -> None:
    frequencies = np.asarray([5.0, 6.0, 7.0])
    series = [np.asarray([1.0, 2.0, 3.0])]

    selected, groups, cropped = plot_module.apply_freq_window(frequencies, [series], 10.0, 11.0)

    assert selected.size == 0
    assert groups[0][0].size == 0
    assert cropped


def test_plot_no_overlap_preserves_existing_outputs(tmp_path: Path) -> None:
    output_dir = tmp_path / "plots"
    output_dir.mkdir()
    existing = output_dir / "input-gain.svg"
    existing.write_bytes(b"known-good")
    summary = plot_module.pd.DataFrame(
        {
            "freq_GHz": [5.0, 6.0],
            "phi_cut_deg": [0, 0],
            "max_gain_dBi": [10.0, 11.0],
        }
    )

    class FakeExcel:
        sheet_names = ["summary"]

        def parse(self, _sheet_name: str):
            return summary.copy()

    argv = ["plot.py", str(tmp_path / "input.xlsx"), "--out-dir", str(output_dir), "--fmin", "10", "--fmax", "11"]
    with (
        mock.patch.object(sys, "argv", argv),
        mock.patch.object(plot_module.pd, "ExcelFile", return_value=FakeExcel()),
        pytest.raises(SystemExit, match="existing plots were preserved"),
    ):
        plot_module.main()

    assert existing.read_bytes() == b"known-good"


def test_touchstone_v1_supports_inline_comments_and_continuations(tmp_path: Path) -> None:
    source = tmp_path / "sample.s1p"
    source.write_text(
        "# GHZ S RI R 50\n"
        "2.0 0.2 0.0 ! second sample\n"
        "1.0\n"
        "0.1 0.0 ! continued first sample\n",
        encoding="utf-8",
    )

    frequencies, data, fmt, z0, ports = read_touchstone(str(source))

    assert frequencies.tolist() == [1.0e9, 2.0e9]
    assert data.tolist() == [[0.1, 0.0], [0.2, 0.0]]
    assert (fmt, z0, ports) == ("RI", 50.0, 1)


@pytest.mark.parametrize(
    "content,message",
    [
        ("[Version] 2.0\n", "2.0"),
        ("# GHZ Z RI R 50\n1 0 0\n", "S-parameter"),
        ("# GHZ S RI R 50\n1 0\n", "Incomplete"),
        ("# GHZ S RI R 50\n1 0 0\n1 0.1 0\n", "duplicate"),
    ],
)
def test_touchstone_rejects_unsupported_or_malformed_data(tmp_path: Path, content: str, message: str) -> None:
    source = tmp_path / "bad.s1p"
    source.write_text(content, encoding="utf-8")

    with pytest.raises(TouchstoneParseError, match=message):
        read_touchstone(str(source))


def test_invalid_ffs_raises_and_does_not_replace_existing_workbook(tmp_path: Path) -> None:
    source = tmp_path / "invalid.ffs"
    output = tmp_path / "result.xlsx"
    linkcalc_output = tmp_path / "linkCalc" / "known-good.ffs"
    source.write_text("not a CST far-field file", encoding="utf-8")
    output.write_bytes(b"known-good")
    linkcalc_output.parent.mkdir()
    linkcalc_output.write_bytes(b"known-good-linkcalc")

    with mock.patch.object(sys, "argv", ["beamwidth_xlsx.py", str(output), str(source)]):
        with pytest.raises(SystemExit, match="no outputs were published"):
            beamwidth_xlsx.main()

    assert output.read_bytes() == b"known-good"
    assert not (tmp_path / "ant_files").exists()
    assert linkcalc_output.read_bytes() == b"known-good-linkcalc"


def test_ffs_reader_rejects_empty_and_incomplete_grids(tmp_path: Path) -> None:
    source = tmp_path / "bad.ffs"
    source.write_text("Frequency 5 GHz\n0 0 1 0 0 0\n", encoding="utf-8")

    with pytest.raises(FFSParseError, match="at least two phi and theta"):
        read_ffs_broadband(source)


def test_collision_mapping_preserves_normal_names_and_disambiguates_conflicts(tmp_path: Path) -> None:
    first = tmp_path / "a" / "same.ffs"
    second = tmp_path / "b" / "same.ffs"
    long_path = tmp_path / ("x" * 40 + ".ffs")

    mappings = build_input_output_map([first, second, long_path])

    assert mappings[0]["data"] != mappings[1]["data"]
    assert mappings[0]["ant_stem"] != mappings[1]["ant_stem"]
    assert mappings[2]["phi0"].endswith("_phi0")
    assert mappings[2]["phi90"].endswith("_phi90")
    assert all(len(mapping[key]) <= 31 for mapping in mappings for key in ("data", "phi0", "phi90"))


def test_linkcalc_gain_rows_keep_source_order_and_absolute_dbi() -> None:
    source_rows = [
        (180.0, 90.0, 1 + 0j, 0j),
        (0.0, 0.0, 2 + 0j, 0j),
        (180.0, 0.0, 3 + 0j, 0j),
        (0.0, 90.0, 4 + 0j, 0j),
    ]

    with mock.patch.object(beamwidth_xlsx, "read_ffs_broadband", return_value={5e9: source_rows}):
        result = beamwidth_xlsx.compute_for_file(Path("sample_H.ffs"), smooth=1, theta_window=8.0)

    rows = result[5][5e9]
    assert [(phi, theta) for phi, theta, _gain in rows] == [
        (180.0, 90.0),
        (0.0, 0.0),
        (180.0, 0.0),
        (0.0, 90.0),
    ]
    assert [gain for _phi, _theta, gain in rows] == pytest.approx(
        [-6.995700704721642, -0.9751007914420182, 2.546724389671606, 5.045499121837605]
    )


def test_linkcalc_writer_formats_two_polarizations_and_close_frequencies(tmp_path: Path) -> None:
    rows_by_frequency = {
        5_000_000_000.0: [(180.1234567890123, 90.0, 1.2345678912), (0.0, 0.0, -2.0)],
        5_000_000_001.0: [(45.0, 30.0, 3.0)],
    }

    horizontal = beamwidth_xlsx.write_linkcalc_files(tmp_path, "sample_H", rows_by_frequency)
    vertical = beamwidth_xlsx.write_linkcalc_files(tmp_path, "sample_V", rows_by_frequency)

    assert {path.name for path in horizontal + vertical} == {
        "sample_H-5GHz.ffs",
        "sample_H-5.000000001GHz.ffs",
        "sample_V-5GHz.ffs",
        "sample_V-5.000000001GHz.ffs",
    }
    assert (tmp_path / "sample_H-5GHz.ffs").read_text(encoding="utf-8") == (
        "180.123456789 90 1.234567891\n"
        "0 0 -2.000000000\n"
    )
    assert (tmp_path / "sample_H-5.000000001GHz.ffs").read_text(encoding="utf-8") == (
        "45 30 3.000000000\n"
    )


@pytest.mark.filterwarnings("ignore:Mean of empty slice:RuntimeWarning")
def test_successful_beam_publish_replaces_obsolete_linkcalc_files(tmp_path: Path) -> None:
    source = tmp_path / "sample_H.ffs"
    output = tmp_path / "result.xlsx"
    source.write_text("source", encoding="utf-8")
    stale = tmp_path / "linkCalc" / "stale.ffs"
    stale.parent.mkdir()
    stale.write_text("obsolete", encoding="utf-8")
    source_rows = [
        (0.0, 0.0, 1 + 0j, 0j),
        (0.0, 90.0, 1 + 0j, 0j),
        (180.0, 0.0, 1 + 0j, 0j),
        (180.0, 90.0, 1 + 0j, 0j),
    ]
    with mock.patch.object(beamwidth_xlsx, "read_ffs_broadband", return_value={5e9: source_rows}):
        computed = beamwidth_xlsx.compute_for_file(source, smooth=1, theta_window=8.0)

    with (
        mock.patch.object(sys, "argv", ["beamwidth_xlsx.py", str(output), str(source)]),
        mock.patch.object(beamwidth_xlsx, "compute_for_file", return_value=computed),
    ):
        assert beamwidth_xlsx.main() == 0

    assert not stale.exists()
    assert (tmp_path / "linkCalc" / "sample_H-5GHz.ffs").exists()


def test_beam_workbook_reuse_requires_matching_manifest(tmp_path: Path) -> None:
    source = tmp_path / "sample.ffs"
    source.write_text("source", encoding="utf-8")
    workbook_path = tmp_path / "beam.xlsx"
    mappings = build_input_output_map([source])
    workbook = Workbook()
    write_workbook_manifest(
        workbook,
        build_workbook_manifest([source], smooth=5, theta_window=8.0, sheet_maps=mappings),
    )
    workbook.save(workbook_path)

    assert beam_workbook_is_fresh(workbook_path, [source], smooth=5, theta_window=8.0)
    assert not beam_workbook_is_fresh(workbook_path, [source], smooth=7, theta_window=8.0)
    assert not beam_workbook_is_fresh(workbook_path, [source], smooth=5, theta_window=9.0)


def test_atomic_publish_rolls_back_group_on_failure(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("old-a", encoding="utf-8")
    (tmp_path / "b.txt").write_text("old-b", encoding="utf-8")
    stage = StageWorkspace(tmp_path, "probe")
    stage.path("a.txt").write_text("new-a", encoding="utf-8")
    stage.path("b.txt").write_text("new-b", encoding="utf-8")
    path_type = type(stage.root)
    original_replace = path_type.replace

    def failing_replace(self: Path, target: Path):
        if self == stage.root / "b.txt":
            raise PermissionError("simulated lock")
        return original_replace(self, target)

    with mock.patch.object(path_type, "replace", new=failing_replace):
        with pytest.raises(AtomicPublishError, match="simulated lock"):
            stage.publish(["a.txt", "b.txt"])

    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "old-a"
    assert (tmp_path / "b.txt").read_text(encoding="utf-8") == "old-b"


def test_atomic_publish_validates_nested_outputs_before_replacement(tmp_path: Path) -> None:
    existing = tmp_path / "output.txt"
    existing.write_bytes(b"known-good")
    stage = StageWorkspace(tmp_path, "probe")
    stage.path("output.txt").write_bytes(b"replacement")

    with pytest.raises(AtomicPublishError, match="missing.svg"):
        stage.publish(["output.txt"], validate=["nested/missing.svg"])

    assert existing.read_bytes() == b"known-good"


def test_artifact_paths_are_rebased_structurally_and_legacy_staging_paths_are_repaired(tmp_path: Path) -> None:
    stage_root = tmp_path / ".plot-staging-test"
    final_svg = tmp_path / "polar" / "gain.svg"
    final_svg.parent.mkdir()
    final_svg.write_text("<svg/>", encoding="utf-8")
    staged_svg = stage_root / "polar" / "gain.svg"
    charts = {"gain": {"svg": str(staged_svg)}}

    rebased = rebase_artifact_paths(charts, stage_root, tmp_path)
    assert rebased["gain"]["svg"] == str(final_svg)

    manifest_path = tmp_path / "sample-artifacts.json"
    manifest_path.write_text(
        json.dumps({"schema_version": 2, "bookstem": "sample", "charts": charts}),
        encoding="utf-8",
    )
    loaded = load_artifact_manifest(manifest_path, bookstem="sample")
    assert loaded["charts"]["gain"]["svg"] == str(final_svg.resolve())


def test_process_failure_clears_queue_and_reports_blocked_commands() -> None:
    proc = Proc.__new__(Proc)
    proc.win = mock.Mock()
    proc.running_cmd = ["python", "beamwidth_xlsx.py"]
    proc.queue = [["python", "extract_data_xlsx.py"], ["python", "plot.py"]]
    proc._progress_buffers = {"stdout": "", "stderr": ""}
    proc._dequeue_and_start = mock.Mock()

    proc._on_finished(1, None)

    assert proc.queue == []
    assert proc.running_cmd is None
    proc._dequeue_and_start.assert_not_called()
    proc.win.on_proc_batch_aborted.assert_called_once()
    skipped = proc.win.on_proc_batch_aborted.call_args.args[2]
    assert skipped == [["python", "extract_data_xlsx.py"], ["python", "plot.py"]]


def test_bundle_import_rejects_mixed_roots_and_symlinks(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    mixed = tmp_path / "mixed.zip"
    with zipfile.ZipFile(mixed, "w") as archive:
        archive.writestr("one/project.json", json.dumps({"name": "One", "slug": "one"}))
        archive.writestr("two/file.txt", "data")
    with pytest.raises(ValueError, match="one consistent"):
        store.import_project_bundle(mixed)

    linked = tmp_path / "linked.zip"
    link_info = zipfile.ZipInfo("one/link")
    link_info.create_system = 3
    link_info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(linked, "w") as archive:
        archive.writestr("one/project.json", json.dumps({"name": "One", "slug": "one"}))
        archive.writestr(link_info, "target")
    with pytest.raises(ValueError, match="non-regular"):
        store.import_project_bundle(linked)


def test_bundle_import_rejects_unsafe_compression_ratio(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    bundle = tmp_path / "ratio.zip"
    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("one/project.json", json.dumps({"name": "One", "slug": "one"}))
        archive.writestr("one/zeros.bin", b"0" * (1024 * 1024))

    with pytest.raises(ValueError, match="compression ratio"):
        store.import_project_bundle(bundle)
