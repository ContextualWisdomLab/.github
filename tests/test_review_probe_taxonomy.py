"""Branch-complete unit tests for the observed review probe taxonomy."""

from __future__ import annotations

import pytest

from scripts.ci import review_probe_taxonomy as taxonomy


def valid_probe(kind: str = "mutable_alias") -> dict:
    fields = taxonomy.OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[kind]
    witnesses = {
        field: f"{field} records a concrete independently observed {kind} behavior"
        for field in fields
    }
    return {
        "probe_kind": kind,
        "hypothesis": "The changed invariant may fail under adversarial state.",
        "attack_or_counterexample": "Exercise a counterexample against the changed invariant.",
        "evidence": "; ".join(
            f"{field}={observation}" for field, observation in witnesses.items()
        ),
        "class_evidence": witnesses,
    }


def error(probe: dict) -> str:
    return taxonomy.observed_probe_class_evidence_error(probe, label="probe 1")


@pytest.mark.parametrize("value", ["1", "true", "YES", "on", " true "])
def test_observed_probe_taxonomy_required_truthy(monkeypatch, value):
    monkeypatch.setenv("REVIEW_TAXONOMY_TEST", value)
    assert taxonomy.observed_probe_taxonomy_required("REVIEW_TAXONOMY_TEST") is True


def test_observed_probe_taxonomy_required_false_when_unset_or_other(monkeypatch):
    monkeypatch.delenv("REVIEW_TAXONOMY_TEST", raising=False)
    assert taxonomy.observed_probe_taxonomy_required("REVIEW_TAXONOMY_TEST") is False
    monkeypatch.setenv("REVIEW_TAXONOMY_TEST", "0")
    assert taxonomy.observed_probe_taxonomy_required("REVIEW_TAXONOMY_TEST") is False


def test_canonical_observation_normalizes_whitespace_and_case():
    assert taxonomy.canonical_observation("  Mixed\n  CASE\ttext  ") == "mixed case text"


def test_valid_probe_has_no_error():
    assert error(valid_probe()) == ""


@pytest.mark.parametrize("kind", [[], "invented_class"])
def test_rejects_non_string_or_unknown_kind(kind):
    probe = valid_probe()
    probe["probe_kind"] = kind
    assert "requires probe_kind from the observed defect taxonomy" in error(probe)


@pytest.mark.parametrize("class_evidence", [[], {"alias_origin": "only one field"}])
def test_rejects_non_mapping_or_wrong_class_fields(class_evidence):
    probe = valid_probe()
    probe["class_evidence"] = class_evidence
    assert "must contain exactly" in error(probe)


@pytest.mark.parametrize("evidence", [None, "   "])
def test_rejects_missing_parent_evidence(evidence):
    probe = valid_probe()
    probe["evidence"] = evidence
    assert "requires parent evidence" in error(probe)


@pytest.mark.parametrize("observation", [123, "too short"])
def test_rejects_non_string_or_short_observation(observation):
    probe = valid_probe()
    probe["class_evidence"]["alias_origin"] = observation
    assert "alias_origin requires a concrete observation" in error(probe)


def test_rejects_vacuous_observation():
    probe = valid_probe()
    probe["class_evidence"]["alias_origin"] = "works as expected"
    probe["evidence"] += "; alias_origin=works as expected"
    assert "alias_origin is vacuous" in error(probe)


def test_rejects_three_word_generic_observation():
    probe = valid_probe()
    probe["class_evidence"]["alias_origin"] = "caller alias retained"
    probe["evidence"] += "; alias_origin=caller alias retained"
    assert "alias_origin is vacuous" in error(probe)


def test_rejects_hypothesis_restatement():
    probe = valid_probe()
    probe["class_evidence"]["alias_origin"] = probe["hypothesis"]
    probe["evidence"] += f"; alias_origin={probe['hypothesis']}"
    assert "cannot merely restate hypothesis or attack text" in error(probe)


def test_rejects_attack_restatement():
    probe = valid_probe()
    probe["class_evidence"]["alias_origin"] = probe["attack_or_counterexample"]
    probe["evidence"] += f"; alias_origin={probe['attack_or_counterexample']}"
    assert "cannot merely restate hypothesis or attack text" in error(probe)


def test_rejects_duplicate_semantic_observations():
    probe = valid_probe()
    duplicate = probe["class_evidence"]["alias_origin"]
    probe["class_evidence"]["mutation_attempt"] = duplicate
    probe["evidence"] += f"; mutation_attempt={duplicate}"
    assert "class_evidence observations must be distinct" in error(probe)


def test_rejects_observation_not_quoted_under_its_field():
    probe = valid_probe()
    probe["class_evidence"]["alias_origin"] = (
        "alias_origin records a replacement concrete caller-owned alias observation"
    )
    assert "must be quoted in probe evidence" in error(probe)
