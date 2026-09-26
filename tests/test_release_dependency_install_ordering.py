"""No unadjudicated dependency may be installed (#2342).

The gate's premise is that a denied, unknown or untrusted dependency is refused
*before* anything of it runs. That was false at the workflow level: the release
closure was installed in a step that preceded both the lock-source validation and
the licence prescreen, so a GPL/AGPL or UNKNOWN dependency — and a lock pointing
at an untrusted index — reached the environment first.

These tests pin the wiring, not the parser. ``RELEASE_GATE_PIP`` points at a
recorder, so each case asserts on the pip invocations that actually happened:

* a refused lock directive performs **no** pip call at all — not even a download;
* a refused licence stage performs **no** ``install``;
* a report that merely claims a pass installs nothing, because authorization is
  bound to the judged artifacts and lock in
  ``test_release_dependency_install_binding.py``, which also covers the one
  authorized install.

The workflow step order is asserted too, because the defect lived there and no
other test reads that file's ordering.
"""

from __future__ import annotations

import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CAPTURE = REPO_ROOT / "scripts" / "ci" / "release_dependency_capture_raw.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-dependency-license-strix-gate.yml"

# The capture path uses GNU `find -printf`, which BSD/macOS find does not have.
# The refusal cases stop before that line and run everywhere; the success case
# needs it, so it is skipped rather than silently weakened off GNU coreutils.
_GNU_FIND = (
    subprocess.run(
        ["find", ".", "-maxdepth", "0", "-printf", ""],
        capture_output=True,
        check=False,
    ).returncode
    == 0
)

_SHA = "a" * 64
_METADATA = (
    "Metadata-Version: 2.4\nName: green-lib\nVersion: 1.0.0\nLicense-Expression: MIT\n\n"
)


def _recorder(tmp_path: Path) -> tuple[Path, Path]:
    """Write a fake pip that logs its argv and materializes a wheel on download."""

    log = tmp_path / "pip-calls.log"
    script = tmp_path / "fake-pip"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys, zipfile\n"
        f"log = {str(log)!r}\n"
        "argv = sys.argv[1:]\n"
        "with open(log, 'a', encoding='utf-8') as handle:\n"
        "    handle.write('\\t'.join(argv) + '\\n')\n"
        "if argv and argv[0] == 'download':\n"
        "    dest = argv[argv.index('--dest') + 1]\n"
        "    os.makedirs(dest, exist_ok=True)\n"
        "    path = os.path.join(dest, 'green_lib-1.0.0-py3-none-any.whl')\n"
        "    with zipfile.ZipFile(path, 'w') as archive:\n"
        f"        archive.writestr('green_lib-1.0.0.dist-info/METADATA', {_METADATA!r})\n"
        "        archive.writestr('green_lib/__init__.py', '')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script, log


