"""Executable contract for one-time QSR job-private paths and run witnesses."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci.qsr_job_private import (
    JobPrivateError,
    _contained,
    _publish,
    _read_witness,
    claim_job_private,
    cleanup_job_private,
    main,
    use_job_private,
    witness_document,
)
from scripts.ci.qsr_source_run_paths import SourceRunPathError, relative_paths

HEAD = "a" * 40
OTHER = "b" * 40


def _claim(workspace, **overrides):
    """Claim one private path with the default run identity."""
    values = {
        "job": "verify",
        "source": HEAD,
        "run_id": "17",
        "run_attempt": "2",
    }
    values.update(overrides)
    return claim_job_private(workspace, **values)


def test_witness_hash_changes_when_the_run_changes_and_keeps_the_head():
    """The same head in a later run gets a different witness hash."""
    current = witness_document("verify", HEAD, "17", "2")
    later = witness_document("verify", HEAD, "18", "2")
    other_head = witness_document("verify", OTHER, "17", "2")
    assert current["head"] == HEAD
    assert current["sha256"] != later["sha256"]
    assert current["sha256"] != other_head["sha256"]
    assert len(current["sha256"]) == 64


def test_claim_use_and_cleanup_record_one_private_path(tmp_path):
    """Creation, use, and cleanup stay on this run and leave the neighbor."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    evidence_file = evidence / "kept.txt"
    evidence_file.write_text("keep", encoding="utf-8")
    tool = tmp_path / "tool"
    tool.mkdir()
    claimed = _claim(workspace, evidence_roots=(evidence,), tool_roots=(tool,))
    paths = claimed["paths"]
    assert paths["cwd"] == paths["checkout"]
    assert paths["cleanup"] == workspace / relative_paths("verify", HEAD, "17", "2")["cleanup"]
    assert paths["output"].is_dir()
    assert not paths["checkout"].exists()
    witness = json.loads((paths["cleanup"] / "run-witness.json").read_text(encoding="utf-8"))
    assert witness == claimed["witness"]
    marker = paths["output"] / "used.txt"
    marker.write_text("used", encoding="utf-8")
    (paths["cleanup"] / "checkout").mkdir()
    (paths["checkout"] / "source.txt").write_text("source", encoding="utf-8")
    used = use_job_private(
        workspace,
        job="verify",
        source=HEAD,
        run_id="17",
        run_attempt="2",
        evidence_roots=(evidence,),
        tool_roots=(tool,),
    )
    assert used["witness"] == claimed["witness"]
    neighbor = _claim(workspace, job="coverage", run_id="18")
    removed = cleanup_job_private(
        workspace,
        job="verify",
        source=HEAD,
        run_id="17",
        run_attempt="2",
        evidence_roots=(evidence,),
        tool_roots=(tool,),
    )
    assert removed["removed"] == str(paths["cleanup"])
    assert not paths["cleanup"].exists()
    assert neighbor["paths"]["cleanup"].is_dir()
    assert evidence_file.read_text(encoding="utf-8") == "keep"
    assert tool.is_dir()
    assert stat.S_IMODE(neighbor["paths"]["cleanup"].stat().st_mode) == 0o700


def test_previous_witness_is_not_reused_for_a_later_run(tmp_path):
    """A witness file from an earlier run is refused even when the head matches."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = _claim(workspace, run_id="17")
    previous = (first["paths"]["cleanup"] / "run-witness.json").read_bytes()
    second = _claim(workspace, run_id="18")
    witness = second["paths"]["cleanup"] / "run-witness.json"
    witness.unlink()
    witness.write_bytes(previous)
    with pytest.raises(JobPrivateError, match="current binding"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="18", run_attempt="2")
    with pytest.raises(JobPrivateError, match="current binding"):
        cleanup_job_private(
            workspace, job="verify", source=HEAD, run_id="18", run_attempt="2"
        )
    assert witness.read_bytes() == previous
    assert second["paths"]["output"].is_dir()
    assert first["paths"]["cleanup"].is_dir()


def test_claim_refuses_an_existing_private_root_and_path_mixing(tmp_path):
    """A second claim and an evidence overlap do not adopt the private path."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = _claim(workspace)
    original = (first["paths"]["cleanup"] / "run-witness.json").read_bytes()
    with pytest.raises(SourceRunPathError, match="cleanup already exists"):
        _claim(workspace)
    assert (first["paths"]["cleanup"] / "run-witness.json").read_bytes() == original
    overlap = workspace / "qsr-job"
    with pytest.raises(SourceRunPathError, match="mixes"):
        _claim(workspace, run_id="19", evidence_roots=(overlap,))


