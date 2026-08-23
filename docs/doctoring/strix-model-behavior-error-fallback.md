# Strix ModelBehaviorError classifier: evidence and design record

## Decision

Strix treats a trusted LiteLLM or OpenAI Agents SDK `ModelBehaviorError` as
provider/runtime abort evidence, not as a target-application vulnerability.
When the scan log also contains no `Vulnerabilities [1-9]` signal, the
required check may classify the run as a neutral skip so a malformed tool
call cannot block an otherwise empty scan.

This classifier exists because LineageWeave PR #74 job 95148793283 printed
`Vulnerabilities 0` and then failed closed on `ModelBehaviorError`. That
abort is an agents-SDK reaction to an invalid tool call, not a finding.

## Trust boundary

The classifier accepts only a single bounded log line that contains both:

1. a trusted SDK/provider marker (`litellm.exceptions.<Name>Error` or
   `agents.exceptions.ModelBehaviorError`); and
2. the `ModelBehaviorError` exception name.

It does not assemble those signals from different lines. A source literal
that merely mentions `ModelBehaviorError`, an application traceback without
the SDK marker, or any `Vulnerabilities [1-9]` / `severity:` finding remains
blocking. Real findings are never downgraded.

The gate also routes the same classifier into infrastructure detection,
cross-model fallback, and same-model retry. A catalog 404 is not retried on
the same model; a `ModelBehaviorError` may be, because the next sample from
the same model can emit a valid tool call.

## Verification contract

Regression evidence proves that:

1. the agents-SDK abort observed in required CI is recognized;
2. a LiteLLM-wrapped `APIError: ModelBehaviorError` is recognized;
3. a source literal without the SDK marker is not recognized;
4. provider context and `ModelBehaviorError` on different lines are not
   recognized;
5. `Vulnerabilities [1-9]` prevents neutralization;
6. the classifier is wired into infrastructure, retry, and same-model retry;
   and
7. the required-workflow smoke contract pins the workflow and gate strings.

## Limitations

This change does not treat arbitrary model errors as success. It does not
weaken Strix severity, changed-file attribution, incomplete-scan fail-closed
behavior, or independent approval requirements. NVIDIA NIM catalog 404s stay
on their own same-line classifier.

## References

Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC
9110). Internet Engineering Task Force. https://doi.org/10.17487/RFC9110

OpenAI. (2026). *Agents SDK exceptions*. OpenAI Agents SDK.
https://openai.github.io/openai-agents-python/ref/exceptions/
