"""Fail-closed GitHub REST authority contracts for central CI HTTP clients."""

from __future__ import annotations

from email.message import Message
from io import BytesIO
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.request import Request
from urllib.response import addinfourl

import pytest

from scripts.ci import codeql_ghas_configuration_identity as identity
from scripts.ci import strix_evidence_binding as binding


UNTRUSTED_GITHUB_API_URLS = (
    "http://api.github.com/repos/ContextualWisdomLab/example",
    "https://api.github.com.evil.example/repos/ContextualWisdomLab/example",
    "https://api.github.com@evil.example/repos/ContextualWisdomLab/example",
    "https://api.github.com:443/repos/ContextualWisdomLab/example",
    "https://api.github.com/repos/ContextualWisdomLab/example#fragment",
    "https://[api.github.com/repos/ContextualWisdomLab/example",
    "file:///etc/passwd",
)
REDIRECT_TARGETS = (
    "https://api.github.com/repos/ContextualWisdomLab/redirected",
    "https://api.github.com.evil.example/repos/ContextualWisdomLab/example",
    "http://api.github.com/repos/ContextualWisdomLab/example",
    "file:///etc/passwd",
)
CANONICAL_GITHUB_API_URL = "https://api.github.com/repos/ContextualWisdomLab/example"
G17_ROW_PREFIX = "| G-17 |"
FULL_COMMIT_SHA = re.compile(r"`([0-9a-f]{40})`")


class _SyntheticRedirectTransport:
    """Return one synthetic 302 while recording every request reaching transport."""

    def __init__(self, target: str) -> None:
        """Store the redirect target and initialize the observed request ledger."""
        self.target = target
        self.calls: list[tuple[str, str | None]] = []

    def https_open(self, request: Request) -> Any:
        """Return a synthetic redirect response without contacting a network target."""
        self.calls.append((request.full_url, request.get_header("Authorization")))
        headers = Message()
        headers["Location"] = self.target
        response = addinfourl(BytesIO(b""), headers, request.full_url, code=302)
        response.msg = "Found"
        return response


class _JsonResponse:
    """Minimal context-managed JSON response for opener-boundary contracts."""

    def __enter__(self) -> _JsonResponse:
        """Enter the fake response context."""
        return self

    def __exit__(self, *_args: Any) -> None:
        """Leave the fake response context without suppressing exceptions."""
        return None

    def read(self) -> bytes:
        """Return an empty JSON array payload."""
        return b"[]"


def _unexpected_open(*_args: Any, **_kwargs: Any) -> Any:
    """Fail if a rejected authority reaches the network/file opener boundary."""
    pytest.fail("rejected GitHub API authority reached opener")


def _assert_g17_evidence_is_published(baseline: str) -> None:
    """Require every full G-17 evidence SHA to resolve in current published ancestry."""
    rows = [line for line in baseline.splitlines() if line.startswith(G17_ROW_PREFIX)]
    assert len(rows) == 1, "G-17 must have exactly one gap-register row"
    evidence_shas = FULL_COMMIT_SHA.findall(rows[0])
    assert evidence_shas, "G-17 must name full commit evidence"

    repository_root = Path(__file__).resolve().parents[1]
    for evidence_sha in evidence_shas:
        resolvable = subprocess.run(
            ["git", "cat-file", "-e", f"{evidence_sha}^{{commit}}"],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
        )
        assert resolvable.returncode == 0, f"G-17 evidence {evidence_sha} is not published"

        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", evidence_sha, "HEAD"],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
        )
        assert ancestor.returncode == 0, (
            f"G-17 evidence {evidence_sha} is not published in current HEAD ancestry"
        )


