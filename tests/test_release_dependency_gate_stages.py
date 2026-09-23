"""The gate's two stages, credential absence, and full-set scope checks (#2342).

The reusable workflow declares the five provider secrets as ``required: false`` so
a review-only negative fixture can exercise the licence decision with no
credential present. That is only safe if three things hold, and each has a test
here:

1. A denied or unverifiable licence is refused by the **licence** stage, which
   never reads a Strix binding and needs no credential.
2. An *allowed* input that reaches the Strix stage **without** credentials fails
   closed with ``STRIX_CREDENTIALS_ABSENT`` — never skipped, neutral, or passed.
3. A passing licence-stage report can never be sealed, so the prescreen cannot
   stand in for the Strix stage.

The scope tests encode CO#1226: coverage was accepted because one component of an
ecosystem existed, so every expected member must now be counted and matched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import release_dependency_gate as gate
from tests.test_release_dependency_gate import (
    CARGO_METADATA,
    PY_HASH,
    SOURCE_SHA,
    _python_evidence,
    build_capture,
)


def _codes(report: gate.GateReport) -> set[str]:
    """Return the set of failure codes one gate report carries."""
    return {failure.code for failure in report.failures}


def _strip_strix_evidence(capture: Path) -> None:
    """Remove every Strix binding, as a credential-free run would leave the tree."""
    for binding in (capture / "strix" / "bindings").iterdir():
        binding.unlink()


# ---------------------------------------------------------------------------
# Regression direction (a): denied licence, no credentials, licence stage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("GPL-3.0-only", "LICENSE_DENIED_GPL"),
        ("LGPL-2.1-only", "LICENSE_DENIED_LGPL"),
        ("AGPL-3.0-only", "LICENSE_DENIED_AGPL"),
    ],
)
def test_denied_licence_fails_at_the_licence_stage_without_any_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expression: str, expected: str
) -> None:
    """A copyleft dependency is refused before Strix, with the licence reason code."""
    for name in gate.STRIX_CREDENTIAL_NAMES:
        monkeypatch.delenv(name, raising=False)
    capture = build_capture(
        tmp_path, python_evidence=_python_evidence(license_expression=expression)
    )
    _strip_strix_evidence(capture)
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    assert not report.passed
    codes = _codes(report)
    assert expected in codes
    # The licence stage reads no binding at all, so no Strix code can appear and
    # the refusal cannot be mistaken for a Strix verdict.
    assert not {code for code in codes if code.startswith("STRIX_")}
    assert report.to_json()["stage"] == gate.LICENSE_STAGE
    assert report.to_json()["strix_evidence_binder_sha256"] == ""


def test_unknown_licence_is_a_hold_at_the_licence_stage(tmp_path: Path) -> None:
    """UNKNOWN holds the release rather than passing it (atheris/numpy policy)."""
    for name, expression in (("atheris", ""), ("numpy", "UNKNOWN")):
        capture = build_capture(
            tmp_path / name,
            python_evidence=_python_evidence(
                license_expression=expression, license="", classifiers=[]
            ),
        )
        _strip_strix_evidence(capture)
        report = gate.gate(capture, stage=gate.LICENSE_STAGE)
        assert not report.passed, name
        assert _codes(report) & {"LICENSE_MISSING", "LICENSE_UNRECOGNIZED"}, name


def test_dual_licence_without_a_recorded_selection_fails_at_the_licence_stage(
    tmp_path: Path,
) -> None:
    """An `OR` expression needs an explicit permissive selection and a rationale."""
    capture = build_capture(
        tmp_path,
        python_evidence=_python_evidence(license_expression="MIT OR GPL-3.0-or-later"),
    )
    _strip_strix_evidence(capture)
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    assert not report.passed
    assert "LICENSE_SELECTION_REQUIRED" in _codes(report)


def test_licence_stage_passes_an_allowed_release_with_no_binding_present(
    tmp_path: Path,
) -> None:
    """The licence stage is meaningful only if an allowed input clears it credential-free."""
    capture = build_capture(tmp_path)
    _strip_strix_evidence(capture)
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    assert report.passed
    assert report.to_json()["stage"] == gate.LICENSE_STAGE


# ---------------------------------------------------------------------------
# Regression direction (b): allowed input reaching Strix with no credentials
# ---------------------------------------------------------------------------


def test_allowed_input_reaching_strix_without_credentials_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Credential absence at the Strix stage is a refusal, not a skip or a pass."""
    for name in gate.STRIX_CREDENTIAL_NAMES:
        monkeypatch.delenv(name, raising=False)
    failures = gate.require_strix_credentials(dict())
    assert [failure.code for failure in failures] == [gate.STRIX_CREDENTIALS_ABSENT]
    detail = failures[0].detail
    for name in gate.STRIX_CREDENTIAL_NAMES:
        assert name in detail


