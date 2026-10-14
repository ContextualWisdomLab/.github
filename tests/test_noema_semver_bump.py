"""Tests for Noema-decided semver bump (ADR-0033)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts.ci import noema_semver_bump as semver

FIXTURES = Path("tests/fixtures/noema_semver")


def _evidence(name: str) -> dict:
    """Load a named evidence fixture."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_production_module_exposes_no_uncalibrated_model_response_path() -> None:
    """Recorded verdict parsing stays outside the production release module."""
    for name in (
        "SemverVerdict",
        "call_noema_for_bump",
        "extract_json_object",
        "load_recorded_verdict",
        "parse_verdict",
    ):
        assert not hasattr(semver, name), name


@pytest.mark.parametrize("reported_confidence", [0.0, 0.7, 1.0])
def test_direct_decision_fails_without_released_calibration(
    reported_confidence: float,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No self-reported confidence can authorize a production release."""
    recorded = tmp_path / "recorded.json"
    recorded.write_text(
        json.dumps(
            {
                "bump": "minor",
                "reason": "unreleased fixture",
                "evidence_refs": ["fixture:direct-call"],
                "confidence": reported_confidence,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("NOEMA_SEMVER_RECORDED_RESPONSE_PATH", str(recorded))

    with pytest.raises(semver.SemverBumpError, match="calibrated release-decision receipt"):
        semver.decide_release_version(_evidence("evidence_minor.json"))


def test_apply_bump_major_minor_patch() -> None:
    """Core semver arithmetic matches semver.org 2.0.0 core rules."""
    assert semver.apply_bump("0.11.2", "major") == "1.0.0"
    assert semver.apply_bump("0.11.2", "minor") == "0.12.0"
    assert semver.apply_bump("0.11.2", "patch") == "0.11.3"


def test_main_fails_without_writing_release_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The direct CLI cannot publish provenance or GitHub release outputs."""
    monkeypatch.setenv(
        "NOEMA_SEMVER_RECORDED_RESPONSE_PATH",
        str(FIXTURES / "recorded_minor_ok.json"),
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        (FIXTURES / "evidence_minor.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    output = tmp_path / "prov.json"
    notes = tmp_path / "notes.md"
    gh_out = tmp_path / "github_output"
    rc = semver.main(
        [
            "--evidence",
            str(evidence),
            "--output",
            str(output),
            "--notes-prefix",
            str(notes),
            "--github-output",
            str(gh_out),
        ]
    )
    assert rc == 1
    assert not output.exists()
    assert not notes.exists()
    assert not gh_out.exists()


def test_main_returns_one_on_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI exits 1 when the gate fails closed."""
    monkeypatch.setenv(
        "NOEMA_SEMVER_RECORDED_RESPONSE_PATH",
        str(FIXTURES / "recorded_unavailable.json"),
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        (FIXTURES / "evidence_minor.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    rc = semver.main(
        [
            "--evidence",
            str(evidence),
            "--output",
            str(tmp_path / "prov.json"),
        ]
    )
    assert rc == 1


def test_parse_core_semver_rejects_noncanonical_version() -> None:
    """Noncanonical core versions fail closed."""
    with pytest.raises(semver.SemverBumpError):
        semver.parse_core_semver("01.0.0")


def test_apply_bump_rejects_unknown_class() -> None:
    """Unknown bump tokens fail closed."""
    with pytest.raises(semver.SemverBumpError, match="unknown bump"):
        semver.apply_bump("1.0.0", "mega")


def test_load_evidence_errors(tmp_path: Path) -> None:
    """Corrupt or non-object evidence packs fail closed."""
    missing = tmp_path / "missing.json"
    with pytest.raises(semver.SemverBumpError, match="unable to read"):
        semver.load_evidence(missing)
    bad = tmp_path / "bad.json"
    bad.write_text("[1,2]\n", encoding="utf-8")
    with pytest.raises(semver.SemverBumpError, match="JSON object"):
        semver.load_evidence(bad)
    assert semver.load_evidence(FIXTURES / "evidence_minor.json")["previous_version"] == "0.11.2"


def test_detected_breaking_refs_validate_shape() -> None:
    """Breaking-ref lists must be lists of non-empty strings."""
    with pytest.raises(semver.SemverBumpError, match="must be a list"):
        semver.detected_breaking_refs({"removed_public_symbols": "nope"})
    with pytest.raises(semver.SemverBumpError, match="non-empty strings"):
        semver.detected_breaking_refs({"removed_public_symbols": ["  "]})
    refs = semver.detected_breaking_refs(
        {
            "renamed_public_symbols": ["a->b"],
            "required_arg_promotions": ["f.x"],
        }
    )
    assert refs == ("api:renamed:a->b", "api:required-arg:f.x")


def test_module_main_entrypoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``python -m`` style __main__ guard exits with main()'s status."""
    monkeypatch.setenv(
        "NOEMA_SEMVER_RECORDED_RESPONSE_PATH",
        str(FIXTURES / "recorded_minor_ok.json"),
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        (FIXTURES / "evidence_minor.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    output = tmp_path / "prov.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "noema_semver_bump.py",
            "--evidence",
            str(evidence),
            "--output",
            str(output),
        ],
    )
    with pytest.raises(SystemExit) as excinfo:
        import runpy

        runpy.run_module("scripts.ci.noema_semver_bump", run_name="__main__")
    assert excinfo.value.code == 1


def test_main_without_optional_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI works when notes-prefix and github-output are omitted."""
    monkeypatch.setenv(
        "NOEMA_SEMVER_RECORDED_RESPONSE_PATH",
        str(FIXTURES / "recorded_minor_ok.json"),
    )
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        (FIXTURES / "evidence_minor.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    output = tmp_path / "prov.json"
    assert (
        semver.main(
            [
                "--evidence",
                str(evidence),
                "--output",
                str(output),
                "--previous-version",
                "0.11.2",
            ]
        )
        == 1
    )
