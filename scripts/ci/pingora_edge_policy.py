#!/usr/bin/env python3
"""Enforce the CWL Pingora-only edge runtime policy on pull-request changes.

The checker never executes pull-request content. It reads changed-file metadata and
bounded final file content through the GitHub REST API, then rejects active Nginx
runtime artifacts while allowing documentation, license text, recognized image
evidence, and source-level negative test fixtures.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
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
GITHUB_API_ORIGIN = "https://api.github.com"

DOCUMENT_SUFFIXES = frozenset({".md", ".mdx", ".rst", ".adoc", ".txt"})
DOCUMENT_ASSET_SUFFIXES = frozenset({".gif", ".jpeg", ".jpg", ".png", ".webp"})
SOURCE_TEST_SUFFIXES = frozenset({".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".rs"})
LICENSE_NAMES = frozenset({"license", "license.md", "copying", "copyrights", "notice"})
DOCUMENTATION_DIRECTORIES = frozenset({"doc", "docs", "documentation"})
DOCUMENTATION_ROOT_NAMES = frozenset({"readme", "changelog", "changes"})

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


OpenJson = Callable[[str, str], object]


class NoRedirectHandler(HTTPRedirectHandler):
    """Reject redirects so validated GitHub API requests keep one origin."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        """Return no follow-up request for any HTTP redirect response."""
        return None


github_opener = build_opener(NoRedirectHandler())


def _is_documentation_or_source_fixture(path: str) -> bool:
    """Return whether *path* is prose, license text, or scanner source fixture."""

    pure = PurePosixPath(path)
    lower_name = pure.name.lower()
    stem = pure.stem.lower()
    is_known_documentation_path = pure.parts and (
        any(part.lower() in DOCUMENTATION_DIRECTORIES for part in pure.parts)
        or (len(pure.parts) == 1 and stem in DOCUMENTATION_ROOT_NAMES)
    )
    if lower_name in LICENSE_NAMES or (
        is_known_documentation_path
        and pure.suffix.lower() in DOCUMENT_SUFFIXES
    ):
        return True
    if pure.as_posix() == "scripts/ci/pingora_edge_policy.py":
        return True
    lower_parts = tuple(part.lower() for part in pure.parts)
    is_tests_fixture = len(lower_parts) >= 2 and lower_parts[:2] == ("tests", "fixtures")
    if is_tests_fixture and pure.suffix.lower() in SOURCE_TEST_SUFFIXES | DOCUMENT_SUFFIXES:
        return True
    return False


def _is_documentation_image_path(path: str) -> bool:
    """Return whether *path* claims to be raster evidence below documentation."""

    pure = PurePosixPath(path)
    return bool(
        pure.parts
        and any(part.lower() in DOCUMENTATION_DIRECTORIES for part in pure.parts)
        and pure.suffix.lower() in DOCUMENT_ASSET_SUFFIXES
    )


def _is_recognized_documentation_image(path: str, raw: bytes) -> bool:
    """Accept only bounded bytes with the expected raster format envelope."""

    suffix = PurePosixPath(path).suffix.lower()
    if suffix in {".jpeg", ".jpg"}:
        return len(raw) >= 4 and raw.startswith(b"\xff\xd8\xff") and raw.endswith(b"\xff\xd9")
    if suffix == ".gif":
        return len(raw) >= 14 and raw[:6] in {b"GIF87a", b"GIF89a"} and raw[-1:] == b"\x3b"
    if suffix == ".webp":
        return (
            len(raw) >= 20
            and raw[:4] == b"RIFF"
            and raw[8:12] == b"WEBP"
            and int.from_bytes(raw[4:8], "little") == len(raw) - 8
        )
    if suffix != ".png" or len(raw) < 33 or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    offset = 8
    saw_idat = False
    while offset + 12 <= len(raw):
        length = int.from_bytes(raw[offset : offset + 4], "big")
        end = offset + 12 + length
        if end > len(raw):
            return False
        chunk_type = raw[offset + 4 : offset + 8]
        chunk_data = raw[offset + 8 : offset + 8 + length]
        declared_crc = int.from_bytes(raw[offset + 8 + length : end], "big")
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != declared_crc:
            return False
        if offset == 8 and (chunk_type != b"IHDR" or length != 13):
            return False
        if chunk_type == b"IHDR" and (
            int.from_bytes(chunk_data[:4], "big") == 0
            or int.from_bytes(chunk_data[4:8], "big") == 0
        ):
            return False
        saw_idat |= chunk_type == b"IDAT"
        if chunk_type == b"IEND":
            return length == 0 and saw_idat and end == len(raw)
        offset = end
    return False


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
    raise PolicyError("GitHub changed-file pagination exceeded 3,000 files")


def _load_file_bytes(api_url: str, repository: str, path: str, head_sha: str, token: str, opener: OpenJson) -> bytes:
    """Load one final head file as bounded bytes from the Contents API."""

    encoded_path = quote(path, safe="/")
    url = f"{api_url}/repos/{repository}/contents/{encoded_path}?ref={head_sha}"
    payload = opener(url, token)
    if not isinstance(payload, Mapping):
        raise PolicyError(f"GitHub content evidence for {path} is not an object")
    if payload.get("type") != "file" or payload.get("encoding") != "base64":
        raise PolicyError(f"GitHub content evidence for {path} is not a regular base64 file")
    encoded = payload.get("content")
    declared_size = payload.get("size")
    if not isinstance(encoded, str) or not isinstance(declared_size, int) or declared_size < 0 or declared_size > MAX_FILE_BYTES:
        raise PolicyError(f"GitHub content evidence for {path} exceeds or violates the size contract")
    try:
        raw = base64.b64decode("".join(encoded.split()), validate=True)
    except (ValueError, TypeError) as exc:
        raise PolicyError(f"GitHub content evidence for {path} is invalid base64") from exc
    if len(raw) != declared_size:
        raise PolicyError(f"GitHub content evidence for {path} has a size mismatch")
    return raw


def _load_file_content(api_url: str, repository: str, path: str, head_sha: str, token: str, opener: OpenJson) -> str:
    """Load one final head file as bounded UTF-8 text from the Contents API."""
    try:
        return _load_file_bytes(api_url, repository, path, head_sha, token, opener).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PolicyError(f"Runtime policy candidate {path} is not valid UTF-8") from exc


def _needs_content_scan(changed: ChangedFile) -> bool:
    """Return whether a changed final file can carry an active edge runtime."""

    if changed.status == "removed":
        return False
    if _is_documentation_image_path(changed.path):
        return True
    if _is_documentation_or_source_fixture(changed.path):
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
    opener: OpenJson = _github_open_json,
) -> tuple[Violation, ...]:
    """Evaluate one pull request without checking out or executing its content."""

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
    changed_files = _load_changed_files(api_url.rstrip("/"), repository, pull_request, token, opener)
    violations: list[Violation] = []
    for changed in changed_files:
        if not _needs_content_scan(changed):
            continue
        if _is_documentation_image_path(changed.path):
            raw = _load_file_bytes(api_url.rstrip("/"), repository, changed.path, head_sha, token, opener)
            if not _is_recognized_documentation_image(changed.path, raw):
                raise PolicyError(f"Documentation image evidence for {changed.path} is not a recognized image")
            continue
        content = _load_file_content(api_url.rstrip("/"), repository, changed.path, head_sha, token, opener)
        violations.extend(scan_content(changed.path, content))
    return tuple(violations)


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
