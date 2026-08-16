"""Tests for blinded expert-gold code-review adjudication."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/ci/opencode_review_adjudicate.py"


def load_module() -> ModuleType:
    """Load the exact adjudicator module without package import side effects."""
    spec = importlib.util.spec_from_file_location(
        "opencode_review_adjudicate", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adjudicate = load_module()


def case_identity() -> dict[str, Any]:
    """Build one immutable review case identity shared by every evidence record."""
    return {
        "case_id": "case_001",
        "repository": "ContextualWisdomLab/example",
        "pull_request_number": 42,
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "diff_sha256": f"sha256:{'c' * 64}",
        "context_sha256": f"sha256:{'d' * 64}",
    }


def source_finding(identifier: str, *, line: int = 12) -> dict[str, Any]:
    """Build one complete expert-discovered source defect."""
    return {
        "expert_finding_id": identifier,
        "path": "scripts/ci/example.py",
        "line": line,
        "defect_class": "correctness",
        "severity": "high",
        "trigger": "The input contains a duplicate exact-head identity.",
        "impact": "The benchmark counts one pull request twice.",
        "root_cause": "The identity set is not checked before aggregation.",
        "fix_direction": "Reject duplicate repository, PR, and head tuples.",
        "regression_target": "Add a duplicate exact-head fixture to the sampler tests.",
    }


def expert(
    annotation_id: str, expert_id: str, findings: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build one blinded independent expert annotation."""
    return {
        "schema_version": "1.0",
        "annotation_id": annotation_id,
        "expert_id": expert_id,
        "case": case_identity(),
        "reviewer_outputs_hidden": True,
        "full_repository_context_reviewed": True,
        "no_additional_findings": True,
        "findings": findings,
    }


def decision(
    identifier: str,
    *,
    expert_a_ids: list[str],
    expert_b_ids: list[str],
    outcome: str,
    gold_id: str | None,
    line: int | None = 12,
) -> dict[str, Any]:
    """Build one accepted or rejected blinded adjudication decision."""
    accepted = outcome == "accept"
    return {
        "decision_id": identifier,
        "expert_a_finding_ids": expert_a_ids,
        "expert_b_finding_ids": expert_b_ids,
        "outcome": outcome,
        "gold_finding_id": gold_id,
        "path": "scripts/ci/example.py" if accepted else None,
        "line": line if accepted else None,
        "defect_class": "correctness" if accepted else None,
        "severity": "high" if accepted else None,
        "trigger": "The input contains a duplicate exact-head identity."
        if accepted
        else None,
        "impact": "The benchmark counts one pull request twice." if accepted else None,
        "root_cause": "The identity set is not checked before aggregation."
        if accepted
        else None,
        "fix_direction": "Reject duplicate repository, PR, and head tuples."
        if accepted
        else None,
        "regression_target": "Add a duplicate exact-head fixture to the sampler tests."
        if accepted
        else None,
        "reason": "Independent experts and source evidence support this defect."
        if accepted
        else "The report describes intended behavior rather than a defect.",
    }


