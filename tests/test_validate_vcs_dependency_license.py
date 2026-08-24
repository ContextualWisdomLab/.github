"""Contract tests for exact-revision VCS dependency license validation."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
from types import ModuleType

import pytest


SCRIPT = Path("scripts/ci/validate_vcs_dependency_license.py")
COMMIT = "61c49c50d3b4a24fc9bd7c6d3a7f2f4ba19d7be6"


def load_validator() -> ModuleType:
    """Load the production validator only after proving the file exists."""
    assert SCRIPT.is_file(), "the exact-revision VCS license validator is missing"
    spec = importlib.util.spec_from_file_location("validate_vcs_dependency_license", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse(io.BytesIO):
    """Minimal urllib response fixture with a stable final URL."""

    def __init__(self, payload: dict[str, object], url: str) -> None:
        super().__init__(json.dumps(payload).encode("utf-8"))
        self._url = url

    def geturl(self) -> str:
        """Return the final response URL exposed by urllib."""
        return self._url

    def __enter__(self) -> "FakeResponse":
        """Support the response context-manager protocol."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Close the in-memory response."""
        self.close()


class FakeOpener:
    """Capture one outbound license request and return fixture metadata."""

    def __init__(self, spdx_id: str | None, *, final_url: str | None = None) -> None:
        self.spdx_id = spdx_id
        self.final_url = final_url
        self.request_url = ""

    def open(self, request: object, timeout: int) -> FakeResponse:
        """Return one bounded GitHub license response fixture."""
        del timeout
        self.request_url = request.full_url  # type: ignore[attr-defined]
        payload = {"license": {"spdx_id": self.spdx_id}}
        return FakeResponse(payload, self.final_url or self.request_url)


class RawOpener:
    """Return arbitrary response bytes for malformed and oversized fixtures."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def open(self, request: object, timeout: int) -> FakeResponse:
        """Return the raw payload from the otherwise exact request URL."""
        del timeout
        response = FakeResponse({}, request.full_url)  # type: ignore[attr-defined]
        response.seek(0)
        response.truncate()
        response.write(self.payload)
        response.seek(0)
        return response


@pytest.mark.parametrize(
    "spdx_id",
    [
        "MIT",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "MPL-2.0",
        "PostgreSQL",
    ],
)
def test_permitted_exact_spdx_identifiers_pass(spdx_id: str) -> None:
    """Every explicitly governed commercial/permissive SPDX ID passes."""
    validator = load_validator()
    opener = FakeOpener(spdx_id)

    assert validator.validate_license("RankWeave", COMMIT, opener=opener) == spdx_id
    assert opener.request_url == (
        "https://api.github.com/repos/ContextualWisdomLab/RankWeave/"
        f"license?ref={COMMIT}"
    )


@pytest.mark.parametrize(
    "spdx_id",
    ["GPL-3.0-only", "AGPL-3.0-or-later", "LGPL-2.1-only", "NOASSERTION", None],
)
def test_disallowed_or_unknown_spdx_identifiers_fail_closed(
    spdx_id: str | None,
) -> None:
    """Copyleft, unknown, and absent metadata never enter the trusted image."""
    validator = load_validator()

    with pytest.raises(ValueError, match="not permitted"):
        validator.validate_license("RankWeave", COMMIT, opener=FakeOpener(spdx_id))


def test_repository_and_commit_are_bounded_before_network_access() -> None:
    """Untrusted path syntax cannot steer the fixed GitHub API origin."""
    validator = load_validator()
    opener = FakeOpener("MIT")

    with pytest.raises(ValueError, match="repository"):
        validator.validate_license("../outside", COMMIT, opener=opener)
    with pytest.raises(ValueError, match="commit"):
        validator.validate_license("RankWeave", "main", opener=opener)

    assert opener.request_url == ""


def test_redirected_license_metadata_is_rejected() -> None:
    """A redirect cannot substitute a different origin for GitHub metadata."""
    validator = load_validator()
    opener = FakeOpener("MIT", final_url="https://attacker.invalid/license.json")

    with pytest.raises(RuntimeError, match="origin"):
        validator.validate_license("RankWeave", COMMIT, opener=opener)


def test_default_opener_disables_proxy_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production requests use the no-proxy opener instead of runner proxy state."""
    validator = load_validator()
    opener = FakeOpener("MIT")
    captured: list[object] = []

    def build_opener(*handlers: object) -> FakeOpener:
        captured.extend(handlers)
        return opener

    monkeypatch.setattr(validator.urllib.request, "build_opener", build_opener)

    assert validator.validate_license("RankWeave", COMMIT) == "MIT"
    assert len(captured) == 2
    assert isinstance(captured[0], validator.urllib.request.ProxyHandler)
    assert isinstance(captured[1], validator.RejectRedirectHandler)


def test_default_opener_rejects_redirect_before_following_target() -> None:
    """Production metadata requests never contact a redirect destination."""
    validator = load_validator()
    handler = validator.RejectRedirectHandler()

    with pytest.raises(RuntimeError, match="redirect"):
        handler.redirect_request(
            object(),
            object(),
            302,
            "Found",
            {},
            "https://attacker.invalid/license.json",
        )


def test_oversized_and_malformed_metadata_fail_closed() -> None:
    """The metadata parser rejects both resource abuse and invalid JSON."""
    validator = load_validator()

    with pytest.raises(RuntimeError, match="size limit"):
        validator.validate_license(
            "RankWeave",
            COMMIT,
            opener=RawOpener(b"x" * (validator.MAX_METADATA_BYTES + 1)),
        )
    with pytest.raises(ValueError, match="malformed"):
        validator.validate_license(
            "RankWeave", COMMIT, opener=RawOpener(b"not-json")
        )


def test_main_reports_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI prints a permitted ID and converts validation errors to exit 1."""
    validator = load_validator()
    arguments = ["--repository", "RankWeave", "--commit", COMMIT]

    monkeypatch.setattr(validator, "validate_license", lambda *_args: "Apache-2.0")
    assert validator.main(arguments) == 0
    assert capsys.readouterr().out == "Apache-2.0\n"

    def reject(*_args: object) -> str:
        raise ValueError("fixture denial")

    monkeypatch.setattr(validator, "validate_license", reject)
    assert validator.main(arguments) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "VCS dependency license validation failed: fixture denial" in captured.err
