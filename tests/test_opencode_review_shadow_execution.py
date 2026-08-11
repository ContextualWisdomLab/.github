"""Execution tests for the bounded non-publishing OpenCode shadow pool."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).resolve().parent
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

from opencode_review_shadow_test_support import (
    WRAPPER_PATH,
    changed_file,
    request,
    shadow,
    write_json,
)


def fake_opencode(
    path: Path,
    *,
    fail_role: str = "",
    sleep_role: str = "",
    leak_role: str = "",
) -> Path:
    """Create a deterministic fake OpenCode CLI that validates credential mapping."""
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, time\n"
        "args = sys.argv[1:]\n"
        "message = args[-1]\n"
        "role = message.split('role=', 1)[1].split()[0]\n"
        "assert os.environ.get('NVIDIA_API_KEY') == 'nim-secret'\n"
        "if role == " + repr(sleep_role) + ": time.sleep(2)\n"
        "if role == " + repr(fail_role) + ":\n"
        "    print('bounded fake failure', file=sys.stderr)\n"
        "    raise SystemExit(7)\n"
        "event = {'argv': args, 'role': role, 'secret_exposed': 'nim-secret' in json.dumps(args)}\n"
        "if role == " + repr(leak_role) + ":\n"
        "    event['untrusted_echo'] = os.environ['NVIDIA_API_KEY']\n"
        "    print(os.environ['NVIDIA_API_KEY'], file=sys.stderr)\n"
        "print(json.dumps(event))\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    return path


def run_inputs(tmp_path: Path) -> tuple[dict[str, object], Path, Path]:
    """Create one plan, exact evidence file, and working directory."""
    evidence = tmp_path / "evidence.md"
    evidence.write_text("evidence", encoding="utf-8")
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    return shadow.build_plan(request()), evidence, workdir


def test_execute_plan_invokes_detectors_before_verifiers_without_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner uses fixed OpenCode arguments and passes detector output to verifiers."""
    plan, evidence, workdir = run_inputs(tmp_path)
    executable = fake_opencode(tmp_path / "opencode")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nim-secret")
    output = tmp_path / "output"
    output.mkdir()
    manifest = shadow.execute_plan(
        plan,
        evidence_path=evidence,
        output_directory=output,
        opencode_binary=executable,
        working_directory=workdir,
    )
    assert manifest["shadow_mode"] is True
    assert manifest["publication_enabled"] is False
    assert manifest["plan_sha256"] == plan["plan_sha256"]
    assert all(item["status"] == "complete" for item in manifest["attempts"])
    phases = [item["phase"] for item in manifest["attempts"]]
    assert phases == ["detector", "verifier"]

    detector_record, verifier_record = manifest["attempts"]
    detector_event = json.loads(
        (output / detector_record["stdout_file"]).read_text(encoding="utf-8")
    )
    verifier_event = json.loads(
        (output / verifier_record["stdout_file"]).read_text(encoding="utf-8")
    )
    for event, record in (
        (detector_event, detector_record),
        (verifier_event, verifier_record),
    ):
        argv = event["argv"]
        assert argv[0] == "run"
        assert "--agent" in argv
        assert "--model" in argv
        assert "--variant" in argv
        assert argv[argv.index("--format") + 1] == "json"
        assert argv[argv.index("--dir") + 1] == str(workdir)
        assert "--share" not in argv
        assert "--command" not in argv
        assert event["secret_exposed"] is False
        assert record["stdout_sha256"].startswith("sha256:")
        assert record["stderr_sha256"].startswith("sha256:")
    verifier_files = [
        verifier_event["argv"][index + 1]
        for index, value in enumerate(verifier_event["argv"])
        if value == "--file"
    ]
    assert str(evidence) in verifier_files
    assert str(output / detector_record["stdout_file"]) in verifier_files
    assert manifest["execution_sha256"].startswith("sha256:")


def test_runner_records_partial_failure_and_keeps_independent_work_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One detector failure is isolated while a successful detector still feeds verification."""
    value = request(
        files=[
            changed_file("src/auth.py", risk_tags=["security"]),
        ]
    )
    plan = shadow.build_plan(value)
    executable = fake_opencode(tmp_path / "opencode", fail_role="security_detector")
    evidence = tmp_path / "evidence.md"
    evidence.write_text("evidence", encoding="utf-8")
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nim-secret")
    manifest = shadow.execute_plan(
        plan,
        evidence_path=evidence,
        output_directory=tmp_path / "output",
        opencode_binary=executable,
        working_directory=workdir,
    )
    statuses = {item["role_code"]: item["status"] for item in manifest["attempts"]}
    assert statuses["general_detector"] == "complete"
    assert statuses["security_detector"] == "failed"
    assert statuses["verifier"] == "complete"
    assert manifest["completed_attempt_count"] == 2
    assert manifest["failed_attempt_count"] == 1


def test_all_detector_failures_skip_dependent_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A verifier is not run on an empty detector evidence set."""
    plan, evidence, workdir = run_inputs(tmp_path)
    executable = fake_opencode(tmp_path / "opencode", fail_role="general_detector")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nim-secret")
    manifest = shadow.execute_plan(
        plan,
        evidence_path=evidence,
        output_directory=tmp_path / "output",
        opencode_binary=executable,
        working_directory=workdir,
    )
    assert [item["status"] for item in manifest["attempts"]] == [
        "failed",
        "dependency_failed",
    ]
    assert manifest["failed_attempt_count"] == 2


