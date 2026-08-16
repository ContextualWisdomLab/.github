"""Close branch coverage for blinded review-gold adjudication."""

from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SUPPORT_PATH = ROOT / "tests/test_opencode_review_adjudicate.py"
MODULE_PATH = ROOT / "scripts/ci/opencode_review_adjudicate.py"


def load_support() -> ModuleType:
    """Load the primary adjudicator test support without requiring a package."""
    spec = importlib.util.spec_from_file_location(
        "opencode_review_adjudicate_support", SUPPORT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


support = load_support()
adjudicate = support.adjudicate
case_identity = support.case_identity
valid_inputs = support.valid_inputs


def test_direct_module_load_registers_its_support_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A path-based invocation must make sibling validation modules importable."""
    module_dir = str(MODULE_PATH.parent)
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry != module_dir])

    spec = importlib.util.spec_from_file_location(
        "opencode_review_adjudicate_direct", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert sys.path[0] == module_dir


def test_adjudicator_helper_boundaries_reject_invalid_shapes_and_scalars() -> None:
    """Low-level adjudication helpers must reject unsupported JSON values."""
    with pytest.raises(adjudicate.AdjudicationError, match="must be an object"):
        adjudicate.object_value([], "object")
    with pytest.raises(adjudicate.AdjudicationError, match="must be an array"):
        adjudicate.array_value({}, "array")
    with pytest.raises(adjudicate.AdjudicationError, match="non-empty text"):
        adjudicate.text_value(" ", "text")
    with pytest.raises(adjudicate.AdjudicationError, match="must be boolean"):
        adjudicate.bool_value(1, "flag")
    with pytest.raises(adjudicate.AdjudicationError, match="commit SHA"):
        adjudicate.commit_sha_value("main", "head")
    with pytest.raises(adjudicate.AdjudicationError, match="sha256"):
        adjudicate.digest_value("sha256:invalid", "digest")
    with pytest.raises(adjudicate.AdjudicationError, match="duplicates"):
        adjudicate.unique_text_values(["same", "same"], "identifiers")


def test_case_and_finding_metadata_reject_invalid_repository_and_severity() -> None:
    """Source evidence must keep a valid repository coordinate and severity scale."""
    value = case_identity()
    value["repository"] = "invalid"
    with pytest.raises(adjudicate.AdjudicationError, match="owner/name"):
        adjudicate.validate_case(value, "case")

    expert_a, _, _ = valid_inputs()
    expert_a["findings"][0]["severity"] = "urgent"
    with pytest.raises(adjudicate.AdjudicationError, match="severity"):
        adjudicate.validate_expert(expert_a, "expert")


def test_expert_annotation_rejects_version_and_duplicate_finding_identity() -> None:
    """Expert records need the exact schema and unique local finding identifiers."""
    expert_a, _, _ = valid_inputs()
    expert_a["schema_version"] = "2.0"
    with pytest.raises(adjudicate.AdjudicationError, match="schema_version"):
        adjudicate.validate_expert(expert_a, "expert")

    expert_a, _, _ = valid_inputs()
    expert_a["findings"][1]["expert_finding_id"] = "a_shared"
    with pytest.raises(adjudicate.AdjudicationError, match="duplicates"):
        adjudicate.validate_expert(expert_a, "expert")


def test_decision_contract_rejects_invalid_outcome_and_incomplete_acceptance() -> None:
    """Accepted and rejected decisions must satisfy mutually exclusive evidence forms."""
    _, _, record = valid_inputs()
    record["decisions"][0]["outcome"] = "maybe"
    with pytest.raises(adjudicate.AdjudicationError, match="accept or reject"):
        adjudicate.validate_adjudication(record)

    _, _, record = valid_inputs()
    record["decisions"][0]["gold_finding_id"] = None
    with pytest.raises(adjudicate.AdjudicationError, match="gold_finding_id"):
        adjudicate.validate_adjudication(record)

    _, _, record = valid_inputs()
    record["decisions"][0]["severity"] = "urgent"
    with pytest.raises(adjudicate.AdjudicationError, match="severity"):
        adjudicate.validate_adjudication(record)

    _, _, record = valid_inputs()
    record["decisions"][2]["path"] = "scripts/ci/example.py"
    with pytest.raises(adjudicate.AdjudicationError, match="rejected.*evidence"):
        adjudicate.validate_adjudication(record)


def test_adjudication_record_rejects_version_and_empty_decisions() -> None:
    """The decision record must use the exact schema and contain reviewed outcomes."""
    _, _, record = valid_inputs()
    record["schema_version"] = "2.0"
    with pytest.raises(adjudicate.AdjudicationError, match="schema_version"):
        adjudicate.validate_adjudication(record)

    _, _, record = valid_inputs()
    record["decisions"] = []
    with pytest.raises(adjudicate.AdjudicationError, match="must not be empty"):
        adjudicate.validate_adjudication(record)


def test_uncovered_diagnostics_cover_each_expert_side() -> None:
    """Incomplete adjudication diagnostics must identify A-only and B-only omissions."""
    expert_a, expert_b, record = valid_inputs()
    record["decisions"] = [
        item
        for item in record["decisions"]
        if item["decision_id"] != "decision_a_only"
    ]
    with pytest.raises(adjudicate.AdjudicationError, match="expert A"):
        adjudicate.adjudicate_case(expert_a, expert_b, record)

    expert_a, expert_b, record = valid_inputs()
    record["decisions"] = [
        item
        for item in record["decisions"]
        if item["decision_id"] != "decision_b_rejected"
    ]
    with pytest.raises(adjudicate.AdjudicationError, match="expert B"):
        adjudicate.adjudicate_case(expert_a, expert_b, record)


def test_load_json_wraps_syntax_and_filesystem_errors(tmp_path: Path) -> None:
    """Malformed or unavailable evidence files must return bounded stable errors."""
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{")
    with pytest.raises(adjudicate.AdjudicationError, match="cannot load"):
        adjudicate.load_json(malformed)
    with pytest.raises(adjudicate.AdjudicationError, match="cannot load"):
        adjudicate.load_json(tmp_path / "absent.json")


def test_adjudicator_module_entrypoint_uses_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct script execution must route through the tested adjudicator CLI."""
    expert_a, expert_b, decision_record = valid_inputs()
    a_path = tmp_path / "a.json"
    b_path = tmp_path / "b.json"
    d_path = tmp_path / "d.json"
    output = tmp_path / "gold.json"
    for path, value in (
        (a_path, expert_a),
        (b_path, expert_b),
        (d_path, decision_record),
    ):
        path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            str(MODULE_PATH),
            "--expert-a",
            str(a_path),
            "--expert-b",
            str(b_path),
            "--adjudication",
            str(d_path),
            "--output",
            str(output),
        ],
    )
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(MODULE_PATH), run_name="__main__")
    assert output.exists()
