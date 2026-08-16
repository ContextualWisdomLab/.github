# Changelog

All notable changes to the organization automation repository are documented in
this file. The format follows Keep a Changelog, and versioned releases follow
Semantic Versioning where the repository publishes a release.

## [Unreleased]

### Added

- Added a trusted pull-request comment router for `@cwl-noema-review` and review-only `@opencode-agent` dispatches, with an organization sweep, exact-head receipts, repository allowlisting, fixed runners, immutable checkout pins, and a permanent 100% statement/branch/docstring quality gate.
- Added exact-base `uv.lock` materialization that reconstructs standalone nested projects with a checksum-pinned official `uv` exporter, isolated frozen/offline execution, strict exact-pin and SHA-256 output validation, and complete Python 3.10/3.14 quality evidence.
- Added a permanent exact-head contract workflow for the hourly review-repair scheduler, immutable reusable-workflow source, NVIDIA NIM model boundary, credential isolation, and fail-closed unattended-agent permissions.
- Added a dedicated Clearfolio hourly caller that invokes the product-neutral central scheduler with the exact repository, protected base branch, one-dispatch budget, one-hour retry floor, single-flight concurrency, and only the established scheduler credentials.
- Added a dedicated DiskSage hourly caller that invokes the same product-neutral RCA and remediation-feasibility scheduler with an exact repository target, one-dispatch budget, two-hour same-head retry floor, non-cancelling single-flight heartbeat, and explicit established scheduler credentials.
- Added a dedicated fast-mlsirm hourly caller that preserves Rust-owned psychometric arithmetic while dispatching at most one exact-head, root-cause-driven repair with a two-hour same-head retry floor.

### Changed

- Require the hourly repair worker to establish an exact-head root cause, enumerate the smallest remediation candidates, and prove writer authority, sealed-path scope, credentials, dependency order, verifiability, and causal effect before editing; infeasible or external blockers leave the tree unchanged while the broader loop continues with another eligible PR or buyer-visible product gap.
- Run the bounded Clearfolio PR review-feedback repair caller at minute 23 of every hour while keeping the shared scheduler free of product-specific timers and repository names for modular reuse by naruon, contextual-orchestrator, Inkspan, and other CWL services.
- Run the bounded DiskSage repair heartbeat at minute 37 of every hour, dispatch no more than one exact-head repair, and wait two hours before redispatching an unchanged head so legitimate OpenCode or NVIDIA NIM latency does not create duplicate writers.
- Run the bounded fast-mlsirm repair heartbeat at minute 49 of every hour with one-dispatch scope and a two-hour same-head floor, without weakening true-parameter recovery, CPU/GPU parity, skipped-test, or Rust-ownership gates.
- Use NVIDIA NIM `mistralai/mistral-small-4-119b-2603` with explicit high reasoning for scheduled repair and `nvidia/nemotron-3-nano-30b-a3b` for bounded helper work instead of GitHub Models in the write-capable autofix worker.
- Apply one NUL-delimited exact-path and complete pre/post-worktree verification contract to both ordinary review repair and merge-conflict repair rather than relying on a visible post-model diff for the ordinary path.

### Fixed

- Pinned OpenSSF Scorecard to one immutable action SHA (`2d1146689b8cda280b9bc96326124645441f03bc`, v2.4.4) on both the PR visibility job and the default-branch analysis job so a Dependabot split cannot execute a second unreviewed control sphere (CWE-829).
- Materialized base Python locks only when every package line is an exact SHA-256 pin or a bounded relative `-r`/`--requirement` include. A lone `--require-hashes` directive, a dotted include such as `./lock.txt`, or `-r other-hashes.txt` no longer enters the trusted build context.
- Refused a conflict-scope repository root whose immediate parent is a symbolic link, so a swapped parent cannot redirect the canonical worktree after the last-component check (CWE-367).
- Bounded the Strix quality self-test's deterministic timeout fixtures to 3-second process and 5-second fake-sleep budgets so exact-head policy evidence completes inside the existing job limit without changing production Strix scanner timeouts, providers, credentials, or review semantics.
- Allowed commas and ASCII parentheses in the bounded Strix changed-file path policy so legal tracked Packrat fixtures can receive exact-head security analysis, while rejecting raw `..` components before normalization and keeping controls, backslashes, whitespace ambiguity, and shell punctuation fail-closed.
- Bound each review-agent invocation key to the wrapper's complete canonical payload, including the base branch and requesting actor; altered fields with a valid-format key now fail before durable-leader election or forwarding, and wrapper write permission is job-scoped.
- Bound both trusted-uv quality jobs to `github.event.pull_request.head.sha` and added a permanent two-checkout regression contract so exact-head compatibility, coverage, docstring, and compilation claims cannot silently measure GitHub's generated pull-request merge revision.
- Made Strix treat only a single LiteLLM provider-error line containing NVIDIA NIM context and model-catalog 404 evidence as cross-model fallback evidence, rejecting cross-line signal assembly and provider-like target source literals; moved the public default to Nemotron 3 Super 120B and added a second NVIDIA hosted candidate before GitHub Models without neutralizing reported vulnerabilities.
- Bind reusable scheduler implementation to the validated called-workflow repository, SHA, ref, and file path, and verify the checked-out commit before executing privileged scheduler logic.
- Removed the ambiguous central-repository schedule fallback that could scan `.github` instead of Clearfolio when no external variable was configured; the active product caller now names Clearfolio explicitly while the reusable engine retains caller and dispatch overrides.
- Corrected the conflict-ordering regression contract to select the conflict-specific snapshot and verification after the ordinary path adopted the same trusted helper.

### Security

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

- Added an APA 7 doctoring record for conflict-control evidence isolation, including the Strix-reported trust-boundary failure, test-first remediation, canonical-path rule, operator contract, rollback, MITRE CWE-22, and current GitHub Actions secure-use guidance.
- Added operator and APA 7 doctoring records for the hourly cadence, immutable source identity, NVIDIA NIM provider and secret boundary, high-reasoning Mistral Small 4 writer, model-process credential isolation, modular MSA ownership, product-specific caller activation, verification contract, and rollback.
- Added DiskSage operational documentation for the hourly RCA loop, bounded retry cadence, permission model, standalone and MSA reuse, verification, rollback, and APA 7 references.
- Added fast-mlsirm operational documentation for the hourly RCA loop, psychometric scientific gates, Rust ownership, bounded retry cadence, credential isolation, modular reuse, rollback, and APA 7 references.
- Documented the ordinary and conflict repair write-scope parity, ignored-path and symlink inventory, Git-control-file denial, hook suppression, explicit push destination, RED/GREEN evidence, operator response, and local-versus-protected evidence boundary.
- Documented the review-authentication boundary that excludes autonomous writer control-plane paths from review-derived file authority, its test-first Strix security evidence, exact-head coverage contract, and rollback prohibition.