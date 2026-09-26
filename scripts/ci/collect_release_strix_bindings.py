#!/usr/bin/env python3
"""Collect one current-attempt Strix binding per licensed dependency."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterable, Mapping

try:
    from scripts.ci import release_dependency_gate as gate
    from scripts.ci.verify_release_distribution_set import (
        DIGEST_RE,
        DistributionSetError,
        MAX_CONTROL_BYTES,
        _archive,
        _artifact,
        _digest,
        _json_bytes,
        _members,
        _timestamp,
        fetch_artifact,
        verify_distribution_set,
    )
except ImportError:  # pragma: no cover - trusted direct `python3 -I` invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import release_dependency_gate as gate
    from verify_release_distribution_set import (
        DIGEST_RE,
        DistributionSetError,
        MAX_CONTROL_BYTES,
        _archive,
        _artifact,
        _digest,
        _json_bytes,
        _members,
        _timestamp,
        fetch_artifact,
        verify_distribution_set,
    )


def collect_bindings(
    capture_root: Path,
    license_report: Path,
    plan_path: Path,
    artifacts: Iterable[Any],
    attempt: Any,
    *,
    repository: str,
    source_sha: str,
    control_sha: str,
    run_id: int,
    run_attempt: int,
    fetch: Callable[[str, int, BinaryIO], None],
    report_path: Path,
    verified_distributions: list[dict[str, Any]],
    verdict_path: Path,
    record_artifact_id: int,
    record_artifact_digest: str,
    archive_report_path: Path | None = None,
    verified_scope_path: Path | None = None,
) -> gate.GateReport:
    """Accept the exact matrix result set, then rerun the full gate unchanged."""

    if (not isinstance(attempt, Mapping) or type(attempt.get("id")) is not int
            or attempt["id"] != run_id or type(attempt.get("run_attempt")) is not int
            or attempt["run_attempt"] != run_attempt or attempt.get("head_sha") != control_sha):
        raise gate.GateError(gate.STRIX_BINDING_UNBOUND, "workflow attempt differs from collector")
    started = _timestamp(attempt.get("run_started_at"))
    expected = gate.strix_fanout_plan(
        capture_root, license_report, control_sha, run_id, run_attempt, archive_report_path
    )
    plan = gate.load_json(plan_path)
    if plan != expected or plan["source_repository"] != repository or plan["source_sha"] != source_sha:
        raise gate.GateError(gate.STRIX_BINDING_UNBOUND, "fanout plan differs from trusted capture")
    listed: dict[str, Mapping[str, Any]] = {}
    for item in artifacts:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            raise gate.GateError(gate.STRIX_BINDING_MALFORMED, "artifact metadata is invalid")
        if item["name"] in listed:
            raise gate.GateError(gate.STRIX_BINDING_UNBOUND, "duplicate artifact name in run")
        listed[item["name"]] = item
    prefix = f"release-strix-binding-a{run_attempt}-"
    expected_names = {row["artifact_name"] for row in plan["dependencies"]}
    if {name for name in listed if name.startswith(prefix)} != expected_names:
        raise gate.GateError(gate.STRIX_BINDING_MISSING, "matrix binding artifact set is incomplete or has extras")
    bindings = capture_root / "strix" / "bindings"
    if (bindings.exists() or bindings.is_symlink() or report_path.exists()
            or report_path.is_symlink() or verdict_path.exists() or verdict_path.is_symlink()):
        raise gate.GateError(gate.STRIX_BINDING_UNBOUND, "collector destination already exists")
    if not verified_distributions or type(record_artifact_id) is not int or record_artifact_id <= 0:
        raise gate.GateError(gate.STRIX_BINDING_UNBOUND, "verified distribution set is unavailable")
    _artifact(listed, "reproducibility-record", record_artifact_id,
              _digest(record_artifact_digest), run_id, control_sha, started)
    if any(not isinstance(row, Mapping) for row in verified_distributions):
        raise gate.GateError(
            gate.STRIX_BINDING_UNBOUND,
            "verified distribution report contains a malformed row",
        )
    wheel_filenames = [
        row.get("file") for row in verified_distributions
        if row.get("leg") != "sdist" and isinstance(row.get("file"), str)
    ]
    sdist_filenames = [
        row.get("file") for row in verified_distributions
        if row.get("leg") == "sdist" and isinstance(row.get("file"), str)
    ]
    if not wheel_filenames or len(sdist_filenames) != 1:
        raise gate.GateError(
            gate.STRIX_BINDING_UNBOUND,
            "verified distribution report lacks wheel/sdist coverage",
        )
    try:
        with tempfile.TemporaryDirectory(
            prefix=".release-distributions-", dir=bindings.parent
        ) as distribution_scratch:
            canonical_distributions = verify_distribution_set(
                artifacts,
                attempt,
                repository=repository,
                source_sha=source_sha,
                control_sha=control_sha,
                run_id=run_id,
                run_attempt=run_attempt,
                record_artifact_id=record_artifact_id,
                record_artifact_digest=record_artifact_digest,
                wheel_filename=wheel_filenames[0],
                sdist_filename=sdist_filenames[0],
                fetch=fetch,
                output_dir=Path(distribution_scratch) / "verified",
            )
    except DistributionSetError as error:
        raise gate.GateError(
            gate.STRIX_BINDING_UNBOUND,
            "distribution set failed immutable artifact verification",
        ) from error
    if verified_distributions != canonical_distributions:
        raise gate.GateError(
            gate.STRIX_BINDING_UNBOUND,
            "verified distribution report differs from immutable artifacts",
        )
    seen_ids: set[int] = {record_artifact_id}
    with tempfile.TemporaryDirectory(prefix=".strix-bindings-", dir=bindings.parent) as scratch:
        staging = Path(scratch)
        for row in plan["dependencies"]:
            name = row["artifact_name"]
            item = listed[name]
            artifact_id = item.get("id")
            digest = item.get("digest")
            if (type(artifact_id) is not int or artifact_id in seen_ids
                    or not isinstance(digest, str)):
                raise gate.GateError(gate.STRIX_BINDING_UNBOUND, "binding artifact ID or digest is invalid")
            _artifact(listed, name, artifact_id, digest, run_id, control_sha, started)
            seen_ids.add(artifact_id)
            member_name = f"{row['slug']}.json"
            with _archive(repository, artifact_id, digest, fetch) as archive:
                member = _members(archive, {member_name})[member_name]
                if member.file_size > MAX_CONTROL_BYTES:
                    raise gate.GateError(gate.STRIX_BINDING_MALFORMED, "binding JSON exceeds size limit")
                raw = archive.read(member)
            payload = _json_bytes(raw)
            if (not isinstance(payload, Mapping) or payload.get("schema") != gate.BINDING_SCHEMA
                    or payload.get("source_sha") != source_sha
                    or payload.get("control_sha") != control_sha
                    or type(payload.get("run_id")) is not int or payload["run_id"] != run_id
                    or type(payload.get("run_attempt")) is not int
                    or payload["run_attempt"] != run_attempt
                    or not isinstance(payload.get("fixture"), Mapping)
                    or payload["fixture"].get("id") != row["key"]
                    or payload["fixture"].get("sha256") != row["fixture_sha256"]):
                raise gate.GateError(gate.STRIX_BINDING_UNBOUND, f"{row['key']}: binding differs from plan")
            (staging / member_name).write_bytes(raw)
        staging.rename(bindings)
    scope_identities: list[dict[str, Any]] | None = None
    if verified_scope_path is not None:
        scope = gate.load_json(verified_scope_path)
        rows = scope.get("verified_scope_evidence") if isinstance(scope, Mapping) else None
        if (not isinstance(rows, list) or len(rows) != 13
                or not all(isinstance(row, Mapping) for row in rows)):
            raise gate.GateError(gate.SCOPE_UNVERIFIABLE, "verified scope set is incomplete")
        scope_identities = [{key: row.get(key) for key in
                             ("leg", "artifact_id", "artifact_name", "artifact_digest")}
                            for row in rows]
        if (any(not isinstance(row["leg"], str)
                       or row["artifact_name"] != f"repro-digest-{row['leg']}"
                       or type(row["artifact_id"]) is not int or row["artifact_id"] <= 0
                       or not isinstance(row["artifact_digest"], str)
                       or DIGEST_RE.fullmatch(row["artifact_digest"]) is None
                       for row in scope_identities)
                or len({row["leg"] for row in scope_identities}) != 13
                or len({row["artifact_id"] for row in scope_identities}) != 13
                or sum(row["leg"] == "sdist" for row in scope_identities) != 1):
            raise gate.GateError(gate.SCOPE_UNVERIFIABLE, "verified scope identities are malformed")
        used_ids = seen_ids | {row.get("artifact_id") for row in verified_distributions}
        if any(row["artifact_id"] in used_ids for row in scope_identities):
            raise gate.GateError(gate.SCOPE_UNVERIFIABLE, "scope artifact ID overlaps distribution set")
        for row in scope_identities:
            _artifact(listed, row["artifact_name"], row["artifact_id"],
                      row["artifact_digest"], run_id, control_sha, started)
    report = gate.gate(capture_root, stage=gate.FULL_STAGE)
    archive_reviews = []
    build_reviews = []
    tool_reviews = []
    if archive_report_path is not None and report.passed:
        archive_payload = gate.load_json(archive_report_path)
        by_key = {row["key"]: row for row in archive_payload["archives"]}
        build_by_key = {row["key"]: row for row in archive_payload["build_packages"]}
        tool_by_key = {row["key"]: row for row in archive_payload["build_tools"]}
        for row in plan["dependencies"]:
            if not {"runtime_archive", "build_package", "build_tool"} & row.keys():
                continue
            build = "build_package" in row
            tool = "build_tool" in row
            approved = (tool_by_key if tool else build_by_key if build else by_key)[row["key"]]
            dependency = gate.Dependency("github-release" if tool else "pypi",
                                         approved["name"], approved["version"])
            failures = gate.validate_strix_binding(
                bindings / f"{row['slug']}.json", dependency,
                {"source_sha256": approved["source_sha256"]}, row["fixture_sha256"],
                source_sha, fixture_key=row["key"],
            )
            report.failures.extend(failures)
            review = {"key": row["key"], "package_key": approved["package_key"],
                      "source_sha256": approved["source_sha256"],
                      "license": approved["license"],
                      "fixture_sha256": row["fixture_sha256"],
                      "legs": approved["legs"]}
            (tool_reviews if tool else build_reviews if build else archive_reviews).append(review)
    report_payload = report.to_json()
    if archive_report_path is not None:
        report_payload["runtime_archive_reviews"] = sorted(archive_reviews, key=lambda row: row["key"])
        report_payload["build_package_reviews"] = sorted(build_reviews, key=lambda row: row["key"])
        report_payload["build_tool_reviews"] = sorted(tool_reviews, key=lambda row: row["key"])
    report_path.write_text(json.dumps(report_payload, indent=2, sort_keys=True) + "\n")
    if not report.passed:
        raise gate.GateError(gate.STRIX_FINDINGS_OPEN, "full gate refused collected bindings")
    binding_artifacts = [
        {"key": row["key"], "name": row["artifact_name"],
         "id": listed[row["artifact_name"]]["id"],
         "digest": listed[row["artifact_name"]]["digest"]}
        for row in plan["dependencies"] if not {"runtime_archive", "build_package", "build_tool"} & row.keys()
    ]
    archive_binding_artifacts = [
        {"key": row["key"], "name": row["artifact_name"],
         "id": listed[row["artifact_name"]]["id"],
         "digest": listed[row["artifact_name"]]["digest"]}
        for row in plan["dependencies"] if "runtime_archive" in row
    ]
    build_binding_artifacts = [
        {"key": row["key"], "name": row["artifact_name"],
         "id": listed[row["artifact_name"]]["id"],
         "digest": listed[row["artifact_name"]]["digest"]}
        for row in plan["dependencies"] if "build_package" in row
    ]
    tool_binding_artifacts = [
        {"key": row["key"], "name": row["artifact_name"],
         "id": listed[row["artifact_name"]]["id"],
         "digest": listed[row["artifact_name"]]["digest"]}
        for row in plan["dependencies"] if "build_tool" in row
    ]
    verdict = {
        "schema": "cwl.release-full-set-verdict/1", "result": "PASS",
        "source_repository": repository, "source_sha": source_sha,
        "control_sha": control_sha, "run_id": run_id, "run_attempt": run_attempt,
        "record_artifact_id": record_artifact_id,
        "record_artifact_digest": record_artifact_digest,
        "distributions": canonical_distributions,
        "binding_artifacts": binding_artifacts,
        "license_report_sha256": hashlib.sha256(license_report.read_bytes()).hexdigest(),
        "gate_report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
    }
    if archive_report_path is not None:
        verdict["runtime_archive_binding_artifacts"] = archive_binding_artifacts
        verdict["build_package_binding_artifacts"] = build_binding_artifacts
        verdict["build_tool_binding_artifacts"] = tool_binding_artifacts
        verdict["runtime_archive_license_sha256"] = expected["runtime_archive_license_sha256"]
    if scope_identities is not None:
        verdict["scope_evidence"] = sorted(scope_identities, key=lambda row: row["leg"])
    verdict_path.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in (
        "capture", "license-report", "plan", "metadata", "attempt", "repository",
        "source-sha", "control-sha", "run-id", "run-attempt", "report",
        "verified-distributions", "verdict", "record-artifact-id", "record-artifact-digest",
    ):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--runtime-archive-license-report")
    parser.add_argument("--verified-scope")
    args = parser.parse_args()
    artifacts = [_json_bytes(line.encode("utf-8")) for line in Path(args.metadata).read_text().splitlines()]
    attempt = _json_bytes(Path(args.attempt).read_bytes())
    verified = _json_bytes(Path(args.verified_distributions).read_bytes())
    if not isinstance(verified, Mapping) or not isinstance(verified.get("verified_distributions"), list):
        raise gate.GateError(gate.STRIX_BINDING_UNBOUND, "verified distribution report is malformed")
    report = collect_bindings(
        Path(args.capture), Path(args.license_report), Path(args.plan),
        artifacts, attempt, repository=args.repository, source_sha=args.source_sha,
        control_sha=args.control_sha, run_id=int(args.run_id),
        run_attempt=int(args.run_attempt), fetch=fetch_artifact,
        report_path=Path(args.report),
        verified_distributions=verified["verified_distributions"],
        verdict_path=Path(args.verdict),
        record_artifact_id=int(args.record_artifact_id),
        record_artifact_digest=args.record_artifact_digest,
        archive_report_path=(Path(args.runtime_archive_license_report)
                             if args.runtime_archive_license_report else None),
        verified_scope_path=Path(args.verified_scope) if args.verified_scope else None,
    )
    print(json.dumps(report.to_json(), sort_keys=True))


if __name__ == "__main__":
    main()
