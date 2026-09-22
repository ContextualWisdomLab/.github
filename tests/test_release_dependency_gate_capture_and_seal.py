"""Raw-capture assembly, sealed-evidence composition, and fail-closed parsing (#2342).

These tests cover the halves of the gate that surround the policy decision: the
tested transformation from raw runner output into the capture contract, the
sealed six-member evidence directory that
``.github/workflows/exact-artifact-sbom-attestation.yml`` verifies, and every
input-validation path that must fail closed rather than degrade.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import release_dependency_gate as gate
from scripts.ci import verify_exact_artifact_sbom_handoff as handoff
from tests.test_release_dependency_gate import (
    CARGO_METADATA,
    PY_HASH,
    REPOSITORY,
    SOURCE_SHA,
    build_capture,
    _hash,
)


# ---------------------------------------------------------------------------
# Trusted binder resolution
# ---------------------------------------------------------------------------


def test_binder_resolves_next_to_this_script() -> None:
    """The binder is found beside the gate script, not via a repository root."""
    binder = gate.resolve_evidence_binder()
    assert binder.name == gate.BINDER_FILENAME
    assert binder.parent == Path(gate.__file__).resolve().parent


def test_missing_binder_fails_closed(tmp_path: Path) -> None:
    """A script directory without the trusted binder refuses to gate anything."""
    with pytest.raises(gate.GateError) as error:
        gate.resolve_evidence_binder(tmp_path)
    assert error.value.code == "STRIX_BINDER_UNAVAILABLE"


def test_symlinked_binder_fails_closed(tmp_path: Path) -> None:
    """A symlinked binder is refused even though it would resolve to real bytes."""
    (tmp_path / gate.BINDER_FILENAME).symlink_to(gate.resolve_evidence_binder())
    with pytest.raises(gate.GateError):
        gate.resolve_evidence_binder(tmp_path)


def test_gate_error_and_failure_serialize() -> None:
    """A gate error carries its stable code and a failure serializes for artifacts."""
    error = gate.GateError("SOME_CODE", "some detail")
    assert (error.code, error.detail) == ("SOME_CODE", "some detail")
    assert str(error) == "SOME_CODE: some detail"
    assert gate.Failure("C", "s", "d").to_json() == {
        "code": "C",
        "subject": "s",
        "detail": "d",
    }


# ---------------------------------------------------------------------------
# Bounded capture loading
# ---------------------------------------------------------------------------


def test_missing_capture_member_fails_closed(tmp_path: Path) -> None:
    """An absent capture member is a refusal, not an empty default."""
    with pytest.raises(gate.GateError) as error:
        gate.load_json(tmp_path / "absent.json")
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def test_symlinked_capture_member_fails_closed(tmp_path: Path) -> None:
    """A symlinked capture member is refused before it is read."""
    (tmp_path / "real.json").write_text("{}", encoding="utf-8")
    (tmp_path / "link.json").symlink_to(tmp_path / "real.json")
    with pytest.raises(gate.GateError):
        gate.load_json(tmp_path / "link.json")


def test_oversized_capture_member_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A capture member larger than the bound is refused rather than parsed."""
    path = tmp_path / "big.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(gate, "_MAX_JSON_BYTES", 1)
    with pytest.raises(gate.GateError):
        gate.load_json(path)


def test_invalid_json_capture_member_fails_closed(tmp_path: Path) -> None:
    """A capture member that is not JSON is refused."""
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(gate.GateError):
        gate.load_json(path)


def test_evidence_shape_helpers_fail_closed() -> None:
    """Array and object evidence fields are validated before they are trusted."""
    with pytest.raises(gate.GateError) as array_error:
        gate._require_list({"members": "nope"}, "members", "pypi/x@1")
    assert array_error.value.code == gate.EVIDENCE_INCOMPLETE
    with pytest.raises(gate.GateError):
        gate._require_mapping({"texts": []}, "texts", "pypi/x@1")


# ---------------------------------------------------------------------------
# Python and Cargo enumeration failures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "lock",
    [
        "greenlib>=1.0.0 --hash=sha256:" + PY_HASH,
        "greenlib==1.0.0",
        "# only a comment\n",
        "-r other.txt\n",
    ],
)
def test_unpinned_lock_is_refused(lock: str) -> None:
    """A lock that is not exactly pinned and hashed cannot be enumerated."""
    with pytest.raises(gate.GateError) as error:
        gate.parse_python_lock(lock)
    assert error.value.code == gate.LOCK_UNPINNED


