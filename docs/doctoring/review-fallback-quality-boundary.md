# Review fallback quality boundary

## Observed failure

On 2026-09-08, the latest five Noema/OpenCode formal review objects found in the
20 newest open `.github` PRs were all fallback/status-derived OpenCode output.
There were 11 matching review objects in that bounded collection. The selected
five are not a representative sample of model quality or the organization.

| PR | Review ID | Reviewed commit | Matched head at collection |
| --- | --- | --- | --- |
| #2029 | 5136651994 | eb79481bc1696c63273b6c2ca22b5e34f68d0208 | No |
| #2021 | 5134455762 | 4dec9c6a2e03d2ff3e62b186a47fe99910cfcd63 | No |
| #2019 | 5134382662 | 100f1e1b0554b48ba2f843c965d414993cf5588f | Yes |
| #2020 | 5134381479 | 29d9d5ec6a02f5c23b315b70f8315a582dac5d1b | No |
| #2016 | 5134310293 | 5baffac6fdb754e6444c4dfad6a56e4af89d9fe7 | Yes |

All five described a gate limitation and contained Mermaid, but none supplied
a behavioral summary, a concrete file responsibility beyond its category, or
a hypothesis/counterexample/evidence chain. Their diagrams were generic file
inventories. These observations do not establish an outage cause.

The [#2029 review](https://github.com/ContextualWisdomLab/.github/pull/2029#pullrequestreview-5136651994)
claimed that OpenCode reviewed the product diff, then displayed two generated
file maps. `build_fallback_review` created the first map and completion claim;
`publish_fallback_diff_review` appended another completion claim, and the
common publisher appended its own map. File classification is not source review.

## Repair and measurement

Label the fallback as an inventory with a next action, remove its duplicate
diagram, and stop the caller from appending a completed-review claim. Public
symbols read from supplied files are identified as such, not as changed APIs.
The common publisher retains its evidence map and gate handling. No inference
result, approval, or finding is synthesized.

English/Korean regression baseline: 0/2 outputs correctly identify the fallback
limit on main `7fd571dbcdbae6acf29d8f4ee704d7ba6297e4db`. Reproduce with:

```sh
uv run --no-project .venv/bin/python -m pytest tests/test_opencode_review_surfaces.py tests/test_opencode_review_comment_helpers.py --cov=scripts.ci.opencode_review_surfaces --cov-report=term-missing --cov-fail-under=100 -q
```

After repair: 2/2 language cases pass; all 43 surface/helper tests pass with
100% statement and branch coverage of `opencode_review_surfaces`. Docstrings
also reach 100%. Actionlint passes with its optional ShellCheck/Pyflakes
integrations disabled; the full invocation was interrupted after remaining
silent for several minutes. It is not recorded as a full lint pass.

## Model availability dependency

[Noema run 34128415567](https://github.com/ContextualWisdomLab/.github/actions/runs/34128415567/job/101776606311)
failed after 1,976.2 seconds with one caller attempt and terminal HTTP 502.
Its [sidecar artifact](https://github.com/ContextualWisdomLab/.github/actions/runs/34128415567/artifacts/10025654264)
records `provider_connection_error`, 26 review-phase attempt log entries,
including 19 timeouts and three HTTP errors. Six routes passing preflight
did not establish success for the real review request.

The installed owner revision was `414f22973658c4ddc3d4320fcf7acd9b4e8ba991`,
also the consumer pin observed during this investigation.
[ContextualWisdomLab/contextual-orchestrator#1094](https://github.com/ContextualWisdomLab/contextual-orchestrator/pull/1094)
already contains a candidate for structured-response synthesizer failover on
retryable 502/429/timeout errors. At head
`1c61eff2da012382255bf8b4e1aa6dd0d6dd05ca`, it remains open with six nonterminal
checks, nine unresolved threads, and no exact-head formal review.
Triage that owner candidate before duplicating repair in a consumer. Its scope
matches the failure, but this historical log does not prove the fix works.
Adoption requires protected owner merge, immutable release, consumer contract
verification, and a real Noema replay. Do not add caller retries or paid routes.

This repair improves truthful publication, not model availability. A subsequent
real model review must still demonstrate behavioral explanation, source-bound
findings, counterexamples, verification limits, and useful next actions. Use the
[Greptile reference](https://github.com/BerriAI/litellm/pull/20421#issuecomment-3847832704)
for concrete behavior/flow explanations, not an unsupported numerical score.

## References

GitHub. (n.d.). *REST API endpoints for pull request reviews*. Retrieved
September 8, 2026, from https://docs.github.com/en/rest/pulls/reviews

Greptile. (2026, February 4). *Greptile overview* [Pull request comment]. GitHub.
https://github.com/BerriAI/litellm/pull/20421#issuecomment-3847832704
