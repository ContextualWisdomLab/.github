from __future__ import annotations

import hashlib
import io
import json
import runpy
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from scripts.ci import prescreen_release_runtime_archives as prescreen_module
from scripts.ci import release_dependency_gate as gate
from scripts.ci import verify_release_scope_evidence_set as scope_module
from scripts.ci.prescreen_release_runtime_archives import (
    _build_packages,
    _maturin_tool,
    prescreen,
)
from scripts.ci.verify_release_distribution_set import DistributionSetError
from scripts.ci.verify_release_scope_evidence_set import (
    verify_macos_x86_runtime_set,
    verify_scope_evidence_set,
)

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


def test_runtime_native_wheel_reads_links_and_refuses_uninspected_members(monkeypatch):
    """The archive prescreen must not infer empty links from a native path."""
    monkeypatch.setattr(prescreen_module, "_reader", lambda: {"path": "/pinned/llvm-readobj"})
    monkeypatch.setattr(prescreen_module, "_links", lambda binary, target, reader, **kwargs: [
        {"arch": "x86_64", "needed": ["libc.so.6"]}])
    wheel = _zip({"directory/": b"", "package/native.so": b"\x7fELFfixture",
                  "package/second.pyd": b"MZfixture"})
    assert prescreen_module._native_wheel_libraries(wheel, "x86_64-unknown-linux-gnu") == [
        {"path": "package/native.so", "needed": ["libc.so.6"], "static_archives": []},
        {"path": "package/second.pyd", "needed": ["libc.so.6"], "static_archives": []}]
    assert prescreen_module._native_wheel_libraries(
        wheel, "universal2-apple-darwin", required_architecture="x86_64",
    ) == [
        {"path": "package/native.so", "needed": ["libc.so.6"], "static_archives": []},
        {"path": "package/second.pyd", "needed": ["libc.so.6"], "static_archives": []}]
    with pytest.raises(gate.GateError, match="static or wasm native member"):
        prescreen_module._native_wheel_libraries(
            _zip({"package/libnative.a": b"!<arch>\n"}), "x86_64-unknown-linux-gnu")


def test_runtime_native_wheel_refuses_oversized_or_unreadable_members(monkeypatch):
    """Native inspection must fail closed on resource and analyzer failures."""
    class OversizedEntry:
        filename = "package/native.so"
        file_size = 128 * 1024 * 1024 + 1

        @staticmethod
        def is_dir() -> bool:
            return False

    class OversizedArchive:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def infolist():
            return [OversizedEntry()]

        @staticmethod
        def open(_entry):
            return io.BytesIO(b"\x7fELFfixture")

    with monkeypatch.context() as scoped:
        scoped.setattr(prescreen_module.zipfile, "ZipFile", lambda *_args: OversizedArchive())
        with pytest.raises(gate.GateError, match="exceeds inspection limit"):
            prescreen_module._native_wheel_libraries(
                b"fixture", "x86_64-unknown-linux-gnu"
            )

    monkeypatch.setattr(
        prescreen_module,
        "_reader",
        lambda: (_ for _ in ()).throw(ValueError("unavailable")),
    )
    with pytest.raises(gate.GateError, match="could not be inspected"):
        prescreen_module._native_wheel_libraries(
            _zip({"package/native.so": b"\x7fELFfixture"}),
            "x86_64-unknown-linux-gnu",
        )


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
                       "uv_version": "uv 0.12.5", "python_version": leg.rsplit("-py", 1)[1],
                       "implementation": "cpython",
                       "sys_platform": {"x86_64-unknown-linux-gnu": "linux", "aarch64-unknown-linux-gnu": "linux",
                                        "universal2-apple-darwin": "darwin", "x86_64-pc-windows-msvc": "win32"}[target],
                       "machine": {"x86_64-unknown-linux-gnu": "x86_64", "aarch64-unknown-linux-gnu": "aarch64",
                                   "universal2-apple-darwin": "arm64", "x86_64-pc-windows-msvc": "AMD64"}[target],
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


def _scope_folder(tmp_path: Path, index: int = 1) -> tuple[dict, Path, str, dict[str, str]]:
    case = _case()
    leg = case["distributions"][index - 1]["leg"]
    folder = tmp_path / f"scope-{index}"
    folder.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(case["archives"][index])) as archive:
        archive.extractall(folder)
    members = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
               for path in folder.iterdir()}
    return case, folder, leg, members


