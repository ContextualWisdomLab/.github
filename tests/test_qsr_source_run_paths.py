"""Executable contract for one QSR source and run path binding."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci.qsr_source_run_paths import (
    WORKFLOW_CHECKOUT_PATH,
    WORKFLOW_CLEANUP_PATH,
    WORKFLOW_OUTPUT_PATH,
    SourceRunPathError,
    bind_source_run_paths,
    main,
    prepare_source_run_paths,
    relative_paths,
)

HEAD = "a" * 40
OTHER = "b" * 40


def test_workflow_expressions_render_to_the_relative_contract():
    """GitHub path expressions are the same contract as the Python paths."""
    rendered = {
        "checkout": WORKFLOW_CHECKOUT_PATH,
        "output": WORKFLOW_OUTPUT_PATH,
        "cleanup": WORKFLOW_CLEANUP_PATH,
    }
    tokens = {
        "${{ github.job }}": "branch-coverage",
        "${{ github.run_id }}": "17",
        "${{ github.run_attempt }}": "2",
        "${{ github.event.pull_request.head.sha || github.sha }}": HEAD,
    }
    for role, value in rendered.items():
        for token, replacement in tokens.items():
            value = value.replace(token, replacement)
        rendered[role] = value
    expected = relative_paths("branch-coverage", HEAD, "17", "2")
    assert rendered["checkout"] == expected["checkout"]
    assert rendered["output"] == expected["output"]
    assert rendered["cleanup"] == expected["cleanup"]
    assert expected["cwd"] == expected["checkout"]
    assert expected["checkout"] != expected["output"]


def test_distinct_source_run_and_job_do_not_share_paths(tmp_path):
    """Another source, earlier attempt, or other job gets a disjoint cleanup root."""
    current = bind_source_run_paths(
        tmp_path, job="verify", source=HEAD, run_id="17", run_attempt="2"
    )
    variants = (
        bind_source_run_paths(
            tmp_path, job="verify", source=OTHER, run_id="17", run_attempt="2"
        ),
        bind_source_run_paths(
            tmp_path, job="verify", source=HEAD, run_id="17", run_attempt="1"
        ),
        bind_source_run_paths(
            tmp_path, job="coverage", source=HEAD, run_id="18", run_attempt="2"
        ),
    )
    for other in variants:
        assert current["cleanup"] != other["cleanup"]
        assert not str(other["cleanup"]).startswith(str(current["cleanup"]) + os.sep)
        assert not str(current["cleanup"]).startswith(str(other["cleanup"]) + os.sep)


@pytest.mark.parametrize(
    ("job", "source", "run_id", "run_attempt"),
    [
        ("Verify", HEAD, "17", "2"),
        ("../verify", HEAD, "17", "2"),
        ("verify", "A" * 40, "17", "2"),
        ("verify", HEAD, "0", "2"),
        ("verify", HEAD, "17", "02"),
    ],
)
def test_identity_rejection(job, source, run_id, run_attempt):
    """Path components that can escape or collide are refused before use."""
    with pytest.raises(SourceRunPathError):
        relative_paths(job, source, run_id, run_attempt)


def test_refuses_symlink_file_and_missing_workspace(tmp_path):
    """A workspace must be a real directory, not a link, file, or absent path."""
    linked = tmp_path / "linked"
    target = tmp_path / "target"
    target.mkdir()
    linked.symlink_to(target, target_is_directory=True)
    file_path = tmp_path / "file"
    file_path.write_text("x", encoding="utf-8")
    for workspace in (linked, file_path, tmp_path / "missing"):
        with pytest.raises(SourceRunPathError, match="workspace"):
            bind_source_run_paths(
                workspace, job="verify", source=HEAD, run_id="17", run_attempt="2"
            )


def test_refuses_evidence_and_tool_overlap(tmp_path):
    """The four paths must not contain or sit inside evidence or tool directories."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evidence = workspace / "qsr-job" / "verify" / "17" / "2" / HEAD
    evidence.mkdir(parents=True)
    with pytest.raises(SourceRunPathError, match="mixes"):
        bind_source_run_paths(
            workspace,
            job="verify",
            source=HEAD,
            run_id="17",
            run_attempt="2",
            evidence_roots=(evidence.resolve(),),
        )
    tool = tmp_path / "tool"
    tool.mkdir()
    output = workspace / "qsr-job" / "verify" / "17" / "2" / OTHER / "output"
    with pytest.raises(SourceRunPathError, match="absolute"):
        bind_source_run_paths(
            workspace,
            job="verify",
            source=OTHER,
            run_id="17",
            run_attempt="2",
            tool_roots=(Path("relative-tool"),),
        )
    with pytest.raises(SourceRunPathError, match="mixes"):
        bind_source_run_paths(
            workspace,
            job="verify",
            source=OTHER,
            run_id="17",
            run_attempt="2",
            tool_roots=(output,),
        )