def adjudication(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    """Build one identity-blinded adjudication record."""
    return {
        "schema_version": "1.0",
        "adjudication_id": "adjudication_001",
        "adjudicator_id": "adjudicator_gamma",
        "case": case_identity(),
        "reviewer_identities_hidden": True,
        "decisions": decisions,
    }


def valid_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Build two experts and complete decisions covering every source finding once."""
    expert_a = expert(
        "annotation_a",
        "expert_alpha",
        [source_finding("a_shared"), source_finding("a_only", line=30)],
    )
    expert_b = expert(
        "annotation_b",
        "expert_beta",
        [source_finding("b_shared"), source_finding("b_rejected", line=44)],
    )
    decisions = [
        decision(
            "decision_shared",
            expert_a_ids=["a_shared"],
            expert_b_ids=["b_shared"],
            outcome="accept",
            gold_id="gold_shared",
        ),
        decision(
            "decision_a_only",
            expert_a_ids=["a_only"],
            expert_b_ids=[],
            outcome="accept",
            gold_id="gold_a_only",
            line=30,
        ),
        decision(
            "decision_b_rejected",
            expert_a_ids=[],
            expert_b_ids=["b_rejected"],
            outcome="reject",
            gold_id=None,
            line=None,
        ),
    ]
    return expert_a, expert_b, adjudication(decisions)


def test_adjudication_freezes_complete_gold_with_receipts_and_agreement() -> None:
    """Accepted findings and all source receipts must form one deterministic freeze."""
    expert_a, expert_b, decision_record = valid_inputs()
    first = adjudicate.adjudicate_case(expert_a, expert_b, decision_record)
    second = adjudicate.adjudicate_case(expert_a, expert_b, decision_record)
    assert first == second
    assert [item["finding_id"] for item in first["gold_findings"]] == [
        "gold_a_only",
        "gold_shared",
    ]
    assert first["agreement_metrics"] == {
        "expert_a_findings": 2,
        "expert_b_findings": 2,
        "accepted_gold_findings": 2,
        "accepted_by_both_experts": 1,
        "accepted_from_expert_a_only": 1,
        "accepted_from_expert_b_only": 0,
        "rejected_source_findings": 1,
    }
    assert first["freeze_sha256"].startswith("sha256:")
    assert {item["expert_id"] for item in first["annotation_receipts"]} == {
        "expert_alpha",
        "expert_beta",
    }
    assert all(
        item["annotation_sha256"].startswith("sha256:")
        for item in first["annotation_receipts"]
    )
    assert first["adjudication_receipt"]["adjudication_sha256"].startswith(
        "sha256:"
    )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda a, b, d: a.update({"unexpected": True}),
            "unknown fields",
        ),
        (
            lambda a, b, d: a["case"].update({"unexpected": True}),
            "unknown fields",
        ),
        (
            lambda a, b, d: a["findings"][0].update({"unexpected": True}),
            "unknown fields",
        ),
        (
            lambda a, b, d: d["decisions"][0].update({"unexpected": True}),
            "unknown fields",
        ),
        (
            lambda a, b, d: a.update({"reviewer_outputs_hidden": False}),
            "reviewer_outputs_hidden",
        ),
        (
            lambda a, b, d: b.update({"full_repository_context_reviewed": False}),
            "full_repository_context_reviewed",
        ),
        (
            lambda a, b, d: a.update({"no_additional_findings": False}),
            "no_additional_findings",
        ),
        (
            lambda a, b, d: d.update({"reviewer_identities_hidden": False}),
            "reviewer_identities_hidden",
        ),
    ],
)
def test_adjudicator_rejects_extensible_or_unblinded_evidence(
    mutate: Any, message: str
) -> None:
    """Every annotation and decision layer must fail closed and preserve blinding."""
    expert_a, expert_b, decision_record = valid_inputs()
    mutate(expert_a, expert_b, decision_record)
    with pytest.raises(adjudicate.AdjudicationError, match=message):
        adjudicate.adjudicate_case(expert_a, expert_b, decision_record)


def test_adjudicator_requires_exact_same_case_identity() -> None:
    """Expert and adjudicator evidence must bind to one immutable base and head."""
    expert_a, expert_b, decision_record = valid_inputs()
    expert_b["case"]["head_sha"] = "e" * 40
    with pytest.raises(adjudicate.AdjudicationError, match="case identity"):
        adjudicate.adjudicate_case(expert_a, expert_b, decision_record)


def test_adjudicator_requires_independent_pseudonymous_roles() -> None:
    """The two experts and adjudicator must be three distinct pseudonymous actors."""
    expert_a, expert_b, decision_record = valid_inputs()
    expert_b["expert_id"] = expert_a["expert_id"]
    with pytest.raises(adjudicate.AdjudicationError, match="distinct"):
        adjudicate.adjudicate_case(expert_a, expert_b, decision_record)

    expert_a, expert_b, decision_record = valid_inputs()
    decision_record["adjudicator_id"] = expert_a["expert_id"]
    with pytest.raises(adjudicate.AdjudicationError, match="distinct"):
        adjudicate.adjudicate_case(expert_a, expert_b, decision_record)


def test_adjudicator_requires_every_source_finding_exactly_once() -> None:
    """No expert discovery may be dropped or reused across decisions."""
    expert_a, expert_b, decision_record = valid_inputs()
    decision_record["decisions"].pop()
    with pytest.raises(adjudicate.AdjudicationError, match="uncovered"):
        adjudicate.adjudicate_case(expert_a, expert_b, decision_record)

    expert_a, expert_b, decision_record = valid_inputs()
    decision_record["decisions"][1]["expert_a_finding_ids"] = ["a_shared"]
    with pytest.raises(adjudicate.AdjudicationError, match="more than once"):
        adjudicate.adjudicate_case(expert_a, expert_b, decision_record)

    expert_a, expert_b, decision_record = valid_inputs()
    decision_record["decisions"][0]["expert_a_finding_ids"] = ["unknown"]
    with pytest.raises(adjudicate.AdjudicationError, match="unknown expert"):
        adjudicate.adjudicate_case(expert_a, expert_b, decision_record)


def test_adjudicator_rejects_empty_decisions_and_duplicate_ids() -> None:
    """Every decision needs source evidence and stable unique identifiers."""
    expert_a, expert_b, decision_record = valid_inputs()
    decision_record["decisions"][0]["expert_a_finding_ids"] = []
    decision_record["decisions"][0]["expert_b_finding_ids"] = []
    with pytest.raises(adjudicate.AdjudicationError, match="at least one"):
        adjudicate.adjudicate_case(expert_a, expert_b, decision_record)

    expert_a, expert_b, decision_record = valid_inputs()
    decision_record["decisions"][1]["decision_id"] = "decision_shared"
    with pytest.raises(adjudicate.AdjudicationError, match="duplicates"):
        adjudicate.adjudicate_case(expert_a, expert_b, decision_record)

    expert_a, expert_b, decision_record = valid_inputs()
    decision_record["decisions"][1]["gold_finding_id"] = "gold_shared"
    with pytest.raises(adjudicate.AdjudicationError, match="gold_finding_id"):
        adjudicate.adjudicate_case(expert_a, expert_b, decision_record)


def test_accept_and_reject_contracts_are_mutually_exclusive() -> None:
    """Accepted gold needs complete source evidence; rejected reports must not mint gold."""
    expert_a, expert_b, decision_record = valid_inputs()
    decision_record["decisions"][0]["path"] = None
    with pytest.raises(adjudicate.AdjudicationError, match="accepted.*path"):
        adjudicate.adjudicate_case(expert_a, expert_b, decision_record)

    expert_a, expert_b, decision_record = valid_inputs()
    rejected = decision_record["decisions"][2]
    rejected["gold_finding_id"] = "gold_invalid"
    with pytest.raises(adjudicate.AdjudicationError, match="rejected.*gold"):
        adjudicate.adjudicate_case(expert_a, expert_b, decision_record)


def test_adjudicator_rejects_unsafe_path_line_and_scalar_types() -> None:
    """Gold evidence must remain source-relative, positively anchored, and type strict."""
    expert_a, expert_b, decision_record = valid_inputs()
    decision_record["decisions"][0]["path"] = "../secret"
    with pytest.raises(adjudicate.AdjudicationError, match="relative source path"):
        adjudicate.adjudicate_case(expert_a, expert_b, decision_record)

    expert_a, expert_b, decision_record = valid_inputs()
    decision_record["decisions"][0]["line"] = 0
    with pytest.raises(adjudicate.AdjudicationError, match="positive integer"):
        adjudicate.adjudicate_case(expert_a, expert_b, decision_record)

    expert_a, expert_b, decision_record = valid_inputs()
    expert_a["case"]["pull_request_number"] = True
    with pytest.raises(adjudicate.AdjudicationError, match="integer"):
        adjudicate.adjudicate_case(expert_a, expert_b, decision_record)


def test_load_json_rejects_duplicate_keys_and_nonfinite_numbers(tmp_path: Path) -> None:
    """Annotation files must reject duplicate keys and non-standard JSON constants."""
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":"1.0","schema_version":"1.0"}')
    with pytest.raises(adjudicate.AdjudicationError, match="duplicate JSON key"):
        adjudicate.load_json(duplicate)

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"line": Infinity}')
    with pytest.raises(adjudicate.AdjudicationError, match="non-finite JSON number"):
        adjudicate.load_json(nonfinite)


def test_cli_writes_atomic_frozen_case_and_rejects_invalid_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI must publish one atomic freeze or return a stable validation status."""
    expert_a, expert_b, decision_record = valid_inputs()
    a_path = tmp_path / "a.json"
    b_path = tmp_path / "b.json"
    d_path = tmp_path / "d.json"
    output = tmp_path / "nested" / "gold.json"
    for path, value in (
        (a_path, expert_a),
        (b_path, expert_b),
        (d_path, decision_record),
    ):
        path.write_text(json.dumps(value), encoding="utf-8")
    assert (
        adjudicate.main(
            [
                "--expert-a",
                str(a_path),
                "--expert-b",
                str(b_path),
                "--adjudication",
                str(d_path),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text(encoding="utf-8"))["gold_findings"]
    assert not output.with_name(f".{output.name}.tmp").exists()

    decision_record["case"]["head_sha"] = "e" * 40
    d_path.write_text(json.dumps(decision_record), encoding="utf-8")
    assert (
        adjudicate.main(
            [
                "--expert-a",
                str(a_path),
                "--expert-b",
                str(b_path),
                "--adjudication",
                str(d_path),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert "adjudication evidence rejected" in capsys.readouterr().err


def test_public_adjudicator_callables_have_docstrings() -> None:
    """Every production class and function must remain beginner-readable."""
    missing = [
        name
        for name, value in vars(adjudicate).items()
        if not name.startswith("_")
        and (isinstance(value, type) or callable(value))
        and getattr(value, "__module__", None) == adjudicate.__name__
        and not getattr(value, "__doc__", None)
    ]
    assert missing == []
