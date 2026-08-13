# Changelog

All notable changes to the organization automation repository are documented in
this file. The format follows Keep a Changelog, and versioned releases follow
Semantic Versioning where the repository publishes a release.

## [Unreleased]

### Added

- Added a trusted pull-request comment router for `@cwl-noema-review` and review-only `@opencode-agent` dispatches, with an organization sweep, exact-head receipts, repository allowlisting, fixed runners, immutable checkout pins, and a permanent 100% statement/branch/docstring quality gate.
- Added exact-base `uv.lock` materialization that reconstructs standalone nested projects with a checksum-pinned official `uv` exporter, isolated frozen/offline execution, strict exact-pin and SHA-256 output validation, and complete Python 3.10/3.14 quality evidence.

### Fixed

- Omitted the duplicate leftover reason bullet when a leftover line sits inside a deferred multi-line `path:start-end`, so authors see the deferred range then the Manual-edit excerpt.
- Omitted the duplicate leftover reason bullet when the leftover heading already prefixes a deferred range/origin for the same `path:line`, so authors see one deferred line then the Manual-edit excerpt.
- Listed a deferred leftover ahead of its Manual-edit excerpt in the leftover heading when the same `path:line` is both deferred and leftover, so authors see the unposted fence first.
- Kept both the leftover Manual-edit ` ```diff ` block and the deferred range/origin row when a cannot-provide or pure-deletion leftover sits past the 20-comment 422 retry cap, and still omitted those fences from applyable GitHub suggestions.
- Recorded leftover OpenCode comments past the 20-comment 422 retry cap as deferred overview ranges with their LEFT origin, and stopped listing them under applyable GitHub suggestions because those comments are never posted.
- Kept `start_line`/`start_side` on remapped leftover OpenCode suggestions when a batch 422 is retried one comment at a time, so a multi-line RIGHT range still posts as one GitHub suggestion.
- Labeled remapped leftover OpenCode applyable ranges with the original LEFT `path:line` so the overview shows `path:right` came from LEFT `path:left`.
- Anchored remapped leftover OpenCode LEFT comments to the first RIGHT line of the same `@@` hunk when the original line is gone, so multi-hunk files do not attach the suggestion to an earlier hunk.
- Remapped leftover OpenCode LEFT suggested-diff comments onto a same-path current-head RIGHT hunk when one exists so those replacements become one-click GitHub suggestions instead of leftover manual-edit blocks. Pure deletions and cannot-provide fences stay leftover.
- Persisted leftover OpenCode `cannot-provide` and `LEFT` suggested-diff replacement text as a distinct overview “Manual edit (not a GitHub suggestion):” ```diff block so authors can copy the change by hand without treating it as an applyable `path:line` / `path:start-end` GitHub suggestion.
- Distinguished applyable OpenCode GitHub suggestion ranges from leftover ```diff fences (`cannot-provide` or `LEFT`) in the overview receipts so authors can see which hunks are one-click applies and which still need a manual edit.
- Listed applyable OpenCode GitHub suggestion ranges (`path:line` or `path:start-end`) in the overview receipts so authors can see which surviving hunks shipped as one-click applies.
- Set `start_line`/`line` on surviving multi-line OpenCode GitHub suggestions so a replacement that spans more than one current-head hunk line applies as one range.
- Converted surviving OpenCode inline suggested diffs into GitHub `suggestion` blocks so authors can apply the replacement on the current-head hunk in one click.
- Dropped OpenCode inline comments that sit outside every current-head changed hunk before the GitHub POST so those comments become overview receipts instead of a 422 that wipes the batch.
- Capped one-at-a-time OpenCode inline retries at 20 comments and listed attached `path:line` beside refused receipts so the overview shows both outcomes, plus any locations left untried by the cap.
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
