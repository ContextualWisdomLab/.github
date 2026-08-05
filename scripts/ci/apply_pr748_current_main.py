#!/usr/bin/env python3
"""Reapply the reviewed npm-workspace resolver without regressing LLVM coverage.

This temporary branch-repair helper derives one previously reviewed commit as a
unified patch, removes only the unrelated LLVM-toolchain deletion hunks, applies
the remaining patch with Git's three-way merge support, and fails closed on any
unexpected file or residual conflict. The publishing workflow deletes this file
before committing the verified product-policy tree.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


REVIEWED_BASE = "4d076f636b6de5043e8501e93c06ed0a8c896eb3"
REVIEWED_CHILD = "b715577b9e946ecad4bd00c9f8afc7b2a219e048"
EXPECTED_MAIN_PARENT = "f070c504c1cb06891b800d7ab0cf6ac7d3cf8eae"
PATCH_PATH = Path("/tmp/pr748-current-main.patch")
ALLOWED_PATHS = (
    ".github/workflows/opencode-review-dispatch.yml",
    "docs/doctoring/npm-workspace-lock-ownership.md",
    "scripts/ci/npm_workspace_install_root.py",
    "tests/npm_workspace_test_support.py",
    "tests/test_npm_workspace_install_root.py",
    "tests/test_npm_workspace_install_root_hardening.py",
    "tests/test_opencode_agent_contract.py",
)
TEMPORARY_PATHS = (
    ".github/workflows/rebuild-pr748-current-main.yml",
    "scripts/ci/apply_pr748_current_main.py",
)
LLVM_PRESERVATION_TOKENS = (
    "llvm-19",
    "LLVM_COV",
    "LLVM_PROFDATA",
    "cargo-llvm-cov/releases/download",
    "test_opencode_coverage_image_provisions_compatible_llvm_tools",
)


def _run(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Run one Git command with text-mode output and fail on any error."""

    return subprocess.run(
        args,
        check=True,
        text=True,
        capture_output=capture,
    )


def _section_path(section: str) -> str:
    """Return the repository path named by one unified-diff file section."""

    first_line = section.splitlines()[0]
    match = re.fullmatch(r"diff --git a/(.+) b/(.+)", first_line)
    if match is None or match.group(1) != match.group(2):
        raise SystemExit(f"unexpected diff header: {first_line!r}")
    return match.group(1)


def _filter_reviewed_patch(patch: str) -> str:
    """Keep the seven-file resolver patch while preserving LLVM hunks."""

    sections = [
        part
        for part in re.split(r"(?=^diff --git )", patch, flags=re.MULTILINE)
        if part.strip()
    ]
    if not sections:
        raise SystemExit("reviewed child commit produced no patch")

    seen: set[str] = set()
    filtered_sections: list[str] = []
    for section in sections:
        path = _section_path(section)
        if path not in ALLOWED_PATHS:
            raise SystemExit(f"unexpected path in reviewed patch: {path}")
        if path in seen:
            raise SystemExit(f"duplicate path in reviewed patch: {path}")
        seen.add(path)

        if path not in {
            ".github/workflows/opencode-review-dispatch.yml",
            "tests/test_opencode_agent_contract.py",
        }:
            filtered_sections.append(section)
            continue

        parts = re.split(r"(?=^@@ )", section, flags=re.MULTILINE)
        header, hunks = parts[0], parts[1:]
        kept_hunks = [
            hunk
            for hunk in hunks
            if not any(token in hunk for token in LLVM_PRESERVATION_TOKENS)
        ]
        if not kept_hunks:
            raise SystemExit(f"filter removed every hunk for required path: {path}")
        filtered_sections.append(header + "".join(kept_hunks))

    if seen != set(ALLOWED_PATHS):
        missing = sorted(set(ALLOWED_PATHS) - seen)
        raise SystemExit(f"reviewed patch is missing required paths: {missing}")

    filtered = "".join(filtered_sections)
    for line in filtered.splitlines():
        if line.startswith("-") and any(
            token in line for token in LLVM_PRESERVATION_TOKENS
        ):
            raise SystemExit(f"filtered patch still deletes LLVM contract: {line}")
    return filtered


def _verify_applied_tree() -> None:
    """Verify the staged tree contains the resolver and preserved toolchain."""

    workflow = Path(
        ".github/workflows/opencode-review-dispatch.yml"
    ).read_text(encoding="utf-8")
    required_workflow_fragments = (
        "llvm-19",
        "ENV LLVM_COV=/usr/bin/llvm-cov-19",
        "ENV LLVM_PROFDATA=/usr/bin/llvm-profdata-19",
        "resolve_npm_package_root()",
        "resolve_npm_install_root()",
        "npm_workspace_install_root.py",
        '--workspace "$npm_workspace_selector"',
    )
    for fragment in required_workflow_fragments:
        if fragment not in workflow:
            raise SystemExit(f"required workflow fragment is absent: {fragment}")

    changed = set(
        _run(
            "git",
            "diff",
            "--cached",
            "--name-only",
            capture=True,
        ).stdout.splitlines()
    )
    if changed != set(ALLOWED_PATHS):
        raise SystemExit(
            "staged product-policy scope mismatch: "
            f"expected={sorted(ALLOWED_PATHS)}, actual={sorted(changed)}"
        )


def _verify_trigger_scope() -> None:
    """Require the trigger branch to contain only the two temporary files."""

    _run(
        "git",
        "merge-base",
        "--is-ancestor",
        EXPECTED_MAIN_PARENT,
        "HEAD",
    )
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
    patch = _run(
        "git",
        "diff",
        "--binary",
        REVIEWED_BASE,
        REVIEWED_CHILD,
        "--",
        *ALLOWED_PATHS,
        capture=True,
    ).stdout
    PATCH_PATH.write_text(_filter_reviewed_patch(patch), encoding="utf-8")
    _run("git", "apply", "--3way", "--index", str(PATCH_PATH))
    _run("git", "diff", "--cached", "--check")
    _verify_applied_tree()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
