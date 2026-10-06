from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import runpy
import subprocess
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from scripts.ci import verify_release_distribution_set as distribution_set
from scripts.ci.verify_release_distribution_set import (
    DistributionSetError,
    verify_distribution_set,
)


SOURCE = "a" * 40
CONTROL = "b" * 40
RUN = 424242
ATTEMPT = 2
CREATED = "2026-09-26T12:01:00Z"
STARTED = "2026-09-26T12:00:00Z"


def _zip(members: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return output.getvalue()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _case() -> dict:
    rows = []
    archives = {}
    metadata = []
    record_lines = [
        f"# release v1.2.3 @ {SOURCE}, SOURCE_DATE_EPOCH=1",
        "target\tbyte_verified\tverification\tsha256\trebuild_sha256\tfile\tbuild_env",
    ]
    for index in range(1, 14):
        leg = "sdist" if index == 13 else f"target{index}-py3.12"
        filename = "pkg-1.2.3.tar.gz" if index == 13 else f"pkg-1.2.3-{index}.whl"
        name = "dist-sdist" if index == 13 else f"dist-wheel-{leg}"
        data = f"verified bytes for {leg}".encode()
        archive = _zip({filename: data})
        digest = "sha256:" + _sha(archive)
        archives[index] = archive
        metadata.append({"id": index, "name": name, "digest": digest,
                         "created_at": CREATED, "expired": False,
                         "workflow_run": {"id": RUN, "head_sha": CONTROL}})
        rows.append({"leg": leg, "file": filename, "sha256": _sha(data),
                     "artifact_id": index, "artifact_name": name,
                     "artifact_digest": digest})
        record_lines.append(f"{leg}\ttrue\tclean-target-repeat-same-env\t{_sha(data)}\t{_sha(data)}\t{filename}\trunner:x")
    manifest = {"schema_version": 1, "source_repository": "owner/repo",
                "source_sha": SOURCE, "control_sha": CONTROL, "run_id": RUN,
                "run_attempt": ATTEMPT, "distributions": rows}
    record = ("\n".join(record_lines) + "\n").encode()
    case = {"manifest": manifest, "record": record, "archives": archives,
            "metadata": metadata, "attempt": {"id": RUN, "run_attempt": ATTEMPT,
                                             "head_sha": CONTROL, "run_started_at": STARTED}}
    _repack_record(case)
    return case


def _repack_record(case: dict) -> None:
    archive = _zip({
        "reproducibility-record.tsv": case["record"],
        "release-scope-identities.json": b"[]\n",
        "release-scope-evidence-set.json": b"{}\n",
        "release-gate-distribution-set.json": (json.dumps(case["manifest"]) + "\n").encode(),
    })
    case["archives"][14] = archive
    entry = {"id": 14, "name": "reproducibility-record", "digest": "sha256:" + _sha(archive),
             "created_at": CREATED, "expired": False,
             "workflow_run": {"id": RUN, "head_sha": CONTROL}}
    case["metadata"] = [item for item in case["metadata"] if item["name"] != "reproducibility-record"] + [entry]


def _verify(case: dict, output: Path, *, wheel: str = "pkg-1.2.3-1.whl") -> list[dict]:
    record_digest = next(item["digest"] for item in case["metadata"] if item["name"] == "reproducibility-record")

    def fetch(repository: str, artifact_id: int, destination) -> None:
        assert repository == "owner/repo"
        destination.write(case["archives"][artifact_id])

    return verify_distribution_set(
        case["metadata"], case["attempt"], repository="owner/repo",
        source_sha=SOURCE, control_sha=CONTROL, run_id=RUN, run_attempt=ATTEMPT,
        record_artifact_id=14, record_artifact_digest=record_digest,
        wheel_filename=wheel, sdist_filename="pkg-1.2.3.tar.gz",
        fetch=fetch, output_dir=output,
    )


def test_verifies_all_thirteen_immutable_artifact_archives(tmp_path: Path) -> None:
    case = _case()
    verified = _verify(case, tmp_path / "dist")
    assert len(verified) == 13
    assert {path.name for path in (tmp_path / "dist").iterdir()} == {
        row["file"] for row in case["manifest"]["distributions"]
    }
    for row in verified:
        assert _sha((tmp_path / "dist" / row["file"]).read_bytes()) == row["sha256"]


def test_refuses_record_without_scope_evidence_set(tmp_path: Path) -> None:
    case = _case()
    with zipfile.ZipFile(io.BytesIO(case["archives"][14])) as original:
        members = {name: original.read(name) for name in original.namelist()
                   if name != "release-scope-evidence-set.json"}
    case["archives"][14] = _zip(members)
    case["metadata"][-1]["digest"] = "sha256:" + _sha(case["archives"][14])
    with pytest.raises(DistributionSetError, match="ZIP members differ"):
        _verify(case, tmp_path / "dist")


def test_cli_downloads_the_exact_ids_before_exposing_files(tmp_path: Path) -> None:
    case = _case()
    archives = tmp_path / "archives"
    archives.mkdir()
    for artifact_id, data in case["archives"].items():
        (archives / f"{artifact_id}.zip").write_bytes(data)
    metadata = tmp_path / "metadata.jsonl"
    metadata.write_text("".join(json.dumps(item) + "\n" for item in case["metadata"]))
    attempt = tmp_path / "attempt.json"
    attempt.write_text(json.dumps(case["attempt"]))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys\n"
        "path = sys.argv[2]\n"
        "sys.stdout.buffer.write((pathlib.Path(os.environ['FAKE_ARCHIVES']) / (path.split('/')[-2] + '.zip')).read_bytes())\n"
    )
    gh.chmod(0o755)
    script = Path(__file__).resolve().parents[1] / "scripts/ci/verify_release_distribution_set.py"
    record_digest = next(item["digest"] for item in case["metadata"] if item["name"] == "reproducibility-record")
    result = subprocess.run(
        [sys.executable, "-I", str(script), "--repository", "owner/repo",
         "--source-sha", SOURCE, "--control-sha", CONTROL,
         "--run-id", str(RUN), "--run-attempt", str(ATTEMPT),
         "--record-artifact-id", "14", "--record-artifact-digest", record_digest,
         "--wheel-filename", "pkg-1.2.3-1.whl", "--sdist-filename", "pkg-1.2.3.tar.gz",
         "--metadata", str(metadata), "--attempt", str(attempt),
         "--output", str(tmp_path / "dist")],
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}",
             "FAKE_ARCHIVES": str(archives)},
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)["verified_distributions"]) == 13
    assert len(list((tmp_path / "dist").iterdir())) == 13


