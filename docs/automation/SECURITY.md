# Security contract: CWL automation control plane

Status: normative security policy; implementation evidence is linked from
[TRACEABILITY.md](TRACEABILITY.md).

## Security objectives

1. A PR-controlled value cannot select privileged workflow code, widen a job's
   permissions, expose a credential, or authorize a mutation.
2. Every check, review, branch update, merge, release, and incident-closure
   claim is bound to its real producer, target repository, and exact revision.
3. A single compromised provider, runner, model response, or leaf repository
   cannot silently obtain fleet-wide write authority.
4. Failures preserve useful diagnostics without publishing authentication
   material or credential-shaped command output.
5. Supply-chain artifacts and dependencies remain attributable, reproducible,
   and reviewable.

## Non-negotiable invariants

- PR text, issue text, review comments, workflow inputs, model output, archives,
  patches, and target source are untrusted data.
- A `pull_request_target` bootstrap may inspect metadata but must not execute
  PR-controlled code while holding a secret or write permission.
- Privileged workflow code comes from a protected default branch. Repository,
  ref, SHA, PR number, source head, base branch, and current live-base identity
  are revalidated after every trust-boundary crossing.
- A textual verdict is never merge authority, release authority, deployment
  authority, or ruleset approval. The corresponding eligible GitHub object and
  all independent gates must exist.
- The branch writer lease is exclusive for `(repository, branch)`. The fleet
  auditor is read-only and cannot borrow a writer credential.
- Identity, integrity, authorization, TLS, checksum, signature, and ref
  failures fail closed. Retrying them without a material state change is
  prohibited.

## Identity and authorization

| Actor | Minimum authority | Explicitly excluded |
|---|---|---|
| Required-workflow bootstrap | PR metadata and check publication | PR source execution, branch write, merge |
| Strix | exact-head evidence publication | formal approval, merge, release |
| OpenCode and Noema adapters | bounded review publication under named identity | unilateral counted approval or merge |
| Merge scheduler | dispatch plus guarded branch/merge action for one target | release or deployment |
| Autofix worker | guarded same-repository PR-branch write | protected-base write, cross-repository branch mutation |
| Fleet auditor | organization/repository policy read | dispatch, review, source write, merge |
| Release/deploy workflow | environment-scoped release or deployment | retroactive review evidence |

Repository selection and requested action are authorization inputs, not merely
strings. Allow-list membership, installation scope, actor association, event
origin, and live repository state are checked before a privileged dispatch.
Self-authored, bot-authored, dismissed, stale, or otherwise ineligible reviews
do not satisfy an independent-approval rule.

## Permission and secret contract

- Workflows default to `contents: read`; each job declares only the permissions
  required for its API calls.
- `id-token: write` is scoped to the job that exchanges OIDC identity. GitHub
  App installation tokens are short lived and target-repository scoped.
- Long-lived compatibility credentials are separated by purpose. In
  particular, review publication, branch mutation, merge, release, and deploy
  credentials are not interchangeable.
- `NVIDIA_NIM_API_KEY` is materialized only for an actual model request after
  deterministic eligibility and identity gates pass.
- `COPILOT_GITHUB_TOKEN` is not an accepted development-agent credential.
- Reusable workflows declare named secret inputs. Blanket `secrets: inherit`
  is a documented migration risk, including the current caller guidance for
  `.github/workflows/deploy-pages.yml`.
- Secrets are never passed through PR-authored command lines, persisted in
  artifacts, included in model prompts, or echoed for debugging.

Credential rotation invalidates the affected installation/session, updates the
smallest secret scope, and exercises a non-destructive authenticated probe
before source mutation resumes. A failed probe does not trigger broader-token
fallback automatically.

## Secret and sensitive-configuration registry

This table is value-free. It covers the complete union of `secrets.*` names in
tracked workflows at the audited revision. “Optional” means the named feature
degrades or uses its documented narrower alternative; it does not permit a
synthetic success.

