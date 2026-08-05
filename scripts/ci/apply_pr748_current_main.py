#!/usr/bin/env python3
"""Reapply the reviewed npm-workspace resolver to protected current main.

This temporary branch-repair helper derives the six nonconflicting product and
resolver-test files from one previously reviewed commit and adds a
current-main-compatible workflow contract test directly. It deliberately does
not import unrelated coverage-toolchain work from another pull request. The
publishing workflow deletes this helper before committing the verified
product-policy tree.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


REVIEWED_BASE = "4d076f636b6de5043e8501e93c06ed0a8c896eb3"
REVIEWED_CHILD = "b715577b9e946ecad4bd00c9f8afc7b2a219e048"
EXPECTED_MAIN_PARENT = "f070c504c1cb06891b800d7ab0cf6ac7d3cf8eae"
PATCH_PATH = Path("/tmp/pr748-current-main.patch")
CONTRACT_PATH = Path("tests/test_opencode_agent_contract.py")
PATCH_PATHS = (
    ".github/workflows/opencode-review-dispatch.yml",
    "docs/doctoring/npm-workspace-lock-ownership.md",
    "scripts/ci/npm_workspace_install_root.py",
    "tests/npm_workspace_test_support.py",
    "tests/test_npm_workspace_install_root.py",
    "tests/test_npm_workspace_install_root_hardening.py",
)
FINAL_PATHS = PATCH_PATHS + (str(CONTRACT_PATH),)
TEMPORARY_PATHS = (
    ".github/workflows/rebuild-pr748-current-main.yml",
    "scripts/ci/apply_pr748_current_main.py",
)
CONTRACT_FUNCTION = "test_opencode_coverage_resolves_validated_npm_workspace_lock_owner"
CONTRACT_TEST = r'''


def test_opencode_coverage_resolves_validated_npm_workspace_lock_owner():
    """Guard nested npm packages against invalid duplicate-lock requirements."""
    workflow = Path(".github/workflows/opencode-review-dispatch.yml").read_text(
        encoding="utf-8"
    )

    assert "resolve_npm_package_root()" in workflow
    assert "resolve_npm_install_root()" in workflow
    assert (
        'python3 -I "$GITHUB_WORKSPACE/scripts/ci/npm_workspace_install_root.py"'
        in workflow
    )
    assert 'trusted_npm_lock_is_materialized "$npm_install_root"' in workflow
    assert 'npm_workspace_args=(--workspace "$npm_workspace_selector")' in workflow
    assert 'install_package_dependencies "$package_runner" "$package_dir"' in workflow
    assert "npm workspace-root offline ci, lifecycle hooks disabled" in workflow
    assert "npm ci --offline --ignore-scripts" in workflow
    assert "ContextualWisdomLab/.github:scripts/ci/npm_workspace_install_root.py" in workflow
    assert "ContextualWisdomLab/.github:tests/test_npm_workspace_install_root.py" in workflow
    assert (
        "ContextualWisdomLab/.github:tests/"
        "test_npm_workspace_install_root_hardening.py" in workflow
    )
'''


def _run(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Run one Git command with text-mode output and fail on any error."""

    return subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=capture,
    )


def _ensure_reviewed_commit(commit_sha: str) -> None:
    """Fetch one exact reviewed commit when branch rewrites made it unreachable."""

    try:
        _run("git", "cat-file", "-e", f"{commit_sha}^{{commit}}")
    except subprocess.CalledProcessError:
        _run("git", "fetch", "--no-tags", "--depth=1", "origin", commit_sha)
        _run("git", "cat-file", "-e", f"{commit_sha}^{{commit}}")


def _section_path(section: str) -> str:
    """Return the repository path named by one unified-diff file section."""

    first_line = section.splitlines()[0]
    match = re.fullmatch(r"diff --git a/(.+) b/(.+)", first_line)
    if match is None or match.group(1) != match.group(2):
        raise SystemExit(f"unexpected diff header: {first_line!r}")
    return match.group(1)