def test_timeout_is_bounded_and_recorded_without_exception_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slow model attempt is terminated and downstream verification is skipped."""
    value = request()
    value["policy"]["attempt_timeout_seconds"] = 1
    plan = shadow.build_plan(value)
    evidence = tmp_path / "evidence.md"
    evidence.write_text("evidence", encoding="utf-8")
    workdir = tmp_path / "worktree"
    workdir.mkdir()
    executable = fake_opencode(tmp_path / "opencode", sleep_role="general_detector")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nim-secret")
    manifest = shadow.execute_plan(
        plan,
        evidence_path=evidence,
        output_directory=tmp_path / "output",
        opencode_binary=executable,
        working_directory=workdir,
    )
    assert [item["status"] for item in manifest["attempts"]] == [
        "timed_out",
        "dependency_failed",
    ]


def test_child_secret_echo_is_redacted_from_all_persisted_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An untrusted child cannot persist its mapped provider secret in evidence."""
    plan, evidence, workdir = run_inputs(tmp_path)
    executable = fake_opencode(
        tmp_path / "opencode", leak_role="general_detector"
    )
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nim-secret")
    output = tmp_path / "output"
    manifest = shadow.execute_plan(
        plan,
        evidence_path=evidence,
        output_directory=output,
        opencode_binary=executable,
        working_directory=workdir,
    )
    persisted = "\n".join(
        (output / record[field]).read_text(encoding="utf-8")
        for record in manifest["attempts"]
        if record["status"] == "complete"
        for field in ("stdout_file", "stderr_file")
    )
    assert "nim-secret" not in persisted
    assert "[REDACTED_NVIDIA_API_KEY]" in persisted


def test_execution_fails_before_process_start_on_untrusted_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Credential, evidence, executable, and worktree boundaries fail closed."""
    plan, evidence, workdir = run_inputs(tmp_path)
    executable = fake_opencode(tmp_path / "opencode")
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    with pytest.raises(shadow.ShadowExecutionError, match="NVIDIA_NIM_API_KEY"):
        shadow.execute_plan(
            plan,
            evidence_path=evidence,
            output_directory=tmp_path / "output",
            opencode_binary=executable,
            working_directory=workdir,
        )

    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nim-secret")
    evidence.write_text("changed", encoding="utf-8")
    with pytest.raises(shadow.ShadowExecutionError, match="evidence_sha256"):
        shadow.execute_plan(
            plan,
            evidence_path=evidence,
            output_directory=tmp_path / "output",
            opencode_binary=executable,
            working_directory=workdir,
        )

    evidence.write_text("evidence", encoding="utf-8")
    executable.chmod(stat.S_IRWXU | stat.S_IWGRP)
    with pytest.raises(shadow.ShadowExecutionError, match="writable"):
        shadow.execute_plan(
            plan,
            evidence_path=evidence,
            output_directory=tmp_path / "output",
            opencode_binary=executable,
            working_directory=workdir,
        )

    executable.chmod(0o700)
    symlink = tmp_path / "opencode-link"
    symlink.symlink_to(executable)
    with pytest.raises(shadow.ShadowExecutionError, match="symlink"):
        shadow.execute_plan(
            plan,
            evidence_path=evidence,
            output_directory=tmp_path / "output",
            opencode_binary=symlink,
            working_directory=workdir,
        )

    non_executable = tmp_path / "not-executable"
    non_executable.write_text("not executable", encoding="utf-8")
    with pytest.raises(shadow.ShadowExecutionError, match="executable file"):
        shadow.execute_plan(
            plan,
            evidence_path=evidence,
            output_directory=tmp_path / "output",
            opencode_binary=non_executable,
            working_directory=workdir,
        )

    invalid_worktree = tmp_path / "not-a-worktree"
    invalid_worktree.write_text("not a directory", encoding="utf-8")
    with pytest.raises(shadow.ShadowExecutionError, match="trusted directory"):
        shadow.execute_plan(
            plan,
            evidence_path=evidence,
            output_directory=tmp_path / "output",
            opencode_binary=executable,
            working_directory=invalid_worktree,
        )


@pytest.mark.parametrize("boundary", ["symlink", "file", "writable", "nonempty"])
def test_execution_rejects_untrusted_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    """Output evidence cannot follow links or overwrite a reusable untrusted path."""
    plan, evidence, workdir = run_inputs(tmp_path)
    executable = fake_opencode(tmp_path / "opencode")
    output = tmp_path / "output"
    if boundary == "symlink":
        target = tmp_path / "target"
        target.mkdir()
        output.symlink_to(target, target_is_directory=True)
    elif boundary == "file":
        output.write_text("not a directory", encoding="utf-8")
    else:
        output.mkdir()
        if boundary == "writable":
            output.chmod(0o770)
        else:
            (output / "existing.txt").write_text("existing", encoding="utf-8")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "nim-secret")
    with pytest.raises(shadow.ShadowExecutionError, match="output directory"):
        shadow.execute_plan(
            plan,
            evidence_path=evidence,
            output_directory=output,
            opencode_binary=executable,
            working_directory=workdir,
        )


def test_shell_wrapper_is_thin_non_publishing_and_functional(tmp_path: Path) -> None:
    """The permanent wrapper delegates to Python and has no GitHub mutation path."""
    source = WRAPPER_PATH.read_text(encoding="utf-8")
    assert "exec python3" in source
    assert "opencode_review_shadow.py" in source
    for forbidden in ("gh ", "curl ", "git push", "pulls/", "reviews"):
        assert forbidden not in source
    subprocess.run(["bash", "-n", str(WRAPPER_PATH)], check=True)

    request_path = tmp_path / "request.json"
    output_path = tmp_path / "plan.json"
    write_json(request_path, request())
    completed = subprocess.run(
        [
            "bash",
            str(WRAPPER_PATH),
            "plan",
            "--input",
            str(request_path),
            "--output",
            str(output_path),
        ],
        check=False,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(output_path.read_text(encoding="utf-8"))["shadow_mode"] is True
