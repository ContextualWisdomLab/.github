#!/usr/bin/env python3
"""Apply the bounded PR 743 quality-regression repair.

This temporary branch repair script modifies only reviewed paths and fails closed
when the expected exact source fragments have moved. The one-shot workflow runs
all quality gates before committing and deletes this script from the verified
final tree.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: str, old: str, new: str) -> None:
    """Replace exactly one reviewed fragment in *path* or terminate."""
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one reviewed fragment, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def insert_once(path: str, marker: str, addition: str) -> None:
    """Insert *addition* immediately before one exact *marker* if absent."""
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if addition in text:
        return
    count = text.count(marker)
    if count != 1:
        raise SystemExit(f"{path}: expected one insertion marker, found {count}")
    target.write_text(text.replace(marker, addition + marker, 1), encoding="utf-8")


def verify_git_ownership_repair() -> None:
    """Require the concurrent hermetic Git ownership repair on current head."""
    text = (ROOT / "tests/test_opencode_agent_contract.py").read_text(
        encoding="utf-8"
    )
    required = (
        "def test_sandbox_git_config_env_trusts_only_the_validated_worktree",
        '"GIT_CONFIG_NOSYSTEM": "1"',
        '"GIT_CONFIG_GLOBAL": "/dev/null"',
        '"GIT_CONFIG_KEY_0": "safe.directory"',
        '"GIT_CONFIG_VALUE_0": str(worktree)',
        'assert configured.stdout.splitlines() == [str(worktree)]',
        'assert "*" not in configured.stdout',
    )
    missing = [needle for needle in required if needle not in text]
    if missing:
        raise SystemExit(
            "tests/test_opencode_agent_contract.py: current hermetic ownership "
            f"repair is incomplete; missing {missing!r}"
        )


def repair_strix_legacy_default() -> None:
    """Migrate only the retired implicit NIM default before fallback gating."""
    path = ".github/workflows/strix.yml"
    current_marker = (
        'if [ "$strix_model" = '
        '"nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b" ]; then'
    )
    text = (ROOT / path).read_text(encoding="utf-8")
    if current_marker in text:
        return
    replace_once(
        path,
        '''          if [ -z "$STRIX_MODEL_REQUESTED" ] && [ "$strix_model" = "nvidia_nim/nvidia/nemotron-3-super-120b-a12b" ] && [ -z "${STRIX_NVIDIA_NIM_API_KEY:-}" ]; then
            strix_model="gpt-5.6-luna"
          fi
''',
        '''          if [ -z "$STRIX_MODEL_REQUESTED" ]; then
            if [ "$strix_model" = "nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b" ]; then
              strix_model="nvidia_nim/nvidia/nemotron-3-super-120b-a12b"
            fi
            if [ "$strix_model" = "nvidia_nim/nvidia/nemotron-3-super-120b-a12b" ] && [ -z "${STRIX_NVIDIA_NIM_API_KEY:-}" ]; then
              strix_model="gpt-5.6-luna"
            fi
          fi
''',
    )


def update_changelog() -> None:
    """Record both exact-head regression repairs under Unreleased."""
    path = ROOT / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8")
    addition = (
        "- Isolated Git protected configuration in the sandbox `safe.directory` "
        "regression so hosted-runner trust defaults cannot mask the exact validated "
        "worktree allowlist contract.\n"
        "- Normalized the retired implicit NVIDIA NIM Strix default to the current "
        "Nemotron 3 Super model before credential fallback selection, without "
        "accepting an explicitly requested retired model.\n"
    )
    if addition in text:
        return
    marker = "### Fixed\n\n"
    if text.count(marker) != 1:
        raise SystemExit("CHANGELOG.md: expected one Unreleased Fixed marker")
    path.write_text(text.replace(marker, marker + addition, 1), encoding="utf-8")


def update_doctoring() -> None:
    """Document the Git and Strix decisions with APA 7th references."""
    git_section = '''## Hermetic Git ownership-boundary verification

The full-suite regression for the OpenCode coverage sandbox asks Git to expose
only one command-scope `safe.directory` value for the validated worktree. A
hosted runner may carry system or global trust entries, so the test disables
system configuration and points global configuration at the null device before
asserting the exact configured value, absence of the sibling repository, and
absence of the wildcard `*`. This measures the production boundary rather than
the runner image's ambient policy. Git 2.54.0 resolves `safe.directory` through
protected configuration, so the isolation is current and version-explicit.

'''
    insert_once(
        "docs/doctoring/trusted-uv-lock-materialization.md",
        "## References\n",
        git_section,
    )
    git_record = ROOT / "docs/doctoring/trusted-uv-lock-materialization.md"
    git_text = git_record.read_text(encoding="utf-8")
    references = '''
The Git Project. (2026a). *git-config documentation (Version 2.54.0)*.
https://git-scm.com/docs/git-config/2.54.0

The Git Project. (2026b). *setup.c (Version 2.54.0)* [Source code].
https://github.com/git/git/blob/v2.54.0/setup.c
'''
    if references.strip() not in git_text:
        git_record.write_text(
            git_text.rstrip() + "\n\n" + references.strip() + "\n",
            encoding="utf-8",
        )

    strix_section = '''## Legacy implicit-default migration

An empty `STRIX_MODEL_REQUESTED` marker distinguishes a workflow-owned default
from an operator's explicit model selection. If an older caller still supplies
the retired implicit Nemotron 3 Ultra default, the gate first normalizes it to
the current Nemotron 3 Super default. It then applies the ordinary credential
rule: use NVIDIA NIM when its scoped key exists, or use the established direct
OpenAI fallback when the implicit public default has no NVIDIA credential.

The normalization never applies when a caller explicitly requests the retired
model. Explicit unsupported selections continue to fail closed, so backward
compatibility for inherited defaults does not broaden the accepted operator
surface.

'''
    insert_once(
        "docs/doctoring/strix-nvidia-nim-not-found-fallback.md",
        "## Verification contract\n",
        strix_section,
    )


def main() -> None:
    """Apply or verify all bounded repairs on the exact trigger commit."""
    verify_git_ownership_repair()
    repair_strix_legacy_default()
    update_changelog()
    update_doctoring()


if __name__ == "__main__":
    main()
