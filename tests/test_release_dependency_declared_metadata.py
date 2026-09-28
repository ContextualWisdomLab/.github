"""Licence facts must come from the artifact, not from an installed environment (#2342).

The gate judges a licence *before* the release closure is installed, so it can no
longer read ``pip inspect`` of a lock-only environment: at that point no such
environment exists. It reads each fetched distribution's own ``METADATA`` (wheel)
or ``PKG-INFO`` (sdist) instead, and re-checks that the archive declares the
pinned project and version — a file whose metadata names something else must fail
rather than be adjudicated under the wrong identity.

``install_is_authorized`` is the other half: the install step may run only when a
prescreen report records a passed licence stage, so a missing, malformed or
failing report refuses the install instead of defaulting to permitted.
"""

from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts.ci import release_dependency_gate as gate

_METADATA = (
    "Metadata-Version: 2.4\n"
    "Name: Green.Lib\n"
    "Version: 1.0.0\n"
    "License-Expression: MIT\n"
    "License: MIT\n"
    "Classifier: License :: OSI Approved :: MIT License\n"
    "Classifier: Programming Language :: Python :: 3\n"
    "\n"
    "Body text is not metadata.\n"
)


def _wheel(directory: Path, metadata: str = _METADATA, *, member: str | None = None) -> Path:
    path = directory / "green_lib-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member or "green_lib-1.0.0.dist-info/METADATA", metadata)
        archive.writestr("green_lib/__init__.py", "")
    return path


def _sdist(directory: Path, metadata: str = _METADATA) -> Path:
    path = directory / "green_lib-1.0.0.tar.gz"
    raw = metadata.encode("utf-8")
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("green_lib-1.0.0/PKG-INFO")
        info.size = len(raw)
        archive.addfile(info, io.BytesIO(raw))
    return path


def test_wheel_metadata_is_read_from_the_distribution(tmp_path: Path) -> None:
    declared = gate.distribution_declared_metadata(_wheel(tmp_path), "green-lib", "1.0.0")
    assert declared == {
        "ecosystem": "pypi",
        "name": "green-lib",
        "version": "1.0.0",
        "license_expression": "MIT",
        "license": "MIT",
        "classifiers": ["License :: OSI Approved :: MIT License"],
        "distribution_inclusion": ["sdist", "wheel"],
        "known_vulnerabilities": [],
    }


def test_sdist_metadata_is_read_from_pkg_info(tmp_path: Path) -> None:
    declared = gate.distribution_declared_metadata(_sdist(tmp_path), "green-lib", "1.0.0")
    assert declared["license_expression"] == "MIT"
    assert declared["version"] == "1.0.0"


def test_absent_licence_fields_are_empty_rather_than_defaulted(tmp_path: Path) -> None:
    bare = "Metadata-Version: 2.4\nName: green-lib\nVersion: 1.0.0\n\n"
    declared = gate.distribution_declared_metadata(_wheel(tmp_path, bare), "green-lib", "1.0.0")
    assert declared["license_expression"] == ""
    assert declared["license"] == ""
    assert declared["classifiers"] == []


