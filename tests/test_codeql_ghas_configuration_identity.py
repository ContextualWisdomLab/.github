"""Contract tests for GHAS CodeQL base/head configuration identity pairing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import codeql_ghas_configuration_identity as identity


def _analysis(
    *,
    commit_sha: str,
    category: str,
    analysis_key: str = identity.DEFAULT_SETUP_ANALYSIS_KEY,
    tool: str = "CodeQL",
) -> dict[str, Any]:
    """Build one code-scanning analysis fixture row."""
    return {
        "commit_sha": commit_sha,
        "category": category,
        "analysis_key": analysis_key,
        "tool": {"name": tool},
        "ref": "refs/heads/main",
    }


def test_default_setup_identity_matches_ghas_warning_title():
    """Default setup rust identity renders the way GHAS titles the #2133 warning."""
    item = identity.default_setup_identity("rust")
    assert item == (
        "dynamic/github-code-scanning/codeql:analyze",
        "/language:rust",
    )
    assert identity.format_identity(item) == "Default setup /language:rust"


def test_pairing_ready_when_base_and_head_share_default_setup_language():
    """Matching Default setup identities on exact base/head SHAs are continuous."""
    base_sha = "a" * 40
    head_sha = "b" * 40
    base = [
        _analysis(commit_sha=base_sha, category="/language:rust"),
        _analysis(commit_sha=base_sha, category="/language:actions"),
    ]
    head = [
        _analysis(commit_sha=head_sha, category="/language:rust"),
        _analysis(commit_sha=head_sha, category="/language:actions"),
    ]

    ready, missing = identity.pairing_ready(
        base,
        head,
        base_sha=base_sha,
        head_sha=head_sha,
        language="rust",
    )

    assert ready is True
    assert missing == []


def test_pairing_not_ready_when_head_missing_base_default_setup_language():
    """Negative case: base Default setup rust with no head match fails closed."""
    base_sha = "c" * 40
    head_sha = "d" * 40
    base = [
        _analysis(commit_sha=base_sha, category="/language:rust"),
        _analysis(commit_sha=base_sha, category="/language:actions"),
    ]
    # Head only published the fast actions shard — the #2133 race.
    head = [_analysis(commit_sha=head_sha, category="/language:actions")]

    ready, missing = identity.pairing_ready(
        base,
        head,
        base_sha=base_sha,
        head_sha=head_sha,
        language="rust",
    )

    assert ready is False
    assert missing == [identity.default_setup_identity("rust")]
    assert identity.format_identity(missing[0]) == "Default setup /language:rust"


def test_pairing_ignores_other_tools_and_unrelated_commits():
    """Non-CodeQL rows and other SHAs cannot satisfy or poison the contract."""
    base_sha = "e" * 40
    head_sha = "f" * 40
    base = [_analysis(commit_sha=base_sha, category="/language:rust")]
    head = [
        _analysis(commit_sha=head_sha, category="/language:rust", tool="Semgrep OSS"),
        _analysis(commit_sha="0" * 40, category="/language:rust"),
        _analysis(
            commit_sha=head_sha,
            category="/language:rust",
            analysis_key=".github/workflows/other.yml:analyze",
        ),
    ]

    ready, missing = identity.pairing_ready(
        base,
        head,
        base_sha=base_sha,
        head_sha=head_sha,
        language="rust",
    )

    assert ready is False
    assert missing == [identity.default_setup_identity("rust")]


def test_pairing_ready_when_base_has_no_language_configuration():
    """A language absent from the base does not demand a head configuration."""
    base_sha = "1" * 40
    head_sha = "2" * 40
    ready, missing = identity.pairing_ready(
        [_analysis(commit_sha=base_sha, category="/language:actions")],
        [],
        base_sha=base_sha,
        head_sha=head_sha,
        language="rust",
    )
    assert ready is True
    assert missing == []


