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

