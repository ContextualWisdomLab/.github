# Psychometrics Commons central Runtime CI candidate

## Scope and source

The reusable `psychometrics-commons-ci.yml` preserves the three Runtime CI
checks from `ContextualWisdomLab/psychometrics-commons` PR #165 head
`bb9028714d996871ed2588ea9a3aa83fd581af84`. Its commands/image/tool versions
also match product main `e81441ce70c676992470afe2be469dd891ad3eb5`; their
trigger/concurrency differences remain caller-owned. The unavailable temporary
product checkout was replaced by immutable GitHub source reads, not an assumed
local snapshot.

The workflow exposes only `workflow_call`, without executable inputs or
inherited secrets. Every job admits only an open, non-Draft, same-repository
PR targeting `main` in the fixed `ContextualWisdomLab/psychometrics-commons`
repository before runner allocation. The first step then validates event
identity, positive PR number, exact merge ref, and canonical head before
checkout. Checkout uses the supplied PR head only and verifies actual HEAD;
there is no fallback to an event SHA.

## Execution and unchanged gates

All jobs select `CWL CI isolated` with `self-hosted`, `linux`, `x64`, and
`cwlab-ci-isolated`. No shared control/review runner or hosted fallback exists.
Rust 1.97.1, nightly-2026-08-18, cargo-llvm-cov 0.8.6 and the product's exact
PostgreSQL 18 image digest are unchanged. Stable commands explicitly use the
pinned toolchain. Formatting, all-target compile/test/Clippy, committed lock,
Python coverage contracts, warning-free rustdoc, complete production line and
branch coverage, and failure diagnostics remain required.

Each job has its own GitHub-managed PostgreSQL service/network and ephemeral
test password. Docker allocates a random host port; connection setup consumes
that service's reported port instead of binding shared host port 5432. Service
cleanup belongs to the job lifecycle, not recursive deletion of runner storage.

## Admission and evidence limits

This is a source candidate, not runtime-ready evidence. Central main
`58d12a9f1b46d611f75cfcf3e6c5a3fe19a55f96` defines the isolated group contract,
but labels and YAML do not prove disposable guest isolation or safe execution.
The parent previously observed that group 13 did not admit psychometrics.
An authorized operator must verify consumer access, disposable job isolation,
Docker/service capabilities, clean teardown, pinned tool availability and
actual exact-head runs. Do not relabel privileged runners to release queued
jobs. No grants, registrations, restarts, secret changes, dispatch, remote
push, merge or product caller edits were performed for this candidate.

Only PR events are admitted in this slice. Main pushes and manual callers are
not silently interpreted as PR validation; they would need a separately
verified admission contract. Job skips are not quality success. Preserve all
three exact check names when a thin consumer caller is later pinned to an
integrated immutable central commit, and keep consumer concurrency there.

## Local verification

The focused tests parse the actual workflow, verify job-level admission and
exact checkout, execute the defensive shell with allowed and rejected synthetic
metadata, and bind toolchain/image/coverage threshold commands. Actionlint and
whitespace checks validate the candidate. These tests do not execute product
Rust tests, PostgreSQL services, GitHub runners or formal App review.
