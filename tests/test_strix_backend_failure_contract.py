from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "strix.yml"


def _workflow_text() -> str:
    """Read the trusted Strix workflow used by the required security gate."""
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_caido_startup_failure_is_classified_as_infrastructure() -> None:
    """Neutralize only the known local Caido startup outage, not findings."""
    workflow = _workflow_text()
    signal_line = next(
        line for line in workflow.splitlines() if "backend_unavailable_signal=" in line
    )

    assert "loginAsGuest failed" in signal_line
    assert r"127\.0\.0\.1 port 48080" in signal_line
    assert '&& ! grep -Eiq "$reported_vulnerability_signal"' in workflow


def test_strix_warning_names_scanner_runtime_as_well_as_llm() -> None:
    """Tell operators which infrastructure boundary failed and where to inspect it."""
    workflow = _workflow_text()

    assert "Strix infrastructure unavailable" in workflow
    assert "LLM backend or scanner runtime" in workflow
