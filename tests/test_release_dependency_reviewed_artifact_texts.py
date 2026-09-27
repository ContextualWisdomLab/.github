"""Actual artifact license bytes exercise the same dependency consumer."""

import hashlib
import json
from pathlib import Path
import re

import pytest

from scripts.ci import release_dependency_gate as gate
from scripts.ci import spdx_license_policy as policy
from tests.test_release_dependency_gate import _python_evidence

ROOT = Path(__file__).parent / "fixtures" / "release_license_texts"
ROWS = json.loads((ROOT / "provenance.json").read_text(encoding="utf-8"))
TEXTS = json.loads((ROOT / "texts.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("row", ROWS, ids=lambda r: r["package"])
def test_actual_whole_text_and_consumer(row):
    """Whole text matches recorded bytes and the declared-license caller."""
    raw = TEXTS[row["fixture"]].encode("utf-8")
    assert hashlib.sha256(raw).hexdigest() == row["raw_sha256"]
    text = raw.decode("utf-8")
    normalized = re.sub(r"[ \t\r\n]+", " ", text).strip(" \t\r\n")
    assert hashlib.sha256(normalized.encode()).hexdigest() == row["normalized_sha256"]
    assert policy.recognize_license_text(text) == frozenset({row["identifier"]})
    # This synthetic declaration exercises the recognizer, and does not claim
    # that atheris's actual missing metadata has been repaired.
    evidence = _python_evidence(license_expression=row["identifier"],
                                license_texts={"LICENSE": text})
    failures, _, _ = gate.evaluate_dependency_license(evidence, row["package"], None)
    assert failures == []


@pytest.mark.parametrize("row", ROWS, ids=lambda r: r["package"])
@pytest.mark.parametrize("placement", ["prefix", "suffix", "body", "notice"])
def test_additional_condition_and_multifile_are_rejected(row, placement):
    """No additional condition can inherit the recognized full-text digest."""
    text = TEXTS[row["fixture"]]
    restriction = "Commercial use is prohibited. Academic research only."
    files = {"LICENSE": text}
    if placement == "prefix":
        files["LICENSE"] = restriction + "\n" + text
    elif placement == "suffix":
        files["LICENSE"] = text + "\n" + restriction
    elif placement == "body":
        middle = len(text) // 2
        files["LICENSE"] = text[:middle] + restriction + text[middle:]
    else:
        files["NOTICE"] = restriction
    failures, _, _ = gate.evaluate_dependency_license(
        _python_evidence(license_expression=row["identifier"], license_texts=files),
        row["package"], None)
    assert [f.code for f in failures] == [policy.LICENSE_TEXT_UNVERIFIED]


def test_atheris_missing_declaration_is_not_auto_repaired():
    """Identifying bundled Apache text does not manufacture package metadata."""
    row = next(r for r in ROWS if r["package"] == "atheris@3.1.0")
    failures, decision, _ = gate.evaluate_dependency_license(
        _python_evidence(license_expression=None, license="", classifiers=[],
                         license_texts={"LICENSE": TEXTS[row["fixture"]]}),
        row["package"], None)
    assert not decision.allowed
    assert failures


def test_allocator_dual_licence_uses_both_actual_archive_texts():
    rows = [row for row in ROWS if row['package'] == 'allocator-api2@0.2.21']
    evidence = _python_evidence(
        license_expression='MIT OR Apache-2.0',
        license_texts={row['member']: TEXTS[row['fixture']] for row in rows},
    )
    failures, decision, _ = gate.evaluate_dependency_license(
        evidence, 'cargo/allocator-api2@0.2.21',
        {'chosen': 'MIT', 'rationale': 'Inspected both archive licence texts; retain the MIT permission notice.'},
    )
    assert failures == []
    assert decision.allowed
    failures, _, _ = gate.evaluate_dependency_license(evidence, 'cargo/allocator-api2@0.2.21', None)
    assert policy.LICENSE_SELECTION_REQUIRED in {failure.code for failure in failures}


@pytest.mark.parametrize("row", [r for r in json.loads((ROOT / "reference_provenance.json").read_text())
                                  if r["package"].startswith("android_system_properties@")],
                         ids=lambda row: row["package"])
@pytest.mark.parametrize("mutation", [None, "no-mit", "notice-only", "changed-notice",
                                      "apache-choice", "pypi", "and-expression", "no-choice"])
def test_android_apache_notice_does_not_supply_a_full_grant(row, mutation):
    text = TEXTS[row["fixture"]]
    assert hashlib.sha256(text.encode()).hexdigest() == row["raw_sha256"]
    normalized = re.sub(r"[ \t\r\n]+", " ", text).strip(" \t\r\n")
    assert hashlib.sha256(normalized.encode()).hexdigest() == row["normalized_sha256"]
    assert policy.recognize_license_text(text) is None
    texts = {"LICENSE-MIT": TEXTS["android_system_properties-0.1.6-LICENSE-MIT.txt"],
             "LICENSE-APACHE": text}
    if mutation in {"no-mit", "notice-only"}:
        del texts["LICENSE-MIT"]
    if mutation == "changed-notice":
        texts["LICENSE-APACHE"] += "Commercial redistribution requires additional permission."
    expression = "MIT AND Apache-2.0" if mutation == "and-expression" else "MIT OR Apache-2.0"
    selection = {"chosen": "Apache-2.0" if mutation == "apache-choice" else "MIT",
                 "rationale": "Read complete MIT grant and the separate Apache reference notice."}
    if mutation == "no-choice":
        selection = None
    evidence = _python_evidence(license_expression=expression, license_texts=texts,
                                ecosystem="pypi" if mutation == "pypi" else "cargo")
    failures, decision, _ = gate.evaluate_dependency_license(evidence, row["package"], selection)
    assert (decision.allowed and not failures) == (mutation is None)
    if mutation == "apache-choice":
        assert policy.LICENSE_TEXT_MISSING in {failure.code for failure in failures}


@pytest.mark.parametrize("mutation", [None, "checksum", "subject", "filename", "template", "no-apache",
                                      "changed-apache", "mit-choice", "no-choice", "pypi", "denied"])
def test_unarray_template_is_only_reference_for_exact_apache_choice(mutation):
    row = next(r for r in json.loads((ROOT / "reference_provenance.json").read_text())
               if r["package"] == "unarray@0.1.4")
    template = TEXTS[row["fixture"]]
    assert hashlib.sha256(template.encode()).hexdigest() == row["raw_sha256"]
    assert policy.recognize_license_text(template) is None
    apache = TEXTS[row["required_grant_fixture"]]
    assert policy.recognize_license_text(apache) == frozenset({"Apache-2.0"})
    files = {row["member"]: template, "unarray-0.1.4/LICENSE-APACHE": apache}
    subject = "cargo/unarray@0.1.4"
    evidence = _python_evidence(ecosystem="cargo", license_expression="MIT OR Apache-2.0",
                                license_texts=files, source_sha256=row["artifact_sha256"])
    selection = {"chosen": "Apache-2.0", "rationale": "Read exact README and full Apache grant; retain template unchanged."}
    if mutation == "checksum":
        evidence["source_sha256"] = "0" * 64
    elif mutation == "subject":
        subject = "cargo/unarray@0.1.5"
    elif mutation == "filename":
        files["OTHER-MIT"] = files.pop(row["member"])
    elif mutation == "template":
        files[row["member"]] += "Commercial use prohibited."
    elif mutation == "no-apache":
        del files["unarray-0.1.4/LICENSE-APACHE"]
    elif mutation == "changed-apache":
        files["unarray-0.1.4/LICENSE-APACHE"] += "Commercial use prohibited."
    elif mutation == "mit-choice":
        selection["chosen"] = "MIT"
    elif mutation == "no-choice":
        selection = None
    elif mutation == "pypi":
        evidence["ecosystem"] = "pypi"
    elif mutation == "denied":
        files["EXTRA-LICENSE"] = "GNU GENERAL PUBLIC LICENSE Version 3"
    failures, decision, _ = gate.evaluate_dependency_license(evidence, subject, selection)
    assert (decision.allowed and not failures) == (mutation is None)
    assert policy.recognize_license_text(template) is None
