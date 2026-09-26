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
        MAX_CONTROL_BYTES,
        _archive,
        _artifact,
        _digest,
        _json_bytes,
        _members,
        _timestamp,
        fetch_artifact,
    )
except ImportError:  # pragma: no cover - trusted direct `python3 -I` invocation
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import release_dependency_gate as gate
    from verify_release_distribution_set import (
        MAX_CONTROL_BYTES,
        _archive,
        _artifact,
        _digest,
        _json_bytes,
        _members,
        _timestamp,
        fetch_artifact,
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
) -> gate.GateReport:
    """Accept the exact matrix result set, then rerun the full gate unchanged."""

    if (not isinstance(attempt, Mapping) or type(attempt.get("id")) is not int
            or attempt["id"] != run_id or type(attempt.get("run_attempt")) is not int
            or attempt["run_attempt"] != run_attempt or attempt.get("head_sha") != control_sha):
        raise gate.GateError(gate.STRIX_BINDING_UNBOUND, "workflow attempt differs from collector")
    started = _timestamp(attempt.get("run_started_at"))
    expected = gate.strix_fanout_plan(
        capture_root, license_report, control_sha, run_id, run_attempt
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
    report = gate.gate(capture_root, stage=gate.FULL_STAGE)
    report_path.write_text(json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n")
    if not report.passed:
        raise gate.GateError(gate.STRIX_FINDINGS_OPEN, "full gate refused collected bindings")
    binding_artifacts = [
        {"key": row["key"], "name": row["artifact_name"],
         "id": listed[row["artifact_name"]]["id"],
         "digest": listed[row["artifact_name"]]["digest"]}
        for row in plan["dependencies"]
    ]
    verdict = {
        "schema": "cwl.release-full-set-verdict/1", "result": "PASS",
        "source_repository": repository, "source_sha": source_sha,
        "control_sha": control_sha, "run_id": run_id, "run_attempt": run_attempt,
        "record_artifact_id": record_artifact_id,
        "record_artifact_digest": record_artifact_digest,
        "distributions": verified_distributions,
        "binding_artifacts": binding_artifacts,
        "license_report_sha256": hashlib.sha256(license_report.read_bytes()).hexdigest(),
        "gate_report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
    }
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
    )
    print(json.dumps(report.to_json(), sort_keys=True))


if __name__ == "__main__":
    main()
