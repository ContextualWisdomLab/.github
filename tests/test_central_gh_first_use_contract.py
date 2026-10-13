"""Require job-local GitHub CLI provisioning before the affected host calls."""
from __future__ import annotations

import copy
from pathlib import Path
import re

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    ("strix.yml", "strix"),
    ("codeql-pr.yml", "analyze-head"),
    ("codeql-pr.yml", "dispatch-current-head"),
)
INSTALL = "Provision pinned job-local GitHub CLI"
VERIFY = "Verify pinned job-local GitHub CLI selection"


def _steps(filename: str, job: str) -> list[dict]:
    """Read the actual executable steps without interpreting the event key."""
    return yaml.safe_load((ROOT / ".github/workflows" / filename).read_text())["jobs"][job]["steps"]


def _assert_order(steps: list[dict]) -> None:
    """Require unconditional setup and selection before the first literal call."""
    installs = [i for i, step in enumerate(steps) if step.get("name") == INSTALL]
    verifies = [i for i, step in enumerate(steps) if step.get("name") == VERIFY]
    assert len(installs) == len(verifies) == 1, "missing gh provisioning/selection"
    install, verify = installs[0], verifies[0]
    calls = [i for i, step in enumerate(steps) if i not in (install, verify)
             and re.search(r"(?:^|[\s;|&($])(?:/[^\s]+/)?gh\s+(?:api|auth|pr|run)\b", step.get("run", ""))]
    assert calls and install < verify < min(calls), "gh provisioning is after first use"
    for i in (install, verify):
        # Conditional readiness must exactly follow every affected consumer.
        consumer_guards = [steps[index].get("if") for index in calls]
        expected = consumer_guards[0] if len(set(consumer_guards)) == 1 else None
        assert steps[i].get("if") == expected
        assert "continue-on-error" not in steps[i]
        assert steps[i].get("shell") == "bash"
    assert "sha256" in steps[install]["run"]
    assert 'with open(os.environ["GITHUB_PATH"], "a", encoding="utf-8")' in steps[install]["run"]
    assert "command -v gh" in steps[verify]["run"]
    assert "gh --version" in steps[verify]["run"]


@pytest.mark.parametrize("filename,job", TARGETS)
def test_affected_job_provisions_gh_before_first_host_use(filename: str, job: str) -> None:
    """Catch the original missing-prerequisite failure in each separate job."""
    _assert_order(_steps(filename, job))


@pytest.mark.parametrize("mutation", ["delete", "late", "conditional", "tolerated", "comment"])
def test_provisioning_order_rejects_mutated_executable_steps(mutation: str) -> None:
    """A name/comment or optional/late setup cannot satisfy executable ordering."""
    steps = copy.deepcopy(_steps(*TARGETS[0]))
    index = next(i for i, step in enumerate(steps) if step.get("name") == INSTALL)
    if mutation == "delete":
        del steps[index]
    elif mutation == "late":
        steps.append(steps.pop(index))
    elif mutation == "conditional":
        steps[index]["if"] = "false"
    elif mutation == "tolerated":
        steps[index]["continue-on-error"] = True
    else:
        steps[index]["run"] = "# sha256 and $GITHUB_PATH are documentation only"
    with pytest.raises(AssertionError):
        _assert_order(steps)


def test_docs_only_shard_does_not_admit_network_provisioning() -> None:
    """Preserve the docs-only check without downloading an unused host tool."""
    steps = _steps("codeql-pr.yml", "analyze-head")
    guard = "needs.detect-languages.outputs.code == 'true'"
    selected = [step for step in steps if step.get("name") in (
        "Set up Python for pinned GitHub CLI provisioning", INSTALL, VERIFY)]
    assert len(selected) == 3
    assert all(step.get("if") == guard for step in selected)
    consumer = next(step for step in steps if step.get("name") == "Read current-head CodeQL dispatch verdict")
    assert consumer.get("if") == guard


def test_strix_bootstrap_does_not_introduce_fixed_network_deadline() -> None:
    """Honor the existing Strix bootstrap DNS/TLS readiness policy."""
    import ast

    run = next(step["run"] for step in _steps("strix.yml", "strix") if step.get("name") == INSTALL)
    payload = run.split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    calls = [node for node in ast.walk(ast.parse(payload)) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "urlopen"]
    assert len(calls) == 1
    assert not calls[0].keywords, "fixed network deadline introduced before Strix review"