def test_incompatible_analysis_keys_are_not_interchangeable():
    """Advanced-setup uploads do not satisfy a Default setup base identity."""
    base_sha = "3" * 40
    head_sha = "4" * 40
    base = [_analysis(commit_sha=base_sha, category="/language:rust")]
    head = [
        _analysis(
            commit_sha=head_sha,
            category="/language:rust",
            analysis_key=".github/workflows/codeql-scan-dispatch.yml:scan",
        )
    ]

    ready, missing = identity.pairing_ready(
        base,
        head,
        base_sha=base_sha,
        head_sha=head_sha,
        language="rust",
    )

    assert ready is False
    assert missing == [identity.default_setup_identity("rust")]


def test_wait_for_language_pairing_succeeds_after_retry(monkeypatch):
    """Bounded polling accepts a head identity that appears on a later attempt."""
    base_sha = "5" * 40
    head_sha = "6" * 40
    head_attempts = {"n": 0}
    sleeps: list[float] = []

    def fake_list(repository, *, token, ref=None, per_page=100, timeout_seconds=30):
        del repository, token, per_page, timeout_seconds
        if ref and ref.endswith("/main"):
            return [_analysis(commit_sha=base_sha, category="/language:rust")]
        head_attempts["n"] += 1
        if head_attempts["n"] == 1:
            return [_analysis(commit_sha=head_sha, category="/language:actions")]
        return [_analysis(commit_sha=head_sha, category="/language:rust")]

    monkeypatch.setattr(identity, "list_codeql_analyses", fake_list)

    missing = identity.wait_for_language_pairing(
        repository="ContextualWisdomLab/wardnet",
        token="opaque",
        base_ref="refs/heads/main",
        base_sha=base_sha,
        head_ref="refs/pull/129/head",
        head_sha=head_sha,
        language="rust",
        attempts=3,
        sleep_seconds=0.01,
        sleeper=sleeps.append,
    )

    assert missing == []
    assert sleeps == [0.01]
    assert head_attempts["n"] == 2


def test_wait_for_language_pairing_fails_closed_when_budget_exhausted(monkeypatch):
    """Exhausted polls raise with the rendered Default setup identity."""
    base_sha = "7" * 40
    head_sha = "8" * 40

    def fake_list(repository, *, token, ref=None, per_page=100, timeout_seconds=30):
        del repository, token, per_page, timeout_seconds
        if ref and "main" in ref:
            return [_analysis(commit_sha=base_sha, category="/language:rust")]
        return [_analysis(commit_sha=head_sha, category="/language:actions")]

    monkeypatch.setattr(identity, "list_codeql_analyses", fake_list)

    with pytest.raises(identity.ConfigurationIdentityError) as excinfo:
        identity.wait_for_language_pairing(
            repository="ContextualWisdomLab/wardnet",
            token="opaque",
            base_ref="refs/heads/main",
            base_sha=base_sha,
            head_ref="refs/pull/129/head",
            head_sha=head_sha,
            language="rust",
            attempts=2,
            sleep_seconds=0.0,
            sleeper=lambda _seconds: None,
        )

    assert "Default setup /language:rust" in str(excinfo.value)


def test_main_cli_returns_zero_when_pairing_is_ready(monkeypatch, capsys):
    """The handler CLI exits 0 only after continuity is proven."""
    base_sha = "9" * 40
    head_sha = "a" * 40

    def fake_wait(**kwargs):
        assert kwargs["language"] == "rust"
        return []

    monkeypatch.setenv("GH_TOKEN", "opaque")
    monkeypatch.setattr(identity, "wait_for_language_pairing", fake_wait)

    code = identity.main(
        [
            "--repository",
            "ContextualWisdomLab/wardnet",
            "--base-ref",
            "refs/heads/main",
            "--base-sha",
            base_sha,
            "--head-ref",
            "refs/pull/129/head",
            "--head-sha",
            head_sha,
            "--language",
            "rust",
            "--attempts",
            "1",
        ]
    )

    assert code == 0
    assert "configuration identity is continuous" in capsys.readouterr().out


