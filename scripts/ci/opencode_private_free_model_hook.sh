#!/usr/bin/env bash
# Thin hook sourced by the live model-pool runner. Do not replace the pool.

anonymous_free_candidates="opencode-free/nemotron-3-ultra-free opencode-free/deepseek-v4-flash-free opencode-free/north-mini-code-free opencode-free/laguna-s-2.1-free opencode-free/ling-3.0-flash-free opencode-free/big-pickle opencode-free/mimo-v2.5-free"

die() {
  printf '%s\n' "$1" >&2
  exit 1
}

candidate_list_contains_anonymous_free_model() {
  local candidate
  local -a candidates
  read -r -a candidates <<<"${OPENCODE_MODEL_CANDIDATES:-}"
  for candidate in "${candidates[@]}"; do
    case "$candidate" in
      opencode-free/*)
        return 0
        ;;
    esac
  done
  return 1
}

is_governed_anonymous_free_candidate() {
  local candidate="$1"
  case " $anonymous_free_candidates " in
    *" $candidate "*) return 0 ;;
    *) return 1 ;;
  esac
}

filter_preconfigured_anonymous_free_candidates() {
  local allow_governed_free="$1"
  local combined=""
  local candidate
  local -a candidates
  read -r -a candidates <<<"${OPENCODE_MODEL_CANDIDATES:-}"
  for candidate in "${candidates[@]}"; do
    case "$candidate" in
      opencode-free/*)
        if [ "$allow_governed_free" != "true" ] ||
          ! is_governed_anonymous_free_candidate "$candidate"; then
          continue
        fi
        ;;
    esac
    combined="${combined:+$combined }$candidate"
  done
  OPENCODE_MODEL_CANDIDATES="$combined"
  export OPENCODE_MODEL_CANDIDATES
}

prepend_unique_anonymous_free_candidates() {
  local combined=""
  local candidate
  local -a candidates
  read -r -a candidates <<<"$anonymous_free_candidates ${OPENCODE_MODEL_CANDIDATES:-}"
  for candidate in "${candidates[@]}"; do
    case " $combined " in
      *" $candidate "*)
        ;;
      *)
        combined="${combined:+$combined }$candidate"
        ;;
    esac
  done
  OPENCODE_MODEL_CANDIDATES="$combined"
  export OPENCODE_MODEL_CANDIDATES
}

source_repository_is_public_without_credentials() {
  local source_workdir="${OPENCODE_SOURCE_WORKDIR:-}"
  local remote_url
  [ -n "$source_workdir" ] && [ -d "$source_workdir/.git" ] || return 1
  remote_url="$(
    git -c credential.helper= -C "$source_workdir" remote get-url origin 2>/dev/null || true
  )"
  if ! [[ "$remote_url" =~ ^https://github\.com/ContextualWisdomLab/[A-Za-z0-9_.-]+(\.git)?$ ]]; then
    return 1
  fi

  # Positive unauthenticated Git access is sufficient evidence that the source is
  # public. Any timeout, transport failure, private auth requirement, or malformed
  # remote is deliberately indistinguishable here and fails closed.
  timeout --kill-after=5s 15s \
    env -u GH_TOKEN -u GITHUB_TOKEN -u COPILOT_GITHUB_TOKEN -u OPENCODE_APP_TOKEN \
      -u ACTIONS_ID_TOKEN_REQUEST_TOKEN -u ACTIONS_ID_TOKEN_REQUEST_URL \
      -u ACTIONS_RUNTIME_TOKEN -u STRIX_GITHUB_MODELS_TOKEN \
      -u OPENCODE_API_KEY -u OPENAI_API_KEY -u OPENROUTER_API_KEY \
      -u NVIDIA_API_KEY -u NVIDIA_NIM_API_KEY \
      GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL=/dev/null GIT_TERMINAL_PROMPT=0 \
      git -c credential.helper= -c http.extraHeader= ls-remote "$remote_url" HEAD \
      >/dev/null 2>&1
}

repository_visibility_is_public() {
  case "${OPENCODE_REPOSITORY_IS_PRIVATE:-}" in
    false)
      return 0
      ;;
    true)
      return 1
      ;;
    "")
      source_repository_is_public_without_credentials
      return $?
      ;;
    *)
      printf '::warning::OpenCode repository visibility input is invalid; anonymous free candidates require trusted-base policy approval.\n' >&2
      return 1
      ;;
  esac
}

maybe_enable_private_free_models() {
  if repository_visibility_is_public; then
    # Public callers may keep only currently governed zero-cost aliases. Unknown
    # `opencode-free/*` names are removed so catalog drift cannot become paid or
    # model-unavailable traffic under a misleading free prefix.
    filter_preconfigured_anonymous_free_candidates true
    return 0
  fi

  # Private or unverified callers never inherit a preconfigured anonymous
  # candidate. The immutable base policy below is the only re-enable path.
  filter_preconfigured_anonymous_free_candidates false

  local source_workdir="${OPENCODE_SOURCE_WORKDIR:-}"
  local base_sha="${PR_BASE_SHA:-}"
  local head_sha="${PR_HEAD_SHA:-${HEAD_SHA:-}}"
  [ -n "$source_workdir" ] || return 0
  [ -n "$base_sha" ] || return 0
  [ -n "$head_sha" ] || return 0

  local policy_result policy_status
  set +e
  policy_result="$(
    python3 -I "$policy_checker" \
      --repo-root "$source_workdir" \
      --base-sha "$base_sha" \
      --head-sha "$head_sha" \
      --explain 2>&1
  )"
  policy_status=$?
  set -e

  case "$policy_status" in
    0)
      prepend_unique_anonymous_free_candidates
      printf '%s\n' "$policy_result"
      printf 'Enabled governed anonymous OpenCode free-model candidates from the unchanged trusted base policy.\n'
      ;;
    1)
      # Missing, invalid, or head-modified policies are the expected fail-closed path.
      ;;
    *)
      printf '::warning::Private free-model policy evaluation failed closed.\n' >&2
      ;;
  esac
}

install_provider_guard() {
  local real_opencode
  real_opencode="$(command -v opencode 2>/dev/null || true)"
  [ -n "$real_opencode" ] || return 0

  local guard_parent guard_dir
  guard_parent="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
  mkdir -p "$guard_parent"
  guard_dir="$(mktemp -d "$guard_parent/opencode-provider-guard.XXXXXX")"
  cp "$provider_guard" "$guard_dir/opencode"
  chmod 0700 "$guard_dir/opencode"
  OPENCODE_REAL_BIN="$real_opencode"
  OPENCODE_PROVIDER_GUARD_DIR="$guard_dir"
  PATH="$guard_dir:$PATH"
  export OPENCODE_REAL_BIN OPENCODE_PROVIDER_GUARD_DIR PATH
}

cleanup_provider_guard() {
  if [ -n "${OPENCODE_PROVIDER_GUARD_DIR:-}" ]; then
    rm -rf -- "$OPENCODE_PROVIDER_GUARD_DIR"
  fi
}

apply_private_free_model_policy() {
  local hook_dir
  hook_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  policy_checker="$hook_dir/opencode_private_free_model_policy.py"
  provider_guard="$hook_dir/opencode_provider_guard.sh"
  [ -f "$policy_checker" ] || die "OpenCode private free-model policy checker is missing."
  [ -f "$provider_guard" ] || die "OpenCode provider credential guard is missing."
  # Unit tests pass OPENCODE_MODEL_CANDIDATES directly. Do not strip free
  # aliases unless the review workflow supplied visibility or a base SHA.
  if [ -z "${OPENCODE_REPOSITORY_IS_PRIVATE:-}" ] &&
    [ -z "${PR_BASE_SHA:-}" ]; then
    trap cleanup_provider_guard EXIT INT TERM
    install_provider_guard
    return 0
  fi
  maybe_enable_private_free_models
  trap cleanup_provider_guard EXIT INT TERM
  install_provider_guard
}
