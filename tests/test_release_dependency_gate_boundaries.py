"""Exercise the release gate's filesystem and archive trust boundaries."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import tarfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import pytest

from scripts.ci import release_dependency_gate as gate
from tests.test_release_dependency_fanout_plan import CONTROL, _allowed
from tests.test_release_dependency_gate import _fixture_archive, build_capture


class _ArchiveStream:
    """Minimal descriptor-backed stream for bounded archive-read tests."""

    def __init__(self, payload: object) -> None:
        self.payload = payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def fileno(self) -> int:
        return 7

    def read(self, _size: int) -> object:
        return self.payload


class _OversizedPayload:
    """Report one byte beyond the archive bound without allocating 256 MiB."""

    def __len__(self) -> int:
        return 256 * 1024 * 1024 + 1


@pytest.mark.parametrize(
    ("mode", "payload", "message"),
    [
        (stat.S_IFIFO, b"", "not a regular file"),
        (stat.S_IFREG, _OversizedPayload(), "exceeds the bounded read"),
    ],
)
def test_archive_snapshot_refuses_nonregular_and_oversized_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: int,
    payload: object,
    message: str,
) -> None:
    """Descriptor validation must reject devices and archives above the hard bound."""
    monkeypatch.setattr(gate.os, "open", lambda *_args: 7)
    monkeypatch.setattr(gate.os, "fdopen", lambda *_args: _ArchiveStream(payload))
    monkeypatch.setattr(gate.os, "fstat", lambda _fd: SimpleNamespace(st_mode=mode))

    with pytest.raises(gate.GateError, match=message):
        gate.read_archive_snapshot(tmp_path / "source.archive")


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    """Build one in-memory wheel-like archive."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("declared", "code"),
    [
        ("../LICENSE", gate.ARCHIVE_PATH_ESCAPE),
        ("ABSENT", gate.CAPTURE_INCOMPLETE),
    ],
)
def test_python_declared_license_path_must_be_safe_and_present(
    declared: str, code: str
) -> None:
    """Wheel metadata cannot redirect licence reads outside the immutable archive."""
    raw = _zip_bytes(
        {
            "green-1.0.dist-info/METADATA": (
                f"Metadata-Version: 2.4\nName: green\nVersion: 1.0\nLicense-File: {declared}\n"
            ).encode(),
            "LICENSE": b"MIT License",
        }
    )
    with pytest.raises(gate.GateError) as error:
        gate.archive_license_evidence(raw, "pypi")
    assert error.value.code == code


def test_archive_symlink_member_is_refused() -> None:
    """A ZIP symlink must never be interpreted as licence evidence."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        link = zipfile.ZipInfo("LICENSE")
        link.external_attr = stat.S_IFLNK << 16
        archive.writestr(link, "target")
    with pytest.raises(gate.GateError) as error:
        gate.archive_license_evidence(buffer.getvalue(), "pypi")
    assert error.value.code == gate.ARCHIVE_PATH_ESCAPE


def test_cargo_declared_license_path_must_stay_inside_package() -> None:
    """Cargo's ``license-file`` cannot traverse out of the crate archive."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        payload = b'[package]\nname="green"\nversion="1.0"\nlicense-file="../LICENSE"\n'
        member = tarfile.TarInfo("green-1.0/Cargo.toml")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    with pytest.raises(gate.GateError) as error:
        gate.archive_license_evidence(buffer.getvalue(), "cargo")
    assert error.value.code == gate.ARCHIVE_PATH_ESCAPE


def test_archive_member_and_total_license_bounds_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-member and aggregate licence text limits are independently enforced."""
    raw = _zip_bytes({"LICENSE": b"MIT", "NOTICE": b"notice"})
    monkeypatch.setattr(gate, "_MAX_METADATA_BYTES", 2)
    with pytest.raises(gate.GateError, match="oversized"):
        gate.archive_license_evidence(raw, "pypi")

    monkeypatch.setattr(gate, "_MAX_METADATA_BYTES", 1024)
    monkeypatch.setattr(gate, "_MAX_JSON_BYTES", 4)
    with pytest.raises(gate.GateError, match="text set exceeds"):
        gate.archive_license_evidence(raw, "pypi")


def test_archive_decode_and_member_count_fail_closed() -> None:
    """Invalid UTF-8 and archive bombs with excessive member counts are refused."""
    with pytest.raises(gate.GateError, match="cannot be decoded"):
        gate.archive_license_evidence(_zip_bytes({"LICENSE": b"\xff"}), "pypi")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for index in range(10001):
            archive.writestr(f"d{index}/", b"")
    with pytest.raises(gate.GateError, match="too many members"):
        gate.archive_license_evidence(buffer.getvalue(), "pypi")


def test_cargo_declared_license_member_must_exist() -> None:
    """A crate manifest cannot name licence evidence absent from its archive."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, payload in {
            "green-1.0/Cargo.toml": b'[package]\nname="green"\nversion="1.0"\nlicense-file="MISSING"\n',
            "other-1.0/Cargo.toml": b'[package]\nname="other"\nversion="1.0"\n',
        }.items():
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    with pytest.raises(gate.GateError, match="declared license member is absent"):
        gate.archive_license_evidence(buffer.getvalue(), "cargo")


