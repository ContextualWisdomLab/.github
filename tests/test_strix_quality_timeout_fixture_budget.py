from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "strix-changed-path-quality-ci.yml"


def _named_step(workflow: str, name: str) -> str:
    """Return one exact named workflow step without loading workflow YAML tags."""
    marker = f"      - name: {name}\n"
    start = workflow.index(marker)
    try:
        end = workflow.index("\n      - name:", start + len(marker))
    except ValueError:
        end = len(workflow)
    return workflow[start:end]


def test_strix_quality_uses_short_fake_process_timeouts() -> None:
    """Keep deterministic timeout fixtures well inside the quality-job budget."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    step = _named_step(workflow, "Verify exact-head path policy and syntax")

    assert 'STRIX_TEST_PROCESS_TIMEOUT_SECONDS: "3"' in step
    assert 'STRIX_TEST_FAKE_SLEEP_SECONDS: "5"' in step
    assert "bash scripts/ci/test_strix_quick_gate.sh" in step


def test_strix_quality_trigger_includes_fixture_contract_paths() -> None:
    """Keep fixture behavior and doctoring changes inside the quality trigger."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    trigger = workflow[: workflow.index("\njobs:")]

    assert "docs/doctoring/strix-quality-timeout-fixtures.md" in trigger
    assert "tests/test_strix_quality_timeout_fixture_budget.py" in trigger
    assert "docs/doctoring/strix-model-behavior-error.md" in trigger
    assert "tests/test_strix_model_behavior_error.py" in trigger


def test_strix_quality_keeps_real_scanner_budgets_out_of_fixture_overrides() -> None:
    """Fixture acceleration must not weaken production Strix scanner timeouts."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    step = _named_step(workflow, "Verify exact-head path policy and syntax")

    assert "STRIX_PROCESS_TIMEOUT_SECONDS:" not in step
    assert "STRIX_TOTAL_TIMEOUT_SECONDS:" not in step
    assert "LLM_TIMEOUT:" not in step
