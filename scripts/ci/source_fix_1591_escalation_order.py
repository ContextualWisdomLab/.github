#!/usr/bin/env python3
"""Remove the order-sensitive shared preflight escalation cap on PR #1591."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess

SOURCE = Path("scripts/ci/contextual_orchestrator_review_launcher.py")
TESTS = Path("tests/test_contextual_orchestrator_review_runtime_preflight.py")
CHANGELOG = Path("CHANGELOG.md")
BASELINE = Path("docs/product-technical-gap-baseline.md")


def run(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Run one deterministic repository command."""
    return subprocess.run(
        args,
        check=check,
        text=True,
        capture_output=capture,
        env={**os.environ, "PYTHONPATH": "."},
    )


def commit_and_push(message: str) -> None:
    """Publish one non-force TDD increment on the canonical branch."""
    run("git", "diff", "--cached", "--check")
    run("git", "commit", "-m", message)
    run("git", "push", "origin", f"HEAD:{os.environ['TARGET_BRANCH']}")


def add_red_test() -> None:
    """Add a regression proving later candidates cannot lose escalation by order."""
    text = TESTS.read_text(encoding="utf-8")
    if "test_every_budget_starved_route_gets_its_own_escalation" in text:
        return
    anchor = "\ndef test_preflight_keeps_more_than_twelve_admitted_primary_routes() -> None:\n"
    if text.count(anchor) != 1:
        raise SystemExit("preflight cardinality test anchor changed unexpectedly")
    red = r'''

def test_every_budget_starved_route_gets_its_own_escalation() -> None:
    """Catalog order cannot deny a candidate its own evidence-bearing retry."""
    namespace = _load_launcher()
    preflight = namespace["_preflight_review_agents"]
    agents = [
        SimpleNamespace(
            id=f"starved_{index}", provider_name="openrouter", model=f"starved/{index}"
        )
        for index in range(6)
    ]
    starved = {
        "choices": [{"finish_reason": "length", "message": {"content": ""}}]
    }
    client = _ProbeClient({agent.id: dict(starved) for agent in agents})

    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight(agents, client=client)

    rows = failure.value.report["routes"]
    assert [row["attempts"] for row in rows] == [2] * len(agents)
    assert all(row.get("error_type") != "escalation_budget_exhausted" for row in rows)
    assert failure.value.report["escalations_used"] == len(agents)
    assert len(client.calls) == 2 * len(agents)

'''
    TESTS.write_text(text.replace(anchor, red + anchor, 1), encoding="utf-8")


def verify_red() -> None:
    """Prove the current first-come-first-served cap violates the regression."""
    result = run(
        "python3",
        "-m",
        "pytest",
        "-q",
        f"{TESTS}::test_every_budget_starved_route_gets_its_own_escalation",
        check=False,
        capture=True,
    )
    output = result.stdout + result.stderr
    print(output, flush=True)
    if result.returncode != 1 or "1 failed" not in output:
        raise SystemExit("expected one genuine RED escalation-order regression")


