# Operability: CWL automation control plane

Status: normative service-level and operating contract. Targets apply after the
relevant signal is measurable; absence of telemetry is reported as unknown,
not success.

## Service model

The control plane is an asynchronous governance service. It is healthy when it
turns eligible events into current, attributable evidence and safe guarded
actions while continuing unrelated lanes during local deferrals. It is not
measured by the number of comments, retries, polls, or commits produced.

## SLIs and targets

| SLI | Measurement | Policy target |
|---|---|---|
| Snapshot integrity | decisions whose repository/PR/source-head/base/live-base tuple is complete and current | 100% |
| Guarded mutation | writes/merges with a freshly verified expected head and legitimate authority | 100% |
| Evidence attribution | required evidence records with producer, type, revision, and run identity | 100% |
| Secret containment | published logs/artifacts with no credential disclosure | 100% |
| Work conservation | eligible runs with safe writable work that produce one substantive verified mutation | 100% |
| Review dispatch latency | eligible non-deferred review requests dispatched within two scheduler sweep periods (30 minutes at the current fifteen-minute cadence) | at least 99% over 30 days |
| Protected-main acceptance | central operational fixes with real-consumer evidence before closure | 100% |
| Fleet enrollment visibility | enrolled repositories covered by a current read-only audit | at least 99% over 24 hours |

The error budget never permits bypassing identity, integrity, secret,
independent-review, ruleset, or final head-match controls. Availability targets
may instead defer model-dependent work or reduce concurrency.

## Required telemetry

Every run or handoff should emit bounded structured fields:

- automation mode, run/job/attempt, repository, PR, source ref and head;
- base branch, observed live-base SHA, snapshot time, and dependency identity;
- evidence type, producer, authority class, conclusion, and freshness;
- retry class, attempt/budget, deferral reason, next eligible trigger, and
  handoff owner;
- writer-lease key and lease result for mutation paths;
- expected-head result, merge/release/deploy actor, and final transaction id;
- consumer repository/run identity for operational acceptance.

Credential values, raw authorization headers, installation tokens, and
unbounded command output are never telemetry fields.

## Dashboards and alerts

Operators need views by repository and workflow for queue age, deferred reason,
provider health, API error class, stale-evidence rejection, writer contention,
ruleset drift, unresolved review state, redaction events, and acceptance debt.
Alerts should fire on unauthorized mutation attempts, credential disclosure,
protected-ref surprises, repeated permanent failures, fleet-wide dispatch
failure, audit drift, or an accepted incident without consumer evidence.

One pending PR or provider wait does not page the fleet. Repeated local failure
creates an issue/handoff with exact identity; widespread or security-impacting
failure activates [INCIDENT_RUNBOOK.md](INCIDENT_RUNBOOK.md).

## Queue and capacity behavior

Queue identity is `(repository, PR, exact head, dependency state, operation)`.
After one fresh observation, an unchanged external wait is deferred. The loop
continues a different repository, branch, PR, product gap, documentation gap,
or read-only audit lane. An unchanged item is revisited only after external
state changes, another substantive acceptance/mutation occurs, or a final
sweep is due.

Mention invocation artifacts currently provide at-most-once forwarding for 30
days. A claim written before a failed forward is a dead-letter, not completed
work; the operator uses a new trusted comment until the recoverable claim state
tracked in `ContextualWisdomLab/.github#893` is implemented.

Provider pools have attempt and wall-clock budgets. Capacity exhaustion does
not synthesize review evidence. GitHub API backoff honors classified transient
responses while permanent authorization or integrity errors surface at once.

## Release, rollback, and acceptance

Central changes use exact-head PR gates, protected-default-branch integration,
and staged real-consumer exercise. Rollback selects a known-good protected
revision through a reviewed revert or explicit caller pin; it never force-moves
protected refs or disables rulesets as a convenience.

After rollback, verify event delivery, evidence attribution, redaction,
expected-head behavior, and one representative consumer. Reopen the incident
if the recovery path only passes in the central repository.

## Ownership and handoff

Each deferred or incident item records the current owner, exact target, evidence
already collected, last material state change, next valid trigger, and the
action that remains unauthorized or unsafe. Handoffs cannot transfer a writer
lease implicitly. A new actor acquires and revalidates ownership before write.

## Routine reviews

- Each run: current queue identity, lease, evidence freshness, and useful
  diagnostics.
- Daily: fleet enrollment/drift and prolonged deferrals.
- Weekly: provider/retry distributions, stale-evidence rejection, acceptance
  debt, and expiring exceptions.
- After every incident or architecture change: SLI definition, threat model,
  runbook, test matrix, and ADR supersession review.
