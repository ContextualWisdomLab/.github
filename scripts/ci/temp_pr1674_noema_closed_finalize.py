#!/usr/bin/env python3
"""One-shot finalizer for PR #1674's closed-current-head Noema contract.

The script records a regression RED against the current production workflow,
then adds an explicit proceed/skip output so downstream review/setup/publication
steps cannot run after a PR closes on the exact expected head. It also removes
the abandoned Strix materializer lane and this helper from the published tree.
"""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/noema-review.yml"
TESTS = ROOT / "tests/test_opencode_workflow_shell_syntax.py"
BASELINE = ROOT / "docs/product-technical-gap-baseline.md"
TEMP_WORKFLOW = ROOT / ".github/workflows/_temp_pr1674_strix_live_state_repair.yml"
TEMP_STRIX_TEST = ROOT / "tests/test_strix_repository_dispatch_live_state.py"
TEMP_TRIGGER = ROOT / ".github/.pr1674-repair-trigger"
SELF = Path(__file__).resolve()

TEST = r'''


def test_noema_closed_current_head_gates_every_downstream_review_step():
    """Closed exact-head Noema targets must skip all later setup and publication."""
    from pathlib import Path
    import re

    text = Path('.github/workflows/noema-review.yml').read_text(encoding='utf-8')
    validation = re.search(
        r"      - name: Validate current pull request head\n(?P<body>.*?)(?=\n      - name: Resolve Noema target repository visibility)",
        text,
        re.S,
    )
    assert validation is not None
    body = validation.group('body')
    assert "        id: live_pr\n" in body
    assert 'echo "proceed=false" >>"$GITHUB_OUTPUT"' in body
    assert 'echo "proceed=true" >>"$GITHUB_OUTPUT"' in body

    guarded_steps = (
        'Resolve Noema target repository visibility',
        'Provision contextual-orchestrator review sidecar',
        'Prepare Noema model verdict',
        'Refresh repository-scoped Noema GitHub App token for publication',
        'Publish prepared Noema verdict on the exact live head',
    )
    for step_name in guarded_steps:
        step = re.search(
            rf"      - name: {re.escape(step_name)}\n(?P<body>.*?)(?=\n      - name:|\Z)",
            text,
            re.S,
        )
        assert step is not None, step_name
        assert "steps.live_pr.outputs.proceed == 'true'" in step.group('body'), step_name
'''


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one repository command with text output."""
    return subprocess.run(cmd, cwd=ROOT, check=check, text=True)


def add_regression_and_require_red() -> None:
    """Append the workflow-level contract and prove it fails before production repair."""
    text = TESTS.read_text(encoding="utf-8")
    marker = "def test_noema_closed_current_head_gates_every_downstream_review_step"
    if marker in text:
        raise RuntimeError("PR1674 final regression already exists on the input head")
    TESTS.write_text(text + TEST, encoding="utf-8")
    red = run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_opencode_workflow_shell_syntax.py",
            "-q",
            "-k",
            "noema_closed_current_head_gates_every_downstream_review_step",
        ],
        check=False,
    )
    if red.returncode == 0:
        raise RuntimeError("PR1674 regression unexpectedly passed before the production repair")
    print(f"PR1674_RED_CONFIRMED pytest_exit={red.returncode}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace exactly one bounded source fragment."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def repair_workflow() -> None:
    """Add explicit live-target proceed authority and gate every later review step."""
    text = WORKFLOW.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "      - name: Validate current pull request head\n        if: env.PR_NUMBER != ''\n",
        "      - name: Validate current pull request head\n        id: live_pr\n        if: env.PR_NUMBER != ''\n",
        "validation id",
    )
    text = replace_once(
        text,
        "            printf '::notice::Noema review target closed on its current head (state=%s); nothing left to review, skipping.\\n' \"$live_state\"\n            exit 0\n          fi\n\n      - name: Resolve Noema target repository visibility\n",
        "            printf '::notice::Noema review target closed on its current head (state=%s); nothing left to review, skipping.\\n' \"$live_state\"\n            echo \"proceed=false\" >>\"$GITHUB_OUTPUT\"\n            exit 0\n          fi\n          echo \"proceed=true\" >>\"$GITHUB_OUTPUT\"\n\n      - name: Resolve Noema target repository visibility\n",
        "proceed outputs",
    )
    text = replace_once(
        text,
        "      - name: Resolve Noema target repository visibility\n        if: env.PR_NUMBER != ''\n",
        "      - name: Resolve Noema target repository visibility\n        if: env.PR_NUMBER != '' && steps.live_pr.outputs.proceed == 'true'\n",
        "visibility guard",
    )
    text = replace_once(
        text,
        "      - name: Provision contextual-orchestrator review sidecar\n        if: env.PR_NUMBER != ''\n",
        "      - name: Provision contextual-orchestrator review sidecar\n        if: env.PR_NUMBER != '' && steps.live_pr.outputs.proceed == 'true'\n",
        "sidecar guard",
    )
    text = replace_once(
        text,
        "      - name: Prepare Noema model verdict\n        if: env.PR_NUMBER != ''\n",
        "      - name: Prepare Noema model verdict\n        if: env.PR_NUMBER != '' && steps.live_pr.outputs.proceed == 'true'\n",
        "prepare guard",
    )
    text = replace_once(
        text,
        "        if: env.PR_NUMBER != '' && steps.noema_prepare.outputs.prepared == 'true' && steps.noema_credential.outputs.source == 'github-app'\n",
        "        if: env.PR_NUMBER != '' && steps.live_pr.outputs.proceed == 'true' && steps.noema_prepare.outputs.prepared == 'true' && steps.noema_credential.outputs.source == 'github-app'\n",
        "publication token guard",
    )
    text = replace_once(
        text,
        "        if: env.PR_NUMBER != '' && steps.noema_prepare.outputs.prepared == 'true'\n",
        "        if: env.PR_NUMBER != '' && steps.live_pr.outputs.proceed == 'true' && steps.noema_prepare.outputs.prepared == 'true'\n",
        "publication guard",
    )
    WORKFLOW.write_text(text, encoding="utf-8")


def repair_traceability() -> None:
    """Use repository-qualified PR references required by the baseline contract."""
    text = BASELINE.read_text(encoding="utf-8")
    text = text.replace("`.github#1672`", "`ContextualWisdomLab/.github#1672`")
    BASELINE.write_text(text, encoding="utf-8")


def remove_abandoned_lane() -> None:
    """Remove temporary Strix/future-state artifacts and this one-shot finalizer."""
    for path in (TEMP_WORKFLOW, TEMP_STRIX_TEST, TEMP_TRIGGER, SELF):
        if path.exists():
            path.unlink()


def main() -> int:
    """Run RED, apply minimal Noema repair, fix traceability, and retire temp artifacts."""
    add_regression_and_require_red()
    repair_workflow()
    repair_traceability()
    remove_abandoned_lane()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
