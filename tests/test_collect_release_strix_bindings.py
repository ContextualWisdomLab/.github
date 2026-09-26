"""Exact current-attempt matrix collection before the unchanged full gate."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from scripts.ci import release_dependency_gate as gate
from scripts.ci.collect_release_strix_bindings import collect_bindings
from tests.test_release_dependency_gate import REPOSITORY, SOURCE_SHA, build_capture


CONTROL = "d" * 40
RUN = 42
ATTEMPT = 2
STARTED = "2026-09-26T12:00:00Z"
CREATED = "2026-09-26T12:01:00Z"


def _zip(name: str, data: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, data)
    return output.getvalue()


def _case(root: Path) -> dict:
    capture = build_capture(root / "capture")
    for fixture in (capture / "strix/fixtures").glob("*.json"):
        fixture.with_suffix(".sha256").write_text(
            gate.fixture_digest(json.loads(fixture.read_text())) + "\n"
        )
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    assert report.passed
    license_path = capture / "license-report.json"
    license_path.write_text(json.dumps(report.to_json()) + "\n")
    plan_path = capture / "strix-fanout-plan.json"
    plan = gate.strix_fanout_plan(capture, license_path, CONTROL, RUN, ATTEMPT)
    plan_path.write_text(json.dumps(plan) + "\n")
    metadata = []
    archives = {}
    for index, row in enumerate(plan["dependencies"], 1):
        path = capture / "strix/bindings" / f"{row['slug']}.json"
        binding = json.loads(path.read_text())
        binding.update(control_sha=CONTROL, run_id=RUN, run_attempt=ATTEMPT)
        archive = _zip(path.name, (json.dumps(binding) + "\n").encode())
        archives[index] = archive
        metadata.append({"id": index, "name": row["artifact_name"],
                         "digest": "sha256:" + hashlib.sha256(archive).hexdigest(),
                         "created_at": CREATED, "expired": False,
                         "workflow_run": {"id": RUN, "head_sha": CONTROL}})
    metadata.append({"id": 900, "name": "reproducibility-record",
                     "digest": "sha256:" + "a" * 64,
                     "created_at": CREATED, "expired": False,
                     "workflow_run": {"id": RUN, "head_sha": CONTROL}})
    shutil.rmtree(capture / "strix/bindings")
    return {"capture": capture, "license": license_path, "plan": plan_path,
            "metadata": metadata, "archives": archives,
            "attempt": {"id": RUN, "run_attempt": ATTEMPT,
                        "head_sha": CONTROL, "run_started_at": STARTED},
            "report": root / "full-report.json", "verdict": root / "full-verdict.json"}


def _collect(case: dict):
    def fetch(repository: str, artifact_id: int, output) -> None:
        assert repository == REPOSITORY
        output.write(case["archives"][artifact_id])

    return collect_bindings(
        case["capture"], case["license"], case["plan"],
        case["metadata"], case["attempt"], repository=REPOSITORY,
        source_sha=SOURCE_SHA, control_sha=CONTROL, run_id=RUN,
        run_attempt=ATTEMPT, fetch=fetch, report_path=case["report"],
        verified_distributions=[{"leg": "example", "file": "example.whl"}],
        verdict_path=case["verdict"], record_artifact_id=900,
        record_artifact_digest="sha256:" + "a" * 64,
    )


def test_collects_every_binding_and_replays_full_gate(tmp_path: Path) -> None:
    case = _case(tmp_path)
    report = _collect(case)
    assert report.passed
    assert json.loads(case["report"].read_text())["result"] == "PASS"
    verdict = json.loads(case["verdict"].read_text())
    assert verdict["result"] == "PASS"
    plan = json.loads(case["plan"].read_text())
    assert verdict["binding_artifacts"][0]["name"] == plan["dependencies"][0]["artifact_name"]
    assert {path.name for path in (case["capture"] / "strix/bindings").iterdir()} == {
        f"{row['slug']}.json" for row in plan["dependencies"]
    }


def test_refuses_missing_extra_stale_forged_or_changed_bindings(tmp_path: Path) -> None:
    def missing(case):
        case["metadata"].pop()

    def extra(case):
        case["metadata"].append({**case["metadata"][0], "id": 99,
                                 "name": "release-strix-binding-a2-unlisted"})

    def stale(case):
        case["metadata"][0]["created_at"] = "2026-09-26T11:59:59Z"

    def wrong_run(case):
        case["metadata"][0]["workflow_run"] = {"id": 1, "head_sha": CONTROL}

    def tamper_zip(case):
        case["archives"][1] = _zip("binding.json", b"altered")

    def duplicate_id(case):
        case["metadata"][1]["id"] = case["metadata"][0]["id"]

    def wrong_plan(case):
        plan = json.loads(case["plan"].read_text())
        plan["source_sha"] = "e" * 40
        case["plan"].write_text(json.dumps(plan))

    def wrong_attempt(case):
        case["attempt"]["run_attempt"] = 1

    def wrong_record(case):
        case["metadata"][-1]["workflow_run"]["id"] = 1

    for name, mutate in (
        ("missing", missing), ("extra", extra), ("stale", stale),
        ("wrong-run", wrong_run), ("tamper-zip", tamper_zip),
        ("duplicate-id", duplicate_id), ("wrong-plan", wrong_plan),
        ("wrong-attempt", wrong_attempt), ("wrong-record", wrong_record),
    ):
        case = _case(tmp_path / name)
        mutate(case)
        with pytest.raises((gate.GateError, ValueError)):
            _collect(case)
        assert not case["report"].exists(), name
        assert not case["verdict"].exists(), name


def test_reports_structured_findings_as_fail(tmp_path: Path) -> None:
    case = _case(tmp_path)
    plan = json.loads(case["plan"].read_text())
    first = plan["dependencies"][0]
    raw = case["archives"][1]
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        binding = json.loads(archive.read(f"{first['slug']}.json"))
    binding["findings"] = [{"rule": "test-finding"}]
    binding["verdict"] = "findings_present"
    changed = _zip(f"{first['slug']}.json", (json.dumps(binding) + "\n").encode())
    case["archives"][1] = changed
    case["metadata"][0]["digest"] = "sha256:" + hashlib.sha256(changed).hexdigest()
    with pytest.raises(gate.GateError, match=gate.STRIX_FINDINGS_OPEN):
        _collect(case)
    report = json.loads(case["report"].read_text())
    assert report["result"] == "FAIL"
    assert not case["verdict"].exists()
    assert any(item["code"] == gate.STRIX_FINDINGS_OPEN for item in report["failures"])
