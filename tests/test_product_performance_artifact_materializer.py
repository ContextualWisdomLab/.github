"""Unit contracts for bounded inert product-performance artifact materialization."""

from __future__ import annotations

import io
import stat
import zipfile
from pathlib import Path

import pytest

from scripts.ci import materialize_product_performance_artifact as materializer


def _write_archive(path: Path, members: dict[str, bytes]) -> None:
    """Write one deterministic deflated ZIP fixture."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)


def _valid_members() -> dict[str, bytes]:
    """Return the canonical three-member evidence fixture."""
    return {
        "result.json": b'{"metrics":{"p95_ms":12.3}}',
        "runtime.json": b'{"runner":"k6"}',
        "fixture.json": b'{"records":[1]}',
    }


def test_materialize_exact_three_file_archive(tmp_path: Path) -> None:
    """Extract only the three expected root-level files into a new private directory."""
    archive = tmp_path / "evidence.zip"
    _write_archive(archive, _valid_members())
    output = tmp_path / "sealed-evidence"

    manifest = materializer.materialize(
        archive,
        output,
        result_filename="result.json",
        runtime_filename="runtime.json",
        fixture_filename="fixture.json",
    )

    assert sorted(path.name for path in output.iterdir()) == [
        "fixture.json",
        "result.json",
        "runtime.json",
    ]
    assert (output / "result.json").read_bytes() == _valid_members()["result.json"]
    assert manifest["member_count"] == 3
    assert manifest["total_uncompressed_bytes"] == sum(
        len(value) for value in _valid_members().values()
    )


@pytest.mark.parametrize(
    "name",
    ["../result.json", "nested/result.json", "nested\\result.json", ".", "..", ""],
)
def test_safe_filename_rejects_path_syntax(name: str) -> None:
    """Reject traversal, nesting, and empty evidence member names."""
    with pytest.raises(materializer.MaterializationError, match="root-level filename"):
        materializer._safe_filename(name, "result filename")


def test_materialize_rejects_extra_or_missing_member(tmp_path: Path) -> None:
    """Require exact cardinality and exact expected names."""
    archive = tmp_path / "evidence.zip"
    members = _valid_members()
    members["extra.json"] = b"{}"
    _write_archive(archive, members)

    with pytest.raises(materializer.MaterializationError, match="cardinality mismatch"):
        materializer.materialize(
            archive,
            tmp_path / "output-extra",
            result_filename="result.json",
            runtime_filename="runtime.json",
            fixture_filename="fixture.json",
        )

    archive.unlink()
    members.pop("extra.json")
    members.pop("runtime.json")
    _write_archive(archive, members)
    with pytest.raises(materializer.MaterializationError, match="cardinality mismatch"):
        materializer.materialize(
            archive,
            tmp_path / "output-missing",
            result_filename="result.json",
            runtime_filename="runtime.json",
            fixture_filename="fixture.json",
        )


def test_materialize_rejects_duplicate_member_names(tmp_path: Path) -> None:
    """Reject ZIP central directories that repeat an evidence name."""
    archive = tmp_path / "evidence.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("result.json", b"{}")
        bundle.writestr("result.json", b'{"replacement":true}')
        bundle.writestr("runtime.json", b"{}")
        bundle.writestr("fixture.json", b"{}")

    with pytest.raises(materializer.MaterializationError, match="duplicate"):
        materializer.materialize(
            archive,
            tmp_path / "output",
            result_filename="result.json",
            runtime_filename="runtime.json",
            fixture_filename="fixture.json",
        )


def test_materialize_rejects_symlink_member(tmp_path: Path) -> None:
    """Reject a UNIX symlink entry rather than materializing its payload."""
    archive = tmp_path / "evidence.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        symlink = zipfile.ZipInfo("result.json")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(symlink, b"runtime.json")
        bundle.writestr("runtime.json", b"{}")
        bundle.writestr("fixture.json", b"{}")

    with pytest.raises(materializer.MaterializationError, match="regular file"):
        materializer.materialize(
            archive,
            tmp_path / "output",
            result_filename="result.json",
            runtime_filename="runtime.json",
            fixture_filename="fixture.json",
        )


def test_materialize_rejects_unsupported_compression(tmp_path: Path) -> None:
    """Reject compression algorithms outside stored and deflated ZIP members."""
    archive = tmp_path / "evidence.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_BZIP2) as bundle:
        for name, payload in _valid_members().items():
            bundle.writestr(name, payload)

    with pytest.raises(materializer.MaterializationError, match="compression"):
        materializer.materialize(
            archive,
            tmp_path / "output",
            result_filename="result.json",
            runtime_filename="runtime.json",
            fixture_filename="fixture.json",
        )


def test_materialize_rejects_declared_member_over_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject an oversized member from central-directory metadata before extraction."""
    archive = tmp_path / "evidence.zip"
    _write_archive(archive, _valid_members())
    monkeypatch.setattr(materializer, "_MAX_RESULT_BYTES", 1)

    with pytest.raises(materializer.MaterializationError, match="declared size"):
        materializer.materialize(
            archive,
            tmp_path / "output",
            result_filename="result.json",
            runtime_filename="runtime.json",
            fixture_filename="fixture.json",
        )


