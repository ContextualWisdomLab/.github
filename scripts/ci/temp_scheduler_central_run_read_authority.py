#!/usr/bin/env python3
"""Materialize the central stale-review run read-authority repair on protected-main source."""

from __future__ import annotations

from pathlib import Path


SCHEDULER = Path("scripts/ci/pr_review_merge_scheduler.py")
CHANGELOG = Path("CHANGELOG.md")
SELF = Path("scripts/ci/temp_scheduler_central_run_read_authority.py")
WORKFLOW = Path(".github/workflows/_temp_scheduler_central_run_read_authority.yml")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace exactly one reviewed source block and fail closed on layout drift."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one exact source block, found {count}")
    return text.replace(old, new, 1)


def repair_scheduler() -> None:
    """Route central Actions run reads through the existing dispatch credential boundary."""
    source = SCHEDULER.read_text(encoding="utf-8")
    old = '''def _fresh_active_run_for_cancellation(run_repo: str, run_id: str) -> dict[str, Any]:\n    """Return fresh active workflow-run evidence immediately before cancellation."""\n    payload = gh_api_json(f"repos/{run_repo}/actions/runs/{run_id}")\n'''
    new = '''def _fresh_active_run_for_cancellation(run_repo: str, run_id: str) -> dict[str, Any]:\n    """Return fresh active workflow-run evidence with repository-correct read authority."""\n    central_repo = (os.environ.get("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY") or "").strip()\n    use_dispatch_authority = bool(\n        central_repo and run_repo == validate_github_repository(central_repo)\n    )\n    reader = gh_api_json_via_dispatch_token if use_dispatch_authority else gh_api_json\n    payload = reader(f"repos/{run_repo}/actions/runs/{run_id}")\n'''
    SCHEDULER.write_text(
        replace_once(source, old, new, "central stale-review run credential routing"),
        encoding="utf-8",
    )


def update_changelog() -> None:
    """Record the control-plane credential-boundary repair under Unreleased."""
    text = CHANGELOG.read_text(encoding="utf-8")
    bullet = (
        "- **Bind stale-review run revalidation to repository-correct credentials.** "
        "Central `repository_dispatch` Actions evidence now uses the existing central dispatch "
        "read authority while direct target-repository runs retain target read authority.\n"
    )
    if bullet in text:
        return
    anchor = "## [Unreleased]\n"
    if text.count(anchor) != 1:
        raise RuntimeError("CHANGELOG Unreleased anchor drifted")
    CHANGELOG.write_text(text.replace(anchor, anchor + bullet, 1), encoding="utf-8")


def main() -> None:
    """Apply the production repair, update release traceability, and retire one-shot sources."""
    repair_scheduler()
    update_changelog()
    SELF.unlink(missing_ok=True)
    WORKFLOW.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
