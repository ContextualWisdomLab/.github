# OpenCode review surfaces and OriginWeave coverage sandbox

검토 기준일: **2026-08-16**

## Incident

ContextualWisdomLab/OriginWeave#47, head
`79cf275686e2376a51783a2d03128eca21e7c0e5`, workflow run `31951179896`,
published the same body as both the formal pull-request review and the issue
comment: a generic overview plus one HIGH finding on
`.github/workflows/opencode-review.yml:1` saying coverage-evidence failed. The
pull request actually changed
`crates/originweave-destination/src/lib.rs`, `resolution.rs`, and
`tests/resolution_freshness.rs` (FreshResolutionSnapshot / DNS-rebinding
TOCTOU). The mermaid inventory said `Changed file (3 files)` because unknown
paths, including `crates/`, were bucketed as "Changed file". Repository CI on
that head passed. The central isolated coverage job failed and replaced the
entire review.

## Root cause

When `needs.coverage-evidence.result != success`, the publisher synthesized
`REQUEST_CHANGES`, posted it with `gh pr review` and again as an issue comment,
and exited before the model pool could review the diff. The coverage sandbox
false blocker was Debian rustc 1.85 plus cargo-llvm-cov 0.8.7 without
`llvm-tools-preview`, in a `--network=none` image, against a workspace that
declares `rust-version = "1.97"` and `edition = "2024"`. The job log was
`failed to find llvm-tools-preview`. The default 100% line threshold was not
the false blocker: OriginWeave also requires 100% in repository CI.

## Decision

Coverage remains a fail-closed gate. It is no longer the review.

1. The formal pull-request review is a source-backed walkthrough of the
   current-head product diff, including a fallback review that names the
   changed crate files when the model pool did not emit a control block.
2. The issue comment is gate/status only: head SHA, run id/attempt, coverage
   result, model-pool outcome, verdict, and a link to the formal review. It
   must not repeat `## Pull request overview`, `## Findings`, mermaid, or the
   model walkthrough.
3. A coverage miss, skip, or unsupported-tooling result blocks approval and
   fails the required review job after the diff review is published. It must
   not cite `.github/workflows/opencode-review.yml:1` unless that file is in
   the pull-request diff.
4. The trusted coverage image materializes bounded `Cargo.toml` /
   `Cargo.lock` / `rust-toolchain.toml` / workspace member manifests, installs
   the declared rustup channel with `llvm-tools-preview` when it is newer than
   Debian rustc 1.85, prefetches the lockfile, and runs
   `cargo llvm-cov --offline --locked`. Repos that ship
   `scripts/ci/verify_coverage.py` without
   `workspace.metadata.opencode.coverage` run that verifier instead of the
   canned `--fail-under-lines 100` default. rustc/cargo identity and the full
   rust/python/js measure log are published in `coverage_summary`. A real
   coverage miss still fails.
5. Coverage-evidence failure is injected into `bounded-review-evidence.md` as
   a `## Coverage gate` section. The model pool still runs. The publisher does
   not early-return before the model path. `format_request_changes_body` keeps
   model walkthrough/diagrams and appends structured findings.

Read-only review-agent permissions, NVIDIA NIM-first routing
(`NVIDIA_NIM_API_KEY` bound into `NVIDIA_API_KEY`), OpenCode CLI 1.17.13, and
the existing review-bot identity are unchanged. `COPILOT_GITHUB_TOKEN` is not
introduced. The same dispatch file now gives NIM (and matching cadence /
dynamic-cap) a 7200s run window instead of the 180s kill that skipped
reviews on ContextualWisdomLab/fast-mlsirm#290, keeps GPT-5 / free-tier
short, and omits `opencode/gpt-5.6-terra` and `github-models/*` from the
pool. Concurrency remains PR-number scoped with `cancel-in-progress: true`.

## Verification contract

Regression tests prove that:

1. the formal review body is not equal to the status comment;
2. a coverage-gate failure still produces a review that names the changed
   crate files;
3. no finding is anchored to `opencode-review.yml:1` unless that file is in
   the diff;
4. mermaid labels a `crates/...` change as a Rust crate surface, not
   `Changed file (3 files)`;
5. the publisher function
   `request_changes_for_coverage_evidence_failure` updates the status comment
   and does not call `create_pull_review`;
6. the model pool still runs when coverage-evidence failed (`!= cancelled`);
7. bounded Rust toolchain materialization copies manifests only, selects
   rustup 1.97 for OriginWeave-style workspaces, and rejects parent-directory
   members and symlinks; and
8. a rust-version 1.97 workspace without opencode coverage metadata does not
   publish the canned coverage review as the entire PR review. Repos that
   ship `scripts/ci/verify_coverage.py` use that verifier instead of default
   `--fail-under-lines 100`.

## Limitations

A later rustup or llvm-tools catalog change can still fail the image build.
That failure remains a coverage-gate failure, not a synthesized product-file
finding. The sandbox does not weaken a genuine below-threshold coverage miss.

## References

GitHub, Inc. (2026). *REST API endpoints for pull request reviews*. GitHub
Docs.
https://docs.github.com/en/rest/pulls/reviews

Rust Project Developers. (2026). *The rustup book*. Rust Project.
https://rust-lang.github.io/rustup/

Taiki Endo. (2026). *cargo-llvm-cov*. GitHub.
https://github.com/taiki-e/cargo-llvm-cov
