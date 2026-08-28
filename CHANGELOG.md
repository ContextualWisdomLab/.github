# Changelog

All notable changes to the organization automation repository are documented in
this file. The format follows Keep a Changelog, and versioned releases follow
Semantic Versioning where the repository publishes a release.

## [Unreleased]
- Add a bounded hourly LineageWeave stacked-PR review-repair caller while
  preserving the existing review-agent, model-routing, and protected-merge
  boundaries. Product-gap development remains a separately gated coordinator
  capability and is not claimed by this caller. The shared repair scheduler
  now treats an explicit `*` base scope as all branch bases so stacked pull
  requests are inspected instead of silently filtered out.
- Ensure the central Security Scan and SAST Semgrep pull-request workflows
  trigger for stacked PRs targeting feature branches, preserving the same
  diff-scoped dependency and repository-wide filesystem security coverage.
- Harden the contextual-orchestrator Strix sidecar by rejecting line-breaking
  bearer tokens and masking the token before clone, install, launch, or health
  diagnostics can emit it. The raw bearer no longer enters `GITHUB_ENV` (where
  a later step header could render it before masking); only a mode-0600 token
  file path crosses steps, and each model consumer validates and masks the file
  inside its own step. The bounded required-workflow smoke now parses every
  governed shell input independently, including the sidecar and token loader.
  Strix also qualifies only the loopback child model as
  `openai/orchestrator/free`, which satisfies LiteLLM's explicit-provider
  contract while preserving `orchestrator/free` at the gateway boundary; a
  missing, empty, or non-pinned contextual-orchestrator API base fails closed.
- Restore OpenCode coverage honesty and mermaid surfaces stacked on main after #1360 squash `17052a7c`: `publish_fallback_diff_review` posts a COMMENT product-file review then `request_changes_for_coverage_evidence_failure` sets the status comment to `COVERAGE_BLOCKED` so a coverage miss never looks finished as `Gate result: COMMENT`; mermaid labels crates/packages instead of generic `Changed file (N files)` and does not invent class edges; findings say `Review process` instead of `.github/workflows/opencode-review.yml:1` unless that file is in the diff. Does not change `noema-review.yml` (PM owns `feat/noema-orchestrator-free-zdr`) and is not NIM-2h or GitHub Models.
- Required OpenCode dispatch and Strix now use the vendored
  `contextual-orchestrator/orchestrator/free` gateway for model execution and
  failed-check diagnosis. The generated OpenCode config contains only the
  gateway provider, Strix rejects non-gateway model overrides and external
  fallbacks, and private-target visibility enables the sidecar's attested ZDR
  requirement. The sidecar installs its vendored dependencies with the
  hash-pinned lock, and gateway provider exhaustion remains fail-closed.
- Required Noema review now routes through the same vendored
  `contextual-orchestrator` sidecar as the autofix writer: `noema-review.yml`
  provisions the gateway with the five provider secrets, points the LLM step
  at the loopback `orchestrator/free` pool (ZDR-first auto-discovery), and
  deletes the public-repo NVIDIA NIM hardcode. `call_llm` keeps SSRF closed
  for arbitrary private and `localhost` targets and allows only the
  orchestrator sidecar loopback (`127.0.0.1` / `::1`) only when it matches the
  exact configured sidecar base URL. Reviewer identity
  is unchanged (`NOEMA_REVIEW_TOKEN` / GitHub App / OIDC; never
  `github.token`). The hourly-review-repair roster is untouched.
