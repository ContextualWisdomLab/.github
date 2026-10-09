"""Tool consumer regression: real gate/binder, fake collection and installer."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import release_dependency_gate as gate
from tests.test_release_dependency_gate import _fixture_archive, REVIEWED_TEXTS


@pytest.mark.parametrize("case", ["permitted", "forbidden", "unknown", "changed", "direct", "credentials"])
@pytest.mark.parametrize("role", ["co", "strix"])
def test_tool_prepare_real_consumer(tmp_path, monkeypatch, case, role):
    original_run = subprocess.run
    source = tmp_path / "source"
    source.mkdir()
    lock_name = "requirements.lock" if role == "co" else "requirements-strix-ci-hashes.txt"
    text = REVIEWED_TEXTS["pytest-9.1.1.txt"]
    expression = "MIT"
    if case == "forbidden":
        expression = "GPL-3.0-only"
    if case == "unknown":
        text = "Academic use only"
    snapshot = _fixture_archive({"LICENSE": text}, "pypi")
    digest = hashlib.sha256(snapshot).hexdigest()
    lock = f"greenlib==1.0.0 --hash=sha256:{digest}\n"
    if case == "direct":
        lock = "greenlib @ https://example.invalid/archive.tar.gz\n"
    (source / lock_name).write_text(lock)
    for args in (["init", "-q"], ["add", lock_name],
                 ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"]):
        original_run(["git", "-C", str(source), *args], check=True, capture_output=True)
    sha = original_run(["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    root = tmp_path / "tool"
    log = tmp_path / "installer.log"
    recorder = tmp_path / "fake-pip"
    recorder.write_text(f"#!{sys.executable}\nimport sys\nopen({str(log)!r},'a').write(repr(sys.argv[1:])+'\\n')\n")
    recorder.chmod(0o700)
    monkeypatch.setenv("RELEASE_GATE_PIP", str(recorder))
    for name in (*gate.STRIX_CREDENTIAL_NAMES, "ORCHESTRATOR_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    if case == "credentials":
        monkeypatch.setenv("ORCHESTRATOR_TOKEN", "synthetic-not-a-secret")
    calls = []

    def run(argv, **kwargs):
        if "--raw-root" in argv:
            calls.append("capture")
            raw = root / "raw" / "greenlib"
            raw.mkdir(parents=True)
            (raw / "source.archive").write_bytes(snapshot)
            (raw / "source.sha256").write_text(digest)
            (raw / "metadata.json").write_text(json.dumps({"ecosystem": "pypi", "name": "greenlib", "version": "1.0.0", "license_expression": expression, "distribution_inclusion": ["wheel"]}))
            python = root / "capture/python"
            python.mkdir(parents=True)
            (python / "lock.txt").write_text(lock)
            (python / "installed.json").write_text(json.dumps({"installed": [{"metadata": {"name": "greenlib", "version": "1.0.0"}}]}))
            (root / "collected").mkdir()
            (root / "collected/greenlib-1.0.0-py3-none-any.whl").write_bytes(snapshot)
            if case == "changed":
                (source / lock_name).write_text(lock + "# changed\n")
            return subprocess.CompletedProcess(argv, 0)
        if "venv" in argv and "--without-pip" in argv:
            (root / "venv/bin").mkdir(parents=True)
            (root / "venv/bin/python").symlink_to(sys.executable)
            return subprocess.CompletedProcess(argv, 0)
        return original_run(argv, **kwargs)

    monkeypatch.setattr(gate.subprocess, "run", run)
    if case == "permitted":
        assert gate.main([
            "tool-environment", "--prepare", "--role", role, "--source", str(source),
            "--source-sha", sha, "--root", str(root),
        ]) == 0
        assert "install" in log.read_text()
        # The complete pinned closure is authoritative. In particular Strix's
        # declared cryptography<49 must not re-resolve the approved lock's 50 pin.
        assert "--no-deps" in log.read_text()
        assert digest in (root / "collected/gated-requirements.txt").read_text()
        gate.tool_environment(source, sha, root, role, prepare=False)
        assert len(log.read_text().splitlines()) == 1
        (source / lock_name).write_text(lock + "# changed after preparation\n")
        with pytest.raises(gate.GateError, match=gate.SOURCE_HASH_MISMATCH):
            gate.tool_environment(source, sha, root, role, prepare=False)
        assert len(log.read_text().splitlines()) == 1
    else:
        with pytest.raises(gate.GateError):
            gate.tool_environment(source, sha, root, role, prepare=True)
        assert not log.exists()
        if case in {"direct", "credentials"}:
            assert calls == []


def test_every_sidecar_workflow_prepares_before_credential_step():
    root = Path(__file__).resolve().parents[1]
    for name in ("noema-review.yml", "strix.yml", "opencode-review-dispatch.yml", "pr-review-autofix.yml", "release-dependency-license-strix-gate.yml"):
        source = (root / ".github/workflows" / name).read_text()
        prepare = source.index("contextual_orchestrator_review_sidecar.sh\" --prepare") if name != "release-dependency-license-strix-gate.yml" else source.index("contextual_orchestrator_review_sidecar.sh --prepare")
        assert "BYTEZ_API_KEY:" not in source[source.rfind("      - name:", 0, prepare):prepare]
        assert "contextual_orchestrator_review_sidecar.sh" in source[prepare + 60:]


def test_tool_identity_cli_prints_the_lock_digest(tmp_path: Path) -> None:
    """The sidecar receipt is the exact commit and the tracked lock digest."""
    source = tmp_path / "source"
    source.mkdir()
    lock = "greenlib==1.0.0 --hash=sha256:" + "ab" * 32 + "\n"
    (source / "requirements.lock").write_text(lock)
    subprocess.run(["git", "-C", str(source), "init", "-q"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(source), "add", "requirements.lock"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-qm", "fixture"],
        check=True,
        capture_output=True,
    )
    sha = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert gate.main(["tool-identity", "--role", "co", "--source", str(source), "--source-sha", sha]) == 0


def test_tool_source_identity_refuses_an_inexact_checkout(tmp_path: Path, monkeypatch) -> None:
    """A bad SHA, another commit, or a swapped lock is not the pinned source."""
    source = tmp_path / "source"
    source.mkdir()
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises(gate.GateError, match=gate.SOURCE_HASH_MISMATCH):
        gate.tool_source_identity(link, "a" * 40, "requirements.lock")
    (source / "requirements.lock").write_text("greenlib==1.0.0 --hash=sha256:" + "ab" * 32 + "\n")
    subprocess.run(["git", "-C", str(source), "init", "-q"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(source), "add", "requirements.lock"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-qm", "fixture"],
        check=True, capture_output=True,
    )
    sha = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()
    with pytest.raises(gate.GateError, match=gate.SOURCE_HASH_MISMATCH):
        gate.tool_source_identity(source, "not-a-sha", "requirements.lock")
    with pytest.raises(gate.GateError, match=gate.SOURCE_HASH_MISMATCH):
        gate.tool_source_identity(source, "b" * 40, "requirements.lock")
    real = gate._tool_git_stdout

    def diverge(checkout: Path, *args: str) -> bytes:
        if args and args[0] == "show":
            return b"different\n"
        return real(checkout, *args)

    monkeypatch.setattr(gate, "_tool_git_stdout", diverge)
    with pytest.raises(gate.GateError, match=gate.SOURCE_HASH_MISMATCH):
        gate.tool_source_identity(source, sha, "requirements.lock")


def test_launch_refuses_a_receipt_for_a_different_lock(tmp_path: Path) -> None:
    """Launch does not install when the preparation receipt names another lock."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "requirements.lock").write_text("greenlib==1.0.0 --hash=sha256:" + "ab" * 32 + "\n")
    subprocess.run(["git", "-C", str(source), "init", "-q"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(source), "add", "requirements.lock"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "commit", "-qm", "fixture"],
        check=True, capture_output=True,
    )
    sha = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True,
    ).stdout.strip()
    root = tmp_path / "tool"
    root.mkdir()
    (root / "prepared.json").write_text("{}")
    with pytest.raises(gate.GateError, match=gate.SOURCE_HASH_MISMATCH):
        gate.tool_environment(source, sha, root, "co", prepare=False)


def test_tool_environment_refuses_a_symlinked_source(tmp_path: Path) -> None:
    """A symlinked checkout is not an exact tool source."""
    source = tmp_path / "source"
    source.mkdir()
    link = tmp_path / "link"
    link.symlink_to(source)
    with pytest.raises(gate.GateError, match=gate.SOURCE_HASH_MISMATCH):
        gate.tool_environment(link, "a" * 40, tmp_path / "root", "co", prepare=True)
