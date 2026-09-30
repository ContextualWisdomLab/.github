# Trusted uv PyYAML collection boundary

## Problem

After #2040 was ordinarily reconciled with protected `main`, exact-head Trusted
uv run `36771261554` failed collection before the complete repository gate:
`tests/test_control_workflows_skip_draft_prs.py`,
`tests/test_opencode_coverage_runner_hygiene.py`,
`tests/test_opencode_pr_head_worktree_reuse.py`, and
`tests/test_pr_review_fix_scheduler_control_runner.py` import `yaml`, while the
hash-locked quality environment omitted PyYAML.

## Repair

The canonical OpenCode CI input now pins `pyyaml==6.0.3`; its generated
`--require-hashes` lock is refreshed by
`scripts/ci/compile_opencode_review_lock.sh`. A focused contract requires the
dependency at the same owner boundary. No unpinned install, scanner exclusion,
or workflow gate weakening is introduced.

## Evidence and remaining boundary

The new contract failed before the dependency change and the affected 11-file
surface passes 449 tests after it. The full suite then collects and executes
5,179 tests, 6 skips, and 40 subtests. Its coverage report remains below the
mandatory 100% threshold because inherited production paths still contain 178
uncovered statements; that distinct failure remains fail-closed and keeps
#2040 Draft pending owner coverage repair, hosted exact-head evidence, and an
independent current-head review.