- Central review now routes through the vendored `contextual-orchestrator`
  gateway sidecar: the write-capable PR autofix and the shared `opencode.jsonc`
  default use the fail-closed zero-cost pool `orchestrator/free`, with
  ZDR-compliant (zero-data-retention) routes prioritized inside it. The five
  provider secrets (`BYTEZ_API_KEY`, `NVIDIA_NIM_API_KEY`,
  `NVIDIA_NIM_API_KEY_SUB`, `OPENROUTER_API_KEY`, `OPENAI_API_KEY`) are
  registered into the gateway's process-local KV as bootstrap transport, model
  selection is delegated to the orchestrator's auto model discovery, and the
  previous direct NVIDIA NIM pin is gone from the autofix writer. Adds
  `scripts/ci/zdr_policy.py`,
  `scripts/ci/contextual_orchestrator_review_policy.py`,
  `scripts/ci/contextual_orchestrator_review_launcher.py`, and
  `scripts/ci/contextual_orchestrator_review_sidecar.sh` with contract-test and
  ZDR/audit evidence (`docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md`,
  `docs/doctoring/contextual-orchestrator-vendored-sidecar.md`). Mutation
  authority is unchanged: app-token-only, never `github.token`.
- Dependency updates now keep coverage evidence when the lock file passes
  validation. If validation reports a problem, refresh the lock file and run
  the review again before merging.
- Route Strix cross-provider fallbacks to explicit direct-OpenAI models
  (`openai-direct/...`) through the OpenAI inference endpoint instead of
  inheriting a provider-specific primary base: the workflow now provisions
  `STRIX_OPENAI_FALLBACK_API_BASE_FILE` (`https://api.openai.com/v1`), while
  standalone caller-supplied `LLM_API_BASE_FILE` values remain honored for
  OpenAI-compatible endpoints. Known GitHub Models, NVIDIA NIM, and OpenRouter
  bases are never inherited, and LiteLLM uses native OpenAI defaults only when
  no base is supplied. A non-https override fails configuration. This removes the NVIDIA-NIM-edge
  `404 page not found` that made the contracted final fallback unreachable
  after NIM exhaustion.
- Align stale `gpt-5.6-luna` test expectations with the valid `gpt-5.4`
  contract left behind by the earlier model rename.
- Honor each trusted base project's exact, integrity-bearing pnpm
  `packageManager` specification in OpenCode coverage images through the pinned
  Node distribution's Corepack runtime, instead of admitting the specification
  during materialization and then rejecting every version except pnpm 11.5.3;
  route generic coverage and docstring package scripts through the same
  Corepack boundary instead of invoking a removed bare `pnpm` binary.
- Review scans now run in a controlled order so each pull request receives a
  complete result instead of a rate-limit interruption. Open the pull request
  after the active scan finishes to review the latest result.
- Closed pull-request cleanup now preserves the review record and reports any
  authorization or malformed-data issue for follow-up. Reopen the pull request
  or update its credentials when the cleanup message asks you to act.
- Keep `--trust-lockfile` only for pnpm 11.3 and newer
  (`trustLockfile` landed in pnpm 11.3). pnpm 9, 10, and 11.0–11.2 reject
  that flag and previously failed LineageWeave JavaScript coverage before
  tests could run. Jest test scripts still receive `--coverage` because Jest
  documents a native coverage flag.
- Run declared JavaScript test scripts without synthesizing `--coverage` when
  the package does not declare a compatible coverage command, but keep the
  coverage result failed until the repository adds a lock-pinned provider and
  owned coverage command. A generic `c8`, `nyc`, or Istanbul dependency no
  longer makes an unrelated test runner receive an unsupported flag.
- Fix OpenCode coverage evidence for exact-base, organization-owned Python VCS
  dependencies without weakening registry hashes or the networkless PR sandbox,
  reject namespace, ambiguous, linked, native-extension, and installed-metadata
  layouts, and make exact roots readable by the unprivileged coverage user.

### Added

- Refresh the live product and technical gap baseline against the current
  open-PR queue after ContextualWisdomLab/.github#1252 merged, with SHA-bound
  snapshot rows, a same-session open/close delta, ADR Figma File ID N/A, and
  APA 7th doctoring. The inventory is not merge authorization.

- Classify Strix `ModelBehaviorError` and provider exhaustion as typed
  `STRIX_PROVIDER_UNAVAILABLE` evidence while preserving a nonzero required
  check. Incomplete scans and reported vulnerabilities both fail closed.

