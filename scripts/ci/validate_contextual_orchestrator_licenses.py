#!/usr/bin/env python3
"""Validate pinned contextual-orchestrator source and dependency licenses."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import io
import json
import pathlib
import re
import tarfile
import urllib.parse
import urllib.request
import zipfile
from email.message import Message
from email.parser import BytesParser
from typing import Any


ALLOWED_SPDX = frozenset(
    {
        "0BSD",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "ISC",
        "MIT",
        "PSF-2.0",
        "Zlib",
    }
)
PACKAGE_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)==(?P<version>[^\s\\]+)"
)
HASH_OPTION = re.compile(r"--hash=sha256:(?P<digest>[0-9a-fA-F]{64})(?=\s|\\|$)")
SPDX_TOKEN = re.compile(r"\(|\)|AND|OR|[A-Za-z0-9][A-Za-z0-9.+-]*")
MAX_METADATA_BYTES = 2 * 1024 * 1024
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
MAX_LICENSE_METADATA_BYTES = 256 * 1024
PYPI_HOSTS = frozenset({"pypi.org", "files.pythonhosted.org"})
CLASSIFIER_TO_SPDX = {
    "BSD License": "BSD-3-Clause",
    "ISC License": "ISC",
    "MIT License": "MIT",
    "Python Software Foundation License": "PSF-2.0",
    "zlib/libpng License": "Zlib",
}
SOURCE_LICENSE_MARKERS = {
    "MIT License": "MIT",
    "Apache License": "Apache-2.0",
    "BSD 3-Clause License": "BSD-3-Clause",
    "ISC License": "ISC",
    "Python Software Foundation License": "PSF-2.0",
}


class LicenseValidationError(RuntimeError):
    """Raised when license evidence is absent, invalid, or disallowed."""


@dataclass(frozen=True)
class LockedPackage:
    """One exact dependency pin and its admitted SHA-256 artifact closure."""

    name: str
    version: str
    sha256_hashes: frozenset[str]


@dataclass(frozen=True)
class LockedArtifact:
    """One PyPI artifact whose identity and digest are bound to the lock."""

    filename: str
    url: str
    sha256: str
    size: int


def _normalize_package_name(name: str) -> str:
    """Return the PEP 503 comparison key for one distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _read_bounded(response: object, limit: int) -> bytes:
    """Read a bounded response without accepting an oversized metadata body."""
    payload = bytearray()
    while len(payload) <= limit:
        chunk = response.read(min(64 * 1024, limit + 1 - len(payload)))  # type: ignore[attr-defined]
        if not chunk:
            return bytes(payload)
        payload.extend(chunk)
    raise LicenseValidationError("license evidence exceeded the bounded response size")


