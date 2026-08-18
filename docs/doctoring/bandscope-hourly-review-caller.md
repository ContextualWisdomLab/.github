# BandScope hourly review-repair caller

## Status

Accepted on 2026-08-18 as the product-specific heartbeat for
`ContextualWisdomLab/bandscope`. The music repository remains the sole writer of
its application, audio-analysis, Rust, Storybook, and Figma-owned product code;
central `.github` owns only the reusable queue, credential, and dispatch control
plane.

## Buyer problem

BandScope has a dependency-root and several stacked buyer-visible rehearsal
slices. Repository checks, independent review, and central evidence can complete
at different times. Without a bounded heartbeat, actionable current-head review
findings may remain idle even though another exact-head repair can be performed
without crossing product ownership boundaries.

## Decision

The caller runs at minute 53 of every hour and invokes the sealed central
`pr-review-fix-scheduler.yml` with protected base `develop`. Minute 53 avoids the
established product-specific heartbeat minutes already present on protected
central `main`. Each heartbeat scans at most 50 open pull requests and dispatches
at most one writer. The two-hour same-head retry floor prevents a later heartbeat
from duplicating a legitimate OpenCode, Strix, Noema, browser, Rust, or
NVIDIA-backed investigation. The non-cancelling concurrency contract preserves
root-cause analysis already in progress.

A writer may edit only after it establishes the first causal boundary, compares
bounded remediation candidates, proves remediation feasibility, verifies writer
and dependency ownership, and defines a RED-to-GREEN test. Review latency or a
queued workflow is not itself a reason to stop scanning other eligible work.

## Music-science merge boundary

Automation must not convert synthetic success into a product-quality claim.
Every music-information-retrieval or rehearsal-analysis change requires the
metric appropriate to the feature and a real-audio acceptance fixture whose
expected musical result is independently specified. Examples include annotated
beat or onset timing, known chord progression, stem alignment, score-to-audio
correspondence, role range, and section-boundary expectations. Synthetic fixtures
remain useful for edge cases, but they do not replace authorized or openly
licensed recordings and annotation provenance.

Rust-owned production arithmetic remains in Rust when BandScope assigns an
algorithm or decoder to that layer. Python, TypeScript, browser, and UI code may
orchestrate, validate, visualize, and compare results, but an automated repair
must not silently move owned numerical work into a convenience layer. Changes
must retain CPU/GPU or native/portable parity where the owning product contract
requires it, complete production statement and branch coverage, public docstring
coverage, and realistic regression evidence.

## Credential and approval boundary

The caller itself has read-only contents permission. It forwards only the
established `PR_REVIEW_MERGE_TOKEN` and `OPENCODE_APPROVE_TOKEN` scheduler
credentials and never uses `secrets: inherit`. It does not receive
`NVIDIA_NIM_API_KEY`; that model credential remains sealed inside the central
OpenCode execution step. `COPILOT_GITHUB_TOKEN` is forbidden. Existing reviewer
credential and model-pool contracts are not changed by this caller.

A repair does not authorize approval or merge. The exact unchanged head still
requires terminal required checks, zero valid unresolved findings, qualifying
independent non-author approval, and ordinary branch-protection acceptance.
Agents must not self-approve, synthesize status evidence, weaken rulesets, or
force-cancel a legitimate long-running analysis.

## Standalone and ecosystem operation

BandScope must remain usable as a standalone desktop/web product. Ecosystem
connections to naruon, contextual-orchestrator, Semantic Data Portal, billing,
or other CWL products use versioned package/API/event contracts. The hourly
caller may repair BandScope-owned adapters, but it may not write a dedicated
sibling repository or copy sibling internals into BandScope.

## Verification and rollback

The caller, this doctoring record, and their contract test are tracked by the
permanent hourly NVIDIA NIM quality workflow. Verification requires the focused
contract suite, compile checks, complete owned coverage/docstrings, and
exact-current-head protected checks. Rollback removes the product caller and its
focused tracking together; it must not leave a timer that points at a renamed or
unverified reusable workflow.

## APA 7th references

Bittner, R. M., Fuentes, M., Rubinstein, D., Jansson, A., Choi, K., & Kell, T.
(2019). mirdata: Software for reproducible usage of datasets. In *Proceedings of
the 20th International Society for Music Information Retrieval Conference* (pp.
99–106). International Society for Music Information Retrieval.

Raffel, C., McFee, B., Humphrey, E. J., Salamon, J., Nieto, O., Liang, D., Ellis,
D. P. W., & Raffel, C. C. (2014). mir_eval: A transparent implementation of
common MIR metrics. In *Proceedings of the 15th International Society for Music
Information Retrieval Conference* (pp. 367–372). International Society for
Music Information Retrieval.

GitHub. (2026). *Security hardening for GitHub Actions*. GitHub Docs.
https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions
