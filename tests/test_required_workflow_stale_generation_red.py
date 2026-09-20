"""Pin the stale-generation cancellation defect in central required workflows.

A workflow-level PR-number concurrency group is evaluated before any job can
revalidate the live pull-request head.  With ``cancel-in-progress: true``, a
delayed predecessor-head event can therefore cancel newer current-head
evidence before the older run reaches its own stale-head guard.

This contract is deliberately only the first structural RED.  Adding a bare
head SHA to a group is not complete acceptance: an owner repair must also
retire obsolete predecessor generations through live-revalidated cleanup so
old work cannot leak indefinitely.  That cleanup is tracked by the canonical
queue/admission owner rather than being invented in consumer repositories.
"""

from pathlib import Path
import re

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
HEAVY_REQUIRED_WORKFLOWS = (
    "agent-review-runtime-quality-ci.yml",
    "codeql-pr.yml",
    "python-security.yml",
    "sast-semgrep.yml",
    "security-scan.yml",
)
WORKFLOW_CONCURRENCY_BLOCK = re.compile(
    r"(?ms)^concurrency:\s*\n(?P<body>(?:^[ \t]+.*\n?)+)"
)


def _workflow_text(filename: str) -> str:
    """Read one central required-workflow definition from the repository tree."""
    return (REPO_ROOT / ".github" / "workflows" / filename).read_text(
        encoding="utf-8"
    )


def _workflow_concurrency_block(filename: str) -> str:
    """Return only the top-level concurrency block for one workflow."""
    match = WORKFLOW_CONCURRENCY_BLOCK.search(_workflow_text(filename))
    assert match is not None, f"{filename} has no workflow-level concurrency block"
    return match.group("body")


@pytest.mark.parametrize("filename", HEAVY_REQUIRED_WORKFLOWS)
def test_native_pr_cancellation_cannot_cross_exact_head_generations(filename: str) -> None:
    """PR-wide native cancellation must not let an older head evict the live head.

    GitHub resolves workflow concurrency before jobs run, so a later in-job
    live-head check cannot repair a cancellation that already happened.  Any
    heavy required workflow that keeps native ``cancel-in-progress: true``
    therefore has to isolate pull-request generations by the exact submitted
    head SHA.  This is necessary but not sufficient: predecessor cleanup still
    needs a separately proven, live-revalidated owner path.
    """
    block = _workflow_concurrency_block(filename)
    if not re.search(r"(?m)^\s*cancel-in-progress:\s*true\s*$", block):
        return

    assert "github.event.pull_request.head.sha" in block, (
        f"{filename} uses workflow-level cancel-in-progress on a PR-wide group; "
        "a delayed predecessor generation can cancel current-head evidence "
        "before any job-level live-head check runs"
    )