def patch_source() -> None:
    """Give each budget-starved candidate one independent evidence retry."""
    text = SOURCE.read_text(encoding="utf-8")
    cap_block = '''# Shared cap on how many candidates in one preflight run may use the\n# escalation retry above. It bounds request count, never model response time.\nREVIEW_PREFLIGHT_MAX_ESCALATIONS = 4\n'''
    if text.count(cap_block) != 1:
        raise SystemExit("shared escalation cap block changed unexpectedly")
    text = text.replace(cap_block, "", 1)
    old_signature = '''def _preflight_review_agents(\n    agents: list[object], *, client: Any, escalations_used: int = 0\n) -> tuple[list[object], dict[str, object]]:\n'''
    new_signature = '''def _preflight_review_agents(\n    agents: list[object], *, client: Any\n) -> tuple[list[object], dict[str, object]]:\n'''
    if text.count(old_signature) != 1:
        raise SystemExit("preflight signature changed unexpectedly")
    text = text.replace(old_signature, new_signature, 1)
    text = text.replace(
        '''    viable: list[object] = []\n    routes: list[dict[str, object]] = []\n''',
        '''    viable: list[object] = []\n    routes: list[dict[str, object]] = []\n    escalations_used = 0\n''',
        1,
    )
    cap_branch = re.compile(
        r'''        # KNOWN, ACCEPTED, TRACKED LIMITATION on the escalations_used >=\n.*?        if not budget_signature or escalations_used >= REVIEW_PREFLIGHT_MAX_ESCALATIONS:\n            row\["status"\] = "rejected"\n            row\["error_type"\] = \(\n                "invalid_chat_response" if not budget_signature else "escalation_budget_exhausted"\n            \)\n            routes\.append\(row\)\n            continue\n''',
        re.DOTALL,
    )
    replacement = '''        if not budget_signature:\n            row["status"] = "rejected"\n            row["error_type"] = "invalid_chat_response"\n            routes.append(row)\n            continue\n'''
    text, count = cap_branch.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit("order-sensitive escalation branch changed unexpectedly")
    if '        "escalation_budget": REVIEW_PREFLIGHT_MAX_ESCALATIONS,\n' not in text:
        raise SystemExit("preflight report escalation budget field missing")
    text = text.replace('        "escalation_budget": REVIEW_PREFLIGHT_MAX_ESCALATIONS,\n', "", 1)

    # Keep the useful two-stage fallback but stop carrying an admission-affecting
    # shared counter from primary order into fallback order.
    text = text.replace(
        '''        escalations_used = int(primary_error.report.get("escalations_used", 0))\n        try:\n            viable, report = _preflight_review_agents(\n                fallback_agents, client=client, escalations_used=escalations_used\n            )\n''',
        '''        try:\n            viable, report = _preflight_review_agents(\n                fallback_agents, client=client\n            )\n''',
        1,
    )
    if "escalations_used=escalations_used" in text:
        raise SystemExit("shared escalation state still crosses preflight stages")

    # Replace the stale docstring section that claimed a fixed shared budget.
    text = re.sub(
        r'''    The two stages share ADR-0005's one ``REVIEW_PREFLIGHT_MAX_ESCALATIONS``\n.*?    ``primary_attempt`` nests the primary stage's own report -- including its\n    own ``escalations_used`` -- whenever a fallback stage ran at all\.\n''',
        '''    Each candidate keeps the same two-attempt evidence contract used by\n    ``_preflight_review_agents``. A candidate that returns the explicit\n    budget-starvation signature receives exactly one larger-budget retry;\n    another candidate's earlier position cannot consume or deny that retry.\n    Primary and fallback reports preserve their own observed escalation counts\n    for audit without using those counts as admission authority.\n''',
        text,
        count=1,
        flags=re.DOTALL,
    )
    text = text.replace(
        '''    marked rejected -- bounded by a shared ``REVIEW_PREFLIGHT_MAX_ESCALATIONS``\n    counter, which the ``escalations_used`` argument carries forward across\n    calls (not per candidate, and not reset per call): a caller that probes\n    two stages of the same preflight run (e.g. ``_preflight_with_fallback``'s\n    primary and fallback stages) must pass the previous stage's ending count\n    back in here so the two stages share one budget instead of each getting\n    its own -- otherwise the computed worst-case bound this counter exists to\n    enforce silently doubles. Every other failure class (transport exception,\n''',
        '''    marked rejected. The retry decision is local to that candidate and\n    cannot be exhausted by earlier catalog entries. Every other failure class\n    (transport exception,\n''',
        1,
    )
    text = text.replace(
        '''        escalations_used: Escalations already spent earlier in this same\n            preflight run (e.g. by a prior stage), so the shared budget is\n            honored across calls rather than restarted at zero.\n\n''',
        "",
        1,
    )
    text = text.replace(
        '''        report's ``escalations_used`` is the running total including\n        ``escalations_used``'s starting value, so a caller chaining another\n        stage can pass it straight back in.\n''',
        '''        report's ``escalations_used`` is observed telemetry for this\n        stage only and never an admission quota.\n''',
        1,
    )
    if "REVIEW_PREFLIGHT_MAX_ESCALATIONS" in text or "escalation_budget_exhausted" in text:
        raise SystemExit("retired shared escalation authority remains in launcher")
    SOURCE.write_text(text, encoding="utf-8")


