"""Source-bound refusal of stale, symlink, and empty QSR output artifacts."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci.qsr_source_artifacts import (
    SourceArtifactError,
    admit_source_artifact,
    main,
)
from scripts.ci.qsr_source_run_paths import (
    SourceRunPathError,
    bind_source_run_paths,
    prepare_source_run_paths,
)

HEAD = "a" * 40
OTHER = "b" * 40
JOB = "verify"
RUN_ID = "17"
ATTEMPT = "2"
SENTINEL = "FOREIGN-SENTINEL-NOT-EVIDENCE"


def _output(tmp_path, source=HEAD):
    """Create one prepared output directory for a source."""
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True)
    paths = bind_source_run_paths(
        workspace, job=JOB, source=source, run_id=RUN_ID, run_attempt=ATTEMPT
    )
    prepare_source_run_paths(paths)
    return workspace, paths["output"]


def _bind(artifact: Path, source: str) -> None:
    """Write a regular sidecar that names one source."""
    payload = json.dumps({"source": source}, sort_keys=True)
    artifact.with_name(artifact.name + ".source.json").write_text(
        payload, encoding="utf-8"
    )


def _admit(workspace, artifact, source=HEAD):
    """Admit one artifact against one target source."""
    return admit_source_artifact(
        workspace,
        artifact,
        job=JOB,
        source=source,
        run_id=RUN_ID,
        run_attempt=ATTEMPT,
    )


def test_three_unbound_artifacts_are_distinct_and_bound_file_stays(tmp_path):
    """Stale, symlink, and empty artifacts refuse; a bound file still admits."""
    workspace, output = _output(tmp_path)
    bound = output / "podman-info.json"
    bound.write_text('{"host":{}}\n', encoding="utf-8")
    _bind(bound, HEAD)
    stale = output / "previous.json"
    stale.write_text('{"host":{"old":true}}\n', encoding="utf-8")
    _bind(stale, OTHER)
    empty = output / "empty.json"
    empty.write_bytes(b"")
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text(SENTINEL, encoding="utf-8")
    link = output / "linked.json"
    link.symlink_to(sentinel)

    accepted = _admit(workspace, bound)
    assert accepted["result"] == "accepted"
    assert accepted["bound"] is True
    assert accepted["code"] == "SRC03-ART-BOUND"
    assert accepted["source"] == HEAD
    assert accepted["fixture"] == str(bound)

    refused = {}
    for artifact in (stale, link, empty):
        with pytest.raises(SourceArtifactError) as caught:
            _admit(workspace, artifact)
        refused[caught.value.code] = caught.value
        assert caught.value.record["source"] == HEAD
        assert caught.value.record["fixture"] == str(artifact)
        assert caught.value.record["result"] == "refused"
        assert caught.value.record["bound"] is False
        assert SENTINEL not in json.dumps(caught.value.record)
    assert set(refused) == {
        "SRC03-ART-STALE",
        "SRC03-ART-SYMLINK",
        "SRC03-ART-EMPTY",
    }
    assert sentinel.read_text(encoding="utf-8") == SENTINEL
    assert link.resolve() != bound


def test_artifact_outside_this_source_output_is_stale(tmp_path):
    """A file under another source output is not admitted for this source."""
    workspace, _output_dir = _output(tmp_path)
    _foreign_workspace, foreign_output = _output(tmp_path / "other", source=OTHER)
    foreign = foreign_output / "podman-info.json"
    foreign.write_text("foreign\n", encoding="utf-8")
    _bind(foreign, OTHER)
    with pytest.raises(SourceArtifactError) as caught:
        _admit(workspace, foreign)
    assert caught.value.code == "SRC03-ART-STALE"
    assert caught.value.record["fixture"] == str(foreign)
    assert caught.value.record["source"] == HEAD


def test_relative_missing_and_nonregular_artifacts_are_stale(tmp_path):
    """Relative, absent, directory, and hardlinked artifacts are not bound."""
    workspace, output = _output(tmp_path)
    with pytest.raises(SourceArtifactError) as relative:
        _admit(workspace, Path("podman-info.json"))
    assert relative.value.code == "SRC03-ART-STALE"
    missing = output / "missing.json"
    with pytest.raises(SourceArtifactError) as absent:
        _admit(workspace, missing)
    assert absent.value.code == "SRC03-ART-STALE"
    directory = output / "dir.json"
    directory.mkdir()
    with pytest.raises(SourceArtifactError) as folder:
        _admit(workspace, directory)
    assert folder.value.code == "SRC03-ART-STALE"
    source_file = output / "one.json"
    source_file.write_text("x", encoding="utf-8")
    linked = output / "two.json"
    os.link(source_file, linked)
    _bind(linked, HEAD)
    with pytest.raises(SourceArtifactError) as hard:
        _admit(workspace, linked)
    assert hard.value.code == "SRC03-ART-STALE"


def test_duplicate_source_key_refuses_artifact_body(tmp_path):
    """A repeated source key is stale and does not approve the artifact body."""
    workspace, output = _output(tmp_path)
    artifact = output / "podman-info.json"
    body = b'{"host":{"sentinel":"FOREIGN-BODY-NOT-APPROVED"}}\n'
    artifact.write_bytes(body)
    sidecar = (
        b'{"source":"' + OTHER.encode("ascii") + b'","source":"'
        + HEAD.encode("ascii") + b'"}'
    )
    artifact.with_name(artifact.name + ".source.json").write_bytes(sidecar)
    with pytest.raises(SourceArtifactError) as caught:
        _admit(workspace, artifact)
    assert caught.value.code == "SRC03-ART-STALE"
    record = caught.value.record
    assert record["result"] == "refused"
    assert record["bound"] is False
    assert record["source"] == HEAD
    assert record["fixture"] == str(artifact)
    assert b"FOREIGN-BODY-NOT-APPROVED" not in json.dumps(record).encode("utf-8")
    assert artifact.read_bytes() == body
    status = main(
        [
            "--workspace",
            str(workspace),
            "--job",
            JOB,
            "--source",
            HEAD,
            "--run-id",
            RUN_ID,
            "--run-attempt",
            ATTEMPT,
            "--artifact",
            str(artifact),
        ]
    )
    assert status == 1
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.ci.qsr_source_artifacts",
            "--workspace",
            str(workspace),
            "--job",
            JOB,
            "--source",
            HEAD,
            "--run-id",
            RUN_ID,
            "--run-attempt",
            ATTEMPT,
            "--artifact",
            str(artifact),
        ],
        cwd=root,
        check=False,
        capture_output=True,
    )
    assert completed.returncode == 1
    assert b"SRC03-ART-STALE" in completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["code"] == "SRC03-ART-STALE"
    assert payload["bound"] is False
    assert payload["result"] == "refused"
    assert b"FOREIGN-BODY-NOT-APPROVED" not in completed.stdout
    assert b"FOREIGN-BODY-NOT-APPROVED" not in completed.stderr
    assert artifact.read_bytes() == body


def test_bad_sidecar_is_stale_not_symlink_or_empty(tmp_path):
    """A nonempty regular artifact with an unbound sidecar stays stale."""
    workspace, output = _output(tmp_path)
    artifact = output / "podman-info.json"
    artifact.write_text("payload\n", encoding="utf-8")
    with pytest.raises(SourceArtifactError) as missing:
        _admit(workspace, artifact)
    assert missing.value.code == "SRC03-ART-STALE"
    sidecar = artifact.with_name(artifact.name + ".source.json")
    sidecar.symlink_to(artifact)
    with pytest.raises(SourceArtifactError) as linked:
        _admit(workspace, artifact)
    assert linked.value.code == "SRC03-ART-STALE"
    sidecar.unlink()
    sidecar.mkdir()
    with pytest.raises(SourceArtifactError) as folder:
        _admit(workspace, artifact)
    assert folder.value.code == "SRC03-ART-STALE"
    os.rmdir(sidecar)
    sidecar.write_text("", encoding="utf-8")
    with pytest.raises(SourceArtifactError) as empty:
        _admit(workspace, artifact)
    assert empty.value.code == "SRC03-ART-STALE"
    sidecar.write_text("x" * 129, encoding="utf-8")
    with pytest.raises(SourceArtifactError) as oversized:
        _admit(workspace, artifact)
    assert oversized.value.code == "SRC03-ART-STALE"
    sidecar.write_text("{", encoding="utf-8")
    with pytest.raises(SourceArtifactError) as broken:
        _admit(workspace, artifact)
    assert broken.value.code == "SRC03-ART-STALE"
    sidecar.write_bytes(b"\xff")
    with pytest.raises(SourceArtifactError) as binary:
        _admit(workspace, artifact)
    assert binary.value.code == "SRC03-ART-STALE"
    sidecar.unlink()
    other = output / "extra.json"
    other.write_text("y", encoding="utf-8")
    os.link(other, sidecar)
    with pytest.raises(SourceArtifactError) as hard:
        _admit(workspace, artifact)
    assert hard.value.code == "SRC03-ART-STALE"


def test_symlink_output_and_parent_are_not_followed(tmp_path):
    """A symlink output or parent is refused without reading through it."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    paths = bind_source_run_paths(
        workspace, job=JOB, source=HEAD, run_id=RUN_ID, run_attempt=ATTEMPT
    )
    real = tmp_path / "real-output"
    real.mkdir()
    paths["output"].parent.mkdir(parents=True)
    paths["output"].symlink_to(real, target_is_directory=True)
    escaped = real / "podman-info.json"
    escaped.write_text(SENTINEL, encoding="utf-8")
    with pytest.raises(SourceArtifactError) as output_link:
        _admit(workspace, escaped)
    assert output_link.value.code == "SRC03-ART-STALE"
    assert SENTINEL not in json.dumps(output_link.value.record)
    paths["output"].unlink()
    paths["output"].mkdir()
    alias = tmp_path / "alias-output"
    alias.symlink_to(paths["output"], target_is_directory=True)
    artifact = alias / "podman-info.json"
    artifact.write_text("payload\n", encoding="utf-8")
    _bind(artifact, HEAD)
    with pytest.raises(SourceArtifactError) as parent_link:
        _admit(workspace, artifact)
    assert parent_link.value.code == "SRC03-ART-STALE"


