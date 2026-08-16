# PR review and merge scheduler

## Terminal result policy

The scheduler isolates a failed mutation or dispatch to its pull request and
continues the bounded scan. It emits the human-readable lines, job summary, and
versioned JSON decision payload for every inspected pull request before choosing
the process result.

An `action_error` is a material execution failure, so one or more such decisions
produce a non-zero terminal result after the summary is written. Policy outcomes
such as `wait`, `block`, `skip`, and deferred capacity do not make an otherwise
healthy scheduler invocation fail.

A targeted single-pull-request run and the organization sweep use the same
terminal policy. The organization sweep preserves each repository's captured
summary, records that repository as failed, finishes its bounded repository
walk, and then fails the job. A repository is classified as unavailable only
when the scheduler fails before emitting its versioned structured payload and
the error proves that the sweep credential cannot read the repository.

This separation keeps ordinary governance waits visible without reporting them
as incidents, while preventing a failed merge, update, auto-merge, or review
dispatch from producing a passing workflow result.

## References (APA 7th)

GitHub. (n.d.). *Workflow commands for GitHub Actions*. GitHub Docs. Retrieved
August 16, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands-for-github-actions

GitHub. (n.d.). *Workflow syntax for GitHub Actions*. GitHub Docs. Retrieved
August 16, 2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax
