"""Route the central fix-scheduler dispatch job to the control pool safely.

The dispatch job only reads the GitHub API and dispatches autofix. It waited
up to 12 h on the saturated hosted `ubuntu-24.04` queue on 2026-09-29 while
the `cwlab-control` runners were idle. It may use that trusted pool only when
the caller is the central main hourly workflow, and it must never check out
pull-request head content there.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
FIX_SCHEDULER = REPO_ROOT / ".github/workflows/pr-review-fix-scheduler.yml"
AUTOFIX = REPO_ROOT / ".github/workflows/pr-review-autofix.yml"
CENTRAL_CALLER = (
    "ContextualWisdomLab/.github/.github/workflows/hourly-review-repair.yml@refs/heads/main"
)
CONTROL = (
    "fromJSON('{\"group\":\"CWL central control\","
    "\"labels\":[\"self-hosted\",\"linux\",\"x64\",\"cwlab-control\"]}')"
)


def _job() -> dict:
    return yaml.safe_load(FIX_SCHEDULER.read_text(encoding="utf-8"))["jobs"][
        "dispatch-review-fixes"
    ]


def test_control_pool_only_for_central_main_caller() -> None:
    runs_on = _job()["runs-on"]
    assert runs_on == (
        f"${{{{ github.workflow_ref == '{CENTRAL_CALLER}' && {CONTROL} "
        "|| fromJSON('[\"self-hosted\",\"linux\",\"x64\",\"cwlab-ci-isolated\"]') }}"
    )


def test_dispatch_job_never_checks_out_pull_request_content() -> None:
    text = FIX_SCHEDULER.read_text(encoding="utf-8")
    assert "pull_request.head" not in text
    checkouts = [s for s in _job()["steps"] if "actions/checkout" in str(s.get("uses", ""))]
    assert len(checkouts) == 1
    with_ = checkouts[0]["with"]
    assert with_["repository"] == "${{ steps.trusted_source.outputs.repository }}"
    assert with_["ref"] == "${{ steps.trusted_source.outputs.sha }}"
    assert with_["persist-credentials"] is False


def test_dispatched_autofix_stays_off_the_control_pool() -> None:
    """Autofix runs PR code, so it must keep an isolated runner."""
    assert "cwlab-control" not in AUTOFIX.read_text(encoding="utf-8")
    assert "CWL central control" not in AUTOFIX.read_text(encoding="utf-8")
