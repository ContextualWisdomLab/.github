#!/usr/bin/env python3
"""Validate pinned contextual-orchestrator source and dependency licenses."""

from __future__ import annotations

import argparse
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


ALLOWED_SPDX = frozenset(
    {"0BSD", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC", "MIT", "PSF-2.0", "Zlib"}
)
PACKAGE_LINE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)==(?P<version>[^\\s]+)")
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
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != allowed_host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
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


def _fetch_json(url: str) -> dict[str, object]:
    """Fetch one bounded PyPI metadata object without following redirects."""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect()
    )
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with opener.open(request, timeout=20) as response:
        payload = _read_bounded(response, MAX_METADATA_BYTES)
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise LicenseValidationError("PyPI license evidence was not an object")
    return value


def parse_locked_packages(lock_text: str) -> tuple[tuple[str, str], ...]:
    """Return exact package/version pairs from a pip-compile lock."""
    packages: list[tuple[str, str]] = []
    for raw_line in lock_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith("--hash="):
            continue
        match = PACKAGE_LINE.fullmatch(line.rstrip("\\").rstrip())
        if match is None:
            raise LicenseValidationError(f"unrecognized requirements.lock line: {line}")
        packages.append((match["name"], match["version"]))
    if not packages:
        raise LicenseValidationError("requirements.lock contains no pinned packages")
    return tuple(packages)


def _metadata_from_artifact(payload: bytes, filename: str) -> Message:
    """Extract one bounded wheel or source-distribution METADATA document."""
    metadata_bytes: bytes | None = None
    if filename.endswith(".whl"):
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                raise LicenseValidationError("wheel has no unique dist-info METADATA")
            info = archive.getinfo(names[0])
            if info.file_size > MAX_LICENSE_METADATA_BYTES:
                raise LicenseValidationError("wheel license metadata is oversized")
            metadata_bytes = archive.read(info)
    elif filename.endswith((".tar.gz", ".tar.bz2", ".tar.xz", ".tgz")):
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
            members = [member for member in archive.getmembers() if member.name.endswith("/PKG-INFO")]
            if len(members) != 1 or members[0].size > MAX_LICENSE_METADATA_BYTES:
                raise LicenseValidationError("source distribution has invalid PKG-INFO")
            extracted = archive.extractfile(members[0])
            if extracted is None:
                raise LicenseValidationError("source distribution PKG-INFO is unreadable")
            metadata_bytes = extracted.read(MAX_LICENSE_METADATA_BYTES + 1)
            if len(metadata_bytes) > MAX_LICENSE_METADATA_BYTES:
                raise LicenseValidationError("source license metadata is oversized")
    if metadata_bytes is None:
        raise LicenseValidationError(f"unsupported PyPI artifact type: {filename}")
    return BytesParser().parsebytes(metadata_bytes)


def _artifact_license(name: str, version: str, metadata: dict[str, object]) -> str:
    """Fetch and return one allowed SPDX license from a PyPI artifact."""
    urls = metadata.get("urls")
    if not isinstance(urls, list):
        raise LicenseValidationError(f"PyPI metadata has no artifact list for {name}=={version}")
    candidates = [item for item in urls if isinstance(item, dict) and item.get("packagetype") == "bdist_wheel"]
    candidates += [item for item in urls if isinstance(item, dict) and item.get("packagetype") == "sdist"]
    for item in candidates:
        filename = item.get("filename")
        url = item.get("url")
        if not isinstance(filename, str) or not isinstance(url, str):
            continue
        host = "pypi.org" if "pypi.org" in url else "files.pythonhosted.org"
        _https_url(url, host)
        request = urllib.request.Request(url)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=30) as response:
            payload = _read_bounded(response, MAX_ARTIFACT_BYTES)
        parsed = _metadata_from_artifact(payload, filename)
        values = parsed.get_all("License-Expression") or parsed.get_all("License")
        if not values:
            values = [
                CLASSIFIER_TO_SPDX[value.removeprefix("License :: OSI Approved :: ")]
                for value in parsed.get_all("Classifier")
                if value.removeprefix("License :: OSI Approved :: ") in CLASSIFIER_TO_SPDX
            ]
        if len(values) != 1 or values[0].strip() not in ALLOWED_SPDX:
            raise LicenseValidationError(
                f"disallowed or ambiguous license for {name}=={version}: {values or '<missing>'}"
            )
        return values[0].strip()
    raise LicenseValidationError(f"no usable PyPI artifact for {name}=={version}")


def validate_source_license(root: pathlib.Path) -> str:
    """Validate the pinned source tree's declared license before execution."""
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        raise LicenseValidationError("contextual-orchestrator source lacks pyproject.toml")
    pyproject.read_bytes()
    for candidate in (root / "LICENSE", root / "LICENSE.txt", root / "LICENSE.md"):
        if candidate.is_file():
            content = candidate.read_text(encoding="utf-8", errors="replace")
            for marker, spdx in SOURCE_LICENSE_MARKERS.items():
                if marker in content:
                    return spdx
    raise LicenseValidationError("source license evidence is missing or not approved")


def validate_tree(root: pathlib.Path) -> dict[str, str]:
    """Validate source and every exact dependency before any installation."""
    source_license = validate_source_license(root)
    packages = parse_locked_packages((root / "requirements.lock").read_text(encoding="utf-8"))
    result = {"contextual-orchestrator": source_license}
    for name, version in packages:
        normalized = name.lower().replace("_", "-")
        url = _https_url(
            "https://pypi.org/pypi/"
            f"{urllib.parse.quote(normalized, safe='')}/{urllib.parse.quote(version, safe='')}/json",
            "pypi.org",
        )
        result[f"{name}=={version}"] = _artifact_license(name, version, _fetch_json(url))
    return result


def main() -> int:
    """Validate one contextual-orchestrator checkout and print evidence."""
    parser = argparse.ArgumentParser()
    parser.add_argument("repository_root", type=pathlib.Path)
    args = parser.parse_args()
    try:
        licenses = validate_tree(args.repository_root.resolve())
    except (OSError, ValueError, KeyError, LicenseValidationError, json.JSONDecodeError) as exc:
        print(f"LICENSE_VALIDATION_FAILED: {exc}")
        return 1
    print(f"LICENSE_VALIDATION_OK: {len(licenses)} source and dependency licenses verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
