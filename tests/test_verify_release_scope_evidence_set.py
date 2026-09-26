from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from scripts.ci.verify_release_distribution_set import DistributionSetError
from scripts.ci.verify_release_scope_evidence_set import verify_scope_evidence_set
from scripts.ci.prescreen_release_runtime_archives import _build_packages, prescreen
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
    tool_assets = json.loads((Path(__file__).resolve().parents[1] /
                              "scripts/ci/release_maturin_tool_evidence.json").read_text())["assets"]
    legs = [f"{target}-py{version}" for target in (
        "x86_64-unknown-linux-gnu", "aarch64-unknown-linux-gnu",
        "universal2-apple-darwin", "x86_64-pc-windows-msvc")
        for version in ("3.12", "3.13", "3.14")] + ["sdist"]
    for index, leg in enumerate(legs, 1):
        name = f"repro-digest-{leg}"
        target = "x86_64-unknown-linux-gnu" if leg == "sdist" else leg.rsplit("-py", 1)[0]
        build_env = ({"universal2-apple-darwin": "runner:macos/15/macOS/ARM64",
                      "x86_64-pc-windows-msvc": "runner:windows/2025/Windows/X64"}.get(target)
                     or ("runner:ubuntu/24.04/Linux/X64" if leg == "sdist" else
                         "container:ghcr.io/pyo3/maturin@sha256:" + "a" * 64))
        asset_key = target + "/ARM64" if target == "universal2-apple-darwin" else target
        installed = {"pip/a.py": b"x",
                     "pip-25.2.dist-info/METADATA":
                         b"Name: pip\nVersion: 25.2\nLicense-Expression: MIT\nLicense-File: LICENSE\n",
                     "pip-25.2.dist-info/licenses/LICENSE": MIT_TEXT.encode()}
        snapshot = _zip({f"pip/{name}": payload for name, payload in installed.items()})
        build = {"source_sha": SOURCE, "leg": leg, "build_env": build_env,
                 "maturin_version": "maturin 1.15.0",
                 "maturin_binary_sha256": tool_assets[asset_key]["binary_sha256"],
                 "python_snapshot_sha256": hashlib.sha256(snapshot).hexdigest(),
                 "python_packages": [{"name": "pip", "version": "25.2", "files": sorted((
                     {"path": name, "size": len(payload),
                      "sha256": hashlib.sha256(payload).hexdigest()}
                     for name, payload in installed.items()), key=lambda row: row["path"])}]}
        members = {f"{leg}.tsv": b"row\n", f"{leg}.bundle.json": b"{}\n",
                   f"{leg}.build-first.json": json.dumps(build | {"pass": "first"}).encode(),
                   f"{leg}.build-second.json": json.dumps(build | {"pass": "second"}).encode(),
                   f"{leg}.build-python.zip": snapshot}
        distribution = {"leg": leg, "artifact_id": index + 20,
                        "file": f"pkg-{index}.whl", "sha256": "d" * 64}
        if leg != "sdist":
            wheel_name = f"package-{index}.whl"
            wheel = _zip({f"package-{index}.dist-info/METADATA":
                          f"Name: package\nVersion: {index}\nLicense-Expression: MIT\nLicense-File: LICENSE\n".encode(),
                          f"package-{index}.dist-info/licenses/LICENSE": MIT_TEXT.encode()})
            runtime = {"source_sha": SOURCE, "leg": leg, "file": distribution["file"],
                       "sha256": distribution["sha256"],
                       "uv_version": "uv 0.12.5", "python_version": "3.12",
                       "implementation": "cpython", "sys_platform": "linux", "machine": "x86_64",
                       "requirements_sha256": "a" * 64, "uv_lock_sha256": "b" * 64,
                       "locked_dependencies": [{"name": "package", "version": str(index)}],
                       "installed": [{"name": "fast-mlsirm", "version": "0.11.4"}],
                       "archives": [{"file": wheel_name, "size": len(wheel),
                                     "sha256": hashlib.sha256(wheel).hexdigest(),
                                     "name": "package", "version": str(index)}]}
            members.update({f"{leg}.runtime.json": json.dumps(runtime).encode(),
                            f"{leg}.runtime-requirements.txt": b"lock\n",
                            wheel_name: wheel})
            metadata_name = "fast_mlsirm-0.11.4.dist-info/METADATA"
            wheel_name_record = "fast_mlsirm-0.11.4.dist-info/WHEEL"
            extension_name = "fast_mlsirm/_core.cpython-312-x86_64-linux-gnu.so"
            metadata_bytes = b"Name: fast-mlsirm\nVersion: 0.11.4\n"
            wheel_bytes = b"Wheel-Version: 1.0\nTag: cp312-cp312-manylinux_2_17_x86_64\n"
            extension_bytes = b"\x7fELFconsumer extension"
            consumer = _zip({metadata_name: metadata_bytes,
                             wheel_name_record: wheel_bytes,
                             extension_name: extension_bytes})
            receipt = {"schema_version": 1, "source_sha": SOURCE, "leg": leg,
                       "build_env": "runner:fixture", "sdist_file": "pkg-13.whl",
                       "sdist_sha256": "d" * 64, "file": distribution["file"],
                       "published_sha256": distribution["sha256"],
                       "consumer_sha256": hashlib.sha256(consumer).hexdigest(),
                       "metadata_members": {
                           metadata_name: hashlib.sha256(metadata_bytes).hexdigest(),
                           wheel_name_record: hashlib.sha256(wheel_bytes).hexdigest(),
                       },
                       "native_extension": {
                           "member": extension_name,
                           "sha256": hashlib.sha256(extension_bytes).hexdigest(),
                       },
                       "installation": {key: runtime[key] for key in (
                           "uv_version", "python_version", "implementation", "sys_platform",
                           "machine", "requirements_sha256", "uv_lock_sha256",
                           "locked_dependencies", "installed")} | {
                               "imported_extension": {
                                   "member": extension_name,
                                   "sha256": hashlib.sha256(extension_bytes).hexdigest(),
                               }}}
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
    assert len(reviews["archives"]) == 12
    assert len(reviews["build_packages"]) == 1
    assert len(reviews["build_tools"]) == 4
    assert {row["license"] for row in reviews["build_tools"]} == {"Apache-2.0"}
    assert {row["license"] for row in [*reviews["archives"], *reviews["build_packages"]]} == {"MIT"}
    assert all(row["key"] == f"{row['package_key']}/sha256/{row['source_sha256']}"
               and row["fixture"]["id"] == row["key"]
               and gate.fixture_digest(row["fixture"]) == row["fixture_sha256"]
               for row in [*reviews["archives"], *reviews["build_packages"]])
    wheel = scope_root / "repro-digest-x86_64-unknown-linux-gnu-py3.12/package-1.whl"
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