def test_a_single_absent_credential_still_fails_closed() -> None:
    """Four of five credentials is not four fifths of a pass."""
    environ = {name: "present" for name in gate.STRIX_CREDENTIAL_NAMES}
    environ["OPENAI_API_KEY"] = "   "
    failures = gate.require_strix_credentials(environ)
    assert [failure.code for failure in failures] == [gate.STRIX_CREDENTIALS_ABSENT]
    assert failures[0].detail.endswith("OPENAI_API_KEY")


def test_present_credentials_are_never_echoed_or_measured() -> None:
    """A present credential's value must not reach the reason code in any form."""
    sentinel = "SENTINEL-c0ffee-VALUE"
    environ = {name: sentinel for name in gate.STRIX_CREDENTIAL_NAMES}
    environ["BYTEZ_API_KEY"] = ""
    failures = gate.require_strix_credentials(environ)
    detail = failures[0].detail
    assert sentinel not in detail
    # Neither the value nor its length may be inferable from the refusal.
    assert str(len(sentinel)) not in detail
    assert detail.endswith("BYTEZ_API_KEY")


def test_all_credentials_present_is_no_failure() -> None:
    """The check refuses only absence; it never invents a credential failure."""
    environ = {name: "present" for name in gate.STRIX_CREDENTIAL_NAMES}
    assert gate.require_strix_credentials(environ) == []


def test_credential_command_exits_non_zero_and_prints_only_names(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI refuses with the reason code and leaks no secret material."""
    sentinel = "SENTINEL-c0ffee-VALUE"
    for name in gate.STRIX_CREDENTIAL_NAMES:
        monkeypatch.setenv(name, sentinel)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert gate.main(["require-strix-credentials"]) == 2
    captured = capsys.readouterr()
    assert gate.STRIX_CREDENTIALS_ABSENT in captured.err
    assert "OPENROUTER_API_KEY" in captured.err
    assert sentinel not in captured.err + captured.out


def test_credential_command_exits_zero_when_every_credential_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Strix stage proceeds only when all five credentials are present."""
    for name in gate.STRIX_CREDENTIAL_NAMES:
        monkeypatch.setenv(name, "present")
    assert gate.main(["require-strix-credentials"]) == 0


def test_full_stage_without_bindings_still_refuses_with_a_binding_code(
    tmp_path: Path,
) -> None:
    """Reaching the full stage with no Strix evidence refuses; it never degrades."""
    capture = build_capture(tmp_path)
    _strip_strix_evidence(capture)
    report = gate.gate(capture, stage=gate.FULL_STAGE)
    assert not report.passed
    assert gate.STRIX_BINDING_MISSING in _codes(report)


# ---------------------------------------------------------------------------
# A licence-stage report is not sealable
# ---------------------------------------------------------------------------


def test_a_passing_licence_stage_report_can_never_be_sealed(tmp_path: Path) -> None:
    """Sealing a prescreen would publish bytes Strix never examined."""
    capture = build_capture(tmp_path / "capture")
    _strip_strix_evidence(capture)
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    assert report.passed
    report_path = tmp_path / "prescreen.json"
    report_path.write_text(json.dumps(report.to_json()), encoding="utf-8")
    wheel = tmp_path / "pkg-1.0-py3-none-any.whl"
    sdist = tmp_path / "pkg-1.0.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    with pytest.raises(gate.GateError) as error:
        gate.seal(report_path, wheel, sdist, tmp_path / "sealed", "evidence")
    assert error.value.code == gate.CAPTURE_INCOMPLETE
    assert "full stage" in str(error.value)


def test_an_unknown_stage_is_refused(tmp_path: Path) -> None:
    """Only the two declared stages exist; anything else fails closed."""
    capture = build_capture(tmp_path)
    with pytest.raises(gate.GateError) as error:
        gate.gate(capture, stage="strix-only")
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def test_prescreen_and_gate_commands_report_their_stage(tmp_path: Path) -> None:
    """The CLI records which stage produced a report, so seal can check it."""
    capture = build_capture(tmp_path / "capture")
    prescreen_report = tmp_path / "prescreen.json"
    assert gate.main(
        ["prescreen", "--capture", str(capture), "--report", str(prescreen_report)]
    ) == 0
    assert json.loads(prescreen_report.read_text(encoding="utf-8"))["stage"] == (
        gate.LICENSE_STAGE
    )
    full_report = tmp_path / "gate.json"
    assert gate.main(["gate", "--capture", str(capture), "--report", str(full_report)]) == 0
    assert json.loads(full_report.read_text(encoding="utf-8"))["stage"] == gate.FULL_STAGE


def test_prescreen_command_exits_non_zero_on_a_denied_licence(tmp_path: Path) -> None:
    """The prescreen refuses through its exit status, and writes the reason code."""
    capture = build_capture(
        tmp_path / "capture",
        python_evidence=_python_evidence(license_expression="GPL-3.0-only"),
    )
    _strip_strix_evidence(capture)
    report_path = tmp_path / "prescreen.json"
    assert gate.main(
        ["prescreen", "--capture", str(capture), "--report", str(report_path)]
    ) == 2
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["result"] == "FAIL"
    assert {failure["code"] for failure in payload["failures"]} == {"LICENSE_DENIED_GPL"}


# ---------------------------------------------------------------------------
# Early exact-SHA and repository shape validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source_sha",
    ["", "main", "3c3ca9b1", SOURCE_SHA.upper(), SOURCE_SHA + "a", "g" * 40],
)
def test_a_non_exact_source_sha_is_refused_early(source_sha: str) -> None:
    """A release must name an exact 40-hex commit, not a branch or a short SHA."""
    with pytest.raises(gate.GateError) as error:
        gate.validate_release_identity("ContextualWisdomLab/fast-mlsirm", source_sha)
    assert error.value.code == gate.CAPTURE_INCOMPLETE


