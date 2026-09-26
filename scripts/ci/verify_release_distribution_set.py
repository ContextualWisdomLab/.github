#!/usr/bin/env python3
"""Recheck a release distribution set against immutable Actions artifact bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterable, Mapping

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
NAME_RE = re.compile(r"^[A-Za-z0-9_.+-]+$")
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
RECORD_MEMBERS = {
    "reproducibility-record.tsv",
    "release-scope-identities.json",
    "release-gate-distribution-set.json",
}
ROW_KEYS = {"leg", "file", "sha256", "artifact_id", "artifact_name", "artifact_digest"}
MANIFEST_KEYS = {
    "schema_version", "source_repository", "source_sha", "control_sha",
    "run_id", "run_attempt", "distributions",
}
MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024
MAX_CONTROL_BYTES = 16 * 1024 * 1024


class DistributionSetError(ValueError):
    """Refuse an incomplete or unbound release distribution set."""


def _strict_object(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DistributionSetError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise DistributionSetError(f"non-finite JSON value: {value}")


def _json_bytes(data: bytes) -> Any:
    if len(data) > MAX_CONTROL_BYTES:
        raise DistributionSetError("control JSON is too large")
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_strict_object,
                          parse_constant=_reject_constant)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise DistributionSetError("invalid control JSON") from error


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DistributionSetError("missing canonical UTC timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DistributionSetError("invalid UTC timestamp") from error
    if result.utcoffset() is None or result.utcoffset().total_seconds() != 0:
        raise DistributionSetError("timestamp is not UTC")
    return result


def _digest(value: Any) -> str:
    if not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None:
        raise DistributionSetError("missing canonical artifact digest")
    return value


def _artifact(artifacts: Mapping[str, Mapping[str, Any]], name: str, artifact_id: int,
              digest: str, run_id: int, control_sha: str, started: datetime) -> None:
    item = artifacts.get(name)
    if item is None or type(artifact_id) is not int or artifact_id <= 0:
        raise DistributionSetError(f"{name}: missing immutable artifact identity")
    workflow_run = item.get("workflow_run")
    if (type(item.get("id")) is not int or item["id"] != artifact_id
            or item.get("digest") != digest
            or item.get("expired") is not False
            or not isinstance(workflow_run, Mapping)
            or workflow_run.get("id") != run_id
            or workflow_run.get("head_sha") != control_sha
            or _timestamp(item.get("created_at")) <= started):
        raise DistributionSetError(f"{name}: foreign, stale, or changed artifact metadata")


@contextmanager
def _archive(repository: str, artifact_id: int, digest: str,
             fetch: Callable[[str, int, BinaryIO], None]):
    with tempfile.TemporaryFile() as archive:
        fetch(repository, artifact_id, archive)
        if archive.tell() > MAX_ARCHIVE_BYTES:
            raise DistributionSetError("artifact ZIP exceeds the size limit")
        archive.seek(0)
        actual = "sha256:" + hashlib.file_digest(archive, "sha256").hexdigest()
        if actual != digest:
            raise DistributionSetError("artifact ZIP digest mismatch")
        archive.seek(0)
        with zipfile.ZipFile(archive) as result:
            yield result


def _members(archive: zipfile.ZipFile, expected: set[str]) -> dict[str, zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) != len(expected) or {entry.filename for entry in entries} != expected:
        raise DistributionSetError("artifact ZIP members differ from the expected set")
    for entry in entries:
        mode = entry.external_attr >> 16
        if (NAME_RE.fullmatch(entry.filename) is None or entry.is_dir()
                or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                or entry.file_size > (MAX_CONTROL_BYTES if expected == RECORD_MEMBERS else MAX_ARCHIVE_BYTES)):
            raise DistributionSetError("unsafe or oversized artifact ZIP member")
    return {entry.filename: entry for entry in entries}


def _record_rows(data: bytes, source_sha: str) -> dict[str, tuple[str, str]]:
    if len(data) > MAX_CONTROL_BYTES:
        raise DistributionSetError("reproducibility record is too large")
    try:
        lines = data.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise DistributionSetError("invalid reproducibility record encoding") from error
    header = ["target", "byte_verified", "verification", "sha256", "rebuild_sha256", "file", "build_env"]
    if (len(lines) < 4 or re.fullmatch(
            rf"# release [^ ]+ @ {source_sha}, SOURCE_DATE_EPOCH=[0-9]+", lines[0]) is None
            or lines[1].split("\t") != header):
        raise DistributionSetError("reproducibility record is not bound to the source")
    rows: dict[str, tuple[str, str]] = {}
    for line in lines[2:]:
        fields = line.split("\t")
        if (len(fields) != len(header) or fields[0] in rows
                or fields[1] != "true" or fields[3] != fields[4]
                or re.fullmatch(r"[0-9a-f]{64}", fields[3]) is None):
            raise DistributionSetError("duplicate, unverified, or malformed record row")
        rows[fields[0]] = (fields[5], fields[3])
    return rows


def verify_distribution_set(artifacts: Iterable[Any], attempt: Any, *,
                            repository: str, source_sha: str,
                            control_sha: str, run_id: int, run_attempt: int,
                            record_artifact_id: int, record_artifact_digest: str,
                            wheel_filename: str, sdist_filename: str,
                            fetch: Callable[[str, int, BinaryIO], None],
                            output_dir: Path) -> list[dict[str, Any]]:
    """Require exact metadata and ZIP bytes for every declared distribution."""
    if (REPOSITORY_RE.fullmatch(repository) is None or SHA_RE.fullmatch(source_sha) is None
            or SHA_RE.fullmatch(control_sha) is None or type(run_id) is not int or run_id <= 0
            or type(run_attempt) is not int or run_attempt <= 0):
        raise DistributionSetError("invalid expected release identity")
    if (not isinstance(attempt, Mapping) or type(attempt.get("id")) is not int
            or attempt["id"] != run_id or type(attempt.get("run_attempt")) is not int
            or attempt["run_attempt"] != run_attempt or attempt.get("head_sha") != control_sha):
        raise DistributionSetError("workflow attempt differs from the caller")
    started = _timestamp(attempt.get("run_started_at"))
    listed: dict[str, Mapping[str, Any]] = {}
    for item in artifacts:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            raise DistributionSetError("invalid artifact metadata entry")
        name = item["name"]
        if name in listed:
            raise DistributionSetError(f"duplicate artifact name: {name}")
        listed[name] = item
    _artifact(listed, "reproducibility-record", record_artifact_id,
              _digest(record_artifact_digest), run_id, control_sha, started)
    with _archive(repository, record_artifact_id, record_artifact_digest, fetch) as archive:
        _members(archive, RECORD_MEMBERS)
        manifest = _json_bytes(archive.read("release-gate-distribution-set.json"))
        record = archive.read("reproducibility-record.tsv")
    if not isinstance(manifest, Mapping) or set(manifest) != MANIFEST_KEYS:
        raise DistributionSetError("distribution manifest has an unknown shape")
    if (type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1
            or manifest["source_repository"] != repository
            or manifest["source_sha"] != source_sha or manifest["control_sha"] != control_sha
            or type(manifest["run_id"]) is not int or manifest["run_id"] != run_id
            or type(manifest["run_attempt"]) is not int or manifest["run_attempt"] != run_attempt):
        raise DistributionSetError("distribution manifest differs from the caller identity")
    rows = manifest["distributions"]
    if not isinstance(rows, list) or len(rows) < 2:
        raise DistributionSetError("distribution manifest lacks wheel/sdist coverage")
    record_rows = _record_rows(record, source_sha)
    expected_names: set[str] = set()
    seen_legs: set[str] = set()
    seen_files: set[str] = set()
    seen_ids = {record_artifact_id}
    verified: list[dict[str, Any]] = []
    if output_dir.exists() or output_dir.is_symlink():
        raise DistributionSetError("distribution output already exists")
    with tempfile.TemporaryDirectory(prefix=".release-set-", dir=output_dir.parent) as staging_name:
        staging = Path(staging_name)
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != ROW_KEYS:
                raise DistributionSetError("invalid distribution row shape")
            leg, filename, name = row["leg"], row["file"], row["artifact_name"]
            artifact_id, digest, sha = row["artifact_id"], row["artifact_digest"], row["sha256"]
            if (not isinstance(leg, str) or NAME_RE.fullmatch(leg) is None
                    or not isinstance(filename, str) or NAME_RE.fullmatch(filename) is None
                    or not isinstance(name, str) or name != ("dist-sdist" if leg == "sdist" else f"dist-wheel-{leg}")
                    or filename.endswith(".tar.gz") != (leg == "sdist")
                    or (leg != "sdist" and not filename.endswith(".whl"))
                    or not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None
                    or type(artifact_id) is not int or artifact_id in seen_ids
                    or leg in seen_legs or filename in seen_files):
                raise DistributionSetError("duplicate or malformed distribution identity")
            _artifact(listed, name, artifact_id, _digest(digest), run_id, control_sha, started)
            if record_rows.get(leg) != (filename, sha):
                raise DistributionSetError(f"{leg}: distribution differs from reproducibility record")
            with _archive(repository, artifact_id, digest, fetch) as archive:
                member = _members(archive, {filename})[filename]
                with archive.open(member) as source, (staging / filename).open("xb") as target:
                    copied = hashlib.sha256()
                    size = 0
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        size += len(block)
                        if size > MAX_ARCHIVE_BYTES:
                            raise DistributionSetError("distribution member exceeds the size limit")
                        copied.update(block)
                        target.write(block)
                if copied.hexdigest() != sha or size != member.file_size:
                    raise DistributionSetError(f"{leg}: distribution bytes differ from the manifest")
            expected_names.add(name)
            seen_legs.add(leg)
            seen_files.add(filename)
            seen_ids.add(artifact_id)
            verified.append(dict(row))
        if seen_legs != set(record_rows) or "sdist" not in seen_legs:
            raise DistributionSetError("distribution set differs from reproducibility record")
        if {name for name in listed if name.startswith("dist-")} != expected_names:
            raise DistributionSetError("distribution artifact set is missing or has extras")
        if (wheel_filename not in {row["file"] for row in verified if row["leg"] != "sdist"}
                or sdist_filename != next(row["file"] for row in verified if row["leg"] == "sdist")):
            raise DistributionSetError("selected wheel/sdist is not in the verified distribution set")
        staging.rename(output_dir)
    return verified


def fetch_artifact(repository: str, artifact_id: int, output: BinaryIO) -> None:
    """Stream one immutable GitHub artifact ZIP without invoking a shell."""
    process = subprocess.Popen(
        ["gh", "api", f"repos/{repository}/actions/artifacts/{artifact_id}/zip"],
        stdout=subprocess.PIPE,
    )
    try:
        while block := process.stdout.read(1024 * 1024):
            output.write(block)
            if output.tell() > MAX_ARCHIVE_BYTES:
                raise DistributionSetError("artifact ZIP exceeds the size limit")
        if process.wait() != 0:
            raise DistributionSetError("GitHub artifact download failed")
    except BaseException:
        if process.poll() is None:
            process.kill()
        process.wait()
        raise
    finally:
        process.stdout.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    for option in ("repository", "source-sha", "control-sha", "run-id", "run-attempt",
                   "record-artifact-id", "record-artifact-digest", "wheel-filename",
                   "sdist-filename", "metadata", "attempt", "output"):
        parser.add_argument(f"--{option}", required=True)
    args = parser.parse_args()
    repository = args.repository
    record_id = int(args.record_artifact_id)
    record_digest = _digest(args.record_artifact_digest)
    metadata = [_json_bytes(line.encode("utf-8")) for line in Path(args.metadata).read_text(encoding="utf-8").splitlines()]
    attempt = _json_bytes(Path(args.attempt).read_bytes())
    verified = verify_distribution_set(
        metadata, attempt, repository=repository,
        source_sha=args.source_sha, control_sha=args.control_sha,
        run_id=int(args.run_id), run_attempt=int(args.run_attempt),
        record_artifact_id=record_id, record_artifact_digest=record_digest,
        wheel_filename=args.wheel_filename, sdist_filename=args.sdist_filename,
        fetch=fetch_artifact, output_dir=Path(args.output),
    )
    print(json.dumps({"verified_distributions": verified}, sort_keys=True))


if __name__ == "__main__":
    main()
