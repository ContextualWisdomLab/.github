# External review gateway admission

Status: proposed, disabled by default, with no registered released adapter.
Baseline: protected `.github` main `dd0b96feded94f66ecf59b25a5a9b58cfc8b4f69`.

## Problem and scope

The existing review bootstrap always starts a loopback CO instance using provider
credentials. An inference-token-only external deployment cannot use that path.
The CO inference APIs already expose authenticated model discovery and chat;
administrator `/readyz` access is neither necessary nor appropriate.

CO PR #1084 proposes the consolidated request/evidence contract but is not a
released dependency. Its fixture, source and proposed branch are not imported
here. No production workflow opts into this change, and no provider request
or production credential is used in its tests.

## Chosen boundary

The existing composite action adds `gateway_mode`, default `sidecar`. Explicit
`external` branches before provider-secret bootstrap and admits only a protected
source-registered immutable contract adapter. The registry is empty, so every
real external invocation currently fails with `released_contract_unavailable`
before token access, network calls, checkout of CO, or readiness exports.
An environment value containing a full commit hash cannot authorize adoption.

The owner probe port describes inference `/v1/models` discovery and capability
checks through `/v1/chat/completions`. It requires the exact `orchestrator/free`
alias plus JSON object/schema and tool-call evidence; a failed or missing
capability prevents partial readiness. The port accepts only an explicit HTTPS
origin and an owned, mode-0600, regular token file. It never exports a raw bearer.
Successful test-double observations produce only bounded capability evidence.

TLS verification, redirect rejection, trusted origin authorization, secure token
opening and full response validation are obligations of the future released
adapter. They are not implemented HTTP transport in this delta. No claim of a
working external gateway or verified TLS follows from these port tests.

## Alternatives and next owner work

- An early return that exports a supplied URL/token path would silently bypass
  all capability and private-data policy checks; rejected.
- Copying CO #1084's fixture or provider discovery into `.github` would create an
  unreleased dependency or duplicate owner logic; rejected.
- A new gateway service is unnecessary: use CO's existing inference contract.

After CO publishes its reviewed immutable contract, a separate protected change
must implement/register the released adapter and verify live external HTTPS,
token-only authentication, exact free-pool capability, and sanitized failure
evidence. It must retain failure classification without paid fallback and must
not impose a model-duration timeout. No code may infer provider retention from
a successful response: ZDR evidence is configured policy only.

Every private review request must retain `zdr_only`, not just preflight. This
bootstrap exports that requirement for the future caller integration; it cannot
enforce it on an unrelated client's later HTTP requests. Strix's fixed-loopback
allowlist and Noema's private-origin exception need separate reviewed integration
before deployment. Default sidecar provisioning and those gates are unchanged.

## Verification

The baseline external-mode test failed because the legacy path demanded provider
secrets, and the port did not exist. Tests now exercise private-file/origin
admission, missing free inventory, each failed capability, unregistered revision,
safe output, and exceptions using owner test doubles. Synthetic data is confined
to unit tests. Full lifecycle evidence still requires protected review, release,
caller adoption, and a live exact-head review.