def test_maturin_prescreen_refuses_changed_or_foreign_executable(tmp_path: Path) -> None:
    case = _case()
    root = tmp_path / "scope"
    selected = _verify(case, root)
    scope = {"verified_scope_evidence": selected}
    row = selected[0]
    leg = row["leg"]
    receipt_path = root / row["artifact_name"] / f"{leg}.build-first.json"
    original = receipt_path.read_bytes()
    receipt = json.loads(original)
    receipt["maturin_binary_sha256"] = "0" * 64
    changed = json.dumps(receipt).encode()
    receipt_path.write_bytes(changed)
    with pytest.raises(gate.GateError, match="receipts changed"):
        prescreen(scope, root)
    row["members"][receipt_path.name] = hashlib.sha256(changed).hexdigest()
    with pytest.raises(gate.GateError, match="executable differs"):
        prescreen(scope, root)
    receipt_path.write_bytes(original)
    row["members"][receipt_path.name] = hashlib.sha256(original).hexdigest()
    second_path = receipt_path.with_name(f"{leg}.build-second.json")
    second = json.loads(second_path.read_text())
    second["maturin_binary_sha256"] = "0" * 64
    changed = json.dumps(second).encode()
    second_path.write_bytes(changed)
    row["members"][second_path.name] = hashlib.sha256(changed).hexdigest()
    with pytest.raises(gate.GateError, match="executable differs"):
        prescreen(scope, root)


