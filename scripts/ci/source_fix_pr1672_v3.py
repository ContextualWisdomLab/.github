#!/usr/bin/env python3
"""Run PR #1672's owner repair and normalize touched UTF-8 files for git diff hygiene."""
from __future__ import annotations

import runpy
from pathlib import Path

# Publication bridge retrigger: source semantics remain deterministic; the V3
# workflow now publishes only non-workflow files with its branch-scoped token.
PRIMARY = Path("scripts/ci/source_fix_pr1672_v2.py")
SELF = Path("scripts/ci/source_fix_pr1672_v3.py")
WORKFLOW_V2 = Path(".github/workflows/source-fix-pr1672-single-request-v2.yml")
WORKFLOW_V3 = Path(".github/workflows/source-fix-pr1672-single-request-v3.yml")
COMPLETED_TIMEOUT_HELPERS = (
    Path("scripts/ci/source_fix_pr1714_no_model_job_timeout.py"),
    Path("scripts/ci/source_fix_pr1715_no_model_job_timeout.py"),
    Path(".github/workflows/source-fix-pr1714-no-model-job-timeout.yml"),
    Path(".github/workflows/source-fix-pr1715-no-model-job-timeout.yml"),
)
NORMALIZE = (
    Path("scripts/ci/noema_review_gate.py"),
    Path(".github/actions/noema-review/two_phase.py"),
    Path("tests/test_noema_review_gate.py"),
    Path("tests/test_noema_model_output_failure_classification.py"),
    Path("tests/test_noema_repair_attempt_telemetry.py"),
    Path("docs/product-technical-gap-baseline.md"),
    Path("CHANGELOG.md"),
)


def main() -> None:
    """Apply the deterministic repair, retire completed helpers, and normalize text."""
    runpy.run_path(str(PRIMARY), run_name="__main__")
    for path in COMPLETED_TIMEOUT_HELPERS:
        path.unlink(missing_ok=True)
    for path in NORMALIZE:
        if path.exists():
            path.write_text(path.read_text(encoding="utf-8").rstrip() + "\n", encoding="utf-8")
    SELF.unlink(missing_ok=True)
    WORKFLOW_V2.unlink(missing_ok=True)
    WORKFLOW_V3.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
