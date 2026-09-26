#!/usr/bin/env python3
"""Collect one current-attempt Strix binding per licensed dependency."""

from __future__ import annotations

import argparse
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
    if bindings.exists() or bindings.is_symlink() or report_path.exists() or report_path.is_symlink():
        raise gate.GateError(gate.STRIX_BINDING_UNBOUND, "collector destination already exists")
    seen_ids: set[int] = set()
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
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in (
        "capture", "license-report", "plan", "metadata", "attempt", "repository",
        "source-sha", "control-sha", "run-id", "run-attempt", "report",
    ):
        parser.add_argument(f"--{name}", required=True)
    args = parser.parse_args()
    artifacts = [_json_bytes(line.encode("utf-8")) for line in Path(args.metadata).read_text().splitlines()]
    attempt = _json_bytes(Path(args.attempt).read_bytes())
    report = collect_bindings(
        Path(args.capture), Path(args.license_report), Path(args.plan),
        artifacts, attempt, repository=args.repository, source_sha=args.source_sha,
        control_sha=args.control_sha, run_id=int(args.run_id),
        run_attempt=int(args.run_attempt), fetch=fetch_artifact,
        report_path=Path(args.report),
    )
    print(json.dumps(report.to_json(), sort_keys=True))


if __name__ == "__main__":
    main()
