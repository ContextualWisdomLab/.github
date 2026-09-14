#!/usr/bin/env python3
"""Enforce the CWL Pingora-only edge runtime policy on pull-request changes.

The checker never executes pull-request content. It reads changed-file metadata and
bounded UTF-8 file content through the GitHub REST API, then rejects active Nginx
runtime artifacts while allowing documentation, license text, and source-level
negative test fixtures.

Issue #2193 -- declared research/data artifact paths: a consumer repository may
declare literal path prefixes (``ARTIFACT_PATH_DECLARATION_PATH``) that hold
binary research or data artefacts not shaped like documentation (raw response
workbooks, SPSS ``.sav`` files, serialized model objects, compressed numeric
arrays). That declaration is resolved *only* from the pull request's base ref,
never its head, so a pull request cannot self-authorize admission of its own
binary by adding or widening the declaration in the same diff -- see
``_load_artifact_path_declaration`` and ``evaluate_pull_request``'s ``base_ref``
parameter. The declaration replaces only the path-shape test
(`_is_known_documentation_path`'s equivalent for declared prefixes); it never
substitutes for content evidence, and an active-runtime-named file
(`_runtime_path_rule`) stays rejected inside a declared prefix exactly as inside
``docs/`` today.

Suffix decision: most research-data formats (``.xlsx``, ``.sav``, ``.rds``,
``.npz``, ...) have no entry in ``BINARY_DOCUMENT_MAGIC``, which only knows
``.hwpx``/``.pdf``/``.png``. Rather than grow that registry for every such
format, a file under a declared prefix whose suffix has no magic entry is
admitted on the stricter complement of the UTF-8 decode this module already
performs for every ordinarily-scanned file: no diff patch available, *and* the
fetched bytes fail to decode as UTF-8. That keeps the module's central
guarantee honest -- a file that decodes as valid UTF-8 is never treated as a
binary artifact, since scanning exactly that content is what this module
exists to do -- while still admitting genuinely opaque research binaries
without maintaining an open-ended magic-byte catalog. A suffix that *does*
have a magic entry keeps that entry's existing structural evidence check
(``_is_complete_png``, ``_is_complete_hwpx``, or the raw magic-prefix check for
``.pdf``) even under a declared prefix.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_FILE_BYTES = 1_048_576
MAX_RESPONSE_BYTES = 16_777_216
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# A base ref threaded into evaluate_pull_request may be either a branch name
# (e.g. "main", "release/2026.09") or a commit SHA -- whatever the calling
# workflow already has on the pull_request event without new permissions.
# Bounded charset/length, no ".." traversal, and no leading/trailing "/".
BASE_REF_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._/-]{0,253}[A-Za-z0-9])?$")
GITHUB_API_ORIGIN = "https://api.github.com"

DOCUMENT_SUFFIXES = frozenset({".md", ".mdx", ".rst", ".adoc", ".txt"})
# Opaque binary document formats that cannot embed an interpretable, active
# Nginx runtime artifact (unlike a text config, script, or container image
# reference). Without this, any such file placed under a documentation
# directory still falls through to `_needs_content_scan` -> `True` (binary
# files never carry a GitHub diff `patch`), and then `_load_file_content`
# fails closed with a `PolicyError` for any instance over the Contents API's
# 1 MiB base64 ceiling -- rejecting a legitimate research-paper citation
# (this org's own "attach the relevant paper PDF" convention) for a reason
# that has nothing to do with the Nginx runtime policy this module enforces.
BINARY_DOCUMENT_MAGIC = {
    ".hwpx": (b"PK\x03\x04",),
    ".pdf": (b"%PDF-",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
}
PNG_SIGNATURE = BINARY_DOCUMENT_MAGIC[".png"][0]
SOURCE_TEST_SUFFIXES = frozenset({".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".rs"})
LICENSE_NAMES = frozenset({"license", "license.md", "copying", "copyrights", "notice"})
DOCUMENTATION_DIRECTORIES = frozenset({"doc", "docs", "documentation"})
DOCUMENTATION_ROOT_NAMES = frozenset({"readme", "changelog", "changes"})

# Consumer-repository declaration of research/data artifact path prefixes
# (issue #2193). Resolved *only* from the pull request's base ref -- never
# its head -- so a PR cannot self-authorize admission of its own binary by
# adding or widening the declaration in the same diff; see
# `_load_artifact_path_declaration`.
ARTIFACT_PATH_DECLARATION_PATH = ".github/edge-policy-artifact-paths.txt"
# Parsing-safety bounds only, not a product limit on how many research/data
# artifact locations a repository may declare: they exist so a pathological
# declaration file cannot make policy evaluation walk an unbounded number of
# entries, or match against an unbounded path depth, for every changed file
# in every pull request the required workflow evaluates.
MAX_DECLARED_ARTIFACT_PREFIXES = 64
MAX_DECLARED_ARTIFACT_PREFIX_DEPTH = 8

RUNTIME_PATH_NAMES = frozenset({
    "dockerfile",
    "containerfile",
    "nginx.conf",
    "nginx.service",
})
SUDO_ARGUMENT_OPTION_RE = (
    r"(?:-(?:u|g|h|C|p|R|T)|--(?:user|group|host|close-from|prompt|chroot|command-timeout))"
)
SUDO_OPTION_RE = (
    rf"(?:{SUDO_ARGUMENT_OPTION_RE}(?:=|\s+)\S+|"
    rf"(?!(?:{SUDO_ARGUMENT_OPTION_RE})(?:=|\s|$))--?\S+|--)"
)
SUDO_PREFIX_RE = rf"(?:sudo\s+(?:{SUDO_OPTION_RE}\s+)*|)"
NGINX_RUNTIME_IMAGE_RE = (
    r"(?:nginx|nginx-(?!prometheus-exporter(?:[:@\s]|$))[A-Za-z0-9._-]+)"
)

CONTENT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "nginx_container_image",
        re.compile(
            r"(?im)^\s*(?:-\s*)?(?:FROM|image:)\s+"
            r"(?:[A-Za-z0-9._-]+(?::[0-9]+)?/)*"
            rf"{NGINX_RUNTIME_IMAGE_RE}"
            r"(?:[:@]\S+|\s|$)"
        ),
    ),
    (
        "nginx_ingress_controller",
        re.compile(
            r"(?im)(?:nginx\.ingress\.kubernetes\.io/|"
            r"kubernetes\.io/ingress\.class\s*:\s*(?:[\"']nginx[\"']|nginx(?:\s|$))|"
            r"ingressClassName\s*:\s*(?:[\"']nginx[\"']|nginx(?:\s|$)))"
        ),
    ),
    (
        "nginx_runtime_command",
        re.compile(
            r"(?im)(?:^\s*(?:systemctl|service)\s+(?:--\S+\s+)*(?:\S+\s+)*nginx\b|"
            rf"^\s*{SUDO_PREFIX_RE}nginx(?=\s|$|[;&|])|"
            r"(?:CMD|ENTRYPOINT)\s*\[[^\n]*[\"']nginx[\"']|"
            r"\bnginx\s+-g\s+[\"']daemon\s+off;)"
        ),
    ),
    (
        "nginx_runtime_path",
        re.compile(
            r"(?i)(?:/etc/nginx(?:/|\b)|/var/(?:cache|run|log)/nginx(?:/|\b)|"
            r"/usr/share/nginx(?:/|\b))"
        ),
    ),
    (
        "nginx_package_install",
        re.compile(
            rf"(?im)^\s*(?:RUN\s+)?{SUDO_PREFIX_RE}(?:apk\s+add|apt(?:-get)?\s+install|"
            r"dnf\s+install|yum\s+install)\b(?:[^\n#]*\\\s*\n\s*)*[^\n#]*\bnginx\b"
        ),
    ),
)


@dataclass(frozen=True)
class ChangedFile:
    """A bounded subset of GitHub pull-request changed-file metadata."""

    path: str
    status: str
    patch: str
    patch_available: bool = True


@dataclass(frozen=True)
class Violation:
    """A single policy violation suitable for GitHub annotation output."""

    path: str
    rule: str
    line: int
    excerpt: str


class PolicyError(RuntimeError):
    """Raised when policy evidence cannot be collected or validated safely."""


class ContentSizeExceededError(PolicyError):
    """Raised when a well-formed Contents API response exceeds MAX_FILE_BYTES.

    Distinct from every other ``PolicyError`` cause (a malformed response, a
    non-file/non-base64 entry, corrupt base64, a declared size that does not
    match the decoded bytes) so a caller can choose to trust a narrow,
    path-scoped convention -- a genuinely oversized documentation PDF, the
    one case this module cannot verify by content at all -- instead of
    failing the whole check closed. Every other content-evidence failure
    still fails closed exactly as before.
    """


class ArtifactDeclarationNotFoundError(PolicyError):
    """Raised when the GitHub API reports no resource at a requested path.

    Distinguished from every other ``PolicyError`` cause via the source
    HTTP 404 status specifically, so ``_load_artifact_path_declaration`` can
    treat "no declaration file at this base ref" as the repository simply
    not having opted into the research/data artifact-path exemption --
    identical to today's behavior -- while every other evidence failure
    (malformed JSON, an invalid declared entry, a transient network error)
    still fails the whole check closed exactly like any other ``PolicyError``.
    """


OpenJson = Callable[[str, str], object]


class NoRedirectHandler(HTTPRedirectHandler):
    """Reject redirects so validated GitHub API requests keep one origin."""

    def redirect_request(self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str) -> None:
        """Raise an HTTPError instead of following the redirect."""
        raise HTTPError(req.full_url, code, msg, headers, fp)


github_opener = build_opener(NoRedirectHandler())


def _is_known_documentation_path(pure: PurePosixPath) -> bool:
    """Return whether *pure* sits in a recognized documentation location."""

    stem = pure.stem.lower()
    return bool(pure.parts) and (
        any(part.lower() in DOCUMENTATION_DIRECTORIES for part in pure.parts)
        or (len(pure.parts) == 1 and stem in DOCUMENTATION_ROOT_NAMES)
    )


def _parse_artifact_path_declaration(text: str) -> tuple[str, ...]:
    """Parse a declared research/data artifact path-prefix list.

    One explicit path prefix per non-blank line; no globs or wildcards --
    every entry names a literal directory prefix, matched segment-wise by
    ``_declared_prefix_for_path``. Rejects an absolute path, a ``..``
    traversal component, an empty entry, or a bare ``.``/``/``. Bounded by
    ``MAX_DECLARED_ARTIFACT_PREFIXES`` (entry count) and
    ``MAX_DECLARED_ARTIFACT_PREFIX_DEPTH`` (path segment depth) -- both are
    parsing-safety bounds, not a product limit on how many locations a
    repository may declare. A malformed entry always raises ``PolicyError``
    naming the offending entry; this never falls back to admitting nothing
    or everything.
    """

    prefixes: list[str] = []
    for raw_line in text.splitlines():
        entry = raw_line.strip()
        if not entry:
            continue
        if len(prefixes) >= MAX_DECLARED_ARTIFACT_PREFIXES:
            raise PolicyError(
                f"Artifact path declaration exceeds {MAX_DECLARED_ARTIFACT_PREFIXES} entries at {entry!r}"
            )
        if entry.startswith("/") or entry in (".", "/"):
            raise PolicyError(f"Artifact path declaration entry must be a relative path prefix: {entry!r}")
        if any(char in entry for char in "*?[]"):
            raise PolicyError(f"Artifact path declaration entry must not use glob syntax: {entry!r}")
        parts = PurePosixPath(entry).parts
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise PolicyError(f"Artifact path declaration entry is malformed: {entry!r}")
        if len(parts) > MAX_DECLARED_ARTIFACT_PREFIX_DEPTH:
            raise PolicyError(
                f"Artifact path declaration entry exceeds depth {MAX_DECLARED_ARTIFACT_PREFIX_DEPTH}: {entry!r}"
            )
        prefixes.append(entry)
    return tuple(prefixes)


def _declared_prefix_for_path(path: str, declared_prefixes: Sequence[str]) -> str | None:
    """Return the first declared prefix *path* falls under, else ``None``.

    Matched by path segment, not raw string prefix, so a declared ``local``
    does not also match an unrelated ``local-cache`` directory.
    """

    parts = PurePosixPath(path).parts
    for prefix in declared_prefixes:
        prefix_parts = PurePosixPath(prefix).parts
        if parts[: len(prefix_parts)] == prefix_parts:
            return prefix
    return None


def _load_artifact_path_declaration(
    *, api_url: str, repository: str, base_ref: str, token: str, opener: OpenJson
) -> tuple[str, ...]:
    """Load and parse the research/data artifact path declaration at *base_ref*.

    Resolved **only** from the pull request's base ref -- never its head --
    so a pull request cannot self-authorize admission of its own binary by
    adding or widening the declaration in the same diff: a PR that adds or
    widens the declaration gets no benefit from it until that change is
    itself reviewed and merged into the base branch.

    A declaration file absent from the base ref (HTTP 404) is not a policy
    failure: it means the repository has not opted in, identical to today's
    behavior before this feature existed. Every other failure to load or
    parse it (malformed API shape, an invalid declared entry) still fails
    the whole check closed via ``PolicyError``.
    """

    try:
        content = _load_file_content(api_url, repository, ARTIFACT_PATH_DECLARATION_PATH, base_ref, token, opener)
    except ArtifactDeclarationNotFoundError:
        return ()
    return _parse_artifact_path_declaration(content)


def _is_documentation_or_source_fixture(path: str) -> bool:
    """Return whether *path* is prose, license text, or scanner source fixture.

    Textual suffixes only: a ``.pdf`` is handled separately by
    ``_is_binary_documentation_asset`` and gated on GitHub reporting no diff
    ``patch`` for it, so a textual file merely named with a ``.pdf`` suffix
    (one GitHub *can* diff, meaning it could carry inspectable content) is
    never exempted here.

    Only the trusted scanner source itself and dedicated inert samples under
    ``tests/fixtures`` receive a source-fixture exemption. Executable test
    modules remain runtime candidates under the binding policy; regression
    samples that contain denied forms must live in the dedicated fixture
    boundary rather than exempting the whole test module.
    """

    pure = PurePosixPath(path)
    lower_name = pure.name.lower()
    if lower_name in LICENSE_NAMES or (
        _is_known_documentation_path(pure) and pure.suffix.lower() in DOCUMENT_SUFFIXES
    ):
        return True
    if pure.as_posix() == "scripts/ci/pingora_edge_policy.py":
        return True
    lower_parts = tuple(part.lower() for part in pure.parts)
    is_tests_fixture = len(lower_parts) >= 2 and lower_parts[:2] == ("tests", "fixtures")
    if is_tests_fixture and pure.suffix.lower() in SOURCE_TEST_SUFFIXES | DOCUMENT_SUFFIXES:
        return True
    return False


def _is_binary_documentation_asset(changed: ChangedFile, declared_prefixes: Sequence[str] = ()) -> bool:
    """Return whether *changed* is a plausibly binary documentation asset.

    This is only the cheap, patch-presence pre-filter: GitHub's changed-files
    API never returns a diff ``patch`` for a true binary file, so a missing
    ``patch`` is *necessary* but not *sufficient* evidence -- GitHub also
    omits one for a textual diff that merely exceeds its own rendering
    limit. A caller with network access (``evaluate_pull_request``) must
    still confirm this with ``_binary_documentation_evidence_confirms`` before
    trusting it; a caller without one (this module's own unit tests calling
    this function directly) is only checking the necessary condition.

    *declared_prefixes* (issue #2193) is the base-ref-only research/data
    artifact declaration: it replaces ONLY this function's path-shape test,
    never the content evidence a caller still confirms below. A file whose
    suffix is a recognized ``BINARY_DOCUMENT_MAGIC`` format (``.hwpx``/
    ``.pdf``/``.png``) is admitted under a declared prefix on the exact same
    format evidence documentation paths already require. A file whose
    suffix has no magic entry at all (research formats such as ``.xlsx``,
    ``.sav``, ``.rds``, ``.npz`` have none) can ONLY be admitted through a
    declared prefix, and only on the stricter "no patch + genuinely
    non-UTF-8 bytes" evidence ``_binary_documentation_evidence_confirms``
    checks for that case -- a file that decodes as valid UTF-8 must never
    be treated as a binary artifact, since that is exactly the case this
    scanner exists to inspect.
    """

    if changed.patch_available or _runtime_path_rule(changed.path) is not None:
        return False
    pure = PurePosixPath(changed.path)
    suffix = pure.suffix.lower()
    declared_prefix = _declared_prefix_for_path(changed.path, declared_prefixes)
    if suffix in BINARY_DOCUMENT_MAGIC:
        return (
            _is_known_documentation_path(pure)
            or (suffix == ".hwpx" and "evidence" in (part.lower() for part in pure.parts))
            or declared_prefix is not None
        )
    return declared_prefix is not None


def _runtime_path_rule(path: str) -> str | None:
    """Return a path-level violation rule for active Nginx runtime artifacts."""

    pure = PurePosixPath(path)
    lower_parts = tuple(part.lower() for part in pure.parts)
    lower_name = pure.name.lower()
    if lower_name in RUNTIME_PATH_NAMES and "nginx" in lower_name:
        return "nginx_runtime_artifact"
    if "nginx" in lower_parts:
        return "nginx_runtime_artifact"
    if lower_name.startswith("nginx-") and pure.suffix.lower() in {".conf", ".service", ".sh", ".yaml", ".yml"}:
        return "nginx_runtime_artifact"
    return None


def _line_number(content: str, start: int) -> int:
    """Translate a character offset into a one-based line number."""

    return content.count("\n", 0, start) + 1


def scan_content(path: str, content: str) -> tuple[Violation, ...]:
    """Return all Pingora policy violations found in one final file version."""

    if _is_documentation_or_source_fixture(path):
        return ()
    violations: list[Violation] = []
    path_rule = _runtime_path_rule(path)
    if path_rule is not None:
        violations.append(Violation(path, path_rule, 1, "active Nginx runtime artifact path"))
    for rule, pattern in CONTENT_RULES:
        for match in pattern.finditer(content):
            excerpt = " ".join(match.group(0).strip().split())[:160]
            violations.append(Violation(path, rule, _line_number(content, match.start()), excerpt))
    return tuple(violations)


def _validate_github_api_url(url: str) -> None:
    """Reject policy evidence URLs outside the public GitHub REST origin."""

    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.github.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or not parsed.path.startswith("/repos/")
        or parsed.fragment
    ):
        raise PolicyError("GitHub API policy URL is outside the approved origin")


def _github_open_json(url: str, token: str) -> object:
    """Read one bounded GitHub REST JSON document using bearer authentication."""

    _validate_github_api_url(url)
    request = Request(  # noqa: S310 - URL is validated immediately above
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "cwl-pingora-edge-policy/1",
        },
    )
    try:
        with github_opener.open(request, timeout=30) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError) as exc:
        if isinstance(exc, HTTPError) and exc.code == 404:
            raise ArtifactDeclarationNotFoundError(
                f"GitHub API reported no resource for policy evidence at {url}"
            ) from exc
        raise PolicyError(f"GitHub API request failed for policy evidence: {type(exc).__name__}") from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise PolicyError("GitHub API policy response exceeded the bounded response size")
    try:
        return json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PolicyError("GitHub API returned malformed JSON policy evidence") from exc


def _load_changed_files(api_url: str, repository: str, pull_request: int, token: str, opener: OpenJson) -> tuple[ChangedFile, ...]:
    """Load every changed-file page while enforcing shape and pagination bounds."""

    files: list[ChangedFile] = []
    for page in range(1, 32):
        url = f"{api_url}/repos/{repository}/pulls/{pull_request}/files?per_page=100&page={page}"
        payload = opener(url, token)
        if not isinstance(payload, list):
            raise PolicyError("GitHub changed-file evidence is not a JSON array")
        for item in payload:
            if not isinstance(item, Mapping):
                raise PolicyError("GitHub changed-file entry is not an object")
            path = item.get("filename")
            status = item.get("status")
            raw_patch = item.get("patch")
            patch = "" if raw_patch is None else raw_patch
            if (
                not isinstance(path, str)
                or not path
                or not isinstance(status, str)
                or not isinstance(patch, str)
            ):
                raise PolicyError("GitHub changed-file entry has invalid bounded fields")
            files.append(
                ChangedFile(
                    path=path,
                    status=status,
                    patch=patch,
                    patch_available=raw_patch is not None,
                )
            )
            if len(files) > 3_000:
                raise PolicyError("GitHub changed-file pagination exceeded 3,000 files")
        if len(payload) < 100:
            return tuple(files)
    # Unreachable by construction, not a live fallback: every one of the 31
    # `range(1, 32)` iterations that reaches this point already returned a
    # page whose length is >= 100 (a page under 100 items hits the `return`
    # two lines up first), so 31 such pages accumulate at least 3,100 files
    # -- strictly more than the 3,000 cap above, which is checked after
    # every single appended item, not just at page boundaries. That in-loop
    # check therefore always raises no later than partway through the 31st
    # page, before the `for` loop can ever exhaust its range. Kept as a
    # structural fail-closed guard (so a future change to PAGE_COUNT,
    # per_page, or the 3,000 cap that breaks this invariant fails loudly
    # instead of silently truncating evidence) rather than deleted; see
    # test_changed_file_pagination_bound_is_provably_unreachable, which
    # pins the arithmetic relationship itself.
    raise PolicyError("GitHub changed-file pagination exceeded 3,000 files")  # pragma: no cover


def _load_raw_file_bytes(api_url: str, repository: str, path: str, head_sha: str, token: str, opener: OpenJson) -> bytes:
    """Load one final head file's raw decoded bytes from the Contents API.

    Raises ``ContentSizeExceededError`` specifically when the declared size
    is a well-formed positive integer over ``MAX_FILE_BYTES`` -- a signal a
    caller may treat differently from every other, genuinely malformed
    response shape, which always raises the base ``PolicyError`` instead.

    GitHub's Contents API returns two distinct shapes for a file it cannot
    inline: some responses still report ``encoding: "base64"`` with a
    ``size`` over the inline-content ceiling and empty/absent ``content``;
    for files whose blob exceeds that ceiling, GitHub instead reports
    ``encoding: "none"`` with an accurate ``size`` and no ``content`` at
    all. Both are treated as the same size-exceeded evidence; every other
    response shape still fails closed.

    *head_sha* is also reused, unchanged, to fetch a base-ref-scoped file
    (the issue #2193 artifact-path declaration): any git ref -- a commit SHA
    or a branch name -- works here, so it is URL-encoded rather than assumed
    to be the hex-only pull-request head SHA ``evaluate_pull_request``
    validates separately.
    """

    encoded_path = quote(path, safe="/")
    url = f"{api_url}/repos/{repository}/contents/{encoded_path}?ref={quote(head_sha, safe='')}"
    payload = opener(url, token)
    if not isinstance(payload, Mapping):
        raise PolicyError(f"GitHub content evidence for {path} is not an object")
    if payload.get("type") != "file":
        raise PolicyError(f"GitHub content evidence for {path} is not a regular file")
    encoding = payload.get("encoding")
    declared_size = payload.get("size")
    if encoding == "none":
        if isinstance(declared_size, int) and declared_size > MAX_FILE_BYTES:
            raise ContentSizeExceededError(f"GitHub content evidence for {path} exceeds the size contract")
        raise PolicyError(f"GitHub content evidence for {path} has no inline content and no verifiable oversized size")
    if encoding != "base64":
        raise PolicyError(f"GitHub content evidence for {path} is not a regular base64 file")
    encoded = payload.get("content")
    if not isinstance(encoded, str) or not isinstance(declared_size, int) or declared_size < 0:
        raise PolicyError(f"GitHub content evidence for {path} has a malformed size or content field")
    if declared_size > MAX_FILE_BYTES:
        raise ContentSizeExceededError(f"GitHub content evidence for {path} exceeds the size contract")
    try:
        raw = base64.b64decode("".join(encoded.split()), validate=True)
    except (ValueError, TypeError) as exc:
        raise PolicyError(f"GitHub content evidence for {path} is invalid base64") from exc
    if len(raw) != declared_size:
        raise PolicyError(f"GitHub content evidence for {path} has a size mismatch")
    return raw


def _load_file_content(api_url: str, repository: str, path: str, head_sha: str, token: str, opener: OpenJson) -> str:
    """Load one final head file as bounded UTF-8 text from the Contents API."""

    raw = _load_raw_file_bytes(api_url, repository, path, head_sha, token, opener)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PolicyError(f"Runtime policy candidate {path} is not valid UTF-8") from exc


def _binary_documentation_evidence_confirms(
    changed: ChangedFile,
    *,
    api_url: str,
    repository: str,
    head_sha: str,
    token: str,
    opener: OpenJson,
) -> bool:
    """Return whether a claimed binary documentation asset is genuine.

    A missing diff ``patch`` alone is not proof of binary content: GitHub
    also omits a patch for a textual diff that exceeds its own rendering
    limit, well under this module's ``MAX_FILE_BYTES`` content-fetch
    ceiling. Whenever the file's raw bytes can be fetched at all, this
    verifies the declared format's magic prefix instead of trusting
    patch-presence alone. Only a file whose content evidently exceeds the
    Contents API's size ceiling -- the exact case ``_is_binary_documentation_asset``
    exists for, a cited, large research paper -- falls back to trusting the
    path+suffix convention for oversized PDFs only; every other
    content-evidence failure (a
    malformed API response, corrupt base64, a declared size that does not
    match the decoded bytes) propagates and fails the whole check closed,
    same as for any other file that needs scanning.

    A suffix with no ``BINARY_DOCUMENT_MAGIC`` entry only reaches this
    branch when ``_is_binary_documentation_asset`` admitted it through a
    declared research/data artifact prefix (issue #2193), which has no
    magic byte to check. That case is confirmed by the strict complement of
    the UTF-8 decode ``_load_file_content`` uses for every ordinarily-scanned
    file: bytes that fail to decode as UTF-8 are genuinely binary evidence;
    bytes that decode cleanly are never admitted this way, so a valid-UTF-8
    file cannot be mistaken for a binary artifact merely by sitting under a
    declared prefix -- it still reaches the normal content scan instead.
    """

    try:
        raw = _load_raw_file_bytes(api_url, repository, changed.path, head_sha, token, opener)
    except ContentSizeExceededError:
        return PurePosixPath(changed.path).suffix.lower() == ".pdf"
    suffix = PurePosixPath(changed.path).suffix.lower()
    if suffix == ".png":
        return _is_complete_png(raw)
    if suffix == ".hwpx":
        return _is_complete_hwpx(raw)
    if suffix not in BINARY_DOCUMENT_MAGIC:
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError:
            return True
        return False
    return raw.startswith(BINARY_DOCUMENT_MAGIC[suffix])


def _is_complete_hwpx(raw: bytes) -> bool:
    """Confirm a bounded HWPX container without extracting document content.

    Require an unprefixed ZIP, its exact end record, unique members, and the
    stored HWPX MIME marker plus an unencrypted package manifest. This is
    format evidence, not XML document validation or malware inspection.
    """
    if not raw.startswith(BINARY_DOCUMENT_MAGIC[".hwpx"][0]):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            archive_entries = archive.infolist()
            member_names = [member_info.filename for member_info in archive_entries]
            end_offset = len(raw) - 22 - len(archive.comment)
            if end_offset < 0 or raw[end_offset:end_offset + 4] != b"PK\x05\x06":
                return False
            if int.from_bytes(raw[end_offset + 20:end_offset + 22], "little") != len(archive.comment):
                return False
            if not archive_entries or archive_entries[0].header_offset != 0:
                return False
            if member_names[0] != "mimetype" or len(member_names) != len(set(member_names)):
                return False
            mimetype_info = archive.getinfo("mimetype")
            manifest_info = archive.getinfo("Contents/content.hpf")
            expected_mimetype = b"application/hwp+zip"
            if mimetype_info.flag_bits & 1 or manifest_info.flag_bits & 1:
                return False
            if mimetype_info.compress_type != zipfile.ZIP_STORED or mimetype_info.file_size != len(expected_mimetype):
                return False
            if manifest_info.is_dir() or manifest_info.file_size == 0:
                return False
            with archive.open(mimetype_info) as mimetype_stream:
                return mimetype_stream.read(len(expected_mimetype) + 1) == expected_mimetype
    except (KeyError, UnicodeError, OSError, ValueError, NotImplementedError, zipfile.BadZipFile):
        return False


def _png_unfilter_row(filtered: bytes, previous: bytes, filter_type: int, bytes_per_pixel: int) -> bytes:
    """Reconstruct one PNG scanline for bounded indexed-pixel validation."""

    reconstructed = bytearray(len(filtered))
    for index, value in enumerate(filtered):
        left = reconstructed[index - bytes_per_pixel] if index >= bytes_per_pixel else 0
        above = previous[index] if previous else 0
        upper_left = previous[index - bytes_per_pixel] if previous and index >= bytes_per_pixel else 0
        if filter_type == 0:
            predictor = 0
        elif filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = above
        elif filter_type == 3:
            predictor = (left + above) // 2
        else:
            estimate = left + above - upper_left
            distances = (abs(estimate - left), abs(estimate - above), abs(estimate - upper_left))
            predictor = (left, above, upper_left)[distances.index(min(distances))]
        reconstructed[index] = (value + predictor) & 0xFF
    return bytes(reconstructed)


def _is_complete_png(raw: bytes) -> bool:
    """Validate one bounded PNG including its null- or Adam7-interlaced stream."""

    if not raw.startswith(PNG_SIGNATURE):
        return False
    offset = len(PNG_SIGNATURE)
    header: tuple[int, int, int, int, int] | None = None
    palette_entries = 0
    image_data: list[bytes] = []
    image_data_closed = False
    while offset + 12 <= len(raw):
        length = int.from_bytes(raw[offset : offset + 4], "big")
        chunk_end = offset + 12 + length
        if chunk_end > len(raw):
            return False
        chunk_type = raw[offset + 4 : offset + 8]
        chunk_data = raw[offset + 8 : offset + 8 + length]
        expected_crc = int.from_bytes(raw[offset + 8 + length : chunk_end], "big")
        if (
            any(not (65 <= byte <= 90 or 97 <= byte <= 122) for byte in chunk_type)
            or chunk_type[2] & 0x20
            or zlib.crc32(chunk_type + chunk_data) != expected_crc
        ):
            return False
        if header is None:
            if chunk_type != b"IHDR" or length != 13 or offset != len(PNG_SIGNATURE):
                return False
            width = int.from_bytes(chunk_data[0:4], "big")
            height = int.from_bytes(chunk_data[4:8], "big")
            bit_depth, color_type, compression, filtering, interlace = chunk_data[8:13]
            allowed_depths = {
                0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8},
                4: {8, 16}, 6: {8, 16},
            }
            if (
                width == 0 or height == 0
                or bit_depth not in allowed_depths.get(color_type, set())
                or compression != 0 or filtering != 0 or interlace not in {0, 1}
            ):
                return False
            header = (width, height, bit_depth, color_type, interlace)
        elif chunk_type == b"IHDR":
            return False
        elif chunk_type == b"PLTE":
            if palette_entries or image_data or length == 0 or length > 768 or length % 3:
                return False
            _width, _height, bit_depth, color_type, _interlace = header
            if color_type == 3 and length // 3 > 1 << bit_depth:
                return False
            palette_entries = length // 3
        elif chunk_type == b"IDAT":
            if image_data_closed:
                return False
            image_data.append(chunk_data)
        elif chunk_type == b"IEND":
            if length != 0 or not image_data or chunk_end != len(raw):
                return False
            width, height, bit_depth, color_type, interlace = header
            if (color_type == 3 and not palette_entries) or (
                color_type in {0, 4} and palette_entries
            ):
                return False
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
            passes = (
                ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
                 (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
                if interlace else ((0, 0, 1, 1),)
            )
            scanlines: list[tuple[int, int, int]] = []
            expected_size = 0
            for x_start, y_start, x_step, y_step in passes:
                if width <= x_start or height <= y_start:
                    continue
                pass_width = (width - x_start + x_step - 1) // x_step
                pass_height = (height - y_start + y_step - 1) // y_step
                row_bytes = (pass_width * channels * bit_depth + 7) // 8
                expected_size += pass_height * (row_bytes + 1)
                if expected_size > MAX_RESPONSE_BYTES:
                    return False
                scanlines.append((pass_height, row_bytes, pass_width))
            decoder = zlib.decompressobj()
            try:
                decoded = decoder.decompress(b"".join(image_data), expected_size + 1)
            except zlib.error:
                return False
            if (
                len(decoded) != expected_size or not decoder.eof
                or decoder.unused_data or decoder.unconsumed_tail
            ):
                return False
            decoded_offset = 0
            for row_count, row_bytes, pass_width in scanlines:
                previous = b""
                for _ in range(row_count):
                    filter_type = decoded[decoded_offset]
                    if filter_type > 4:
                        return False
                    filtered = decoded[decoded_offset + 1 : decoded_offset + row_bytes + 1]
                    if color_type == 3:
                        reconstructed = _png_unfilter_row(filtered, previous, filter_type, 1)
                        mask = (1 << bit_depth) - 1
                        for pixel in range(pass_width):
                            bit_offset = pixel * bit_depth
                            palette_index = (
                                reconstructed[bit_offset // 8]
                                >> (8 - bit_depth - bit_offset % 8)
                            ) & mask
                            if palette_index >= palette_entries:
                                return False
                        previous = reconstructed
                    decoded_offset += row_bytes + 1
            return decoded_offset == len(decoded)
        elif chunk_type[0] & 0x20 == 0:
            return False
        elif image_data:
            image_data_closed = True
        offset = chunk_end
    return False


def _needs_content_scan(changed: ChangedFile, declared_prefixes: Sequence[str] = ()) -> bool:
    """Return whether a changed final file can carry an active edge runtime.

    A claimed binary documentation asset (``_is_binary_documentation_asset``)
    exempts here on the cheap, offline pre-filter alone; ``evaluate_pull_request``
    never actually relies on that -- it runs ``_binary_documentation_evidence_confirms``
    for that case before this function is even consulted. *declared_prefixes*
    is the base-ref-only research/data artifact declaration from issue
    #2193; it is passed straight through to ``_is_binary_documentation_asset``.
    """

    if changed.status == "removed" or _is_documentation_or_source_fixture(changed.path):
        return False
    if _is_binary_documentation_asset(changed, declared_prefixes):
        return False
    if not changed.patch_available:
        return True
    if _runtime_path_rule(changed.path) is not None:
        return True
    lower_path = changed.path.lower()
    if PurePosixPath(lower_path).name in {"dockerfile", "containerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
        return True
    if PurePosixPath(lower_path).suffix in {".conf", ".service", ".yaml", ".yml", ".sh"}:
        return True
    return "nginx" in changed.patch.lower()


def evaluate_pull_request(
    *,
    api_url: str,
    repository: str,
    pull_request: int,
    head_sha: str,
    event_action: str,
    token: str,
    base_ref: str | None = None,
    opener: OpenJson = _github_open_json,
) -> tuple[Violation, ...]:
    """Evaluate one pull request without checking out or executing its content.

    *base_ref* (issue #2193) is an optional pull-request base ref -- a
    branch name or a commit SHA, whatever the calling workflow already has
    on the ``pull_request`` event without new permissions. When given, the
    research/data artifact path declaration at ``ARTIFACT_PATH_DECLARATION_PATH``
    is resolved from that ref (never from ``head_sha``) and its declared
    prefixes are admitted on the same content-evidence terms as documentation
    paths. Omitting it (the default) reproduces this module's exact prior
    behavior: no declared prefixes, no declaration fetch at all.
    """

    if event_action == "closed":
        return ()
    if not REPOSITORY_RE.fullmatch(repository):
        raise PolicyError("Repository identity is malformed")
    if pull_request <= 0:
        raise PolicyError("Pull-request number must be positive")
    if not SHA_RE.fullmatch(head_sha):
        raise PolicyError("Pull-request head SHA is malformed")
    if not token:
        raise PolicyError("GITHUB_TOKEN is required for policy evidence")
    if base_ref is not None and (".." in base_ref or not BASE_REF_RE.fullmatch(base_ref)):
        raise PolicyError("Pull-request base ref is malformed")
    resolved_api_url = api_url.rstrip("/")
    declared_prefixes: tuple[str, ...] = ()
    if base_ref is not None:
        declared_prefixes = _load_artifact_path_declaration(
            api_url=resolved_api_url, repository=repository, base_ref=base_ref, token=token, opener=opener
        )
    changed_files = _load_changed_files(resolved_api_url, repository, pull_request, token, opener)
    violations: list[Violation] = []
    for changed in changed_files:
        declared_prefix = _declared_prefix_for_path(changed.path, declared_prefixes)
        # A claimed binary documentation asset gets its own network-verified
        # check ahead of _needs_content_scan's patch-presence-only signal:
        # a missing patch does not by itself prove binary content (GitHub
        # also omits one for an oversized textual diff), so this confirms
        # the format's magic prefix whenever the bytes can be fetched at
        # all, falling back to the path+suffix convention only when the
        # content genuinely exceeds the Contents API's size ceiling. A
        # removed file has no head content to fetch at all -- _needs_content_scan
        # already special-cases this the same way for every other file.
        if changed.status != "removed" and _is_binary_documentation_asset(changed, declared_prefixes):
            if _binary_documentation_evidence_confirms(
                changed,
                api_url=resolved_api_url,
                repository=repository,
                head_sha=head_sha,
                token=token,
                opener=opener,
            ):
                if declared_prefix is not None:
                    # Names the reviewed declaration this admission relied
                    # on, so a reviewer can trace it back to the base ref.
                    print(_declared_prefix_notice(changed.path, declared_prefix, base_ref))
                continue
        elif not _needs_content_scan(changed, declared_prefixes):
            continue
        content = _load_file_content(resolved_api_url, repository, changed.path, head_sha, token, opener)
        violations.extend(scan_content(changed.path, content))
    return tuple(violations)


def _declared_prefix_notice(path: str, prefix: str, base_ref: str) -> str:
    """Render one bounded GitHub workflow notice for a declared-prefix admission."""

    escaped_path = path.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A").replace(",", "%2C")
    message = (
        f"CWL edge policy admitted a research/data artifact under declared prefix "
        f"'{prefix}' (declaration read from base ref '{base_ref}')"
    )
    message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::notice file={escaped_path}::{message}"


def _annotation(violation: Violation) -> str:
    """Render one bounded GitHub workflow command annotation."""

    path = violation.path.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A").replace(",", "%2C")
    message = f"CWL edge policy requires Cloudflare Pingora; {violation.rule}: {violation.excerpt}"
    message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return f"::error file={path},line={violation.line}::{message}"


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser used by the required workflow."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pull-request", required=True, type=int)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--event-action", required=True)
    parser.add_argument("--api-url", default=GITHUB_API_ORIGIN)
    parser.add_argument(
        "--base-ref",
        default=None,
        help=(
            "Pull-request base ref (branch name or commit SHA) used to resolve the "
            "issue #2193 research/data artifact path declaration. Omit to disable "
            "that declaration entirely (identical to this module's prior behavior)."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None) -> int:
    """Run the policy checker and return a process exit status."""

    args = build_parser().parse_args(argv)
    env = os.environ if environ is None else environ
    try:
        violations = evaluate_pull_request(
            api_url=args.api_url,
            repository=args.repository,
            pull_request=args.pull_request,
            head_sha=args.head_sha,
            event_action=args.event_action,
            token=env.get("GITHUB_TOKEN", ""),
            base_ref=args.base_ref,
        )
    except PolicyError as exc:
        print(f"::error::Pingora edge policy could not establish complete evidence: {exc}")
        return 2
    if violations:
        for violation in violations:
            print(_annotation(violation))
        print(f"CWL Pingora edge policy rejected {len(violations)} active Nginx runtime artifact(s).")
        return 1
    print("CWL Pingora edge policy passed: no changed active Nginx runtime artifact remains.")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main() contract tests
    sys.exit(main())
