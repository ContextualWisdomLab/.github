#!/usr/bin/env bash
# Execute one OpenCode command with provider-scoped credentials only.
set -euo pipefail

if [ "$#" -lt 1 ]; then
  printf 'Usage: %s <opencode arguments...>\n' "${0##*/}" >&2
  exit 64
fi

real_opencode="${OPENCODE_REAL_BIN:-}"
if [ -z "$real_opencode" ] || [ ! -x "$real_opencode" ]; then
  printf 'OPENCODE_REAL_BIN must name the executable captured before guard activation.\n' >&2
  exit 69
fi

model_candidate=""
model_argument_count=0
expect_model_value=0
option_parsing=1
for argument in "$@"; do
  if [ "$expect_model_value" -eq 1 ]; then
    case "$argument" in
      --)
        printf '%s\n' '--model/-m requires a model candidate.' >&2
        exit 64
        ;;
      --model | -m | --model=* | -m=*)
        printf 'exactly one model selector is allowed.\n' >&2
        exit 64
        ;;
      *)
        model_candidate="$argument"
        expect_model_value=0
        ;;
    esac
    continue
  fi
  if [ "$option_parsing" -eq 0 ]; then
    continue
  fi
  case "$argument" in
    --)
      option_parsing=0
      ;;
    --model | -m)
      model_argument_count=$((model_argument_count + 1))
      expect_model_value=1
      ;;
    --model=*)
      model_argument_count=$((model_argument_count + 1))
      model_candidate="${argument#--model=}"
      ;;
    -m=*)
      model_argument_count=$((model_argument_count + 1))
      model_candidate="${argument#-m=}"
      ;;
  esac
  if [ "$model_argument_count" -gt 1 ]; then
    printf 'exactly one model selector is allowed.\n' >&2
    exit 64
  fi
done
if [ "$expect_model_value" -eq 1 ] ||
  { [ "$model_argument_count" -gt 0 ] && [ -z "$model_candidate" ]; }; then
  printf '%s\n' '--model/-m requires a model candidate.' >&2
  exit 64
fi

# GitHub and Actions credentials are never needed by a read-only model process.
environment=(
  env
  -u GH_TOKEN
  -u GITHUB_TOKEN
  -u OPENCODE_APP_TOKEN
  -u ACTIONS_ID_TOKEN_REQUEST_TOKEN
  -u ACTIONS_ID_TOKEN_REQUEST_URL
  -u ACTIONS_RUNTIME_TOKEN
  -u ACTIONS_CACHE_URL
  -u ACTIONS_RESULTS_URL
  -u ACTIONS_RUNTIME_URL
)

# Start with no provider credential, then keep only the selected provider's key.
case "$model_candidate" in
  nvidia-nim/*)
    environment+=(
      -u STRIX_GITHUB_MODELS_TOKEN
      -u OPENCODE_API_KEY
      -u OPENAI_API_KEY
      -u OPENROUTER_API_KEY
    )
    ;;
  opencode/*)
    environment+=(
      -u STRIX_GITHUB_MODELS_TOKEN
      -u OPENAI_API_KEY
      -u OPENROUTER_API_KEY
      -u NVIDIA_API_KEY
      -u NVIDIA_NIM_API_KEY
    )
    ;;
  openai/*)
    environment+=(
      -u STRIX_GITHUB_MODELS_TOKEN
      -u OPENCODE_API_KEY
      -u OPENROUTER_API_KEY
      -u NVIDIA_API_KEY
      -u NVIDIA_NIM_API_KEY
    )
    ;;
  openrouter/*)
    environment+=(
      -u STRIX_GITHUB_MODELS_TOKEN
      -u OPENCODE_API_KEY
      -u OPENAI_API_KEY
      -u NVIDIA_API_KEY
      -u NVIDIA_NIM_API_KEY
    )
    ;;
  github-models/*)
    environment+=(
      -u OPENCODE_API_KEY
      -u OPENAI_API_KEY
      -u OPENROUTER_API_KEY
      -u NVIDIA_API_KEY
      -u NVIDIA_NIM_API_KEY
    )
    ;;
  *)
    environment+=(
      -u STRIX_GITHUB_MODELS_TOKEN
      -u OPENCODE_API_KEY
      -u OPENAI_API_KEY
      -u OPENROUTER_API_KEY
      -u NVIDIA_API_KEY
      -u NVIDIA_NIM_API_KEY
    )
    ;;
esac

exec "${environment[@]}" "$real_opencode" "$@"
