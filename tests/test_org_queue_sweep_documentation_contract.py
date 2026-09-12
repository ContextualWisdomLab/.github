"""Contract for the superseded organization queue-sweep runbook."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = ROOT / "docs" / "doctoring" / "org-queue-sweep-rotation.md"


def test_runbook_marks_removed_queue_hygiene_as_historical() -> None:
    """The runbook must not describe removed repository-wide inventory as current."""
    source = RUNBOOK.read_text(encoding="utf-8")

    assert "Superseded for queue hygiene" in source
    assert "does not repeat an Actions inventory per repository" in source
    assert "#1878" in source
    assert "historical operational evidence" in source