def update_tests_and_docs() -> None:
    """Replace the obsolete shared-budget contract and record the RCA."""
    text = TESTS.read_text(encoding="utf-8")
    pattern = re.compile(
        r'''def test_fallback_escalation_budget_is_shared_across_full_admitted_catalog\(\) -> None:\n.*?(?=\ndef test_every_budget_starved_route_gets_its_own_escalation\(\) -> None:)''',
        re.DOTALL,
    )
    replacement = r'''def test_fallback_escalation_is_independent_of_primary_catalog_order() -> None:
    """Primary starvation cannot consume a fallback candidate's own retry."""
    namespace = _load_launcher()
    preflight = namespace["_preflight_with_fallback"]
    primary_agents = [
        SimpleNamespace(id=f"primary_{index}", provider_name="openrouter", model="x/free")
        for index in range(6)
    ]
    fallback_agents = [
        SimpleNamespace(id=f"fallback_{index}", provider_name="openrouter", model="y/priced")
        for index in range(3)
    ]
    starved = {"choices": [{"finish_reason": "length", "message": {"content": ""}}]}
    client = _ProbeClient({agent.id: dict(starved) for agent in [*primary_agents, *fallback_agents]})

    with pytest.raises(namespace["ReviewPreflightError"]) as failure:
        preflight(primary_agents, fallback_agents, client=client)

    assert failure.value.report["escalations_used"] == len(fallback_agents)
    assert failure.value.report["primary_attempt"]["escalations_used"] == len(primary_agents)
    assert len(client.calls) == 2 * (len(primary_agents) + len(fallback_agents))
    assert all(
        row.get("error_type") != "escalation_budget_exhausted"
        for report in (failure.value.report["primary_attempt"], failure.value.report)
        for row in report["routes"]
    )


'''
    text, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit("shared-budget regression block changed unexpectedly")
    TESTS.write_text(text, encoding="utf-8")

    changelog = CHANGELOG.read_text(encoding="utf-8")
    entry = "- Remove the shared first-come-first-served review preflight escalation quota. Every route that emits the explicit budget-starvation signature now receives its own single evidence-bearing escalation, so catalog order cannot deny later eligible routes a viability test; primary/fallback escalation counts remain audit telemetry only.\n"
    if entry not in changelog:
        changelog = changelog.replace("## [Unreleased]\n", "## [Unreleased]\n" + entry, 1)
        CHANGELOG.write_text(changelog, encoding="utf-8")

    baseline = BASELINE.read_text(encoding="utf-8")
    note = "\n### 2026-09-01 — Review preflight escalation order removed\n\n`_preflight_review_agents` no longer uses a shared first-come-first-served escalation quota. A route's explicit budget-starvation evidence authorizes one retry for that route independently of catalog position; primary and fallback escalation counts are retained only as audit telemetry. This removes the order-sensitive admission defect identified on PR #1591 without turning provider identity, route count, or an arbitrary shared quota into routing authority.\n"
    if "Review preflight escalation order removed" not in baseline:
        baseline += note
        BASELINE.write_text(baseline, encoding="utf-8")


def verify_green() -> None:
    """Verify focused runtime semantics and the full repository contract."""
    run("python3", "-m", "pytest", "-q", str(TESTS))
    run("python3", "-m", "pytest", "-q", "tests")
    run("python3", "-m", "compileall", "-q", str(SOURCE))
    run("git", "diff", "--check")


def main() -> None:
    """Execute test-first repair and publish both TDD phases."""
    add_red_test()
    verify_red()
    run("git", "add", str(TESTS))
    commit_and_push("test(review): expose order-sensitive preflight escalation")

    patch_source()
    update_tests_and_docs()
    verify_green()
    run("git", "add", str(SOURCE), str(TESTS), str(CHANGELOG), str(BASELINE))
    commit_and_push("fix(review): remove shared preflight escalation quota")


if __name__ == "__main__":
    main()