def _calls(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [line.split("\t") for line in log.read_text(encoding="utf-8").splitlines() if line]


def _run(tmp_path: Path, pip: Path, *args: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ, RELEASE_GATE_PIP=str(pip))
    return subprocess.run(
        ["bash", str(CAPTURE), *args],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=environment,
        check=False,
    )


def _collect(tmp_path: Path, lock_text: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    lock = tmp_path / "lock.txt"
    lock.write_text(lock_text, encoding="utf-8")
    pip, log = _recorder(tmp_path)
    result = _run(
        tmp_path,
        pip,
        "--raw-root",
        str(tmp_path / "raw"),
        "--capture-root",
        str(tmp_path / "capture"),
        "--download-root",
        str(tmp_path / "collected"),
        "--ecosystems",
        "python",
        "--python-lock",
        str(lock),
    )
    return result, log


@pytest.mark.parametrize(
    ("directive", "code"),
    [
        ("--index-url https://packages.example.com/simple\n", "LOCK_SOURCE_ORIGIN_DENIED"),
        ("--no-index\n", "LOCK_SOURCE_UNSUPPORTED"),
        ("-r other-requirements.txt\n", "LOCK_SOURCE_UNSUPPORTED"),
    ],
)
def test_a_refused_lock_directive_fetches_nothing(
    tmp_path: Path, directive: str, code: str
) -> None:
    result, log = _collect(tmp_path, f"{directive}green-lib==1.0.0 --hash=sha256:{_SHA}\n")
    assert result.returncode == 2
    assert code in result.stdout + result.stderr
    assert _calls(log) == []


@pytest.mark.skipif(not _GNU_FIND, reason="capture needs GNU find -printf")
def test_a_collected_release_downloads_without_installing(tmp_path: Path) -> None:
    result, log = _collect(tmp_path, f"green-lib==1.0.0 --hash=sha256:{_SHA}\n")
    assert result.returncode == 0, result.stderr
    commands = [call[0] for call in _calls(log)]
    assert commands == ["download"], commands
    download = _calls(log)[0]
    assert "--only-binary=:all:" in download
    declared = json.loads((tmp_path / "capture" / "python" / "installed.json").read_text())
    assert declared["installed"][0]["metadata"]["license_expression"] == "MIT"


def _install(
    tmp_path: Path, report_payload: object | None
) -> tuple[subprocess.CompletedProcess[str], Path]:
    lock = tmp_path / "lock.txt"
    lock.write_text(f"green-lib==1.0.0 --hash=sha256:{_SHA}\n", encoding="utf-8")
    collected = tmp_path / "collected"
    collected.mkdir(exist_ok=True)
    capture = tmp_path / "capture"
    capture_python = capture / "python"
    capture_python.mkdir(parents=True, exist_ok=True)
    (capture_python / "lock.txt").write_bytes(lock.read_bytes())
    with zipfile.ZipFile(collected / "green_lib-1.0.0-py3-none-any.whl", "w") as archive:
        archive.writestr("green_lib-1.0.0.dist-info/METADATA", _METADATA)
    report = tmp_path / "license-report.json"
    if report_payload is not None:
        report.write_text(json.dumps(report_payload) + "\n", encoding="utf-8")
    pip, log = _recorder(tmp_path)
    result = _run(
        tmp_path,
        pip,
        "--install-gated",
        "--python-lock",
        str(lock),
        "--capture-root",
        str(capture),
        "--download-root",
        str(collected),
        "--license-report",
        str(report),
    )
    return result, log


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"stage": "license", "result": "FAIL"},
        {"stage": "full", "result": "PASS"},
    ],
    ids=["no-report", "copyleft-or-unknown-rejected", "wrong-stage"],
)
def test_an_unauthorized_licence_stage_installs_nothing(
    tmp_path: Path, payload: object | None
) -> None:
    result, log = _install(tmp_path, payload)
    assert result.returncode == 2
    assert [call for call in _calls(log) if "install" in call] == []


def test_a_report_that_only_claims_a_pass_installs_nothing(tmp_path: Path) -> None:
    """A two-field report is no longer sufficient authorization.

    Independent review showed this exact report authorizing an install that then
    re-read the original lock. The install now has to be bound to the judged
    artifacts and lock, which `test_release_dependency_install_binding.py` drives
    end to end, including the one authorized install.
    """
    result, log = _install(tmp_path, {"stage": "license", "result": "PASS"})
    assert result.returncode == 2
    assert "the licence verdict does not authorize installing these bytes" in result.stderr
    assert [call for call in _calls(log) if "install" in call] == []


def test_the_workflow_installs_only_after_source_validation_and_the_licence_stage() -> None:
    steps = [
        line.split("- name:", 1)[1].strip()
        for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("- name:")
    ]
    collect = steps.index("Collect the release closure without installing or executing it")
    licence = steps.index("Refuse a denied or unverifiable licence before any credential exists")
    install = steps.index("Install the prescreened closure into a lock-only environment")
    assert collect < licence < install
    assert not any("Install the release dependency closure" in step for step in steps)


def test_the_workflow_install_step_reuses_the_collected_download_root() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count('--download-root "${RUNNER_TEMP}/collected"') == 2
    assert "--install-gated" in text
    # The old unconditional install line must not come back.
    assert 'pip --python "${RUNNER_TEMP}/gate-venv/bin/python" install' not in text
