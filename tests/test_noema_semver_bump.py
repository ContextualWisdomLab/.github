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


def test_recorded_minor_ok_computes_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Happy path: recorded minor verdict yields previous+minor."""
    monkeypatch.setenv(
        "NOEMA_SEMVER_RECORDED_RESPONSE_PATH",
        str(FIXTURES / "recorded_minor_ok.json"),
    )
    provenance = semver.decide_release_version(_evidence("evidence_minor.json"))
    assert provenance["release_version"] == "0.12.0"
    assert provenance["verdict"]["bump"] == "minor"
    notes = semver.render_notes_prefix(provenance)
    assert "Noema semver verdict" in notes
    assert "`minor`" in notes


def test_recorded_unavailable_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unavailable Noema must stop the release for a human."""
    monkeypatch.setenv(
        "NOEMA_SEMVER_RECORDED_RESPONSE_PATH",
        str(FIXTURES / "recorded_unavailable.json"),
    )
    with pytest.raises(semver.SemverBumpError, match="unavailable"):
        semver.decide_release_version(_evidence("evidence_minor.json"))


def test_recorded_low_confidence_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Low-confidence verdicts fail closed even when the bump class looks fine."""
    monkeypatch.setenv(
        "NOEMA_SEMVER_RECORDED_RESPONSE_PATH",
        str(FIXTURES / "recorded_low_confidence.json"),
    )
    with pytest.raises(semver.SemverBumpError, match="confidence"):
        semver.decide_release_version(_evidence("evidence_minor.json"))


def test_recorded_patch_conflicts_with_breaking_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detected removed public symbol + patch bump is a hard conflict."""
    monkeypatch.setenv(
        "NOEMA_SEMVER_RECORDED_RESPONSE_PATH",
        str(FIXTURES / "recorded_patch_conflicts_breaking.json"),
    )
    with pytest.raises(semver.SemverBumpError, match="conflicts with detected breaking"):
        semver.decide_release_version(_evidence("evidence_breaking.json"))


def test_recorded_major_ok_on_breaking(monkeypatch: pytest.MonkeyPatch) -> None:
    """Breaking evidence with a major verdict is accepted."""
    monkeypatch.setenv(
        "NOEMA_SEMVER_RECORDED_RESPONSE_PATH",
        str(FIXTURES / "recorded_major_ok.json"),
    )
    provenance = semver.decide_release_version(_evidence("evidence_breaking.json"))
    assert provenance["release_version"] == "1.0.0"
    assert provenance["breaking_refs_detected"] == [
        "api:removed:fast_mlsirm.old_helper"
    ]


def test_requested_version_must_match_computed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Human-requested version that disagrees with Noema fails closed."""
    monkeypatch.setenv(
        "NOEMA_SEMVER_RECORDED_RESPONSE_PATH",
        str(FIXTURES / "recorded_minor_ok.json"),
    )
    with pytest.raises(semver.SemverBumpError, match="does not match"):
        semver.decide_release_version(
            _evidence("evidence_minor.json"),
            requested_version="0.11.3",
        )


def test_main_writes_provenance_and_github_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI used by the workflow writes provenance, notes, and GITHUB_OUTPUT."""
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
    assert rc == 0
    prov = json.loads(output.read_text(encoding="utf-8"))
    assert prov["release_version"] == "0.12.0"
    assert "Noema semver verdict" in notes.read_text(encoding="utf-8")
    gh_text = gh_out.read_text(encoding="utf-8")
    assert "release_version=0.12.0" in gh_text
    assert "bump=minor" in gh_text


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


def test_call_noema_live_transport_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live URL/key/model env is fail-closed; recorded path is required."""
    monkeypatch.delenv("NOEMA_SEMVER_RECORDED_RESPONSE_PATH", raising=False)
    for name in (
        "NOEMA_LLM_API_KEY",
        "NOEMA_LLM_API_URL",
        "NOEMA_LLM_MODEL",
        "CONTEXTUAL_ORCHESTRATOR_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(semver.SemverBumpError, match="NOEMA_SEMVER_RECORDED_RESPONSE_PATH"):
        semver.call_noema_for_bump({"previous_version": "0.1.0"})

    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_MODEL", "orchestrator/free")
    with pytest.raises(semver.SemverBumpError, match="live LLM transport"):
        semver.call_noema_for_bump({"previous_version": "0.1.0"})

    # Even with a recorded fixture, live transport env remains rejected.
    monkeypatch.setenv(
        "NOEMA_SEMVER_RECORDED_RESPONSE_PATH",
        str(FIXTURES / "recorded_minor_ok.json"),
    )
    with pytest.raises(semver.SemverBumpError, match="live LLM transport"):
        semver.call_noema_for_bump({"previous_version": "0.1.0"})


def test_call_noema_recorded_only_without_live_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recorded fixtures work when no live LLM transport env is present."""
    for name in (
        "NOEMA_LLM_API_KEY",
        "NOEMA_LLM_API_URL",
        "NOEMA_LLM_MODEL",
        "CONTEXTUAL_ORCHESTRATOR_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(
        "NOEMA_SEMVER_RECORDED_RESPONSE_PATH",
        str(FIXTURES / "recorded_minor_ok.json"),
    )
    verdict = semver.call_noema_for_bump({"previous_version": "0.11.2"})
    assert verdict.bump == "minor"


