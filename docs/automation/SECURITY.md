# Security architecture and control objectives

Status: accepted baseline
Last reviewed: 2026-08-09

## 1. Security objectives

1. Untrusted pull-request content never executes with privileged workflow authority.
2. Every privileged action is bound to a validated repository, actor, PR, exact head, live base, purpose, and expected operation.
3. Checks, statuses, model results, reviews, and merge authority cannot impersonate one another.
4. Credentials use least privilege, short lifetime, explicit purpose, and minimal distribution.
5. Evidence remains diagnostically useful without publishing credentials or unbounded attacker-controlled content.
6. Supply-chain inputs are immutable or integrity-verified and fail closed on origin, TLS, pin, signature, or schema mismatch.
7. Operational incidents close only after protected-main or real-consumer proof.
8. Business-required PII stays usable under purpose-bound access and audit controls; indiscriminate masking is not the default privacy mechanism.

## 2. Identity and authorization

- Repository rulesets and branch protection are the final policy enforcement layer.
- Formal GitHub review identities remain distinct from automated reviewer identities.
- Dispatch workers validate canonical payload fields against live GitHub state before any write or model execution.
- OIDC/App exchanges are preferred for cross-repository authority. Audience, issuer, repository, workflow source, and requested scope must be constrained.
- `GITHUB_TOKEN` permissions are read-only by default and expanded only for a bounded job.
- A writer lease authorizes mutation of one repository/ref/expected-head tuple, not general organization writes.
- Expected-head comparisons guard source, ref, comment-resolution, branch-update, and merge mutations against time-of-check/time-of-use races.

## 3. Secret contract

| Secret or authority | Allowed purpose | Prohibited use |
|---|---|---|
| `NVIDIA_NIM_API_KEY` | Actual approved model calls in OpenCode/Noema/Strix or autonomous development | Checkout, deterministic tests, source materialization, anonymous/free providers, merge authority |
| OIDC request token | Exchange for one reviewed App/provider purpose | Logging, artifact retention, general shell inheritance |
| GitHub App token | Bounded target-repository reads/writes named by the exchange policy | Unrelated repositories or jobs; human-review impersonation |
| `PR_REVIEW_MERGE_TOKEN` / compatible reviewed fallback | Existing cross-repository scheduler compatibility path | Scope expansion, self-approval, unrelated product operations |
| `github.token` | Same-repository capability under explicit job permissions | Assumed cross-repository authority |
| `COPILOT_GITHUB_TOKEN` | None in autonomous development | Any autonomous development or review execution |

Reusable workflows must declare named secrets and callers must pass only
explicitly mapped secrets matching the callee's `on.workflow_call` contract.
`secrets: inherit` is prohibited for approved central consumers. This is the
target contract, not a claim that every protected-main path already conforms.

### 3.1 Known protected-main mapping debt

The registry proves name inventory, not reusable-call mapping. Source audit at
this review found secret expressions without matching reusable
`workflow_call.secrets` declarations in these exact paths:

- `.github/workflows/pr-review-fix-scheduler.yml`;
- `.github/workflows/pr-review-merge-scheduler.yml`;
- `.github/workflows/pr-auto-rebase.yml`; and
- `.github/workflows/deploy-pages.yml`.