def test_refuses_forged_missing_stale_and_tampered_sets(tmp_path: Path) -> None:
    def missing(case):
        case["manifest"]["distributions"].pop()
        _repack_record(case)

    def wrong_source(case):
        case["manifest"]["source_sha"] = "c" * 40
        _repack_record(case)

    def wrong_run(case):
        case["metadata"][0]["workflow_run"]["id"] = 1

    def earlier_attempt(case):
        case["metadata"][0]["created_at"] = "2026-09-26T11:59:59Z"

    def tampered_zip(case):
        case["archives"][1] = _zip({case["manifest"]["distributions"][0]["file"]: b"altered"})

    def tampered_inner(case):
        case["archives"][1] = _zip({case["manifest"]["distributions"][0]["file"]: b"altered"})
        digest = "sha256:" + _sha(case["archives"][1])
        case["metadata"][0]["digest"] = digest
        case["manifest"]["distributions"][0]["artifact_digest"] = digest
        _repack_record(case)

    def duplicate_id(case):
        case["manifest"]["distributions"][1]["artifact_id"] = 1
        _repack_record(case)

    def extra_artifact(case):
        case["metadata"].append({**copy.deepcopy(case["metadata"][0]), "id": 100,
                                 "name": "dist-wheel-extra"})

    def wrong_attempt(case):
        case["attempt"]["run_attempt"] = 1

    for name, mutate in (
        ("missing", missing), ("wrong-source", wrong_source),
        ("wrong-run", wrong_run), ("earlier-attempt", earlier_attempt),
        ("tampered-zip", tampered_zip), ("tampered-inner", tampered_inner),
        ("duplicate-id", duplicate_id),
        ("extra-artifact", extra_artifact), ("wrong-attempt", wrong_attempt),
    ):
        case = _case()
        mutate(case)
        output = tmp_path / name
        with pytest.raises(DistributionSetError):
            _verify(case, output)
        assert not output.exists(), name

    with pytest.raises(DistributionSetError, match="selected wheel/sdist"):
        _verify(_case(), tmp_path / "foreign-pair", wheel="../../outside.whl")
    assert not (tmp_path / "foreign-pair").exists()


