# Python source-tree test contract evidence

## Baseline and ownership

The starting central revision is
`c9052e607e5f3cc76e73207e7786b21500721b79`. CodeGraph indexed 300 files,
7,084 nodes and 16,560 edges. The query was "Reusable Python pytest uv workflow
inputs and unit test execution"; targeted workflow reads then established that
the existing reusable coverage gate owns a single-module quality shape and
the Python security workflow does not execute consumer unit tests.

The motivating consumer's 33 operational workflows had no PR test trigger or
pytest invocation. Its effective branch rules required review but no test
check. Static inspection of 56 test files found temporary/mock external
boundaries rather than required production services. This is static scope
evidence, not a hosted-runner or network-isolation result.

A subsequent local full-suite run failed on a runbook migration entry absent
from the original protected baseline. The repair belongs to the consumer;
central execution must expose such failures rather than omit that test file.
The consumer's `dev` dependencies are an optional extra, not a dependency group.
Its source import configuration permits testing without an editable build.

## Proposed experiment and acceptance

The owner candidate adds a fixed pytest execution path with native PR identity
validation and no deployment authority. The executable guard test must reject
missing/zero/mismatched PRs, non-PR events, invalid head identities and command
injection-shaped values before checkout. Workflow contract checks must retain
read-only permissions, immutable actions, locked sync, no implicit resync and
non-persistent checkout credentials.

The first candidate passed 16 local contract tests and actionlint. Independent
source review then found that grouping by the input PR number could cancel a
different PR before the admission guard executed. Bind concurrency to the native
event PR instead, with a unique run-ID fallback for subsequently rejected events;
test that exact expression rather than claiming to emulate GitHub scheduling.
The concurrency regression produced two failures before the correction; the
corrected candidate passed all 17 local contract cases, actionlint, Ruff and
`git diff --check`.

The full owner suite then passed 2,992 tests, one skip and 21 subtests in
873.43 seconds. A subsequent caller-scope assertion failed because the fixed
reusable name still shared a group across different caller workflows in one
repository. The final group uses `github.workflow` (the caller name); callers
must leave concurrency ownership here to avoid self-cancellation. That final
group change passed all 17 focused cases in 7.13 seconds and actionlint; the
preceding full-suite result must not be attributed to a later source revision.

Local regression results, workflow lint, actual Actions runs, independent review,
protected merge, immutable release and the first consumer run are separate
evidence stages. None of the latter stages is claimed by this proposal.
Do not add the consumer caller against a mutable branch or an unreviewed SHA.
After publication, verify the nested check name before making it a required
consumer check, and prove both failure propagation and success on real runs.

Context7 retrieval was unavailable because its monthly quota was exhausted;
DeepWiki had no index for this repository. GitHub Project #1 could not be read
because the current CLI token lacks `read:project`. No scope expansion or
credential change was attempted. The repository and official documentation
provided the implementation evidence; the Project was not updated.

## References

Astral. (n.d.). *Using uv in GitHub Actions*. Retrieved September 7, 2026, from
<https://docs.astral.sh/uv/guides/integration/github/>.
The documentation confirms setup-uv version/Python selection and project
sync/run behavior. The published setup-uv action has an MIT license.

GitHub. (n.d.). *Reuse workflows*. Retrieved September 7, 2026, from
<https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows>.
Reusable workflow inputs are explicit, nested permissions cannot increase,
and commit-SHA references provide the most stable dependency binding.

GitHub. (n.d.). *Reusing workflow configurations*. Retrieved September 7, 2026,
from <https://docs.github.com/en/actions/reference/workflows-and-actions/reusing-workflow-configurations>.
The reusable workflow receives the caller's `github.workflow` value; using
the same cancellation group in both layers can cancel the caller itself.
