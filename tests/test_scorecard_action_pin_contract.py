"""Pin OpenSSF Scorecard to one immutable action SHA across workflows."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCORECARD_SHA = "2d1146689b8cda280b9bc96326124645441f03bc"
SCORECARD_TAG = "v2.4.4"
_PIN = re.compile(
    r"ossf/scorecard-action@([0-9a-f]{40}) # (v\d+\.\d+\.\d+)"
)


def test_scorecard_pr_and_analysis_share_one_action_sha() -> None:
    """CWE-829: PR and scheduled Scorecard must execute one immutable SHA.

    A Dependabot bump that updates only one workflow would analyze PRs with
    a different trusted action than the default-branch posture job.
    """
    shas: set[str] = set()
    tags: set[str] = set()
    for filename in ("scorecard-pr.yml", "scorecard-analysis.yml"):
        workflow = (REPO_ROOT / ".github/workflows" / filename).read_text(
            encoding="utf-8"
        )
        pins = _PIN.findall(workflow)
        assert pins, f"{filename} has no pinned ossf/scorecard-action"
        for sha, tag in pins:
            shas.add(sha)
            tags.add(tag)

    assert shas == {SCORECARD_SHA}
    assert tags == {SCORECARD_TAG}