def _installer_tree():
    """Compile only the Python payload actually embedded in executable YAML."""
    import ast

    run = next(step["run"] for step in _steps(*TARGETS[0]) if step.get("name") == INSTALL)
    payload = run.split("python3 - <<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    return ast.parse(payload)


def _fixture_archive(binary: bytes, kind: str = "regular") -> bytes:
    """Make explicit synthetic supplier bytes for behavioral boundary controls."""
    import io
    import tarfile

    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode="w:gz") as archive:
        member = tarfile.TarInfo("gh_2.102.0_linux_amd64/bin/gh")
        if kind == "linked":
            member.type = tarfile.SYMTYPE
            member.linkname = "/outside/gh"
            archive.addfile(member)
        else:
            member.size = len(binary)
            archive.addfile(member, io.BytesIO(binary))
            if kind == "duplicate":
                archive.addfile(member, io.BytesIO(binary))
    return result.getvalue()


def _run_installer_fixture(monkeypatch, tmp_path, *, kind="regular", mismatch=None, fail_download=False):
    """Execute real embedded installer with synthetic archive pins and no network."""
    import ast
    import hashlib
    import io
    import platform
    import sys
    import urllib.request

    binary = b'#!/bin/sh\nprintf "gh version 2.102.0 (synthetic fixture)\\n"\n'
    archive = _fixture_archive(binary, kind)
    tree = _installer_tree()
    pins = {"archive_sha256": hashlib.sha256(archive).hexdigest(),
            "binary_sha256": hashlib.sha256(binary).hexdigest()}
    if mismatch:
        pins[mismatch] = "0" * 64
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            key = node.targets[0].id
            if key in pins:
                node.value = ast.Constant(pins[key])
    ast.fix_missing_locations(tree)
    runner = tmp_path / "runner"
    runner.mkdir()
    envfile = tmp_path / "env"
    pathfile = tmp_path / "path"
    monkeypatch.setenv("RUNNER_TEMP", str(runner))
    monkeypatch.setenv("GITHUB_ENV", str(envfile))
    monkeypatch.setenv("GITHUB_PATH", str(pathfile))
    # Platform patching admits only this synthetic, portable shell fixture.
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")

    def download(url, timeout=None):
        """Disallow external requests while reproducing a bounded response."""
        assert url == "https://github.com/cli/cli/releases/download/v2.102.0/gh_2.102.0_linux_amd64.tar.gz"
        assert timeout is None
        if fail_download:
            raise OSError("synthetic download refusal")
        return io.BytesIO(archive)

    monkeypatch.setattr(urllib.request, "urlopen", download)
    try:
        exec(compile(tree, "<workflow-gh-installer-fixture>", "exec"), {})
    except BaseException:
        assert not list(runner.iterdir()), "failed install must clean its exclusive directory"
        assert not envfile.exists() and not pathfile.exists()
        raise
    executable = Path(envfile.read_text().strip().split("=", 1)[1])
    assert executable.read_bytes() == binary
    assert pathfile.read_text() == str(executable.parent) + "\n"
    assert not executable.is_symlink()
    return executable


def test_embedded_installer_runs_synthetic_verified_supplier(monkeypatch, tmp_path) -> None:
    """Exercise download/hash/copy/execution/path handoff, not real gh inference."""
    _run_installer_fixture(monkeypatch, tmp_path)


@pytest.mark.parametrize("mismatch", ["archive_sha256", "binary_sha256"])
def test_embedded_installer_refuses_changed_supplier_bytes(monkeypatch, tmp_path, mismatch) -> None:
    """Neither changed archive nor changed binary can reach publication."""
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        _run_installer_fixture(monkeypatch, tmp_path, mismatch=mismatch)


@pytest.mark.parametrize("kind", ["linked", "duplicate"])
def test_embedded_installer_refuses_nonregular_or_duplicate_binary(monkeypatch, tmp_path, kind) -> None:
    """Never follow archive links or choose ambiguously duplicated members."""
    with pytest.raises(RuntimeError, match="one regular binary"):
        _run_installer_fixture(monkeypatch, tmp_path, kind=kind)


