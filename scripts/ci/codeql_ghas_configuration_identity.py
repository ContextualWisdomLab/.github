#!/usr/bin/env python3
"""Prove GHAS CodeQL base/head configuration identity continuity.

GitHub Advanced Security computes PR-introduced alerts by pairing each CodeQL
configuration present on the protected base with the same identity on the PR
head. A Default setup baseline such as ``Default setup /language:rust`` is the
tuple ``(dynamic/github-code-scanning/codeql:analyze, /language:rust)``. When
the head is missing that identity, GHAS reports a neutral
``configuration not found`` result even if a central dispatch scan already
passed (ContextualWisdomLab/.github#2133).

This module is the executable contract for that pairing rule. It never uploads
SARIF, never disables Default setup, and never synthesizes a status: callers
supply authenticated analysis payloads and receive a fail-closed verdict.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_SETUP_ANALYSIS_KEY = "dynamic/github-code-scanning/codeql:analyze"
CODEQL_TOOL_NAME = "CodeQL"


class ConfigurationIdentityError(RuntimeError):
    """Report a fail-closed GHAS configuration-identity contract failure."""


def language_category(language: str) -> str:
    """Return the CodeQL category string GHAS uses for one language."""
    normalized = str(language or "").strip().lower()
    if not normalized:
        raise ConfigurationIdentityError("language is required for a GHAS category")
    if any(ch.isspace() for ch in normalized) or "/" in normalized:
        raise ConfigurationIdentityError(f"language is not a safe CodeQL category token: {language!r}")
    return f"/language:{normalized}"


def configuration_identity(analysis_key: str, category: str) -> tuple[str, str]:
    """Normalize one GHAS configuration identity as ``(analysis_key, category)``."""
    key = str(analysis_key or "").strip()
    cat = str(category or "").strip()
    if not key or not cat:
        raise ConfigurationIdentityError("analysis_key and category are both required")
    return key, cat


def default_setup_identity(language: str) -> tuple[str, str]:
    """Return the Default setup identity GHAS shows as ``Default setup /language:X``."""
    return configuration_identity(DEFAULT_SETUP_ANALYSIS_KEY, language_category(language))


def iter_codeql_identities(
    analyses: Sequence[Mapping[str, Any]],
    *,
    commit_sha: str | None = None,
) -> set[tuple[str, str]]:
    """Collect CodeQL ``(analysis_key, category)`` identities from analysis payloads.

    When ``commit_sha`` is set, only analyses bound to that exact commit are
    kept. Non-mapping rows and non-CodeQL tools are ignored.
    """
    wanted = str(commit_sha or "").strip().lower() or None
    found: set[tuple[str, str]] = set()
    for row in analyses:
        if not isinstance(row, Mapping):
            continue
        tool = row.get("tool")
        tool_name = ""
        if isinstance(tool, Mapping):
            tool_name = str(tool.get("name") or "")
        elif isinstance(tool, str):
            tool_name = tool
        if tool_name != CODEQL_TOOL_NAME:
            continue
        if wanted is not None:
            sha = str(row.get("commit_sha") or "").strip().lower()
            if sha != wanted:
                continue
        try:
            found.add(
                configuration_identity(
                    str(row.get("analysis_key") or ""),
                    str(row.get("category") or ""),
                )
            )
        except ConfigurationIdentityError:
            continue
    return found


def missing_base_identities(
    base_identities: Iterable[tuple[str, str]],
    head_identities: Iterable[tuple[str, str]],
    *,
    language: str | None = None,
) -> list[tuple[str, str]]:
    """Return base identities absent from the head, optionally limited to one language."""
    base_set = {configuration_identity(*item) for item in base_identities}
    head_set = {configuration_identity(*item) for item in head_identities}
    missing = base_set - head_set
    if language is not None:
        category = language_category(language)
        missing = {item for item in missing if item[1] == category}
    return sorted(missing)


def pairing_ready(
    base_analyses: Sequence[Mapping[str, Any]],
    head_analyses: Sequence[Mapping[str, Any]],
    *,
    base_sha: str,
    head_sha: str,
    language: str,
) -> tuple[bool, list[tuple[str, str]]]:
    """Return whether GHAS can pair base/head CodeQL identities for ``language``."""
    base_ids = iter_codeql_identities(base_analyses, commit_sha=base_sha)
    head_ids = iter_codeql_identities(head_analyses, commit_sha=head_sha)
    category = language_category(language)
    base_for_language = {item for item in base_ids if item[1] == category}
    if not base_for_language:
        # No base configuration for this language means GHAS will not demand one
        # on the head for introduced-alert computation of that language.
        return True, []
    missing = missing_base_identities(base_for_language, head_ids, language=language)
    return not missing, missing


def format_identity(identity: tuple[str, str]) -> str:
    """Render one identity the way GHAS titles Default setup warnings."""
    analysis_key, category = identity
    if analysis_key == DEFAULT_SETUP_ANALYSIS_KEY:
        return f"Default setup {category}"
    return f"{analysis_key} {category}"


def _require_github_api_https_url(url: str) -> str:
    """Reject non-HTTPS and non-api.github.com URLs before urllib opens them."""
    parsed = urllib.parse.urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationIdentityError(
            "GitHub API URL must be https://api.github.com/... without credentials"
        ) from exc
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname != "api.github.com"
        or port not in (None, 443)
        or parsed.params
        or parsed.fragment
    ):
        raise ConfigurationIdentityError(
            "GitHub API URL must be https://api.github.com/... without credentials"
        )
    return url


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Refuse redirects so Authorization never follows off api.github.com."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        """Raise HTTPError instead of following the redirect."""
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def _open_github_api(request: urllib.request.Request, *, timeout: float) -> Any:
    """Open a pre-validated GitHub API request without following redirects."""
    return urllib.request.build_opener(_NoRedirectHandler()).open(  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected  # nosec B310
        request,
        timeout=timeout,
    )


def _request_json(url: str, *, token: str, timeout_seconds: int) -> Any:
    """GET one GitHub REST URL and decode JSON, or raise ConfigurationIdentityError."""
    safe_url = _require_github_api_https_url(url)
    request = urllib.request.Request(
        safe_url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "cwl-codeql-ghas-configuration-identity",
        },
        method="GET",
    )
    try:
        with _open_github_api(request, timeout=timeout_seconds) as response:
            payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[-400:]
        raise ConfigurationIdentityError(
            f"GitHub API GET failed with HTTP {exc.code}: {body}"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ConfigurationIdentityError(
            f"GitHub API transport failed: {type(exc).__name__}"
        ) from exc
    if not payload.strip():
        return []
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ConfigurationIdentityError("GitHub API returned invalid JSON") from exc


def list_codeql_analyses(
    repository: str,
    *,
    token: str,
    ref: str | None = None,
    per_page: int = 100,
    timeout_seconds: int = 30,
) -> list[dict[str, Any]]:
    """List code-scanning analyses for a repository, optionally filtered by ref."""
    if not repository or "/" not in repository:
        raise ConfigurationIdentityError("repository must be owner/name")
    if not token:
        raise ConfigurationIdentityError("token is required to list analyses")
    params: dict[str, str] = {"per_page": str(per_page), "tool_name": CODEQL_TOOL_NAME}
    if ref:
        params["ref"] = ref
    query = urllib.parse.urlencode(params)
    url = f"https://api.github.com/repos/{repository}/code-scanning/analyses?{query}"
    payload = _request_json(url, token=token, timeout_seconds=timeout_seconds)
    if not isinstance(payload, list):
        raise ConfigurationIdentityError("code-scanning analyses response was not a list")
    return [row for row in payload if isinstance(row, dict)]


def wait_for_language_pairing(
    *,
    repository: str,
    token: str,
    base_ref: str,
    base_sha: str,
    head_ref: str,
    head_sha: str,
    language: str,
    attempts: int = 30,
    sleep_seconds: float = 20.0,
    sleeper: Any = time.sleep,
) -> list[tuple[str, str]]:
    """Poll until the head carries every base CodeQL identity for ``language``.

    Returns the empty list on success. Raises ConfigurationIdentityError when
    the budget is exhausted with identities still missing.
    """
    if attempts < 1:
        raise ConfigurationIdentityError("attempts must be at least 1")
    last_missing: list[tuple[str, str]] = []
    for attempt in range(1, attempts + 1):
        base_analyses = list_codeql_analyses(repository, token=token, ref=base_ref)
        head_analyses = list_codeql_analyses(repository, token=token, ref=head_ref)
        ready, missing = pairing_ready(
            base_analyses,
            head_analyses,
            base_sha=base_sha,
            head_sha=head_sha,
            language=language,
        )
        if ready:
            return []
        last_missing = missing
        rendered = ", ".join(format_identity(item) for item in missing) or "<unknown>"
        print(
            f"GHAS configuration identity not yet continuous for {language} "
            f"(attempt {attempt}/{attempts}): missing {rendered}",
            file=sys.stderr,
        )
        if attempt < attempts:
            sleeper(sleep_seconds)
    rendered = ", ".join(format_identity(item) for item in last_missing) or "<unknown>"
    raise ConfigurationIdentityError(
        "GHAS cannot pair base/head CodeQL configuration identities for "
        f"{language}; missing on head: {rendered}"
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser used by the CodeQL scan-dispatch handler."""
    parser = argparse.ArgumentParser(
        description=(
            "Fail closed unless the PR head publishes every protected-base "
            "CodeQL configuration identity for one language."
        )
    )
    parser.add_argument("--repository", required=True, help="owner/name target repository")
    parser.add_argument("--base-ref", required=True, help="protected base ref, e.g. refs/heads/main")
    parser.add_argument("--base-sha", required=True, help="exact protected base SHA")
    parser.add_argument("--head-ref", required=True, help="PR head ref, e.g. refs/pull/1/head")
    parser.add_argument("--head-sha", required=True, help="exact PR head SHA")
    parser.add_argument("--language", required=True, help="CodeQL language token, e.g. rust")
    parser.add_argument(
        "--attempts",
        type=int,
        default=int(os.environ.get("GHAS_CONFIG_IDENTITY_ATTEMPTS", "30")),
        help="bounded poll attempts while Default setup finishes slower languages",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=float(os.environ.get("GHAS_CONFIG_IDENTITY_SLEEP_SECONDS", "20")),
        help="delay between poll attempts in seconds",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry: wait for GHAS base/head identity continuity, then exit 0/1."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    token = str(os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    try:
        wait_for_language_pairing(
            repository=args.repository,
            token=token,
            base_ref=args.base_ref,
            base_sha=args.base_sha,
            head_ref=args.head_ref,
            head_sha=args.head_sha,
            language=args.language,
            attempts=args.attempts,
            sleep_seconds=args.sleep_seconds,
        )
    except ConfigurationIdentityError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    print(
        "GHAS CodeQL configuration identity is continuous for "
        f"{args.language} on {args.repository} "
        f"(base={args.base_sha[:12]} head={args.head_sha[:12]})."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through ``main`` tests
    raise SystemExit(main())
