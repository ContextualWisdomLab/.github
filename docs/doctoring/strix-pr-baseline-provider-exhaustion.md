# Strix PR baseline/provider-exhaustion incident

## Observed failure

LineageWeave PR 392 run `32530198775` reported a critical secret in the
nonexistent `frontend/src/config.ts`. The trusted changed-file mapper correctly
classified that report as unchanged, but later fallback attempts ended in
provider HTTP 410 retirement brownouts. The gate retained the earlier severity
rank and returned the same exit code used for changed-file findings, so the
outer workflow could not distinguish the cleared baseline report from a real
pull-request vulnerability.

A later central PR run reported zero vulnerabilities and then failed before
scanning when Strix's local Caido process did not accept connections on
`127.0.0.1:48080`; the outer workflow did not yet recognize that exact scanner
bootstrap outage as infrastructure.

Another observed run selected Azure `gpt-5.6-sol`, where LiteLLM forwarded
Strix's `temperature=0.2`. Azure rejected the unsupported sampling parameter
and LiteLLM had no fallback group for that model. Microsoft documents
`temperature` as unsupported for reasoning models (Microsoft, 2026), while the
documented Strix configuration surface has no generation-parameter control and
the missing capability remains an upstream request (AkikoOrenji, 2026;
usestrix, n.d.).

## Root cause and repair

The quick gate already owns the exact PR-head changed-file mapping decision.
After it has classified every report as `allow_baseline`, provider exhaustion
now returns the dedicated status 3, including a deployment with no distinct
fallback configured. The trusted reusable workflow maps only that status to a
neutral infrastructure warning. Changed, unmapped, or manifest findings still
return the blocking status, and configuration or unexpected statuses still
fail closed.

The outer workflow also recognizes only the observed `loginAsGuest` retry
exhaustion with curl exit 7 against Strix's fixed local Caido port. It is neutral
only when no positive vulnerability or severity signal exists; every other
runtime failure remains blocking.

The preferred request-boundary repair is to omit a sampling parameter a caller
did not explicitly provide. The pinned Strix integration cannot currently do
that through its documented configuration, so the quick gate recognizes only a
single log line containing the complete LiteLLM/Azure unsupported-temperature
failure and the missing internal model group. It skips deterministic same-model
retry and moves to the existing distinct outer fallback. Split-line signal
assembly stays non-retryable, and provider exhaustion becomes neutral only
after the existing trusted PR-scope mapper has classified every report as
`allow_baseline`.

## Verification

- A three-attempt regression reproduces an unchanged critical report followed
  by two provider failures and requires status 3.
- A primary-only regression requires the same trusted baseline outcome without
  treating the absent fallback as a pull-request finding.
- Existing source tests require changed findings to remain blocking and clean
  unchanged findings to remain admissible.
- A workflow regression requires the exact Caido bootstrap outage to be neutral
  with zero findings and blocking when any vulnerability is reported.
- An Azure capability regression requires the exact unsupported-temperature
  line to reach the configured GitHub Models fallback without a same-model
  retry; a split-line imitation must remain non-recoverable.
- The central Python suite, native workflow validation, Bash syntax checks, and
  the complete Strix shell regression suite run on the final tree.

## References

AkikoOrenji. (2026, June 4). *[Feature] Expose LLM generation parameters to
control local/OpenAI-compatible model behaviour and prevent runaway tool-call
loops* (Issue No. 514) [GitHub issue]. GitHub.
https://github.com/usestrix/strix/issues/514

Microsoft. (2026, August 20). *Azure OpenAI reasoning models—GPT-5 series,
o3-mini, o1, o1-mini*. Microsoft Learn.
https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/reasoning

usestrix. (n.d.). *Configuration* [Computer software documentation]. GitHub.
Retrieved August 22, 2026, from
https://github.com/usestrix/strix/blob/main/docs/advanced/configuration.mdx