@pytest.mark.parametrize(
    "repository", ["", "fast-mlsirm", "a/b/c", "Contextual WisdomLab/x", "owner/"]
)
def test_a_malformed_repository_is_refused_early(repository: str) -> None:
    """The gated repository must be an unambiguous owner/name pair."""
    with pytest.raises(gate.GateError) as error:
        gate.validate_release_identity(repository, SOURCE_SHA)
    assert error.value.code == gate.CAPTURE_INCOMPLETE


def test_validate_inputs_command_accepts_an_exact_release_identity(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The workflow's first step passes only a well-formed exact identity."""
    assert (
        gate.main(
            [
                "validate-inputs",
                "--source-repository",
                "ContextualWisdomLab/fast-mlsirm",
                "--source-sha",
                SOURCE_SHA,
            ]
        )
        == 0
    )
    assert "well formed" in capsys.readouterr().out


def test_validate_inputs_command_refuses_a_branch_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A branch ref reaching the gate is refused before any credentialed step."""
    assert (
        gate.main(
            [
                "validate-inputs",
                "--source-repository",
                "ContextualWisdomLab/fast-mlsirm",
                "--source-sha",
                "main",
            ]
        )
        == 2
    )
    assert "40-hex" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Full-set scope comparison (CO#1226)
# ---------------------------------------------------------------------------


def test_a_subset_of_the_expected_python_set_is_a_scope_mismatch(tmp_path: Path) -> None:
    """A lock member with no collected evidence refuses the release."""
    second = f"otherlib==2.0.0 \\\n    --hash=sha256:{'b' * 64}\n"
    capture = build_capture(
        tmp_path,
        lock_text=f"greenlib==1.0.0 \\\n    --hash=sha256:{PY_HASH}\n{second}",
        installed={
            "installed": [
                {"metadata": {"name": "greenlib", "version": "1.0.0"}},
                {"metadata": {"name": "otherlib", "version": "2.0.0"}},
            ]
        },
    )
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    assert not report.passed
    assert gate.SCOPE_SET_MISMATCH in _codes(report)
    rows = {row["ecosystem"]: row for row in report.to_json()["scopes"]}
    # Two expected, one collected: counted and compared, not assumed.
    assert rows["python"]["expected_count"] == 2
    assert rows["python"]["collected_count"] == 1
    assert rows["python"]["matched_count"] == 1


def test_a_missing_fixture_is_a_scope_mismatch(tmp_path: Path) -> None:
    """Evidence without the isolated fixture leaves the Strix scope unestablished."""
    capture = build_capture(tmp_path)
    (capture / "strix" / "fixtures" / "pypi__greenlib__1.0.0.json").unlink()
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    assert not report.passed
    assert gate.SCOPE_SET_MISMATCH in _codes(report)
    rows = {row["ecosystem"]: row for row in report.to_json()["scopes"]}
    assert rows["python"]["collected_count"] == 1
    assert rows["python"]["matched_count"] == 0


def test_collected_material_outside_every_expected_set_is_a_scope_mismatch(
    tmp_path: Path,
) -> None:
    """Capture material the producer never declared leaves membership unestablished."""
    capture = build_capture(tmp_path)
    (capture / "evidence" / "pypi__smuggled__9.9.9.json").write_text(
        "{}", encoding="utf-8"
    )
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    assert not report.passed
    mismatches = [
        failure for failure in report.failures if failure.code == gate.SCOPE_SET_MISMATCH
    ]
    assert any("pypi__smuggled__9.9.9" in failure.detail for failure in mismatches)


def test_scope_rows_count_every_expected_member_on_a_green_release(
    tmp_path: Path,
) -> None:
    """A pass states the arithmetic it passed on, per ecosystem."""
    capture = build_capture(tmp_path)
    report = gate.gate(capture)
    assert report.passed
    rows = {row["ecosystem"]: row for row in report.to_json()["scopes"]}
    for ecosystem in ("python", "cargo"):
        row = rows[ecosystem]
        assert (
            row["expected_count"]
            == row["enumerated_count"]
            == row["collected_count"]
            == row["matched_count"]
            == 1
        ), ecosystem
        assert row["established"] is True


def test_a_target_only_cargo_dependency_gets_no_exemption(tmp_path: Path) -> None:
    """A cfg()-gated dependency such as `r-efi` is expected and gated like any other.

    `resolve_cargo_graph` walks every ``resolve.nodes`` edge regardless of
    ``dep_kind`` or target cfg, so a UEFI-only crate is in the expected set. This
    gate grants no target-based exemption, so its absence from the collected set is
    a refusal rather than a permitted omission.
    """
    metadata = json.loads(json.dumps(CARGO_METADATA))
    efi_id = "r-efi 5.4.0 (registry+https://github.com/rust-lang/crates.io-index)"
    metadata["packages"].append(
        {
            "id": efi_id,
            "name": "r-efi",
            "version": "5.4.0",
            "license": "MIT OR Apache-2.0 OR LGPL-2.1-or-later",
            "source": "registry+https://github.com/rust-lang/crates.io-index",
        }
    )
    root = metadata["resolve"]["root"]
    for node in metadata["resolve"]["nodes"]:
        if node["id"] == root:
            node["deps"].append(
                {"pkg": efi_id, "dep_kinds": [{"kind": None, "target": "x86_64-unknown-uefi"}]}
            )
    metadata["resolve"]["nodes"].append({"id": efi_id, "deps": []})
    capture = build_capture(tmp_path)
    (capture / "cargo" / "metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )
    lock_path = capture / "cargo" / "Cargo.lock"
    lock_path.write_text(
        lock_path.read_text(encoding="utf-8")
        + '\n[[package]]\nname = "r-efi"\nversion = "5.4.0"\n'
        + f'source = "registry+https://github.com/rust-lang/crates.io-index"\n'
        + f'checksum = "{"c" * 64}"\n',
        encoding="utf-8",
    )
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    assert not report.passed
    # It is enumerated as an expected member, so its uncollected evidence refuses.
    rows = {row["ecosystem"]: row for row in report.to_json()["scopes"]}
    assert rows["cargo"]["expected_count"] == 2
    assert gate.SCOPE_SET_MISMATCH in _codes(report)
    assert any(
        "cargo__r-efi__5.4.0" in failure.detail
        for failure in report.failures
        if failure.code == gate.SCOPE_SET_MISMATCH
    )


def test_unsupported_ecosystem_names_are_each_reported(tmp_path: Path) -> None:
    """Every unenumerable ecosystem is named, not just the first one found."""
    capture = build_capture(tmp_path)
    payload = json.loads((capture / "release.json").read_text(encoding="utf-8"))
    payload["ecosystems"] = ["python", "cargo", "npm", "maven"]
    (capture / "release.json").write_text(json.dumps(payload), encoding="utf-8")
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    subjects = {
        failure.subject
        for failure in report.failures
        if failure.code == gate.SCOPE_UNVERIFIABLE
    }
    assert subjects == {"ecosystem/npm", "ecosystem/maven"}


def test_scope_helpers_ignore_non_json_and_symlinked_capture_entries(
    tmp_path: Path,
) -> None:
    """Only regular ``.json`` files count as collected material."""
    directory = tmp_path / "evidence"
    directory.mkdir()
    (directory / "real.json").write_text("{}", encoding="utf-8")
    (directory / "notes.txt").write_text("x", encoding="utf-8")
    (directory / "link.json").symlink_to(directory / "real.json")
    (directory / "nested.json").mkdir()
    assert gate._present_slugs(directory) == {"real"}
    assert gate._present_slugs(tmp_path / "absent") == set()


def test_slug_for_key_matches_the_dependency_slug() -> None:
    """The scope comparison and the capture filenames must agree exactly."""
    dependency = gate.Dependency("pypi", "green-lib", "1.0.0")
    assert gate._slug_for_key(dependency.key) == dependency.slug


def test_missing_expected_key_set_is_treated_as_unestablished(tmp_path: Path) -> None:
    """An ecosystem whose enumerator produced no expected member cannot pass."""
    rows, failures = gate._scope_rows(tmp_path, ["python"], {"python": set()}, [])
    assert [failure.code for failure in failures] == [gate.SCOPE_UNVERIFIABLE]
    assert rows[0]["expected_count"] == 0


def test_evidence_present_for_a_dependency_absent_from_the_environment(
    tmp_path: Path,
) -> None:
    """A lock member missing from the environment fails scope *and* reconciliation."""
    capture = build_capture(
        tmp_path,
        lock_text=(
            f"greenlib==1.0.0 \\\n    --hash=sha256:{PY_HASH}\n"
            f"ghostlib==3.0.0 \\\n    --hash=sha256:{'d' * 64}\n"
        ),
    )
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    assert not report.passed
    codes = _codes(report)
    assert gate.LOCK_ENV_MISMATCH in codes
    assert gate.SCOPE_SET_MISMATCH in codes


def test_report_json_sorts_scope_rows_by_ecosystem(tmp_path: Path) -> None:
    """The report is deterministic, so a diff of two runs is meaningful."""
    capture = build_capture(tmp_path)
    payload = gate.gate(capture).to_json()
    ecosystems = [row["ecosystem"] for row in payload["scopes"]]
    assert ecosystems == sorted(ecosystems)


def test_strix_credential_names_are_exactly_the_workflow_secrets() -> None:
    """The checked set and the workflow's declared secrets must not drift apart."""
    workflow = Path(
        ".github/workflows/release-dependency-license-strix-gate.yml"
    ).read_text(encoding="utf-8")
    block = workflow.split("    secrets:\n", 1)[1].split("    outputs:", 1)[0]
    declared = [
        line.strip().rstrip(":")
        for line in block.splitlines()
        if line.startswith("      ") and line.strip().endswith(":")
    ]
    assert declared == list(gate.STRIX_CREDENTIAL_NAMES)


def test_supported_ecosystems_map_to_the_dependency_key_prefixes() -> None:
    """The scope comparison must key on the same prefix the enumerators emit."""
    assert gate.SUPPORTED_ECOSYSTEMS == {"python": "pypi", "cargo": "cargo"}


def test_gate_stages_are_exactly_the_two_declared_stages() -> None:
    """A third stage would need its own sealing rule, so the set is pinned."""
    assert gate.GATE_STAGES == (gate.LICENSE_STAGE, gate.FULL_STAGE)


def test_require_strix_credentials_accepts_an_explicit_name_list() -> None:
    """The caller may narrow the checked names; absence still refuses."""
    assert gate.require_strix_credentials({"A": "x"}, ["A"]) == []
    failures = gate.require_strix_credentials({"A": ""}, ["A"])
    assert failures[0].code == gate.STRIX_CREDENTIALS_ABSENT
