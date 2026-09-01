#!/usr/bin/env python3
"""Resume PR #1591 escalation repair after retiring stale predecessor contracts."""

from __future__ import annotations

from pathlib import Path
import re

from scripts.ci import source_fix_1591_escalation_order as fix


def repair_adr_contract() -> None:
    """Keep the accepted sidecar pin and exact no-timeout language executable tests require."""
    path = Path("docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md")
    text = path.read_text(encoding="utf-8")
    pin = "8cd99f139915131ba0239bce12a5d6a5fd85394e"
    if pin not in text:
        raise SystemExit("accepted sidecar pin disappeared from ADR-0003")
    old = (
        "including initial completion probes, warm-up, retry, repair verdicts, "
        "or substantive review calls."
    )
    new = (
        "including initial completion ping, warm-up, retry, repair verdicts, "
        "or substantive review calls."
    )
    if old in text:
        text = text.replace(old, new, 1)
    if "initial completion ping" not in text:
        raise SystemExit("ADR-0003 no-timeout contract lacks initial completion ping")
    path.write_text(text, encoding="utf-8")


def update_tests_and_docs() -> None:
    """Remove the obsolete shared-cap contract before applying replacement tests."""
    path = Path("tests/test_contextual_orchestrator_review_runtime_preflight.py")
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r'''def test_escalation_budget_is_shared_and_bounded_across_candidates\(\) -> None:\n.*?(?=\n@pytest\.mark\.parametrize\()''',
        re.DOTALL,
    )
    text, count = pattern.subn("", text, count=1)
    if count != 1 and "test_escalation_budget_is_shared_and_bounded_across_candidates" in text:
        raise SystemExit("obsolete shared escalation-cap regression changed unexpectedly")
    path.write_text(text, encoding="utf-8")
    fix.update_tests_and_docs_original()
    repair_adr_contract()


def commit_and_push(message: str) -> None:
    """Skip an already-published TDD phase, otherwise publish normally."""
    staged = fix.run("git", "diff", "--cached", "--quiet", check=False)
    if staged.returncode == 0:
        return
    fix.commit_and_push_original(message)


fix.update_tests_and_docs_original = fix.update_tests_and_docs
fix.commit_and_push_original = fix.commit_and_push
fix.update_tests_and_docs = update_tests_and_docs
fix.commit_and_push = commit_and_push
fix.main()