def test_lock_continuation_lines_are_joined() -> None:
    """Backslash continuations are joined so the hash binds to its requirement."""
    parsed = gate.parse_python_lock(f"greenlib==1.0.0 \\\n    --hash=sha256:{PY_HASH}\n")
    assert parsed == {("greenlib", "1.0.0"): frozenset({PY_HASH})}


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"installed": {}},
        {"installed": [{}]},
        {"installed": [{"metadata": {"name": "x"}}]},
    ],
)
def test_malformed_environment_capture_is_refused(payload: Any) -> None:
    """``pip inspect`` output that is not the documented shape is refused."""
    with pytest.raises(gate.GateError) as error:
        gate.parse_installed_environment(payload)
    assert error.value.code == gate.CAPTURE_INCOMPLETE


@pytest.mark.parametrize(
    "text",
    ["this is not toml = = =", "version = 4\n", '[[package]]\nversion = "1.0"\n'],
)
def test_malformed_cargo_lock_is_refused(text: str) -> None:
    """A Cargo lock that cannot be enumerated is refused."""
    with pytest.raises(gate.GateError) as error:
        gate.parse_cargo_lock(text)
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def _metadata(**overrides: Any) -> dict[str, Any]:
    """Return a mutable copy of the passing cargo metadata capture."""
    payload = json.loads(json.dumps(CARGO_METADATA))
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"packages": {}, "resolve": {}},
        {"packages": [{"name": "x"}], "resolve": {"root": "r", "nodes": []}},
        {"packages": [{"id": "r"}], "resolve": {"nodes": {}, "root": "r"}},
        {"packages": [{"id": "r"}], "resolve": {"nodes": [{}], "root": "r"}},
        {
            "packages": [{"id": "r", "name": "r", "version": "1"}],
            "resolve": {"nodes": [{"id": "r", "deps": [{}]}], "root": "r"},
        },
        {
            "packages": [{"id": "r", "name": "r", "version": "1"}],
            "resolve": {"nodes": [{"id": "other", "deps": []}], "root": "r"},
        },
        {
            "packages": [{"id": "r", "name": "r", "version": "1"}],
            "resolve": {"nodes": [{"id": "r", "deps": [{"pkg": "ghost"}]}], "root": "r"},
        },
        {
            "packages": [{"id": "r", "name": "r", "version": "1"}, {"id": "d", "name": 7}],
            "resolve": {
                "nodes": [{"id": "r", "deps": [{"pkg": "d"}]}, {"id": "d", "deps": []}],
                "root": "r",
            },
        },
    ],
)
def test_malformed_cargo_metadata_is_refused(payload: Any) -> None:
    """Every defect in the resolved build graph refuses enumeration."""
    with pytest.raises(gate.GateError) as error:
        gate.resolve_cargo_graph(payload)
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def test_shared_transitive_dependency_is_visited_once() -> None:
    """A diamond in the build graph resolves to one component, not two."""
    payload = {
        "packages": [
            {"id": "r", "name": "root", "version": "1"},
            {"id": "a", "name": "a", "version": "1"},
            {"id": "b", "name": "b", "version": "1"},
            {"id": "c", "name": "c", "version": "1"},
        ],
        "resolve": {
            "root": "r",
            "nodes": [
                {"id": "r", "deps": [{"pkg": "a"}, {"pkg": "b"}]},
                {"id": "a", "deps": [{"pkg": "c"}]},
                {"id": "b", "deps": [{"pkg": "c"}]},
                {"id": "c", "deps": []},
            ],
        },
    }
    assert set(gate.resolve_cargo_graph(payload)) == {("a", "1"), ("b", "1"), ("c", "1")}


def test_cargo_lock_and_build_graph_must_agree() -> None:
    """Either asymmetry between Cargo.lock and the build graph refuses the release."""
    root = ("root", "1")
    graph = {("a", "1"): {}, ("b", "1"): {}}
    lock = {root: None, ("a", "1"): _hash("a"), ("c", "1"): _hash("c")}
    codes = {failure.code for failure in gate.reconcile_cargo(lock, graph, root)}
    assert codes == {gate.CARGO_LOCK_GRAPH_MISMATCH}


