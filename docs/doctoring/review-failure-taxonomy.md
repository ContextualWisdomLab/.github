# Review failure taxonomy: gateway routing, scanner tooling, dispatch admission

On 2026-09-21 the central review pipeline looked like a provider outage. It was not.
Three unrelated failures were being read as one.

## What the hosted evidence showed

Every run reached the vendored contextual-orchestrator sidecar and every run reported
`provider secrets present: 5 of 5`, including runs that predate any credential change.
The gateway answered its own preflight with `status: ready` and `finish_reason: stop`.
Provider credentials were never the blocker.

## 1. OpenCode: gateway routing, reported as `Error: not found`

The sidecar exports `CONTEXTUAL_ORCHESTRATOR_BASE_URL` as a bare `scheme://host:port`.
Noema and Strix append `/v1/chat/completions` themselves. OpenCode's
`@ai-sdk/openai-compatible` provider appends only `/chat/completions`, so it posted to an
unprefixed path. The gateway serves `/v1/chat/completions` and answers anything else with
`route_not_found`, whose message is the bare string `not found` — which OpenCode printed
verbatim as `Error: not found`, half a second after its banner had already resolved the
agent and model.

Reproduced locally against a stub gateway with the installed OpenCode CLI: an unprefixed
`baseURL` produced `POST /chat/completions`, and `{env:CONTEXTUAL_ORCHESTRATOR_BASE_URL}/v1`
produced `POST /v1/chat/completions`. The `/v1` belongs in the OpenCode provider options,
never in the sidecar export — moving it there would double-prefix Noema and Strix.

The banner is the tell: once `> <agent> · <model>` has printed, agent and model already
resolved, so a later `not found` is a transport answer, not configuration lookup.

## 2. Strix: scanner tooling, previously folded into the provider verdict

A failing scan emitted Caido GraphQL errors (`Invalid HTTPQL query`, `Failed to parse
cursor`, `TransportQueryError`) while the gateway was healthy. Genuine provider rate
limits appeared in the same log, so the single `STRIX_PROVIDER_UNAVAILABLE` notice was not
wrong — it was incomplete, and it hid a scanner defect behind an infrastructure label.
`strix.yml` now emits `STRIX_TOOLING_ERROR` on its own whenever a tooling signature
appears. Both notices can appear together. Neither changes the exit code: an incomplete
scan stays non-passing.

## 3. Dispatch admission: never a gateway outcome

`repository_dispatch authorization rejected` and `repository_dispatch metadata does not
match the live pull request` fire before the sidecar is provisioned. Counting them as
review-pipeline outages inflates the apparent provider failure rate.

## Rule

Attribute a review failure to the provider only after the gateway request itself failed.
Name the gateway's served path, the scanner's own errors, and admission gates as separate
classes. `tests/test_review_failure_taxonomy_contract.py` pins all three.
