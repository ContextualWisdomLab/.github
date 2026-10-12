# fast-mlsirm product CI as a central reusable workflow

Date: 2026-09-18

## What moved

`.github/workflows/fast-mlsirm-ci.yml` now holds the job bodies that existed
only in `ContextualWisdomLab/fast-mlsirm/.github/workflows/ci.yml`: the
CPython 3.12/3.14 maturin editable-install matrix with the Rust-primary backend
assertion, the Rust workspace plus PyO3 manifest tests, the bounded
software-Vulkan GPU parity lane, the Atheris lane, and the wheel build with
release-acceptance and sales-readiness gates.

The consumer keeps its own triggers, concurrency group, and draft/closed
policy, because a reusable workflow cannot own `on.pull_request` filters.

## Why, and what this does not claim

This is maintenance consolidation: one reviewed copy of the pinned action SHAs
and the hash-locked install contract instead of a copy that drifts silently.

It is **not** a queue fix. `docs/adr/0030-ci-centralization-scope-given-plan-ceiling.md`
measured that the org bottleneck is the plan-level concurrent-job ceiling, and
warned that a consolidation project pursued as a queue remedy solves the wrong
layer at real cost. That warning is the reason for the shape below.

## Shape: no stub jobs

The obvious way to preserve the consumer's pinned check names — `python`,
`rust`, `package`, `fuzz` — is a name-preserving stub job per lane that
re-exports the reusable job's result. That was rejected: each stub is a real
runner job, so four stubs would add four jobs to every PR head under a fixed
ceiling, making the measured problem slightly worse in exchange for a
cosmetic name.

Instead the consumer calls this workflow from a single `uses:` job. A caller
job that only calls a reusable workflow consumes no runner of its own, so the
consumer's job count per PR head is unchanged. The cost is a **rename**: check
contexts become `<caller job> / <job here>`.

## The `python` aggregate job is gone, on purpose

The consumer's `ci.yml` published its required `python` context from an
aggregate job that did nothing but `echo` the matrix result and `test` it,
joined to the matrix by a `needs:` edge. `actions-capacity-root-cause-20260917.md`
measured what such an edge costs here: on run 34931908846, 21 minutes of actual
job execution stretched across 13h57m of wall time, 97.5% of it inter-job queue
wait, and `naruon#1528` spent 22h41m queueing for two single-`echo` jobs chained
for ordering alone.

So this workflow has no aggregate and no `needs:` edge at all. Every lane is
independent. The consumer requires `python (3.12)` and `python (3.14)` directly.
The cost is one branch-protection update whenever the interpreter list changes;
the saving is a full queue wait on every PR, plus one runner job.

## The rename is the risky part

`docs/adr/0024-dependency-review-reusable-workflow-consolidation.md` records a
consumer's branch protection deadlocking on exactly this. fast-mlsirm's live
required contexts on `main` at the time of this change were:

```
Analyze (actions)  scan-pr-queue  dependency-review  osv-scan  trivy-fs
scorecard  required-workflow-bootstrap  coverage-evidence  opencode-review
python  rust  package  fuzz
```

`gpu-smoke` is **not** required — an earlier design pass assumed it was, and a
live read corrected that. Of the rest, only `python`, `rust`, `package`, and
`fuzz` come from the workflow being migrated. Those four contexts must be
swapped in the same window as the consumer's caller PR, or every fast-mlsirm PR
blocks on required checks that nothing produces any more. `python` in
particular has no direct successor: it is replaced by the two matrix-leg
contexts, for the capacity reason above.

## Sequencing

1. This PR lands the reusable on protected `main`. No consumer references it,
   so nothing can break yet.
2. Before adoption, fast-mlsirm generates and reviews
   `requirements/fuzz.txt` with hashes for every fuzz dependency. The reusable
   workflow fails closed if that product-owned lock is absent; it does not
   resolve the `fuzz` extra from the registry at run time.
3. The consumer's caller PR pins `uses:` to this merge commit SHA — never
   `@main` (ADR 0023).
4. Branch protection swaps the four context names in the same window.
5. Rollback is a revert of the consumer PR plus restoring the four context
   names; this file can stay.

Every checkout also sets `persist-credentials: false`. Product build, test,
fuzz, and packaging code therefore cannot recover a caller token from the
checkout's Git configuration.

## Do not

- Do not add this workflow to org ruleset `18156473`. Required-workflow
  admission scans the entire file, and this one builds and runs product code
  (ADR 0025).
- Do not let a caller pass shell. Inputs are bounded data and capability flags
  (ADR 0023), and `tests/test_fast_mlsirm_ci_reusable_workflow_contract.py`
  asserts no input reaches a `run:` body.
- Do not migrate the consumer's `codeql.yml`, `publish-pypi.yml`, or
  `release-tag.yml`. The first publishes a pinned required context that a
  required workflow may not produce; the latter two are bound to the consumer's
  filename via `gh workflow run publish-pypi.yml` and to its PyPI publisher
  configuration.
