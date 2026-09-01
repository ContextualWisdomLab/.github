#!/usr/bin/env python3
"""One-shot PR #1591 RED/GREEN repair; removed by its writer workflow."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def run(*args: str, expect_success: bool = True) -> subprocess.CompletedProcess[str]:
    """Run one repository command and enforce the expected exit contract."""
    completed = subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**__import__("os").environ, "PYTHONPATH": "."},
        check=False,
    )
    print(completed.stdout, end="")
    if expect_success and completed.returncode != 0:
        raise SystemExit(completed.returncode)
    if not expect_success and completed.returncode == 0:
        raise SystemExit("expected RED command to fail before production repair")
    return completed


def append_red_tests() -> None:
    """Add failing compatibility/runtime contracts before touching production."""
    admission = ROOT / "tests/test_contextual_orchestrator_no_heuristic_admission.py"
    text = admission.read_text(encoding="utf-8")
    test = '''\n\ndef test_legacy_ignored_inputs_accept_arbitrary_values() -> None:\n    \"\"\"Ignored compatibility inputs cannot become an accidental admission contract.\"\"\"\n    rows = [_free_row(index) for index in range(3)]\n    sentinel = object()\n\n    result = policy.build_zdr_prioritized_catalog(\n        rows,\n        pool=\"free\",\n        limit=\"retired-limit\",\n        account_cap=sentinel,\n    )\n\n    assert [entry[\"model\"] for entry in result[\"agents\"]] == [\n        row[\"model\"] for row in rows\n    ]\n    assert result[\"report\"][\"legacy_limit_ignored\"] is True\n    assert result[\"report\"][\"legacy_account_cap_ignored\"] is True\n'''
    if "def test_legacy_ignored_inputs_accept_arbitrary_values" not in text:
        admission.write_text(text + test, encoding="utf-8")

    runtime = ROOT / "tests/test_contextual_orchestrator_review_runtime_preflight.py"
    text = runtime.read_text(encoding="utf-8")
    test = '''\n\ndef test_launcher_has_no_legacy_catalog_admission_caps() -> None:\n    \"\"\"Runtime bootstrap must not restore retired catalog admission authority.\"\"\"\n    namespace = _load_launcher()\n    source = _LAUNCHER.read_text(encoding=\"utf-8\")\n\n    assert \"_bounded_primary_catalog_limit\" not in namespace\n    assert \"_bounded_fallback_catalog_limit\" not in namespace\n    assert \"_catalog_account_cap\" not in namespace\n    assert \"REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES\" not in source\n    assert \"REVIEW_PREFLIGHT_PRIMARY_ROUTE_LIMIT\" not in source\n    assert \"ORCHESTRATOR_CATALOG_LIMIT\" not in source\n    assert \"ORCHESTRATOR_CATALOG_ACCOUNT_CAP\" not in source\n'''
    if "def test_launcher_has_no_legacy_catalog_admission_caps" not in text:
        runtime.write_text(text + test, encoding="utf-8")


def verify_red() -> None:
    """Prove the new contracts fail on the pre-repair implementation."""
    run(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_contextual_orchestrator_no_heuristic_admission.py",
        "tests/test_contextual_orchestrator_review_runtime_preflight.py",
        "-k",
        "legacy_ignored_inputs_accept_arbitrary_values or launcher_has_no_legacy_catalog_admission_caps",
        expect_success=False,
    )


def repair_launcher() -> None:
    """Remove retired cardinality/account caps from runtime admission."""
    path = ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "ZDR-prioritized, credential-account-diverse catalog for ``orchestrator/free``.",
        "evidence-admitted catalog for ``orchestrator/free``; routing preference remains owned by the orchestrator's explicit evidence model.",
    )
    cap_constants = "REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES = 12\nREVIEW_PREFLIGHT_PRIMARY_ROUTE_LIMIT = 8\n"
    if text.count(cap_constants) != 1:
        raise SystemExit("launcher cap constants changed unexpectedly")
    text = text.replace(cap_constants, "", 1)
    start = text.index("def _bounded_primary_catalog_limit(")
    end = text.index("def _with_discovery_counts(", start)
    text = text[:start] + text[end:]
    text = text.replace("        DEFAULT_ACCOUNT_CAP,\n", "")

    primary_budget = '''    requested_catalog_limit = int(os.environ.get("ORCHESTRATOR_CATALOG_LIMIT", "12"))\n    primary_limit = _bounded_primary_catalog_limit(\n        requested_catalog_limit, pool=args.pool, has_free_rows=bool(admitted_free_rows)\n    )\n'''
    if text.count(primary_budget) != 1:
        raise SystemExit("launcher primary budget block changed unexpectedly")
    text = text.replace(primary_budget, "", 1)

    primary_call = '''    result = build_zdr_prioritized_catalog(\n        primary_rows,\n        limit=primary_limit,\n        account_cap=_catalog_account_cap(DEFAULT_ACCOUNT_CAP),\n'''
    if text.count(primary_call) != 1:
        raise SystemExit("launcher primary catalog call changed unexpectedly")
    text = text.replace(primary_call, '''    result = build_zdr_prioritized_catalog(\n        primary_rows,\n''', 1)

    fallback_budget = '''    fallback_limit = _bounded_fallback_catalog_limit(\n        requested_catalog_limit, primary_count=len(result["agents"])\n    )\n'''
    if text.count(fallback_budget) != 1:
        raise SystemExit("launcher fallback budget block changed unexpectedly")
    text = text.replace(fallback_budget, "", 1)

    fallback_condition = '''        and admitted_priced_rows\n        and fallback_limit\n    ):\n'''
    if text.count(fallback_condition) != 1:
        raise SystemExit("launcher fallback condition changed unexpectedly")
    text = text.replace(fallback_condition, '''        and admitted_priced_rows\n    ):\n''', 1)

    fallback_call = '''            fallback_result = build_zdr_prioritized_catalog(\n                admitted_priced_rows,\n                limit=fallback_limit,\n                account_cap=_catalog_account_cap(DEFAULT_ACCOUNT_CAP),\n'''
    if text.count(fallback_call) != 1:
        raise SystemExit("launcher fallback catalog call changed unexpectedly")
    text = text.replace(fallback_call, '''            fallback_result = build_zdr_prioritized_catalog(\n                admitted_priced_rows,\n''', 1)

    forbidden = (
        "_bounded_primary_catalog_limit",
        "_bounded_fallback_catalog_limit",
        "_catalog_account_cap",
        "REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES",
        "REVIEW_PREFLIGHT_PRIMARY_ROUTE_LIMIT",
        "ORCHESTRATOR_CATALOG_LIMIT",
        "ORCHESTRATOR_CATALOG_ACCOUNT_CAP",
    )
    lingering = [token for token in forbidden if token in text]
    if lingering:
        raise SystemExit(f"launcher still contains retired cap contracts: {lingering}")
    path.write_text(text, encoding="utf-8")


def repair_policy() -> None:
    """Make ignored compatibility arguments genuinely non-authoritative."""
    path = ROOT / "scripts/ci/contextual_orchestrator_review_policy.py"
    text = path.read_text(encoding="utf-8")
    signature = "    limit: int = DEFAULT_CATALOG_LIMIT,\n    account_cap: int = DEFAULT_ACCOUNT_CAP,\n"
    if text.count(signature) != 2:
        raise SystemExit("policy compatibility signatures changed unexpectedly")
    text = text.replace(
        signature,
        "    limit: object = DEFAULT_CATALOG_LIMIT,\n    account_cap: object = DEFAULT_ACCOUNT_CAP,\n",
        2,
    )
    validation = '''    if isinstance(limit, bool) or not isinstance(limit, int):\n        raise PolicyError("legacy limit must be an integer when supplied")\n    if isinstance(account_cap, bool) or not isinstance(account_cap, int):\n        raise PolicyError("legacy account_cap must be an integer when supplied")\n\n'''
    if text.count(validation) != 1:
        raise SystemExit("legacy policy validation block changed unexpectedly")
    text = text.replace(validation, "", 1)
    report = '            "legacy_limit_ignored": limit,\n            "legacy_account_cap_ignored": account_cap,\n'
    if text.count(report) != 1:
        raise SystemExit("legacy policy report fields changed unexpectedly")
    text = text.replace(
        report,
        '            "legacy_limit_ignored": True,\n            "legacy_account_cap_ignored": True,\n',
        1,
    )
    text = text.replace(
        '        type=int,\n        default=DEFAULT_CATALOG_LIMIT,\n',
        '        default=DEFAULT_CATALOG_LIMIT,\n',
        1,
    )
    text = text.replace(
        '        type=int,\n        default=DEFAULT_ACCOUNT_CAP,\n',
        '        default=DEFAULT_ACCOUNT_CAP,\n',
        1,
    )
    path.write_text(text, encoding="utf-8")


def repair_sidecar() -> None:
    """Remove shell transport for retired admission-cap variables."""
    path = ROOT / "scripts/ci/contextual_orchestrator_review_sidecar.sh"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "ZDR-prioritized, credential-account-diverse agents catalog by\n# scripts/ci/contextual_orchestrator_review_policy.py for the `orchestrator/free`",
        "evidence-admitted agents catalog by\n# scripts/ci/contextual_orchestrator_review_policy.py for the `orchestrator/free`",
        1,
    )
    start = text.index('CATALOG_LIMIT="${ORCHESTRATOR_CATALOG_LIMIT:-12}"')
    end = text.index('ORCHESTRATOR_GITHUB_ENV="${GITHUB_ENV:-}"', start)
    text = text[:start] + text[end:]
    exports = 'export ORCHESTRATOR_CATALOG_LIMIT="$CATALOG_LIMIT"\nexport ORCHESTRATOR_CATALOG_ACCOUNT_CAP="$CATALOG_ACCOUNT_CAP"\n'
    if text.count(exports) != 1:
        raise SystemExit("sidecar catalog cap exports changed unexpectedly")
    text = text.replace(exports, "", 1)
    if "ORCHESTRATOR_CATALOG_LIMIT" in text or "ORCHESTRATOR_CATALOG_ACCOUNT_CAP" in text:
        raise SystemExit("sidecar still contains retired catalog caps")
    path.write_text(text, encoding="utf-8")


def rewrite_runtime_contract_tests() -> None:
    """Preserve retry-budget coverage while removing obsolete route-cap assertions."""
    path = ROOT / "tests/test_contextual_orchestrator_review_runtime_preflight.py"
    text = path.read_text(encoding="utf-8")
    start = text.index(
        "def test_fallback_escalation_budget_is_shared_with_primary_and_bounds_worst_case"
    )
    end = text.index(
        "def test_zdr_admission_selects_priced_tier_when_free_routes_are_not_private",
        start,
    )
    replacement = '''def test_fallback_escalation_budget_is_shared_across_full_admitted_catalog() -> None:\n    \"\"\"Escalation retries stay shared without evicting evidence-admitted routes.\"\"\"\n    namespace = _load_launcher()\n    preflight = namespace[\"_preflight_with_fallback\"]\n    max_escalations = namespace[\"REVIEW_PREFLIGHT_MAX_ESCALATIONS\"]\n    primary_agents = [\n        SimpleNamespace(id=f\"primary_{index}\", provider_name=\"openrouter\", model=\"x/free\")\n        for index in range(13)\n    ]\n    fallback_agents = [\n        SimpleNamespace(id=f\"fallback_{index}\", provider_name=\"openrouter\", model=\"y/priced\")\n        for index in range(5)\n    ]\n    starved = {\"choices\": [{\"finish_reason\": \"length\", \"message\": {\"content\": \"\"}}]}\n    client = _ProbeClient({agent.id: dict(starved) for agent in [*primary_agents, *fallback_agents]})\n\n    with pytest.raises(namespace[\"ReviewPreflightError\"]) as failure:\n        preflight(primary_agents, fallback_agents, client=client)\n\n    assert failure.value.report[\"escalations_used\"] == max_escalations\n    assert failure.value.report[\"primary_attempt\"][\"escalations_used\"] == max_escalations\n    assert len(client.calls) == len(primary_agents) + len(fallback_agents) + max_escalations\n\n\ndef test_preflight_keeps_more_than_twelve_admitted_primary_routes() -> None:\n    \"\"\"Admission cardinality cannot crash or truncate runtime preflight.\"\"\"\n    namespace = _load_launcher()\n    preflight = namespace[\"_preflight_with_fallback\"]\n    agents = [\n        SimpleNamespace(id=f\"ready_{index}\", provider_name=\"openrouter\", model=f\"model/{index}\")\n        for index in range(13)\n    ]\n    client = _ProbeClient({agent.id: _openai_text(\"OK\") for agent in agents})\n\n    viable, report, fallback_used = preflight(agents, [], client=client)\n\n    assert viable == agents\n    assert report[\"ready_count\"] == len(agents)\n    assert fallback_used is False\n    assert [call[0] for call in client.calls] == agents\n\n\ndef test_auto_fallback_keeps_all_admitted_routes_after_primary_failure() -> None:\n    \"\"\"Auto-pool fallback is evidence-triggered, not cardinality-truncated.\"\"\"\n    namespace = _load_launcher()\n    preflight = namespace[\"_preflight_with_fallback\"]\n    primary = [\n        SimpleNamespace(id=f\"free_{index}\", provider_name=\"openrouter\", model=f\"free/{index}\")\n        for index in range(9)\n    ]\n    fallback = [\n        SimpleNamespace(id=f\"priced_{index}\", provider_name=\"openrouter\", model=f\"priced/{index}\")\n        for index in range(5)\n    ]\n    client = _ProbeClient(\n        {agent.id: TimeoutError(\"unavailable\") for agent in primary}\n        | {agent.id: _openai_text(\"OK\") for agent in fallback}\n    )\n\n    viable, report, fallback_used = preflight(primary, fallback, client=client)\n\n    assert viable == fallback\n    assert fallback_used is True\n    assert report[\"fallback_reason\"] == \"primary_routes_unavailable\"\n    assert [call[0] for call in client.calls] == [*primary, *fallback]\n\n\n'''
    path.write_text(text[:start] + replacement + text[end:], encoding="utf-8")


def update_docs() -> None:
    """Record the live causal repair and retire contradictory cap wording."""
    changelog = ROOT / "CHANGELOG.md"
    text = changelog.read_text(encoding="utf-8")
    entry = (
        "- Remove the retired Noema/OpenCode catalog cardinality heuristics from the review launcher and sidecar. "
        "Evidence-eligible routes are no longer truncated before runtime preflight, auto-mode keeps the full priced fallback set, "
        "and legacy `limit`/`account_cap` inputs are accepted only as ignored compatibility arguments. This closes the >12-route startup crash found by Devin Review without making serialization order or provider identity a routing preference.\n"
    )
    if entry not in text:
        text = text.replace("## [Unreleased]\n", "## [Unreleased]\n" + entry, 1)
    changelog.write_text(text, encoding="utf-8")

    baseline = ROOT / "docs/product-technical-gap-baseline.md"
    text = baseline.read_text(encoding="utf-8")
    heading = "## 2026-09-01 Noema/OpenCode admission/runtime reconciliation"
    note = f'''\n\n{heading}\n\nDevin Review exposed a contract split in PR #1591: the policy layer correctly stopped truncating evidence-eligible routes, while the launcher still rejected any primary catalog larger than the historical 12-route preflight budget. The causal owner is the central `.github` launcher/sidecar boundary, not a leaf repository. The repair removes catalog cardinality and per-account caps from launcher admission, preserves the full primary and evidence-triggered priced fallback catalogs, and keeps neutral policy priority. Legacy `limit` and `account_cap` inputs remain accepted but are explicitly non-authoritative. Regression coverage includes >12 primary routes, >8 free routes with a priced fallback set, shared escalation evidence across a larger catalog, and arbitrary ignored compatibility values. The former `12 base attempts + 4 escalations = 160s` statement is historical rather than a current admission invariant; startup-latency control must not silently evict eligible routes without an independently justified decision model.\n'''
    if heading not in text:
        text += note
    baseline.write_text(text, encoding="utf-8")


def verify_green() -> None:
    """Run focused and repository-wide evidence after production repair."""
    run(
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_contextual_orchestrator_no_heuristic_admission.py",
        "tests/test_contextual_orchestrator_review_policy.py",
        "tests/test_contextual_orchestrator_review_runtime_preflight.py",
    )
    run(sys.executable, "-m", "pytest", "-q", "tests")
    run(sys.executable, "-m", "compileall", "-q", "scripts/ci", "tests")
    run(
        "interrogate",
        "--fail-under=100",
        "scripts/ci/contextual_orchestrator_review_policy.py",
        "scripts/ci/contextual_orchestrator_review_launcher.py",
    )
    run("git", "diff", "--check")


def main() -> None:
    """Execute RED, causal repair, migrated contracts, and GREEN verification."""
    append_red_tests()
    verify_red()
    repair_launcher()
    repair_policy()
    repair_sidecar()
    rewrite_runtime_contract_tests()
    update_docs()
    verify_green()


if __name__ == "__main__":
    main()
