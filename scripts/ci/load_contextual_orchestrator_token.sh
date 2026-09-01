#!/usr/bin/env bash
# Source inside a model-consuming GitHub Actions step. The provisioner exports
# only this file path across steps so the raw bearer cannot appear in a later
# step's rendered environment header before masking takes effect.

_contextual_orchestrator_token_fail() {
  printf '::error::%s\n' "$*" >&2
  return 1
}

_contextual_orchestrator_stat() {
  local format="$1" target="$2" value

  if value="$(stat -c "$format" -- "$target" 2>/dev/null)"; then
    printf '%s\n' "$value"
    return 0
  fi
  if [ "$format" = "%a" ]; then
    stat -f '%OMp %OLp' "$target"
    return 0
  fi
  stat -f "$format" "$target"
}

_contextual_orchestrator_load_token() {
  local token_file token_mode token_size

  token_file="${CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE:-}"
  if [ -z "$token_file" ]; then
    _contextual_orchestrator_token_fail "CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE is required; the review sidecar was not provisioned." || return 1
  fi
  if [ ! -f "$token_file" ] || [ -L "$token_file" ]; then
    _contextual_orchestrator_token_fail "CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE must name a regular, non-symlink file." || return 1
  fi
  if [ "$(_contextual_orchestrator_stat %u "$token_file")" != "$(id -u)" ]; then
    _contextual_orchestrator_token_fail "CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE must be owned by the current runner user." || return 1
  fi
  token_mode="$(_contextual_orchestrator_stat %a "$token_file")"
  case "$token_mode" in
    600|"0 600") ;;
    *)
      _contextual_orchestrator_token_fail "CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE must have mode 600." || return 1
      ;;
  esac
  token_size="$(wc -c < "$token_file")"
  if [ "$token_size" -lt 1 ] || [ "$token_size" -gt 4096 ]; then
    _contextual_orchestrator_token_fail "CONTEXTUAL_ORCHESTRATOR_TOKEN must contain between 1 and 4096 bytes." || return 1
  fi
  if [ "$(wc -l < "$token_file")" -ne 0 ] || grep -q $'\r' -- "$token_file"; then
    _contextual_orchestrator_token_fail "CONTEXTUAL_ORCHESTRATOR_TOKEN must not contain CR or LF." || return 1
  fi

  CONTEXTUAL_ORCHESTRATOR_TOKEN="$(cat -- "$token_file")"
  if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    printf '::add-mask::%s\n' "$CONTEXTUAL_ORCHESTRATOR_TOKEN"
  fi
  export CONTEXTUAL_ORCHESTRATOR_TOKEN
}

_contextual_orchestrator_materialize_noema_codegraph() {
  # This loader is shared by several model consumers. Noema is identified by
  # the reviewer-credential provenance that its trusted workflow sets in the
  # same step; all other consumers retain token-loading-only behavior.
  if [ -z "${NOEMA_REVIEW_TOKEN_SOURCE:-}" ]; then
    return 0
  fi
  if [ -z "${TARGET_REPOSITORY:-}" ] || [ -z "${PR_NUMBER:-}" ] || [ -z "${EXPECTED_HEAD_SHA:-}" ]; then
    _contextual_orchestrator_token_fail "Noema CodeGraph materialization requires target repository, PR number, and exact head SHA." || return 1
  fi
  if [ -z "${GH_TOKEN:-}" ]; then
    _contextual_orchestrator_token_fail "Noema CodeGraph materialization requires the selected repository-scoped reviewer token." || return 1
  fi
  if [ -z "${RUNNER_TEMP:-}" ] || [ -z "${GITHUB_WORKSPACE:-}" ]; then
    _contextual_orchestrator_token_fail "Noema CodeGraph materialization requires GitHub runner paths." || return 1
  fi

  local pull_request_json live_head_sha base_sha helper
  if ! pull_request_json="$(gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}")"; then
    _contextual_orchestrator_token_fail "Noema CodeGraph could not refresh pull-request identity before materialization." || return 1
  fi
  live_head_sha="$(jq -r '.head.sha // empty' <<<"$pull_request_json")"
  base_sha="$(jq -r '.base.sha // empty' <<<"$pull_request_json")"
  if [[ ! "$base_sha" =~ ^[0-9a-fA-F]{40}$ ]] || [ "${live_head_sha,,}" != "${EXPECTED_HEAD_SHA,,}" ]; then
    _contextual_orchestrator_token_fail "Noema CodeGraph refused stale or malformed pull-request source identity." || return 1
  fi

  helper="${GITHUB_WORKSPACE}/scripts/ci/noema_codegraph_context.sh"
  if [ ! -f "$helper" ] || [ -L "$helper" ]; then
    _contextual_orchestrator_token_fail "Trusted Noema CodeGraph helper is missing or symlinked." || return 1
  fi

  PR_BASE_SHA="$base_sha"
  NOEMA_CODEGRAPH_CONTEXT_PATH="${RUNNER_TEMP}/noema-codegraph-evidence.md"
  NOEMA_REQUIRE_CODEGRAPH_CONTEXT=1
  export PR_BASE_SHA NOEMA_CODEGRAPH_CONTEXT_PATH NOEMA_REQUIRE_CODEGRAPH_CONTEXT
  if ! bash "$helper"; then
    _contextual_orchestrator_token_fail "Noema CodeGraph exact-head materialization failed." || return 1
  fi
  if [ ! -s "$NOEMA_CODEGRAPH_CONTEXT_PATH" ] || [ -L "$NOEMA_CODEGRAPH_CONTEXT_PATH" ]; then
    _contextual_orchestrator_token_fail "Noema CodeGraph did not produce a regular non-empty evidence packet." || return 1
  fi
}

_contextual_orchestrator_cleanup_helpers() {
  unset -f \
    _contextual_orchestrator_load_token \
    _contextual_orchestrator_materialize_noema_codegraph \
    _contextual_orchestrator_stat \
    _contextual_orchestrator_token_fail \
    _contextual_orchestrator_cleanup_helpers
}

_contextual_orchestrator_load_token || {
  _contextual_orchestrator_status=$?
  _contextual_orchestrator_cleanup_helpers
  return "$_contextual_orchestrator_status"
}
_contextual_orchestrator_materialize_noema_codegraph || {
  _contextual_orchestrator_status=$?
  _contextual_orchestrator_cleanup_helpers
  return "$_contextual_orchestrator_status"
}
_contextual_orchestrator_cleanup_helpers
