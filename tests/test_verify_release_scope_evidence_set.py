from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from scripts.ci.verify_release_distribution_set import DistributionSetError
from scripts.ci.verify_release_scope_evidence_set import verify_scope_evidence_set
from scripts.ci.prescreen_release_runtime_archives import prescreen
from scripts.ci import release_dependency_gate as gate


SOURCE = "a" * 40
CONTROL = "b" * 40
RUN = 424242
ATTEMPT = 2
MIT_TEXT = json.loads((Path(__file__).resolve().parent / "fixtures/release_license_texts/texts.json").read_text())["pytest-9.1.1.txt"]


def _zip(members: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return output.getvalue()


def _case() -> dict:
    archives, artifacts, distributions, evidence = {}, [], [], []
    for index in range(1, 14):
        leg = "sdist" if index == 13 else f"target{index}-py3.12"
        name = f"repro-digest-{leg}"
        members = {f"{leg}.tsv": b"row\n", f"{leg}.bundle.json": b"{}\n",
                   f"{leg}.build-first.json": b"{}\n",
                   f"{leg}.build-second.json": b"{}\n"}
        distribution = {"leg": leg, "artifact_id": index + 20,
                        "file": f"pkg-{index}.whl", "sha256": "d" * 64}
        if leg != "sdist":
            wheel_name = f"package-{index}.whl"
            wheel = _zip({f"package-{index}.dist-info/METADATA":
                          f"Name: package\nVersion: {index}\nLicense-Expression: MIT\nLicense-File: LICENSE\n".encode(),
                          f"package-{index}.dist-info/licenses/LICENSE": MIT_TEXT.encode()})
            runtime = {"source_sha": SOURCE, "leg": leg, "file": distribution["file"],
                       "sha256": distribution["sha256"],
                       "locked_dependencies": [{"name": "package", "version": str(index)}],
                       "archives": [{"file": wheel_name, "size": len(wheel),
                                     "sha256": hashlib.sha256(wheel).hexdigest(),
                                     "name": "package", "version": str(index)}]}
            members.update({f"{leg}.runtime.json": json.dumps(runtime).encode(),
                            f"{leg}.runtime-requirements.txt": b"lock\n",
                            wheel_name: wheel})
            consumer = b"consumer wheel bytes"
            receipt = {"schema_version": 1, "source_sha": SOURCE, "leg": leg,
                       "build_env": "runner:fixture", "sdist_file": "pkg-13.whl",
                       "sdist_sha256": "d" * 64, "file": distribution["file"],
                       "published_sha256": distribution["sha256"],
                       "consumer_sha256": hashlib.sha256(consumer).hexdigest(),
                       "metadata_members": {}, "native_extension": {}}
            members.update({f"{leg}.consumer.json": json.dumps(receipt).encode(),
                            f"{leg}.consumer.whl": consumer})
        archives[index] = _zip(members)
        digest = "sha256:" + hashlib.sha256(archives[index]).hexdigest()
        artifacts.append({"id": index, "name": name, "digest": digest,
                          "created_at": "2026-09-26T12:01:00Z", "expired": False,
                          "workflow_run": {"id": RUN, "head_sha": CONTROL}})
        distributions.append(distribution)
        evidence.append({"leg": leg, "artifact_id": index, "artifact_name": name,
                         "artifact_digest": digest})
    manifest = {"schema_version": 1, "source_repository": "owner/repo",
                "source_sha": SOURCE, "control_sha": CONTROL, "run_id": RUN,
                "run_attempt": ATTEMPT, "evidence": evidence}
    archives[14] = _zip({"reproducibility-record.tsv": b"record\n",
                         "release-scope-identities.json": b"[]\n",
                         "release-scope-evidence-set.json": json.dumps(manifest).encode(),
                         "release-gate-distribution-set.json": b"{}\n"})
    record_digest = "sha256:" + hashlib.sha256(archives[14]).hexdigest()
    artifacts.append({"id": 14, "name": "reproducibility-record", "digest": record_digest,
                      "created_at": "2026-09-26T12:01:00Z", "expired": False,
                      "workflow_run": {"id": RUN, "head_sha": CONTROL}})
    return {"archives": archives, "artifacts": artifacts, "distributions": distributions,
            "manifest": manifest, "record_digest": record_digest,
            "attempt": {"id": RUN, "run_attempt": ATTEMPT, "head_sha": CONTROL,
                        "run_started_at": "2026-09-26T12:00:00Z"}}


def _verify(case: dict, output: Path) -> list[dict]:
    def fetch(repository: str, artifact_id: int, target) -> None:
        assert repository == "owner/repo"
        target.write(case["archives"][artifact_id])

    return verify_scope_evidence_set(
        case["artifacts"], case["attempt"], repository="owner/repo",
        source_sha=SOURCE, control_sha=CONTROL, run_id=RUN, run_attempt=ATTEMPT,
        record_artifact_id=14, record_artifact_digest=case["record_digest"],
        distributions=case["distributions"], fetch=fetch, output_dir=output,
    )


def _repack_record(case: dict) -> None:
    with zipfile.ZipFile(io.BytesIO(case["archives"][14])) as archive:
        members = {member: archive.read(member) for member in archive.namelist()}
    members["release-scope-evidence-set.json"] = json.dumps(case["manifest"]).encode()
    case["archives"][14] = _zip(members)
    case["record_digest"] = "sha256:" + hashlib.sha256(case["archives"][14]).hexdigest()
    case["artifacts"][-1]["digest"] = case["record_digest"]


def _repack_scope(case: dict, members: dict[str, bytes], index: int = 1) -> None:
    case["archives"][index] = _zip(members)
    new_digest = "sha256:" + hashlib.sha256(case["archives"][index]).hexdigest()
    case["artifacts"][index - 1]["digest"] = new_digest
    case["manifest"]["evidence"][index - 1]["artifact_digest"] = new_digest
    _repack_record(case)


def test_transports_all_thirteen_exact_scope_artifact_archives(tmp_path: Path) -> None:
    case = _case()
    selected = _verify(case, tmp_path / "scope")
    assert len(selected) == 13
    for row in selected:
        folder = tmp_path / "scope" / row["artifact_name"]
        assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in folder.iterdir()} == row["members"]


