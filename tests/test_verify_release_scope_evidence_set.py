from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from scripts.ci.verify_release_distribution_set import DistributionSetError
from scripts.ci.verify_release_scope_evidence_set import verify_scope_evidence_set


SOURCE = "a" * 40
CONTROL = "b" * 40
RUN = 424242
ATTEMPT = 2


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
        members = {f"{leg}.tsv": b"row\n", f"{leg}.bundle.json": b"{}\n"}
        distribution = {"leg": leg, "artifact_id": index + 20,
                        "file": f"pkg-{index}.whl", "sha256": "d" * 64}
        if leg != "sdist":
            wheel_name = f"package-{index}.whl"
            wheel = b"archive bytes"
            runtime = {"source_sha": SOURCE, "leg": leg, "file": distribution["file"],
                       "sha256": distribution["sha256"],
                       "archives": [{"file": wheel_name, "size": len(wheel),
                                     "sha256": hashlib.sha256(wheel).hexdigest(),
                                     "name": "package", "version": str(index)}]}
            members.update({f"{leg}.runtime.json": json.dumps(runtime).encode(),
                            f"{leg}.runtime-requirements.txt": b"lock\n",
                            wheel_name: wheel})
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


def test_transports_all_thirteen_exact_scope_artifact_archives(tmp_path: Path) -> None:
    case = _case()
    selected = _verify(case, tmp_path / "scope")
    assert len(selected) == 13
    for row in selected:
        folder = tmp_path / "scope" / row["artifact_name"]
        assert {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in folder.iterdir()} == row["members"]


def test_workflow_requires_scope_transport_before_dependency_capture() -> None:
    workflow = Path(".github/workflows/release-dependency-license-strix-gate.yml").read_text()
    transport = "python3 -I trusted-gate/scripts/ci/verify_release_scope_evidence_set.py"
    capture = "bash trusted-gate/scripts/ci/release_dependency_capture_raw.sh"
    assert transport in workflow
    assert workflow.index(transport) < workflow.rindex(capture)


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
    case["archives"][1] = _zip(members)
    new_digest = "sha256:" + hashlib.sha256(case["archives"][1]).hexdigest()
    case["artifacts"][0]["digest"] = new_digest
    case["manifest"]["evidence"][0]["artifact_digest"] = new_digest
    _repack_record(case)
    with pytest.raises(DistributionSetError, match="runtime archive differs"):
        _verify(case, tmp_path / "changed-inner")
    assert not (tmp_path / "changed-inner").exists()
