#!/usr/bin/env python3
"""Run the issue-952 patcher with a drift-safe long-form test update."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE_PATCHER = ROOT / "scripts" / "ci" / "apply_strix_952_repair.py"


def load_patcher():
    """Load the one-shot patcher without invoking its command-line entrypoint."""
    spec = importlib.util.spec_from_file_location("apply_strix_952_repair", BASE_PATCHER)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load issue-952 patcher")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def patch_full_shell_contract(patcher) -> None:
    """Extend the long-form shell contract using unambiguous source markers."""
    path = ROOT / "scripts" / "ci" / "test_strix_quick_gate.sh"
    text = path.read_text(encoding="utf-8")
    marker = (
        '\tassert_file_contains "$workflow_file" "Materialize central Strix dependency '
        'lock from PR head" "strix workflow validates central same-repo lock-file PRs '
        'against the PR head lock"\n'
    )
    replacement = marker + (
        '\tassert_file_contains "$workflow_file" "--require-hashes --no-deps -r '
        'requirements-strix-ci-hashes.txt" "strix workflow installs the complete hashed '
        'lock without dependency re-resolution"\n'
        '\tassert_file_contains "$workflow_file" "validate_strix_runtime_compatibility.py" '
        '"strix workflow executes exact-pin and crypto consumer smoke checks"\n'
    )
    text = patcher.replace_once(
        text, marker, replacement, "full shell install contract"
    )
    marker = (
        '\tassert_file_contains "$workflow_file" "Collect Strix reports for artifact upload" '
        '"strix workflow preserves reports from trusted workspace"\n'
    )
    replacement = marker + (
        '\tassert_file_not_contains "$workflow_file" "Treating as a neutral skip" '
        '"strix workflow keeps incomplete provider scans fail-closed"\n'
        '\tassert_file_contains "$GATE_SCRIPT" "import-current-attempt" '
        '"strix gate imports authoritative current-attempt reports"\n'
        '\tassert_file_contains "$GATE_SCRIPT" '
        '"vulnerability_file_is_self_negating_no_finding" '
        '"strix gate semantically excludes contradictory no-finding records"\n'
    )
    text = patcher.replace_once(
        text, marker, replacement, "full shell evidence contract"
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    """Apply all bounded production and regression changes exactly once."""
    patcher = load_patcher()
    patcher.patch_workflow()
    patcher.patch_gate()
    patcher.patch_nvidia_contract_test()
    patcher.patch_required_smoke()
    patch_full_shell_contract(patcher)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
