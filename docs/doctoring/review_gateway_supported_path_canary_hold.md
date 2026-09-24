# Review gateway supported-path canary: execution hold

Status: **Draft plan; do not dispatch.** Checked against `.github` `main`
`e6334e229581a918e2f22de18733b76fa65d7e71` on 2026-09-24. This
document adds no workflow trigger, credential, or provider call.

## Why the existing Noema run is not an A/B test

[`noema-review.yml`](../../.github/workflows/noema-review.yml) starts
[`contextual_orchestrator_review_sidecar.sh`](../../scripts/ci/contextual_orchestrator_review_sidecar.sh) and calls
its local `/v1/chat/completions` endpoint with `orchestrator/free`. The sidecar
defaults to CO `767e67fbc6b881a452761f32abb69b9971b9b03b`, requires at least
one real provider credential, and installs the checked-out `requirements.lock`.
Its [launcher](../../scripts/ci/contextual_orchestrator_review_launcher.py)
constructs `TaskOrchestrator` directly; it does not call the
`build_review_orchestrator` entry point used by the pending review-allocation
repair. A green Noema run therefore cannot prove that repair ran.

The workflow has `pull_request_target` and `repository_dispatch` triggers, not
`workflow_dispatch`. Adding a manual trigger to this secret-bearing required
workflow would widen its authority. Do not use a PR head, free-form ref, URL,
command, request body, or repository-dispatch payload to choose executable
code or provider inputs.

## Exact candidate comparison, pending route equivalence

| Role | CO commit | SHA-256 of `requirements.lock` |
| --- | --- | --- |
| Before the review-allocation change | `9504495c6c616a15c314c7a38218a73b143aa5e1` | `b6a74b19acec0d0e0c16a597a4d16a36a30503b58d5a16ceff0150bf58132518` |
| Stacked candidate through empty-batch repair | `89b7beafbde9a6952af1861e719e99daf97fa56d` | `b6a74b19acec0d0e0c16a597a4d16a36a30503b58d5a16ceff0150bf58132518` |

These commits share a lock digest, but that alone does not make their hosted
routes, discovered catalog, selected model, or provider behavior equivalent.
The currently supported sidecar default `767e67fb...` has a different lock
digest, `c80752a4c6bbbc1bc9b0cb2b938831693a88dfdca7d1130bb4c00e2f9fe21345`.
The bounded Noema run inspection found no candidate hosted run or comparable
request-level artifact.

## Small GitHub execution contract to review before enabling

1. Use a separate default-branch workflow with no caller-controlled executable
   inputs. Its only selectable builds are the two full CO commits above; verify
   each checkout and lock digest before startup. Run only trusted `.github`
   source. Require a protected canary environment with named reviewers; verify
   that protection exists before adding any secret-bearing trigger. Use the
   existing sidecar credential bootstrap only after that gate. No PR content,
   repository files, or research material may enter the request.
2. First make the launcher's review-allocation path equivalent to the candidate
   owner entry point, or show an exact-code proof that the supported launcher
   enables the same guard. A run using today's direct `TaskOrchestrator`
   construction does not test the proposed repair. Check that the same
   eligible catalog and selected concrete model are available for both pins;
   stop the comparison if either differs.
3. Use one fixed synthetic text request on local `/v1/chat/completions` with
   `model=orchestrator/free`, `max_tokens=16`, one caller, two warmups and ten
   measured calls per build. Bind an external hard ceiling on provider attempts
   and spend before any provider egress; workflow request counts and a
   zero-cost label alone are not a cost cap. If that ceiling cannot be enforced,
   keep the workflow disabled. A no-egress synthetic upstream can measure only
   gateway overhead, not real provider throughput.
4. Keep the bearer in the existing owner-only runner file. Upload only a
   sanitized artifact containing workflow/run ID, `.github` SHA, CO SHA, lock
   digest, runner class, catalog/selected-model identity, per-request elapsed
   milliseconds, HTTP status and typed error code, provider-attempt count, and
   a bounded cost receipt. Do not upload prompts, completions, headers,
   credentials, raw stderr, or provider error bodies. Count successes,
   rejections, transport failures, timeouts, and unknown outcomes separately.
   Compare p50/p95 and completed requests per second only for equivalent
   successful requests; a fast 503 is not serving capacity.

## Release condition

An independent security review must approve the manual-event authority,
protected environment, exact-source checkout, sanitizer, and enforceable cost
ceiling. Then a separate reviewed change may add the workflow. Until a hosted
pair satisfies the route and input equivalence checks above, supported-path
latency, error rate, and throughput improvement remain **unproven**. Do not
dispatch a canary or merge this plan as runtime authorization.