def test_prepare_creates_private_output_and_refuses_existing_nodes(tmp_path):
    """Preparation creates only this run's directories and does not adopt nodes."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    paths = bind_source_run_paths(
        workspace, job="verify", source=HEAD, run_id="17", run_attempt="2"
    )
    prepare_source_run_paths(paths)
    for key in ("cleanup", "output"):
        mode = stat.S_IMODE(paths[key].stat().st_mode)
        assert mode == 0o700, key
    assert not paths["checkout"].exists()
    with pytest.raises(SourceRunPathError, match="cleanup already exists"):
        prepare_source_run_paths(paths)
    outside = tmp_path / "outside-output"
    outside.mkdir()
    fresh = bind_source_run_paths(
        workspace, job="coverage", source=HEAD, run_id="17", run_attempt="2"
    )
    fresh["output"] = outside
    with pytest.raises(SourceRunPathError, match="output already exists"):
        prepare_source_run_paths(fresh)
    link_parent = tmp_path / "link-parent"
    link_parent.mkdir()
    link = link_parent / "cleanup-link"
    link.symlink_to(workspace, target_is_directory=True)
    with pytest.raises(SourceRunPathError, match="cleanup already exists"):
        prepare_source_run_paths({"cleanup": link, "output": tmp_path / "unused"})


def test_entrypoint_prints_paths_and_refuses_mixing(tmp_path, capsys):
    """The module entrypoint is the consumer of the path contract."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    code = main(
        [
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
            "--evidence",
            str(evidence),
            "--prepare",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert Path(payload["cwd"]) == Path(payload["checkout"])
    assert Path(payload["output"]).is_dir()
    assert not str(payload["cleanup"]).startswith(str(evidence))
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.ci.qsr_source_run_paths",
            "--workspace",
            str(workspace),
            "--job",
            "podman-e2e-positive-lsm",
            "--source",
            HEAD,
            "--run-id",
            "17",
            "--run-attempt",
            "4",
            "--tool",
            str(evidence),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    external = json.loads(completed.stdout)
    assert Path(external["cwd"]) == Path(external["checkout"])
    assert Path(external["output"]).parent == Path(external["cleanup"])
    assert Path(external["checkout"]).parent == Path(external["cleanup"])
    plain = main(
        [
            "--workspace",
            str(workspace),
            "--job",
            "verify",
            "--source",
            OTHER,
            "--run-id",
            "17",
            "--run-attempt",
            "5",
            "--evidence",
            str(evidence),
        ]
    )
    assert plain == 0
    plain_payload = json.loads(capsys.readouterr().out)
    assert plain_payload["cwd"] == plain_payload["checkout"]
    refused = main(
        [
            "--workspace",
            str(workspace),
            "--job",
            "podman-e2e-positive-lsm",
            "--source",
            HEAD,
            "--run-id",
            "17",
            "--run-attempt",
            "4",
            "--tool",
            str(Path(external["cleanup"])),
        ]
    )
    assert refused == 1
    assert "SRC03-PATH-001" in capsys.readouterr().err


def test_module_guard_returns_entrypoint_status(tmp_path, monkeypatch):
    """Running the module as __main__ uses the same path entrypoint."""
    import runpy

    workspace = tmp_path / "guard-workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qsr_source_run_paths",
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
        runpy.run_module("scripts.ci.qsr_source_run_paths", run_name="__main__")
    assert raised.value.code == 0