| Name | Consumer and minimum scope | Requirement and owner | Rotation or revocation |
|---|---|---|---|
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare DNS/Pages account identifier | required for Cloudflare action; infrastructure owner | update on account migration; remove from runners/callers when retired |
| `CLOUDFLARE_API_TOKEN` | Cloudflare DNS/Pages token limited to managed zones/projects | required for apply/deploy; infrastructure owner | revoke on exposure/role change; replace and dry-run before apply |
| `GCP_SA_KEY` | Vertex provider service-account JSON | optional provider path; security/model owner; long-lived migration risk | revoke key immediately on exposure and prefer workload identity/OIDC |
| `NOEMA_GITHUB_APP_PRIVATE_KEY` | Noema App token minting for target repository | optional when approved OIDC/PAT path exists; review-platform owner | rotate App key, revoke installations, verify one non-destructive review probe |
| `NOEMA_LLM_API_KEY` | Noema model endpoint only | optional model path; review-platform owner | rotate at provider and verify bounded model call; no broader fallback on auth error |
| `NOEMA_REVIEW_TOKEN` | Noema review publication compatibility token | optional App/OIDC fallback; review-platform owner | revoke on exposure or eligibility change; audit review objects since exposure |
| `NVIDIA_NIM_API_KEY` | OpenCode/Noema/Strix NVIDIA NIM model-call steps | optional provider path; model-platform owner | rotate at NVIDIA; never accept legacy `NVIDIA_API_KEY` as a workflow secret fallback |
| `OPENAI_API_KEY` | OpenCode/Noema/Strix OpenAI-compatible model calls | optional provider path; model-platform owner | rotate at provider; test only provider-scoped step and inspect egress logs |
| `OPENCODE_APPROVE_TOKEN` | review publication and scheduler compatibility mutation | optional App/merge-token fallback; automation owner | revoke on exposure/scope change; audit reviews/writes and prefer scoped App/token |
| `OPENCODE_ZEN_API_KEY` | OpenCode Zen model-call step | optional provider path; model-platform owner | rotate at provider and verify bounded model call |
| `OPENROUTER_API_KEY` | OpenRouter model-call step | optional provider path; model-platform owner | rotate at provider and verify bounded model call |
| `PR_REVIEW_MERGE_TOKEN` | cross-repository scheduler/router/autofix/SBOM read-write actions | required only for uncovered cross-repository operations; automation owner | revoke on exposure or repository-scope change; audit every affected target and replace narrowly |
| `SBOM_INVENTORY_TOKEN` | organization repository read for SBOM aggregation | optional App-token fallback; supply-chain owner | revoke on exposure; verify read-only inventory scope before resuming |
| `STRIX_GITHUB_MODELS_TOKEN` | GitHub Models call for Strix/OpenCode evidence | optional provider token; security/model owner | revoke on exposure; fall back only to an independently configured provider within budget |
| `STRIX_OPENAI_API_KEY` | Strix-specific OpenAI provider call | optional provider token; security owner | rotate at provider and verify Strix model boundary |
| `VERTEX_LOCATION` | Vertex region value stored through the secret context, not authentication material | optional configuration; model-platform owner; migrate to a non-secret variable | update on region/policy change; removal does not require credential rotation |

Every new `secrets.*` name updates this registry in the same change. Each entry
must identify consumer, minimum scope, required/optional behavior, owner, and
rotation/revocation. Configuration identifiers should migrate to `vars` or an
approved configuration store when secrecy is unnecessary.

## Execution and egress controls

`scripts/ci/sandboxed_verify.py` and `scripts/ci/sandboxed_web_e2e.py` start
with a credential-scrubbed environment. Network access and each environment
variable are explicit exceptions supported by an evidence note. Scratch
worktrees and service processes are bounded to the runner lifecycle.

External providers receive only the minimum source/evidence slice required for
the requested review. Provider output is untrusted and is parsed with size,
schema, timeout, and authority limits. Provider failure never yields synthetic
approval and does not relax deterministic gates.

## Logging, privacy, and retention

Structured records retain repository, PR, workflow/run/job identity, source
head, live base, evidence class, producer, conclusion, attempt, and bounded
failure detail. Before output reaches logs, summaries, comments, or artifacts,
credential-shaped values in stdout, stderr, service output, and timeout tails
are transformed by the publication boundary.

The stronger subprocess-log redaction implementation is pending in
`ContextualWisdomLab/.github#842`; it is not represented as protected-main
behavior. Until it lands and passes consumer acceptance, operators must treat
raw command output as sensitive and restrict audience and retention.

PII is controlled through purpose limitation, least-privilege audience,
minimized collection, bounded retention, encrypted transport/storage, and
auditable access. Indiscriminate masking is not required when it would destroy
necessary review or incident context. Authentication material is always
secret, regardless of whether it is personal data.

## Supply-chain controls

- Workflow actions are pinned according to repository policy and privileged
  definitions are sourced from protected refs.
- Python bootstrap dependencies use hash-locked requirements and trusted
  materialization paths. Integrity failures are permanent failures.
- CodeQL, secret scanning, OSV/dependency scanning, Scorecard, SBOM generation,
  and scheduled security workflows remain separate evidence producers; none is
  inferred from another producer's success.
- A skipped or neutral job is not authoritative Strix scan evidence. The
  current fail-closed terminal-gate gap is tracked in
  `ContextualWisdomLab/.github#891` and remains an operational risk until
  protected-main consumer acceptance.
- Generated SBOM/provenance evidence identifies the source revision and build
  invocation. Missing or predecessor-revision artifacts are non-passing when
  required.
- A central change is staged through its own exact-head checks and a real
  protected-main consumer before fleet-wide operational closure.

## Vulnerability and exception handling

Confirmed secret exposure, unauthorized write, evidence forgery, protected-ref
movement, or cross-repository authority escape is a security incident. Follow
[INCIDENT_RUNBOOK.md](INCIDENT_RUNBOOK.md), preserve audit evidence, rotate only
affected credentials, and reopen every dependent acceptance claim.

A temporary policy exception names the owner, exact repository/ref, rationale,
expiry, compensating control, detection signal, and rollback. It cannot waive
exact-head binding, protected workflow provenance, legitimate reviewer
eligibility, or final head-match protection.

## Verification

Security changes require realistic negative tests for malformed identity,
stale heads, unauthorized actors, missing/over-broad credentials, malicious
output, timeout tails, replay, concurrency, and cross-repository scope. The
exact test strategy and protected-main evidence requirements are defined in
[TEST_STRATEGY.md](TEST_STRATEGY.md).
