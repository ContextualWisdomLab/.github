"""Contract tests for OSV scanner action version traceability.

A commercial buyer reading ``security-scan.yml`` must see the same
release the pinned SHA actually embeds. The failed one-shot repair on
ContextualWisdomLab/.github#921 left four ``# v2.3.8`` comments on SHA
``f4cfcc01edc9c8b756a9b873b7a623ca674da51e`` (upstream v2.5.0) and a
``contents: write`` workflow that Scorecard Token-Permissions scored 0.
"""

from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_DIRECTORY = _REPOSITORY_ROOT / ".github" / "workflows"
_WORKFLOW_PATH = _WORKFLOW_DIRECTORY / "security-scan.yml"
_ONE_SHOT_PATH = _WORKFLOW_DIRECTORY / "one-shot-pr921-osv-version-comments.yml"
_ACTION_SHA = "f4cfcc01edc9c8b756a9b873b7a623ca674da51e"
_EMBEDDED_RELEASE = "v2.5.0"
_STALE_RELEASE = "v2.3.8"
_PIN_PREFIX = f"google/osv-scanner-action/osv-scanner-action@{_ACTION_SHA}"


def _pinned_osv_lines(workflow: str) -> list[str]:
    """Return stripped ``uses:`` lines that pin the current OSV scanner SHA."""

    return [
        line.strip()
        for line in workflow.splitlines()
        if _PIN_PREFIX in line
    ]


def test_osv_scanner_action_pin_reports_embedded_release() -> None:
    """Every pinned scanner invocation identifies upstream release v2.5.0."""

    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    pinned_lines = _pinned_osv_lines(workflow)

    assert len(pinned_lines) == 4
    assert all(line.endswith(f"# {_EMBEDDED_RELEASE}") for line in pinned_lines)
    assert f"@{_ACTION_SHA} # {_STALE_RELEASE}" not in workflow


def test_osv_version_comment_matches_real_workflow_layout() -> None:
    """The four production scanner steps keep SHA, args, and comment aligned."""

    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    expected = f"uses: {_PIN_PREFIX} # {_EMBEDDED_RELEASE}"

    assert workflow.count(expected) == 4
    assert "scan-args:" in workflow
    assert workflow.count("continue-on-error: true") >= 4
    assert "contents: write" not in workflow


def test_pr921_one_shot_write_workflow_is_absent() -> None:
    """Completed Scorecard-failing one-shot writers must not remain mergeable."""

    assert not _ONE_SHOT_PATH.exists()
    leftover = list(_WORKFLOW_DIRECTORY.glob("one-shot-pr921-*.yml"))
    assert leftover == []