def _https_url(url: str, allowed_host: str) -> str:
    """Validate one HTTPS URL against one exact host and default port."""
    try:
        parsed = urllib.parse.urlparse(url)
        parsed_port = parsed.port
    except ValueError as exc:
        raise LicenseValidationError(f"untrusted license evidence URL: {url}") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != allowed_host
        or parsed.username is not None
        or parsed.password is not None
        or parsed_port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise LicenseValidationError(f"untrusted license evidence URL: {url}")
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Reject redirects so license evidence cannot change its source host."""

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        """Fail closed on a redirect from the pinned metadata endpoint."""
        raise LicenseValidationError("license evidence URL redirected")


def _opener() -> Any:
    """Build the no-proxy, no-redirect opener used for license evidence."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _fetch_json(url: str) -> dict[str, object]:
    """Fetch one bounded PyPI metadata object without following redirects."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with _opener().open(request, timeout=20) as response:
        payload = _read_bounded(response, MAX_METADATA_BYTES)
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise LicenseValidationError("PyPI license evidence was not an object")
    return value


def _finalize_lock_block(
    block: list[str],
    packages: list[LockedPackage],
    seen_names: set[str],
) -> None:
    """Validate one logical pip-compile requirement block."""
    joined = " ".join(part.rstrip("\\").strip() for part in block)
    match = PACKAGE_LINE.match(joined)
    if match is None:
        raise LicenseValidationError(f"unrecognized requirements.lock line: {block[0]}")
    name = match["name"]
    version = match["version"]
    digests = frozenset(
        digest.lower() for digest in HASH_OPTION.findall(joined)
    )
    if not digests:
        raise LicenseValidationError(f"package {name}=={version} has no SHA-256 closure")

    remainder = joined[match.end() :]
    remainder = HASH_OPTION.sub("", remainder).replace("\\", "").strip()
    if remainder:
        raise LicenseValidationError(
            f"unrecognized requirements.lock option for {name}=={version}: {remainder}"
        )

    normalized_name = _normalize_package_name(name)
    if normalized_name in seen_names:
        raise LicenseValidationError(f"duplicate package pin for {normalized_name}")
    seen_names.add(normalized_name)
    packages.append(LockedPackage(name, version, digests))


def parse_locked_packages(lock_text: str) -> tuple[LockedPackage, ...]:
    """Return exact package pins bound to their SHA-256 artifact closures."""
    packages: list[LockedPackage] = []
    seen_names: set[str] = set()
    block: list[str] = []

    for raw_line in lock_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if PACKAGE_LINE.match(line):
            if block:
                _finalize_lock_block(block, packages, seen_names)
            block = [line]
        elif line.startswith("--hash=sha256:"):
            if not block:
                raise LicenseValidationError("orphan SHA-256 hash in requirements.lock")
            block.append(line)
        else:
            raise LicenseValidationError(f"unrecognized requirements.lock line: {line}")

        if not line.endswith("\\"):
            _finalize_lock_block(block, packages, seen_names)
            block = []

    if block:
        _finalize_lock_block(block, packages, seen_names)
    if not packages:
        raise LicenseValidationError("requirements.lock contains no pinned packages")
    return tuple(packages)


def select_locked_artifact(
    package: LockedPackage,
    metadata: dict[str, object],
) -> LockedArtifact:
    """Select one wheel or sdist whose PyPI digest is admitted by the lock."""
    info = metadata.get("info")
    if not isinstance(info, dict):
        raise LicenseValidationError(
            f"PyPI metadata identity mismatch for {package.name}=={package.version}"
        )
    metadata_name = info.get("name")
    metadata_version = info.get("version")
    if (
        not isinstance(metadata_name, str)
        or _normalize_package_name(metadata_name) != _normalize_package_name(package.name)
        or metadata_version != package.version
    ):
        raise LicenseValidationError(
            f"PyPI metadata identity mismatch for {package.name}=={package.version}"
        )

    urls = metadata.get("urls")
    if not isinstance(urls, list):
        raise LicenseValidationError(
            f"PyPI metadata has no artifact list for {package.name}=={package.version}"
        )
    candidates = [
        item
        for package_type in ("bdist_wheel", "sdist")
        for item in urls
        if isinstance(item, dict) and item.get("packagetype") == package_type
    ]
    for item in candidates:
        filename = item.get("filename")
        url = item.get("url")
        size = item.get("size")
        digests = item.get("digests")
        if (
            not isinstance(filename, str)
            or not isinstance(url, str)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or not 0 < size <= MAX_ARTIFACT_BYTES
            or not isinstance(digests, dict)
        ):
            continue
        try:
            host = urllib.parse.urlparse(url).hostname
        except ValueError as exc:
            raise LicenseValidationError(f"untrusted license evidence URL: {url}") from exc
        if host not in PYPI_HOSTS:
            raise LicenseValidationError(f"untrusted license evidence URL: {url}")
        _https_url(url, host)
        digest = digests.get("sha256")
        if (
            isinstance(digest, str)
            and re.fullmatch(r"[0-9a-fA-F]{64}", digest)
            and digest.lower() in package.sha256_hashes
        ):
            return LockedArtifact(filename, url, digest.lower(), size)
    raise LicenseValidationError(
        f"no hash-bound PyPI artifact for {package.name}=={package.version}"
    )


def _download_locked_artifact(artifact: LockedArtifact) -> bytes:
    """Download one bounded artifact and recheck its size and SHA-256 digest."""
    try:
        host = urllib.parse.urlparse(artifact.url).hostname
    except ValueError as exc:
        raise LicenseValidationError(
            f"untrusted license evidence URL: {artifact.url}"
        ) from exc
    if host not in PYPI_HOSTS:
        raise LicenseValidationError(f"untrusted license evidence URL: {artifact.url}")
    _https_url(artifact.url, host)
    request = urllib.request.Request(artifact.url)
    with _opener().open(request, timeout=30) as response:
        payload = _read_bounded(response, MAX_ARTIFACT_BYTES)
    if len(payload) != artifact.size:
        raise LicenseValidationError(
            f"artifact size mismatch for {artifact.filename}: expected {artifact.size}, got {len(payload)}"
        )
    digest = hashlib.sha256(payload).hexdigest()
    if digest != artifact.sha256:
        raise LicenseValidationError(
            f"artifact digest mismatch for {artifact.filename}"
        )
    return payload


def _metadata_from_artifact(payload: bytes, filename: str) -> Message:
    """Extract one bounded wheel or source-distribution METADATA document."""
    metadata_bytes: bytes | None = None
    try:
        if filename.endswith(".whl"):
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                names = [
                    name
                    for name in archive.namelist()
                    if name.endswith(".dist-info/METADATA")
                ]
                if len(names) != 1:
                    raise LicenseValidationError(
                        "wheel has no unique dist-info METADATA"
                    )
                info = archive.getinfo(names[0])
                if info.file_size > MAX_LICENSE_METADATA_BYTES:
                    raise LicenseValidationError(
                        "wheel license metadata is oversized"
                    )
                metadata_bytes = archive.read(info)
        elif filename.endswith((".tar.gz", ".tar.bz2", ".tar.xz", ".tgz")):
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
                members = [
                    member
                    for member in archive.getmembers()
                    if member.isfile() and member.name.endswith("/PKG-INFO")
                ]
                if len(members) != 1 or members[0].size > MAX_LICENSE_METADATA_BYTES:
                    raise LicenseValidationError(
                        "source distribution has invalid PKG-INFO"
                    )
                extracted = archive.extractfile(members[0])
                if extracted is None:
                    raise LicenseValidationError(
                        "source distribution PKG-INFO is unreadable"
                    )
                metadata_bytes = extracted.read(MAX_LICENSE_METADATA_BYTES + 1)
                if len(metadata_bytes) > MAX_LICENSE_METADATA_BYTES:
                    raise LicenseValidationError(
                        "source license metadata is oversized"
                    )
    except (tarfile.TarError, zipfile.BadZipFile, KeyError, OSError) as exc:
        raise LicenseValidationError(
            f"artifact metadata container is invalid: {filename}"
        ) from exc
    if metadata_bytes is None:
        raise LicenseValidationError(f"unsupported PyPI artifact type: {filename}")
    return BytesParser().parsebytes(metadata_bytes)


def _validate_spdx_expression(expression: str) -> str:
    """Validate a bounded SPDX expression containing only approved licenses."""
    value = expression.strip()
    if not value:
        raise LicenseValidationError("incomplete SPDX expression")
    tokens = SPDX_TOKEN.findall(value)
    residual = SPDX_TOKEN.sub("", value)
    if residual.strip():
        raise LicenseValidationError(f"disallowed SPDX expression: {value}")

    expect_operand = True
    depth = 0
    for token in tokens:
        if expect_operand:
            if token == "(":
                depth += 1
                continue
            if token in {"AND", "OR", ")"}:
                raise LicenseValidationError("incomplete SPDX expression")
            if token not in ALLOWED_SPDX:
                raise LicenseValidationError(f"disallowed SPDX license: {token}")
            expect_operand = False
        else:
            if token == ")":
                if depth < 1:
                    raise LicenseValidationError("incomplete SPDX expression")
                depth -= 1
                continue
            if token not in {"AND", "OR"}:
                raise LicenseValidationError("incomplete SPDX expression")
            expect_operand = True
    if expect_operand or depth:
        raise LicenseValidationError("incomplete SPDX expression")
    return value


def _license_from_metadata(metadata: Message) -> str:
    """Return one approved SPDX expression from package metadata."""
    expressions = [
        value.strip()
        for value in metadata.get_all("License-Expression", [])
        if value.strip()
    ]
    if expressions:
        if len(set(expressions)) != 1:
            raise LicenseValidationError("ambiguous SPDX license expressions")
        return _validate_spdx_expression(expressions[0])

    licenses = [
        value.strip()
        for value in metadata.get_all("License", [])
        if value.strip() and value.strip().upper() != "UNKNOWN"
    ]
    if licenses:
        if len(set(licenses)) != 1:
            raise LicenseValidationError("ambiguous package license metadata")
        return _validate_spdx_expression(licenses[0])

    mapped_classifiers = {
        CLASSIFIER_TO_SPDX[classifier.removeprefix("License :: OSI Approved :: ")]
        for classifier in metadata.get_all("Classifier", [])
        if classifier.removeprefix("License :: OSI Approved :: ")
        in CLASSIFIER_TO_SPDX
    }
    if len(mapped_classifiers) != 1:
        raise LicenseValidationError("package license metadata is missing or ambiguous")
    return mapped_classifiers.pop()


def _artifact_license(package: LockedPackage, metadata: dict[str, object]) -> str:
    """Download a lock-bound artifact and return its approved SPDX license."""
    artifact = select_locked_artifact(package, metadata)
    parsed = _metadata_from_artifact(
        _download_locked_artifact(artifact),
        artifact.filename,
    )
    parsed_name = parsed.get("Name")
    parsed_version = parsed.get("Version")
    if (
        not isinstance(parsed_name, str)
        or _normalize_package_name(parsed_name)
        != _normalize_package_name(package.name)
        or parsed_version != package.version
    ):
        raise LicenseValidationError(
            f"artifact metadata identity mismatch for {package.name}=={package.version}"
        )
    return _license_from_metadata(parsed)


def validate_source_license(root: pathlib.Path) -> str:
    """Validate the pinned source tree's declared license before execution."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise LicenseValidationError(
            "contextual-orchestrator source lacks pyproject.toml"
        )
    pyproject.read_bytes()
    for candidate in (
        root / "LICENSE",
        root / "LICENSE.txt",
        root / "LICENSE.md",
    ):
        if candidate.is_file():
            content = candidate.read_text(encoding="utf-8", errors="replace")
            for marker, spdx in SOURCE_LICENSE_MARKERS.items():
                if marker in content:
                    return spdx
    raise LicenseValidationError(
        "source license evidence is missing or not approved"
    )


