"""Exact current-attempt matrix collection before the unchanged full gate."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ci import collect_release_strix_bindings as collector
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
        native_report_path=case.get("native_report"),
    )


def test_native_report_is_recomputed_from_immutable_distributions(tmp_path, monkeypatch):
    analyzer = {"path": "/usr/lib/llvm-18/bin/llvm-readobj", "version": "18.1.3",
                "sha256": "a" * 64}
    case = _case(tmp_path)
    native = {"schema": "cwl.release-native-links/2", "source_sha": SOURCE_SHA,
              "analyzer": analyzer, "wheels": [{"leg": "linux-py3.12"}]}
    path = tmp_path / "native-links.json"
    path.write_text(json.dumps(native) + "\n")
    case["native_report"] = path
    monkeypatch.setattr(collector, "_reader", lambda: analyzer)
    monkeypatch.setattr(collector, "scan", lambda verified, root, sha, reader: native)
    _collect(case)
    verdict = json.loads(case["verdict"].read_text())
    assert verdict["native_links_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert verdict["native_link_analyzer"] == analyzer

    case = _case(tmp_path / "tampered")
    path = tmp_path / "tampered-native-links.json"
    path.write_text(json.dumps({**native, "wheels": []}) + "\n")
    case["native_report"] = path
    with pytest.raises(gate.GateError, match="native links differ"):
        _collect(case)


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
    tool_sha = "a" * 64
    tool_key = f"github-release/maturin@1.15.0/sha256/{tool_sha}"
    tool_fixture = gate.build_fixture(gate.Dependency("github-release", "maturin", "1.15.0"),
                                      {"source_sha256": tool_sha, "archive_members": [],
                                       "install_hook_sources": {}, "parsed_inputs": [],
                                       "native_libraries": [], "known_vulnerabilities": []})
    tool_fixture["id"] = tool_key
    archive_report = case["capture"] / "archive-report.json"
    archive_report.write_text(json.dumps({"schema": "cwl.release-runtime-archive-licenses/3",
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
                                                              "fixture_sha256": gate.fixture_digest(build_fixture)}],
                                          "build_tools": [{"key": tool_key,
                                                           "package_key": "github-release/maturin@1.15.0",
                                                           "name": "maturin", "version": "1.15.0",
                                                           "source_sha256": tool_sha,
                                                           "license": "Apache-2.0", "legs": ["sdist"],
                                                           "fixture": tool_fixture,
                                                           "fixture_sha256": gate.fixture_digest(tool_fixture)}]}))
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
    tool_variant = next(row for row in plan["dependencies"] if "build_tool" in row)
    tool_binding = copy.deepcopy(binding)
    tool_binding["dependency"] = tool_fixture["dependency"]
    tool_binding["fixture"].update(id=tool_key, sha256=tool_variant["fixture_sha256"])
    tool_zip = _zip(f"{tool_variant['slug']}.json", (json.dumps(tool_binding) + "\n").encode())
    case["archives"][97] = tool_zip
    case["metadata"].insert(-3, {"id": 97, "name": tool_variant["artifact_name"],
                                 "digest": "sha256:" + hashlib.sha256(tool_zip).hexdigest(),
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


def test_collector_refuses_malformed_metadata_destinations_and_distribution_rows(
    tmp_path: Path,
) -> None:
    def malformed_metadata(case):
        case["metadata"].append(None)

    def duplicate_name(case):
        case["metadata"].append({**case["metadata"][0], "id": 999})

    def existing_destination(case):
        case["report"].write_text("occupied")

    for name, mutate, verified, message in (
        ("metadata", malformed_metadata, None, "artifact metadata is invalid"),
        ("duplicate", duplicate_name, None, "duplicate artifact name"),
        ("destination", existing_destination, None, "destination already exists"),
        ("empty", lambda case: None, [], "distribution set is unavailable"),
        ("malformed-row", lambda case: None, [None], "malformed row"),
        ("no-wheel", lambda case: None, [{"leg": "sdist", "file": "source.tar.gz"}],
         "lacks wheel/sdist coverage"),
    ):
        case = _case(tmp_path / name)
        mutate(case)
        with pytest.raises(gate.GateError, match=message):
            _collect(case, case["verified"] if verified is None else verified)


def test_collector_refuses_missing_native_report_and_distribution_verifier_failure(
    tmp_path: Path, monkeypatch,
) -> None:
    case = _case(tmp_path / "missing-native")
    case["native_report"] = tmp_path / "missing.json"
    with pytest.raises(gate.GateError, match="native link report is missing"):
        _collect(case)

    case = _case(tmp_path / "distribution-error")
    monkeypatch.setattr(
        collector,
        "verify_distribution_set",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            collector.DistributionSetError("invalid distribution")
        ),
    )
    with pytest.raises(gate.GateError, match="failed immutable artifact verification"):
        _collect(case)


def test_collector_refuses_oversized_or_unbound_bindings_and_scope_rows(
    tmp_path: Path, monkeypatch,
) -> None:
    case = _case(tmp_path / "oversized")
    with monkeypatch.context() as bounded:
        bounded.setattr(collector, "MAX_CONTROL_BYTES", 1)
        with pytest.raises(gate.GateError, match="binding JSON exceeds"):
            _collect(case)

    case = _case(tmp_path / "unbound")
    plan = json.loads(case["plan"].read_text())
    first = plan["dependencies"][0]
    changed = _zip(f"{first['slug']}.json", b"{}\n")
    case["archives"][1] = changed
    case["metadata"][0]["digest"] = "sha256:" + hashlib.sha256(changed).hexdigest()
    with pytest.raises(gate.GateError, match="binding differs from plan"):
        _collect(case)

    case = _case(tmp_path / "scope-incomplete")
    path = case["capture"] / "verified-scope.json"
    path.write_text(json.dumps({"verified_scope_evidence": []}))
    case["verified_scope"] = path
    with pytest.raises(gate.GateError, match="scope set is incomplete"):
        _collect(case)

    case = _with_scope_set(_case(tmp_path / "scope-malformed"))
    payload = json.loads(case["verified_scope"].read_text())
    payload["verified_scope_evidence"][0]["artifact_name"] = "wrong"
    case["verified_scope"].write_text(json.dumps(payload))
    with pytest.raises(gate.GateError, match="scope identities are malformed"):
        _collect(case)


@pytest.mark.parametrize("with_optional_paths", [False, True])
def test_main_parses_files_and_forwards_optional_evidence(
    tmp_path: Path, monkeypatch, capsys, with_optional_paths: bool,
) -> None:
    metadata = tmp_path / "metadata.jsonl"
    metadata.write_text(json.dumps({"name": "artifact"}) + "\n")
    attempt = tmp_path / "attempt.json"
    attempt.write_text(json.dumps({"id": RUN}))
    verified = tmp_path / "verified.json"
    verified.write_text(json.dumps({"verified_distributions": [{"leg": "sdist"}]}))
    captured = {}

    def fake_collect(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(to_json=lambda: {"result": "PASS"})

    monkeypatch.setattr(collector, "collect_bindings", fake_collect)
    argv = [
        "collect_release_strix_bindings.py",
        "--capture", str(tmp_path / "capture"),
        "--license-report", str(tmp_path / "license.json"),
        "--plan", str(tmp_path / "plan.json"),
        "--metadata", str(metadata),
        "--attempt", str(attempt),
        "--repository", REPOSITORY,
        "--source-sha", SOURCE_SHA,
        "--control-sha", CONTROL,
        "--run-id", str(RUN),
        "--run-attempt", str(ATTEMPT),
        "--report", str(tmp_path / "report.json"),
        "--verified-distributions", str(verified),
        "--verdict", str(tmp_path / "verdict.json"),
        "--record-artifact-id", "900",
        "--record-artifact-digest", "sha256:" + "a" * 64,
    ]
    if with_optional_paths:
        argv.extend([
            "--runtime-archive-license-report", str(tmp_path / "archive.json"),
            "--verified-scope", str(tmp_path / "scope.json"),
            "--native-report", str(tmp_path / "native.json"),
        ])
    monkeypatch.setattr(sys, "argv", argv)
    collector.main()
    assert json.loads(capsys.readouterr().out) == {"result": "PASS"}
    assert (captured["archive_report_path"] is not None) is with_optional_paths
    assert (captured["verified_scope_path"] is not None) is with_optional_paths
    assert (captured["native_report_path"] is not None) is with_optional_paths

    verified.write_text("[]")
    with pytest.raises(gate.GateError, match="report is malformed"):
        collector.main()
