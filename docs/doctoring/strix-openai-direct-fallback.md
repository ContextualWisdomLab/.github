# Strix openai-direct fallback: evidence and design record

## Decision

The central Strix workflow advertises `openai-direct/gpt-5.6-luna` as the
cross-provider fallback after NVIDIA NIM catalog misses. LiteLLM does not
recognize the hyphenated `openai-direct/` provider prefix. The gate rewrites
that alias to `openai_direct/` and dispatches it as LiteLLM `openai/`, clears a
non-OpenAI primary API base, and authenticates with the established
`STRIX_OPENAI_API_KEY` / `OPENAI_API_KEY` secret through a trusted runtime
file.

## Trust boundary

- `normalize_model` rewrites only `openai-direct/?*` to `openai_direct/`.
- `run_strix_once` normalizes the candidate before `child_model_for_api_base`.
- Cross-provider `openai_direct/*` attempts do not inherit NVIDIA, OpenRouter,
  or GitHub Models API bases.
- A missing `STRIX_OPENAI_FALLBACK_KEY_FILE` during a cross-provider fallback
  is configuration exit 2. The notice-only workflow step that skips writing
  the file when the secret is empty does not weaken that gate.
- Incomplete scans, exhausted fallbacks, and reported vulnerabilities remain
  fail-closed. This change does not ignore findings or skip the scanner.

## Observed incident

ScopeWeave #589 job 97204514255 (run 32643656525) on
`dce2424b45833fa6a942fae1edb5d16f0d687bdb` produced an empty SARIF and a
penetration report with no product findings. The last attempt log recorded
`model=openai-direct/gpt-5.6-luna` and `litellm.BadRequestError: LLM Provider
NOT provided`. That is infrastructure failure, not a Stripe HMAC finding.

## Verification

- `python3 -m unittest tests.test_strix_nvidia_nim_not_found_fallback`
- `bash scripts/ci/test_strix_quick_gate.sh` (normalize_model alias + workflow
  contract for `STRIX_OPENAI_FALLBACK_KEY_FILE`)
