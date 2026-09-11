"""Deterministic tests for Strix finding location integrity."""

from pathlib import Path

from scripts.ci.validate_strix_location_ranges import location_state


def _records(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "locations.tsv"
    path.write_text(content, encoding="utf-8")
    return path


def test_all_out_of_range_locations_are_model_inconsistency(tmp_path: Path) -> None:
    source = tmp_path / "scan" / "module.py"
    source.parent.mkdir()
    source.write_text("one\ntwo\n", encoding="utf-8")

    assert location_state(
        tmp_path,
        None,
        _records(tmp_path, "scan/module.py\t9\t10\n"),
    ) == 0


def test_mixed_locations_remain_blocking(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("one\ntwo\n", encoding="utf-8")

    assert location_state(
        tmp_path,
        None,
        _records(tmp_path, "module.py\t1\t1\nmodule.py\t9\t10\n"),
    ) == 1


def test_all_valid_locations_use_existing_finding_path(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("one\ntwo\n", encoding="utf-8")

    assert location_state(
        tmp_path,
        None,
        _records(tmp_path, "module.py\t1\t2\n"),
    ) == 2
