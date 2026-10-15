# pg-erd-cloud central quality workflow — candidate

## Owner requirement

The October 8, 2026 instruction requires central ContextualWisdomLab/.github
ownership, self-hosted execution with no GitHub-hosted fallback, and genuine
Noema/OpenCode exact-head review and independent bot approval. Model selection
is `auto`. This change owns only the missing product validation reusable workflow;
it does not duplicate the all-workflow routing candidate in #2565, the review
reliability lane in #2574, or their secrets and publication handlers.

## Implementation

`.github/workflows/pg-erd-cloud-quality.yml` has fixed backend and frontend jobs.
It declares only `workflow_call`, no caller-provided executable strings, no
inherited secrets, and `contents: read`. Both jobs target `CWL CI isolated` and
`[self-hosted, linux, x64, cwlab-ci-isolated]`. The first inline step rejects
foreign repositories, forks, pull_request_target, unsupported events and
non-main push/dispatch before any action or checkout. Same-repository PRs remain
admitted, including stacked PRs. Actions use immutable SHA pins; checkout selects
the caller head and disables persisted credentials.

Backend keeps Python 3.10, both product hash locks, automation contracts, mypy
and pytest. A unique RUNNER_TEMP directory holds its venv, is cleaned on EXIT,
and avoids installing candidate dependencies into shared runner Python. Frontend
keeps Node 26, npm ci including dev dependencies, typecheck, tests, production
build, and explicit NODE_ENV test/production. All phases remain failure-gating.

Keep concurrency in the caller only. The eventual thin caller has:

- name `ci`;
- push on main and same-repository PR triggers;
- contents read;
- `ci-${{ github.repository }}-${{ github.event.pull_request.number || github.run_id }}`
  concurrency with PR-only cancellation;
- one reusable job calling
  `ContextualWisdomLab/.github/.github/workflows/pg-erd-cloud-quality.yml@`
  followed by a real reviewed/published 40-character central commit SHA;
- no `secrets: inherit` and no arbitrary inputs.

Do not activate a mutable branch caller or invent its not-yet-published SHA.
Reusable invocation can change displayed required check names. Reconcile those
through the protection owner without removing checks merely to unblock merge.

## Executed acceptance

Tests first failed for the missing workflow. The next test failed because the
initial port installed Python dependencies globally. Job-private venv repair
followed. Final local focused result: 24/24 new contracts plus 72/72 existing
queue contracts, 96 passed. Actual admission shell was executed for 18 accepted
and rejected tuples. The actual backend shell was exercised with synthetic tool
executables for success, mypy failure and pytest failure: exit propagation,
owned temporary cleanup and unrelated-directory preservation passed. This is
shell/contract execution, not backend dependency installation or runner evidence.

Actionlint passed with the exact custom-label vocabulary supplied by #2565's
`.github/actionlint.yaml` in a separate scratch config; that PR-owned file was
not duplicated or edited. Default actionlint without custom-label config failed
on the isolation label, and that failure must not be hidden as schema success.

## Fresh capacity observation — October 8, 2026

Group 13, `CWL CI isolated`, contains three runners: orgmetra-ci-01,
keyverse-ci-01 and calendarweave-ci-01, all offline at the observed GET. Its five
selected repositories are .github, CalendarWeave, fast-mlsirm, keyverse and
Orgmetra. pg-erd-cloud is not selected. Other online runners do not establish
this group's capacity and must not be relabeled or silently borrowed.

The existing operator lane is ContextualWisdomLab/linux-cluster-ops#326. Its
isolation, custodian acceptance, runner registration, tool availability and
cleanup canary remain required. This source change neither provisions a runner
nor modifies ACLs. No remote job execution, model-backed approval, merge or
hosted-only retirement is established by these local tests.

## Review/gateway boundary

Protected central workflows currently route Noema/OpenCode through the vendored
contextual-orchestrator sidecar and `orchestrator/free`. The sidecar explicitly
rejects auto in its current admission. Workflow model-string substitution alone
is therefore incorrect. External LiteLLM routing needs a separately reviewed
configuration/provider contract, least-privilege key, budget and private-target
ZDR protection while preserving the existing independent bot publisher and
exact-head verdict checks. The LiteLLM UI requested login; the secure credential
save was declined, so no key was issued or read and no inference claim is made.

The implementing account must not self-approve. Only a real passing independent
model verdict plus current-head publication authority permits formal approval.

## Primary technical reference

GitHub Docs, *Reuse workflows* and *Using self-hosted runners in a workflow*.
Check the live documentation before activation. Group restriction and label
matching are routing/access constraints, not proof of isolation. Local proposed
configuration, central publication, consumer adoption, actual runner execution,
review approval and ordinary protected merge are distinct acceptance states.