def test_private_root_rejects_escaped_and_unprivate_nodes(tmp_path):
    """Symlinks, files, and loose modes are not a job-private directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(JobPrivateError, match="escapes"):
        _contained(workspace, outside)
    linked_workspace = tmp_path / "linked-workspace"
    linked_workspace.symlink_to(workspace, target_is_directory=True)
    with pytest.raises(SourceRunPathError, match="workspace"):
        _claim(linked_workspace)
    file_workspace = tmp_path / "file-workspace"
    file_workspace.write_text("x", encoding="utf-8")
    with pytest.raises(SourceRunPathError, match="workspace"):
        _claim(file_workspace)
    blocked = workspace / "qsr-job"
    blocked.write_text("blocked", encoding="utf-8")
    with pytest.raises(JobPrivateError, match="escapes"):
        _claim(workspace)
    blocked.unlink()
    target = tmp_path / "linked-parent"
    target.mkdir()
    blocked.symlink_to(target, target_is_directory=True)
    with pytest.raises(JobPrivateError, match="escapes"):
        _claim(workspace)
    assert not any(target.iterdir())
    blocked.unlink()
    claimed = _claim(workspace, run_id="21")
    mode_path = claimed["paths"]["output"]
    mode_path.chmod(0o755)
    with pytest.raises(JobPrivateError, match="not private"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="21", run_attempt="2")
    mode_path.chmod(0o700)
    leaf = claimed["paths"]["cleanup"]
    witness = leaf / "run-witness.json"
    witness.unlink()
    witness.symlink_to(outside / "missing")
    with pytest.raises(JobPrivateError, match="regular file"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="21", run_attempt="2")


def test_witness_file_shapes_are_refused(tmp_path):
    """Only one regular current witness file can authorize the private path."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    claimed = _claim(workspace)
    witness = claimed["paths"]["cleanup"] / "run-witness.json"
    _publish(tmp_path / "fresh-witness.json", claimed["witness"])
    with pytest.raises(JobPrivateError, match="already exists"):
        _publish(tmp_path / "fresh-witness.json", claimed["witness"])
    with pytest.raises(JobPrivateError, match="not a new file"):
        _publish(tmp_path / "missing-parent" / "witness.json", claimed["witness"])
    original = witness.read_bytes()
    witness.unlink()
    witness.write_bytes(b"")
    with pytest.raises(JobPrivateError, match="regular file"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="17", run_attempt="2")
    witness.write_bytes(b"{" * 4097)
    with pytest.raises(JobPrivateError, match="too large"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="17", run_attempt="2")
    witness.write_bytes(b"\xff")
    with pytest.raises(JobPrivateError, match="current binding"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="17", run_attempt="2")
    witness.write_bytes(b"[]")
    with pytest.raises(JobPrivateError, match="current binding"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="17", run_attempt="2")
    witness.write_bytes(b"not-json")
    with pytest.raises(JobPrivateError, match="current binding"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="17", run_attempt="2")
    duplicate = original.replace(b'"head":', b'"head":"x","head":', 1)
    witness.write_bytes(duplicate)
    with pytest.raises(JobPrivateError, match="current binding"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="17", run_attempt="2")
    payload = json.loads(original.decode("utf-8"))
    payload["extra"] = "no"
    witness.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(JobPrivateError, match="current binding"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="17", run_attempt="2")
    del payload["extra"]
    payload["run_id"] = 17
    witness.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(JobPrivateError, match="current binding"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="17", run_attempt="2")
    payload["run_id"] = "17"
    payload["sha256"] = "c" * 64
    witness.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    with pytest.raises(JobPrivateError, match="current binding"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="17", run_attempt="2")
    witness.write_bytes(original)
    linked = witness.with_name("hard-link.json")
    os.link(witness, linked)
    with pytest.raises(JobPrivateError, match="regular file"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="17", run_attempt="2")
    linked.unlink()
    missing = claimed["paths"]["cleanup"] / "absent.json"
    with pytest.raises(JobPrivateError, match="regular file"):
        _read_witness(missing)
    directory = claimed["paths"]["cleanup"] / "witness-dir"
    directory.mkdir()
    with pytest.raises(JobPrivateError, match="regular file"):
        _read_witness(directory)


