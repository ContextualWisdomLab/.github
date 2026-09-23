"""The install may only install what the verdict judged (#2342).

Independent review of `03ba1777` showed that a report carrying nothing but
``{"stage": "license", "result": "PASS"}`` authorized the gated install, which
then re-read the *original* lock. Two consequences: a forged or stale two-field
report was sufficient, and a lock recording several hashes for one project let
``--require-hashes`` accept an artifact whose licence and contents were never
judged — the judged digest and the installed digest were never compared.

`bind-install` closes both. It requires the lock to still digest to what the
verdict read, every judged artifact to be present in the collected root by
digest, and the root to hold nothing else; then it pins each project to the one
judged digest. These tests drive the real shell path with a pip recorder, so the
negative cases prove zero installs rather than a rejected argument list.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts.ci import release_dependency_gate as gate
from tests.test_release_dependency_gate import REVIEWED_TEXTS

REPO_ROOT = Path(__file__).resolve().parents[1]
CAPTURE_SCRIPT = REPO_ROOT / "scripts" / "ci" / "release_dependency_capture_raw.sh"
_METADATA = "Metadata-Version: 2.4\nName: green-lib\nVersion: 1.0.0\nLicense-Expression: MIT\n\n"


def _wheel(directory: Path, name: str = "green_lib-1.0.0-py3-none-any.whl", body: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("green_lib-1.0.0.dist-info/METADATA", _METADATA)
        archive.writestr("green_lib/__init__.py", body)
        archive.writestr("LICENSE", REVIEWED_TEXTS["pytest-9.1.1.txt"])
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report(
    path: Path,
    *,
    lock_digest: str,
    rows: list[dict[str, object]],
    result: str = "PASS",
) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema": "cwl.release-dependency-gate/1",
                "stage": "license",
                "result": result,
                "python_lock_sha256": lock_digest,
                "dependencies": rows,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _row(digest: str, *, name: str = "green-lib", version: str = "1.0.0") -> dict[str, object]:
    return {
        "key": f"pypi/{name}@{version}",
        "ecosystem": "pypi",
        "name": name,
        "version": version,
        "source_sha256": digest,
        "license": "MIT",
        "license_member_sha256": {"LICENSE": hashlib.sha256(
            REVIEWED_TEXTS["pytest-9.1.1.txt"].encode()).hexdigest()},
    }


@pytest.fixture()
def bench(tmp_path: Path) -> dict[str, Path]:
    """One collected artifact, its lock, and a capture root holding that lock."""
    collected = tmp_path / "collected"
    wheel = _wheel(collected)
    capture_python = tmp_path / "capture" / "python"
    capture_python.mkdir(parents=True)
    lock = capture_python / "lock.txt"
    # A two-hash lock: the judged artifact plus a second acceptable digest. This is
    # the shape that made the old install unsafe.
    lock.write_text(
        f"green-lib==1.0.0 \\\n    --hash=sha256:{_digest(wheel)} \\\n"
        f"    --hash=sha256:{'b' * 64}\n",
        encoding="utf-8",
    )
    return {
        "collected": collected,
        "wheel": wheel,
        "capture": tmp_path / "capture",
        "lock": lock,
        "root": tmp_path,
    }


def _recorder(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "pip-calls.log"
    script = tmp_path / "fake-pip"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"open({str(log)!r}, 'a', encoding='utf-8').write('\\t'.join(sys.argv[1:]) + '\\n')\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script, log


def _install(bench: dict[str, Path], report: Path) -> tuple[subprocess.CompletedProcess[str], Path]:
    pip, log = _recorder(bench["root"])
    result = subprocess.run(
        [
            "bash",
            str(CAPTURE_SCRIPT),
            "--install-gated",
            "--python-lock",
            str(bench["lock"]),
            "--capture-root",
            str(bench["capture"]),
            "--download-root",
            str(bench["collected"]),
            "--license-report",
            str(report),
        ],
        capture_output=True,
        text=True,
        env=dict(os.environ, RELEASE_GATE_PIP=str(pip)),
        check=False,
    )
    return result, log


def _installs(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [
        line.split("\t")
        for line in log.read_text(encoding="utf-8").splitlines()
        if line and "install" in line.split("\t")
    ]


def test_a_two_field_report_no_longer_authorizes_an_install(bench: dict[str, Path]) -> None:
    """The exact counterexample: stage and result alone must not be enough."""
    report = bench["root"] / "r.json"
    report.write_text(json.dumps({"stage": "license", "result": "PASS"}) + "\n", encoding="utf-8")
    result, log = _install(bench, report)
    assert result.returncode == 2
    assert _installs(log) == []


@pytest.mark.parametrize("forge_hashes", [False, True])
def test_actual_restrictive_archive_cannot_be_authorized_by_sidecar(bench, forge_hashes):
    text = "Academic research only. Commercial use prohibited."
    with zipfile.ZipFile(bench["wheel"], "w") as archive:
        archive.writestr("LICENSE", text)
    digest = _digest(bench["wheel"])
    bench["lock"].write_text(f"green-lib==1.0.0 --hash=sha256:{digest}\n")
    row = _row(digest)
    if forge_hashes:
        row["license_member_sha256"] = {"LICENSE": hashlib.sha256(text.encode()).hexdigest()}
    report = _report(bench["root"] / "r.json", lock_digest=_digest(bench["lock"]), rows=[row])
    result, log = _install(bench, report)
    assert result.returncode == 2
    assert (gate.LICENSE_TEXT_UNVERIFIED if forge_hashes else gate.SOURCE_HASH_MISMATCH) in result.stderr
    assert _installs(log) == []


def test_an_install_bound_to_the_judged_artifact_pins_that_one_digest(
    bench: dict[str, Path],
) -> None:
    """The positive case: the install reads the bound file, not the two-hash lock."""
    judged = _digest(bench["wheel"])
    report = _report(
        bench["root"] / "r.json",
        lock_digest=_digest(bench["lock"]),
        rows=[_row(judged)],
    )
    result, log = _install(bench, report)
    assert result.returncode == 0, result.stderr
    installs = _installs(log)
    assert len(installs) == 1
    argv = installs[0]
    bound = bench["collected"] / "gated-requirements.txt"
    assert argv[argv.index("-r") + 1] == str(bound)
    assert bound.read_text(encoding="utf-8") == f"green-lib==1.0.0 --hash=sha256:{judged}\n"
    # The second acceptable hash from the lock is deliberately absent.
    assert "b" * 64 not in bound.read_text(encoding="utf-8")


def test_a_lock_changed_since_the_verdict_installs_nothing(bench: dict[str, Path]) -> None:
    """A lock edited after the licence stage is not the lock that was judged."""
    report = _report(
        bench["root"] / "r.json",
        lock_digest=_digest(bench["lock"]),
        rows=[_row(_digest(bench["wheel"]))],
    )
    bench["lock"].write_text(
        f"green-lib==1.0.0 --hash=sha256:{'c' * 64}\n", encoding="utf-8"
    )
    result, log = _install(bench, report)
    assert result.returncode == 2
    assert _installs(log) == []


def test_a_swapped_artifact_installs_nothing(bench: dict[str, Path]) -> None:
    """Replacing the collected bytes after the verdict breaks the digest binding."""
    report = _report(
        bench["root"] / "r.json",
        lock_digest=_digest(bench["lock"]),
        rows=[_row(_digest(bench["wheel"]))],
    )
    _wheel(bench["collected"], body="# different bytes\n")
    result, log = _install(bench, report)
    assert result.returncode == 2
    assert _installs(log) == []


def test_an_extra_unjudged_distribution_installs_nothing(bench: dict[str, Path]) -> None:
    """An additional wheel nobody judged must refuse the whole install."""
    report = _report(
        bench["root"] / "r.json",
        lock_digest=_digest(bench["lock"]),
        rows=[_row(_digest(bench["wheel"]))],
    )
    _wheel(bench["collected"], name="extra_lib-2.0.0-py3-none-any.whl", body="x")
    result, log = _install(bench, report)
    assert result.returncode == 2
    assert _installs(log) == []


def test_a_failing_report_installs_nothing(bench: dict[str, Path]) -> None:
    """A copyleft or unknown licence refusal must still stop the install."""
    report = _report(
        bench["root"] / "r.json",
        lock_digest=_digest(bench["lock"]),
        rows=[_row(_digest(bench["wheel"]))],
        result="FAIL",
    )
    result, log = _install(bench, report)
    assert result.returncode == 2
    assert _installs(log) == []


def test_a_report_without_a_lock_digest_is_refused(bench: dict[str, Path]) -> None:
    """An older report shape carries no binding and cannot authorize an install."""
    with pytest.raises(gate.GateError) as error:
        gate.bind_install_requirements(
            _report(bench["root"] / "r.json", lock_digest="", rows=[_row("a" * 64)]),
            bench["capture"],
            bench["collected"],
            bench["root"] / "out.txt",
        )
    assert error.value.code == gate.LICENSE_MISSING


@pytest.mark.parametrize(
    ("rows", "code"),
    [
        ([], gate.LICENSE_MISSING),
        ([{"key": "pypi/x@1", "ecosystem": "pypi", "name": "x", "version": "1"}], "SOURCE_HASH_MISMATCH"),
    ],
    ids=["no-python-rows", "row-without-digest"],
)
def test_an_unusable_judged_set_is_refused(
    bench: dict[str, Path], rows: list[dict[str, object]], code: str
) -> None:
    """A verdict that names no usable Python artifact cannot bind an install."""
    with pytest.raises(gate.GateError) as error:
        gate.bind_install_requirements(
            _report(bench["root"] / "r.json", lock_digest=_digest(bench["lock"]), rows=rows),
            bench["capture"],
            bench["collected"],
            bench["root"] / "out.txt",
        )
    assert error.value.code == code


def test_malformed_report_rows_are_refused(bench: dict[str, Path]) -> None:
    """A report whose dependency list is not a list cannot be read as empty."""
    report = bench["root"] / "r.json"
    report.write_text(
        json.dumps(
            {
                "stage": "license",
                "result": "PASS",
                "python_lock_sha256": _digest(bench["lock"]),
                "dependencies": "not-a-list",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(gate.GateError) as error:
        gate.bind_install_requirements(
            report, bench["capture"], bench["collected"], bench["root"] / "out.txt"
        )
    assert error.value.code == gate.LICENSE_MISSING


def test_a_symlinked_collected_entry_is_not_accepted_as_an_artifact(
    bench: dict[str, Path],
) -> None:
    """A symlink in the collected root is skipped, so it cannot stand in for bytes."""
    (bench["collected"] / "link.whl").symlink_to(bench["wheel"])
    report = _report(
        bench["root"] / "r.json",
        lock_digest=_digest(bench["lock"]),
        rows=[_row(_digest(bench["wheel"]))],
    )
    lines = gate.bind_install_requirements(
        report, bench["capture"], bench["collected"], bench["root"] / "out.txt"
    )
    assert lines == [f"green-lib==1.0.0 --hash=sha256:{_digest(bench['wheel'])}"]


def test_the_gate_records_the_lock_digest_it_judged(tmp_path: Path) -> None:
    """Without this field there is nothing for the install to bind against."""
    from tests.test_release_dependency_gate import build_capture

    capture = build_capture(tmp_path)
    report = gate.gate(capture, stage=gate.LICENSE_STAGE).to_json()
    expected = hashlib.sha256((capture / "python" / "lock.txt").read_bytes()).hexdigest()
    assert report["python_lock_sha256"] == expected


def _bind(bench: dict[str, Path], report: Path) -> list[str]:
    return gate.bind_install_requirements(
        report, bench["capture"], bench["collected"], bench["root"] / "out.txt"
    )


def test_a_lock_changed_since_the_verdict_is_refused_in_process(
    bench: dict[str, Path],
) -> None:
    """The shell case above proves zero installs; this names the reason code."""
    report = _report(
        bench["root"] / "r.json",
        lock_digest=_digest(bench["lock"]),
        rows=[_row(_digest(bench["wheel"]))],
    )
    bench["lock"].write_text("green-lib==1.0.0\n", encoding="utf-8")
    with pytest.raises(gate.GateError) as error:
        _bind(bench, report)
    assert error.value.code == gate.SOURCE_HASH_MISMATCH


def test_a_missing_judged_artifact_is_refused(bench: dict[str, Path]) -> None:
    """A verdict naming bytes the collected root does not hold cannot install."""
    report = _report(
        bench["root"] / "r.json",
        lock_digest=_digest(bench["lock"]),
        rows=[_row("d" * 64)],
    )
    with pytest.raises(gate.GateError) as error:
        _bind(bench, report)
    assert error.value.code == gate.SOURCE_HASH_MISMATCH
    assert "missing judged artifacts" in error.value.detail


def test_an_unjudged_distribution_in_the_root_is_refused(bench: dict[str, Path]) -> None:
    """An extra wheel nobody judged refuses the install by name."""
    _wheel(bench["collected"], name="extra_lib-2.0.0-py3-none-any.whl", body="x")
    report = _report(
        bench["root"] / "r.json",
        lock_digest=_digest(bench["lock"]),
        rows=[_row(_digest(bench["wheel"]))],
    )
    with pytest.raises(gate.GateError) as error:
        _bind(bench, report)
    assert error.value.code == gate.SOURCE_HASH_MISMATCH
    assert "extra_lib-2.0.0-py3-none-any.whl" in error.value.detail


def test_non_python_rows_and_non_distribution_files_are_ignored(
    bench: dict[str, Path],
) -> None:
    """Cargo rows and the collector's own side files are not install candidates.

    The collected root also holds the reconstructed pin list and the validated
    option list, so anything that is not a distribution must be skipped rather
    than counted as an unjudged artifact.
    """
    (bench["collected"] / "pins-without-hashes.txt").write_text("x\n", encoding="utf-8")
    report = _report(
        bench["root"] / "r.json",
        lock_digest=_digest(bench["lock"]),
        rows=[
            {"key": "cargo/greencrate@0.1.0", "ecosystem": "cargo", "source_sha256": "e" * 64},
            "not-a-mapping",
            _row(_digest(bench["wheel"])),
        ],
    )
    assert _bind(bench, report) == [
        f"green-lib==1.0.0 --hash=sha256:{_digest(bench['wheel'])}"
    ]


def test_the_cli_prints_the_bound_requirements(bench: dict[str, Path], capsys) -> None:
    """The shell reads this subcommand's exit status, so it must succeed cleanly."""
    report = _report(
        bench["root"] / "r.json",
        lock_digest=_digest(bench["lock"]),
        rows=[_row(_digest(bench["wheel"]))],
    )
    code = gate.main(
        [
            "bind-install",
            "--report",
            str(report),
            "--capture",
            str(bench["capture"]),
            "--download-root",
            str(bench["collected"]),
            "--output",
            str(bench["root"] / "bound.txt"),
        ]
    )
    assert code == 0
    assert f"--hash=sha256:{_digest(bench['wheel'])}" in capsys.readouterr().out


def test_a_cargo_only_release_records_no_lock_digest(tmp_path: Path) -> None:
    """A release with no Python lock has no digest to bind, and must not invent one."""
    import shutil

    from tests.test_release_dependency_gate import build_capture

    capture = build_capture(tmp_path)
    shutil.rmtree(capture / "python")
    for entry in sorted(capture.rglob("pypi*")):
        if entry.exists():
            shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    release = json.loads((capture / "release.json").read_text(encoding="utf-8"))
    release["ecosystems"] = ["cargo"]
    (capture / "release.json").write_text(json.dumps(release) + "\n", encoding="utf-8")
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    assert report.failures == []
    assert report.to_json()["python_lock_sha256"] == ""