def test_unprepared_output_is_stale(tmp_path):
    """An artifact cannot bind when this source output directory is absent."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(SourceArtifactError) as caught:
        _admit(workspace, workspace / "podman-info.json")
    assert caught.value.code == "SRC03-ART-STALE"


def test_entrypoint_records_each_fixture_against_the_target_source(tmp_path):
    """The module entrypoint records refusal or admission for each fixture."""
    workspace, output = _output(tmp_path)
    bound = output / "podman-info.json"
    bound.write_text('{"ok":true}\n', encoding="utf-8")
    _bind(bound, HEAD)
    stale = output / "stale.json"
    stale.write_text("old\n", encoding="utf-8")
    _bind(stale, OTHER)
    empty = output / "empty.json"
    empty.write_bytes(b"")
    sentinel = tmp_path / "sentinel.txt"
    sentinel.write_text(SENTINEL, encoding="utf-8")
    link = output / "link.json"
    link.symlink_to(sentinel)
    record = tmp_path / "admission.jsonl"
    root = Path(__file__).resolve().parents[1]
    codes = []
    for artifact in (stale, link, empty, bound):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.ci.qsr_source_artifacts",
                "--workspace",
                str(workspace),
                "--job",
                JOB,
                "--source",
                HEAD,
                "--run-id",
                RUN_ID,
                "--run-attempt",
                ATTEMPT,
                "--artifact",
                str(artifact),
                "--record",
                str(record),
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        assert payload["source"] == HEAD
        assert payload["fixture"] == str(artifact)
        assert SENTINEL not in completed.stdout
        assert SENTINEL not in completed.stderr
        codes.append((payload["code"], completed.returncode))
    assert codes == [
        ("SRC03-ART-STALE", 1),
        ("SRC03-ART-SYMLINK", 1),
        ("SRC03-ART-EMPTY", 1),
        ("SRC03-ART-BOUND", 0),
    ]
    lines = [
        json.loads(line)
        for line in record.read_text(encoding="utf-8").splitlines()
    ]
    assert [line["fixture"] for line in lines] == [
        str(stale),
        str(link),
        str(empty),
        str(bound),
    ]
    assert {line["source"] for line in lines} == {HEAD}
    refused = main(
        [
            "--workspace",
            str(workspace),
            "--job",
            "Not A Job",
            "--source",
            HEAD,
            "--run-id",
            RUN_ID,
            "--run-attempt",
            ATTEMPT,
            "--artifact",
            str(bound),
        ]
    )
    assert refused == 1
    in_process = tmp_path / "in-process.jsonl"
    admitted = main(
        [
            "--workspace",
            str(workspace),
            "--job",
            JOB,
            "--source",
            HEAD,
            "--run-id",
            RUN_ID,
            "--run-attempt",
            ATTEMPT,
            "--artifact",
            str(bound),
            "--record",
            str(in_process),
        ]
    )
    assert admitted == 0
    denied = main(
        [
            "--workspace",
            str(workspace),
            "--job",
            JOB,
            "--source",
            HEAD,
            "--run-id",
            RUN_ID,
            "--run-attempt",
            ATTEMPT,
            "--artifact",
            str(empty),
        ]
    )
    assert denied == 1
    saved = json.loads(in_process.read_text(encoding="utf-8"))
    assert saved["fixture"] == str(bound)
    assert saved["source"] == HEAD


def test_identity_rejection_stays_on_the_path_contract(tmp_path):
    """Artifact admission uses the path contract identity checks."""
    workspace, output = _output(tmp_path)
    artifact = output / "podman-info.json"
    artifact.write_text("x", encoding="utf-8")
    with pytest.raises(SourceRunPathError):
        admit_source_artifact(
            workspace,
            artifact,
            job="../verify",
            source=HEAD,
            run_id=RUN_ID,
            run_attempt=ATTEMPT,
        )


def test_module_guard_returns_entrypoint_status(tmp_path, monkeypatch, capsys):
    """Running the module as __main__ uses the artifact entrypoint."""
    import runpy

    workspace, output = _output(tmp_path)
    artifact = output / "podman-info.json"
    artifact.write_text("x\n", encoding="utf-8")
    _bind(artifact, HEAD)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "qsr_source_artifacts",
            "--workspace",
            str(workspace),
            "--job",
            JOB,
            "--source",
            HEAD,
            "--run-id",
            RUN_ID,
            "--run-attempt",
            ATTEMPT,
            "--artifact",
            str(artifact),
        ],
    )
    with pytest.raises(SystemExit) as raised:
        runpy.run_module("scripts.ci.qsr_source_artifacts", run_name="__main__")
    assert raised.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["code"] == "SRC03-ART-BOUND"
    assert payload["fixture"] == str(artifact)
    assert payload["source"] == HEAD
