# Strix ModelBehaviorError classifier

Observed required-check flake: Strix exits 1 with `ModelBehaviorError` and
`Vulnerabilities 0` after the scanner model fails to complete a turn.

The outer `strix.yml` backend-unavailable signal now includes
`ModelBehaviorError`. Neutral skip still requires the absence of
`Vulnerabilities [1-9]` and of a `severity:` finding. A scan that reports
any numbered vulnerability stays fail-closed even when the model also
emits `ModelBehaviorError`.

## Operator action

If this check repeats, inspect the exact Strix log for the qualified exception
and confirm that no numbered vulnerability or `severity:` signal is present;
any finding remains fail-closed before retrying.

## References

OpenAI. (n.d.). *Exceptions*. OpenAI Agents SDK. Retrieved August 19, 2026,
from https://openai.github.io/openai-agents-python/ref/exceptions/
