#!/usr/bin/env python3
"""Finalize the reviewed npm workspace repair and remove all one-shot helpers."""

from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEGACY_BOOTSTRAP = ROOT / "scripts/ci/bootstrap_patch_workflow.py"
WORKFLOW = ROOT / ".github/workflows/opencode-review-dispatch.yml"
CONTRACT = ROOT / "tests/test_opencode_agent_contract.py"
SELF = ROOT / "scripts/ci/bootstrap_pr703_final_repair.py"
SELF_WORKFLOW = ROOT / ".github/workflows/pr703-final-repair.yml"


def replace_once(text: str, old: str, new: str, name: str) -> str:
    """Replace exactly one reviewed fragment and fail closed on branch drift."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{name}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_generated_workflow(text: str) -> str:
    """Align the generated npm path with current security contracts."""
    text = replace_once(
        text,
        '              echo "::error::Current npm lock ${relative_lock} lacks an exact validated base-or-HEAD materialization receipt."\n',
        '              echo "::error::Current npm lock ${relative_lock} was not hash-bounded and materialized from the validated base or HEAD with an exact receipt."\n',
        "materialization diagnostic",
    )
    text = replace_once(
        text,
        """                run_and_capture "JavaScript/TypeScript dependencies (npm workspace-root offline ci, lifecycle hooks disabled)" \\
                  bash -c 'cd "$1" && cache="$2" && shift 2 && npm ci --offline --ignore-scripts --cache "$cache" --no-audit --no-fund "$@"' \\
                  bash "$npm_install_root" "$writable_npm_cache_dir" "${npm_workspace_args[@]}"
""",
        """                run_and_capture "JavaScript/TypeScript dependencies (npm workspace-root offline ci, lifecycle hooks disabled)" \\
                  bash -c 'cd "$1" && shift && exec "$@"' \\
                  bash "$npm_install_root" \\
                  npm ci --offline --ignore-scripts --cache "$writable_npm_cache_dir" --no-audit --no-fund \\
                  "${npm_workspace_args[@]}"
""",
        "structured npm invocation",
    )
    return text


def patch_generated_contract(text: str) -> str:
    """Make the generated contract deterministic across hosted Git versions."""
    text = replace_once(
        text,
        """    base_env = {
        **os.environ,
        "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1",
    }
""",
        """    base_env = {
        **os.environ,
        "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
    }
""",
        "isolated Git ownership test configuration",
    )
    text = replace_once(
        text,
        """    assert 'bash "$npm_install_root" "$writable_npm_cache_dir" "${npm_workspace_args[@]}"' in npm_install_case
""",
        """    assert 'bash "$npm_install_root"' in npm_install_case
    assert '--cache "$writable_npm_cache_dir"' in npm_install_case
    assert '"${npm_workspace_args[@]}"' in npm_install_case
""",
        "structured npm invocation assertions",
    )
    return text


def main() -> None:
    """Run the reviewed bootstrap, apply current contracts, and self-remove."""
    if not LEGACY_BOOTSTRAP.is_file():
        raise RuntimeError("legacy PR 703 bootstrap is missing")
    runpy.run_path(str(LEGACY_BOOTSTRAP), run_name="__main__")

    workflow = patch_generated_workflow(WORKFLOW.read_text(encoding="utf-8"))
    contract = patch_generated_contract(CONTRACT.read_text(encoding="utf-8"))
    WORKFLOW.write_text(workflow, encoding="utf-8")
    CONTRACT.write_text(contract, encoding="utf-8")

    SELF.unlink()
    SELF_WORKFLOW.unlink()


if __name__ == "__main__":
    main()
