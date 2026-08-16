# Operability and service objectives

Status: accepted baseline; telemetry gaps are explicit
Last reviewed: 2026-08-09

## 1. Service model

The control plane is a set of GitHub-hosted, event-driven and scheduled workflows rather than one continuously running service. Its availability depends on GitHub APIs/Actions, runner capacity, external review providers, package/tool sources, organization policy, and eligible human reviewers. Degradation of one dependency must not idle unrelated maintenance work.

## 2. Service-level indicators and targets

Targets are design objectives, not claims of achieved performance. [TRACEABILITY.md](TRACEABILITY.md) marks missing telemetry.

| SLI | Proposed target | Measurement |
|---|---|---|
| Exact-revision binding | 100% of gate and mutation records name exact source and workflow revision | contract tests plus run receipts |
| Unauthorized/stale mutation | 0 accepted writes after expected head/base mismatch | scheduler/autofix rejection counters and tests |
| Credential disclosure | 0 known credentials in published evidence | adversarial tests, secret scanning, incident reports |
| Deterministic gate completion | 99% within 30 minutes excluding declared GitHub outage/queue saturation | run timestamps by workflow and repository |
| Model review completion | 95% within 6 hours; no correctness trade for latency | dispatch-to-terminal duration by provider/class |
| Queue starvation | 0 executable item left untouched across two hourly sweeps | maintainer continuation ledger |
| Incident closure quality | 100% of operational closures have protected-main or real-consumer receipt | traceability audit |
| Documentation freshness | 100% of boundary-changing PRs update linked docs/ADR/tests | documentation contract and review checklist |

## 3. Telemetry model

Correlate logs, metrics, checks, reviews, and artifacts by:

- repository full name and PR number;
- source head SHA and live base SHA;
- workflow repository/SHA, run ID, and run attempt;
- trigger and event delivery identity;
- evidence class and gate name;
- provider and failure class, never secret value; and
- writer lease and expected-head outcome.

Recommended metrics include queue age, queued/running/terminal counts, dispatch-to-start latency, duration, retry class/count, provider exhaustion, stale-evidence rejection, expected-head abort, redaction setup failure, artifact expiry, ruleset drift, and protected-main acceptance age.

Raw evidence may contain business PII. Access and retention are purpose-bound; metrics use identifiers/hashes and classifications rather than raw content where possible.

## 4. Queue and capacity management

- Use concurrency keys scoped to repository, PR, and event class so unrelated work can proceed.
- Cancellation may supersede stale current-head work only when cancellation still produces unambiguous evidence; otherwise preserve the run and bound queue growth elsewhere.
- Long-running model reviews enter a deferred set after one state read. The maintainer selects another safe lane rather than polling.
- Dispatch budgets prevent storms but must not permanently starve older eligible PRs; age and fairness are observable.
- GitHub-wide runner saturation triggers local verification, docs, RCA, or other disjoint work and an operator alert when age crosses the objective.

## 5. Provider and platform outages

| Failure | Immediate action | Continued work | Recovery evidence |
|---|---|---|---|
| GitHub API/Actions outage | Preserve non-passing state; stop writes whose live preconditions cannot be checked | local deterministic tests/docs; read-only analysis from already fetched exact source | fresh API state and exact-head rerun |
| Runner queue saturation | Avoid duplicate dispatch; inspect queue age and org capacity | other branches/repos/local proof | queued run starts and completes on intended head |
| Model provider outage/rate limit | Classify and defer or use reviewed fallback | deterministic gates and other queue items | valid current-head model result with provider identity |
| OIDC/App exchange failure | Fail privileged operation closed | read-only/local work | successful scoped exchange and intended operation |
| Package/DNS failure | Retry only if classified transient within budget | cached/disjoint work | integrity-verified install and original test |
| Eligible reviewer unavailable | Preserve governance wait | all other code/docs/operations/product lanes | counted independent current-head approval |

## 6. Deployment and rollback

Central workflow changes deploy when merged to the protected default branch and then affect required/thin consumers according to GitHub source semantics. Rollout therefore uses:

1. exact-head PR gates;
2. protected merge without bypass;
3. central protected-main run;
4. one low-risk real consumer and negative control;
5. wider fleet observation; and
6. incident closure only after receipts are recorded.

Rollback reverts to a reviewed known-good protected commit or disables only the affected optional route. It must not restore a known trust-boundary vulnerability, remove unrelated gates, change credential identity, or erase evidence. Emergency rollback is followed by a normal reviewed reconciliation PR and consumer proof.

## 7. Operator experience

Each terminal failure should state the first failing boundary, evidence identity, classification, what was preserved, the smallest operator action, and the exact rerun/acceptance path. It should not emit a URL without diagnosis, claim success for a skip, or hide ordinary failure context under over-broad redaction.

Routine scheduled runs suppress status-only narration. Notifications are reserved for a required external permission/governance action with no autonomous alternative, an irreconcilable decision, a substantive protected merge/release, or a safety boundary.

## 8. Current operability gaps

- No single persisted cross-repository continuation ledger implements the conceptual `automation_run` model.
- Proposed SLI rollups are not all emitted as metrics.
- Total sandbox output and service-file quotas remain separate work from redaction.
- Legacy inherited deploy-secret usage needs an explicit-secret migration.
- Real-consumer acceptance receipts are distributed across runs and PRs rather than a single index.

These gaps remain open in [TRACEABILITY.md](TRACEABILITY.md); they are not hidden by the target SLOs.
