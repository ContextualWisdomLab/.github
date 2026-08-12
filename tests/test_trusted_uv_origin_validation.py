"""Regression tests for the trusted Astral uv response-origin boundary."""

from __future__ import annotations

import pytest

from scripts.ci import materialize_base_python_requirements as materializer


def test_trusted_uv_origin_accepts_explicit_https_default_port() -> None:
    """An explicit HTTPS port 443 remains inside the fixed trusted origin."""

    materializer._verify_trusted_uv_origin(
        "https://releases.astral.sh:443/github/uv/releases/download/0.12.1/"
        "uv-x86_64-unknown-linux-gnu.tar.gz"
    )


@pytest.mark.parametrize(
    "response_url",
    [
        "https://releases.astral.sh:444/uv.tar.gz",
        "https://releases.astral.sh:not-a-port/uv.tar.gz",
    ],
)
def test_trusted_uv_origin_rejects_nondefault_and_malformed_ports(
    response_url: str,
) -> None:
    """Nondefault and malformed ports fail closed with the stable boundary error."""

    with pytest.raises(RuntimeError, match="redirected outside"):
        materializer._verify_trusted_uv_origin(response_url)