def test_rejects_noncanonical_control_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for data, message in (
        (b'{"key": 1, "key": 2}', "duplicate JSON key"),
        (b'{"key": NaN}', "non-finite JSON value"),
        (b"\xff", "invalid control JSON"),
        (b"{", "invalid control JSON"),
    ):
        with pytest.raises(DistributionSetError, match=message):
            distribution_set._json_bytes(data)

    monkeypatch.setattr(distribution_set, "MAX_CONTROL_BYTES", 1)
    with pytest.raises(DistributionSetError, match="control JSON is too large"):
        distribution_set._json_bytes(b"{}")


def test_rejects_noncanonical_timestamps_and_digests(monkeypatch: pytest.MonkeyPatch) -> None:
    for value, message in (
        (None, "missing canonical UTC timestamp"),
        ("not-a-timeZ", "invalid UTC timestamp"),
    ):
        with pytest.raises(DistributionSetError, match=message):
            distribution_set._timestamp(value)

    real_datetime = distribution_set.datetime

    class NonUtcTimestamp:
        @staticmethod
        def fromisoformat(_value: str):
            return real_datetime.fromisoformat("2026-09-26T12:00:00+01:00")

    monkeypatch.setattr(distribution_set, "datetime", NonUtcTimestamp)
    with pytest.raises(DistributionSetError, match="timestamp is not UTC"):
        distribution_set._timestamp(STARTED)

    for value in (None, "sha256:short", "SHA256:" + "0" * 64):
        with pytest.raises(DistributionSetError, match="canonical artifact digest"):
            distribution_set._digest(value)


