"""Static security contract for the pinned trusted-uv network boundary."""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_MATERIALIZER = _REPO_ROOT / "scripts" / "ci" / "materialize_base_python_requirements.py"
_EXPECTED_URL = (
    "https://releases.astral.sh/github/uv/releases/download/0.12.1/"
    "uv-x86_64-unknown-linux-gnu.tar.gz"
)


def _download_function_text() -> str:
    """Return only the trusted-uv download function source."""
    module_text = _MATERIALIZER.read_text(encoding="utf-8")
    return module_text.split(
        "def _download_trusted_uv_archive() -> bytes:", maxsplit=1
    )[1].split("def _verified_uv_binary", maxsplit=1)[0]


def test_urlopen_receives_one_literal_https_release_url() -> None:
    """Static analysis can prove repository or user data never selects the URL."""
    function_text = _download_function_text()

    assert "urllib.request.Request" not in function_text
    assert function_text.count("urllib.request.urlopen(") == 1
    assert '"https://releases.astral.sh/github/uv/releases/download/0.12.1/"' in function_text
    assert '"uv-x86_64-unknown-linux-gnu.tar.gz"' in function_text
    assert "TRUSTED_UV_ARCHIVE_URL" not in function_text


def test_literal_network_sink_matches_the_documented_release_constant() -> None:
    """The scanner-friendly literal cannot drift from the tested release identity."""
    module_text = _MATERIALIZER.read_text(encoding="utf-8")
    namespace: dict[str, object] = {}
    constant_block = module_text.split(
        "TRUSTED_UV_ARCHIVE_URL = (", maxsplit=1
    )[1].split(")", maxsplit=1)[0]

    exec("TRUSTED_UV_ARCHIVE_URL = (" + constant_block + ")", {}, namespace)

    assert namespace["TRUSTED_UV_ARCHIVE_URL"] == _EXPECTED_URL
    function_text = _download_function_text()
    assert _EXPECTED_URL == "".join(
        (
            "https://releases.astral.sh/github/uv/releases/download/0.12.1/",
            "uv-x86_64-unknown-linux-gnu.tar.gz",
        )
    )
    assert all(part in function_text for part in _EXPECTED_URL.rsplit("/", maxsplit=1))
