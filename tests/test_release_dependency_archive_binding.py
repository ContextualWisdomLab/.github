"""No installation: real ZIP/tar bytes must bind the license decision."""
import hashlib
import io
import json
import tarfile
import zipfile

import pytest

from scripts.ci import release_dependency_gate as gate
from tests.test_release_dependency_gate import build_capture, _fixture_archive, REVIEWED_TEXTS


@pytest.mark.parametrize("ecosystem", ["pypi", "cargo"])
def test_raw_sidecar_cannot_replace_actual_license(tmp_path, ecosystem):
    raw = _fixture_archive({"LICENSE": "Academic research only. Commercial use prohibited."}, ecosystem)
    (tmp_path / "source.archive").write_bytes(raw)
    (tmp_path / "source.sha256").write_text(hashlib.sha256(raw).hexdigest())
    (tmp_path / "metadata.json").write_text(json.dumps({
        "ecosystem": ecosystem, "name": "example", "version": "1", "license_expression": "MIT"}))
    (tmp_path / "licenses").mkdir()
    (tmp_path / "licenses" / "LICENSE").write_text(REVIEWED_TEXTS["pytest-9.1.1.txt"])
    dependency, evidence = gate.build_evidence(tmp_path)
    assert evidence["license_texts"]["LICENSE"].startswith("Academic")
    failures, _, _ = gate.evaluate_dependency_license(evidence, dependency.key, None)
    assert gate.LICENSE_TEXT_UNVERIFIED in {failure.code for failure in failures}


@pytest.mark.parametrize("ecosystem,name,version", [("pypi", "greenlib", "1.0.0"), ("cargo", "greencrate", "0.1.0")])
@pytest.mark.parametrize("mutation", ["text", "archive", "missing"])
def test_gate_refuses_tampered_capture(tmp_path, ecosystem, name, version, mutation):
    root = build_capture(tmp_path)
    dependency = gate.Dependency(ecosystem, name, version)
    archive = root / "archives" / f"{dependency.slug}.archive"
    if mutation == "text":
        path = root / "evidence" / f"{dependency.slug}.json"
        evidence = json.loads(path.read_text())
        evidence["license_texts"] = {"LICENSE": REVIEWED_TEXTS["pytest-9.1.1.txt"] + "\nExtra condition"}
        path.write_text(json.dumps(evidence))
    elif mutation == "archive":
        archive.write_bytes(_fixture_archive({"LICENSE": "Commercial use prohibited"}, ecosystem))
    else:
        archive.unlink()
    report = gate.gate(root, stage=gate.LICENSE_STAGE)
    assert not report.passed
    assert (gate.CAPTURE_INCOMPLETE if mutation == "missing" else gate.SOURCE_HASH_MISMATCH) in {f.code for f in report.failures}


@pytest.mark.parametrize("ecosystem", ["pypi", "cargo"])
def test_duplicate_archive_members_are_refused(ecosystem):
    buffer = io.BytesIO()
    if ecosystem == "pypi":
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("LICENSE", "one")
            with pytest.warns(UserWarning):
                archive.writestr("LICENSE", "two")
    else:
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for text in (b"one", b"two"):
                member = tarfile.TarInfo("LICENSE")
                member.size = len(text)
                archive.addfile(member, io.BytesIO(text))
    with pytest.raises(gate.GateError) as error:
        gate.archive_license_evidence(buffer.getvalue(), ecosystem)
    assert error.value.code == gate.ARCHIVE_PATH_ESCAPE


@pytest.mark.parametrize("ecosystem", ["pypi", "cargo"])
def test_nested_license_bytes_and_raw_hash_are_preserved(ecosystem):
    text = "one\r\ntwo\n"
    path = "a/b/c/d/e/LICENCE"
    raw = _fixture_archive({path: text}, ecosystem)
    evidence = gate.archive_license_evidence(raw, ecosystem)
    assert evidence["license_texts"] == {path: text}
    assert evidence["license_member_sha256"] == {path: hashlib.sha256(text.encode()).hexdigest()}
    assert evidence["source_sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("present", [True, False])
def test_declared_custom_wheel_license_member(present):
    files = {"example.dist-info/METADATA": "License-File: legal/custom.txt\n\n"}
    if present:
        files["example.dist-info/licenses/legal/custom.txt"] = "restricted terms"
    raw = _fixture_archive(files, "pypi")
    if present:
        assert gate.archive_license_evidence(raw, "pypi")["license_texts"] == {
            "example.dist-info/licenses/legal/custom.txt": "restricted terms"}
    else:
        with pytest.raises(gate.GateError, match=gate.CAPTURE_INCOMPLETE):
            gate.archive_license_evidence(raw, "pypi")
