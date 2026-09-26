#!/usr/bin/env python3
"""Transport every same-attempt release scope archive into trusted gate storage."""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import json
import re
import stat
import sys
import tempfile
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, BinaryIO, Callable, Iterable, Mapping

try:
    from scripts.ci.verify_release_distribution_set import (
        DIGEST_RE, MAX_ARCHIVE_BYTES, MAX_CONTROL_BYTES, NAME_RE, RECORD_MEMBERS,
        DistributionSetError, _archive, _artifact, _json_bytes, _members, _timestamp,
        fetch_artifact,
    )
except ImportError:  # pragma: no cover - trusted direct `python3 -I` invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from verify_release_distribution_set import (
        DIGEST_RE, MAX_ARCHIVE_BYTES, MAX_CONTROL_BYTES, NAME_RE, RECORD_MEMBERS,
        DistributionSetError, _archive, _artifact, _json_bytes, _members, _timestamp,
        fetch_artifact,
    )

SCOPE_KEYS = {"schema_version", "source_repository", "source_sha", "control_sha",
              "run_id", "run_attempt", "evidence"}
EVIDENCE_KEYS = {"leg", "artifact_id", "artifact_name", "artifact_digest"}
ARCHIVE_KEYS = {"file", "size", "sha256", "name", "version"}


def _build_python_snapshot(folder: Path, leg: str, source_sha: str,
                           members: Mapping[str, str]) -> None:
    first = _json_bytes((folder / f"{leg}.build-first.json").read_bytes())
    second = _json_bytes((folder / f"{leg}.build-second.json").read_bytes())
    snapshot = folder / f"{leg}.build-python.zip"
    digest = members[snapshot.name]
    for receipt, build_pass in ((first, "first"), (second, "second")):
        if (not isinstance(receipt, Mapping) or receipt.get("source_sha") != source_sha
                or receipt.get("leg") != leg or receipt.get("pass") != build_pass
                or receipt.get("python_snapshot_sha256") != digest):
            raise DistributionSetError(f"{leg}: build snapshot receipt differs from selected run")
    if first.get("python_packages") != second.get("python_packages"):
        raise DistributionSetError(f"{leg}: repeated build package inventories differ")
    packages = first["python_packages"]
    if not isinstance(packages, list) or not packages:
        raise DistributionSetError(f"{leg}: build package inventory is missing")
    expected: dict[str, tuple[int, str]] = {}
    total = 0
    for package in packages:
        if (not isinstance(package, Mapping) or set(package) != {"name", "version", "files"}
                or not isinstance(package["name"], str)
                or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", package["name"]) is None
                or not isinstance(package["version"], str) or not package["version"]
                or not isinstance(package["files"], list) or not package["files"]):
            raise DistributionSetError(f"{leg}: build package inventory is malformed")
        for file in package["files"]:
            if not isinstance(file, Mapping) or set(file) != {"path", "size", "sha256"}:
                raise DistributionSetError(f"{leg}: build file inventory is malformed")
            path = file["path"]
            if (not isinstance(path, str) or not path or len(path) > 512
                    or path.startswith("/") or "\\" in path
                    or str(PurePosixPath(path)) != path or ".." in PurePosixPath(path).parts
                    or not isinstance(file["sha256"], str)
                    or re.fullmatch(r"[0-9a-f]{64}", file["sha256"]) is None
                    or type(file["size"]) is not int or file["size"] < 0):
                raise DistributionSetError(f"{leg}: build file inventory is malformed")
            name = f"{package['name']}/{path}"
            if name in expected:
                raise DistributionSetError(f"{leg}: duplicate build snapshot file")
            expected[name] = (file["size"], file["sha256"])
            total += file["size"]
            if len(expected) > 50_000 or total > MAX_ARCHIVE_BYTES:
                raise DistributionSetError(f"{leg}: build snapshot exceeds size limit")
    with zipfile.ZipFile(snapshot) as archive:
        entries = archive.infolist()
        if len(entries) != len(expected) or {entry.filename for entry in entries} != set(expected):
            raise DistributionSetError(f"{leg}: build snapshot members differ from receipt")
        for entry in entries:
            mode = entry.external_attr >> 16
            size, sha = expected[entry.filename]
            if (entry.is_dir() or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                    or entry.file_size != size):
                raise DistributionSetError(f"{leg}: build snapshot member is unsafe")
            with archive.open(entry) as stream:
                actual = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    actual.update(block)
                if actual.hexdigest() != sha:
                    raise DistributionSetError(f"{leg}: build snapshot file differs from receipt")