@pytest.mark.parametrize("url", UNTRUSTED_GITHUB_API_URLS)
def test_codeql_identity_client_rejects_noncanonical_github_api_authority(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """CodeQL GHAS reads must reject non-HTTPS or non-api.github.com authorities."""
    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", _unexpected_open)

    with pytest.raises(identity.ConfigurationIdentityError, match="GitHub API URL"):
        identity._request_json(url, token="test-token", timeout_seconds=1)


@pytest.mark.parametrize("url", UNTRUSTED_GITHUB_API_URLS)
def test_strix_evidence_client_rejects_noncanonical_github_api_authority(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """Strix evidence reads must reject non-HTTPS or non-api.github.com authorities."""
    monkeypatch.setattr(binding._GITHUB_API_OPENER, "open", _unexpected_open)

    with pytest.raises(binding.EvidenceBindingError, match="GitHub API URL"):
        binding.default_github_opener(url, "test-token")


@pytest.mark.parametrize("target", REDIRECT_TARGETS)
@pytest.mark.parametrize("client", ("codeql", "strix"))
def test_production_openers_reject_redirect_without_forwarding_bearer(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    client: str,
) -> None:
    """Drive a synthetic 302 through each actual opener and forbid a second request."""
    if client == "codeql":
        opener = identity._GITHUB_API_OPENER
        call = lambda: identity._request_json(
            CANONICAL_GITHUB_API_URL,
            token="test-token",
            timeout_seconds=1,
        )
        error_type = identity.ConfigurationIdentityError
    else:
        opener = binding._GITHUB_API_OPENER
        call = lambda: binding.default_github_opener(
            CANONICAL_GITHUB_API_URL,
            "test-token",
        )
        error_type = binding.EvidenceBindingError

    transport = _SyntheticRedirectTransport(target)
    monkeypatch.setitem(
        opener.handle_open,
        "https",
        [transport, *opener.handle_open["https"]],
    )

    with pytest.raises(error_type, match="HTTP 302"):
        call()

    assert transport.calls == [
        (CANONICAL_GITHUB_API_URL, "Bearer test-token"),
    ]


@pytest.mark.parametrize("target", REDIRECT_TARGETS)
def test_codeql_identity_client_never_constructs_redirect_request_with_bearer_token(
    target: str,
) -> None:
    """A GitHub response must not redirect CodeQL credentials to another URL."""
    request = Request(
        CANONICAL_GITHUB_API_URL,
        headers={"Authorization": "Bearer test-token"},
    )
    handler = identity._RejectRedirects()

    from urllib.error import HTTPError
    with pytest.raises(HTTPError, match="HTTP Error 302: Found"):
        handler.redirect_request(request, None, 302, "Found", {}, target)

    assert request.get_header("Authorization") == "Bearer test-token"


@pytest.mark.parametrize("target", REDIRECT_TARGETS)
def test_strix_evidence_client_never_constructs_redirect_request_with_bearer_token(
    target: str,
) -> None:
    """A GitHub response must not redirect Strix credentials to another URL."""
    request = Request(
        CANONICAL_GITHUB_API_URL,
        headers={"Authorization": "Bearer test-token"},
    )
    handler = binding._RejectRedirects()

    from urllib.error import HTTPError
    with pytest.raises(HTTPError, match="HTTP Error 302: Found"):
        handler.redirect_request(request, None, 302, "Found", {}, target)

    assert request.get_header("Authorization") == "Bearer test-token"


def test_canonical_github_api_authority_reaches_both_openers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact HTTPS GitHub REST authority remains an allowed production control."""
    identity_calls: list[str] = []
    strix_calls: list[str] = []

    def identity_open(request: Any, **_kwargs: Any) -> _JsonResponse:
        """Record the CodeQL client's validated request URL."""
        identity_calls.append(request.full_url)
        return _JsonResponse()

    def strix_open(request: Any, **_kwargs: Any) -> _JsonResponse:
        """Record the Strix client's validated request URL."""
        strix_calls.append(request.full_url)
        return _JsonResponse()

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", identity_open)
    monkeypatch.setattr(binding._GITHUB_API_OPENER, "open", strix_open)

    assert identity._request_json(
        CANONICAL_GITHUB_API_URL,
        token="test-token",
        timeout_seconds=1,
    ) == []
    assert binding.default_github_opener(CANONICAL_GITHUB_API_URL, "test-token") == []
    assert identity_calls == [CANONICAL_GITHUB_API_URL]
    assert strix_calls == [CANONICAL_GITHUB_API_URL]


def test_documented_opener_lineage_references_published_commits() -> None:
    """Owner evidence must name the published commits that carry each repair."""
    doctoring = Path(
        "docs/doctoring/github-api-url-authority-2248.md"
    ).read_text(encoding="utf-8")
    baseline = Path("docs/product-technical-gap-baseline.md").read_text(
        encoding="utf-8"
    )
    evidence = doctoring + baseline

    assert "57477289ebec5631b0c48f0bc419f336dbe19deb" in doctoring
    assert "663ffac390d27ab21daa58b91b624d3f00dce7de" in baseline
    assert "9c19c6e00eafc028068719ab482282c1256f8893" in baseline
    assert "b35410673ce60f9a693532daf74862c08971e9e3" not in evidence
    assert "72e17608cac2d673b50b8380301649fb86d18096" not in evidence
    _assert_g17_evidence_is_published(baseline)


def test_published_lineage_guard_rejects_unreachable_g17_evidence() -> None:
    """A commit-shaped but unpublished G-17 evidence identifier must fail closed."""
    baseline = Path("docs/product-technical-gap-baseline.md").read_text(
        encoding="utf-8"
    )
    mutated = baseline.replace(
        "57477289ebec5631b0c48f0bc419f336dbe19deb",
        "0000000000000000000000000000000000000000",
        1,
    )

    with pytest.raises(AssertionError, match="not published"):
        _assert_g17_evidence_is_published(mutated)


def test_doctoring_qualifies_foreign_semgrep_revision_owner() -> None:
    """Foreign evidence must identify its repository instead of resembling a local SHA."""
    doctoring = Path(
        "docs/doctoring/github-api-url-authority-2248.md"
    ).read_text(encoding="utf-8")
    revision = "40b8c63f75dc7c22c8a77482d73bfb864b146f7e"
    expected_link = (
        f"[semgrep/semgrep-rules revision `{revision}`]"
        f"(https://github.com/semgrep/semgrep-rules/commit/{revision})"
    )

    assert expected_link in doctoring
