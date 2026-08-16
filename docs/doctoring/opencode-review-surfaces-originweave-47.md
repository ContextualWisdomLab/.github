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
2. The issue comment is gate/status only: head SHA, run id, coverage/check
   results, and the hidden approve-gate control block. It must not repeat
   `## Pull request overview` or `## Findings`.
3. A coverage miss, skip, or unsupported-tooling result blocks approval and
   fails the required review job after the diff review is published. It must
   not cite `.github/workflows/opencode-review.yml:1` unless that file is in
   the pull-request diff.
4. The trusted coverage image materializes bounded `Cargo.toml` /
   `Cargo.lock` / `rust-toolchain.toml` / workspace member manifests, installs
   the declared rustup channel with `llvm-tools-preview` when it is newer than
   Debian rustc 1.85, prefetches the lockfile, and runs
   `cargo llvm-cov --offline --locked`. A real coverage miss still fails.

Read-only review-agent permissions, NVIDIA NIM-first routing
(`NVIDIA_NIM_API_KEY` bound into `NVIDIA_API_KEY`), OpenCode CLI 1.17.13, and
the existing review-bot identity are unchanged. `COPILOT_GITHUB_TOKEN` is not
introduced.

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
7. `publish_fallback_diff_review` restores `COVERAGE_BLOCKED` after the
   COMMENT review so `create_pull_review` cannot leave `Gate result: COMMENT`
   on a coverage miss;
8. the class diagram lists public items and does not invent
   `FirstType --> SecondType`; and
9. bounded Rust toolchain materialization copies manifests only, selects
   rustup 1.97 for OriginWeave-style workspaces, and rejects parent-directory
   members and symlinks.

## Limitations

A later rustup or llvm-tools catalog change can still fail the image build.
That failure remains a coverage-gate failure, not a synthesized product-file
finding. The sandbox does not weaken a genuine below-threshold coverage miss.

Publishing the fallback review uses `create_pull_review COMMENT`, which also
rewrites the issue comment to `Gate result: COMMENT`. The publisher must then
restore `COVERAGE_BLOCKED` on that status surface so a model-unavailable
coverage miss does not look like a completed comment-only review. The fallback
class diagram lists extracted public items and does not invent a relationship
between the first two names.

## References

GitHub, Inc. (n.d.). *REST API endpoints for pull request reviews*. GitHub
Docs. Retrieved August 16, 2026, from
https://docs.github.com/en/rest/pulls/reviews

International Organization for Standardization. (2023). *Systems and software
engineering — Systems and software Quality Requirements and Evaluation
(SQuaRE) — Product quality model* (ISO/IEC 25010:2023).
https://www.iso.org/standard/78176.html

National Institute of Standards and Technology. (2022). *Secure software
development framework (SSDF) version 1.1: Recommendations for mitigating the
risk of software vulnerabilities* (NIST Special Publication 800-218).
https://doi.org/10.6028/NIST.SP.800-218

Rust Project Developers. (n.d.). *The rustup book*. Retrieved August 16, 2026,
from https://rust-lang.github.io/rustup/

Taiki Endo. (2026). *cargo-llvm-cov* (Version 0.8.7) [Computer software].
https://github.com/taiki-e/cargo-llvm-cov