def test_extract_json_object_and_parse_edges() -> None:
    """Malformed verdicts fail closed."""
    with pytest.raises(semver.SemverBumpError):
        semver.extract_json_object("no object here")
    with pytest.raises(semver.SemverBumpError):
        semver.parse_verdict({"bump": "mega", "reason": "x", "evidence_refs": ["a"], "confidence": 1})
    with pytest.raises(semver.SemverBumpError):
        semver.parse_core_semver("01.0.0")


def test_required_arg_promotion_conflicts_with_minor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR-0028 required-arg promotions are breaking; minor under-bumps fail."""
    monkeypatch.setenv(
        "NOEMA_SEMVER_RECORDED_RESPONSE_PATH",
        str(FIXTURES / "recorded_minor_ok.json"),
    )
    evidence = _evidence("evidence_minor.json")
    evidence["required_arg_promotions"] = ["enumerate_bifactor_direct.max_iter"]
    with pytest.raises(semver.SemverBumpError, match="conflicts with detected breaking"):
        semver.decide_release_version(evidence)


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


def test_parse_verdict_field_errors() -> None:
    """Each verdict field is validated independently."""
    base = {
        "bump": "patch",
        "reason": "ok",
        "evidence_refs": ["a"],
        "confidence": 0.9,
    }
    with pytest.raises(semver.SemverBumpError, match="reason"):
        semver.parse_verdict({**base, "reason": "  "})
    with pytest.raises(semver.SemverBumpError, match="evidence_refs must be a non-empty"):
        semver.parse_verdict({**base, "evidence_refs": []})
    with pytest.raises(semver.SemverBumpError, match="entries must be non-empty"):
        semver.parse_verdict({**base, "evidence_refs": [""]})
    with pytest.raises(semver.SemverBumpError, match="confidence must be a number"):
        semver.parse_verdict({**base, "confidence": True})
    with pytest.raises(semver.SemverBumpError, match=r"\[0, 1\]"):
        semver.parse_verdict({**base, "confidence": 1.5})


def test_extract_json_object_skips_noise_then_parses() -> None:
    """Leading prose before the JSON object is tolerated."""
    obj = semver.extract_json_object(
        'prefix {"bump":"patch","reason":"r","evidence_refs":["e"],"confidence":0.8} trailing'
    )
    assert obj["bump"] == "patch"
    with pytest.raises(semver.SemverBumpError, match="empty"):
        semver.extract_json_object("   ")
    # A bare "{" that is not valid JSON must be skipped before a later object.
    obj2 = semver.extract_json_object(
        '{not-json {"bump":"minor","reason":"r","evidence_refs":["e"],"confidence":0.9}'
    )
    assert obj2["bump"] == "minor"


def test_extract_json_object_ignores_non_dict_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a decode yields a non-dict, scanning continues then fails closed."""
    real_raw = json.JSONDecoder.raw_decode

    def _raw(self: json.JSONDecoder, s: str, idx: int = 0) -> tuple[object, int]:
        if s[idx:].startswith("{1"):
            return ([1], idx + 2)
        return real_raw(self, s, idx)

    monkeypatch.setattr(json.JSONDecoder, "raw_decode", _raw)
    with pytest.raises(semver.SemverBumpError, match="did not contain"):
        semver.extract_json_object("{1 later")


def test_load_recorded_unreadable(tmp_path: Path) -> None:
    """OSError while reading a recorded fixture fails closed."""
    path = tmp_path / "gone.json"
    path.write_text("{}", encoding="utf-8")
    path.unlink()
    with pytest.raises(semver.SemverBumpError, match="unavailable"):
        semver.load_recorded_verdict(path)


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
    assert excinfo.value.code == 0


def test_load_recorded_verdict_shape_errors(tmp_path: Path) -> None:
    """Recorded fixtures that are not objects fail closed."""
    path = tmp_path / "arr.json"
    path.write_text("[1]\n", encoding="utf-8")
    with pytest.raises(semver.SemverBumpError, match="JSON object"):
        semver.load_recorded_verdict(path)
    nested = tmp_path / "nested.json"
    nested.write_text('{"verdict": []}\n', encoding="utf-8")
    with pytest.raises(semver.SemverBumpError, match="must be an object"):
        semver.load_recorded_verdict(nested)
    flat = tmp_path / "flat.json"
    flat.write_text(
        json.dumps(
            {
                "bump": "patch",
                "reason": "docs",
                "evidence_refs": ["c"],
                "confidence": 0.9,
            }
        ),
        encoding="utf-8",
    )
    assert semver.load_recorded_verdict(flat).bump == "patch"


def test_decide_requires_previous_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing previous_version fails before calling Noema."""
    monkeypatch.setenv(
        "NOEMA_SEMVER_RECORDED_RESPONSE_PATH",
        str(FIXTURES / "recorded_minor_ok.json"),
    )
    with pytest.raises(semver.SemverBumpError, match="previous_version is required"):
        semver.decide_release_version({})


def test_requested_version_match_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Matching requested version is accepted."""
    monkeypatch.setenv(
        "NOEMA_SEMVER_RECORDED_RESPONSE_PATH",
        str(FIXTURES / "recorded_minor_ok.json"),
    )
    provenance = semver.decide_release_version(
        _evidence("evidence_minor.json"),
        requested_version="v0.12.0",
    )
    assert provenance["release_version"] == "0.12.0"


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
        == 0
    )
