# Changelog

All notable changes to the organization automation repository are documented in
this file. The format follows Keep a Changelog, and versioned releases follow
Semantic Versioning where the repository publishes a release.

## [Unreleased]

### Added

- Added a trusted pull-request comment router for `@cwl-noema-review` and review-only `@opencode-agent` dispatches, with an organization sweep, exact-head receipts, repository allowlisting, fixed runners, immutable checkout pins, and a permanent 100% statement/branch/docstring quality gate.
- Added exact-base `uv.lock` materialization that reconstructs standalone nested projects with a checksum-pinned official `uv` exporter, isolated frozen/offline execution, strict exact-pin and SHA-256 output validation, and complete Python 3.10/3.14 quality evidence.

### Fixed

- Strix no longer fails a required check when a mid-retry TUI `Severity:` / `Vulnerabilities N` line is left in the console after the trusted gate already printed that those markers are incomplete log-only evidence. GitHub Models `github_models_retirement_brownout` is classified as backend unavailability. The exact gate sentence `failed after provider infrastructure or failure-signal output` is also classified as backend unavailability. Accepted findings without that gate verdict still fail closed. The decision record now cites CWE-754 so leftover TUI severity cannot be treated as an accepted finding.
- Recorded the org control-plane architecture, including the incomplete-retry severity gate, so agents reconstruct the Strix evidence trust boundary from the repo instead of private memory.
- Replaced indented `<<'PY'` inline Python in `strix.yml` with quoted `python3 -c` programs so a raw `bash -n` of the workflow is no longer an unclosed-heredoc false fail, and added a contract that extracts the Actions-stripped run blocks and executes the trusted-source, executable-hash, and Vertex credential snippets.
- Bounded the Strix quality self-test's deterministic timeout fixtures to 3-second process and 5-second fake-sleep budgets so exact-head policy evidence completes inside the existing job limit without changing production Strix scanner timeouts, providers, credentials, or review semantics.
- Allowed commas and ASCII parentheses in the bounded Strix changed-file path policy so legal tracked Packrat fixtures can receive exact-head security analysis, while rejecting raw `..` components before normalization and keeping controls, backslashes, whitespace ambiguity, and shell punctuation fail-closed.
- Bound each review-agent invocation key to the wrapper's complete canonical payload, including the base branch and requesting actor; altered fields with a valid-format key now fail before durable-leader election or forwarding, and wrapper write permission is job-scoped.
- Bound both trusted-uv quality jobs to `github.event.pull_request.head.sha` and added a permanent two-checkout regression contract so exact-head compatibility, coverage, docstring, and compilation claims cannot silently measure GitHub's generated pull-request merge revision.
- Made Strix treat only a single LiteLLM provider-error line containing NVIDIA NIM context and model-catalog 404 evidence as cross-model fallback evidence, rejecting cross-line signal assembly and provider-like target source literals; moved the public default to Nemotron 3 Super 120B and added a second NVIDIA hosted candidate before GitHub Models without neutralizing reported vulnerabilities.
