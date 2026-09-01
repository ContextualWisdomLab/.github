#!/usr/bin/env python3
"""One-shot test-contract repair for PR #1616; self-removes after GREEN."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ORCH = ROOT / "tests/test_noema_orchestrator_workflow_contract.py"
QUEUE = ROOT / "tests/test_required_workflow_queue_contract.py"
DOCTORING = ROOT / "docs/doctoring/noema-review-token-lifetime.md"
BASELINE = ROOT / "docs/product-technical-gap-baseline.md"
CHANGELOG = ROOT / "CHANGELOG.md"
TEMP_WORKFLOW = ROOT / ".github/workflows/source-fix-1616-stale-contracts.yml"
SELF = Path(__file__).resolve()

old_step = '"Run Noema LLM review and submit verdict"'
new_step = '"Prepare Noema model verdict"'

orch = ORCH.read_text(encoding="utf-8")
if orch.count(old_step) != 1:
    raise SystemExit(f"expected one legacy Noema step reference in orchestrator contract, found {orch.count(old_step)}")
old_assertions = '''    assert "python3 -m scripts.ci.noema_review_gate" in workflow\n    assert "python3 scripts/ci/noema_review_gate.py" not in workflow\n'''
new_assertions = '''    prepare = workflow_step(workflow, "Prepare Noema model verdict")\n    publish = workflow_step(workflow, "Publish prepared Noema verdict on the exact live head")\n    assert '.github/actions/noema-review/two_phase.py' in prepare\n    assert '--prepare-verdict-file "$verdict_file"' in prepare\n    assert '.github/actions/noema-review/two_phase.py' in publish\n    assert '--publish-verdict-file "$verdict_file"' in publish\n    assert "python3 -m scripts.ci.noema_review_gate" not in workflow\n'''
if old_assertions not in orch:
    raise SystemExit("legacy single-process Noema command assertions are missing")
orch = orch.replace(old_step, new_step, 1).replace(old_assertions, new_assertions, 1)
ORCH.write_text(orch, encoding="utf-8")

queue = QUEUE.read_text(encoding="utf-8")
legacy_queue_count = queue.count(old_step)
if legacy_queue_count < 1:
    raise SystemExit("expected at least one legacy Noema step reference in queue contract")
queue = queue.replace(old_step, new_step)
QUEUE.write_text(queue, encoding="utf-8")

note = "\n### Regression-suite migration\n\nThe two-phase migration also updates pre-existing executable workflow contracts to target the `Prepare Noema model verdict` step and the explicit prepare/publish helper invocations. This prevents a green focused gate from coexisting with stale broader-suite expectations for the retired single-process command or step name.\n"
doctoring = DOCTORING.read_text(encoding="utf-8")
if "### Regression-suite migration" not in doctoring:
    doctoring = doctoring.rstrip() + note
DOCTORING.write_text(doctoring, encoding="utf-8")

baseline = BASELINE.read_text(encoding="utf-8")
baseline_note = "\n**Regression-suite consistency.** Legacy broader-suite assertions that still named the retired single-process Noema step/module are migrated to the two-phase prepare/publish contract, including step-scoped helper and envelope-argument evidence. This closes the false-GREEN gap where focused token-lifetime CI could pass while unchanged broader contracts described an impossible execution path.\n"
anchor = "**Residual external verification.** After this central change reaches protected `main`, replay Required Noema Review for unchanged `naruon#1497@152d1998c4e8024be9dc7026c8789d343c884fd0`."
if "**Regression-suite consistency.**" not in baseline:
    if anchor not in baseline:
        raise SystemExit("token-lifetime baseline anchor is missing")
    baseline = baseline.replace(anchor, baseline_note + "\n" + anchor, 1)
BASELINE.write_text(baseline, encoding="utf-8")

changelog = CHANGELOG.read_text(encoding="utf-8")
old_fragment = "and executable plus step-scoped regressions cover stale-head, identity, alias, and workflow-wiring behavior."
new_fragment = "and executable plus step-scoped regressions cover stale-head, identity, alias, workflow wiring, and migration of legacy broader-suite contracts away from the retired single-process reviewer path."
if new_fragment not in changelog:
    if old_fragment not in changelog:
        raise SystemExit("token-lifetime changelog entry is missing")
    changelog = changelog.replace(old_fragment, new_fragment, 1)
CHANGELOG.write_text(changelog, encoding="utf-8")

TEMP_WORKFLOW.unlink(missing_ok=True)
SELF.unlink(missing_ok=True)