def test_cargo_registry_dependency_without_a_checksum_is_refused() -> None:
    """A resolved crate with no Cargo.lock checksum has no verifiable source."""
    root = ("root", "1")
    failures = gate.reconcile_cargo({root: None, ("a", "1"): None}, {("a", "1"): {}}, root)
    assert [failure.code for failure in failures] == [gate.CARGO_CHECKSUM_MISSING]


def test_cargo_only_and_python_only_releases_are_both_supported(tmp_path: Path) -> None:
    """A release may declare one ecosystem; the other's captures are then unused."""
    python_only = build_capture(tmp_path / "py")
    payload = json.loads((python_only / "release.json").read_text(encoding="utf-8"))
    payload["ecosystems"] = ["python"]
    (python_only / "release.json").write_text(json.dumps(payload), encoding="utf-8")
    report = gate.gate(python_only)
    assert [row["ecosystem"] for row in report.dependencies] == ["pypi"]

    cargo_only = build_capture(tmp_path / "rs")
    payload["ecosystems"] = ["cargo"]
    (cargo_only / "release.json").write_text(json.dumps(payload), encoding="utf-8")
    report = gate.gate(cargo_only)
    assert [row["ecosystem"] for row in report.dependencies] == ["cargo"]


# ---------------------------------------------------------------------------
# release.json and per-dependency evidence validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutation",
    [
        {"source_repository": "not-a-repository"},
        {"source_sha": "abc"},
        {"ecosystems": []},
        {"ecosystems": "python"},
    ],
)
def test_malformed_release_capture_is_refused(tmp_path: Path, mutation: dict[str, Any]) -> None:
    """The release identity must be exact before any dependency is examined."""
    capture = build_capture(tmp_path)
    payload = json.loads((capture / "release.json").read_text(encoding="utf-8"))
    payload.update(mutation)
    (capture / "release.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(gate.GateError) as error:
        gate.gate(capture)
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def test_release_capture_must_be_an_object(tmp_path: Path) -> None:
    """A release capture that is not an object is refused."""
    capture = build_capture(tmp_path)
    (capture / "release.json").write_text("[]", encoding="utf-8")
    with pytest.raises(gate.GateError):
        gate.gate(capture)


def test_enumerating_nothing_is_a_refusal_not_a_pass(tmp_path: Path) -> None:
    """An empty resolved dependency set can never be a vacuous pass."""
    capture = build_capture(tmp_path)
    payload = json.loads((capture / "release.json").read_text(encoding="utf-8"))
    payload["ecosystems"] = ["npm"]
    (capture / "release.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(gate.GateError) as error:
        gate.gate(capture)
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def test_evidence_must_be_an_object(tmp_path: Path) -> None:
    """Per-dependency evidence that is not an object is refused."""
    capture = build_capture(tmp_path)
    (capture / "evidence" / "pypi__greenlib__1.0.0.json").write_text("[]", encoding="utf-8")
    with pytest.raises(gate.GateError) as error:
        gate.gate(capture)
    assert error.value.code == gate.EVIDENCE_INCOMPLETE


@pytest.mark.parametrize("inclusion", [[], "wheel", ["deb"]])
def test_distribution_inclusion_must_be_declared(tmp_path: Path, inclusion: Any) -> None:
    """Every dependency must record which distributions include it."""
    from tests.test_release_dependency_gate import _python_evidence

    capture = build_capture(
        tmp_path, python_evidence=_python_evidence(distribution_inclusion=inclusion)
    )
    with pytest.raises(gate.GateError) as error:
        gate.gate(capture)
    assert error.value.code == gate.EVIDENCE_INCOMPLETE


@pytest.mark.parametrize(
    "mutation",
    [
        {"native_libraries": ["nope"]},
        {"native_libraries": [{"path": "x.so", "static_archives": ["nope"]}]},
        {"license_texts": []},
        {"bundled_library_licenses": []},
        {"classifiers": "MIT"},
    ],
)
def test_malformed_evidence_fields_are_refused(tmp_path: Path, mutation: dict[str, Any]) -> None:
    """Every evidence field is shape-checked before the policy consults it."""
    from tests.test_release_dependency_gate import _python_evidence

    capture = build_capture(tmp_path, python_evidence=_python_evidence(**mutation))
    if "classifiers" in mutation:
        # A non-list classifier block is ignored rather than fatal, so the
        # dependency falls through to LICENSE_MISSING instead of raising.
        payload = _python_evidence(license_expression="", license="", **mutation)
        capture = build_capture(tmp_path / "classifiers", python_evidence=payload)
        assert gate.LICENSE_MISSING in {
            failure.code for failure in gate.gate(capture).failures
        }
        return
    with pytest.raises(gate.GateError) as error:
        gate.gate(capture)
    assert error.value.code == gate.EVIDENCE_INCOMPLETE


@pytest.mark.parametrize(
    "selections",
    [
        {},
        [[]],
        [{"ecosystem": "pypi", "name": "greenlib"}],
    ],
)
def test_malformed_license_selections_are_refused(tmp_path: Path, selections: Any) -> None:
    """A selection file that does not declare a complete selection is refused."""
    capture = build_capture(tmp_path, selections=[])
    (capture / "license-selections.json").write_text(json.dumps(selections), encoding="utf-8")
    with pytest.raises(gate.GateError) as error:
        gate.gate(capture)
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def test_archive_escape_detector_skips_benign_members() -> None:
    """A member whose link target stays inside the root is not an escape."""
    assert gate.detect_archive_escape(
        [{"type": "symlink", "name": "pkg/a", "linkname": "b"}]
    ) == []


# ---------------------------------------------------------------------------
# Raw-capture assembly
# ---------------------------------------------------------------------------


def _write_raw(root: Path, **files: str) -> Path:
    """Write one raw dependency capture directory with the given member texts."""
    root.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        target = root / name.replace("__", "/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def test_capture_assembles_evidence_and_isolated_fixtures(tmp_path: Path) -> None:
    """Raw runner output becomes the capture contract plus one fixture per dependency."""
    raw = tmp_path / "raw"
    _write_raw(
        raw / "one",
        **{
            "metadata.json": json.dumps(
                {
                    "ecosystem": "pypi",
                    "name": "Green_Lib",
                    "version": "1.0.0",
                    "license_expression": "MIT",
                    "classifiers": ["License :: OSI Approved :: MIT License"],
                    "distribution_inclusion": ["wheel"],
                    "known_vulnerabilities": [{"id": "GHSA-xxxx"}],
                }
            ),
            "source.sha256": f"{PY_HASH}  greenlib-1.0.0.tar.gz\n",
            "members.txt": "file\tgreenlib/__init__.py\t\n\nsymlink\tpkg/l\t../out\n",
            "parsed_inputs.txt": "greenlib/__init__.py\n\n",
            "licenses__LICENSE": "MIT License",
            "hooks__setup.py": "from setuptools import setup",
            "native.json": json.dumps([{"path": "x.so", "needed": [], "static_archives": []}]),
            "bundled_library_licenses.json": json.dumps({"libfoo.so.1": "MIT"}),
        },
    )
    capture_root = tmp_path / "capture"
    assert gate.capture(raw, capture_root) == ["pypi/green-lib@1.0.0"]
    evidence = json.loads(
        (capture_root / "evidence" / "pypi__green-lib__1.0.0.json").read_text(encoding="utf-8")
    )
    assert evidence["source_sha256"] == PY_HASH
    assert evidence["license_texts"] == {"LICENSE": "MIT License"}
    assert evidence["install_hook_sources"] == {"setup.py": "from setuptools import setup"}
    assert evidence["archive_members"][1] == {
        "type": "symlink",
        "name": "pkg/l",
        "linkname": "../out",
    }
    assert evidence["parsed_inputs"] == ["greenlib/__init__.py"]
    fixture = json.loads(
        (capture_root / "strix" / "fixtures" / "pypi__green-lib__1.0.0.json").read_text(
            encoding="utf-8"
        )
    )
    digest = (
        (capture_root / "strix" / "fixtures" / "pypi__green-lib__1.0.0.sha256")
        .read_text(encoding="utf-8")
        .strip()
    )
    assert gate.fixture_digest(fixture) == digest
    assert fixture["scenarios"]["known_vulnerability_surface"] == {"advisories": ["GHSA-xxxx"]}


def test_capture_tolerates_absent_optional_raw_members(tmp_path: Path) -> None:
    """A dependency with no archive listing, licenses, or hooks still captures."""
    raw = tmp_path / "raw"
    _write_raw(
        raw / "cargo-dep",
        **{
            "metadata.json": json.dumps(
                {"ecosystem": "cargo", "name": "greencrate", "version": "0.1.0"}
            ),
        },
    )
    assert gate.capture(raw, tmp_path / "capture") == ["cargo/greencrate@0.1.0"]
    evidence = json.loads(
        (tmp_path / "capture" / "evidence" / "cargo__greencrate__0.1.0.json").read_text(
            encoding="utf-8"
        )
    )
    assert evidence["source_sha256"] == ""
    assert evidence["license_texts"] == {}
    assert evidence["archive_members"] == []


def test_capture_refuses_a_missing_or_empty_raw_root(tmp_path: Path) -> None:
    """A raw root that is absent or holds no dependency is refused."""
    with pytest.raises(gate.GateError):
        gate.capture(tmp_path / "absent", tmp_path / "capture")
    (tmp_path / "empty").mkdir()
    with pytest.raises(gate.GateError):
        gate.capture(tmp_path / "empty", tmp_path / "capture")


def test_capture_refuses_non_directory_raw_entries(tmp_path: Path) -> None:
    """A stray file in the raw root is refused rather than skipped."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "stray.txt").write_text("x", encoding="utf-8")
    with pytest.raises(gate.GateError):
        gate.capture(raw, tmp_path / "capture")


def test_capture_refuses_non_regular_license_members(tmp_path: Path) -> None:
    """A directory inside the flattened license capture is refused."""
    raw = tmp_path / "raw"
    _write_raw(
        raw / "one",
        **{
            "metadata.json": json.dumps(
                {"ecosystem": "cargo", "name": "c", "version": "1"}
            )
        },
    )
    (raw / "one" / "licenses" / "nested").mkdir(parents=True)
    with pytest.raises(gate.GateError):
        gate.capture(raw, tmp_path / "capture")


@pytest.mark.parametrize(
    "metadata",
    [
        "[]",
        json.dumps({"ecosystem": "npm", "name": "x", "version": "1"}),
        json.dumps({"ecosystem": "pypi", "name": "", "version": "1"}),
    ],
)
def test_capture_refuses_malformed_raw_metadata(tmp_path: Path, metadata: str) -> None:
    """Raw metadata must declare a supported ecosystem, a name, and a version."""
    raw = tmp_path / "raw"
    _write_raw(raw / "one", **{"metadata.json": metadata})
    with pytest.raises(gate.GateError):
        gate.capture(raw, tmp_path / "capture")


def test_member_listing_rejects_malformed_lines() -> None:
    """An archive listing line without a name is refused rather than dropped."""
    with pytest.raises(gate.GateError):
        gate.parse_member_listing("file\n")


# ---------------------------------------------------------------------------
# Sealed evidence composition
# ---------------------------------------------------------------------------


def _seal(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    """Gate a passing capture and seal its distributions, returning the outputs."""
    capture = build_capture(tmp_path / "capture")
    report_path = tmp_path / "report.json"
    assert gate.main(["gate", "--capture", str(capture), "--report", str(report_path)]) == 0
    distributions = tmp_path / "dist"
    distributions.mkdir()
    wheel = distributions / "fast_mlsirm-0.11.5-cp313-cp313-linux_x86_64.whl"
    sdist = distributions / "fast_mlsirm-0.11.5.tar.gz"
    wheel.write_bytes(b"wheel bytes")
    sdist.write_bytes(b"sdist bytes")
    evidence_root = tmp_path / "sealed"
    outputs = gate.seal(report_path, wheel, sdist, evidence_root, "sealed-evidence")
    return report_path, outputs, evidence_root


def test_seal_produces_exactly_the_six_members_attestation_verifies(tmp_path: Path) -> None:
    """The sealed directory is accepted verbatim by the attestation handoff verifier."""
    _report, outputs, evidence_root = _seal(tmp_path)
    assert sorted(path.name for path in evidence_root.iterdir()) == sorted(
        [
            outputs["wheel_filename"],
            outputs["wheel_sbom_filename"],
            outputs["sdist_filename"],
            outputs["sdist_sbom_filename"],
            gate.SOURCE_IDENTITY_FILENAME,
            gate.CHECKSUM_FILENAME,
        ]
    )
    manifest = handoff.verify(
        _namespace(outputs, evidence_root, tmp_path / "verified.json")
    )
    assert manifest["result"] == "PASS"


def _namespace(outputs: dict[str, str], evidence_root: Path, manifest: Path) -> Any:
    """Build the attestation verifier's argument namespace from the gate outputs."""
    import argparse

    return argparse.Namespace(
        source_repository=outputs["source_repository"],
        source_sha=outputs["source_sha"],
        evidence_artifact_name=outputs["evidence_artifact_name"],
        evidence_artifact_digest="sha256:" + _hash("artifact"),
        evidence_root=str(evidence_root),
        wheel_filename=outputs["wheel_filename"],
        wheel_sha256=outputs["wheel_sha256"],
        wheel_sbom_filename=outputs["wheel_sbom_filename"],
        wheel_sbom_sha256=outputs["wheel_sbom_sha256"],
        sdist_filename=outputs["sdist_filename"],
        sdist_sha256=outputs["sdist_sha256"],
        sdist_sbom_filename=outputs["sdist_sbom_filename"],
        sdist_sbom_sha256=outputs["sdist_sbom_sha256"],
        source_identity_sha256=outputs["source_identity_sha256"],
        checksum_sha256=outputs["checksum_sha256"],
        predicate_type=outputs["predicate_type"],
        cyclonedx_schema=outputs["cyclonedx_schema"],
        output_manifest=str(manifest),
    )


def test_seal_outputs_cover_every_attestation_input(tmp_path: Path) -> None:
    """Composition is only possible if the gate emits all required handoff fields."""
    _report, outputs, _root = _seal(tmp_path)
    required = {
        "source_repository",
        "source_sha",
        "wheel_filename",
        "wheel_sha256",
        "wheel_sbom_filename",
        "wheel_sbom_sha256",
        "sdist_filename",
        "sdist_sha256",
        "sdist_sbom_filename",
        "sdist_sbom_sha256",
        "source_identity_sha256",
        "checksum_sha256",
        "predicate_type",
        "cyclonedx_schema",
        "evidence_artifact_name",
    }
    assert required.issubset(outputs)
    assert outputs["source_repository"] == REPOSITORY
    assert outputs["source_sha"] == SOURCE_SHA


def test_sealed_sbom_lists_exactly_the_gated_dependencies(tmp_path: Path) -> None:
    """Provenance covers the dependency set the gate examined, with its rationales."""
    report_path, outputs, evidence_root = _seal(tmp_path)
    sbom = json.loads(
        (evidence_root / outputs["wheel_sbom_filename"]).read_text(encoding="utf-8")
    )
    names = [component["name"] for component in sbom["components"]]
    assert names == ["greencrate", "greenlib"]
    assert sbom["serialNumber"] == gate.cyclonedx_serial_number(
        outputs["wheel_filename"], outputs["wheel_sha256"]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["dependency_count"] == 2


def test_sealed_sbom_records_a_dual_license_selection_rationale(tmp_path: Path) -> None:
    """A selection rationale is written into the artifact provenance, not just logs."""
    from tests.test_release_dependency_gate import _python_evidence

    capture = build_capture(
        tmp_path / "capture",
        python_evidence=_python_evidence(license_expression="BSD-3-Clause OR GPL-2.0-only"),
        selections=[
            {
                "ecosystem": "pypi",
                "name": "greenlib",
                "version": "1.0.0",
                "chosen": "BSD-3-Clause",
                "rationale": "BSD-3-Clause selected for commercial redistribution",
            }
        ],
    )
    report_path = tmp_path / "report.json"
    assert gate.main(["gate", "--capture", str(capture), "--report", str(report_path)]) == 0
    wheel = tmp_path / "w.whl"
    sdist = tmp_path / "s.tar.gz"
    wheel.write_bytes(b"w")
    sdist.write_bytes(b"s")
    outputs = gate.seal(report_path, wheel, sdist, tmp_path / "sealed", "sealed-evidence")
    sbom = json.loads(
        (tmp_path / "sealed" / outputs["wheel_sbom_filename"]).read_text(encoding="utf-8")
    )
    rationales = [
        prop["value"]
        for component in sbom["components"]
        for prop in component["properties"]
        if prop["name"] == "cwl:dependency:license-selection-rationale"
    ]
    assert rationales == ["BSD-3-Clause selected for commercial redistribution"]


def test_seal_refuses_a_failing_gate_report(tmp_path: Path) -> None:
    """Bytes that did not pass the gate are never sealed for attestation."""
    from tests.test_release_dependency_gate import _python_evidence

    capture = build_capture(
        tmp_path / "capture",
        python_evidence=_python_evidence(license_expression="AGPL-3.0-only"),
    )
    report_path = tmp_path / "report.json"
    assert gate.main(["gate", "--capture", str(capture), "--report", str(report_path)]) == 2
    wheel = tmp_path / "w.whl"
    sdist = tmp_path / "s.tar.gz"
    wheel.write_bytes(b"w")
    sdist.write_bytes(b"s")
    with pytest.raises(gate.GateError):
        gate.seal(report_path, wheel, sdist, tmp_path / "sealed", "sealed-evidence")


def test_seal_refuses_a_report_that_is_not_an_object(tmp_path: Path) -> None:
    """A gate report that is not an object cannot authorize sealing."""
    report_path = tmp_path / "report.json"
    report_path.write_text("[]", encoding="utf-8")
    with pytest.raises(gate.GateError):
        gate.seal(report_path, tmp_path, tmp_path, tmp_path / "sealed", "name")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_capture_command_writes_evidence(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """The capture subcommand reports the dependency keys it assembled."""
    raw = tmp_path / "raw"
    _write_raw(
        raw / "one",
        **{
            "metadata.json": json.dumps(
                {"ecosystem": "cargo", "name": "greencrate", "version": "0.1.0"}
            )
        },
    )
    assert (
        gate.main(["capture", "--raw", str(raw), "--capture", str(tmp_path / "capture")]) == 0
    )
    assert json.loads(capsys.readouterr().out) == {"captured": ["cargo/greencrate@0.1.0"]}


def test_seal_command_appends_github_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seal subcommand appends every handoff field to ``$GITHUB_OUTPUT``."""
    capture = build_capture(tmp_path / "capture")
    report_path = tmp_path / "report.json"
    assert gate.main(["gate", "--capture", str(capture), "--report", str(report_path)]) == 0
    wheel = tmp_path / "w.whl"
    sdist = tmp_path / "s.tar.gz"
    wheel.write_bytes(b"w")
    sdist.write_bytes(b"s")
    output_file = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    assert (
        gate.main(
            [
                "seal",
                "--report",
                str(report_path),
                "--wheel",
                str(wheel),
                "--sdist",
                str(sdist),
                "--evidence-root",
                str(tmp_path / "sealed"),
                "--evidence-artifact-name",
                "sealed-evidence",
            ]
        )
        == 0
    )
    emitted = dict(
        line.split("=", 1) for line in output_file.read_text(encoding="utf-8").splitlines()
    )
    assert emitted["predicate_type"] == gate.CYCLONEDX_PREDICATE_TYPE
    assert emitted["cyclonedx_schema"] == gate.CYCLONEDX_SCHEMA


def test_write_github_output_is_a_noop_outside_actions(tmp_path: Path) -> None:
    """Without ``$GITHUB_OUTPUT`` the gate writes no output file."""
    gate.write_github_output({"a": "b"}, None)
    assert list(tmp_path.iterdir()) == []


def test_cli_reports_a_gate_error_as_exit_two(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """An unreadable capture exits non-zero instead of defaulting to success."""
    assert (
        gate.main(
            ["gate", "--capture", str(tmp_path / "absent"), "--report", str(tmp_path / "r.json")]
        )
        == 2
    )
    assert "ERROR:" in capsys.readouterr().err