The deploy contract has an active narrow repair in [PR #901](https://github.com/ContextualWisdomLab/.github/pull/901).
The other three remain planned migration debt and must not be reported as
explicitly mapped until their declarations, caller inventory, negative tests,
and protected consumer receipts exist. Runtime fallback credentials remain
purpose-separated; documenting debt does not authorize inheritance.

### 3.2 Value-free workflow secret registry

This registry is value-free and covers the exact union of literal
`secrets.NAME` and `secrets['NAME']` references in tracked `*.yml` and
`*.yaml` workflows at the reviewed revision. “Optional” means the feature
fails closed or uses a separately documented narrower authority; it never
permits synthetic success. Every new workflow secret updates this table in the
same change.

| Secret name | Consumer and minimum scope | Requirement and owner | Rotation or revocation |
|---|---|---|---|
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare DNS/Pages account identifier | Required for the named Cloudflare operation; infrastructure owner | Update on account migration; remove from callers when retired. |
| `CLOUDFLARE_API_TOKEN` | Token limited to managed Cloudflare zones/projects | Required for apply/deploy; infrastructure owner | Revoke on exposure/role change; replace and dry-run before apply. |
| `GCP_SA_KEY` | Vertex provider service-account JSON | Optional provider path; security/model owner; long-lived migration risk | Revoke immediately on exposure and migrate toward workload identity/OIDC. |
| `NOEMA_GITHUB_APP_PRIVATE_KEY` | Noema App-token minting for the target repository | Optional when an approved narrower route exists; review-platform owner | Rotate App key, revoke affected installations, then run a non-destructive review probe. |
| `NOEMA_LLM_API_KEY` | Noema model endpoint only | Optional model path; review-platform owner | Rotate at provider and verify one bounded model call; no broader fallback on auth error. |
| `NOEMA_REVIEW_TOKEN` | Noema review-publication compatibility path | Optional App/OIDC fallback; review-platform owner | Revoke on exposure/eligibility change and audit review objects since exposure. |
| `NVIDIA_NIM_API_KEY` | Approved NVIDIA NIM model-call steps | Optional provider path; model-platform owner | Rotate at NVIDIA; never reuse for checkout, tests, or mutation. |
| `OPENAI_API_KEY` | Approved OpenAI-compatible model-call steps | Optional provider path; model-platform owner | Rotate at provider and verify only the provider-scoped step. |
| `OPENCODE_APPROVE_TOKEN` | Review publication and reviewed scheduler compatibility mutation | Optional App/merge-token fallback; automation owner | Revoke on exposure/scope change; audit reviews/writes and replace narrowly. |
| `OPENCODE_ZEN_API_KEY` | OpenCode Zen model-call step | Optional provider path; model-platform owner | Rotate at provider and verify one bounded model call. |
| `OPENROUTER_API_KEY` | OpenRouter model-call step | Optional provider path; model-platform owner | Rotate at provider and verify one bounded model call. |
| `PR_REVIEW_MERGE_TOKEN` | Named cross-repository scheduler/router/autofix operations | Required only where narrower App authority is unavailable; automation owner | Revoke on exposure/scope change, audit affected targets, and replace narrowly. |
| `SBOM_INVENTORY_TOKEN` | Organization repository read for SBOM aggregation | Optional App-token fallback; supply-chain owner | Revoke on exposure and prove read-only inventory scope before resuming. |
| `STRIX_GITHUB_MODELS_TOKEN` | GitHub Models call for Strix/OpenCode evidence | Optional provider token; security/model owner | Revoke on exposure; use only an independently configured provider fallback within budget. |
| `STRIX_OPENAI_API_KEY` | Strix-specific OpenAI provider call | Optional provider token; security owner | Rotate at provider and verify the Strix model boundary. |
| `VERTEX_LOCATION` | Vertex region identifier currently stored through secret context | Optional configuration; model-platform owner; migrate to non-secret configuration | Update on region/policy change; removal does not require credential rotation. |

Each registry entry defines consumer, minimum scope, required/optional behavior,
owner, and rotation or revocation. Configuration identifiers migrate to
`vars` or another reviewed configuration store when secrecy is unnecessary.

## 4. Pull-request and workflow trust

Metadata-only `pull_request_target` entrypoints may create stable required contexts but must not execute PR-controlled code, use PR-controlled workflow files, or expose secrets. Privileged review/fix work runs from protected default-branch workflow source through a validated default-branch dispatch. PR source is either inert input or runs in a low-privilege, credential-isolated sandbox.

Workflow source identity is captured separately from target source identity. Mutable branch references are insufficient for release or cross-repository trust where an immutable SHA is practical.

## 5. Evidence confidentiality and integrity

All CI-facing publication paths—stdout, stderr, timeouts, exceptions, service logs, command metadata, comments, summaries, artifacts, and structured result markers—share a credential redaction boundary. Redaction occurs before tail selection, truncation, or JSON publication so a secret outside the final tail cannot influence unsafe selection and a secret cannot be split across fields.

The redactor protects credentials, not all sensitive business meaning. PII controls are:

- limit collection to evidence necessary for the review or incident purpose;
- restrict repository, workflow, artifact, and log access;
- use short retention and deletion for raw evidence;
- store bounded hashes/classifications/receipts where raw content is unnecessary;
- audit access and disclosure to named operator roles; and
- keep model-provider routing consistent with repository data classification and consent.

This preserves legitimate investigation and review while avoiding a blanket masking policy that would make enterprise workflows unusable.

## 6. Supply-chain controls

- Pin third-party actions and downloaded tool releases to immutable revisions or verified digests.
- Verify archive origin, redirect policy, expected member set, checksum/signature, and executable boundary before use.
- Keep source materialization separate from privileged publication and signing.
- Treat artifacts from other runs as untrusted until run, attempt, name, digest, source, and schema identity are verified.
- Generate SBOM/provenance/attestation evidence without claiming a SLSA level that has not been independently demonstrated.
- Maintain hash-locked Python requirements and equivalent ecosystem locks.
- Reject GPL/AGPL or otherwise disallowed dependencies under organization license policy.

## 7. Model and prompt security

PR content, comments, source, documentation, test output, and tool output are untrusted instructions. Model runners must separate system policy from repository data, constrain tool and network access, validate structured output, bind findings to exact source receipts, and prevent tool-call markup or model prose from becoming executable commands. A model verdict cannot authorize a human-only action.

Anonymous or free models receive no unrelated credential. Private or classified repositories require explicit trusted-base policy before external model processing. Provider failure or malformed output fails the affected gate closed.

## 8. Egress and runtime isolation

Runners use hardened, ephemeral environments where practical. Egress is restricted or audited by job purpose. Coverage and proof commands execute with scrubbed environments, bounded time, controlled network posture, isolated temporary copies, and no persisted checkout credential. A child process cannot alter the original workspace through the sandbox copy contract.

Resource controls and credential redaction are independent. A correct redactor does not bound child memory, total stdout capture, or service-log file growth; those require explicit quotas and tests.

## 9. Control-framework alignment

Official version decisions and primary references are maintained in [`../doctoring/automation-control-plane-standards.md`](../doctoring/automation-control-plane-standards.md). This architecture can contribute bounded engineering evidence toward:

- final NIST SSDF 1.1 practices for protected development environments, provenance, verification, and vulnerability response, while SSDF 1.2 remains informative as an initial public draft;
- NIST SP 800-204D software-supply-chain controls in CI/CD;
- final NIST SP 800-92 log lifecycle and incident-use guidance, with SP 800-92 Rev. 1 treated as an informative initial public draft;
- ISO/IEC 27001:2022 risk-based management-system concerns and ISO/IEC 27002:2022 access, logging, monitoring, supplier, and incident-control guidance;
- ISO/IEC 42001:2023 governance of AI-assisted review and human accountability;
- the AICPA 2017 Trust Services Criteria with revised points of focus (2022) for security, availability, processing integrity, confidentiality, and privacy evidence; and
- conditional Korean Cloud Security Assurance Program (CSAP) readiness questions for an actual in-scope cloud service and public-sector use.

These mappings are not certification or attestation claims. ISO/IEC 27002 is guidance and is not itself certifiable; SOC 2 requires a scoped service description and an independent attestation engagement; Korean CSAP requires assessment of the actual cloud service under the applicable current program and legal criteria. No ISO certificate, SOC 2 report, CSAP tier/eligibility, SLSA level, or regulatory compliance follows from repository source or tests alone. Any such claim requires defined scope, control ownership, operating evidence over the required period, authorized independent assessment, and remediation of gaps in [TRACEABILITY.md](TRACEABILITY.md).

## 10. Security change gate

Any change to events, permissions, secrets, dispatch schema, source materialization, sandbox output, model routing, review authority, merge logic, artifact provenance, or egress requires threat-model review, negative tests, rollback, exact-head security checks, independent approval, and protected-main acceptance.
