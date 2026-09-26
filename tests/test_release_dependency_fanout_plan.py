"""The Strix matrix may only come from the passing full licence set."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.ci import release_dependency_gate as gate
from tests.test_release_dependency_gate import build_capture


CONTROL = "d" * 40


def _allowed(tmp_path: Path) -> tuple[Path, Path]:
    capture = build_capture(tmp_path)
    for fixture in (capture / "strix/fixtures").glob("*.json"):
        digest = gate.fixture_digest(json.loads(fixture.read_text()))
        fixture.with_suffix(".sha256").write_text(digest + "\n")
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    assert report.passed
    report_path = tmp_path / "license-report.json"
    report_path.write_text(json.dumps(report.to_json()) + "\n")
    return capture, report_path


def test_fanout_plan_matches_every_prescreened_fixture(tmp_path: Path) -> None:
    capture, report_path = _allowed(tmp_path)
    plan = gate.strix_fanout_plan(capture, report_path, CONTROL, 42, 2)
    report = json.loads(report_path.read_text())
    assert plan["source_sha"] == report["source_sha"]
    assert plan["license_report_sha256"] == hashlib.sha256(report_path.read_bytes()).hexdigest()
    assert (plan["control_sha"], plan["run_id"], plan["run_attempt"]) == (CONTROL, 42, 2)
    assert {row["key"] for row in plan["dependencies"]} == {
        row["key"] for row in report["dependencies"]
    }
    assert len({row["artifact_name"] for row in plan["dependencies"]}) == len(plan["dependencies"])
    assert all(row["artifact_name"].startswith("release-strix-binding-a2-") for row in plan["dependencies"])
    assert all(gate.fixture_digest(row["fixture"]) == row["fixture_sha256"] for row in plan["dependencies"])


def test_fanout_adds_distinct_exact_archive_fixtures(tmp_path: Path) -> None:
    capture, report_path = _allowed(tmp_path)
    archives = []
    for sha in ("a" * 64, "b" * 64):
        key = f"pypi/numpy@2.5.1/sha256/{sha}"
        evidence = {"source_sha256": sha, "archive_members": [],
                    "install_hook_sources": {}, "parsed_inputs": [],
                    "native_libraries": [], "known_vulnerabilities": []}
        fixture = gate.build_fixture(gate.Dependency("pypi", "numpy", "2.5.1"), evidence)
        fixture["id"] = key
        archives.append({"key": key, "package_key": "pypi/numpy@2.5.1",
                         "name": "numpy", "version": "2.5.1", "source_sha256": sha,
                         "license": "BSD-3-Clause", "fixture": fixture,
                         "fixture_sha256": gate.fixture_digest(fixture)})
    archive_report = tmp_path / "archive-report.json"
    build = copy.deepcopy(archives[0])
    build["key"] = f"pypi/pip@25.2/sha256/{'c' * 64}"
    build["package_key"] = "pypi/pip@25.2"
    build["name"] = "pip"
    build["version"] = "25.2"
    build["source_sha256"] = "c" * 64
    build["fixture"] = gate.build_fixture(gate.Dependency("pypi", "pip", "25.2"),
                                           {"source_sha256": "c" * 64, "archive_members": [],
                                            "install_hook_sources": {}, "parsed_inputs": [],
                                            "native_libraries": [], "known_vulnerabilities": []})
    build["fixture"]["id"] = build["key"]
    build["fixture_sha256"] = gate.fixture_digest(build["fixture"])
    tool = copy.deepcopy(build)
    tool.update(key=f"github-release/maturin@1.15.0/sha256/{'d' * 64}",
                package_key="github-release/maturin@1.15.0", name="maturin",
                version="1.15.0", source_sha256="d" * 64)
    tool["fixture"] = gate.build_fixture(gate.Dependency("github-release", "maturin", "1.15.0"),
                                          {"source_sha256": "d" * 64, "archive_members": [],
                                           "install_hook_sources": {}, "parsed_inputs": [],
                                           "native_libraries": [], "known_vulnerabilities": []})
    tool["fixture"]["id"] = tool["key"]
    tool["fixture_sha256"] = gate.fixture_digest(tool["fixture"])
    payload = {"schema": "cwl.release-runtime-archive-licenses/3",
               "archives": archives, "build_packages": [build], "build_tools": [tool]}
    archive_report.write_text(json.dumps(payload))
    plan = gate.strix_fanout_plan(capture, report_path, CONTROL, 42, 2, archive_report)
    variants = [row for row in plan["dependencies"] if "runtime_archive" in row]
    assert {row["key"] for row in variants} == {item["key"] for item in archives}
    assert len({row["artifact_name"] for row in variants}) == 2
    assert {row["key"] for row in plan["dependencies"] if "build_package" in row} == {build["key"]}
    assert {row["key"] for row in plan["dependencies"] if "build_tool" in row} == {tool["key"]}
    assert plan["runtime_archive_license_sha256"] == hashlib.sha256(archive_report.read_bytes()).hexdigest()
    archives[0]["fixture"]["id"] = "pypi/other@1"
    archive_report.write_text(json.dumps(payload))
    with pytest.raises(gate.GateError, match="fixture differs"):
        gate.strix_fanout_plan(capture, report_path, CONTROL, 42, 2, archive_report)


def test_plan_refuses_denied_missing_extra_and_duplicate_scope(tmp_path: Path) -> None:
    mutators = {
        "denied": lambda capture, report: report.__setitem__("result", "FAIL"),
        "duplicate": lambda capture, report: report["dependencies"].append(copy.deepcopy(report["dependencies"][0])),
        "limit": lambda capture, report: report.__setitem__("dependencies", report["dependencies"] * 257),
        "missing": lambda capture, report: next((capture / "strix/fixtures").glob("*.json")).unlink(),
        "extra": lambda capture, report: (capture / "strix/fixtures/unlisted.json").write_text("{}"),
        "wrong-source": lambda capture, report: report.__setitem__("source_sha", "e" * 40),
    }
    for name, mutate in mutators.items():
        capture, report_path = _allowed(tmp_path / name)
        report = json.loads(report_path.read_text())
        mutate(capture, report)
        report_path.write_text(json.dumps(report) + "\n")
        with pytest.raises(gate.GateError):
            gate.strix_fanout_plan(capture, report_path, CONTROL, 42, 2)


def test_fanout_cli_emits_one_bounded_matrix_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    capture, report_path = _allowed(tmp_path)
    output = tmp_path / "matrix-output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    plan_path = tmp_path / "plan.json"
    assert gate.main([
        "fanout-plan", "--capture", str(capture), "--license-report", str(report_path),
        "--control-sha", CONTROL, "--run-id", "42", "--run-attempt", "2",
        "--output", str(plan_path),
    ]) == 0
    matrix = json.loads(output.read_text().removeprefix("matrix_json="))
    assert matrix["include"] == json.loads(plan_path.read_text())["dependencies"]
    assert len(matrix["include"]) <= gate.STRIX_MATRIX_LIMIT


def test_fanout_refuses_matrix_output_over_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    capture, report_path = _allowed(tmp_path)
    monkeypatch.setattr(gate, "STRIX_MATRIX_OUTPUT_MAX_BYTES", 1)
    with pytest.raises(gate.GateError, match="bounded job output"):
        gate.strix_fanout_plan(capture, report_path, CONTROL, 42, 2)
