"""Exact current-attempt matrix collection before the unchanged full gate."""

from __future__ import annotations

import copy
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
    return _zip_members({name: data})


def _zip_members(members: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
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
    verified = []
    record_lines = [
        f"# release v1.2.3 @ {SOURCE_SHA}, SOURCE_DATE_EPOCH=1",
        "target\tbyte_verified\tverification\tsha256\trebuild_sha256\tfile\tbuild_env",
    ]
    for artifact_id, leg, filename in (
        (901, "linux-py3.12", "example-1.2.3-py3-none-any.whl"),
        (902, "sdist", "example-1.2.3.tar.gz"),
    ):
        data = f"verified bytes for {leg}".encode()
        archive = _zip(filename, data)
        name = "dist-sdist" if leg == "sdist" else f"dist-wheel-{leg}"
        digest = "sha256:" + hashlib.sha256(archive).hexdigest()
        archives[artifact_id] = archive
        metadata.append({"id": artifact_id, "name": name, "digest": digest,
                         "created_at": CREATED, "expired": False,
                         "workflow_run": {"id": RUN, "head_sha": CONTROL}})
        row = {"leg": leg, "file": filename,
               "sha256": hashlib.sha256(data).hexdigest(),
               "artifact_id": artifact_id, "artifact_name": name,
               "artifact_digest": digest}
        verified.append(row)
        record_lines.append(
            f"{leg}\ttrue\tclean-target-repeat-same-env\t{row['sha256']}\t"
            f"{row['sha256']}\t{filename}\trunner:x"
        )
    manifest = {
        "schema_version": 1, "source_repository": REPOSITORY,
        "source_sha": SOURCE_SHA, "control_sha": CONTROL,
        "run_id": RUN, "run_attempt": ATTEMPT, "distributions": verified,
    }
    record = _zip_members({
        "reproducibility-record.tsv": ("\n".join(record_lines) + "\n").encode(),
        "release-scope-identities.json": b"[]\n",
        "release-scope-evidence-set.json": b"{}\n",
        "release-gate-distribution-set.json": (json.dumps(manifest) + "\n").encode(),
    })
    archives[900] = record
    metadata.append({"id": 900, "name": "reproducibility-record",
                     "digest": "sha256:" + hashlib.sha256(record).hexdigest(),
                     "created_at": CREATED, "expired": False,
                     "workflow_run": {"id": RUN, "head_sha": CONTROL}})
    shutil.rmtree(capture / "strix/bindings")
    return {"capture": capture, "license": license_path, "plan": plan_path,
            "metadata": metadata, "archives": archives,
            "record_digest": metadata[-1]["digest"],
            "attempt": {"id": RUN, "run_attempt": ATTEMPT,
                        "head_sha": CONTROL, "run_started_at": STARTED},
            "report": root / "full-report.json", "verdict": root / "full-verdict.json",
            "verified": verified}


def _collect(case: dict, verified: list[dict] | None = None):
    def fetch(repository: str, artifact_id: int, output) -> None:
        assert repository == REPOSITORY
        output.write(case["archives"][artifact_id])

    return collect_bindings(
        case["capture"], case["license"], case["plan"],
        case["metadata"], case["attempt"], repository=REPOSITORY,
        source_sha=SOURCE_SHA, control_sha=CONTROL, run_id=RUN,
        run_attempt=ATTEMPT, fetch=fetch, report_path=case["report"],
        verified_distributions=case["verified"] if verified is None else verified,
        verdict_path=case["verdict"], record_artifact_id=900,
        record_artifact_digest=case["record_digest"],
        archive_report_path=case.get("archive_report"),
        verified_scope_path=case.get("verified_scope"),
    )


def _with_archive_variant(case: dict) -> dict:
    sha = "e" * 64
    key = f"pypi/numpy@2.5.1/sha256/{sha}"
    fixture = gate.build_fixture(gate.Dependency("pypi", "numpy", "2.5.1"),
                                 {"source_sha256": sha, "archive_members": [],
                                  "install_hook_sources": {}, "parsed_inputs": [],
                                  "native_libraries": [], "known_vulnerabilities": []})
    fixture["id"] = key
    build_sha = "f" * 64
    build_key = f"pypi/pip@25.2/sha256/{build_sha}"
    build_fixture = gate.build_fixture(gate.Dependency("pypi", "pip", "25.2"),
                                      {"source_sha256": build_sha, "archive_members": [],
                                       "install_hook_sources": {}, "parsed_inputs": [],
                                       "native_libraries": [], "known_vulnerabilities": []})
    build_fixture["id"] = build_key
    archive_report = case["capture"] / "archive-report.json"
    archive_report.write_text(json.dumps({"schema": "cwl.release-runtime-archive-licenses/2",
                                          "archives": [{"key": key, "package_key": "pypi/numpy@2.5.1",
                                                        "name": "numpy", "version": "2.5.1",
                                                        "source_sha256": sha, "license": "BSD-3-Clause",
                                                        "legs": ["wheel-example"], "fixture": fixture,
                                                        "fixture_sha256": gate.fixture_digest(fixture)}],
                                          "build_packages": [{"key": build_key,
                                                              "package_key": "pypi/pip@25.2",
                                                              "name": "pip", "version": "25.2",
                                                              "source_sha256": build_sha,
                                                              "license": "MIT", "legs": ["sdist"],
                                                              "fixture": build_fixture,
                                                              "fixture_sha256": gate.fixture_digest(build_fixture)}]}))
    plan = gate.strix_fanout_plan(case["capture"], case["license"], CONTROL, RUN, ATTEMPT,
                                 archive_report)
    case["plan"].write_text(json.dumps(plan) + "\n")
    variant = next(row for row in plan["dependencies"] if "runtime_archive" in row)
    base_row = plan["dependencies"][0]
    base_zip = next(data for data in case["archives"].values()
                    if f"{base_row['slug']}.json" in zipfile.ZipFile(io.BytesIO(data)).namelist())
    with zipfile.ZipFile(io.BytesIO(base_zip)) as archive:
        binding = json.loads(archive.read(f"{base_row['slug']}.json"))
    binding["dependency"] = fixture["dependency"]
    binding["fixture"].update(id=key, sha256=variant["fixture_sha256"])
    variant_zip = _zip(f"{variant['slug']}.json", (json.dumps(binding) + "\n").encode())
    case["archives"][99] = variant_zip
    case["metadata"].insert(-1, {"id": 99, "name": variant["artifact_name"],
                                 "digest": "sha256:" + hashlib.sha256(variant_zip).hexdigest(),
                                 "created_at": CREATED, "expired": False,
                                 "workflow_run": {"id": RUN, "head_sha": CONTROL}})
    build_variant = next(row for row in plan["dependencies"] if "build_package" in row)
    build_binding = copy.deepcopy(binding)
    build_binding["dependency"] = build_fixture["dependency"]
    build_binding["fixture"].update(id=build_key, sha256=build_variant["fixture_sha256"])
    build_zip = _zip(f"{build_variant['slug']}.json", (json.dumps(build_binding) + "\n").encode())
    case["archives"][98] = build_zip
    case["metadata"].insert(-2, {"id": 98, "name": build_variant["artifact_name"],
                                 "digest": "sha256:" + hashlib.sha256(build_zip).hexdigest(),
                                 "created_at": CREATED, "expired": False,
                                 "workflow_run": {"id": RUN, "head_sha": CONTROL}})
    case["archive_report"] = archive_report
    return case


def _with_scope_set(case: dict) -> dict:
    rows = []
    for index in range(13):
        leg = "sdist" if index == 12 else f"target{index}-py3.12"
        name = f"repro-digest-{leg}"
        digest = "sha256:" + hashlib.sha256(name.encode()).hexdigest()
        artifact_id = 100 + index
        rows.append({"leg": leg, "artifact_id": artifact_id,
                     "artifact_name": name, "artifact_digest": digest})
        case["metadata"].append({"id": artifact_id, "name": name, "digest": digest,
                                 "created_at": CREATED, "expired": False,
                                 "workflow_run": {"id": RUN, "head_sha": CONTROL}})
    path = case["capture"] / "verified-scope.json"
    path.write_text(json.dumps({"verified_scope_evidence": rows}))
    case["verified_scope"] = path
    return case


def test_collects_every_binding_and_replays_full_gate(tmp_path: Path) -> None:
    case = _case(tmp_path)
    report = _collect(case)
    assert report.passed
    assert json.loads(case["report"].read_text())["result"] == "PASS"
    verdict = json.loads(case["verdict"].read_text())
    assert verdict["result"] == "PASS"
    assert verdict["distributions"] == case["verified"]
    plan = json.loads(case["plan"].read_text())
    assert verdict["binding_artifacts"][0]["name"] == plan["dependencies"][0]["artifact_name"]
    assert {path.name for path in (case["capture"] / "strix/bindings").iterdir()} == {
        f"{row['slug']}.json" for row in plan["dependencies"]
    }


def test_verdict_seals_same_run_scope_artifact_identities(tmp_path: Path) -> None:
    case = _with_scope_set(_case(tmp_path / "valid"))
    assert _collect(case).passed
    scope = json.loads(case["verified_scope"].read_text())["verified_scope_evidence"]
    assert json.loads(case["verdict"].read_text())["scope_evidence"] == sorted(scope, key=lambda row: row["leg"])

    case = _with_scope_set(_case(tmp_path / "foreign"))
    case["metadata"][-1]["workflow_run"]["id"] = 1
    with pytest.raises((gate.GateError, ValueError)):
        _collect(case)
    assert not case["report"].exists()
    assert not case["verdict"].exists()

    case = _with_scope_set(_case(tmp_path / "duplicate-id"))
    payload = json.loads(case["verified_scope"].read_text())
    payload["verified_scope_evidence"][0]["artifact_id"] = case["metadata"][0]["id"]
    case["verified_scope"].write_text(json.dumps(payload))
    next(item for item in case["metadata"] if item["name"] == payload["verified_scope_evidence"][0]["artifact_name"])[
        "id"] = case["metadata"][0]["id"]
    with pytest.raises(gate.GateError, match="overlaps"):
        _collect(case)
    assert not case["report"].exists()
    assert not case["verdict"].exists()


def test_collects_exact_archive_variant_binding_and_refuses_findings(tmp_path: Path) -> None:
    case = _with_archive_variant(_case(tmp_path / "ok"))
    assert _collect(case).passed
    report = json.loads(case["report"].read_text())
    verdict = json.loads(case["verdict"].read_text())
    assert report["runtime_archive_reviews"][0]["key"].endswith("/sha256/" + "e" * 64)
    assert len(verdict["runtime_archive_binding_artifacts"]) == 1
    assert len(verdict["binding_artifacts"]) == 2
    assert len(verdict["build_package_binding_artifacts"]) == 1
    assert report["build_package_reviews"][0]["key"].endswith("/sha256/" + "f" * 64)

    case = _with_archive_variant(_case(tmp_path / "findings"))
    plan = json.loads(case["plan"].read_text())
    variant = next(row for row in plan["dependencies"] if "runtime_archive" in row)
    with zipfile.ZipFile(io.BytesIO(case["archives"][99])) as archive:
        binding = json.loads(archive.read(f"{variant['slug']}.json"))
    binding["findings"] = [{"rule": "test-finding"}]
    binding["verdict"] = "findings_present"
    changed = _zip(f"{variant['slug']}.json", (json.dumps(binding) + "\n").encode())
    case["archives"][99] = changed
    case["metadata"][-2]["digest"] = "sha256:" + hashlib.sha256(changed).hexdigest()
    with pytest.raises(gate.GateError, match=gate.STRIX_FINDINGS_OPEN):
        _collect(case)
    assert not case["verdict"].exists()

    for name, mutate in (
        ("missing", lambda item: item["metadata"].pop(-2)),
        ("wrong-run", lambda item: item["metadata"][-2]["workflow_run"].update(id=1)),
        ("wrong-sha", lambda item: item["attempt"].update(head_sha="f" * 40)),
        ("tampered", lambda item: item["archives"].__setitem__(99, b"changed")),
    ):
        case = _with_archive_variant(_case(tmp_path / name))
        mutate(case)
        with pytest.raises((gate.GateError, ValueError)):
            _collect(case)
        assert not case["verdict"].exists(), name
def test_refuses_forged_rows_and_unverified_distribution_bytes(tmp_path: Path) -> None:
    forged = _case(tmp_path / "forged")
    forged_rows = copy.deepcopy(forged["verified"])
    forged_rows[0]["sha256"] = "0" * 64
    with pytest.raises((gate.GateError, ValueError)):
        _collect(forged, forged_rows)
    assert not forged["verdict"].exists()

    tampered = _case(tmp_path / "tampered")
    tampered["archives"][901] = _zip(
        tampered["verified"][0]["file"], b"caller never verified these bytes"
    )
    with pytest.raises((gate.GateError, ValueError)):
        _collect(tampered)
    assert not tampered["verdict"].exists()


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
