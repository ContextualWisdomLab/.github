"""Executable traceability contract for the Noema observed-probe doctoring."""

from pathlib import Path


DOCTORING = Path("docs/doctoring/noema-observed-defect-probe-taxonomy.md")


def test_observed_probe_doctoring_records_closed_taxonomy_and_claim_boundary() -> None:
    """Doctoring must retain every probe class and the no-superiority claim boundary."""
    text = DOCTORING.read_text(encoding="utf-8")
    for probe_kind in (
        "mutable_alias",
        "time_of_check_time_of_use",
        "execution_identity",
        "coercion_boundary",
        "test_oracle",
        "cross_contract",
        "authority_boundary",
        "dependency_context",
        "state_machine_race",
    ):
        assert f"`{probe_kind}`" in text
    assert "does not claim parity or superiority" in text
    assert "ContextualWisdomLab/noema#528" in text
    assert "33500648307" in text