@pytest.mark.parametrize("metadata,reason", [
    (b"Name: pip\nVersion: 25.2\nLicense-Expression: GPL-3.0-only\nLicense-File: LICENSE\n", "LICENSE_DENIED"),
    (b"Name: foreign\nVersion: 25.2\nLicense-Expression: MIT\nLicense-File: LICENSE\n", "metadata differs"),
    (b"Name: pip\nName: foreign\nVersion: 25.2\nLicense-Expression: MIT\nLicense-File: LICENSE\n", "metadata differs"),
])
def test_build_package_prescreen_refuses_denied_or_foreign_metadata(
    tmp_path: Path, metadata: bytes, reason: str,
) -> None:
    case = _case()
    root = tmp_path / "scope"
    selected = _verify(case, root)
    row = selected[0]
    leg = row["leg"]
    folder = root / row["artifact_name"]
    snapshot = folder / f"{leg}.build-python.zip"
    with zipfile.ZipFile(snapshot) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    members["pip/pip-25.2.dist-info/METADATA"] = metadata
    snapshot.write_bytes(_zip(members))
    receipt_path = folder / f"{leg}.build-first.json"
    receipt = json.loads(receipt_path.read_text())
    file = next(item for item in receipt["python_packages"][0]["files"]
                if item["path"].endswith(".dist-info/METADATA"))
    file.update(size=len(metadata), sha256=hashlib.sha256(metadata).hexdigest())
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    receipt["python_snapshot_sha256"] = digest
    receipt_path.write_text(json.dumps(receipt))
    row["members"][snapshot.name] = digest
    with pytest.raises(gate.GateError, match=reason):
        _build_packages(row, folder)


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
    del members["x86_64-unknown-linux-gnu-py3.12.build-second.json"]
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


def test_refuses_missing_or_changed_build_snapshot(tmp_path: Path) -> None:
    for mode in ("missing", "changed"):
        case = _case()
        with zipfile.ZipFile(io.BytesIO(case["archives"][1])) as archive:
            members = {member: archive.read(member) for member in archive.namelist()}
        name = "x86_64-unknown-linux-gnu-py3.12.build-python.zip"
        if mode == "missing":
            del members[name]
        else:
            members[name] = _zip({"pip/pip/a.py": b"forged"})
        _repack_scope(case, members)
        with pytest.raises(DistributionSetError, match="scope artifact members differ|snapshot receipt differs"):
            _verify(case, tmp_path / mode)
        assert not (tmp_path / mode).exists()


def test_refuses_duplicate_build_distribution_name(tmp_path: Path) -> None:
    case = _case()
    with zipfile.ZipFile(io.BytesIO(case["archives"][1])) as archive:
        members = {member: archive.read(member) for member in archive.namelist()}
    for build_pass in ("first", "second"):
        name = f"x86_64-unknown-linux-gnu-py3.12.build-{build_pass}.json"
        receipt = json.loads(members[name])
        duplicate = json.loads(json.dumps(receipt["python_packages"][0]))
        duplicate["files"][0]["path"] = "other.py"
        receipt["python_packages"].append(duplicate)
        members[name] = json.dumps(receipt).encode()
    _repack_scope(case, members)
    with pytest.raises(DistributionSetError, match="build package inventory is missing"):
        _verify(case, tmp_path / "duplicate-build-package")


def test_refuses_missing_or_changed_sdist_consumer_wheel(tmp_path: Path) -> None:
    for mode in ("missing", "changed"):
        case = _case()
        with zipfile.ZipFile(io.BytesIO(case["archives"][1])) as archive:
            members = {member: archive.read(member) for member in archive.namelist()}
        if mode == "missing":
            del members["x86_64-unknown-linux-gnu-py3.12.consumer.whl"]
        else:
            members["x86_64-unknown-linux-gnu-py3.12.consumer.whl"] = b"changed"
        _repack_scope(case, members)
        with pytest.raises(DistributionSetError, match="scope artifact members differ|consumer receipt differs"):
            _verify(case, tmp_path / mode)
        assert not (tmp_path / mode).exists()