def test_main_cli_returns_one_on_configuration_identity_error(monkeypatch, capsys):
    """CLI maps ConfigurationIdentityError to a fail-closed exit status."""
    monkeypatch.setenv("GH_TOKEN", "opaque")

    def fake_wait(**kwargs):
        del kwargs
        raise identity.ConfigurationIdentityError("Default setup /language:rust missing")

    monkeypatch.setattr(identity, "wait_for_language_pairing", fake_wait)

    code = identity.main(
        [
            "--repository",
            "ContextualWisdomLab/wardnet",
            "--base-ref",
            "refs/heads/main",
            "--base-sha",
            "b" * 40,
            "--head-ref",
            "refs/pull/1/head",
            "--head-sha",
            "c" * 40,
            "--language",
            "rust",
        ]
    )

    assert code == 1
    assert "Default setup /language:rust missing" in capsys.readouterr().err


def test_language_category_rejects_unsafe_tokens():
    """Category construction fails closed on empty or path-like language tokens."""
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.language_category("")
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.language_category("rust/../actions")


def test_fixture_roundtrip_json_shapes_match_github_analyses_api(tmp_path: Path):
    """Fixture files stay loadable as GitHub analyses API list payloads."""
    payload = [
        _analysis(commit_sha="d" * 40, category="/language:rust"),
        _analysis(commit_sha="e" * 40, category="/language:actions"),
    ]
    path = tmp_path / "analyses.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    ids = identity.iter_codeql_identities(loaded, commit_sha="d" * 40)
    assert ids == {identity.default_setup_identity("rust")}


def test_iter_codeql_identities_covers_string_tool_and_invalid_rows():
    """String tool names, non-mapping rows, and empty identities are skipped safely."""
    rows = [
        "not-a-mapping",
        {
            "commit_sha": "a" * 40,
            "category": "/language:rust",
            "analysis_key": identity.DEFAULT_SETUP_ANALYSIS_KEY,
            "tool": "CodeQL",
        },
        {
            "commit_sha": "a" * 40,
            "category": "/language:rust",
            "analysis_key": identity.DEFAULT_SETUP_ANALYSIS_KEY,
            "tool": 12,
        },
        {
            "commit_sha": "a" * 40,
            "category": "",
            "analysis_key": identity.DEFAULT_SETUP_ANALYSIS_KEY,
            "tool": {"name": "CodeQL"},
        },
        {
            "commit_sha": "b" * 40,
            "category": "/language:rust",
            "analysis_key": identity.DEFAULT_SETUP_ANALYSIS_KEY,
            "tool": {"name": "CodeQL"},
        },
    ]
    found = identity.iter_codeql_identities(rows, commit_sha="a" * 40)
    assert found == {identity.default_setup_identity("rust")}
    # No commit filter still accepts every well-formed CodeQL row.
    assert identity.default_setup_identity("rust") in identity.iter_codeql_identities(rows)


def test_missing_base_identities_without_language_filter_returns_all_gaps():
    """Omitting language keeps every unmatched base identity."""
    missing = identity.missing_base_identities(
        [
            identity.default_setup_identity("rust"),
            identity.default_setup_identity("actions"),
        ],
        [identity.default_setup_identity("actions")],
    )
    assert missing == [identity.default_setup_identity("rust")]


def test_format_identity_renders_advanced_setup_keys():
    """Non-default analysis keys keep their workflow identity in the warning text."""
    item = (
        ".github/workflows/codeql-scan-dispatch.yml:scan",
        "/language:rust",
    )
    assert (
        identity.format_identity(item)
        == ".github/workflows/codeql-scan-dispatch.yml:scan /language:rust"
    )


def test_configuration_identity_requires_both_fields():
    """Empty analysis_key or category fails closed."""
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.configuration_identity("", "/language:rust")
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.configuration_identity(identity.DEFAULT_SETUP_ANALYSIS_KEY, "")


