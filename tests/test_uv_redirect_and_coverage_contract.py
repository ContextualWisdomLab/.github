"""Regression contracts for the trusted uv origin and coverage evidence."""

from __future__ import annotations

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib
from pathlib import Path

import pytest

from scripts.ci import materialize_base_python_requirements as materializer
from tests.conftest import FakeHttpResponse


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "https://github.com:444/astral-sh/uv/releases/download/0.12.1/uv.tar.gz",
        "https://github.com:not-a-port/astral-sh/uv/releases/download/0.12.1/uv.tar.gz",
        "https://release-assets.githubusercontent.com:444/github-production-release-asset/1/file",
    ],
)
def test_trusted_uv_download_rejects_nondefault_or_malformed_ports(
    monkeypatch: pytest.MonkeyPatch,
    unsafe_url: str,
) -> None:
    """The pinned GitHub release origin cannot land on another or malformed port."""

    response = FakeHttpResponse(unsafe_url)
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: response,
    )

    with pytest.raises(RuntimeError, match="redirected outside"):
        materializer._download_trusted_uv_archive()


@pytest.mark.parametrize(
    "trusted_url",
    [
        "https://github.com:443/astral-sh/uv/releases/download/0.12.1/uv-x86_64-unknown-linux-gnu.tar.gz",
        "https://release-assets.githubusercontent.com:443/github-production-release-asset/1/file",
        "https://objects.githubusercontent.com:443/github-production-release-asset/1/file",
    ],
)
def test_trusted_uv_download_accepts_explicit_default_https_port(
    monkeypatch: pytest.MonkeyPatch,
    trusted_url: str,
) -> None:
    """An explicit port 443 still denotes a fixed trusted HTTPS origin."""

    response = FakeHttpResponse(trusted_url)
    monkeypatch.setattr(
        materializer.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: response,
    )

    assert materializer._download_trusted_uv_archive() == b"archive"


def test_repository_coverage_contract_enforces_branches_at_one_hundred_percent() -> None:
    """The declared 100% quality gate measures branch as well as statement coverage."""

    repository_root = Path(__file__).resolve().parents[1]
    configuration = tomllib.loads(
        (repository_root / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert configuration["tool"]["coverage"]["run"]["branch"] is True
    assert configuration["tool"]["coverage"]["report"]["fail_under"] == 100
