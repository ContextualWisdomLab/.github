"""Lock the exact-repository OpenCode enrollment for Four Pillars."""

from pathlib import Path

WORKFLOW_PATH = Path(".github/workflows/opencode-review-dispatch.yml")
TARGET_REPOSITORY = "ContextualWisdomLab/four-pillars"


def _workflow_text() -> str:
    """Return the privileged dispatcher source as UTF-8 text."""
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_four_pillars_is_explicitly_enrolled_without_replacing_dynamic_targets() -> None:
    """Keep the configurable allowlist and add Four Pillars as one exact target."""
    workflow = _workflow_text()

    assert "vars.OPENCODE_REPOSITORY_DISPATCH_TARGETS" in workflow
    assert TARGET_REPOSITORY in workflow
    assert "ALLOWED_DISPATCH_TARGETS:" in workflow


def test_dispatcher_retains_exact_match_and_fail_closed_target_validation() -> None:
    """Reject every repository absent from the comma-delimited exact allowlist."""
    workflow = _workflow_text()

    assert 'IFS=\',\' read -r -a allowed_dispatch_targets' in workflow
    assert '[ "$TARGET_REPOSITORY" = "$allowed_target" ]' in workflow
    assert 'if [ "$target_allowed" -ne 1 ]; then' in workflow
    assert "absent from the configured exact repository allowlist" in workflow
    assert "ContextualWisdomLab/*" not in workflow