def test_rejects_oversized_or_changed_archives(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _zip({"member": b"payload"})

    def fetch(_repository: str, _artifact_id: int, output) -> None:
        output.write(data)

    monkeypatch.setattr(distribution_set, "MAX_ARCHIVE_BYTES", len(data) - 1)
    with pytest.raises(DistributionSetError, match="ZIP exceeds"):
        with distribution_set._archive("owner/repo", 1, "sha256:" + _sha(data), fetch):
            pass

    monkeypatch.setattr(distribution_set, "MAX_ARCHIVE_BYTES", len(data) + 1)
    with pytest.raises(DistributionSetError, match="digest mismatch"):
        with distribution_set._archive("owner/repo", 1, "sha256:" + "0" * 64, fetch):
            pass


def test_rejects_unsafe_archive_members(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("../escape", "directory/"):
        with zipfile.ZipFile(io.BytesIO(_zip({name: b"x"}))) as archive:
            with pytest.raises(DistributionSetError, match="unsafe or oversized"):
                distribution_set._members(archive, {name})

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        info = zipfile.ZipInfo("link")
        info.external_attr = (0o120777 << 16)
        archive.writestr(info, b"target")
    with zipfile.ZipFile(io.BytesIO(output.getvalue())) as archive:
        with pytest.raises(DistributionSetError, match="unsafe or oversized"):
            distribution_set._members(archive, {"link"})

    monkeypatch.setattr(distribution_set, "MAX_ARCHIVE_BYTES", 0)
    with zipfile.ZipFile(io.BytesIO(_zip({"member": b"x"}))) as archive:
        with pytest.raises(DistributionSetError, match="unsafe or oversized"):
            distribution_set._members(archive, {"member"})


def test_rejects_malformed_reproducibility_records(monkeypatch: pytest.MonkeyPatch) -> None:
    valid_header = (
        f"# release v1 @ {SOURCE}, SOURCE_DATE_EPOCH=1\n"
        "target\tbyte_verified\tverification\tsha256\trebuild_sha256\tfile\tbuild_env\n"
    )
    digest = "0" * 64
    valid_row = f"target\ttrue\tclean\t{digest}\t{digest}\tpkg.whl\trunner:x\n"

    for data, message in (
        (b"\xff", "invalid reproducibility record encoding"),
        (b"bad\nrecord\n", "not bound to the source"),
        ((valid_header + valid_row + "bad-row\n").encode(), "malformed record row"),
        ((valid_header + valid_row + valid_row).encode(), "duplicate"),
    ):
        with pytest.raises(DistributionSetError, match=message):
            distribution_set._record_rows(data, SOURCE)

    monkeypatch.setattr(distribution_set, "MAX_CONTROL_BYTES", 1)
    with pytest.raises(DistributionSetError, match="record is too large"):
        distribution_set._record_rows(b"xx", SOURCE)


def test_refuses_invalid_caller_and_artifact_metadata(tmp_path: Path) -> None:
    case = _case()
    digest = case["metadata"][-1]["digest"]

    def invoke(*, artifacts=case["metadata"], attempt=case["attempt"], repository="owner/repo",
               source_sha=SOURCE, control_sha=CONTROL, run_id=RUN, run_attempt=ATTEMPT):
        return verify_distribution_set(
            artifacts, attempt, repository=repository, source_sha=source_sha,
            control_sha=control_sha, run_id=run_id, run_attempt=run_attempt,
            record_artifact_id=14, record_artifact_digest=digest,
            wheel_filename="pkg-1.2.3-1.whl", sdist_filename="pkg-1.2.3.tar.gz",
            fetch=lambda _repository, artifact_id, output: output.write(case["archives"][artifact_id]),
            output_dir=tmp_path / "dist",
        )

    for overrides in (
        {"repository": "owner"}, {"source_sha": "bad"}, {"control_sha": "bad"},
        {"run_id": True}, {"run_id": 0}, {"run_attempt": True}, {"run_attempt": 0},
    ):
        with pytest.raises(DistributionSetError, match="invalid expected release identity"):
            invoke(**overrides)

    for attempt in (None, {**case["attempt"], "id": True},
                    {**case["attempt"], "id": 1},
                    {**case["attempt"], "run_attempt": True},
                    {**case["attempt"], "head_sha": "c" * 40}):
        with pytest.raises(DistributionSetError, match="attempt differs"):
            invoke(attempt=attempt)

    for artifacts, message in (
        ([None], "invalid artifact metadata"),
        ([{}], "invalid artifact metadata"),
        ([case["metadata"][0], copy.deepcopy(case["metadata"][0])], "duplicate artifact name"),
    ):
        with pytest.raises(DistributionSetError, match=message):
            invoke(artifacts=artifacts)

    for artifact_id in (True, 0):
        with pytest.raises(DistributionSetError, match="missing immutable artifact identity"):
            distribution_set._artifact(
                {}, "missing", artifact_id, "sha256:" + "0" * 64,
                RUN, CONTROL, distribution_set._timestamp(STARTED),
            )


def test_refuses_malformed_manifest_rows_and_existing_output(tmp_path: Path) -> None:
    def rejects(case: dict, name: str, message: str) -> None:
        _repack_record(case)
        with pytest.raises(DistributionSetError, match=message):
            _verify(case, tmp_path / name)

    case = _case()
    case["manifest"]["unexpected"] = True
    rejects(case, "shape", "unknown shape")

    case = _case()
    case["manifest"]["schema_version"] = True
    rejects(case, "identity", "differs from the caller identity")

    case = _case()
    case["manifest"]["distributions"] = "not-a-list"
    rejects(case, "rows", "lacks wheel/sdist coverage")

    case = _case()
    case["manifest"]["distributions"][0] = {"leg": "missing-fields"}
    rejects(case, "row-shape", "invalid distribution row shape")

    case = _case()
    case["manifest"]["distributions"][0]["leg"] = "bad/name"
    rejects(case, "row-identity", "malformed distribution identity")

    case = _case()
    case["record"] = case["record"].replace(b"pkg-1.2.3-1.whl", b"other-1.2.3-1.whl")
    rejects(case, "record-mismatch", "differs from reproducibility record")

    case = _case()
    output = tmp_path / "already-exists"
    output.mkdir()
    with pytest.raises(DistributionSetError, match="output already exists"):
        _verify(case, output)


def test_refuses_member_stream_larger_than_its_validated_metadata(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case()
    real_members = distribution_set._members

    class Member:
        filename = case["manifest"]["distributions"][0]["file"]
        file_size = 1

    class ExpandedArchive:
        @staticmethod
        def open(_member):
            return io.BytesIO(b"expanded")

    @contextmanager
    def archive(_repository, artifact_id, _digest, _fetch):
        if artifact_id == 14:
            with zipfile.ZipFile(io.BytesIO(case["archives"][14])) as record_archive:
                yield record_archive
            return
        assert artifact_id == 1
        yield ExpandedArchive()

    def members(archive_value, expected):
        if isinstance(archive_value, ExpandedArchive):
            member = Member()
            return {member.filename: member}
        return real_members(archive_value, expected)

    monkeypatch.setattr(distribution_set, "_archive", archive)
    monkeypatch.setattr(distribution_set, "_members", members)
    monkeypatch.setattr(distribution_set, "MAX_ARCHIVE_BYTES", 1)

    with pytest.raises(DistributionSetError, match="member exceeds the size limit"):
        _verify(case, tmp_path / "dist")


def test_fetch_artifact_fails_closed_and_closes_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    class Process:
        def __init__(self, data: bytes, returncode: int = 0, *, running: bool = False):
            self.stdout = io.BytesIO(data)
            self.returncode = returncode
            self.running = running
            self.killed = False

        def wait(self):
            self.running = False
            return self.returncode

        def poll(self):
            return None if self.running else self.returncode

        def kill(self):
            self.killed = True
            self.running = False

    processes: list[Process] = []

    def popen(_args, stdout, **kwargs):
        assert stdout is subprocess.PIPE
        process = processes.pop(0)
        return process

    monkeypatch.setattr(distribution_set.subprocess, "Popen", popen)

    success = Process(b"payload")
    processes.append(success)
    output = io.BytesIO()
    distribution_set.fetch_artifact("owner/repo", 1, output)
    assert output.getvalue() == b"payload"
    assert success.stdout.closed

    failed = Process(b"", returncode=1)
    processes.append(failed)
    with pytest.raises(DistributionSetError, match="download failed"):
        distribution_set.fetch_artifact("owner/repo", 2, io.BytesIO())
    assert failed.stdout.closed

    oversized = Process(b"xx", running=True)
    processes.append(oversized)
    monkeypatch.setattr(distribution_set, "MAX_ARCHIVE_BYTES", 1)
    with pytest.raises(DistributionSetError, match="exceeds the size limit"):
        distribution_set.fetch_artifact("owner/repo", 3, io.BytesIO())
    assert oversized.killed
    assert oversized.stdout.closed


def test_main_reads_control_files_and_emits_verified_set(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    case = _case()
    metadata = tmp_path / "metadata.jsonl"
    metadata.write_text("".join(json.dumps(item) + "\n" for item in case["metadata"]))
    attempt = tmp_path / "attempt.json"
    attempt.write_text(json.dumps(case["attempt"]))
    record_digest = case["metadata"][-1]["digest"]
    monkeypatch.setattr(
        distribution_set,
        "fetch_artifact",
        lambda _repository, artifact_id, output: output.write(case["archives"][artifact_id]),
    )
    monkeypatch.setattr(sys, "argv", [
        "verify_release_distribution_set.py", "--repository", "owner/repo",
        "--source-sha", SOURCE, "--control-sha", CONTROL,
        "--run-id", str(RUN), "--run-attempt", str(ATTEMPT),
        "--record-artifact-id", "14", "--record-artifact-digest", record_digest,
        "--wheel-filename", "pkg-1.2.3-1.whl", "--sdist-filename", "pkg-1.2.3.tar.gz",
        "--metadata", str(metadata), "--attempt", str(attempt),
        "--output", str(tmp_path / "dist"),
    ])

    distribution_set.main()

    assert len(json.loads(capsys.readouterr().out)["verified_distributions"]) == 13


def test_module_entrypoint_executes_the_same_verified_path(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    case = _case()
    metadata = tmp_path / "metadata.jsonl"
    metadata.write_text("".join(json.dumps(item) + "\n" for item in case["metadata"]))
    attempt = tmp_path / "attempt.json"
    attempt.write_text(json.dumps(case["attempt"]))
    record_digest = case["metadata"][-1]["digest"]
    script = Path(__file__).resolve().parents[1] / "scripts/ci/verify_release_distribution_set.py"

    class Process:
        def __init__(self, data: bytes):
            self.stdout = io.BytesIO(data)

        @staticmethod
        def wait() -> int:
            return 0

        @staticmethod
        def poll() -> int:
            return 0

    def popen(args, stdout, **kwargs):
        assert stdout is subprocess.PIPE
        artifact_id = int(args[2].split("/")[-2])
        return Process(case["archives"][artifact_id])

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(sys, "argv", [
        str(script), "--repository", "owner/repo",
        "--source-sha", SOURCE, "--control-sha", CONTROL,
        "--run-id", str(RUN), "--run-attempt", str(ATTEMPT),
        "--record-artifact-id", "14", "--record-artifact-digest", record_digest,
        "--wheel-filename", "pkg-1.2.3-1.whl", "--sdist-filename", "pkg-1.2.3.tar.gz",
        "--metadata", str(metadata), "--attempt", str(attempt),
        "--output", str(tmp_path / "dist"),
    ])

    runpy.run_path(str(script), run_name="__main__")

    assert len(json.loads(capsys.readouterr().out)["verified_distributions"]) == 13