def _wheel_identity(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as archive:
        metadata = [item for item in archive.infolist()
                    if item.filename.endswith(".dist-info/METADATA")
                    and len(PurePosixPath(item.filename).parts) == 2]
        if len(metadata) != 1 or metadata[0].file_size > 1024 * 1024:
            raise DistributionSetError("runtime wheel metadata is missing or oversized")
        with archive.open(metadata[0]) as source:
            payload = source.read(1024 * 1024 + 1)
    try:
        headers = email.parser.Parser().parsestr(payload.decode("utf-8"))
    except UnicodeError as error:
        raise DistributionSetError("runtime wheel metadata is not UTF-8") from error
    names, versions = headers.get_all("Name", []), headers.get_all("Version", [])
    if len(names) != 1 or len(versions) != 1:
        raise DistributionSetError("runtime wheel metadata has ambiguous identity")
    name = re.sub(r"[-_.]+", "-", names[0]).lower()
    version = versions[0]
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or not version:
        raise DistributionSetError("runtime wheel metadata has no project identity")
    return name, version


def _consumer_wheel_evidence(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Recompute the consumer wheel metadata and sole native extension hashes."""
    metadata: dict[str, str] = {}
    native_members: set[str] = set()
    extension: dict[str, str] | None = None
    magic = (b"\x7fELF", b"MZ", b"\x00asm", b"!<arch>\n",
             b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",
             b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
             b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf",
             b"\xbe\xba\xfe\xca", b"\xbf\xba\xfe\xca")
    total = 0
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) != len({entry.filename for entry in entries}):
                raise DistributionSetError("consumer wheel has duplicate members")
            for entry in entries:
                member = PurePosixPath(entry.filename)
                mode = entry.external_attr >> 16
                if (not entry.filename or entry.filename.startswith("/")
                        or "\\" in entry.filename or str(member) != entry.filename
                        or ".." in member.parts or entry.is_dir() or stat.S_ISLNK(mode)
                        or stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                    raise DistributionSetError("consumer wheel has an unsafe member")
                total += entry.file_size
                if total > MAX_ARCHIVE_BYTES:
                    raise DistributionSetError("consumer wheel members exceed size limit")
                is_metadata = (len(member.parts) == 2
                               and entry.filename.endswith((".dist-info/METADATA", ".dist-info/WHEEL")))
                is_extension = (entry.filename.startswith("fast_mlsirm/_core.")
                                and entry.filename.endswith((".so", ".pyd")))
                digest = hashlib.sha256()
                with archive.open(entry) as source:
                    first = source.read(8)
                    digest.update(first)
                    if is_metadata or is_extension:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(block)
                lower_name = entry.filename.lower()
                if (first.startswith(magic)
                        or re.search(r"\.(?:so(?:\.[0-9]+)*|pyd|dll|dylib|a|lib|exe|wasm)$", lower_name)
                        or ".framework/" in lower_name):
                    native_members.add(entry.filename)
                if is_metadata:
                    metadata[entry.filename] = digest.hexdigest()
                if is_extension:
                    if extension is not None:
                        raise DistributionSetError("consumer wheel has multiple native extensions")
                    extension = {"member": entry.filename, "sha256": digest.hexdigest()}
    except zipfile.BadZipFile as error:
        raise DistributionSetError("consumer receipt differs from selected bytes") from error
    metadata_paths = {PurePosixPath(member) for member in metadata}
    metadata_roots = {path.parent.name for path in metadata_paths}
    if (len(metadata) != 2
            or {path.name for path in metadata_paths} != {"METADATA", "WHEEL"}
            or len(metadata_roots) != 1
            or not next(iter(metadata_roots), "").startswith("fast_mlsirm-")
            or extension is None
            or native_members != {extension["member"]}):
        raise DistributionSetError("consumer wheel metadata or native layout differs")
    return metadata, extension


def _runtime_archives(folder: Path, leg: str, source_sha: str, distribution: Mapping[str, Any],
                      members: Mapping[str, str]) -> list[dict[str, Any]]:
    runtime = _json_bytes((folder / f"{leg}.runtime.json").read_bytes())
    if (not isinstance(runtime, Mapping) or runtime.get("source_sha") != source_sha
            or runtime.get("leg") != leg
            or runtime.get("file") != distribution.get("file")
            or runtime.get("sha256") != distribution.get("sha256")):
        raise DistributionSetError(f"{leg}: runtime receipt differs from distribution")
    archives = runtime.get("archives")
    expected = {name for name in members if name.endswith(".whl")
                and name != f"{leg}.consumer.whl"}
    if not isinstance(archives, list) or not 0 < len(archives) <= 64:
        raise DistributionSetError(f"{leg}: runtime archive set is incomplete")
    seen: set[str] = set()
    for row in archives:
        if (not isinstance(row, Mapping) or set(row) != ARCHIVE_KEYS
                or not isinstance(row["file"], str) or row["file"] in seen
                or row["file"] not in expected
                or type(row["size"]) is not int or row["size"] <= 0
                or not isinstance(row["sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                or not isinstance(row["name"], str)
                or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", row["name"])
                or not isinstance(row["version"], str) or not row["version"]
                or row["sha256"] != members[row["file"]]
                or row["size"] != (folder / row["file"]).stat().st_size
                or _wheel_identity(folder / row["file"]) != (row["name"], row["version"])):
            raise DistributionSetError(f"{leg}: runtime archive differs from selected bytes")
        seen.add(row["file"])
    if seen != expected:
        raise DistributionSetError(f"{leg}: runtime archive set differs from selected members")
    locked = runtime.get("locked_dependencies")
    if (not isinstance(locked, list) or len(locked) != len(archives)
            or not all(isinstance(row, Mapping) and set(row) == {"name", "version"}
                       and isinstance(row["name"], str) and isinstance(row["version"], str)
                       for row in locked)
            or {(row["name"], row["version"]) for row in locked}
            != {(row["name"], row["version"]) for row in archives}):
        raise DistributionSetError(f"{leg}: locked dependency set differs from selected archives")
    return [dict(row) for row in archives]


def verify_scope_evidence_set(
    artifacts: Iterable[Any], attempt: Any, *, repository: str, source_sha: str,
    control_sha: str, run_id: int, run_attempt: int, record_artifact_id: int,
    record_artifact_digest: str, distributions: list[dict[str, Any]],
    fetch: Callable[[str, int, BinaryIO], None], output_dir: Path,
) -> list[dict[str, Any]]:
    """Bind scope members to all thirteen selected distribution legs and ZIPs."""
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or not re.fullmatch(r"[0-9a-f]{40}", source_sha)
            or not re.fullmatch(r"[0-9a-f]{40}", control_sha)
            or type(run_id) is not int or run_id <= 0
            or type(run_attempt) is not int or run_attempt <= 0
            or type(record_artifact_id) is not int or record_artifact_id <= 0
            or not isinstance(record_artifact_digest, str)
            or DIGEST_RE.fullmatch(record_artifact_digest) is None):
        raise DistributionSetError("invalid scope evidence identity")
    if (not isinstance(attempt, Mapping) or attempt.get("id") != run_id
            or attempt.get("run_attempt") != run_attempt
            or attempt.get("head_sha") != control_sha):
        raise DistributionSetError("scope evidence workflow attempt differs")
    started = _timestamp(attempt.get("run_started_at"))
    listed: dict[str, Mapping[str, Any]] = {}
    for item in artifacts:
        if (not isinstance(item, Mapping) or not isinstance(item.get("name"), str)
                or item["name"] in listed):
            raise DistributionSetError("duplicate or invalid scope artifact metadata")
        listed[item["name"]] = item
    if (not isinstance(distributions, list) or len(distributions) != 13
            or not all(isinstance(row, Mapping) and isinstance(row.get("leg"), str)
                       and type(row.get("artifact_id")) is int for row in distributions)
            or len({row["leg"] for row in distributions}) != 13
            or len([row for row in distributions if row["leg"] == "sdist"]) != 1):
        raise DistributionSetError("scope evidence needs thirteen verified distribution legs")
    by_leg = {row["leg"]: row for row in distributions}
    legs = set(by_leg)
    _artifact(listed, "reproducibility-record", record_artifact_id,
              record_artifact_digest, run_id, control_sha, started)
    with _archive(repository, record_artifact_id, record_artifact_digest, fetch) as record:
        _members(record, RECORD_MEMBERS)
        manifest = _json_bytes(record.read("release-scope-evidence-set.json"))
    if not isinstance(manifest, Mapping) or set(manifest) != SCOPE_KEYS:
        raise DistributionSetError("scope evidence set has an unknown shape")
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
            or manifest["source_repository"] != repository
            or manifest["source_sha"] != source_sha
            or manifest["control_sha"] != control_sha
            or manifest["run_id"] != run_id
            or manifest["run_attempt"] != run_attempt):
        raise DistributionSetError("scope evidence set differs from release identity")
    evidence = manifest["evidence"]
    if (not isinstance(evidence, list) or len(evidence) != 13
            or not all(isinstance(row, Mapping) and isinstance(row.get("leg"), str)
                       for row in evidence)
            or {row["leg"] for row in evidence} != legs):
        raise DistributionSetError("scope evidence legs are incomplete")
    names = {f"repro-digest-{leg}" for leg in legs}
    if {name for name in listed if name.startswith("repro-digest-")} != names:
        raise DistributionSetError("scope artifact set is missing or has extras")
    if output_dir.exists() or output_dir.is_symlink():
        raise DistributionSetError("scope evidence output already exists")
    selected: list[dict[str, Any]] = []
    seen_ids = {record_artifact_id} | {row["artifact_id"] for row in distributions}
    with tempfile.TemporaryDirectory(prefix=".scope-evidence-", dir=output_dir.parent) as temporary:
        staging = Path(temporary)
        for row in evidence:
            if not isinstance(row, Mapping) or set(row) != EVIDENCE_KEYS:
                raise DistributionSetError("invalid scope evidence row")
            leg, artifact_id = row["leg"], row["artifact_id"]
            name, digest = row["artifact_name"], row["artifact_digest"]
            if (name != f"repro-digest-{leg}" or type(artifact_id) is not int
                    or artifact_id in seen_ids or not isinstance(digest, str)
                    or DIGEST_RE.fullmatch(digest) is None):
                raise DistributionSetError("scope evidence artifact identity differs")
            _artifact(listed, name, artifact_id, digest, run_id, control_sha, started)
            seen_ids.add(artifact_id)
            folder = staging / name
            folder.mkdir()
            members: dict[str, str] = {}
            with _archive(repository, artifact_id, digest, fetch) as archive:
                entries = archive.infolist()
                expected = {f"{leg}.tsv", f"{leg}.bundle.json",
                            f"{leg}.build-first.json", f"{leg}.build-second.json",
                            f"{leg}.build-python.zip"}
                if leg != "sdist":
                    expected |= {f"{leg}.runtime.json", f"{leg}.runtime-requirements.txt",
                                 f"{leg}.consumer.json", f"{leg}.consumer.whl"}
                member_names = {entry.filename for entry in entries}
                if (len(entries) != len(member_names) or not expected <= member_names
                        or (leg == "sdist" and member_names != expected)
                        or (leg != "sdist" and member_names == expected)
                        or any(not filename.endswith(".whl") for filename in member_names - expected)):
                    raise DistributionSetError(f"{leg}: scope artifact members differ")
                total = 0
                for entry in entries:
                    mode = entry.external_attr >> 16
                    if (NAME_RE.fullmatch(entry.filename) is None or entry.is_dir()
                            or stat.S_ISLNK(mode)
                            or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                            or entry.file_size > (MAX_ARCHIVE_BYTES if entry.filename.endswith((".whl", ".build-python.zip")) else MAX_CONTROL_BYTES)):
                        raise DistributionSetError(f"{leg}: unsafe scope artifact member")
                    total += entry.file_size
                    if total > MAX_ARCHIVE_BYTES:
                        raise DistributionSetError(f"{leg}: scope artifact exceeds size limit")
                    digest_state = hashlib.sha256()
                    with archive.open(entry) as source, (folder / entry.filename).open("xb") as target:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            digest_state.update(block)
                            target.write(block)
                    members[entry.filename] = digest_state.hexdigest()
            _build_python_snapshot(folder, leg, source_sha, members)
            if leg != "sdist":
                consumer = _json_bytes((folder / f"{leg}.consumer.json").read_bytes())
                consumer_metadata, consumer_extension = _consumer_wheel_evidence(
                    folder / f"{leg}.consumer.whl"
                )
                required = {"schema_version", "source_sha", "leg", "build_env", "sdist_file",
                            "sdist_sha256", "file", "published_sha256", "consumer_sha256",
                            "metadata_members", "native_extension", "installation"}
                runtime = _json_bytes((folder / f"{leg}.runtime.json").read_bytes())
                install_keys = {"uv_version", "python_version", "implementation", "sys_platform",
                                "machine", "requirements_sha256", "uv_lock_sha256",
                                "locked_dependencies", "installed"}
                if (not isinstance(consumer, Mapping) or set(consumer) != required
                        or consumer["schema_version"] != 1 or consumer["source_sha"] != source_sha
                        or consumer["leg"] != leg or consumer["sdist_file"] != by_leg["sdist"]["file"]
                        or consumer["sdist_sha256"] != by_leg["sdist"]["sha256"]
                        or consumer["file"] != by_leg[leg]["file"]
                        or consumer["published_sha256"] != by_leg[leg]["sha256"]
                        or consumer["consumer_sha256"] != members[f"{leg}.consumer.whl"]
                        or consumer["metadata_members"] != consumer_metadata
                        or consumer["native_extension"] != consumer_extension
                        or not isinstance(runtime, Mapping)
                        or not install_keys <= runtime.keys()
                        or consumer["installation"] != {
                            **{key: runtime[key] for key in install_keys},
                            "imported_extension": consumer["native_extension"]}):
                    raise DistributionSetError(f"{leg}: sdist consumer receipt differs from selected bytes")
            archives = [] if leg == "sdist" else _runtime_archives(folder, leg, source_sha, by_leg[leg], members)
            selected.append({**dict(row), "members": members, "archives": archives})
        staging.rename(output_dir)
    return selected


def main() -> None:
    parser = argparse.ArgumentParser()
    for option in ("repository", "source-sha", "control-sha", "run-id", "run-attempt",
                   "record-artifact-id", "record-artifact-digest", "verified-distributions",
                   "metadata", "attempt", "output"):
        parser.add_argument(f"--{option}", required=True)
    args = parser.parse_args()
    artifacts = [_json_bytes(line.encode()) for line in Path(args.metadata).read_text().splitlines()]
    attempt = _json_bytes(Path(args.attempt).read_bytes())
    verified = _json_bytes(Path(args.verified_distributions).read_bytes())
    if not isinstance(verified, Mapping) or not isinstance(verified.get("verified_distributions"), list):
        raise DistributionSetError("verified distribution report is malformed")
    result = verify_scope_evidence_set(
        artifacts, attempt, repository=args.repository, source_sha=args.source_sha,
        control_sha=args.control_sha, run_id=int(args.run_id), run_attempt=int(args.run_attempt),
        record_artifact_id=int(args.record_artifact_id),
        record_artifact_digest=args.record_artifact_digest,
        distributions=verified["verified_distributions"],
        fetch=fetch_artifact, output_dir=Path(args.output),
    )
    print(json.dumps({"verified_scope_evidence": result}, sort_keys=True))


if __name__ == "__main__":
    main()
