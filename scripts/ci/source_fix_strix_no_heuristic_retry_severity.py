"""One-shot exact-source repair for Strix retry/severity no-heuristics contracts.

This driver is intentionally temporary. The companion workflow deletes it after
RED-before-repair and focused GREEN verification succeed on the same branch head.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts" / "ci" / "strix_quick_gate.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "strix.yml"
QUEUE_TEST = ROOT / "tests" / "test_required_workflow_queue_contract.py"
RETRY_TEST = ROOT / "tests" / "test_strix_no_heuristic_retry_contract.py"
SEVERITY_TEST = ROOT / "tests" / "test_strix_no_heuristic_severity_contract.py"
DOCTORING = ROOT / "docs" / "doctoring" / "strix-orchestrator-free-model-boundary-2026-09-02.md"


def _run_contract_file(path: Path) -> None:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load contract {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in sorted(dir(module)):
        if name.startswith("test_"):
            getattr(module, name)()


def _prove_red() -> None:
    failures: list[str] = []
    for path in (RETRY_TEST, SEVERITY_TEST):
        try:
            _run_contract_file(path)
        except AssertionError as exc:
            failures.append(f"{path.name}: {exc}")
    if not failures:
        raise SystemExit("no-heuristics Strix contracts were already GREEN before repair")
    print("RED contracts observed:")
    for failure in failures:
        print(f"- {failure}")


def _remove_shell_function(source: str, name: str) -> str:
    pattern = rf"(?ms)^{re.escape(name)}\(\) \{{\n.*?^\}}\n\n"
    result, count = re.subn(pattern, "", source, count=1)
    if count != 1:
        raise SystemExit(f"expected exactly one {name} function, found {count}")
    return result


def _repair_gate() -> None:
    gate = GATE.read_text(encoding="utf-8")
    for line in (
        'STRIX_TRANSIENT_RETRY_PER_MODEL="${STRIX_TRANSIENT_RETRY_PER_MODEL:-0}"\n',
        'STRIX_TRANSIENT_RETRY_BACKOFF_SECONDS="${STRIX_TRANSIENT_RETRY_BACKOFF_SECONDS:-3}"\n',
        '\trequire_non_negative_integer "$STRIX_TRANSIENT_RETRY_PER_MODEL" "STRIX_TRANSIENT_RETRY_PER_MODEL"\n',
        '\trequire_non_negative_integer "$STRIX_TRANSIENT_RETRY_BACKOFF_SECONDS" "STRIX_TRANSIENT_RETRY_BACKOFF_SECONDS"\n',
    ):
        if line not in gate:
            raise SystemExit(f"expected gate line missing: {line!r}")
        gate = gate.replace(line, "", 1)

    for function_name in (
        "is_transient_same_model_retry_error",
        "github_models_rate_limit_should_skip_same_model_retry",
        "run_strix_with_transient_retry",
    ):
        gate = _remove_shell_function(gate, function_name)

    old_success = '''\tif [ "$rc" -eq 0 ]; then
\t\tif has_blocking_vulnerability_reports; then
\t\t\tif ! evaluate_pull_request_findings || [ "$PR_FINDINGS_DECISION" != "allow_baseline" ]; then
\t\t\t\techo "Strix exited successfully but emitted a vulnerability at or above '$STRIX_FAIL_ON_MIN_SEVERITY'; failing closed." >&2
\t\t\t\treturn 1
\t\t\tfi
\t\tfi
\t\tprintf "Strix run succeeded for model '%s' in %ds.\\n" "$model" "$elapsed" >&2
\t\treturn 0
\tfi
'''
    new_success = '''\tif [ "$rc" -eq 0 ]; then
\t\tlocal current_vulnerability_file
\t\tcurrent_vulnerability_file="$(find "$ACTIVE_REPORTS_DIR" -type f -path '*/vulnerabilities/*.md' -print -quit 2>/dev/null || true)"
\t\tif [ -n "$current_vulnerability_file" ]; then
\t\t\techo "Current Strix vulnerability report exists; failing closed without a repository-authored severity threshold." >&2
\t\t\treturn 1
\t\tfi
\t\tprintf "Strix run succeeded for model '%s' in %ds.\\n" "$model" "$elapsed" >&2
\t\treturn 0
\tfi
'''
    if old_success not in gate:
        raise SystemExit("run_strix_once success block did not match expected source")
    gate = gate.replace(old_success, new_success, 1)

    simple_scan = '''run_current_target_scan() {
\tINFRA_ERROR_DETECTED=0
\tZERO_FINDINGS_REPORTED=0

\tlocal primary_scan_rc=0
\trun_strix_once "$PRIMARY_MODEL" || primary_scan_rc=$?
\tif [ "$primary_scan_rc" -eq 0 ]; then
\t\treturn 0
\tfi
\tif [ "$primary_scan_rc" -eq 2 ]; then
\t\treturn 2
\tfi
\tif [ "$INFRA_ERROR_DETECTED" -eq 1 ]; then
\t\techo "STRIX_PROVIDER_UNAVAILABLE: contextual-orchestrator/orchestrator/free did not produce authoritative scan evidence; failing closed without repository-authored retry or fallback allocation." >&2
\telse
\t\techo "Strix quick scan failed; failing closed without repository-authored retry or fallback allocation." >&2
\tfi
\treturn 1
}

'''
    gate, count = re.subn(
        r"(?ms)^run_current_target_scan\(\) \{\n.*?^\}\n\n(?=prepare_pull_request_scan_scope)",
        simple_scan,
        gate,
        count=1,
    )
    if count != 1:
        raise SystemExit(f"expected one run_current_target_scan block, found {count}")
    GATE.write_text(gate, encoding="utf-8")


def _repair_workflow() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for line in (
        "          STRIX_LLM_MAX_RETRIES: 1\n",
        "          STRIX_TRANSIENT_RETRY_PER_MODEL: 2\n",
        "          STRIX_TRANSIENT_RETRY_BACKOFF_SECONDS: 60\n",
        "          STRIX_FAIL_ON_MIN_SEVERITY: MEDIUM\n",
    ):
        if line not in workflow:
            raise SystemExit(f"expected workflow line missing: {line!r}")
        workflow = workflow.replace(line, "", 1)

    workflow = workflow.replace(
        "          # severity branch anchored away from identifiers so environment lines\n"
        "          # such as STRIX_FAIL_ON_MIN_SEVERITY do not look like findings.\n",
        "          # Keep the severity marker anchored away from identifiers so unrelated\n"
        "          # environment text does not look like a reported finding.\n",
        1,
    )

    single_run = '''          strix_run_log="$RUNNER_TEMP/strix_gate_console.log"
          : > "$strix_run_log"
          strix_terminal_log="$strix_run_log"
          strix_rc=0
          set +e
          bash "$TRUSTED_STRIX_GATE" 2>&1 | tee "$strix_terminal_log"
          strix_rc="${PIPESTATUS[0]}"
          set -e

          if [ "$strix_rc" -eq 0 ]; then'''
    workflow, count = re.subn(
        r'''(?ms)          strix_run_log="\$RUNNER_TEMP/strix_gate_console\.log"\n.*?          set -e\n\n          if \[ "\$strix_rc" -eq 0 \]; then''',
        single_run,
        workflow,
        count=1,
    )
    if count != 1:
        raise SystemExit(f"expected one outer Strix retry loop, found {count}")

    workflow = workflow.replace("out-of-scope/below-threshold finding", "out-of-scope finding")
    workflow = workflow.replace("below-threshold finding", "out-of-scope finding")
    if "STRIX_FAIL_ON_MIN_SEVERITY" in workflow:
        raise SystemExit("stale STRIX_FAIL_ON_MIN_SEVERITY remains in workflow")
    if "strix_gate_attempt" in workflow or "STRIX_GATE_RETRY_BACKOFF_SECONDS" in workflow:
        raise SystemExit("stale outer retry authority remains in workflow")
    WORKFLOW.write_text(workflow, encoding="utf-8")


def _repair_existing_test() -> None:
    source = QUEUE_TEST.read_text(encoding="utf-8")
    old = '    assert "STRIX_FAIL_ON_MIN_SEVERITY: MEDIUM" in workflow\n'
    new = '    assert "STRIX_FAIL_ON_MIN_SEVERITY" not in workflow\n'
    if old not in source:
        raise SystemExit("required workflow queue test threshold assertion not found")
    QUEUE_TEST.write_text(source.replace(old, new, 1), encoding="utf-8")


def _append_trace() -> None:
    marker = "## Retry and severity decision repair"
    current = DOCTORING.read_text(encoding="utf-8")
    if marker in current:
        return
    addition = '''

## Retry and severity decision repair

Fresh protected-main evidence showed that the required Strix workflow still allocated two same-model gate retries plus a second outer three-attempt retry loop with fixed backoff values, while the reusable gate classified retryability through hand-authored provider/error regex families. The same path converted Strix severity labels to numeric ranks and used the repository-selected `MEDIUM` cutoff as a merge admission rule. Neither retry allocation nor the severity cutoff had an identified statistical model, authoritative standard, or executable experimental calibration.

The repair therefore does not substitute different retry counts, backoff constants, severity weights, or cutoffs. The central Strix path executes the governed `orchestrator/free` request once; contextual-orchestrator retains provider discovery/failover authority. Any execution that fails to produce authoritative scan evidence fails closed. Any current vulnerability report artifact also fails closed without a repository-authored severity threshold. Severity labels may remain descriptive evidence, but they are not converted into a local admission score.
'''
    DOCTORING.write_text(current.rstrip() + addition, encoding="utf-8")


def main() -> None:
    _prove_red()
    _repair_gate()
    _repair_workflow()
    _repair_existing_test()
    _append_trace()
    _run_contract_file(RETRY_TEST)
    _run_contract_file(SEVERITY_TEST)
    print("Focused no-heuristics Strix contracts are GREEN after repair.")


if __name__ == "__main__":
    main()
