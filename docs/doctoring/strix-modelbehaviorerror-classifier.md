# Strix ModelBehaviorError classifier

## Decision

A pydantic-ai or LiteLLM `ModelBehaviorError` with `Vulnerabilities 0`
is provider-model flake, not a target-application finding. The central
Strix workflow classifies that exact SDK exception as backend
unavailability and may skip the required check as neutral.

`Vulnerabilities [1-9]` stays fail-closed. A source-file mention of
`ModelBehaviorError` without the trusted `pydantic_ai.exceptions` or
`litellm` exception prefix is not infrastructure.

## Trust boundary

The classifier accepts only one bounded log line that names the trusted
SDK exception. Cross-line assembly from repository text is rejected.
This matches the NVIDIA NIM same-line rule
(`docs/doctoring/strix-nvidia-nim-not-found-fallback.md`).

## Verification contract

1. `pydantic_ai.exceptions.ModelBehaviorError` plus `Vulnerabilities 0`
   is neutralized.
2. The same exception plus `Vulnerabilities 1` remains blocking.
3. A source literal `ModelBehaviorError` without the SDK prefix is not
   classified.
4. `reported_vulnerability_signal` still matches `Vulnerabilities [1-9]`.

## References

Pydantic. (2026). *pydantic-ai exceptions* [Software documentation].
https://ai.pydantic.dev/api/exceptions/