def test_witness_read_refuses_a_short_or_changed_file(tmp_path, monkeypatch):
    """A witness that changes while it is read is not the current binding."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    claimed = _claim(workspace)
    real_read = os.read

    def short_read(descriptor, size):
        """Return fewer bytes than the witness file contained."""
        real_read(descriptor, size)
        return b""

    monkeypatch.setattr(os, "read", short_read)
    with pytest.raises(JobPrivateError, match="changed while reading"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="17", run_attempt="2")
    monkeypatch.undo()
    real_stat = os.fstat
    seen = {"count": 0}

    def changed_stat(descriptor):
        """Report a different size after the witness bytes were read."""
        seen["count"] += 1
        info = real_stat(descriptor)
        if seen["count"] == 2:
            class Changed:
                """Stat stand-in with one moved size field."""

                def __getattr__(self, name):
                    if name == "st_size":
                        return info.st_size + 1
                    return getattr(info, name)

            return Changed()
        return info

    monkeypatch.setattr(os, "fstat", changed_stat)
    with pytest.raises(JobPrivateError, match="changed while reading"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="17", run_attempt="2")
    assert claimed["paths"]["cleanup"].is_dir()


def test_cleanup_keeps_symlink_targets_and_refuses_special_nodes(tmp_path):
    """Cleanup unlinks only nodes inside the matching private root."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    claimed = _claim(workspace)
    outside = tmp_path / "outside.txt"
    outside.write_text("stay", encoding="utf-8")
    link = claimed["paths"]["output"] / "alias"
    link.symlink_to(outside)
    linked_dir = claimed["paths"]["cleanup"] / "linked-dir"
    linked_dir.symlink_to(tmp_path, target_is_directory=True)
    real_dir = claimed["paths"]["output"] / "nested"
    real_dir.mkdir()
    (real_dir / "nested.txt").write_text("nested", encoding="utf-8")
    removed = cleanup_job_private(
        workspace, job="verify", source=HEAD, run_id="17", run_attempt="2"
    )
    assert removed["action"] == "cleanup"
    assert not claimed["paths"]["cleanup"].exists()
    assert outside.read_text(encoding="utf-8") == "stay"
    special = _claim(workspace, run_id="22")
    fifo = special["paths"]["output"] / "queue"
    os.mkfifo(fifo)
    with pytest.raises(JobPrivateError, match="unsupported node"):
        cleanup_job_private(
            workspace, job="verify", source=HEAD, run_id="22", run_attempt="2"
        )
    assert fifo.exists()
    assert (special["paths"]["cleanup"] / "run-witness.json").is_file()


