# Changelog

All notable changes to the organization automation repository are documented in
this file. The format follows Keep a Changelog, and versioned releases follow
Semantic Versioning where the repository publishes a release.

## [Unreleased]

### Added

- Added a trusted pull-request comment router for `@cwl-noema-review` and review-only `@opencode-agent` dispatches, with an organization sweep, exact-head receipts, repository allowlisting, fixed runners, immutable checkout pins, and a permanent 100% statement/branch/docstring quality gate.
- Added exact-base `uv.lock` materialization that reconstructs standalone nested projects with a checksum-pinned official `uv` exporter, isolated frozen/offline execution, strict exact-pin and SHA-256 output validation, and complete Python 3.10/3.14 quality evidence.

### Fixed

- Sanitized leftover overview receipt path and phrase so a leftover cannot close `<!-- opencode-review-overview -->` or reopen a GitHub suggestion fence (CWE-116).
- Materialized base Python locks only when every package line is an exact SHA-256 pin or a bounded relative `-r`/`--requirement` include. A lone `--require-hashes` directive, a dotted include such as `./lock.txt`, or `-r other-hashes.txt` no longer enters the trusted build context.
- Recorded attach and refusal `path:line` from `start_line` when a multi-line GitHub suggestion rewrote `line` to the span end, so overview receipts still match the trusted finding line.
- Kept `start_line`/`start_side` on one-at-a-time 422 retries so a multi-line GitHub suggestion still posts as one range instead of a single comment on the last line.
- Capped one-at-a-time OpenCode inline retries at 20 comments and listed attached `path:line` beside refused receipts so the overview shows both outcomes, plus any locations left untried by the cap. A `422` substring inside a SHA or issue number no longer starts that retry (CWE-1288), and receipt phrases escape backticks and HTML metacharacters.
- Kept each refused OpenCode inline comment's own GitHub 422 phrase next to its `path:line` so mixed retries do not collapse every failure into one shared error sentence.
- After a mixed one-at-a-time inline retry, listed only the refused `path:line` rows in the overview receipts so attached hunks are not reported as failed.
- After a batch GitHub 422, retried OpenCode inline comments one at a time so comments on surviving hunks still attach instead of dropping the entire review thread.
- Stored each refused OpenCode inline comment as a durable overview receipt that pairs the trusted `path:line` with the GitHub 422 error phrase from `gh api` stderr or JSON `errors[].message`.
- Named each trusted `path:line` in the OpenCode GitHub 422 inline-comment fallback so a refused attach still tells the author the exact current-head location instead of a generic “cited finding lines” sentence.
- Bounded the Strix quality self-test's deterministic timeout fixtures to 3-second process and 5-second fake-sleep budgets so exact-head policy evidence completes inside the existing job limit without changing production Strix scanner timeouts, providers, credentials, or review semantics.
- Allowed commas and ASCII parentheses in the bounded Strix changed-file path policy so legal tracked Packrat fixtures can receive exact-head security analysis, while rejecting raw `..` components before normalization and keeping controls, backslashes, whitespace ambiguity, and shell punctuation fail-closed.
- Bound each review-agent invocation key to the wrapper's complete canonical payload, including the base branch and requesting actor; altered fields with a valid-format key now fail before durable-leader election or forwarding, and wrapper write permission is job-scoped.
- Bound both trusted-uv quality jobs to `github.event.pull_request.head.sha` and added a permanent two-checkout regression contract so exact-head compatibility, coverage, docstring, and compilation claims cannot silently measure GitHub's generated pull-request merge revision.
- Made Strix treat only a single LiteLLM provider-error line containing NVIDIA NIM context and model-catalog 404 evidence as cross-model fallback evidence, rejecting cross-line signal assembly and provider-like target source literals; moved the public default to Nemotron 3 Super 120B and added a second NVIDIA hosted candidate before GitHub Models without neutralizing reported vulnerabilities.
