# fast-mlsirm hourly review-repair caller

## Decision

ContextualWisdomLab operates one protected hourly caller for
`ContextualWisdomLab/fast-mlsirm`. The caller runs at minute 49, delegates to
the product-neutral central review-fix scheduler, inspects at most 50 open
pull requests, and dispatches at most one bounded repair per heartbeat.

The caller does not duplicate estimator, review, mutation, or merge logic.
It preserves fast-mlsirm as an independently operable psychometrics package
while centralizing privileged automation in `ContextualWisdomLab/.github`.
The reusable worker performs exact-head root-cause analysis, evaluates
remediation feasibility, and edits only when one small reversible action can
alter the diagnosed cause inside sealed writer authority.

## Root-cause analysis and remediation feasibility

The repository can contain long-running Rust, Python, GPU, recovery, and
supply-chain checks. A pending check is a merge blocker, but elapsed time is
not a source defect and must not be converted into a fabricated code change.
Likewise, an independent non-author approval is an authorization gate that
the repair worker cannot synthesize.

Each heartbeat therefore applies this bounded sequence:

1. Refetch the exact live head, protected base, reviews, checks, changed
   paths, and writer state.
2. Trace the causal chain from terminal symptom to the smallest source-owned
   defect that the worker is authorized to change.
3. Enumerate materially distinct minimal remedies.
4. Reject a remedy that lacks writer authority, crosses sealed paths, needs
   unavailable credentials or protected-setting changes, violates dependency
   order, cannot be verified, or does not alter the diagnosed cause.
5. Dispatch at most one feasible repair. Otherwise leave the tree unchanged
   so a later heartbeat can consider another eligible pull request.

Psychometric acceptance bounds, true-parameter recovery criteria, CPU/GPU
parity, skipped-test prohibitions, and Rust ownership of production arithmetic
are not loosened to make a check green. A recovery failure requires scientific
and numerical root-cause analysis rather than threshold inflation.

## Cadence and concurrency

The caller uses a single concurrency group with `cancel-in-progress: false`.
It preserves an in-flight bounded RCA rather than discarding its evidence when
the next heartbeat arrives. The reusable scheduler retains exact-head leases,
one-dispatch scope, and post-edit revalidation.

The caller sets a **two-hour same-head retry floor** because central OpenCode,
NVIDIA NIM, Rust/GPU validation, and hosted security checks can legitimately
approach two hours. A new hourly scan may select another eligible pull request,
but the same unchanged head is not assigned a duplicate writer.

GitHub scheduled workflows execute from the default branch and can be delayed
under shared-runner load. The cron is therefore a heartbeat, not a real-time
service-level promise. Exact-head state controls mutation and integration.

## Credential and model boundary

The caller has only `contents: read`. It maps only the established
`PR_REVIEW_MERGE_TOKEN` and `OPENCODE_APPROVE_TOKEN` scheduler credentials and
never uses `secrets: inherit`.

Model execution remains in the central worker. The model credential is the
GitHub Secret `NVIDIA_NIM_API_KEY`; the caller does not receive or forward it.
`COPILOT_GITHUB_TOKEN` is prohibited. Existing independent review-agent keys,
identities, and model-pool contracts remain unchanged.

## Security, privacy, and modularity

The caller adds no fast-mlsirm runtime dependency, database object, network
endpoint, tenant authority, or product credential. It cannot mask or rewrite
operational PII, modify protected settings, approve, merge, release, or change
reviewer identities. Queued, pending, absent, failed, cancelled,
skipped-required, neutral-required, stale-head, or synthetic-merge evidence is
never treated as success.

fast-mlsirm remains usable on its own and as a Rust/Python psychometrics module
in naruon, contextual-orchestrator, TEPP, or other CWL services. Ecosystem reuse
cannot weaken local validation, exact-head evidence, Rust arithmetic ownership,
independent approval, or security gates.

## Verification and rollback

Repository contracts require the exact cron, repository target, protected base,
one-dispatch budget, two-hour retry floor, non-cancelling single-flight policy,
read-only caller token, explicit secret mapping, and absence of both model and
Copilot credentials from the caller. The focused quality workflow tracks the
caller, this doctoring record, and its contract test on every pull request and
push that changes them.

Rollback is a reviewed source change. Do not disable exact-head binding, reduce
approval requirements, widen dispatch volume, inherit secrets, or convert
provider and runner latency into a source edit. Preserve the central RCA,
feasibility, lease, credential, and sealed-path contracts.

## APA 7th references

GitHub. (n.d.). *Control the concurrency of workflows and jobs*. Retrieved
August 14, 2026, from
https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency

GitHub. (n.d.). *Events that trigger workflows: Schedule*. Retrieved August 14,
2026, from
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule

GitHub. (n.d.). *Reuse workflows*. Retrieved August 14, 2026, from
https://docs.github.com/en/actions/how-tos/sharing-automations/reusing-workflows

NVIDIA. (n.d.). *NVIDIA NIM for large language models documentation*. Retrieved
August 14, 2026, from
https://docs.nvidia.com/nim/large-language-models/latest/

OpenCode. (n.d.). *OpenCode documentation*. Retrieved August 14, 2026, from
https://opencode.ai/docs/

Souppaya, M., Scarfone, K., & Dodson, D. (2022). *Secure software development
framework (SSDF) version 1.1: Recommendations for mitigating the risk of
software vulnerabilities* (NIST Special Publication 800-218). National
Institute of Standards and Technology. https://doi.org/10.6028/NIST.SP.800-218
