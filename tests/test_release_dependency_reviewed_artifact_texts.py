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
