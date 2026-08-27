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
and exited before the model pool could review the diff. Coverage-evidence
failure became the review. The mermaid helper bucketed unknown paths,
including `crates/`, as a generic `Changed file (N files)` inventory and
findings were anchored to `.github/workflows/opencode-review.yml:1` even
when that file was not in the pull-request diff.

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
4. Coverage-evidence failure is injected into `bounded-review-evidence.md` as
   a `## Coverage gate` section. The model pool still runs. The publisher
   does not early-return before the model path. `format_request_changes_body`
   keeps model walkthrough/diagrams and appends structured findings.

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
7. `publish_fallback_diff_review` restores `COVERAGE_BLOCKED` on the status
   comment after the COMMENT product-file review, so a coverage miss never
   looks finished as `Gate result: COMMENT`; and
8. mermaid class diagrams list extracted public Rust API names only and do
   not invent a `FirstType --> SecondType` class edge.

## Limitations

A later coverage-image or tooling catalog change can still fail the isolated
coverage job. That failure remains a coverage-gate failure, not a synthesized
product-file finding. The sandbox does not weaken a genuine below-threshold
coverage miss.

## References

GitHub, Inc. (2026). *REST API endpoints for pull request reviews*. GitHub
Docs.
https://docs.github.com/en/rest/pulls/reviews