def test_missing_private_path_and_file_root_are_refused(tmp_path):
    """Use and cleanup do not create or adopt a path that was not claimed."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(JobPrivateError, match="missing"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="17", run_attempt="2")
    paths = relative_paths("verify", HEAD, "23", "2")
    file_root = workspace / paths["cleanup"]
    file_root.parent.mkdir(parents=True)
    file_root.write_text("file", encoding="utf-8")
    with pytest.raises(JobPrivateError, match="missing"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="23", run_attempt="2")
    file_root.unlink()
    file_root.symlink_to(workspace, target_is_directory=True)
    with pytest.raises(JobPrivateError, match="escapes"):
        use_job_private(workspace, job="verify", source=HEAD, run_id="23", run_attempt="2")


def test_entrypoint_prints_the_run_record_and_refuses_reuse(tmp_path, capsys):
    """The module entrypoint is the consumer of claim, use, and cleanup."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    arguments = [
        "--workspace",
        str(workspace),
        "--job",
        "podman-e2e-positive-lsm",
        "--source",
        HEAD,
        "--run-id",
        "17",
        "--run-attempt",
        "3",
    ]
    assert main(["claim", *arguments]) == 0
    claimed = json.loads(capsys.readouterr().out)
    assert claimed["cwd"] == claimed["checkout"]
    assert claimed["head"] == HEAD
    assert claimed["run_id"] == "17"
    assert Path(claimed["output"]).is_dir()
    assert main(["use", *arguments]) == 0
    used = json.loads(capsys.readouterr().out)
    assert used["sha256"] == claimed["sha256"]
    assert main(["claim", *arguments]) == 1
    assert "SRC03-PATH-001" in capsys.readouterr().err
    witness = Path(claimed["cleanup"]) / "run-witness.json"
    previous = witness.read_bytes()
    assert main(["cleanup", *arguments]) == 0
    removed = json.loads(capsys.readouterr().out)
    assert removed["action"] == "cleanup"
    assert removed["removed"] == removed["cleanup"]
    assert not Path(removed["removed"]).exists()
    later = [
        "--workspace",
        str(workspace),
        "--job",
        "podman-e2e-positive-lsm",
        "--source",
        HEAD,
        "--run-id",
        "18",
        "--run-attempt",
        "3",
    ]
    assert main(["claim", *later]) == 0
    capsys.readouterr()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.ci.qsr_job_private",
            "use",
            "--workspace",
            str(workspace),
            "--job",
            "podman-e2e-positive-lsm",
            "--source",
            HEAD,
            "--run-id",
            "18",
            "--run-attempt",
            "3",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    external = json.loads(completed.stdout)
    assert external["sha256"] != claimed["sha256"]
    reused = Path(external["cleanup"]) / "run-witness.json"
    owned = reused.read_bytes()
    reused.write_bytes(previous)
    refused = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.ci.qsr_job_private",
            "use",
            "--workspace",
            str(workspace),
            "--job",
            "podman-e2e-positive-lsm",
            "--source",
            HEAD,
            "--run-id",
            "18",
            "--run-attempt",
            "3",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )
    assert refused.returncode == 1
    assert "SRC03-PRIVATE-001" in refused.stderr
    assert reused.read_bytes() == previous
    assert main(["cleanup", *later]) == 1
    assert Path(external["output"]).is_dir()
    reused.write_bytes(owned)
    cleaned = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.ci.qsr_job_private",
            "cleanup",
            "--workspace",
            str(workspace),
            "--job",
            "podman-e2e-positive-lsm",
            "--source",
            HEAD,
            "--run-id",
            "18",
            "--run-attempt",
            "3",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )
    assert cleaned.returncode == 0, cleaned.stderr
    record = json.loads(cleaned.stdout)
    assert record["action"] == "cleanup"
    assert record["removed"] == record["cleanup"]
    assert not Path(record["removed"]).exists()
    assert not Path(claimed["cleanup"]).exists()


def test_module_guard_returns_entrypoint_status(tmp_path, monkeypatch):
    """Running the module as __main__ uses the same private-path entrypoint."""
    import runpy

    workspace = tmp_path / "guard-workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qsr_job_private",
            "claim",
            "--workspace",
            str(workspace),
            "--job",
            "verify",
            "--source",
            HEAD,
            "--run-id",
            "9",
            "--run-attempt",
            "1",
        ],
    )
    with pytest.raises(SystemExit) as raised:
        runpy.run_module("scripts.ci.qsr_job_private", run_name="__main__")
    assert raised.value.code == 0