def test_refuses_consumer_install_mismatch(tmp_path: Path) -> None:
    case = _case()
    with zipfile.ZipFile(io.BytesIO(case["archives"][1])) as archive:
        members = {member: archive.read(member) for member in archive.namelist()}
    receipt = json.loads(members["x86_64-unknown-linux-gnu-py3.12.consumer.json"])
    receipt["installation"]["installed"] = []
    members["x86_64-unknown-linux-gnu-py3.12.consumer.json"] = json.dumps(receipt).encode()
    _repack_scope(case, members)
    with pytest.raises(DistributionSetError, match="consumer receipt differs"):
        _verify(case, tmp_path / "forged-install")
    assert not (tmp_path / "forged-install").exists()


@pytest.mark.parametrize("field", ["metadata_members", "native_extension"])
def test_refuses_consumer_receipt_that_differs_from_wheel(
    tmp_path: Path, field: str,
) -> None:
    case = _case()
    with zipfile.ZipFile(io.BytesIO(case["archives"][1])) as archive:
        members = {member: archive.read(member) for member in archive.namelist()}
    receipt = json.loads(members["x86_64-unknown-linux-gnu-py3.12.consumer.json"])
    if field == "metadata_members":
        receipt[field] = {"forged.dist-info/METADATA": "0" * 64}
    else:
        receipt[field] = {"member": "fast_mlsirm/_core.forged.so", "sha256": "0" * 64}
        receipt["installation"]["imported_extension"] = receipt[field]
    members["x86_64-unknown-linux-gnu-py3.12.consumer.json"] = json.dumps(receipt).encode()
    _repack_scope(case, members)
    with pytest.raises(DistributionSetError, match="consumer receipt differs"):
        _verify(case, tmp_path / field)
    assert not (tmp_path / field).exists()


def test_refuses_consumer_metadata_split_across_dist_info_roots(tmp_path: Path) -> None:
    case = _case()
    with zipfile.ZipFile(io.BytesIO(case["archives"][1])) as archive:
        members = {member: archive.read(member) for member in archive.namelist()}
    receipt = json.loads(members["x86_64-unknown-linux-gnu-py3.12.consumer.json"])
    extension = receipt["native_extension"]
    metadata_name = "fast_mlsirm-0.11.4.dist-info/METADATA"
    wheel_name = "other-0.11.4.dist-info/WHEEL"
    metadata_bytes = b"Name: fast-mlsirm\nVersion: 0.11.4\n"
    wheel_bytes = b"Wheel-Version: 1.0\nTag: cp312-cp312-manylinux_2_17_x86_64\n"
    extension_bytes = b"\x7fELFconsumer extension"
    consumer = _zip({metadata_name: metadata_bytes, wheel_name: wheel_bytes,
                     extension["member"]: extension_bytes})
    receipt["consumer_sha256"] = hashlib.sha256(consumer).hexdigest()
    receipt["metadata_members"] = {
        metadata_name: hashlib.sha256(metadata_bytes).hexdigest(),
        wheel_name: hashlib.sha256(wheel_bytes).hexdigest(),
    }
    members["x86_64-unknown-linux-gnu-py3.12.consumer.whl"] = consumer
    members["x86_64-unknown-linux-gnu-py3.12.consumer.json"] = json.dumps(receipt).encode()
    _repack_scope(case, members)
    with pytest.raises(DistributionSetError, match="metadata or native layout differs"):
        _verify(case, tmp_path / "split-dist-info")
    assert not (tmp_path / "split-dist-info").exists()


def test_refuses_wheel_metadata_identity_even_with_rehashed_receipt(tmp_path: Path) -> None:
    case = _case()
    with zipfile.ZipFile(io.BytesIO(case["archives"][1])) as archive:
        members = {member: archive.read(member) for member in archive.namelist()}
    wheel = _zip({"other-1.dist-info/METADATA": b"Name: other\nVersion: 1\n"})
    members["package-1.whl"] = wheel
    runtime = json.loads(members["x86_64-unknown-linux-gnu-py3.12.runtime.json"])
    runtime["archives"][0]["sha256"] = hashlib.sha256(wheel).hexdigest()
    runtime["archives"][0]["size"] = len(wheel)
    members["x86_64-unknown-linux-gnu-py3.12.runtime.json"] = json.dumps(runtime).encode()
    _repack_scope(case, members)
    with pytest.raises(DistributionSetError, match="runtime archive differs"):
        _verify(case, tmp_path / "metadata")
    assert not (tmp_path / "metadata").exists()