- Added an hourly organization commercial-readiness coordinator that discovers writable repositories, honors enabled dedicated writer leases and fully paginated live writer runs, refetches exact repository/workflow/run/PR state before dispatch, rotates bounded review-repair and opt-in NVIDIA OpenCode product-development targets, fails nonzero on fleet-wide inspection or dispatch outages, retains three-day JSON receipts, and keeps the existing 15-minute merge scheduler authoritative.
- Added a dedicated Quarantine Sandbox Runtime hourly caller at minute 14 that targets protected `develop`, dispatches at most one exact-head repair, applies a two-hour same-head retry floor, preserves non-cancelling single-flight execution, and maps only the established scheduler credentials with job-scoped OIDC.
- Added a dedicated OriginWeave hourly caller that invokes the product-neutral central scheduler with the exact repository, protected `main` branch, one-dispatch budget, two-hour same-head retry floor, non-cancelling single-flight heartbeat, job-scoped OIDC, and only the established scheduler credentials.
- Added a trusted pull-request comment router for `@cwl-noema-review` and review-only `@opencode-agent` dispatches, with an organization sweep, exact-head receipts, repository allowlisting, fixed runners, immutable checkout pins, and a permanent 100% statement/branch/docstring quality gate.
- Added an organization-owned reusable exact-artifact SBOM attestation boundary that validates inert six-file wheel/sdist evidence, binds CycloneDX 1.7 predicates to exact SHA-256 subjects, signs through least-privilege GitHub artifact attestations, and exports online and offline verification bundles.
- Added exact-base `uv.lock` materialization that reconstructs standalone nested projects with a checksum-pinned official `uv` exporter, isolated frozen/offline execution, strict exact-pin and SHA-256 output validation, and complete Python 3.10/3.14 quality evidence.
- Added a permanent exact-head contract workflow for the hourly review-repair scheduler, immutable reusable-workflow source, NVIDIA NIM model boundary, credential isolation, and fail-closed unattended-agent permissions.
- Added a dedicated Clearfolio hourly caller that invokes the product-neutral central scheduler with the exact repository, protected base branch, one-dispatch budget, one-hour retry floor, single-flight concurrency, and only the established scheduler credentials.
- Added a dedicated DiskSage hourly caller that invokes the same product-neutral RCA and remediation-feasibility scheduler with an exact repository target, one-dispatch budget, two-hour same-head retry floor, non-cancelling single-flight heartbeat, and explicit established scheduler credentials.
- Added a dedicated fast-mlsirm hourly caller that preserves Rust-owned psychometric arithmetic while dispatching at most one exact-head, root-cause-driven repair with a two-hour same-head retry floor.
- Added a dedicated Orgmetra hourly caller at minute 58 that targets protected `develop`, dispatches at most one exact-head repair, preserves a two-hour same-head retry floor and non-cancelling single-flight execution, and maps only the established scheduler credentials.

### Changed

- Emit completed repository pull-list requests as they finish in the five-minute
  agent-mention sweep, while retaining the four-worker ceiling, rotation, and
  exact-name dispatch ledger, so one slow repository cannot hide ready sibling
  repositories.
