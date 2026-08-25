# Inkspan hourly review-repair caller

검토 기준일: **2026-08-25**

## Decision

ContextualWisdomLab operates one protected hourly caller for
`ContextualWisdomLab/inkspan` (deterministic Markdown/HTML authoring and
bounded document/evidence contracts). The caller runs at minute 56, delegates
to the product-neutral central review-fix scheduler, inspects at most 50 open
pull requests targeting protected `main`, and dispatches at most one bounded
repair per heartbeat.

A paying buyer of commercial-grade editor tooling would feel live Inkspan pull
requests stalling while the hourly NVIDIA NIM repair loop scanned only other
products in the organization. Live heads such as inkspan#299 (stacked-PR CI
gates), inkspan#362 (editor contrast and keyboard focus), and the
writing-diagnostics stack sit in exactly that blind spot when their checks are
green but central review evidence is missing or stale.

The caller does not implement review or mutation logic itself. Inkspan remains
standalone and embeddable; hosts consume `@contextualwisdomlab/cwl-editor`
without owning privileged automation. All mutation authority stays sealed in
`ContextualWisdomLab/.github` behind `PR_REVIEW_MERGE_TOKEN` /
`OPENCODE_APPROVE_TOKEN`.

## Root-cause analysis and remediation feasibility

The reusable worker performs exact-head root-cause analysis, tests remediation
feasibility, and edits only when one small reversible action can change the
diagnosed cause inside its sealed writer authority. It follows the shared
transitions documented in the central scheduler contract: refetch live state,
establish the causal chain, enumerate materially distinct minimal remedies,
reject infeasible ones, and dispatch at most one repair per heartbeat.

Minute 56 avoids every existing hourly heartbeat minute (2, 10, 14, 16, 21,
23, 27, 37, 43, 49, 53, 58) so runner capacity is not contested at dispatch
time.

## Consequences

- Inkspan gains parity with disksage, nonnest2, Clearfolio, afipc, and
  fast-mlsirm for bounded hourly unattended review-repair throughput.
- The two-hour same-head retry floor prevents duplicate writers while keeping
  unrelated PR lanes moving every hour.
- No COPILOT_GITHUB_TOKEN is used; existing review-agent key chains are
  untouched.
