# Changelog

All notable changes to the organization automation repository are documented in
this file. The format follows Keep a Changelog, and versioned releases follow
Semantic Versioning where the repository publishes a release.

## [Unreleased]

### Added

- Added a trusted pull-request comment router for `@cwl-noema-review` and review-only `@opencode-agent` dispatches, with an organization sweep, exact-head receipts, repository allowlisting, fixed runners, immutable checkout pins, and a permanent 100% statement/branch/docstring quality gate.
- Added exact-base `uv.lock` materialization that reconstructs standalone nested projects with a checksum-pinned official `uv` exporter, isolated frozen/offline execution, strict exact-pin and SHA-256 output validation, and complete Python 3.10/3.14 quality evidence.

### Fixed

- A REQUEST_CHANGES finding now also names a current-head file when its suggested diff carries matching `--- a/X` and `+++ b/X` headers, even if the `diff --git` line is missing. A mismatched pair still names neither path (IEEE 1028; CWE-1288).
- A REQUEST_CHANGES finding now also names a current-head file when its suggested diff carries an identical `diff --git a/X b/X` header. A mismatched `a/` and `b/` pair does not dispose either path (IEEE 1028).
- OpenCode REQUEST_CHANGES now fails closed when the review omits any current-head changed file. A finding path or a named no-blocker disposition counts; a single-file blocker that never mentions the rest of the diff is not a file-by-file walk (IEEE 1028).
- OpenCode APPROVE now treats a path as named only when it appears as a whole token, so citing `example.py.bak` cannot dispose `example.py` via a prefix substring.
- OpenCode APPROVE now fails closed when the reason/summary omits any current-head changed file. Naming one path is no longer a file-by-file walk; the trusted changed-file artifact remains the file set. The decision record now cites IEEE 1028 so every changed item must receive a review disposition.
- Recorded the org control-plane architecture, including the per-file approval walk, so agents reconstruct the approval trust boundary from the repo instead of private memory.
- Bounded the Strix quality self-test's deterministic timeout fixtures to 3-second process and 5-second fake-sleep budgets so exact-head policy evidence completes inside the existing job limit without changing production Strix scanner timeouts, providers, credentials, or review semantics.
- Allowed commas and ASCII parentheses in the bounded Strix changed-file path policy so legal tracked Packrat fixtures can receive exact-head security analysis, while rejecting raw `..` components before normalization and keeping controls, backslashes, whitespace ambiguity, and shell punctuation fail-closed.
- Bound each review-agent invocation key to the wrapper's complete canonical payload, including the base branch and requesting actor; altered fields with a valid-format key now fail before durable-leader election or forwarding, and wrapper write permission is job-scoped.
- Bound both trusted-uv quality jobs to `github.event.pull_request.head.sha` and added a permanent two-checkout regression contract so exact-head compatibility, coverage, docstring, and compilation claims cannot silently measure GitHub's generated pull-request merge revision.
- Made Strix treat only a single LiteLLM provider-error line containing NVIDIA NIM context and model-catalog 404 evidence as cross-model fallback evidence, rejecting cross-line signal assembly and provider-like target source literals; moved the public default to Nemotron 3 Super 120B and added a second NVIDIA hosted candidate before GitHub Models without neutralizing reported vulnerabilities.