def _prescreen_case(tmp_path: Path) -> tuple[Path, list[dict]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    scope_case = _case()
    scope_root = tmp_path / "scope"
    return scope_root, _verify(scope_case, scope_root)


def _scope_with_variants(rows: list[dict], root: Path) -> dict:
    variants = []
    for row in rows:
        if not row["leg"].startswith("universal2-apple-darwin-"):
            continue
        name = f"repro-macos-x86-{row['leg']}"
        if not (root / name).exists():
            shutil.copytree(root / row["artifact_name"], root / name)
        runtime_path = root / name / f"{row['leg']}.runtime.json"
        runtime = json.loads(runtime_path.read_text())
        runtime["machine"] = "x86_64"
        runtime_path.write_text(json.dumps(runtime))
        members = {**row["members"], runtime_path.name: hashlib.sha256(runtime_path.read_bytes()).hexdigest()}
        variants.append({**row, "arch": "x86_64", "artifact_name": name, "members": members})
    return {"verified_scope_evidence": rows, "verified_runtime_variants": variants}


def _add_intel_artifacts(case: dict) -> None:
    legs = [row["leg"] for row in case["distributions"]
            if row["leg"].startswith("universal2-apple-darwin-")]
    for offset, leg in enumerate(legs, 100):
        row = next(item for item in case["distributions"] if item["leg"] == leg)
        wheel = _zip({f"package_x86_{offset}-1.dist-info/METADATA":
                      f"Name: package-x86-{offset}\nVersion: 1\nLicense-Expression: MIT\nLicense-File: LICENSE\n".encode(),
                      f"package_x86_{offset}-1.dist-info/licenses/LICENSE": MIT_TEXT.encode()})
        wheel_name = f"package_x86_{offset}-1-py3-none-macosx_11_0_x86_64.whl"
        requirements = b"package-x86==1\n"
        runtime = {"source_sha": SOURCE, "leg": leg, "file": row["file"],
                   "sha256": row["sha256"], "build_env": "runner:macos/15/macOS/ARM64",
                   "uv_version": "uv 0.12.5", "python_version": leg.rsplit("-py", 1)[1],
                   "implementation": "cpython", "sys_platform": "darwin", "machine": "x86_64",
                   "requirements_sha256": hashlib.sha256(requirements).hexdigest(),
                   "uv_lock_sha256": "a" * 64,
                   "locked_dependencies": [{"name": f"package-x86-{offset}", "version": "1"}],
                   "archives": [{"file": wheel_name, "size": len(wheel),
                                 "sha256": hashlib.sha256(wheel).hexdigest(),
                                 "name": f"package-x86-{offset}", "version": "1"}]}
        members = {f"{leg}.tsv": ("\t".join([leg, "true", "clean-target-repeat-same-env",
                    row["sha256"], row["sha256"], row["file"], runtime["build_env"]]) + "\n").encode(),
                   f"{leg}.runtime.json": json.dumps(runtime | {"source_sha": SOURCE}).encode(),
                   f"{leg}.runtime-requirements.txt": requirements,
                   wheel_name: wheel}
        archive = _zip(members)
        case["archives"][offset] = archive
        case["artifacts"].append({"id": offset, "name": f"repro-macos-x86-{leg}",
                                  "digest": "sha256:" + hashlib.sha256(archive).hexdigest(),
                                  "created_at": "2026-09-26T12:01:00Z", "expired": False,
                                  "workflow_run": {"id": RUN, "head_sha": CONTROL}})


def _verify_intel(case: dict, output: Path) -> list[dict]:
    output.mkdir()

    def fetch(repository: str, artifact_id: int, target) -> None:
        assert repository == "owner/repo"
        target.write(case["archives"][artifact_id])

    return verify_macos_x86_runtime_set(
        case["artifacts"], case["attempt"], repository="owner/repo",
        source_sha=SOURCE, control_sha=CONTROL, run_id=RUN, run_attempt=ATTEMPT,
        distributions=case["distributions"], fetch=fetch, output_dir=output)


def test_intel_runtime_artifacts_bind_same_run_wheels_and_archive_bytes(tmp_path: Path) -> None:
    case = _case()
    _add_intel_artifacts(case)
    selected = _verify_intel(case, tmp_path / "ok")
    assert len(selected) == 3
    assert {row["arch"] for row in selected} == {"x86_64"}
    assert all(len(row["archives"]) == 1 for row in selected)
    case["artifacts"][-1]["workflow_run"]["id"] = 1
    with pytest.raises(DistributionSetError, match="foreign"):
        _verify_intel(case, tmp_path / "foreign")
    case["artifacts"][-1]["workflow_run"]["id"] = RUN
    case["archives"][102] += b"changed"
    with pytest.raises(DistributionSetError, match="digest mismatch"):
        _verify_intel(case, tmp_path / "changed")


@pytest.mark.parametrize(("change", "reason"), [
    ("attempt", "workflow attempt differs"),
    ("duplicate-metadata", "duplicate Intel runtime artifact metadata"),
    ("missing-wheel", "no selected universal2 distributions"),
    ("missing-artifact", "artifact set is incomplete"),
    ("duplicate-id", "artifact identity is malformed"),
    ("missing-member", "artifact members differ"),
    ("wrong-receipt", "receipt differs from selected wheel"),
])
def test_intel_runtime_refuses_incomplete_or_forged_evidence(
        tmp_path: Path, change: str, reason: str) -> None:
    case = _case()
    _add_intel_artifacts(case)
    if change == "attempt":
        case["attempt"]["run_attempt"] += 1
    elif change == "duplicate-metadata":
        case["artifacts"].append(dict(case["artifacts"][-1]))
    elif change == "missing-wheel":
        case["distributions"] = [row for row in case["distributions"]
                                 if row["leg"] != "universal2-apple-darwin-py3.12"]
    elif change == "missing-artifact":
        case["artifacts"].pop()
    elif change == "duplicate-id":
        case["artifacts"][-1]["id"] = case["distributions"][0]["artifact_id"]
    else:
        with zipfile.ZipFile(io.BytesIO(case["archives"][100])) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        leg = "universal2-apple-darwin-py3.12"
        if change == "missing-member":
            members.pop(f"{leg}.runtime-requirements.txt")
        else:
            runtime = json.loads(members[f"{leg}.runtime.json"])
            runtime["machine"] = "arm64"
            members[f"{leg}.runtime.json"] = json.dumps(runtime).encode()
        case["archives"][100] = _zip(members)
        item = next(item for item in case["artifacts"] if item["id"] == 100)
        item["digest"] = "sha256:" + hashlib.sha256(case["archives"][100]).hexdigest()
    with pytest.raises(DistributionSetError, match=reason):
        _verify_intel(case, tmp_path / change)


def test_intel_runtime_refuses_missing_destination_and_oversized_members(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case = _case()
    _add_intel_artifacts(case)
    def fetch(_repository: str, artifact_id: int, target) -> None:
        target.write(case["archives"][artifact_id])
    arguments = dict(repository="owner/repo", source_sha=SOURCE, control_sha=CONTROL,
                     run_id=RUN, run_attempt=ATTEMPT, distributions=case["distributions"], fetch=fetch)
    with pytest.raises(DistributionSetError, match="not materialized"):
        verify_macos_x86_runtime_set(case["artifacts"], case["attempt"],
                                     output_dir=tmp_path / "missing", **arguments)
    monkeypatch.setattr(scope_module, "MAX_ARCHIVE_BYTES", 1)
    with pytest.raises(DistributionSetError, match="exceeds size limit"):
        _verify_intel(case, tmp_path / "large")


def test_intel_dependency_wheels_enter_license_prescreen(tmp_path: Path) -> None:
    case = _case()
    _add_intel_artifacts(case)
    root = tmp_path / "scope"
    selected = _verify(case, root)

    def fetch(_repository: str, artifact_id: int, target) -> None:
        target.write(case["archives"][artifact_id])

    variants = verify_macos_x86_runtime_set(
        case["artifacts"], case["attempt"], repository="owner/repo",
        source_sha=SOURCE, control_sha=CONTROL, run_id=RUN, run_attempt=ATTEMPT,
        distributions=case["distributions"], fetch=fetch, output_dir=root)
    report = prescreen({"verified_scope_evidence": selected,
                        "verified_runtime_variants": variants}, root)
    assert len(report["archives"]) == 15
    assert {row["name"] for row in report["archives"] if row["name"].startswith("package-x86-")} == {
        "package-x86-100", "package-x86-101", "package-x86-102"}


def test_intel_native_dependency_requires_x86_64_architecture(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Intel variants must recheck architecture before package/hash deduplication."""
    case = _case()
    primary_index = 7
    with zipfile.ZipFile(io.BytesIO(case["archives"][primary_index])) as primary_artifact:
        primary_members = {name: primary_artifact.read(name)
                           for name in primary_artifact.namelist()}
    primary_wheel_name = "package-7.whl"
    with zipfile.ZipFile(io.BytesIO(primary_members[primary_wheel_name])) as wheel_archive:
        wheel_members = {name: wheel_archive.read(name) for name in wheel_archive.namelist()}
    wheel_members["package/native.dylib"] = b"\xca\xfe\xba\xbefixtures"
    native_wheel = _zip(wheel_members)
    native_digest = hashlib.sha256(native_wheel).hexdigest()
    primary_receipt_name = next(name for name in primary_members
                                if name.endswith(".runtime.json"))
    primary_receipt = json.loads(primary_members[primary_receipt_name])
    primary_receipt["archives"][0]["size"] = len(native_wheel)
    primary_receipt["archives"][0]["sha256"] = native_digest
    primary_members[primary_wheel_name] = native_wheel
    primary_members[primary_receipt_name] = json.dumps(primary_receipt).encode()
    _repack_scope(case, primary_members, index=primary_index)
    _add_intel_artifacts(case)

    intel_index = 100
    with zipfile.ZipFile(io.BytesIO(case["archives"][intel_index])) as intel_artifact:
        intel_members = {name: intel_artifact.read(name) for name in intel_artifact.namelist()}
    intel_wheel_name = next(name for name in intel_members if name.endswith(".whl"))
    intel_receipt_name = next(name for name in intel_members if name.endswith(".runtime.json"))
    intel_receipt = json.loads(intel_members[intel_receipt_name])
    intel_receipt["locked_dependencies"] = [{"name": "package", "version": "7"}]
    intel_receipt["archives"][0].update(
        {"name": "package", "version": "7", "size": len(native_wheel),
         "sha256": native_digest})
    intel_requirements = b"package==7\n"
    intel_receipt["requirements_sha256"] = hashlib.sha256(intel_requirements).hexdigest()
    intel_members[intel_wheel_name] = native_wheel
    intel_members[intel_receipt_name] = json.dumps(intel_receipt).encode()
    intel_members[next(name for name in intel_members
                       if name.endswith(".runtime-requirements.txt"))] = intel_requirements
    case["archives"][intel_index] = _zip(intel_members)
    artifact_row = next(row for row in case["artifacts"] if row["id"] == intel_index)
    artifact_row["digest"] = "sha256:" + hashlib.sha256(case["archives"][intel_index]).hexdigest()

    root = tmp_path / "scope"
    selected = _verify(case, root)

    def fetch(_repository: str, artifact_id: int, target) -> None:
        target.write(case["archives"][artifact_id])

    variants = verify_macos_x86_runtime_set(
        case["artifacts"], case["attempt"], repository="owner/repo",
        source_sha=SOURCE, control_sha=CONTROL, run_id=RUN, run_attempt=ATTEMPT,
        distributions=case["distributions"], fetch=fetch, output_dir=root)
    primary_archive = next(row for row in selected
                           if row["leg"] == "universal2-apple-darwin-py3.12")["archives"][0]
    variant_archive = next(row for row in variants
                           if row["leg"] == "universal2-apple-darwin-py3.12")["archives"][0]
    assert (primary_archive["name"], primary_archive["version"], primary_archive["sha256"]) == (
        variant_archive["name"], variant_archive["version"], variant_archive["sha256"])
    monkeypatch.setattr(prescreen_module, "_reader", lambda: {"path": "/pinned/llvm-readobj"})
    monkeypatch.setattr(prescreen_module, "_links", lambda *args, **kwargs: [
        {"arch": "aarch64", "needed": []}])

    with pytest.raises(gate.GateError, match="requires x86_64 architecture"):
        prescreen({"verified_scope_evidence": selected,
                   "verified_runtime_variants": variants}, root)


def test_intel_native_inspection_follows_archive_structure_validation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Variant native inspection must see only structurally validated wheel bytes."""
    root, rows = _prescreen_case(tmp_path)
    validated_digests: set[str] = set()
    archive_license_evidence = gate.archive_license_evidence

    def validate_archive(archive_bytes: bytes, ecosystem_name: str) -> dict:
        evidence = archive_license_evidence(archive_bytes, ecosystem_name)
        validated_digests.add(hashlib.sha256(archive_bytes).hexdigest())
        return evidence

    def inspect_native(
        archive_bytes: bytes,
        _target_name: str,
        *,
        required_architecture: str | None = None,
    ) -> list[dict]:
        if required_architecture is not None:
            assert hashlib.sha256(archive_bytes).hexdigest() in validated_digests
        return []

    monkeypatch.setattr(gate, "archive_license_evidence", validate_archive)
    monkeypatch.setattr(prescreen_module, "_native_wheel_libraries", inspect_native)
    monkeypatch.setattr(prescreen_module, "_build_packages", lambda _item, _folder: [])
    monkeypatch.setattr(prescreen_module, "_maturin_tool", lambda item, _folder: {
        "key": "github-release/maturin@1.15.0/sha256/" + "a" * 64,
        "legs": [item["leg"]], "build_envs": {item["leg"]: "fixture"},
    })

    prescreen(_scope_with_variants(rows, root), root)


def _rewrite_build_snapshot(
    scope_row: dict,
    scope_root: Path,
    archive_members: dict[str, bytes],
    build_receipt: dict,
) -> None:
    build_leg = scope_row["leg"]
    artifact_folder = scope_root / scope_row["artifact_name"]
    snapshot_path = artifact_folder / f"{build_leg}.build-python.zip"
    snapshot_path.write_bytes(_zip(archive_members))
    snapshot_digest = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    build_receipt["python_snapshot_sha256"] = snapshot_digest
    (artifact_folder / f"{build_leg}.build-first.json").write_text(json.dumps(build_receipt))
    scope_row["members"][snapshot_path.name] = snapshot_digest


def test_build_snapshot_native_file_requires_reviewed_links(tmp_path: Path, monkeypatch) -> None:
    root, rows = _prescreen_case(tmp_path)
    row = rows[0]
    folder = root / row["artifact_name"]
    leg = row["leg"]
    snapshot = folder / f"{leg}.build-python.zip"
    with zipfile.ZipFile(snapshot) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    binary = b"\x7fELFfixture"
    members["pip/native.so"] = binary
    receipt = json.loads((folder / f"{leg}.build-first.json").read_text())
    receipt["python_packages"][0]["files"].append(
        {"path": "native.so", "size": len(binary), "sha256": hashlib.sha256(binary).hexdigest()}
    )
    _rewrite_build_snapshot(row, root, members, receipt)
    monkeypatch.setattr(prescreen_module, "_reader", lambda: {"path": "/pinned/llvm-readobj"})
    monkeypatch.setattr(prescreen_module, "_links", lambda *args, **kwargs: [
        {"arch": "x86_64", "needed": ["libmystery.so.1"]}])
    with pytest.raises(gate.GateError, match="NATIVE_LINK_UNKNOWN"):
        _build_packages(row, folder)


def test_build_snapshot_refuses_unlisted_native_file(tmp_path: Path, monkeypatch) -> None:
    """A native snapshot member omitted from its package receipt is rejected."""
    root, rows = _prescreen_case(tmp_path)
    row = rows[0]
    folder = root / row["artifact_name"]
    leg = row["leg"]
    snapshot = folder / f"{leg}.build-python.zip"
    with zipfile.ZipFile(snapshot) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    members["pip/unlisted.so"] = b"\x7fELFfixture"
    receipt = json.loads((folder / f"{leg}.build-first.json").read_text())
    _rewrite_build_snapshot(row, root, members, receipt)
    monkeypatch.setattr(prescreen_module, "_reader", lambda: {"path": "/pinned/llvm-readobj"})
    monkeypatch.setattr(prescreen_module, "_links", lambda *args, **kwargs: [{"arch": "x86_64", "needed": []}])

    with pytest.raises(gate.GateError, match="unlisted native build file"):
        _build_packages(row, folder)


def test_build_snapshot_refuses_unknown_universal_interpreter_architecture(
    tmp_path: Path,
) -> None:
    """A universal build receipt must bind one recognized interpreter architecture."""
    scope_root, scope_rows = _prescreen_case(tmp_path)
    scope_row = next(row for row in scope_rows if row["leg"].startswith("universal2-apple-darwin-"))
    artifact_folder = scope_root / scope_row["artifact_name"]
    receipt_path = artifact_folder / f"{scope_row['leg']}.build-first.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["build_env"] = "/opt/python/UNKNOWN"
    receipt_path.write_text(json.dumps(receipt))

    with pytest.raises(gate.GateError, match="build interpreter architecture is missing"):
        _build_packages(scope_row, artifact_folder)


def test_runtime_archive_refuses_unknown_native_link(tmp_path: Path, monkeypatch) -> None:
    """A runtime archive with an unlicensed dynamic target cannot pass prescreen."""
    root, rows = _prescreen_case(tmp_path)
    original = gate.evaluate_native_links

    def evaluate(evidence, subject, **kwargs):
        if subject.startswith("pypi/package@"):
            return [gate.Failure(gate.NATIVE_LINK_UNKNOWN, subject, "unknown link")], []
        return original(evidence, subject, **kwargs)

    monkeypatch.setattr(gate, "evaluate_native_links", evaluate)
    with pytest.raises(gate.GateError, match="NATIVE_LINK_UNKNOWN"):
        prescreen(_scope_with_variants(rows, root), root)


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
    scope = _scope_with_variants(selected, scope_root)
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
    scope = _scope_with_variants(selected, root)
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


@pytest.mark.parametrize(("field", "value"), [
    ("source_repository", "attacker/maturin"),
    ("tag", "v1.14.0"),
    ("tag_commit", "0" * 39),
    ("source_archive_sha256", "0" * 63),
])
def test_maturin_prescreen_refuses_invalid_source_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: str,
) -> None:
    case = _case()
    root = tmp_path / "scope"
    selected = _verify(case, root)
    evidence = json.loads(Path(prescreen_module.__file__).with_name(
        "release_maturin_tool_evidence.json"
    ).read_text())
    evidence[field] = value
    evidence_path = tmp_path / "release_maturin_tool_evidence.json"
    evidence_path.write_text(json.dumps(evidence))
    monkeypatch.setattr(
        prescreen_module, "__file__", str(tmp_path / Path(prescreen_module.__file__).name)
    )
    with pytest.raises(gate.GateError, match="provenance is malformed"):
        prescreen(_scope_with_variants(selected, root), root)


@pytest.mark.parametrize("metadata,reason", [
    (b"Name: pip\nVersion: 25.2\nLicense-Expression: GPL-3.0-only\nLicense-File: LICENSE\n", "LICENSE_DENIED"),
    (b"Name: foreign\nVersion: 25.2\nLicense-Expression: MIT\nLicense-File: LICENSE\n", "metadata differs"),
    (b"Name: pip\nName: foreign\nVersion: 25.2\nLicense-Expression: MIT\nLicense-File: LICENSE\n", "metadata differs"),
    (b"Name: pip\nVersion: 25.2\nLicense-Expression: MIT\nLicense-File: ../escape\n", "ARCHIVE_PATH_ESCAPE"),
    (b"Name: pip\nVersion: 25.2\nLicense-Expression: MIT\nLicense-File: ABSENT\n", "declared license is missing"),
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


@pytest.mark.parametrize(("mutation_name", "expected_message"), [
    ("receipt", "build receipt is malformed"),
    ("snapshot", "build snapshot changed"),
    ("packages", "build packages are missing"),
    ("metadata", "metadata is ambiguous"),
])
def test_build_package_prescreen_refuses_incomplete_build_evidence(
    tmp_path: Path, mutation_name: str, expected_message: str,
) -> None:
    scope_root, scope_rows = _prescreen_case(tmp_path)
    scope_row = scope_rows[0]
    build_leg = scope_row["leg"]
    artifact_folder = scope_root / scope_row["artifact_name"]
    receipt_path = artifact_folder / f"{build_leg}.build-first.json"
    build_receipt = json.loads(receipt_path.read_text())
    if mutation_name == "receipt":
        receipt_path.write_text("[]")
    elif mutation_name == "snapshot":
        scope_row["members"][f"{build_leg}.build-python.zip"] = "0" * 64
    elif mutation_name == "packages":
        build_receipt["python_packages"] = []
        receipt_path.write_text(json.dumps(build_receipt))
    else:
        build_receipt["python_packages"][0]["files"] = [
            file_row for file_row in build_receipt["python_packages"][0]["files"]
            if not file_row["path"].endswith(".dist-info/METADATA")
        ]
        receipt_path.write_text(json.dumps(build_receipt))
    with pytest.raises(gate.GateError, match=expected_message):
        _build_packages(scope_row, artifact_folder)


@pytest.mark.parametrize("mutation_name", ["missing", "oversized"])
def test_build_package_prescreen_refuses_missing_or_oversized_text(
    tmp_path: Path, mutation_name: str,
) -> None:
    scope_root, scope_rows = _prescreen_case(tmp_path)
    scope_row = scope_rows[0]
    build_leg = scope_row["leg"]
    artifact_folder = scope_root / scope_row["artifact_name"]
    snapshot_path = artifact_folder / f"{build_leg}.build-python.zip"
    receipt_path = artifact_folder / f"{build_leg}.build-first.json"
    build_receipt = json.loads(receipt_path.read_text())
    with zipfile.ZipFile(snapshot_path) as snapshot_archive:
        archive_members = {
            member_name: snapshot_archive.read(member_name)
            for member_name in snapshot_archive.namelist()
        }
    license_name = "pip/pip-25.2.dist-info/licenses/LICENSE"
    if mutation_name == "missing":
        del archive_members[license_name]
    else:
        archive_members[license_name] = b"x" * (4 * 1024 * 1024 + 1)
    _rewrite_build_snapshot(scope_row, scope_root, archive_members, build_receipt)
    with pytest.raises(gate.GateError, match="text file is missing or oversized"):
        _build_packages(scope_row, artifact_folder)


def test_build_package_prescreen_refuses_unreadable_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_root, scope_rows = _prescreen_case(tmp_path)

    class UnreadableMetadataParser:
        def parsebytes(self, metadata_bytes: bytes) -> None:
            assert metadata_bytes
            raise ValueError("unreadable")

    monkeypatch.setattr(prescreen_module.email.parser, "BytesParser", UnreadableMetadataParser)
    scope_row = scope_rows[0]
    with pytest.raises(gate.GateError, match="metadata is unreadable"):
        _build_packages(scope_row, scope_root / scope_row["artifact_name"])


@pytest.mark.parametrize("mutation_name", ["undecodable", "oversized-set"])
def test_build_package_prescreen_refuses_invalid_license_text_sets(
    tmp_path: Path, mutation_name: str,
) -> None:
    scope_root, scope_rows = _prescreen_case(tmp_path)
    scope_row = scope_rows[0]
    build_leg = scope_row["leg"]
    artifact_folder = scope_root / scope_row["artifact_name"]
    snapshot_path = artifact_folder / f"{build_leg}.build-python.zip"
    receipt_path = artifact_folder / f"{build_leg}.build-first.json"
    build_receipt = json.loads(receipt_path.read_text())
    package_files = build_receipt["python_packages"][0]["files"]
    with zipfile.ZipFile(snapshot_path) as snapshot_archive:
        archive_members = {
            member_name: snapshot_archive.read(member_name)
            for member_name in snapshot_archive.namelist()
        }
    if mutation_name == "undecodable":
        license_paths = ["pip-25.2.dist-info/licenses/LICENSE"]
        license_payloads = [b"\xff"]
    else:
        license_paths = [f"pip-25.2.dist-info/licenses/LICENSE-{index}" for index in range(5)]
        license_payloads = [b"x" * (4 * 1024 * 1024) for _ in license_paths]
        metadata_path = "pip/pip-25.2.dist-info/METADATA"
        metadata_payload = (
            b"Name: pip\nVersion: 25.2\nLicense-Expression: MIT\n"
            + b"".join(f"License-File: LICENSE-{index}\n".encode() for index in range(5))
        )
        archive_members[metadata_path] = metadata_payload
        metadata_row = next(file_row for file_row in package_files
                            if file_row["path"].endswith(".dist-info/METADATA"))
        metadata_row.update(size=len(metadata_payload),
                            sha256=hashlib.sha256(metadata_payload).hexdigest())
    package_files[:] = [file_row for file_row in package_files
                        if "licenses/LICENSE" not in file_row["path"]]
    for license_path, license_payload in zip(license_paths, license_payloads, strict=True):
        archive_members[f"pip/{license_path}"] = license_payload
        package_files.append({"path": license_path, "size": len(license_payload),
                              "sha256": hashlib.sha256(license_payload).hexdigest()})
    package_files.sort(key=lambda file_row: file_row["path"])
    _rewrite_build_snapshot(scope_row, scope_root, archive_members, build_receipt)
    expected_message = "undecodable" if mutation_name == "undecodable" else "text set is oversized"
    with pytest.raises(gate.GateError, match=expected_message):
        _build_packages(scope_row, artifact_folder)


def test_maturin_prescreen_refuses_missing_environment_and_denied_license(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_root, scope_rows = _prescreen_case(tmp_path)
    scope_row = scope_rows[0]
    build_leg = scope_row["leg"]
    artifact_folder = scope_root / scope_row["artifact_name"]
    receipt_path = artifact_folder / f"{build_leg}.build-first.json"
    original_receipt = receipt_path.read_bytes()
    build_receipt = json.loads(original_receipt)
    del build_receipt["build_env"]
    changed_receipt = json.dumps(build_receipt).encode()
    receipt_path.write_bytes(changed_receipt)
    scope_row["members"][receipt_path.name] = hashlib.sha256(changed_receipt).hexdigest()
    with pytest.raises(gate.GateError, match="build environment is missing"):
        _maturin_tool(scope_row, artifact_folder)

    receipt_path.write_bytes(original_receipt)
    scope_row["members"][receipt_path.name] = hashlib.sha256(original_receipt).hexdigest()
    evidence = json.loads(Path(prescreen_module.__file__).with_name(
        "release_maturin_tool_evidence.json"
    ).read_text())
    evidence.update(license_expression="GPL-3.0-only", license_choice="GPL-3.0-only")
    evidence_path = tmp_path / "release_maturin_tool_evidence.json"
    evidence_path.write_text(json.dumps(evidence))
    monkeypatch.setattr(
        prescreen_module, "__file__", str(tmp_path / Path(prescreen_module.__file__).name)
    )
    with pytest.raises(gate.GateError, match="maturin licence"):
        _maturin_tool(scope_row, artifact_folder)


@pytest.mark.parametrize(("native_links", "message"), [
    ([], "native links are missing"),
    ([{"arch": "x86_64", "needed": ["foreign-runtime.so"]}], "maturin native links"),
])
def test_maturin_prescreen_refuses_missing_or_unreviewed_native_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    native_links: list[dict[str, object]],
    message: str,
) -> None:
    scope_root, scope_rows = _prescreen_case(tmp_path)
    scope_row = scope_rows[0]
    artifact_folder = scope_root / scope_row["artifact_name"]
    evidence = json.loads(Path(prescreen_module.__file__).with_name(
        "release_maturin_tool_evidence.json"
    ).read_text())
    for asset in evidence["assets"].values():
        asset["native_links"] = native_links
    evidence_path = tmp_path / "release_maturin_tool_evidence.json"
    evidence_path.write_text(json.dumps(evidence))
    monkeypatch.setattr(
        prescreen_module, "__file__", str(tmp_path / Path(prescreen_module.__file__).name)
    )
    with pytest.raises(gate.GateError, match=message):
        _maturin_tool(scope_row, artifact_folder)


def test_prescreen_refuses_malformed_scope_and_runtime_rows(tmp_path: Path) -> None:
    with pytest.raises(gate.GateError, match="verified scope evidence is incomplete"):
        prescreen({}, tmp_path)

    for mutation_name in ("scope-row", "runtime-set", "archive-row"):
        scope_root, scope_rows = _prescreen_case(tmp_path / mutation_name)
        if mutation_name == "scope-row":
            scope_rows[0]["leg"] = ".."
            expected_message = "scope evidence row is malformed"
        elif mutation_name == "runtime-set":
            scope_rows[0]["archives"] = []
            expected_message = "runtime archive set is incomplete"
        else:
            scope_rows[0]["archives"][0]["size"] = 0
            expected_message = "archive identity is malformed"
        with pytest.raises(gate.GateError, match=expected_message):
            prescreen(_scope_with_variants(scope_rows, scope_root), scope_root)


def test_prescreen_coalesces_duplicate_archive_identity(tmp_path: Path) -> None:
    scope_root, scope_rows = _prescreen_case(tmp_path)
    first_row, second_row = scope_rows[:2]
    first_archive = first_row["archives"][0]
    second_folder = scope_root / second_row["artifact_name"]
    first_path = scope_root / first_row["artifact_name"] / first_archive["file"]
    (second_folder / first_archive["file"]).write_bytes(first_path.read_bytes())
    second_row["archives"] = [dict(first_archive)]
    result = prescreen(_scope_with_variants(scope_rows, scope_root), scope_root)
    duplicate_row = next(item for item in result["archives"]
                         if item["source_sha256"] == first_archive["sha256"])
    assert duplicate_row["legs"] == [first_row["leg"], second_row["leg"]]


def test_prescreen_refuses_rebound_license_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_root, scope_rows = _prescreen_case(tmp_path)
    archive_license_evidence = gate.archive_license_evidence

    def changed_license_evidence(archive_bytes: bytes, ecosystem_name: str) -> dict:
        evidence = archive_license_evidence(archive_bytes, ecosystem_name)
        return evidence | {"source_sha256": "0" * 64}

    monkeypatch.setattr(gate, "archive_license_evidence", changed_license_evidence)
    with pytest.raises(gate.GateError, match="licence evidence changed"):
        prescreen(_scope_with_variants(scope_rows, scope_root), scope_root)


def test_prescreen_refuses_complete_rows_without_sdist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_root, scope_rows = _prescreen_case(tmp_path)
    sdist_row = scope_rows[-1]
    first_archive = dict(scope_rows[0]["archives"][0])
    first_path = scope_root / scope_rows[0]["artifact_name"] / first_archive["file"]
    sdist_row["leg"] = "extra-py3.12"
    sdist_row["artifact_name"] = "repro-digest-extra-py3.12"
    sdist_row["archives"] = [first_archive]
    extra_folder = scope_root / sdist_row["artifact_name"]
    extra_folder.mkdir()
    (extra_folder / first_archive["file"]).write_bytes(first_path.read_bytes())
    monkeypatch.setattr(prescreen_module, "_build_packages", lambda item, folder: [])
    monkeypatch.setattr(prescreen_module, "_maturin_tool", lambda item, folder: {
        "key": "github-release/maturin@1.15.0/sha256/" + "a" * 64,
        "legs": [item["leg"]], "build_envs": {item["leg"]: "fixture"},
    })
    with pytest.raises(gate.GateError, match="runtime archive coverage is incomplete"):
        prescreen(_scope_with_variants(scope_rows, scope_root), scope_root)


@pytest.mark.parametrize("mutation_name", ["oversized", "digest", "architecture"])
def test_prescreen_refuses_untrusted_runtime_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation_name: str,
) -> None:
    """Runtime receipts are bounded, hash-bound, and structurally validated."""
    scope_root, scope_rows = _prescreen_case(tmp_path)
    scope = _scope_with_variants(scope_rows, scope_root)
    row = next(item for item in scope_rows if item["leg"] != "sdist")
    runtime_name = f"{row['leg']}.runtime.json"
    runtime_path = scope_root / row["artifact_name"] / runtime_name
    if mutation_name == "oversized":
        runtime_path.write_bytes(b"x" * (1024 * 1024 + 1))
    elif mutation_name == "digest":
        row["members"][runtime_name] = "0" * 64
    else:
        def invalid_architecture(*args, **kwargs):
            del args, kwargs
            raise DistributionSetError("untrusted architecture")

        monkeypatch.setattr(prescreen_module, "_runtime_target_architecture", invalid_architecture)

    with pytest.raises(gate.GateError, match={
        "oversized": "runtime receipt is oversized",
        "digest": "runtime receipt changed after transport",
        "architecture": "untrusted architecture",
    }[mutation_name]):
        prescreen(scope, scope_root)


def test_prescreen_cli_writes_once_and_refuses_existing_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope_root, scope_rows = _prescreen_case(tmp_path)
    scope_path = tmp_path / "scope.json"
    output_path = tmp_path / "licenses.json"
    scope_path.write_text(json.dumps(_scope_with_variants(scope_rows, scope_root)))
    monkeypatch.setattr("sys.argv", ["prescreen_release_runtime_archives.py",
                                    "--verified-scope", str(scope_path),
                                    "--scope-root", str(scope_root),
                                    "--output", str(output_path)])
    runpy.run_path(prescreen_module.__file__, run_name="__main__")
    assert json.loads(output_path.read_text())["schema"] == "cwl.release-runtime-archive-licenses/3"
    with pytest.raises(gate.GateError, match="output already exists"):
        prescreen_module.main()


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


def test_build_snapshot_refuses_divergent_or_malformed_inventories(tmp_path: Path) -> None:
    mutations = (
        ("divergent", "repeated build package inventories differ"),
        ("package", "build package inventory is malformed"),
        ("file-shape", "build file inventory is malformed"),
        ("file-path", "build file inventory is malformed"),
        ("duplicate-file", "duplicate build snapshot file"),
    )
    for mutation, message in mutations:
        _case_value, folder, leg, members = _scope_folder(tmp_path / mutation)
        first_path = folder / f"{leg}.build-first.json"
        second_path = folder / f"{leg}.build-second.json"
        first = json.loads(first_path.read_text())
        second = json.loads(second_path.read_text())
        if mutation == "divergent":
            second["python_packages"][0]["version"] = "different"
        elif mutation == "package":
            first["python_packages"][0]["name"] = "BAD_NAME"
            second = json.loads(json.dumps(first))
            second["pass"] = "second"
        elif mutation == "file-shape":
            first["python_packages"][0]["files"][0] = {"path": "a.py"}
            second = json.loads(json.dumps(first))
            second["pass"] = "second"
        elif mutation == "file-path":
            first["python_packages"][0]["files"][0]["path"] = "../escape"
            second = json.loads(json.dumps(first))
            second["pass"] = "second"
        else:
            first["python_packages"][0]["files"].append(
                dict(first["python_packages"][0]["files"][0])
            )
            second = json.loads(json.dumps(first))
            second["pass"] = "second"
        first_path.write_text(json.dumps(first))
        second_path.write_text(json.dumps(second))
        with pytest.raises(DistributionSetError, match=message):
            scope_module._build_python_snapshot(folder, leg, SOURCE, members)


def test_build_snapshot_refuses_size_members_mode_and_hash_mismatch(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _case_value, folder, leg, members = _scope_folder(tmp_path / "oversized")
    monkeypatch.setattr(scope_module, "MAX_ARCHIVE_BYTES", 0)
    with pytest.raises(DistributionSetError, match="snapshot exceeds size limit"):
        scope_module._build_python_snapshot(folder, leg, SOURCE, members)
    monkeypatch.undo()

    _case_value, folder, leg, members = _scope_folder(tmp_path / "members")
    snapshot = folder / f"{leg}.build-python.zip"
    snapshot.write_bytes(_zip({"unexpected": b"x"}))
    members[snapshot.name] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    for build_pass in ("first", "second"):
        receipt_path = folder / f"{leg}.build-{build_pass}.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["python_snapshot_sha256"] = members[snapshot.name]
        receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(DistributionSetError, match="members differ from receipt"):
        scope_module._build_python_snapshot(folder, leg, SOURCE, members)

    for mutation, message in (("size", "member is unsafe"), ("hash", "file differs from receipt")):
        _case_value, folder, leg, members = _scope_folder(tmp_path / mutation)
        for build_pass in ("first", "second"):
            receipt_path = folder / f"{leg}.build-{build_pass}.json"
            receipt = json.loads(receipt_path.read_text())
            file_row = receipt["python_packages"][0]["files"][0]
            if mutation == "size":
                file_row["size"] += 1
            else:
                file_row["sha256"] = "0" * 64
            receipt_path.write_text(json.dumps(receipt))
        with pytest.raises(DistributionSetError, match=message):
            scope_module._build_python_snapshot(folder, leg, SOURCE, members)


def test_wheel_identity_refuses_missing_unreadable_ambiguous_and_invalid_metadata(
        tmp_path: Path) -> None:
    cases = (
        ({"package/a.py": b"x"}, "missing or oversized"),
        ({"package-1.dist-info/METADATA": b"\xff"}, "not UTF-8"),
        ({"package-1.dist-info/METADATA": b"Name: one\nName: two\nVersion: 1\n"}, "ambiguous"),
        ({"package-1.dist-info/METADATA": b"Name: !!!\nVersion: 1\n"}, "no project identity"),
    )
    for index, (members, message) in enumerate(cases):
        wheel = tmp_path / f"case-{index}.whl"
        wheel.write_bytes(_zip(members))
        with pytest.raises(DistributionSetError, match=message):
            scope_module._wheel_identity(wheel)


def test_consumer_wheel_refuses_duplicate_unsafe_large_and_multiple_native_members(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    duplicate = tmp_path / "duplicate.whl"
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("same", b"one")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("same", b"two")
    duplicate.write_bytes(stream.getvalue())
    with pytest.raises(DistributionSetError, match="duplicate members"):
        scope_module._consumer_wheel_evidence(duplicate)

    unsafe = tmp_path / "unsafe.whl"
    unsafe.write_bytes(_zip({"../escape": b"x"}))
    with pytest.raises(DistributionSetError, match="unsafe member"):
        scope_module._consumer_wheel_evidence(unsafe)

    large = tmp_path / "large.whl"
    large.write_bytes(_zip({"plain": b"x"}))
    monkeypatch.setattr(scope_module, "MAX_ARCHIVE_BYTES", 0)
    with pytest.raises(DistributionSetError, match="exceed size limit"):
        scope_module._consumer_wheel_evidence(large)
    monkeypatch.undo()

    multiple = tmp_path / "multiple.whl"
    multiple.write_bytes(_zip({
        "fast_mlsirm-1.dist-info/METADATA": b"Name: fast-mlsirm\nVersion: 1\n",
        "fast_mlsirm-1.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
        "fast_mlsirm/_core.one.so": b"\x7fELFone",
        "fast_mlsirm/_core.two.so": b"\x7fELFtwo",
    }))
    with pytest.raises(DistributionSetError, match="multiple native extensions"):
        scope_module._consumer_wheel_evidence(multiple)

    valid_with_plain_file = tmp_path / "valid-with-plain.whl"
    valid_with_plain_file.write_bytes(_zip({
        "fast_mlsirm-1.dist-info/METADATA": b"Name: fast-mlsirm\nVersion: 1\n",
        "fast_mlsirm-1.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
        "fast_mlsirm/_core.one.so": b"\x7fELFone",
        "fast_mlsirm/readme.txt": b"plain text",
    }))
    metadata, extension = scope_module._consumer_wheel_evidence(valid_with_plain_file)
    assert len(metadata) == 2
    assert extension["member"] == "fast_mlsirm/_core.one.so"


def test_runtime_archive_receipt_refuses_incomplete_extra_and_unlocked_sets(tmp_path: Path) -> None:
    for mutation, message in (
        ("receipt", "runtime receipt differs"),
        ("incomplete", "archive set is incomplete"),
        ("extra", "archive set differs"),
        ("unlocked", "locked dependency set differs"),
    ):
        case, folder, leg, members = _scope_folder(tmp_path / mutation)
        runtime_path = folder / f"{leg}.runtime.json"
        runtime = json.loads(runtime_path.read_text())
        if mutation == "receipt":
            runtime["source_sha"] = "c" * 40
        elif mutation == "incomplete":
            runtime["archives"] = []
        elif mutation == "extra":
            members["extra.whl"] = "0" * 64
            (folder / "extra.whl").write_bytes(b"x")
        else:
            runtime["locked_dependencies"] = []
        runtime_path.write_text(json.dumps(runtime))
        with pytest.raises(DistributionSetError, match=message):
            scope_module._runtime_archives(
                folder, leg, SOURCE, case["distributions"][0], members
            )


def test_scope_verifier_refuses_invalid_envelopes_and_rows(tmp_path: Path) -> None:
    def invoke(case: dict, output: Path, **overrides):
        arguments = {
            "repository": "owner/repo", "source_sha": SOURCE, "control_sha": CONTROL,
            "run_id": RUN, "run_attempt": ATTEMPT, "record_artifact_id": 14,
            "record_artifact_digest": case["record_digest"],
            "distributions": case["distributions"], "output_dir": output,
        } | overrides
        return verify_scope_evidence_set(
            case["artifacts"], case["attempt"],
            fetch=lambda _repository, artifact_id, target: target.write(case["archives"][artifact_id]),
            **arguments,
        )

    for index, overrides in enumerate((
        {"repository": "owner"}, {"source_sha": "bad"}, {"control_sha": "bad"},
        {"run_id": True}, {"run_attempt": 0}, {"record_artifact_id": True},
        {"record_artifact_digest": "bad"},
    )):
        with pytest.raises(DistributionSetError, match="invalid scope evidence identity"):
            invoke(_case(), tmp_path / f"identity-{index}", **overrides)

    case = _case()
    case["attempt"]["head_sha"] = "c" * 40
    with pytest.raises(DistributionSetError, match="workflow attempt differs"):
        invoke(case, tmp_path / "attempt")

    case = _case()
    case["artifacts"].insert(0, dict(case["artifacts"][0]))
    with pytest.raises(DistributionSetError, match="duplicate or invalid"):
        invoke(case, tmp_path / "artifact")

    case = _case()
    case["distributions"].pop()
    with pytest.raises(DistributionSetError, match="thirteen verified distribution legs"):
        invoke(case, tmp_path / "distributions")

    case = _case()
    case["manifest"]["unexpected"] = True
    _repack_record(case)
    with pytest.raises(DistributionSetError, match="unknown shape"):
        invoke(case, tmp_path / "manifest")

    case = _case()
    case["manifest"]["evidence"].pop()
    _repack_record(case)
    with pytest.raises(DistributionSetError, match="legs are incomplete"):
        invoke(case, tmp_path / "evidence")

    case = _case()
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(DistributionSetError, match="output already exists"):
        invoke(case, existing)

    case = _case()
    case["manifest"]["evidence"][0] = {"leg": case["manifest"]["evidence"][0]["leg"]}
    _repack_record(case)
    with pytest.raises(DistributionSetError, match="invalid scope evidence row"):
        invoke(case, tmp_path / "row")

    case = _case()
    case["manifest"]["evidence"][0]["artifact_id"] = 14
    _repack_record(case)
    with pytest.raises(DistributionSetError, match="artifact identity differs"):
        invoke(case, tmp_path / "row-identity")


def test_scope_archive_refuses_unsafe_and_oversized_members(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for mutation, message in (("unsafe", "unsafe scope artifact member"),
                              ("oversized", "scope artifact exceeds size limit")):
        case = _case()
        with zipfile.ZipFile(io.BytesIO(case["archives"][1])) as archive:
            members = {member: archive.read(member) for member in archive.namelist()}
        if mutation == "unsafe":
            output = io.BytesIO()
            unsafe_name = next(iter(members))
            with zipfile.ZipFile(output, "w") as archive:
                for name, payload in members.items():
                    if name == unsafe_name:
                        info = zipfile.ZipInfo(name)
                        info.external_attr = 0o120777 << 16
                        archive.writestr(info, payload)
                    else:
                        archive.writestr(name, payload)
            case["archives"][1] = output.getvalue()
            digest = "sha256:" + hashlib.sha256(case["archives"][1]).hexdigest()
            case["artifacts"][0]["digest"] = digest
            case["manifest"]["evidence"][0]["artifact_digest"] = digest
            _repack_record(case)
        else:
            largest = max(len(payload) for payload in members.values())
            assert sum(len(payload) for payload in members.values()) > largest
            monkeypatch.setattr(scope_module, "MAX_ARCHIVE_BYTES", largest)
            _repack_scope(case, members)
        with pytest.raises(DistributionSetError, match=message):
            _verify(case, tmp_path / mutation)
        monkeypatch.undo()


def test_scope_module_entrypoint_verifies_and_emits_selected_rows(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    case = _case()
    _add_intel_artifacts(case)
    metadata = tmp_path / "metadata.jsonl"
    metadata.write_text("".join(json.dumps(item) + "\n" for item in case["artifacts"]))
    attempt = tmp_path / "attempt.json"
    attempt.write_text(json.dumps(case["attempt"]))
    distributions = tmp_path / "distributions.json"
    distributions.write_text(json.dumps({"verified_distributions": case["distributions"]}))

    class Process:
        def __init__(self, data: bytes):
            self.stdout = io.BytesIO(data)

        @staticmethod
        def wait() -> int:
            return 0

        @staticmethod
        def poll() -> int:
            return 0

    def popen(args, stdout):
        assert stdout is subprocess.PIPE
        artifact_id = int(args[2].split("/")[-2])
        return Process(case["archives"][artifact_id])

    script = Path(scope_module.__file__)
    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(sys, "argv", [
        str(script), "--repository", "owner/repo", "--source-sha", SOURCE,
        "--control-sha", CONTROL, "--run-id", str(RUN), "--run-attempt", str(ATTEMPT),
        "--record-artifact-id", "14", "--record-artifact-digest", case["record_digest"],
        "--verified-distributions", str(distributions), "--metadata", str(metadata),
        "--attempt", str(attempt), "--output", str(tmp_path / "scope"),
    ])

    runpy.run_path(str(script), run_name="__main__")

    output = json.loads(capsys.readouterr().out)
    assert len(output["verified_scope_evidence"]) == 13
    assert len(output["verified_runtime_variants"]) == 3


def test_scope_main_refuses_malformed_distribution_report(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    metadata = tmp_path / "metadata.jsonl"
    metadata.write_text("")
    attempt = tmp_path / "attempt.json"
    attempt.write_text("{}")
    distributions = tmp_path / "distributions.json"
    distributions.write_text("[]")
    monkeypatch.setattr(sys, "argv", [
        "verify_release_scope_evidence_set.py", "--repository", "owner/repo",
        "--source-sha", SOURCE, "--control-sha", CONTROL,
        "--run-id", str(RUN), "--run-attempt", str(ATTEMPT),
        "--record-artifact-id", "14", "--record-artifact-digest", "sha256:" + "0" * 64,
        "--verified-distributions", str(distributions), "--metadata", str(metadata),
        "--attempt", str(attempt), "--output", str(tmp_path / "scope"),
    ])

    with pytest.raises(DistributionSetError, match="distribution report is malformed"):
        scope_module.main()


@pytest.mark.parametrize("index,wrong_arch", [(1, "aarch64"), (4, "x86_64"), (7, "x86_64"), (10, "aarch64")])
def test_primary_native_archives_must_match_runtime_before_credentials(tmp_path, monkeypatch, index, wrong_arch):
    case = _case()
    with zipfile.ZipFile(io.BytesIO(case["archives"][index])) as artifact:
        members = {name: artifact.read(name) for name in artifact.namelist()}
    wheel_name = f"package-{index}.whl"
    with zipfile.ZipFile(io.BytesIO(members[wheel_name])) as wheel:
        files = {name: wheel.read(name) for name in wheel.namelist()}
    raw = _zip({**files, "package/native.so": b"\x7fELFsynthetic"})
    receipt_name = next(name for name in members if name.endswith(".runtime.json"))
    receipt = json.loads(members[receipt_name])
    receipt["archives"][0].update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    members[receipt_name] = json.dumps(receipt).encode()
    members[wheel_name] = raw
    _repack_scope(case, members, index)
    root = tmp_path / "scope"
    selected = _verify(case, root)
    monkeypatch.setattr(prescreen_module, "_reader", lambda: {"path": "/pinned/llvm-readobj"})
    monkeypatch.setattr(prescreen_module, "_links", lambda *args, **kwargs: [{"arch": wrong_arch, "needed": []}])
    with pytest.raises(gate.GateError, match="requires .* architecture"):
        prescreen(_scope_with_variants(selected, root), root)


def test_primary_interpreter_cannot_hide_missing_arm_coverage(tmp_path):
    case = _case()
    with zipfile.ZipFile(io.BytesIO(case["archives"][7])) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    name = next(name for name in members if name.endswith(".runtime.json"))
    runtime = json.loads(members[name])
    runtime["machine"] = "x86_64"
    members[name] = json.dumps(runtime).encode()
    consumer_name = next(name for name in members if name.endswith(".consumer.json"))
    consumer = json.loads(members[consumer_name])
    consumer["installation"]["machine"] = "x86_64"
    members[consumer_name] = json.dumps(consumer).encode()
    _repack_scope(case, members, 7)
    with pytest.raises(DistributionSetError, match="required target architecture"):
        _verify(case, tmp_path / "scope")


@pytest.mark.parametrize("index,correct_arch,wrong_arch", [(4, "aarch64", "x86_64"), (7, "aarch64", "x86_64")])
def test_build_native_packages_require_the_build_interpreter_architecture(tmp_path, monkeypatch, index, correct_arch, wrong_arch):
    root, rows = _prescreen_case(tmp_path)
    row = rows[index - 1]
    folder = root / row["artifact_name"]
    snapshot_name = f"{row['leg']}.build-python.zip"
    with zipfile.ZipFile(folder / snapshot_name) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    binary = b"\x7fELFsynthetic"
    receipt = json.loads((folder / f"{row['leg']}.build-first.json").read_text())
    receipt["python_packages"][0]["files"].append(
        {"path": "pip/native.so", "size": len(binary), "sha256": hashlib.sha256(binary).hexdigest()})
    receipt["python_packages"][0]["files"].sort(key=lambda file: file["path"])
    _rewrite_build_snapshot(row, root, {**files, "pip/pip/native.so": binary}, receipt)
    for build_pass in ("first", "second"):
        name = f"{row['leg']}.build-{build_pass}.json"
        (folder / name).write_text(json.dumps(receipt | {"pass": build_pass}))
        row["members"][name] = hashlib.sha256((folder / name).read_bytes()).hexdigest()
    monkeypatch.setattr(prescreen_module, "_reader", lambda: {"path": "/pinned/llvm-readobj"})
    monkeypatch.setattr(prescreen_module, "_links", lambda *args, **kwargs: [{"arch": correct_arch, "needed": []}])
    assert _build_packages(row, folder)
    monkeypatch.setattr(prescreen_module, "_links", lambda *args, **kwargs: [{"arch": wrong_arch, "needed": []}])
    with pytest.raises(gate.GateError, match="requires aarch64 architecture"):
        _build_packages(row, folder)
