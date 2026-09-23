"""Whole-source evidence and real gate regressions; no dependency execution."""

from pathlib import Path
import hashlib

import pytest

from scripts.ci import release_dependency_gate as gate
from scripts.ci import spdx_license_policy as policy
from tests.test_release_dependency_gate import _python_evidence, _cargo_evidence, build_capture


MIT = (Path(__file__).resolve().parents[1] / "LICENSE").read_text(encoding="utf-8")


def test_reviewed_source_is_full_pinned_text():
    assert hashlib.sha256(MIT.encode()).hexdigest() == (
        "08f1fd81fb120bc468b69dc3e58ea0dc23c216305c766e45e107f56c76559e3f"
    )
    assert policy.recognize_license_text(MIT) == frozenset({"MIT"})
    assert policy.recognize_license_text(MIT.replace("\n", "\r\n\t")) == frozenset({"MIT"})


@pytest.mark.parametrize("body", [
    "MIT License",
    "MIT License\nPermission is hereby granted, free of charge, to any person.\n"
    "Additional condition: use is permitted for academic research only. "
    "Commercial use and redistribution are prohibited.",
    "CREATIVE COMMONS LEGAL CODE\nAttribution-NonCommercial 4.0 International\n"
    "Commercial use is prohibited.",
    MIT + "\nAcademic research only.",
    "Commercial redistribution is prohibited.\n" + MIT,
    MIT.replace("without restriction", "only for academic research"),
    MIT.replace("2026 ContextualWisdomLab", "2026 Example: commercial use prohibited"),
    MIT + "\x00",
    MIT + "\u200b",
])
def test_unreviewed_or_modified_whole_text_fails_closed(body):
    assert policy.recognize_license_text(body) is None


@pytest.mark.parametrize("expression,body", [
    ("MIT", MIT + "\nAcademic research only. Commercial use is prohibited."),
    ("CC0-1.0", "CREATIVE COMMONS LEGAL CODE\nAttribution-NonCommercial 4.0 International"),
])
def test_real_gate_rejects_review_counterexamples(tmp_path, expression, body):
    capture = build_capture(tmp_path, python_evidence=_python_evidence(
        license_expression=expression, license_texts={"LICENSE": body}))
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    assert not report.passed
    assert any(f.code == policy.LICENSE_TEXT_UNVERIFIED and "greenlib" in f.subject
               for f in report.failures)


def test_real_gate_preserves_unsupported_cargo_hold_with_verified_python(tmp_path):
    capture = build_capture(tmp_path, python_evidence=_python_evidence(
        license_texts={"LICENSE": MIT}), cargo_evidence=_cargo_evidence(
            license_texts={"LICENSE-APACHE": "Apache License\nVersion 2.0, January 2004"}))
    report = gate.gate(capture, stage=gate.LICENSE_STAGE)
    assert not report.passed  # Explicitly incomplete Apache is still not MIT.
    assert report.failures
    assert all("greencrate" in f.subject and f.code == policy.LICENSE_TEXT_UNVERIFIED
               for f in report.failures)


@pytest.mark.parametrize("extra", ["UNKNOWN", "Commercial use prohibited.", MIT + " extra"])
def test_each_license_file_must_be_verified(extra):
    failures, decision, _ = gate.evaluate_dependency_license(
        _python_evidence(license_texts={"LICENSE": MIT, "NOTICE": extra}),
        "pypi/greenlib@1.0.0", None)
    assert decision.allowed  # Metadata policy and bundled-text evidence differ.
    assert [f.code for f in failures] == [policy.LICENSE_TEXT_UNVERIFIED]


def test_positive_same_caller_and_gpl_separate_file():
    failures, _, _ = gate.evaluate_dependency_license(
        _python_evidence(license_texts={"LICENSE": MIT}), "pypi/greenlib@1.0.0", None)
    assert failures == []
    failures, _, _ = gate.evaluate_dependency_license(
        _python_evidence(license_texts={"LICENSE": MIT,
                                      "COPYING": "GNU GENERAL PUBLIC LICENSE Version 3"}),
        "pypi/greenlib@1.0.0", None)
    assert [f.code for f in failures] == [gate.LICENSE_TEXT_DISAGREEMENT]