def test_archive_directory_members_are_recorded_but_not_read_as_files() -> None:
    """Normal ZIP directories remain provenance rows without becoming text candidates."""
    evidence = gate.archive_license_evidence(
        _zip_bytes({"green/": b"", "green/LICENSE": b"MIT License"}), "pypi"
    )
    assert evidence["archive_members"] == [
        {"type": "directory", "name": "green/", "linkname": ""},
        {"type": "file", "name": "green/LICENSE", "linkname": ""},
    ]
    assert evidence["license_texts"] == {"green/LICENSE": "MIT License"}


@pytest.mark.parametrize(
    "metadata",
    [[], {"ecosystem": "npm", "name": "x", "version": "1"}],
)
def test_build_evidence_rejects_malformed_metadata(
    tmp_path: Path, metadata: object
) -> None:
    """Raw capture metadata must be an object for a supported ecosystem."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(gate.GateError):
        gate.build_evidence(raw)


def test_build_evidence_binds_the_recorded_archive_hash(tmp_path: Path) -> None:
    """The runner's digest cannot name bytes other than the archive read by the gate."""
    raw = tmp_path / "raw"
    raw.mkdir()
    snapshot = _fixture_archive({"LICENSE": "MIT License"}, "pypi")
    (raw / "metadata.json").write_text(
        json.dumps({"ecosystem": "pypi", "name": "green", "version": "1"}),
        encoding="utf-8",
    )
    (raw / "source.archive").write_bytes(snapshot)
    (raw / "source.sha256").write_text("0" * 64, encoding="utf-8")
    with pytest.raises(gate.GateError) as error:
        gate.build_evidence(raw)
    assert error.value.code == gate.SOURCE_HASH_MISMATCH


def test_capture_refuses_archive_destination_symlinks(tmp_path: Path) -> None:
    """Capture must not follow either the archive directory or per-package destination."""
    raw = tmp_path / "raw"
    raw.mkdir()
    capture = tmp_path / "capture"
    target = tmp_path / "target"
    target.mkdir()
    capture.mkdir()
    (capture / "archives").symlink_to(target, target_is_directory=True)
    with pytest.raises(gate.GateError, match="destination must not be a symlink"):
        gate.capture(raw, capture)


def test_capture_refuses_a_per_dependency_archive_symlink(tmp_path: Path) -> None:
    """A precreated package destination cannot redirect immutable archive bytes."""
    raw = tmp_path / "raw" / "one"
    raw.mkdir(parents=True)
    snapshot = _fixture_archive({"LICENSE": "MIT License"}, "pypi")
    (raw / "metadata.json").write_text(
        json.dumps({"ecosystem": "pypi", "name": "green", "version": "1"}),
        encoding="utf-8",
    )
    (raw / "source.archive").write_bytes(snapshot)
    (raw / "source.sha256").write_text(hashlib.sha256(snapshot).hexdigest(), encoding="utf-8")
    capture = tmp_path / "capture"
    archive_dir = capture / "archives"
    archive_dir.mkdir(parents=True)
    target = tmp_path / "target.archive"
    target.write_bytes(b"unchanged")
    (archive_dir / "pypi__green__1.archive").symlink_to(target)
    with pytest.raises(gate.GateError, match="destination must not be a symlink"):
        gate.capture(raw.parent, capture)
    assert target.read_bytes() == b"unchanged"


def test_cargo_workspace_root_must_be_absolute(tmp_path: Path) -> None:
    """Path dependencies can only be trusted relative to an absolute workspace root."""
    capture = build_capture(tmp_path)
    metadata_path = capture / "cargo" / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["workspace_root"] = "relative/workspace"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(gate.GateError, match="workspace root is invalid"):
        gate._enumerate_cargo(capture)