def _validate_reviewed_patch(patch: str) -> str:
    """Require the reviewed patch to contain exactly the six expected files."""

    sections = [
        part
        for part in re.split(r"(?=^diff --git )", patch, flags=re.MULTILINE)
        if part.strip()
    ]
    if not sections:
        raise SystemExit("reviewed child commit produced no patch")

    seen = [_section_path(section) for section in sections]
    if len(seen) != len(set(seen)):
        raise SystemExit(f"reviewed patch contains duplicate file sections: {seen}")
    if set(seen) != set(PATCH_PATHS):
        raise SystemExit(
            "reviewed patch scope mismatch: "
            f"expected={sorted(PATCH_PATHS)}, actual={sorted(seen)}"
        )
    return patch


def _add_current_contract_test() -> None:
    """Add a conflict-free workflow contract to the current-main test file."""

    text = CONTRACT_PATH.read_text(encoding="utf-8")
    if CONTRACT_FUNCTION in text:
        raise SystemExit("npm workspace contract test already exists unexpectedly")
    CONTRACT_PATH.write_text(
        text.rstrip() + CONTRACT_TEST.rstrip() + "\n",
        encoding="utf-8",
    )
    _run("git", "add", str(CONTRACT_PATH))


def _verify_applied_tree() -> None:
    """Verify the staged tree contains the complete npm workspace contract."""

    workflow = Path(".github/workflows/opencode-review-dispatch.yml").read_text(
        encoding="utf-8"
    )
    required_workflow_fragments = (
        "resolve_npm_package_root()",
        "resolve_npm_install_root()",
        "npm_workspace_install_root.py",
        '--workspace "$npm_workspace_selector"',
        "npm workspace-root offline ci, lifecycle hooks disabled",
    )
    for fragment in required_workflow_fragments:
        if fragment not in workflow:
            raise SystemExit(f"required workflow fragment is absent: {fragment}")

    contract = CONTRACT_PATH.read_text(encoding="utf-8")
    if contract.count(f"def {CONTRACT_FUNCTION}(") != 1:
        raise SystemExit("current-main npm workspace contract test is not unique")

    changed = set(
        _run("git", "diff", "--cached", "--name-only", capture=True).stdout.splitlines()
    )
    if changed != set(FINAL_PATHS):
        raise SystemExit(
            "staged product-policy scope mismatch: "
            f"expected={sorted(FINAL_PATHS)}, actual={sorted(changed)}"
        )


def _verify_trigger_scope() -> None:
    """Require the trigger branch to contain only the two temporary files."""

    _run("git", "merge-base", "--is-ancestor", EXPECTED_MAIN_PARENT, "HEAD")
    temporary_diff = set(
        _run(
            "git",
            "diff",
            "--name-only",
            f"{EXPECTED_MAIN_PARENT}...HEAD",
            capture=True,
        ).stdout.splitlines()
    )
    if temporary_diff != set(TEMPORARY_PATHS):
        raise SystemExit(
            "repair trigger scope mismatch: "
            f"expected={sorted(TEMPORARY_PATHS)}, actual={sorted(temporary_diff)}"
        )


def main() -> int:
    """Apply the reviewed resolver patch to the exact protected-main parent."""

    _verify_trigger_scope()
    _ensure_reviewed_commit(REVIEWED_BASE)
    _ensure_reviewed_commit(REVIEWED_CHILD)
    patch = _run(
        "git",
        "diff",
        "--binary",
        REVIEWED_BASE,
        REVIEWED_CHILD,
        "--",
        *PATCH_PATHS,
        capture=True,
    ).stdout
    PATCH_PATH.write_text(_validate_reviewed_patch(patch), encoding="utf-8")
    _run("git", "apply", "--3way", "--index", str(PATCH_PATH))
    _add_current_contract_test()
    _run("git", "diff", "--cached", "--check")
    _verify_applied_tree()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
