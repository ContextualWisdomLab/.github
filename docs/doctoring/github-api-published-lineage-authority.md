# GitHub API evidence published-lineage authority

Status: Proposed repair evidence for `.github` PR #2279. Hosted exact-head security and independent review remain mandatory.

## Finding

The first published-lineage contract checked that the documentation named intended replacement SHAs and omitted two known unreachable candidates. That established expected spelling but not repository reachability. A 40-hex identifier can satisfy those assertions while referring to no commit published in the repository, so the contract did not make G-17's evidence lineage independently reconstructable.

Current-head review identified that gap and required the G-17 evidence identifiers themselves to resolve and belong to the current published branch ancestry.

## RED → repair

- Structural RED `c37db5405142da1d0fa2ae972cbacab28563c370` factors a G-17 evidence validator and adds a mutation control that substitutes the first evidence commit with the all-zero, commit-shaped identifier. The intentionally shape-only validator accepts that mutation, so the regression fails instead of giving false assurance.
- Minimal repair `b339370ed1e032527e504ca3500a2f0ca825ff77` keeps validation in the existing GitHub API authority contract. For every full SHA named in the single G-17 row it now requires both `git cat-file -e <sha>^{commit}` and `git merge-base --is-ancestor <sha> HEAD` to succeed. The negative mutation therefore fails closed, while the documented published evidence must be resolvable in current history.

The repair does not change either production HTTP client, credential handling, redirect policy, workflow threshold, or the standalone `$RUNNER_TEMP` CodeQL materialization boundary. It strengthens only executable evidence traceability.

## Invariants

1. G-17 has exactly one gap-register row.
2. Every full commit SHA named by that row resolves as a commit in the checked-out repository.
3. Every such evidence commit is an ancestor of the exact checked-out head; detached or unreachable object-store artifacts are not accepted as published lineage.
4. A syntactically valid but unreachable 40-hex identifier fails the contract.
5. Exact-head hosted CI/security gates and independent review remain distinct from this focused local invariant.

## Rejected alternatives

Checking only SHA syntax was rejected because it proves formatting rather than publication. Checking only that expected strings occur in Markdown was rejected because unreachable objects can still be named. GitHub API lookups were unnecessary for the repository-local invariant and would add network/credential authority to a test whose evidence is already in Git history.
