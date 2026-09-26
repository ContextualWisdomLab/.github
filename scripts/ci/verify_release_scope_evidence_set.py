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


def _runtime_archives(folder: Path, leg: str, source_sha: str, distribution: Mapping[str, Any],
                      members: Mapping[str, str]) -> list[dict[str, Any]]:
    runtime = _json_bytes((folder / f"{leg}.runtime.json").read_bytes())
    if (not isinstance(runtime, Mapping) or runtime.get("source_sha") != source_sha
            or runtime.get("leg") != leg
            or runtime.get("file") != distribution.get("file")
            or runtime.get("sha256") != distribution.get("sha256")):
        raise DistributionSetError(f"{leg}: runtime receipt differs from distribution")
    archives = runtime.get("archives")
    expected = {name for name in members if name.endswith(".whl")}
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
                            f"{leg}.build-first.json", f"{leg}.build-second.json"}
                if leg != "sdist":
                    expected |= {f"{leg}.runtime.json", f"{leg}.runtime-requirements.txt"}
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
                            or entry.file_size > (MAX_ARCHIVE_BYTES if entry.filename.endswith(".whl") else MAX_CONTROL_BYTES)):
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
