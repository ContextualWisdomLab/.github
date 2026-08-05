"""Static contracts for the NVIDIA NIM merge-conflict repair path."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = (
    REPOSITORY_ROOT / ".github/workflows/nvidia-nim-pr-review-autofix.yml"
)


def _validation_step() -> str:
    """Return the worker's repair validation step as a bounded text slice."""

    workflow = WORKER_PATH.read_text(encoding="utf-8")
    start_marker = "      - name: Validate repair scope and syntax\n"
    end_marker = "\n      - name: Commit and push exact-head repair\n"
    assert start_marker in workflow
    assert end_marker in workflow
    return workflow.split(start_marker, 1)[1].split(end_marker, 1)[0]


def test_conflict_files_are_checked_without_shell_word_splitting() -> None:
    """Allowed paths may contain spaces and must never be expanded via command substitution."""

    step = _validation_step()

    assert 'for changed_file in "${changed_files[@]}"; do' in step
    assert 'if [ -f "$changed_file" ] && grep -nE' in step
    assert '$(cat "$ALLOWED_PATHS_FILE")' not in step
    assert "grep -RInE" not in step


def test_resolved_conflicts_are_staged_before_unmerged_index_check() -> None:
    """Removing conflict markers is insufficient until the index stages each resolution."""

    step = _validation_step()
    stage = step.index('git add -- "${changed_files[@]}"')
    unmerged_check = step.index('git diff --name-only --diff-filter=U', stage)

    assert stage < unmerged_check
    assert "Merge conflicts remain unresolved" in step


def test_deleted_conflict_resolution_is_supported() -> None:
    """A deliberately deleted conflicted file should skip marker scanning but still stage."""

    step = _validation_step()

    assert 'if [ -f "$changed_file" ]' in step
    assert 'git add -- "${changed_files[@]}"' in step