def test_stream_member_rejects_runtime_overrun_and_removes_partial_file(tmp_path: Path) -> None:
    """Enforce byte counters during decompression rather than trusting declared metadata alone."""
    destination = tmp_path / "result.json"

    with pytest.raises(materializer.MaterializationError, match="exceeded"):
        materializer._stream_member(
            io.BytesIO(b"abcd"), destination, maximum_bytes=3, expected_size=4
        )

    assert not destination.exists()


def test_stream_member_rejects_declared_size_mismatch(tmp_path: Path) -> None:
    """Reject decompressed byte counts that disagree with the ZIP central directory."""
    destination = tmp_path / "result.json"

    with pytest.raises(materializer.MaterializationError, match="size mismatch"):
        materializer._stream_member(
            io.BytesIO(b"abc"), destination, maximum_bytes=10, expected_size=2
        )

    assert not destination.exists()


def test_materialize_rejects_existing_output_directory(tmp_path: Path) -> None:
    """Never merge trusted evidence into a pre-existing filesystem tree."""
    archive = tmp_path / "evidence.zip"
    _write_archive(archive, _valid_members())
    output = tmp_path / "sealed-evidence"
    output.mkdir()

    with pytest.raises(materializer.MaterializationError, match="must not already exist"):
        materializer.materialize(
            archive,
            output,
            result_filename="result.json",
            runtime_filename="runtime.json",
            fixture_filename="fixture.json",
        )


def test_materialize_rejects_non_zip_and_cleans_output(tmp_path: Path) -> None:
    """Convert malformed archives into a stable fail-closed error without residual output."""
    archive = tmp_path / "evidence.zip"
    archive.write_bytes(b"not a zip")
    output = tmp_path / "sealed-evidence"

    with pytest.raises(materializer.MaterializationError, match="valid ZIP"):
        materializer.materialize(
            archive,
            output,
            result_filename="result.json",
            runtime_filename="runtime.json",
            fixture_filename="fixture.json",
        )

    assert not output.exists()


def test_materialize_rejects_archive_over_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retain a local archive-size guard in addition to the workflow transfer bound."""
    archive = tmp_path / "evidence.zip"
    _write_archive(archive, _valid_members())
    monkeypatch.setattr(materializer, "_MAX_ARCHIVE_BYTES", 1)

    with pytest.raises(materializer.MaterializationError, match="archive exceeds"):
        materializer.materialize(
            archive,
            tmp_path / "output",
            result_filename="result.json",
            runtime_filename="runtime.json",
            fixture_filename="fixture.json",
        )


def test_main_reports_materialization_error_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Expose deterministic invalid-artifact rejection through the CLI boundary."""
    parser = type(
        "P",
        (),
        {
            "parse_args": lambda self: type(
                "A",
                (),
                {
                    "archive": str(tmp_path / "missing.zip"),
                    "output_dir": str(tmp_path / "output"),
                    "result_filename": "result.json",
                    "runtime_evidence_filename": "runtime.json",
                    "fixture_filename": "fixture.json",
                },
            )()
        },
    )()
    monkeypatch.setattr(materializer, "_parser", lambda: parser)

    assert materializer.main() == 2
    assert "performance artifact rejected" in capsys.readouterr().err
