# Strix unsupported sampling-parameter fallback

## Observed failure

An Azure `gpt-5.6-sol` Strix run failed before vulnerability analysis because
LiteLLM sent `temperature=0.2`. Azure accepts only the model default of `1`,
and LiteLLM had no fallback group for the selected model. Microsoft documents
`temperature` as unsupported for GPT-5 reasoning models (Microsoft, 2026),
while the pinned Strix configuration surface exposes no generation-parameter
control (usestrix, n.d.).

## Root cause and repair

The preferred request-boundary repair is to omit a sampling parameter that a
caller did not explicitly provide. [ContextualWisdomLab/contextual-orchestrator](https://github.com/ContextualWisdomLab/contextual-orchestrator)
owns that provider
boundary for organization software. The pinned Strix integration cannot yet
express the omission through its documented configuration, so the trusted
quick gate recognizes only one physical error line containing all of these
signals:

- a LiteLLM `BadRequestError`;
- Azure or OpenAI exception context;
- the unsupported `temperature` value and supported default; and
- the missing LiteLLM fallback model group.

That exact capability failure is infrastructure evidence and may move directly
to an already-configured distinct outer fallback. It is not eligible for a
same-model retry. A direct-OpenAI primary has no second approved direct model
configured, so its bounded same-model retries are followed by a fail-closed
result rather than a duplicate fallback entry. The shared model normalizer translates the workflow's
accepted `openai-direct/` alias to the canonical `openai_direct/` selector;
the LiteLLM child dispatch then uses its provider-compatible `openai/` form. A
cross-provider direct OpenAI fallback reads the established OpenAI secret and
the explicit `https://api.openai.com/v1` endpoint from trusted runtime files;
otherwise a NVIDIA or OpenRouter run could send the fallback to the wrong
endpoint with the wrong credential. If either input is unavailable, the
attempted fallback fails configuration closed.
If no distinct fallback exists or every fallback fails, the required Strix
check remains non-passing. Existing changed, unmapped, manifest,
`ModelBehaviorError`, and vulnerability-report boundaries remain fail closed.

Cross-line signal assembly is deliberately rejected so unrelated target output
cannot manufacture a provider capability error from separate log lines.

## Verification

- The reproduced single-line Azure failure reaches the configured distinct
  outer fallback exactly once and succeeds only when that scan completes.
- A direct-OpenAI primary does not attempt its normalized primary model again
  as a fallback after bounded same-model retries.
- The configured `openai-direct/gpt-5.6-luna` alias normalizes to the canonical
  `openai_direct/gpt-5.6-luna` selector, then dispatches through LiteLLM as
  `openai/gpt-5.6-luna`.
- A NVIDIA-primary run dispatches that fallback with the OpenAI credential and
  the explicit OpenAI API base, with no inherited NVIDIA API base.
- A split-line imitation is non-recoverable and never dispatches the fallback.
- The full Python suite, native workflow validation, Bash syntax checks, and
  complete Strix shell regression suite run on the final tree.

## References

AkikoOrenji. (2026, June 4). *[Feature] Expose LLM generation parameters to
control local/OpenAI-compatible model behaviour and prevent runaway tool-call
loops* (Issue No. 514) [GitHub issue]. GitHub.
https://github.com/usestrix/strix/issues/514

Microsoft. (2026, August 20). *Azure OpenAI reasoning models—GPT-5 series,
o3-mini, o1, o1-mini*. Microsoft Learn.
https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/reasoning

usestrix. (n.d.). *Configuration* [Computer software documentation]. GitHub.
Retrieved August 23, 2026, from
https://github.com/usestrix/strix/blob/main/docs/advanced/configuration.mdx