def test_prescreens_exact_archives_and_refuses_changed_or_denied_wheels(tmp_path: Path) -> None:
    case = _case()
    scope_root = tmp_path / "scope"
    selected = _verify(case, scope_root)
    scope = {"verified_scope_evidence": selected}
    reviews = prescreen(scope, scope_root)
    assert len(reviews) == 12
    assert {row["license"] for row in reviews} == {"MIT"}
    assert all(row["key"] == f"{row['package_key']}/sha256/{row['source_sha256']}"
               and row["fixture"]["id"] == row["key"]
               and gate.fixture_digest(row["fixture"]) == row["fixture_sha256"]
               for row in reviews)
    wheel = scope_root / "repro-digest-target1-py3.12/package-1.whl"
    original = wheel.read_bytes()
    wheel.write_bytes(b"changed")
    with pytest.raises(gate.GateError, match=gate.SOURCE_HASH_MISMATCH):
        prescreen(scope, scope_root)
    wheel.write_bytes(_zip({"package-1.dist-info/METADATA":
                            b"Name: package\nVersion: 1\nLicense-Expression: GPL-3.0-only\nLicense-File: LICENSE\n",
                            "package-1.dist-info/licenses/LICENSE": MIT_TEXT.encode()}))
    changed = wheel.read_bytes()
    row = selected[0]["archives"][0]
    row["sha256"] = hashlib.sha256(changed).hexdigest()
    row["size"] = len(changed)
    with pytest.raises(gate.GateError, match="LICENSE_DENIED"):
        prescreen(scope, scope_root)
    wheel.write_bytes(original)