def test_wait_rejects_non_positive_attempt_budget():
    """A zero attempt budget is a contract error, not a silent success."""
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.wait_for_language_pairing(
            repository="ContextualWisdomLab/wardnet",
            token="opaque",
            base_ref="refs/heads/main",
            base_sha="a" * 40,
            head_ref="refs/pull/1/head",
            head_sha="b" * 40,
            language="rust",
            attempts=0,
            sleep_seconds=0.0,
            sleeper=lambda _seconds: None,
        )


def test_list_codeql_analyses_and_request_json_paths(monkeypatch):
    """list_codeql_analyses validates inputs and decodes successful JSON lists."""

    class _Response:
        def read(self) -> bytes:
            return json.dumps(
                [_analysis(commit_sha="a" * 40, category="/language:rust")]
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

    def fake_open(request, timeout=30):
        del timeout
        assert "tool_name=CodeQL" in request.full_url
        assert "ref=refs%2Fheads%2Fmain" in request.full_url
        return _Response()

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", fake_open)
    rows = identity.list_codeql_analyses(
        "ContextualWisdomLab/wardnet",
        token="opaque",
        ref="refs/heads/main",
    )
    assert len(rows) == 1

    with pytest.raises(identity.ConfigurationIdentityError):
        identity.list_codeql_analyses("wardnet", token="opaque")
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.list_codeql_analyses("ContextualWisdomLab/wardnet", token="")


def test_request_json_maps_http_and_transport_failures(monkeypatch):
    """HTTP and transport failures become ConfigurationIdentityError."""

    class _HTTPError(identity.urllib.error.HTTPError):
        def read(self) -> bytes:
            return b"denied"

    def raise_http(request, timeout=30):
        del request, timeout
        raise _HTTPError("https://api.github.com/x", 403, "forbidden", hdrs=None, fp=None)

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", raise_http)
    with pytest.raises(identity.ConfigurationIdentityError) as excinfo:
        identity._request_json("https://api.github.com/x", token="t", timeout_seconds=1)
    assert "HTTP 403" in str(excinfo.value)

    def raise_url(request, timeout=30):
        del request, timeout
        raise identity.urllib.error.URLError("down")

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", raise_url)
    with pytest.raises(identity.ConfigurationIdentityError):
        identity._request_json("https://api.github.com/x", token="t", timeout_seconds=1)


def test_request_json_rejects_empty_and_invalid_payloads(monkeypatch):
    """Empty bodies decode to [] and invalid JSON fails closed."""

    class _Empty:
        def read(self) -> bytes:
            return b"   "

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

    monkeypatch.setattr(
        identity._GITHUB_API_OPENER,
        "open",
        lambda request, timeout=30: _Empty(),
    )
    assert identity._request_json("https://api.github.com/x", token="t", timeout_seconds=1) == []

    class _Bad:
        def read(self) -> bytes:
            return b"{not-json"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

    monkeypatch.setattr(
        identity._GITHUB_API_OPENER,
        "open",
        lambda request, timeout=30: _Bad(),
    )
    with pytest.raises(identity.ConfigurationIdentityError):
        identity._request_json("https://api.github.com/x", token="t", timeout_seconds=1)


def test_list_codeql_analyses_rejects_non_list_payload(monkeypatch):
    """A non-list analyses response fails closed."""
    monkeypatch.setattr(identity, "_request_json", lambda url, token, timeout_seconds: {"ok": True})
    with pytest.raises(identity.ConfigurationIdentityError):
        identity.list_codeql_analyses("ContextualWisdomLab/wardnet", token="opaque")


def test_request_json_rejects_non_github_https_urls(monkeypatch):
    """urllib allowlist must fail closed before urlopen (Semgrep/Bandit Medium)."""
    import scripts.ci.codeql_ghas_configuration_identity as mod
    calls = []
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **k: calls.append((a, k)))
    with pytest.raises(mod.ConfigurationIdentityError, match="api.github.com"):
        mod._request_json("http://evil.example/x", token="t", timeout_seconds=1)
    with pytest.raises(mod.ConfigurationIdentityError, match="api.github.com"):
        mod._request_json("https://evil.example/x", token="t", timeout_seconds=1)
    assert calls == []

