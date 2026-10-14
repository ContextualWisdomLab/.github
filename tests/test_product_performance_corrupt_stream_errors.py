"""Regressions for corrupt ZIP stream failures at the performance-artifact boundary."""

from __future__ import annotations

import zipfile
import zlib
from pathlib import Path

import pytest

from scripts.ci import materialize_product_performance_artifact as materializer


def _archive(path: Path) -> None:
    """Write the exact three-member archive required to reach streaming."""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("result.json", b"{}")
        bundle.writestr("runtime.json", b"{}")
        bundle.writestr("fixture.json", b"{}")


@pytest.mark.parametrize(
    "stream_error",
    [zlib.error("invalid deflate stream"), EOFError("truncated compressed stream")],
)
def test_materialize_normalizes_zip_stream_failures_and_cleans_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stream_error: BaseException,
) -> None:
    """Keep decompressor failures inside the deterministic MaterializationError boundary."""
    archive = tmp_path / "evidence.zip"
    output = tmp_path / "sealed-evidence"
    _archive(archive)

    def fail_stream(*args: object, **kwargs: object) -> int:
        """Model failures propagated by ZipExtFile.read after metadata validation."""
        del args, kwargs
        raise stream_error

    monkeypatch.setattr(materializer, "_stream_member", fail_stream)

    with pytest.raises(materializer.MaterializationError, match="member data is corrupted"):
        materializer.materialize(
            archive,
            output,
            result_filename="result.json",
            runtime_filename="runtime.json",
            fixture_filename="fixture.json",
        )

    assert not output.exists()
