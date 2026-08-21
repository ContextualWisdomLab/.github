"""Reconcile OSV registry findings with exact immutable direct-source evidence."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import stat
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
DIRECT_HEADER_RE = re.compile(
    r"(?m)^  (?P<name>(?:@[^/\s]+/)?[^@\s]+)@(?P<url>https://[^\s]+):[ \t]*$"
)
PACKAGES_SECTION_RE = re.compile(r"(?m)^packages:[ \t]*\n")
TOP_LEVEL_SECTION_RE = re.compile(r"(?m)^[^ \t\r\n#][^:\r\n]*:[^\r\n]*$")
ENTRY_BOUNDARY_RE = re.compile(r"(?m)^  \S")
VERSION_LINE_RE = re.compile(r"(?m)^    version:[ \t]*['\"]?([^'\"\s]+)['\"]?[ \t]*$")
TARBALL_RE = re.compile(r"(?:^|[, {])[ \t]*tarball:[ \t]*([^, }]+)")
INTEGRITY_RE = re.compile(r"(?:^|[, {])[ \t]*integrity:[ \t]*(sha512-[A-Za-z0-9+/=]+)")
AFFECTED_RANGE_RE = re.compile(
    r"^[ \t]*(?P<operator><=|<)[ \t]*(?P<version>\d+\.\d+\.\d+)[ \t]*$"
)
SHEETJS_EXCEPTION_VERSION = "0.20.3"
SHEETJS_URL_RE = re.compile(
    r"^/xlsx-(?P<version>\d+\.\d+\.\d+)/xlsx-(?P=version)\.tgz$"
)


@dataclass(frozen=True)
class DirectSource:
    """Evidence parsed from one pnpm direct-tarball package record."""

    package_name: str
    version: str
    source_url: str
    integrity: str
    valid: bool
    reason: str


def parse_semver(value: str) -> tuple[int, int, int] | None:
    """Parse a strict three-component SemVer core."""

    match = SEMVER_RE.fullmatch(value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def valid_sha512_integrity(value: str) -> bool:
    """Return whether an integrity string contains one exact SHA-512 digest."""

    if not value.startswith("sha512-"):
        return False
    try:
        decoded = base64.b64decode(value.removeprefix("sha512-"), validate=True)
    except (ValueError, binascii.Error):
        return False
    return len(decoded) == 64


def validate_sheetjs_source(
    package_name: str,
    header_url: str,
    tarball_url: str,
    version: str,
    integrity: str,
) -> tuple[bool, str]:
    """Validate the exact official immutable SheetJS release identity."""

    if package_name != "xlsx":
        return False, "package is not governed by the SheetJS direct-source contract"
    try:
        parsed = urlsplit(header_url)
        parsed_port = parsed.port
    except ValueError:
        return False, "direct source URL is malformed"
    if (
        parsed.scheme != "https"
        or parsed.hostname != "cdn.sheetjs.com"
        or parsed_port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return False, "direct source is not the canonical SheetJS HTTPS origin"
    path_match = SHEETJS_URL_RE.fullmatch(parsed.path)
    if not path_match or path_match.group("version") != version:
        return False, "package version does not match the immutable SheetJS URL"
    if header_url != tarball_url:
        return False, "pnpm package key and resolution tarball disagree"
    if not valid_sha512_integrity(integrity):
        return False, "direct source lacks one valid SHA-512 integrity receipt"
    return True, "exact official immutable SheetJS release"


def parse_direct_sources(lock_text: str) -> list[DirectSource]:
    """Parse direct HTTPS package records from pnpm's ``packages`` map.

    pnpm v9 repeats direct-tarball keys in ``snapshots``.  Snapshot entries
    describe dependency edges and do not carry resolution provenance, so
    parsing only the ``packages`` map prevents a false duplicate-source
    conflict while retaining conflicting package metadata as a finding.
    """

    sources: list[DirectSource] = []
    for packages_section in PACKAGES_SECTION_RE.finditer(lock_text):
        section_start = packages_section.end()
        next_section = TOP_LEVEL_SECTION_RE.search(lock_text, section_start)
        section_end = next_section.start() if next_section else len(lock_text)
        package_text = lock_text[section_start:section_end]
        matches = list(DIRECT_HEADER_RE.finditer(package_text))
        for match in matches:
            start = match.end()
            boundary = ENTRY_BOUNDARY_RE.search(package_text, start)
            end = boundary.start() if boundary else len(package_text)
            block = package_text[start:end]
            version_match = VERSION_LINE_RE.search(block)
            tarball_match = TARBALL_RE.search(block)
            integrity_match = INTEGRITY_RE.search(block)
            version = version_match.group(1) if version_match else ""
            tarball = tarball_match.group(1) if tarball_match else ""
            integrity = integrity_match.group(1) if integrity_match else ""
            valid, reason = validate_sheetjs_source(
                match.group("name"), match.group("url"), tarball, version, integrity
            )
            sources.append(
                DirectSource(
                    package_name=match.group("name"),
                    version=version,
                    source_url=match.group("url"),
                    integrity=integrity,
                    valid=valid,
                    reason=reason,
                )
            )
    return sources


def iter_result_packages(
    payload: dict[str, Any],
) -> Iterable[tuple[str | None, dict[str, Any]]]:
    """Yield each scanner source path with its package findings."""

    results = payload.get("results")
    if not isinstance(results, list):
        raise TypeError("OSV results must contain a results array")
    for result in results:
        if not isinstance(result, dict):
            raise TypeError("OSV result entries must be objects")
        source = result.get("source")
        observed_source_path = (
            source.get("path")
            if isinstance(source, dict) and isinstance(source.get("path"), str)
            else None
        )
        packages = result.get("packages") or []
        if not isinstance(packages, list):
            raise TypeError("OSV result packages must be an array")
        for package in packages:
            if not isinstance(package, dict):
                raise TypeError("OSV package entries must be objects")
            yield observed_source_path, package


def iter_packages(payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Yield package findings from an OSV Scanner result document."""

    for _, package in iter_result_packages(payload):
        yield package


