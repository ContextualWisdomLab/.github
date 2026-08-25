# Strix direct-OpenAI fallback API-base routing: evidence and design record

## Decision

A Strix cross-provider fallback to an explicit direct-OpenAI model
(`openai-direct/...` or `openai_direct/...`) must route through the OpenAI
inference endpoint, never through the primary provider's `LLM_API_BASE`. The
gate now prefers an explicit `STRIX_OPENAI_FALLBACK_API_BASE_FILE` for such
models and, when the override is absent, resolves no API-base override so
litellm uses its default `https://api.openai.com/v1` endpoint.

The central workflow writes `https://api.openai.com/v1` into
`$RUNNER_TEMP/openai_fallback_api_base.txt` and exports
`STRIX_OPENAI_FALLBACK_API_BASE_FILE` whenever it publishes the OpenAI
fallback key file, so every provider chain that ends in
`openai-direct/gpt-5.4` (NVIDIA NIM primary, OpenRouter primary,
GitHub Models primary) inherits correct routing automatically.

## Failure this fixes

Required-CI evidence (BandScope PR #1021 strix run 32800796577, 2026-08-25)
showed the NVIDIA NIM primary and first fallback exhausting provider
availability, then the contracted final fallback `openai-direct/gpt-5.4`
failing with a plain-text gateway error:

```
LLM CONNECTION FAILED
Could not establish connection to the language model.
Error: 404 page not found
```

Root cause: with `provider_mode=nvidia_nim`, the workflow sets
`LLM_API_BASE_FILE=https://integrate.api.nvidia.com/v1`. The gate reused that
base for the openai-direct fallback child, so litellm sent OpenAI requests to
the NVIDIA NIM edge, whose Go gateway answered `404 page not found`. The
fallback key was already routed correctly (`STRIX_OPENAI_FALLBACK_KEY_FILE`);
only the base URL leaked from the primary provider. Because no vulnerability
report artifact was produced, the gate failed closed — correct policy on an
incomplete scan, but caused by routing rather than by any repository finding.

## Trust boundary

The override is a runner-provisioned regular file under `$RUNNER_TEMP`,
resolved through the same `resolve_trusted_input_file` boundary as the other
API-base files: it must be a regular non-symlink file inside the trusted input
root, must trim to a single `https://` URL, and must not contain whitespace or
control characters. Absent or empty overrides fall back to litellm's default
endpoint instead of failing configuration, preserving standalone local gate
runs where no workflow provisioning exists.

## Verification contract

Regression evidence proves that:

1. with a NVIDIA NIM primary base configured, `openai-direct/gpt-5.4`
   resolves through the explicit OpenAI fallback base when provided;
2. without an override, the resolver returns no base so litellm defaults to
   `https://api.openai.com/v1`;
3. NVIDIA NIM primary attempts keep resolving through the NIM edge;
4. `github_models/*` fallbacks keep their dedicated GitHub Models endpoint;
5. a non-https override fails configuration (exit 2) instead of scanning;
6. the workflow provisions the override file and passes it into the gate env;
7. the required-workflow smoke contract pins both sides of the wiring; and
8. the stale `gpt-5.6-luna` expectations left behind by the model rename are
   aligned with the valid `gpt-5.4` contract in queue-contract tests.

## Limitations

This change restores reachability of the final fallback; it does not create
OpenAI quota. If the OpenAI key is absent or exhausted after NIM exhaustion,
the gate still fails closed as provider-unavailable — by design, because no
complete authoritative scan exists. Hosted model catalogs may also change
independently of this repository; model-name updates remain manual contract
changes reviewed through CI.
