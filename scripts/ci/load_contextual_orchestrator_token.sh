#!/usr/bin/env bash
# Source inside a model-consuming GitHub Actions step. The provisioner exports
# only this file path across steps so the raw bearer cannot appear in a later
# step's rendered environment header before masking takes effect.

_contextual_orchestrator_token_fail() {
  printf '::error::%s\n' "$*" >&2
  return 1
}

_contextual_orchestrator_load_token() {
  local token_file token_size

  token_file="${CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE:-}"
  if [ -z "$token_file" ]; then
    _contextual_orchestrator_token_fail "CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE is required; the review sidecar was not provisioned." || return 1
  fi
  if [ ! -f "$token_file" ] || [ -L "$token_file" ]; then
    _contextual_orchestrator_token_fail "CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE must name a regular, non-symlink file." || return 1
  fi
  if [ "$(stat -c %u -- "$token_file")" != "$(id -u)" ]; then
    _contextual_orchestrator_token_fail "CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE must be owned by the current runner user." || return 1
  fi
  if [ "$(stat -c %a -- "$token_file")" != "600" ]; then
    _contextual_orchestrator_token_fail "CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE must have mode 600." || return 1
  fi
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

_contextual_orchestrator_load_token || {
  _contextual_orchestrator_status=$?
  unset -f _contextual_orchestrator_load_token _contextual_orchestrator_token_fail
  return "$_contextual_orchestrator_status"
}
unset -f _contextual_orchestrator_load_token _contextual_orchestrator_token_fail