def test_workflow_requires_scope_transport_before_dependency_capture() -> None:
    workflow = Path(".github/workflows/release-dependency-license-strix-gate.yml").read_text()
    prepare = workflow.split("  prepare:\n", 1)[1].split("\n  strix:\n", 1)[0]
    transport = "python3 -I trusted-gate/scripts/ci/verify_release_scope_evidence_set.py"
    license_stage = "python3 -I trusted-gate/scripts/ci/prescreen_release_runtime_archives.py"
    capture = "bash trusted-gate/scripts/ci/release_dependency_capture_raw.sh"
    assert prepare.index(transport) < prepare.index(license_stage) < prepare.index(capture)
    assert workflow.index(transport) < workflow.index(license_stage) < workflow.rindex(capture)


def test_refuses_missing_foreign_and_changed_scope_artifacts(tmp_path: Path) -> None:
    for name, mutate in (
        ("missing", lambda case: case["artifacts"].pop(0)),
        ("foreign", lambda case: case["artifacts"][0]["workflow_run"].update(id=1)),
        ("tampered", lambda case: case["archives"].update({1: _zip({"bad": b"bytes"})})),
        ("other-source", lambda case: case["manifest"].update(source_sha="c" * 40)),
    ):
        case = _case()
        mutate(case)
        if name == "other-source":
            _repack_record(case)
        with pytest.raises(DistributionSetError):
            _verify(case, tmp_path / name)
        assert not (tmp_path / name).exists()


def test_refuses_repacked_archive_when_runtime_receipt_hash_is_stale(tmp_path: Path) -> None:
    case = _case()
    with zipfile.ZipFile(io.BytesIO(case["archives"][1])) as archive:
        members = {member: archive.read(member) for member in archive.namelist()}
    members["package-1.whl"] = b"different bytes"
    _repack_scope(case, members)
    with pytest.raises(DistributionSetError, match="runtime archive differs"):
        _verify(case, tmp_path / "changed-inner")
    assert not (tmp_path / "changed-inner").exists()


def test_refuses_scope_archive_without_both_build_receipts(tmp_path: Path) -> None:
    case = _case()
    with zipfile.ZipFile(io.BytesIO(case["archives"][1])) as archive:
        members = {member: archive.read(member) for member in archive.namelist()}
    del members["target1-py3.12.build-second.json"]
    _repack_scope(case, members)
    with pytest.raises(DistributionSetError, match="scope artifact members differ"):
        _verify(case, tmp_path / "missing-build")

    case = _case()
    with zipfile.ZipFile(io.BytesIO(case["archives"][13])) as archive:
        members = {member: archive.read(member) for member in archive.namelist()}
    del members["sdist.build-first.json"]
    _repack_scope(case, members, index=13)
    with pytest.raises(DistributionSetError, match="scope artifact members differ"):
        _verify(case, tmp_path / "missing-sdist-build")


def test_refuses_missing_or_changed_sdist_consumer_wheel(tmp_path: Path) -> None:
    for mode in ("missing", "changed"):
        case = _case()
        with zipfile.ZipFile(io.BytesIO(case["archives"][1])) as archive:
            members = {member: archive.read(member) for member in archive.namelist()}
        if mode == "missing":
            del members["target1-py3.12.consumer.whl"]
        else:
            members["target1-py3.12.consumer.whl"] = b"changed"
        _repack_scope(case, members)
        with pytest.raises(DistributionSetError, match="scope artifact members differ|consumer receipt differs"):
            _verify(case, tmp_path / mode)
        assert not (tmp_path / mode).exists()


def test_refuses_wheel_metadata_identity_even_with_rehashed_receipt(tmp_path: Path) -> None:
    case = _case()
    with zipfile.ZipFile(io.BytesIO(case["archives"][1])) as archive:
        members = {member: archive.read(member) for member in archive.namelist()}
    wheel = _zip({"other-1.dist-info/METADATA": b"Name: other\nVersion: 1\n"})
    members["package-1.whl"] = wheel
    runtime = json.loads(members["target1-py3.12.runtime.json"])
    runtime["archives"][0]["sha256"] = hashlib.sha256(wheel).hexdigest()
    runtime["archives"][0]["size"] = len(wheel)
    members["target1-py3.12.runtime.json"] = json.dumps(runtime).encode()
    _repack_scope(case, members)
    with pytest.raises(DistributionSetError, match="runtime archive differs"):
        _verify(case, tmp_path / "metadata")
    assert not (tmp_path / "metadata").exists()