def test_embedded_installer_download_failure_cleans_exclusive_directory(monkeypatch, tmp_path) -> None:
    """A transport failure propagates before path/environment publication."""
    with pytest.raises(OSError, match="synthetic download refusal"):
        _run_installer_fixture(monkeypatch, tmp_path, fail_download=True)


@pytest.mark.parametrize("osname,architecture", [("darwin", "x86_64"), ("linux", "aarch64")])
def test_embedded_installer_refuses_unapproved_platform_before_download(monkeypatch, osname, architecture) -> None:
    """Do not execute the pinned x64 release on a different OS/architecture."""
    import platform
    import sys
    import urllib.request

    def forbidden(*args, **kwargs):
        """Any downloader invocation in this negative control is a defect."""
        pytest.fail("download attempted before unsupported-platform refusal")

    monkeypatch.setattr(sys, "platform", osname)
    monkeypatch.setattr(platform, "machine", lambda: architecture)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    with pytest.raises(RuntimeError, match="requires Linux x64"):
        exec(compile(_installer_tree(), "<workflow-gh-installer-fixture>", "exec"), {})


def test_all_three_jobs_share_identical_supplier_and_verifier() -> None:
    """Inline bootstraps must retain one exact distribution and selection contract."""
    for name in (INSTALL, VERIFY):
        payloads = [next(step["run"] for step in _steps(*target) if step.get("name") == name)
                    for target in TARGETS]
        # Only the documented Strix DNS/TLS no-timeout policy differs.
        if name == INSTALL:
            assert "urlopen(url)" in payloads[0]
            assert all("urlopen(url, timeout=30)" in item for item in payloads[1:])
            payloads = [item.replace("urlopen(url, timeout=30)", "urlopen(url)") for item in payloads]
        assert len(set(payloads)) == 1
        assert "7469124f706944133d6a169691dd1c6c3511b12e85878d255e044e2948df4c9b" in payloads[0]


@pytest.mark.parametrize("path_selection", ["approved-first", "forged-first", "changed-binary"])
def test_actual_shell_verifier_checks_path_selection_and_bytes(tmp_path, path_selection) -> None:
    """Run the real Bash verifier with explicitly pinned synthetic shell bytes."""
    import hashlib
    import os
    import shutil
    import subprocess

    bindir = tmp_path / "approved"
    forged = tmp_path / "ambient"
    bindir.mkdir()
    forged.mkdir()
    executable = bindir / "gh"
    binary = b'#!/bin/sh\nprintf "gh version 2.102.0 (synthetic fixture)\\n"\n'
    executable.write_bytes(binary)
    executable.chmod(0o700)
    (forged / "gh").write_text('#!/bin/sh\nexit 99\n')
    (forged / "gh").chmod(0o700)
    verifier = next(step["run"] for step in _steps(*TARGETS[0]) if step.get("name") == VERIFY)
    verifier = verifier.replace("7469124f706944133d6a169691dd1c6c3511b12e85878d255e044e2948df4c9b", hashlib.sha256(binary).hexdigest())
    if path_selection == "changed-binary":
        executable.write_bytes(binary + b"# changed\n")
    # sha256sum is a real host utility; no fake checksum executable is supplied.
    checksum = shutil.which("gsha256sum") or shutil.which("sha256sum")
    assert checksum, "fixture requires the actual checksum executable"
    chosen = [forged, bindir] if path_selection == "forged-first" else [bindir, forged]
    # macOS /sbin/sha256sum is BSD-compatible and lacks GNU --status; use GNU.
    checksum_dir = Path(checksum).parent
    environment = {"PATH": ":".join(map(str, chosen)) + ":" + str(checksum_dir) + ":/usr/bin:/bin",
                   "CWL_GH_BIN": str(executable), "HOME": str(tmp_path)}
    verifier = verifier.replace("sha256sum --check --status", str(checksum) + " --check --status")
    result = subprocess.run(["/bin/bash", "-e", "-c", verifier], env=environment,
                            capture_output=True, text=True, timeout=10)
    assert (result.returncode == 0) == (path_selection == "approved-first"), result.stderr
