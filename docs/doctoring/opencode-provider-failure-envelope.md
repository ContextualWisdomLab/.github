# OpenCode provider-failure envelope

## Problem and exact evidence

On 2026-09-12, `.github` PR
[`#2106`](https://github.com/ContextualWisdomLab/.github/pull/2106) at exact
head `24bb6591ab7df23558cb793b4af60c567ff9da97` reached the single required
`contextual-orchestrator/orchestrator/free` model route in OpenCode run
[`34693400612`](https://github.com/ContextualWisdomLab/.github/actions/runs/34693400612).
The request failed after the sidecar and route preflight had succeeded, but the
only surviving causal evidence was `class=provider-error`, two byte counts,
and a statement that provider content was suppressed. That was enough to keep
the review fail-closed, but not enough to distinguish queue admission, HTTP
429/5xx, request size, malformed JSON, route exhaustion, or missing serving
identity. Issue
[`#2112`](https://github.com/ContextualWisdomLab/.github/issues/2112) owns the
repair.

## Constraints

- OpenCode, Noema, and Strix keep the single `orchestrator/free` gateway route;
  no provider/model/group override or paid fallback is introduced.
- Telemetry is diagnostic only. It cannot produce approval, clean evidence, a
  retry, a timeout, or a merge bypass.
- Provider-controlled messages, bodies, prompts, credentials, headers, source
  text, and arbitrary nested payloads never reach stdout, status text, or
  annotations.
- Only exact allowlisted phase/reason enums and validated HTTP status numbers
  may enter causal output. Lexically valid but unproven identifiers are not
  evidence of non-secret provenance. Provider, model, and exception identities
  remain `unknown` until an immutable CO receipt/catalog proves them.

## Alternatives and decision

Keeping the previous byte-count-only line was rejected because it preserves
secrecy at the cost of causal attribution. Printing the raw OpenCode event or
gateway response was rejected because public `pull_request_target` logs cannot
safely carry provider-controlled text. Adding caller-side retries or an
elapsed-time diagnosis was rejected because the gateway owns routing and the
observed five-second failure did not prove a timeout.

The selected design adds a small standard-library parser at the OpenCode
adapter boundary. It reads at most the final 16 KiB of each failure artifact,
drops an incomplete leading line, and accepts only an OpenCode `type=error`
event within an explicit 64-level structural-depth limit. From the gateway response it parses
at most 16 KiB and reads only the canonical `error.detail`/`error_detail`
receipt and its last bounded attempt. Only allowlisted structured status/reason
pairs determine failure class; contradictory pairs become `provider-error`.
Phase is emitted only when it matches a fixed public enum. Provider, exception,
and served model remain `unknown` because this consumer has no immutable CO
catalog proof that can authenticate dynamic identities. Raw
event/stderr bytes are represented only by presence and byte counts, never
passed to the causal classifier. Oversized gateway bodies, deeply nested or
malformed JSON, and malformed Unicode fail closed to bounded metadata.

## Executable evidence, risks, and effects

The production launcher fixtures cover HTTP 429/queue capacity, provider 503,
non-JSON response bodies, HTTP 413 request admission, no eligible route, absent
served-model metadata, contradictory structured causes, raw prose pollution,
unproven identifier provenance, 16 KiB overflow, excessive JSON depth, and
secret-bearing ignored fields. Unit tests cover all parser statements and
branches, and the consolidated runtime-quality workflow selects this suite
whenever the launcher, parser, fixture, or this authority record changes.

The remaining risk is semantic drift and missing identity provenance in the
gateway receipt. Unknown fields are deliberately not guessed or copied; a
future immutable CO schema/catalog change must add a failing fixture before an
identity or enum enters the allowlist. Operators can now route a
429/queue failure to capacity policy, a 5xx to the gateway/provider boundary,
a 413 to request admission, and malformed JSON to the response adapter without
reading secret-bearing bodies. Until exact-head hosted checks, independent
review, protected-main integration, and an unchanged-head replay of #2106 are
complete, this repair remains Proposed rather than released evidence.
