"""Regression contract for request-changes finding/probe binding.

A formal request-changes verdict is not structurally reviewable when findings and confirmed
adversarial probes are only parallel arrays. The response schema must make the relationship explicit
so the model and contextual-orchestrator repair pass can reason about the same contract that the local
validator enforces.
"""

from scripts.ci import noema_review_gate as noema


def test_probe_schema_carries_explicit_published_finding_binding() -> None:
    """Every probe must expose a schema-declared finding binding coordinate."""
    schema = noema._noema_verdict_json_schema(required_probes=2)
    probe_schema = schema["properties"]["adversarial_validation"]["properties"]["probes"]["items"]

    assert "finding_index" in probe_schema["properties"]
    assert "finding_index" in probe_schema["required"]
    assert probe_schema["properties"]["finding_index"] == {
        "type": ["integer", "null"],
        "minimum": 0,
    }


def test_request_changes_prompt_explains_confirmed_probe_binding() -> None:
    """The model prompt must explain how the schema link is populated for each probe outcome."""
    source = noema.__loader__.get_source(noema.__name__)
    assert source is not None
    assert "confirmed probe must set finding_index" in source
    assert "falsified probe must set finding_index to null" in source
