# Strix ModelBehaviorError classifier

Observed required-check flake: Strix exits 1 with `ModelBehaviorError` and
`Vulnerabilities 0` after the scanner model fails to complete a turn.

The outer `strix.yml` backend-unavailable signal includes
`ModelBehaviorError` so operators receive a typed
`STRIX_PROVIDER_UNAVAILABLE` result when no vulnerability finding was emitted.
The workflow preserves the scanner's nonzero result: an incomplete provider
turn is never passing security evidence. A scan that reports any numbered
vulnerability also stays fail-closed.

When a provider failure is recorded only in Strix's structured report log,
the quick gate recognizes explicit rate-limit or provider-availability markers
and tries the configured distinct fallback models. It evaluates the newest
attempt report independently so an earlier failed provider cannot poison a
complete later report. Generic `Warning`, `Fatal`, or `Denied` output without
an explicit provider-availability marker remains non-retryable and fail-closed.

## Operator action

If this check repeats, inspect the exact Strix log and artifact for the
qualified exception. Retry provider execution without changing source
classification; both incomplete analysis and any reported finding remain
non-passing.

## References

OpenAI. (n.d.). *Exceptions*. OpenAI Agents SDK. Retrieved August 19, 2026,
from https://openai.github.io/openai-agents-python/ref/exceptions/
