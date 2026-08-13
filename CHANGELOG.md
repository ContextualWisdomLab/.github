# Changelog

All notable changes to the organization automation repository are documented in
this file. The format follows Keep a Changelog, and versioned releases follow
Semantic Versioning where the repository publishes a release.

## [Unreleased]

### Added

- Added a trusted pull-request comment router for `@cwl-noema-review` and review-only `@opencode-agent` dispatches, with an organization sweep, exact-head receipts, repository allowlisting, fixed runners, immutable checkout pins, and a permanent 100% statement/branch/docstring quality gate.
- Added exact-base `uv.lock` materialization that reconstructs standalone nested projects with a checksum-pinned official `uv` exporter, isolated frozen/offline execution, strict exact-pin and SHA-256 output validation, and complete Python 3.10/3.14 quality evidence.
- Central OpenCode and Noema review prompts now require a per-changed-file walk with an explicit disposition for every path, and they allocate review compute by workflow stage, role, and inference-level ablation (Fugu / Conductor / TRINITY) rather than wall-clock speed.

### Fixed

- GraphQL `addReaction` on a submitted review body treats the already-reacted error as success and refuses an empty or missing `data.addReaction` payload, so a second mention on the same review is not a missed dispatch and a blank 200 is not eyes.
- `@cwl-noema-review` and `@opencode-agent` mentions in submitted review bodies now receive the optional eyes reaction through GraphQL `addReaction` on the review node. A 403 or GraphQL error is a warning after dispatch, not a missed mention.
- `@cwl-noema-review` and `@opencode-agent` mentions on pull-request review comments now receive the optional eyes reaction on `POST /pulls/comments/{id}/reactions`. A 403 there is still a warning, not a missed dispatch. Submitted review bodies still have no REST reaction endpoint.
- The local mention-router job now declares `reactions: write` so the optional eyes reaction is an allowed GitHub App write instead of live `403 Resource not accessible by integration` (runs 31686563920, 31670687388). The reaction remains non-fatal if GitHub still refuses it.
- Pending and dismissed pull-request reviews no longer dispatch `@cwl-noema-review` / `@opencode-agent` mentions; only submitted non-dismissed review bodies in the sweep lookback are requests.
- OpenCode mention dispatch now nests review-only flags under one `review_contract` property so the `repository_dispatch` `client_payload` stays at GitHub's 10-key limit. Live router run 31672030631 queued Noema for ContextualWisdomLab/.github#956@0c253f0d and then failed OpenCode with HTTP 422 ("14 were supplied"). Invocation-key hashing is unchanged.
- Trusted `@cwl-noema-review` and `@opencode-agent` mentions on pull-request review comments and submitted review bodies now reach the mention router and organization sweep, including mixed-case handles; the local workflow hydrates the live PR from `issue.number` or `pull_request.number` and no longer depends on a case-sensitive conversation-comment body filter.
- A 403 on the optional eyes reaction after a successful agent dispatch no longer fails the mention job; the local router now has `pull-requests: write` so pull-request receipt comments can be posted. The decision record now cites CWE-755 so an exceptional reaction response cannot be treated as a missed dispatch.
- Recorded the org control-plane architecture, including the three mention surfaces, so agents reconstruct the review-dispatch trust boundary from the repo instead of private memory.
- Bounded the Strix quality self-test's deterministic timeout fixtures to 3-second process and 5-second fake-sleep budgets so exact-head policy evidence completes inside the existing job limit without changing production Strix scanner timeouts, providers, credentials, or review semantics.
- Allowed commas and ASCII parentheses in the bounded Strix changed-file path policy so legal tracked Packrat fixtures can receive exact-head security analysis, while rejecting raw `..` components before normalization and keeping controls, backslashes, whitespace ambiguity, and shell punctuation fail-closed.
- Bound each review-agent invocation key to the wrapper's complete canonical payload, including the base branch and requesting actor; altered fields with a valid-format key now fail before durable-leader election or forwarding, and wrapper write permission is job-scoped.
- Bound both trusted-uv quality jobs to `github.event.pull_request.head.sha` and added a permanent two-checkout regression contract so exact-head compatibility, coverage, docstring, and compilation claims cannot silently measure GitHub's generated pull-request merge revision.
- Made Strix treat only a single LiteLLM provider-error line containing NVIDIA NIM context and model-catalog 404 evidence as cross-model fallback evidence, rejecting cross-line signal assembly and provider-like target source literals; moved the public default to Nemotron 3 Super 120B and added a second NVIDIA hosted candidate before GitHub Models without neutralizing reported vulnerabilities.
