# Strix tool-protocol fallback

## Incident and buyer impact

Strix can exit before producing security evidence when the selected model
emits a tool call the `strix` agent does not expose:

`agents.exceptions.ModelBehaviorError: Tool execute not found in agent strix`

The required check then failed as if the target repository were insecure,
and configured fallback models never ran.

## Decision

Classify only that exact exception class, missing-tool phrase, and agent
name `strix` as retryable infrastructure. Fallback to a distinct configured
model. Vulnerability artifacts and fallback exhaustion remain fail-closed.
Generic application errors are not matched.

## References

National Institute of Standards and Technology. (2020). *Security and
privacy controls for information systems and organizations* (NIST Special
Publication 800-53 Rev. 5). https://doi.org/10.6028/NIST.SP.800-53r5

OpenAI. (2025). *OpenAI Agents SDK*.
https://openai.github.io/openai-agents-python/