- Require the hourly repair worker to establish an exact-head root cause, enumerate the smallest remediation candidates, and prove writer authority, sealed-path scope, credentials, dependency order, verifiability, and causal effect before editing; infeasible or external blockers leave the tree unchanged while the broader loop continues with another eligible PR or buyer-visible product gap.
- Run the bounded Quarantine Sandbox Runtime heartbeat at minute 14 without granting the caller model secrets, repository mutation permissions, approval, merge, release, artifact-execution, or final security-verdict authority.
- Run the bounded Clearfolio PR review-feedback repair caller at minute 23 of every hour while keeping the shared scheduler free of product-specific timers and repository names for modular reuse by naruon, contextual-orchestrator, Inkspan, and other CWL services.
- Run the bounded DiskSage repair heartbeat at minute 37 of every hour, dispatch no more than one exact-head repair, and wait two hours before redispatching an unchanged head so legitimate OpenCode or NVIDIA NIM latency does not create duplicate writers.
- Run the bounded fast-mlsirm repair heartbeat at minute 49 of every hour with one-dispatch scope and a two-hour same-head floor, without weakening true-parameter recovery, CPU/GPU parity, skipped-test, or Rust-ownership gates.
- Use NVIDIA NIM `mistralai/mistral-small-4-119b-2603` with explicit high reasoning for scheduled repair and `nvidia/nemotron-3-nano-30b-a3b` for bounded helper work instead of GitHub Models in the write-capable autofix worker.
- Apply one NUL-delimited exact-path and complete pre/post-worktree verification contract to both ordinary review repair and merge-conflict repair rather than relying on a visible post-model diff for the ordinary path.

### Changed

- Avoided the expensive R/testthat failure-summary regular expression on marker-absent bounded logs by checking the required terminal marker first, while preserving fail-closed handling for incomplete or malformed failure evidence.

### Fixed

- Resolve Strix visibility from the trusted GitHub event for ordinary push,
  schedule, and pull-request runs, reserving API retries for cross-repository
  dispatches whose workflow token may not see the target repository.
- Reconciled the Strix required-workflow smoke contract and the privileged
  OpenCode model pool with the current `gpt-5.4` direct-OpenAI fallback after
  `gpt-5.6-luna` was retired. This prevents every consumer repository's
  required Strix check from failing on a stale central assertion or selecting a
  nonexistent direct model.

- Publish only the sanitized cumulative Strix report tree, avoiding a later
  copy of relative scanner output that could reintroduce known internal warning
  text into uploaded security evidence.

- Retry configured Strix fallback models when the primary provider records a
  rate-limit or infrastructure failure only in its structured report log, and
  evaluate each fallback against its newest report without letting an older
  failed attempt poison a complete later report.

- Include the exact `backend/app/*.py` package context in PR-scoped Strix
  scans when a module in that package changes. The trusted resolver uses a
  NUL-delimited exact-head tree listing, copies unchanged dependencies from
  the trusted base, and keeps changed-file attribution and provider failures
  fail-closed.
- Include the exact `contextual_orchestrator/*.py` sibling-import context under
  the same NUL-delimited exact-head and fail-closed path boundary without
  expanding changed-file finding attribution.
- Treat Rust source and Cargo manifests as governed Strix inputs and include
  trusted Cargo, toolchain, and `deny.toml` context when a workflow change
  scopes a Rust workspace.
- Run Strix with an explicit canonical scan target from a temporary working
  directory outside that target, so scanner state and relative reports cannot
  become self-scanned source findings; preserve those reports as gate evidence.
  PR-scoped Python scans also include the PostgreSQL introspection security
  helpers when that package exists in the target repository. PR scopes now live
  below the gate's private runtime directory so unrelated temporary-file
  cleanup cannot remove scan input during PR-head materialization.
- Classify Strix `ModelBehaviorError` with zero reported vulnerabilities as
  retryable model-protocol evidence, while keeping `Vulnerabilities [1-9]` and
  other severity signals fail-closed.
