# Noema counterexample publication

## Problem and scope

The review-quality reference is the Greptile overview on
[BerriAI/litellm#20421](https://github.com/BerriAI/litellm/pull/20421#issuecomment-3847832704).
Its useful property is an explanation tied to observable behavior and security
boundaries. A confidence score or diagram alone does not establish correctness.

At baseline `7fd571dbcdbae6acf29d8f4ee704d7ba6297e4db`, Noema's schema and
`validate_substantive_verdict` require `attack_or_counterexample`, but
`format_review_evidence` drops it before `submit_review` constructs the GitHub
review body. Readers see a hypothesis and conclusion without the supplied
scenario used to challenge it.

## Repair and experiment

Preserve the supplied counterexample under its existing probe. Do not generate
a replacement scenario, infer execution from prose, or alter the verdict,
reviewed commit, evidence validation, or credential boundary. Older renderer
inputs without a counterexample retain their existing output.

The publication regression intercepts only the network boundary and checks the
actual serialized review body for APPROVE, REQUEST_CHANGES, and COMMENT. The
counterexample-preservation baseline is **0/3** (all three fail on the missing
scenario).
The implementation experiment `4472deb0` preserves **3/3** scenarios; the Noema
gate and handoff suites passed **157** tests. Run from the repository's
project-local environment:

```sh
uv run --no-project .venv/bin/python -m pytest tests/test_noema_review_gate.py -q -k submit_review_preserves_counterexample
```

This is a unit-level publication metric, not an estimate of model correctness,
organization-wide review quality, or proof of a deployed bot review. The fixture
is synthetic and is never posted as an actual review. Exact-head GitHub Checks,
independent review, protected merge, and a real subsequent bot review remain
separate verification steps. Project #1 could not be read on 2026-09-08 because
the current CLI token lacks `read:project`; no Project status was inferred.

## Remaining quality work

Measure representative live bot output against changed behavior, source-bound
findings, counterexample/evidence preservation, verification limits, and useful
next actions. Keep denominators explicit. Existing first-20 display limits and
the omission of aggregate validation status require separate assessment; this
repair does not claim to solve them. Existing OpenCode prose/diagram preservation
should be reused instead of introducing a second report generator.

## References

GitHub. (n.d.). *REST API endpoints for pull request reviews*. Retrieved
September 8, 2026, from https://docs.github.com/en/rest/pulls/reviews

Greptile. (2026, February 4). *Greptile overview* [Pull request comment]. GitHub.
https://github.com/BerriAI/litellm/pull/20421#issuecomment-3847832704
