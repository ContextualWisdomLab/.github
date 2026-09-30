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

The next exact-head Agent Mention Router Quality run exposed the same boundary
at a second consumer: it executed the complete repository suite while
installing only the OpenCode lock, so 13 Noema tests failed collection on
missing `defusedxml`. That workflow now declares the Noema lock as a trigger,
cache input, and hash-required install. The concurrent Security gate also found
five known vulnerabilities in checked-in runtime/fixture locks; `fast-uri`,
`ip-address`, and PyO3 are refreshed to 3.1.8, 10.7.2, and 0.29.3. Local
evidence is a clean production `npm audit`, a passing locked Cargo fixture, and
seven passing Agent Mention workflow contracts. Coverage and hosted admission
remain fail-closed.

The next Python Security run found newly published urllib3 and PyJWT advisories
in the generated pip-audit and Strix locks. The source inputs now explicitly
pin urllib3 2.8.0 and PyJWT 2.15.0 so regeneration cannot silently return to
the vulnerable transitive versions. Both regenerated full locks pass
`pip-audit` with no known vulnerabilities, and four source-to-lock contracts
pass. This is dependency repair only; it does not convert the Draft PR or the
separate coverage failure into accepted evidence.

Exact-head Trusted uv run `36775249483`, job `110091412037`, then exposed a
separate checkout-depth defect. The complete repository suite executes G-17's
published-lineage contract, which resolves every documented evidence commit
and requires it to be an ancestor of the current HEAD. The Trusted uv job used
the checkout action's shallow default, so published ancestors were absent from
the local object database even though they are reachable from protected
`main`. The Agent Mention full-suite gate already used `fetch-depth: 0` and did
not reproduce that false negative.

The repair keeps the ancestry contract fail closed and gives the Trusted uv
gate the comparison history it is required to inspect. A workflow regression
asserts exactly one `fetch-depth: 0`; credentials remain non-persistent and the
exact PR head remains explicitly selected. The same hosted run also exposed
the baseline's pre-existing missing `APA 7th references` marker, so the live
baseline now carries the heading and directly relevant primary Git/GitHub
references instead of weakening its governance test.