- Derived `org-queue-sweep`'s rotation index (added in `ContextualWisdomLab/.github#1220` to stop the walk-order starvation from `ContextualWisdomLab/.github#1219`) from a persistent `ORG_SWEEP_ROTATION_COUNTER` repository variable incremented by exactly one at the start of every actual sweep execution, instead of `github.run_number` (which increments on every trigger of this workflow, not only the sweep schedule — Devin review finding on `#1220`) or a wall-clock tick alone (which can repeat an offset when this single-flight, up-to-60-minute job runs behind schedule by an exact multiple of the repository count — CodeRabbit review finding on `#1223`). Falls back to the wall-clock tick only if the persistent counter itself is unavailable, so a fairness mechanism never blocks the sweep's review-dispatch/merge work.
- Retried the Strix scan up to `STRIX_TRANSIENT_RETRY_PER_MODEL` times, same model, when the log shows the upstream strix-agent Caido sandbox bootstrap timing race (`loginAsGuest failed after N attempts` / `Failed to connect to 127.0.0.1 port <port>`; tracked upstream as usestrix/strix#1036, #1037, #1056). A slow CI runner can exceed strix-agent's fixed 10-attempt sandbox-login budget before its local intercepting proxy is reachable, even though the penetration test itself never started and no vulnerability evidence was produced or lost; the Docker image is already cached from the failed attempt, so a same-model retry is cheap and typically clears the one-off boot race. Not wired into cross-model fallback, since switching LLM models cannot change local sandbox container boot timing.
- Replaced nonexistent `job.workflow_repository` / `job.workflow_sha` / `job.workflow_ref` / `job.workflow_file_path` context references (actionlint: "property ... is not defined in object type") in `pr-review-fix-scheduler.yml`'s called-workflow source verification and `exact-artifact-sbom-attestation.yml`'s trusted-verifier checkout. Both always failed closed on the missing properties (ContextualWisdomLab/.github#1212) or, for the SBOM attestation checkout, silently resolved an empty repository/ref instead of the pinned trusted source (downstream `gh attestation verify --signer-repo`/`--signer-workflow`, using the separately hardcoded `SIGNER_REPOSITORY` constant rather than any workflow_ref, still failed closed on the resulting empty signer identity). `github.workflow_ref`/`github.workflow_sha` are real, documented properties, but for a `workflow_call` target they reflect the top-level *calling* workflow, not the reusable workflow's own file — a prefix match against the reusable workflow's own path can never succeed. `exact-artifact-sbom-attestation.yml`'s checkout now uses `github.workflow_sha` (correct today: it has no callers yet); `pr-review-fix-scheduler.yml`'s identity check instead validates `github.repository`, since every current caller uses a local, same-repo `uses: ./...` where caller and callee share one commit and `github.workflow_sha` is still the right pin. Tracked follow-up for the SBOM attestation checkout once a real (potentially cross-repo) caller exists: ContextualWisdomLab/.github#1228.
- Used the receiving repository's workflow token for same-repository scheduler
  Actions inventory and read calls, while retaining the established mutation
  credential chain. An exhausted organization-wide OpenCode App installation
  budget can no longer prevent a central `.github` PR from dispatching its
  exact-head review; cross-repository targets still require an explicit
  credential.
- Kept independently valid root-level Python lock environments separate during
  trusted base coverage installation. A directory with more than two candidate
  locks no longer collapses unrelated OpenCode, security, and application
  environments into one impossible resolver transaction; incomplete hash
  closures remain skipped, while each complete hash-pinned closure installs
  independently.
- Rotated `org-queue-sweep`'s repository walk order by the workflow's own run number before applying the shared organization-wide review-dispatch/branch-update budget, so a fixed early repository in the unsorted `gh api /orgs/{org}/repos` walk order can no longer permanently starve every later repository's ready, all-green, zero-open-thread pull requests of the single per-tick dispatch (`ContextualWisdomLab/.github#1219`). The total per-tick budget is unchanged; only which repository consumes it rotates.
- Forward `trigger_reviews=true` explicitly from the trusted OpenCode mention wrapper to the authoritative scheduler while retaining GitHub's ten-key dispatch limit. Source-comment identity remains bound in the verified invocation claim and durable ledger instead of occupying an unused scheduler field, so a successfully routed `@opencode-agent` request now dispatches review work rather than entering queue maintenance with reviews disabled.
- Allowed an allowlisted base repository's open fork-head PR to enter the central exact-head OpenCode review path. The scheduler and privileged reviewer still re-read the live PR, bind base/head refs and SHAs, reject malformed repository identities, keep fork source as untrusted data, preserve the existing maintainer-writable update rule, and reserve the final external-head merge for a maintainer.
- Confined OSV base and head repository checkouts to the same `source/` child directory, so a cross-fork head checkout can replace that repository without deleting the base-scan JSON held at the workspace root. Both scans retain identical source paths and the required base/head vulnerability comparison remains fail-closed.
- Restored 100% docstring coverage for the commercial-readiness GitHub transport constructor.
- Refused PR Review Merge Scheduler head mutations, `update-branch` and the last-push approval head restamp, whenever the resolved mutation credential is the workflow `GITHUB_TOKEN`. GitHub starts no workflow run for events created with that credential, so the moved head collected no current-head required checks and the PR stayed permanently `BLOCKED` with a `github-actions[bot]` merge commit that no later scheduler run could repair, because the branch was no longer behind. The scheduler now waits with `head_mutation_credential_upgrade` guidance naming `PR_REVIEW_MERGE_TOKEN`, `OPENCODE_APPROVE_TOKEN`, and the OpenCode app token exchange.
- Parsed `opencode.jsonc` as JSONC (stripping `//` and `/* */` comments outside string literals) in the reasoning-effort guard and its contract tests, instead of raw `json.loads`, which rejected the file the moment it carried its first explanatory comment (added for the `contextual-orchestrator` provider block) with `Expecting property name enclosed in double quotes`. Comment markers inside string values, such as the `$schema` URL, are left untouched.
- Download the pinned `uv` 0.12.1 exporter from the official GitHub Releases URL instead of `releases.astral.sh`, which now returns HTTP 403 and blocks org-wide OpenCode `coverage-evidence`. The SHA-256 pin is unchanged. The opener may follow one hop onto `release-assets.githubusercontent.com` or `objects.githubusercontent.com` and still rejects every other host, userinfo, non-HTTPS scheme, and nondefault port (ContextualWisdomLab/.github#1109).
- Compared the trusted `uv` executable's post-install `--version` output against the real GitHub Releases build's full string, `uv 0.12.1 (x86_64-unknown-linux-gnu)`, instead of the bare `uv 0.12.1` the prior check required; the genuine release binary always prints the target triple, so every installation was failing the pin check immediately after the archive download itself was fixed (ContextualWisdomLab/.github#1109).
- Excluded relative `-r` and `--requirement` referrers from generated flat base-lock publication while retaining bounded include syntax diagnostics and discovering independently complete direct `.txt` children of `requirements` directories.
- Bound the central Semgrep job to one `SEMGREP_IMAGE` digest for log evidence, manifest inspection, and `docker run`, so a buyer reconstructing the scan can prove the logged scanner is the scanner that ran.
- Published substantive OpenCode LLM probes when they already carried an independent proof and exact source-line digest but omitted a duplicated `path:line` citation, so NVIDIA NIM / OpenCode review evidence is no longer discarded as `NO_CONCLUSION`.
- Refused a conflict-scope repository root whose immediate parent is a symbolic link, so a swapped parent cannot redirect the canonical worktree after the last-component check (CWE-367).
- Materialized base Python locks only when every package line is an exact SHA-256 pin or a bounded relative `-r`/`--requirement` include. A lone `--require-hashes` directive, a dotted include such as `./lock.txt`, or `-r other-hashes.txt` no longer enters the trusted build context.
- Bounded the Strix quality self-test's deterministic timeout fixtures to 3-second process and 5-second fake-sleep budgets so exact-head policy evidence completes inside the existing job limit without changing production Strix scanner timeouts, providers, credentials, or review semantics.
- Allowed commas and ASCII parentheses in the bounded Strix changed-file path policy so legal tracked Packrat fixtures can receive exact-head security analysis, while rejecting raw `..` components before normalization and keeping controls, backslashes, whitespace ambiguity, and shell punctuation fail-closed.
- Bound each review-agent invocation key to the wrapper's complete canonical payload, including the base branch and requesting actor; altered fields with a valid-format key now fail before durable-leader election or forwarding, and wrapper write permission is job-scoped.
- Hardened exact-artifact SBOM verification with strict finite RFC 8259 JSON, integer CycloneDX document versions, deterministic UUIDv5 subject identities, exact filename properties and single SHA-256 root bindings, environment-only shell input transfer, pinned Ubuntu 24.04 quality runners, and checksum-sealed beginner-readable offline evidence.
- Bound both trusted-uv quality jobs to `github.event.pull_request.head.sha` and added a permanent two-checkout regression contract so exact-head compatibility, coverage, docstring, and compilation claims cannot silently measure GitHub's generated pull-request merge revision.
- Made Strix treat only a single LiteLLM provider-error line containing NVIDIA NIM context and model-catalog 404 evidence as cross-model fallback evidence, rejecting cross-line signal assembly and provider-like target source literals; moved the public default to Nemotron 3 Super 120B and added a second NVIDIA hosted candidate before GitHub Models without neutralizing reported vulnerabilities.
- Bind reusable scheduler implementation to the validated called-workflow repository, SHA, ref, and file path, and verify the checked-out commit before executing privileged scheduler logic.
- Removed the ambiguous central-repository schedule fallback that could scan `.github` instead of Clearfolio when no external variable was configured; the active product caller now names Clearfolio explicitly while the reusable engine retains caller and dispatch overrides.
- Corrected the conflict-ordering regression contract to select the conflict-specific snapshot and verification after the ordinary path adopted the same trusted helper.
- Retried the Strix target-repository visibility lookup up to six times with linear backoff before failing closed, matching the existing PR-head-fetch retry convention in the same workflow. A single transient `gh api` failure (observed as a shared GitHub App installation token hitting its hourly rate limit while dozens of org repositories run hourly review schedulers concurrently) previously failed the entire required Strix check immediately, blocking otherwise mergeable, fully reviewed pull requests fleet-wide with no code defect involved.

### Security

- Keep the Quarantine Sandbox Runtime caller read-only and model-secret-free, grant only job-scoped OIDC to the reusable scheduler, and preserve the product boundary in which the sandbox returns artifact-analysis evidence while hosts retain WAF/IDS, admission, final verdict, incident, and retention authority.
- Reject `.github/` and `scripts/ci/` from review-thread-derived autofix path authority so an untrusted inline reviewer cannot authorize the write-capable repair agent to modify workflows, CODEOWNERS, actions, scheduler code, or CI helpers that govern its own control plane.
- Require the model-write snapshot and exact-path allowlist to remain outside the pull-request worktree, checking both absolute and resolved locations so repository-local controls and outside-looking symlinks resolving into the repository fail closed before they can authorize or verify model changes.
- Snapshot the complete pre-model worktree for ordinary and conflict repair and reject every model-caused created, deleted, modified, mode-changed, retargeted, ignored, dangling, directory-backed, external-link, metadata-race, or out-of-scope path before staging or push.
- Add ignored-path inventory through Git's tracked, other, and `--others --ignored --exclude-standard` views so model-created caches, credentials, or build output cannot evade comparison merely because ordinary Git publication omits them.
- Deny `.git` and `.git/*` in both OpenCode permission maps, disable repository hooks for privileged commit and push through `core.hooksPath=/dev/null`, and push only to an explicit revalidated repository URL so model-mutable Git metadata cannot control publication.
- Keep the Clearfolio caller and reusable scheduler read-only at workflow and job scope; authorize mutation only through explicitly mapped `PR_REVIEW_MERGE_TOKEN`, `OPENCODE_APPROVE_TOKEN`, or the short-lived OpenCode GitHub App token exchanged from OIDC, with explicit pre-write guards and no `github.token` mutation fallback.
- Keep the DiskSage caller read-only and pass only the established scheduler credentials; do not inherit secrets, expose the NVIDIA NIM model credential to the queue scanner, use a GitHub Copilot token, or grant the caller repository mutation permissions.
- Keep the fast-mlsirm caller read-only and model-secret-free; preserve independent approval, exact-head evidence, and Rust production-arithmetic ownership while centralizing only bounded review repair.
- Bind `NVIDIA_NIM_API_KEY` only to the two OpenCode model execution steps, fail closed when the secret is absent, and remove GitHub and Actions OIDC credentials from both model subprocesses. The decision record now cites CWE-367 so a later default-branch push cannot replace privileged repair helpers after `repository_dispatch` has already selected the workflow revision.
- Recorded the org control-plane architecture, including the hourly NVIDIA NIM repair gate, so agents reconstruct the write-capable worker trust boundary from the repo instead of private memory.
- Deny unnecessary non-file OpenCode interactions and preserve the independent read-only reviewer workflow and its credential/model-pool contract byte-for-byte.
- Pin the repository-dispatch autofix helper checkout to the exact workflow-run SHA rather than a moving default branch.
- Pass only `PR_REVIEW_MERGE_TOKEN` and `OPENCODE_APPROVE_TOKEN` from the Clearfolio schedule caller; do not use `secrets: inherit` and do not expose the NVIDIA model credential to the queue-scanning workflow.

### Documentation

- Added Quarantine Sandbox Runtime operator and APA 7 doctoring for the hourly RCA loop, source-agnostic leaf boundary, protected-`develop` activation, bounded retry cadence, OIDC and secret scope, independent approval, verification, and rollback.
- Rewrote the root README for org operators and sibling-repo maintainers: org profile plus central required workflows, standalone run, and how siblings consume ruleset `18156473` without copying workflow files. Moved bot/agent PR-review procedure to `docs/pr-review-and-merge-procedure.md`.
- Retargeted the Strix quality-gate prose contract to the review procedure document.
- Added an APA 7 doctoring record for conflict-control evidence isolation, including the Strix-reported trust-boundary failure, test-first remediation, canonical-path rule, operator contract, rollback, MITRE CWE-22, and current GitHub Actions secure-use guidance.
- Added operator and APA 7 doctoring records for the hourly cadence, immutable source identity, NVIDIA NIM provider and secret boundary, high-reasoning Mistral Small 4 writer, model-process credential isolation, modular MSA ownership, product-specific caller activation, verification contract, and rollback.
- Added DiskSage operational documentation for the hourly RCA loop, bounded retry cadence, permission model, standalone and MSA reuse, verification, rollback, and APA 7 references.
- Added fast-mlsirm operational documentation for the hourly RCA loop, psychometric scientific gates, Rust ownership, bounded retry cadence, credential isolation, modular reuse, rollback, and APA 7 references.
- Documented the ordinary and conflict repair write-scope parity, ignored-path and symlink inventory, Git-control-file denial, hook suppression, explicit push destination, RED/GREEN evidence, operator response, and local-versus-protected evidence boundary.
- Documented the review-authentication boundary that excludes autonomous writer control-plane paths from review-derived file authority, its test-first Strix security evidence, exact-head coverage contract, and rollback prohibition.

- Added an organization-owned reusable exact-artifact SBOM attestation boundary that validates inert six-file wheel/sdist evidence, binds CycloneDX 1.7 predicates to exact SHA-256 subjects, signs through least-privilege GitHub artifact attestations, and exports online and offline verification bundles.
- Hardened exact-artifact SBOM verification with strict finite RFC 8259 JSON, integer CycloneDX document versions, deterministic UUIDv5 subject identities, exact filename properties and single SHA-256 root bindings, environment-only shell input transfer, pinned Ubuntu 24.04 quality runners, and checksum-sealed beginner-readable offline evidence. The decision record now cites Bray (2017) so NaN and Infinity cannot be treated as sealed SBOM numbers.
- Recorded the org control-plane architecture, including exact-artifact SBOM attestation, so agents reconstruct the signing trust boundary from the repo instead of private memory.