def test_gate_refuses_a_symlinked_archive_directory(tmp_path: Path) -> None:
    """Replacing the archive directory after capture becomes a recorded refusal."""
    capture = build_capture(tmp_path)
    archive_dir = capture / "archives"
    real_dir = capture / "real-archives"
    archive_dir.rename(real_dir)
    archive_dir.symlink_to(real_dir, target_is_directory=True)
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    assert any(
        failure.code == gate.CAPTURE_INCOMPLETE and "directory is a symlink" in failure.detail
        for failure in report.failures
    )


def test_fanout_refuses_malformed_objects_and_execution_identity(tmp_path: Path) -> None:
    """The matrix requires object evidence and positive exact execution identity."""
    capture, report_path = _allowed(tmp_path)
    report_path.write_text("[]", encoding="utf-8")
    with pytest.raises(gate.GateError, match="licence objects"):
        gate.strix_fanout_plan(capture, report_path, CONTROL, 1, 1)

    capture, report_path = _allowed(tmp_path / "identity")
    with pytest.raises(gate.GateError, match="execution identity"):
        gate.strix_fanout_plan(capture, report_path, "bad", 1, 1)


def test_fanout_refuses_unavailable_fixtures_and_malformed_rows(tmp_path: Path) -> None:
    """Fixture directories and dependency rows are validated before matrix creation."""
    capture, report_path = _allowed(tmp_path / "directory")
    fixtures = capture / "strix" / "fixtures"
    for child in fixtures.iterdir():
        child.unlink()
    fixtures.rmdir()
    with pytest.raises(gate.GateError, match="directory is unavailable"):
        gate.strix_fanout_plan(capture, report_path, CONTROL, 1, 1)

    capture, report_path = _allowed(tmp_path / "row")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["dependencies"] = ["not-an-object"]
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(gate.GateError, match="row is malformed"):
        gate.strix_fanout_plan(capture, report_path, CONTROL, 1, 1)


def test_fanout_refuses_unsafe_slugs_and_fixture_drift(tmp_path: Path) -> None:
    """Derived fixture names must be local and their digest must match the verdict."""
    capture, report_path = _allowed(tmp_path / "slug")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["dependencies"][0]["key"] = "."
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(gate.GateError, match="slug is unsafe"):
        gate.strix_fanout_plan(capture, report_path, CONTROL, 1, 1)

    capture, report_path = _allowed(tmp_path / "digest")
    digest_path = next((capture / "strix" / "fixtures").glob("*.sha256"))
    digest_path.write_text("0" * 64, encoding="utf-8")
    with pytest.raises(gate.GateError, match="fixture differs"):
        gate.strix_fanout_plan(capture, report_path, CONTROL, 1, 1)


def test_fanout_refuses_incomplete_and_malformed_runtime_reports(tmp_path: Path) -> None:
    """Runtime archive evidence must carry every typed, nonempty verdict set."""
    capture, report_path = _allowed(tmp_path)
    runtime = tmp_path / "runtime.json"
    runtime.write_text("{}", encoding="utf-8")
    with pytest.raises(gate.GateError, match="report is incomplete"):
        gate.strix_fanout_plan(capture, report_path, CONTROL, 1, 1, runtime)

    runtime.write_text(
        json.dumps(
            {
                "schema": "cwl.release-runtime-archive-licenses/3",
                "archives": ["malformed"],
                "build_packages": ["malformed"],
                "build_tools": ["malformed"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(gate.GateError, match="row is malformed"):
        gate.strix_fanout_plan(capture, report_path, CONTROL, 1, 1, runtime)


def test_fanout_refuses_an_existing_output_file(tmp_path: Path) -> None:
    """CLI output creation is exclusive so stale plans cannot be overwritten."""
    capture, report_path = _allowed(tmp_path)
    output = tmp_path / "plan.json"
    output.write_text("stale", encoding="utf-8")
    assert gate.main(
        [
            "fanout-plan",
            "--capture",
            str(capture),
            "--license-report",
            str(report_path),
            "--control-sha",
            CONTROL,
            "--run-id",
            "1",
            "--run-attempt",
            "1",
            "--output",
            str(output),
        ]
    ) == 2
    assert output.read_text(encoding="utf-8") == "stale"