def validate_source_path(source_path: str) -> str:
    """Return one normalized repository-relative governed lockfile path."""

    candidate = PurePosixPath(source_path)
    if (
        not source_path
        or candidate.is_absolute()
        or "\\" in source_path
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise ValueError("governed OSV source path must be one normalized relative path")
    return candidate.as_posix()


def source_matches_governed_lockfile(
    observed_source_path: str | None, governed_source_path: str
) -> bool:
    """Bind a scanner result to the exact governed workspace lockfile."""

    governed = validate_source_path(governed_source_path)
    return observed_source_path in {
        governed,
        f"/github/workspace/{governed}",
    }


def authoritative_affected_range(
    vulnerability: dict[str, Any], package_name: str
) -> str | None:
    """Return one GitHub-reviewed npm affected bound with live OSV shape."""

    vulnerability_id = vulnerability.get("id")
    affected = vulnerability.get("affected")
    if not isinstance(vulnerability_id, str) or not isinstance(affected, list):
        return None
    candidates: list[str] = []
    for item in affected:
        if not isinstance(item, dict):
            continue
        package = item.get("package")
        database_specific = item.get("database_specific")
        ranges = item.get("ranges")
        if (
            not isinstance(package, dict)
            or package.get("ecosystem") != "npm"
            or package.get("name") != package_name
            or not isinstance(database_specific, dict)
            or not isinstance(ranges, list)
        ):
            continue
        affected_range = database_specific.get("last_known_affected_version_range")
        source = database_specific.get("source")
        expected_source_fragment = f"/{vulnerability_id}/{vulnerability_id}.json"
        if (
            not isinstance(affected_range, str)
            or not isinstance(source, str)
            or not source.startswith(
                "https://github.com/github/advisory-database/blob/"
            )
            or not source.endswith(expected_source_fragment)
        ):
            continue
        semver_ranges = [
            range_item
            for range_item in ranges
            if isinstance(range_item, dict) and range_item.get("type") == "SEMVER"
        ]
        if len(semver_ranges) != 1:
            continue
        events = semver_ranges[0].get("events")
        if events != [{"introduced": "0"}]:
            continue
        candidates.append(affected_range)
    return candidates[0] if len(set(candidates)) == 1 and candidates else None


def audit_entry(
    *,
    label: str,
    source: DirectSource,
    package_name: str,
    package_version: str,
    vulnerability: dict[str, Any],
    affected_range: str | None,
    status: str,
    reason: str,
) -> dict[str, str]:
    """Build one stable audit record without copying advisory prose."""

    return {
        "scan": label,
        "status": status,
        "reason": reason,
        "package": package_name,
        "version": package_version,
        "vulnerability_id": str(vulnerability.get("id") or "unknown"),
        "affected_range": affected_range or "unknown",
        "source_url": source.source_url,
        "integrity": source.integrity or "missing",
    }


def reconcile_payload(
    payload: dict[str, Any],
    lock_text: str,
    *,
    label: str,
    source_path: str = "pnpm-lock.yaml",
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Remove only findings disproven by exact source and affected-range evidence."""

    direct_sources = parse_direct_sources(lock_text)
    audit: list[dict[str, str]] = []
    governed_source_path = validate_source_path(source_path)
    for observed_source_path, package in iter_result_packages(payload):
        package_info = package.get("package")
        vulnerabilities = package.get("vulnerabilities") or []
        if not isinstance(package_info, dict) or not isinstance(vulnerabilities, list):
            raise TypeError("OSV package evidence is malformed")
        package_name = str(package_info.get("name") or "")
        package_version = str(package_info.get("version") or "")
        if not source_matches_governed_lockfile(
            observed_source_path, governed_source_path
        ):
            if package_name != "xlsx":
                continue
            source = DirectSource(
                package_name=package_name,
                version=package_version,
                source_url="",
                integrity="",
                valid=False,
                reason="OSV finding source does not match governed lockfile",
            )
            for vulnerability in vulnerabilities:
                if not isinstance(vulnerability, dict):
                    raise TypeError("OSV vulnerability entries must be objects")
                audit.append(
                    audit_entry(
                        label=label,
                        source=source,
                        package_name=package_name,
                        package_version=package_version,
                        vulnerability=vulnerability,
                        affected_range=authoritative_affected_range(
                            vulnerability, package_name
                        ),
                        status="SCANNER_METADATA_CONFLICT",
                        reason=source.reason,
                    )
                )
            continue
        candidates = [
            source
            for source in direct_sources
            if source.package_name == package_name
            and (source.version == package_version or not source.version)
        ]
        if not candidates and package_name != "xlsx":
            continue
        if len(candidates) != 1:
            source = candidates[0] if candidates else DirectSource(
                package_name=package_name,
                version=package_version,
                source_url="",
                integrity="",
                valid=False,
                reason="no unique direct-source provenance matches package and version"
                if not candidates
                else "multiple direct-source records match package and version",
            )
            reason = (
                "no unique direct-source provenance matches package and version"
                if not candidates
                else "multiple direct-source records match package and version"
            )
            retained = []
            for vulnerability in vulnerabilities:
                if not isinstance(vulnerability, dict):
                    raise TypeError("OSV vulnerability entries must be objects")
                retained.append(vulnerability)
                audit.append(
                    audit_entry(
                        label=label,
                        source=source,
                        package_name=package_name,
                        package_version=package_version,
                        vulnerability=vulnerability,
                        affected_range=authoritative_affected_range(
                            vulnerability, package_name
                        ),
                        status="SCANNER_METADATA_CONFLICT",
                        reason=reason,
                    )
                )
            package["vulnerabilities"] = retained
            continue
        source = candidates[0]
        retained: list[dict[str, Any]] = []
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                raise TypeError("OSV vulnerability entries must be objects")
            affected_range = authoritative_affected_range(
                vulnerability, package_name
            )
            if not source.valid:
                retained.append(vulnerability)
                audit.append(
                    audit_entry(
                        label=label,
                        source=source,
                        package_name=package_name,
                        package_version=package_version,
                        vulnerability=vulnerability,
                        affected_range=affected_range,
                        status="SCANNER_METADATA_CONFLICT",
                        reason=source.reason,
                    )
                )
                continue
            range_match = AFFECTED_RANGE_RE.fullmatch(affected_range or "")
            version_key = parse_semver(package_version)
            upper_key = (
                parse_semver(range_match.group("version")) if range_match else None
            )
            if version_key is None or upper_key is None:
                retained.append(vulnerability)
                audit.append(
                    audit_entry(
                        label=label,
                        source=source,
                        package_name=package_name,
                        package_version=package_version,
                        vulnerability=vulnerability,
                        affected_range=affected_range,
                        status="SCANNER_METADATA_CONFLICT",
                        reason="advisory lacks one machine-checkable affected upper bound",
                    )
                )
                continue
            inside_affected_range = (
                version_key <= upper_key
                if range_match.group("operator") == "<="
                else version_key < upper_key
            )
            if package_version != SHEETJS_EXCEPTION_VERSION:
                retained.append(vulnerability)
                if inside_affected_range:
                    status = "AFFECTED"
                    reason = "exact direct-source version remains inside the affected range"
                else:
                    status = "SCANNER_METADATA_CONFLICT"
                    reason = (
                        "direct-source reconciliation is limited to immutable "
                        "SheetJS xlsx@0.20.3"
                    )
                audit.append(
                    audit_entry(
                        label=label,
                        source=source,
                        package_name=package_name,
                        package_version=package_version,
                        vulnerability=vulnerability,
                        affected_range=affected_range,
                        status=status,
                        reason=reason,
                    )
                )
                continue
            if inside_affected_range:
                retained.append(vulnerability)
                status = "AFFECTED"
                reason = "exact direct-source version remains inside the affected range"
            else:
                status = "RECONCILED"
                reason = "exact immutable direct-source version is outside the affected range"
            audit.append(
                audit_entry(
                    label=label,
                    source=source,
                    package_name=package_name,
                    package_version=package_version,
                    vulnerability=vulnerability,
                    affected_range=affected_range,
                    status=status,
                    reason=reason,
                )
            )
        package["vulnerabilities"] = retained
    return payload, audit


def atomic_json_write(path: Path, value: object) -> None:
    """Write JSON through a same-directory temporary regular file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_json_object(path: Path) -> dict[str, Any]:
    """Load one JSON object from a regular non-symlink file."""

    value = json.loads(read_utf8_text(path, "required JSON input"))
    if not isinstance(value, dict):
        raise TypeError(f"required JSON input is not an object: {path}")
    return value


def _read_regular_utf8_text(path: Path, description: str) -> str:
    """Read one regular file through a descriptor that cannot follow symlinks.

    Lockfiles and scanner receipts are attacker-controlled repository inputs.
    Opening with ``O_NOFOLLOW`` and checking the descriptor's type closes the
    check/use gap between path validation and the actual read.
    """

    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise ValueError("secure regular-file reads require O_NOFOLLOW support")
    descriptor: int | None = None
    try:
        descriptor = os.open(os.fspath(path), os.O_RDONLY | no_follow)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"{description} is not a regular file: {path}")
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            descriptor = None
            return handle.read()
    except FileNotFoundError as error:
        raise ValueError(f"{description} is not a regular file: {path}") from error
    except UnicodeDecodeError as error:
        raise ValueError(f"{description} is not valid UTF-8: {path}") from error
    except OSError as error:
        raise ValueError(f"{description} is not a regular file: {path}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def read_utf8_text(path: Path, description: str) -> str:
    """Read trusted text input and turn malformed UTF-8 into an explicit error."""

    return _read_regular_utf8_text(path, description)


def read_optional_utf8_text(path: Path, description: str) -> str | None:
    """Read an existing regular file, returning ``None`` only when absent."""

    try:
        return read_utf8_text(path, description)
    except ValueError as error:
        if isinstance(error.__cause__, FileNotFoundError):
            return None
        raise


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--lockfile", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--label", default="scan")
    parser.add_argument("--source-path", default="pnpm-lock.yaml")
    return parser.parse_args()


def main() -> int:
    """Reconcile one OSV document and publish append-only audit evidence."""

    try:
        args = parse_args()
        payload = load_json_object(args.results)
        reconciled, new_audit = reconcile_payload(
            payload,
            read_utf8_text(args.lockfile, "pnpm lock provenance input"),
            label=args.label,
            source_path=args.source_path,
        )
        existing_audit: list[dict[str, str]] = []
        audit_text = read_optional_utf8_text(args.audit, "audit input")
        if audit_text is not None:
            loaded_audit = json.loads(audit_text)
            if not isinstance(loaded_audit, list):
                raise ValueError("audit output must contain an array")
            existing_audit = loaded_audit
        atomic_json_write(args.results, reconciled)
        atomic_json_write(args.audit, [*existing_audit, *new_audit])
        for entry in new_audit:
            print(
                "OSV provenance "
                f"{entry['status']}: {entry['package']}@{entry['version']} "
                f"{entry['vulnerability_id']} ({entry['reason']})"
            )
        return 0
    except (TypeError, ValueError) as error:
        print(f"::error::{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