@pytest.mark.parametrize(
    ("name", "version"),
    [("other-lib", "1.0.0"), ("green-lib", "2.0.0")],
)
def test_metadata_that_contradicts_the_pin_is_refused(
    tmp_path: Path, name: str, version: str
) -> None:
    with pytest.raises(gate.GateError) as error:
        gate.distribution_declared_metadata(_wheel(tmp_path), name, version)
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def test_a_wheel_without_exactly_one_metadata_member_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "green_lib-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("green_lib-1.0.0.dist-info/METADATA", _METADATA)
        archive.writestr("green_lib-1.0.1.dist-info/METADATA", _METADATA)
    with pytest.raises(gate.GateError) as error:
        gate.distribution_declared_metadata(path, "green-lib", "1.0.0")
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def test_a_nested_metadata_path_does_not_satisfy_the_member_requirement(tmp_path: Path) -> None:
    path = _wheel(tmp_path, member="vendor/green_lib-1.0.0.dist-info/METADATA")
    with pytest.raises(gate.GateError) as error:
        gate.distribution_declared_metadata(path, "green-lib", "1.0.0")
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def test_non_utf8_metadata_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "green_lib-1.0.0-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("green_lib-1.0.0.dist-info/METADATA", b"Name: \xff\xfe\n")
    with pytest.raises(gate.GateError) as error:
        gate.distribution_declared_metadata(path, "green-lib", "1.0.0")
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def test_oversize_metadata_is_refused_rather_than_read(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(gate, "_MAX_METADATA_BYTES", 8)
    with pytest.raises(gate.GateError) as error:
        gate.distribution_declared_metadata(_wheel(tmp_path), "green-lib", "1.0.0")
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def test_oversize_sdist_metadata_is_refused_rather_than_read(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(gate, "_MAX_METADATA_BYTES", 8)
    with pytest.raises(gate.GateError) as error:
        gate.distribution_declared_metadata(_sdist(tmp_path), "green-lib", "1.0.0")
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def test_an_sdist_without_exactly_one_top_level_pkg_info_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "green_lib-1.0.0.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        archive.addfile(tarfile.TarInfo("green_lib-1.0.0/src/PKG-INFO"), io.BytesIO(b""))
    with pytest.raises(gate.GateError) as error:
        gate.distribution_declared_metadata(path, "green-lib", "1.0.0")
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def test_a_symlinked_distribution_is_refused(tmp_path: Path) -> None:
    real = _wheel(tmp_path)
    link = tmp_path / "link.whl"
    link.symlink_to(real)
    with pytest.raises(gate.GateError) as error:
        gate.distribution_declared_metadata(link, "green-lib", "1.0.0")
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def _report(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return path


def test_a_passed_licence_stage_authorizes_the_install(tmp_path: Path) -> None:
    report = _report(tmp_path / "r.json", {"stage": gate.LICENSE_STAGE, "result": "PASS"})
    gate.install_is_authorized(report)


@pytest.mark.parametrize(
    "payload",
    [
        {"stage": gate.LICENSE_STAGE, "result": "FAIL"},
        {"stage": gate.FULL_STAGE, "result": "PASS"},
        {"stage": gate.LICENSE_STAGE},
        ["not", "an", "object"],
    ],
)
def test_an_unpassed_or_malformed_report_refuses_the_install(
    tmp_path: Path, payload: object
) -> None:
    report = _report(tmp_path / "r.json", payload)
    with pytest.raises(gate.GateError) as error:
        gate.install_is_authorized(report)
    assert error.value.code == gate.LICENSE_MISSING


def test_a_missing_report_refuses_the_install(tmp_path: Path) -> None:
    with pytest.raises(gate.GateError) as error:
        gate.install_is_authorized(tmp_path / "absent.json")
    assert error.value.code == gate.LICENSE_MISSING


def test_the_cli_emits_declared_metadata(tmp_path: Path, capsys) -> None:
    code = gate.main(
        [
            "distribution-metadata",
            "--distribution",
            str(_wheel(tmp_path)),
            "--name",
            "green-lib",
            "--version",
            "1.0.0",
        ]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["license_expression"] == "MIT"


def test_the_cli_authorizes_and_refuses_the_install(tmp_path: Path, capsys) -> None:
    passed = _report(tmp_path / "pass.json", {"stage": gate.LICENSE_STAGE, "result": "PASS"})
    assert gate.main(["install-authorized", "--report", str(passed)]) == 0
    assert "authorized" in capsys.readouterr().out
    failed = _report(tmp_path / "fail.json", {"stage": gate.LICENSE_STAGE, "result": "FAIL"})
    assert gate.main(["install-authorized", "--report", str(failed)]) == 2
    assert gate.LICENSE_MISSING in capsys.readouterr().err


@pytest.mark.parametrize(
    "expression", ["GPL-3.0-or-later", "AGPL-3.0-only", "LGPL-2.1-or-later", "NOASSERTION"]
)
def test_a_denied_or_unknown_expression_is_carried_through_verbatim(
    tmp_path: Path, expression: str
) -> None:
    """The reader never normalizes or softens what the distribution declares.

    Policy is applied later, by ``evaluate_dependency_license``. If this step
    rewrote or dropped a copyleft or unknown expression, the licence stage would
    adjudicate something the artifact never said. This replaces the equivalent
    assertions of the deleted ``pip inspect``-based transform test, whose jq
    program no longer exists: licence facts now come from the artifact, because
    nothing is installed before the licence stage runs.
    """

    metadata = _METADATA.replace("License-Expression: MIT", f"License-Expression: {expression}")
    declared = gate.distribution_declared_metadata(
        _wheel(tmp_path, metadata), "green-lib", "1.0.0"
    )
    assert declared["license_expression"] == expression


def test_a_declared_size_that_understates_the_stream_is_still_refused() -> None:
    """The bound is enforced on the bytes read, not only on the declared size.

    A zip entry's ``file_size`` is attacker-controlled metadata, so the size check
    before the read cannot be the only one: the decode step refuses anything that
    actually exceeds the bound even when the header claimed it would not.
    """

    with pytest.raises(gate.GateError) as error:
        gate._decode_metadata(b"x" * (gate._MAX_METADATA_BYTES + 1), Path("METADATA"))
    assert error.value.code == gate.CAPTURE_INCOMPLETE
