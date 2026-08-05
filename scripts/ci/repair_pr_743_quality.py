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


def repair_git_ownership_test() -> None:
    """Isolate protected Git configuration in the ownership-boundary test."""
    replace_once(
        "tests/test_opencode_agent_contract.py",
        '''    base_env = {
        **os.environ,
        "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1",
    }
''',
        '''    isolated_home = tmp_path / "git-config-home"
    isolated_home.mkdir()
    base_env = {
        **os.environ,
        "GIT_TEST_ASSUME_DIFFERENT_OWNER": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "HOME": str(isolated_home),
        "XDG_CONFIG_HOME": str(isolated_home / "xdg"),
    }
''',
    )


def repair_strix_legacy_default() -> None:
    """Migrate only the retired implicit NIM default before fallback gating."""
    replace_once(
        ".github/workflows/strix.yml",
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
        "- Isolated Git system and global protected configuration in the sandbox "
        "`safe.directory` regression so hosted-runner trust defaults cannot mask "
        "an unrelated repository, while preserving the exact validated worktree "
        "allowlist contract.\n"
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

The full-suite regression for the OpenCode coverage sandbox deliberately asks Git
to treat two temporary repositories as differently owned. Git reads
`safe.directory` only from protected configuration scopes. A hosted runner may
therefore carry a system or global trust entry that makes both repositories look
safe and turns the negative control into a false pass.

The test supplies an isolated `HOME` and `XDG_CONFIG_HOME`, disables system
configuration with `GIT_CONFIG_NOSYSTEM`, and points global configuration at the
null device before adding one command-scope `safe.directory` entry. The selected
worktree must succeed, while a sibling repository must still fail with dubious
ownership. This measures the production boundary rather than the runner image's
ambient policy. Git 2.54.0 retains the test-only different-owner switch and
resolves `safe.directory` through protected configuration, so the isolation is
both current and version-explicit.

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
    """Apply all bounded repairs to the checked-out exact trigger commit."""
    repair_git_ownership_test()
    repair_strix_legacy_default()
    update_changelog()
    update_doctoring()


if __name__ == "__main__":
    main()