def validate_tree(root: pathlib.Path) -> dict[str, str]:
    """Validate source and every exact dependency before any installation."""
    source_license = validate_source_license(root)
    packages = parse_locked_packages(
        (root / "requirements.lock").read_text(encoding="utf-8")
    )
    result = {"contextual-orchestrator": source_license}
    for package in packages:
        normalized = _normalize_package_name(package.name)
        url = _https_url(
            "https://pypi.org/pypi/"
            f"{urllib.parse.quote(normalized, safe='')}/"
            f"{urllib.parse.quote(package.version, safe='')}/json",
            "pypi.org",
        )
        result[f"{package.name}=={package.version}"] = _artifact_license(
            package,
            _fetch_json(url),
        )
    return result


def main() -> int:
    """Validate one contextual-orchestrator checkout and print evidence."""
    parser = argparse.ArgumentParser()
    parser.add_argument("repository_root", type=pathlib.Path)
    args = parser.parse_args()
    try:
        licenses = validate_tree(args.repository_root.resolve())
    except (
        OSError,
        ValueError,
        KeyError,
        LicenseValidationError,
        json.JSONDecodeError,
    ) as exc:
        print(f"LICENSE_VALIDATION_FAILED: {exc}")
        return 1
    print(
        "LICENSE_VALIDATION_OK: "
        f"{len(licenses)} source and dependency licenses verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
