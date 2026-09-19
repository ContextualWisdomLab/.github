#!/usr/bin/env bash
# Fail-closed GitHub token export for Orca workers.
# Prefers a local App installation token, then falls back to the shared PAT.
# Never prints token values. Secrets stay under ~/.config/orca-workers/.
set -euo pipefail

ORCA_WORKERS_DIR="${ORCA_WORKERS_DIR:-${HOME}/.config/orca-workers}"
APP_TOKEN_FILE="${ORCA_APP_TOKEN_FILE:-${ORCA_WORKERS_DIR}/gh-token-app}"
APP_META_FILE="${ORCA_APP_META_FILE:-${ORCA_WORKERS_DIR}/gh-token-app.meta.json}"
PAT_TOKEN_FILE="${ORCA_PAT_TOKEN_FILE:-${ORCA_WORKERS_DIR}/gh-token}"
RATE_LIMIT_FILE="${ORCA_RATE_LIMIT_FILE:-${ORCA_WORKERS_DIR}/rate-limit.json}"
CACHE_DIR="${ORCA_GH_CACHE_DIR:-${ORCA_WORKERS_DIR}/cache}"

umask 077
mkdir -p "${ORCA_WORKERS_DIR}" "${CACHE_DIR}"

log() {
  printf '%s\n' "$*" >&2
}

die() {
  log "error: $*"
  exit 1
}

read_secret_file() {
  local path="$1"
  [[ -f "$path" ]] || return 1
  # strip a single trailing newline; reject empty
  local value
  value="$(tr -d '\r' <"$path" | sed -e 's/[[:space:]]*$//')"
  [[ -n "$value" ]] || return 1
  printf '%s' "$value"
}

iso_to_epoch() {
  local iso="$1"
  if date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$iso" "+%s" 2>/dev/null; then
    return 0
  fi
  if date -u -d "$iso" "+%s" 2>/dev/null; then
    return 0
  fi
  python3 - "$iso" <<'PY'
import sys
from datetime import datetime, timezone
raw = sys.argv[1].replace("Z", "+00:00")
print(int(datetime.fromisoformat(raw).astimezone(timezone.utc).timestamp()))
PY
}

app_token_unexpired() {
  [[ -f "$APP_META_FILE" ]] || return 1
  local expires
  expires="$(python3 - "$APP_META_FILE" <<'PY'
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
data = json.loads(path.read_text())
expires_at = data.get("expires_at")
if not isinstance(expires_at, str) or not expires_at:
    raise SystemExit(1)
print(expires_at)
PY
)" || return 1
  [[ -n "$expires" ]] || return 1
  local exp_epoch now
  exp_epoch="$(iso_to_epoch "$expires")" || return 1
  now="$(date -u +%s)"
  # 120s skew so workers do not use a token about to die mid-call
  (( now + 120 < exp_epoch ))
}

write_rate_limit_snapshot() {
  local remaining="$1" reset="$2" resource="$3" source="$4"
  python3 - "$RATE_LIMIT_FILE" "$remaining" "$reset" "$resource" "$source" <<'PY'
import json, sys, time
from pathlib import Path
path = Path(sys.argv[1])
payload = {
    "remaining": int(sys.argv[2]) if sys.argv[2].isdigit() else None,
    "reset": int(sys.argv[3]) if sys.argv[3].isdigit() else None,
    "resource": sys.argv[4] or None,
    "source": sys.argv[5],
    "recorded_at": int(time.time()),
}
path.write_text(json.dumps(payload, indent=2) + "\n")
PY
}

probe_token_budget() {
  local token="$1" label="$2"
  local headers auth_header remaining reset resource status
  headers="$(mktemp)"
  auth_header="$(mktemp)"
  chmod 0600 "$auth_header"
  printf 'Authorization: Bearer %s\n' "$token" >"$auth_header"
  trap 'rm -f "$headers" "$auth_header"' EXIT
  # One probe only. Do not retry here.
  status="$(
    curl -sS -D "$headers" -o /dev/null -w "%{http_code}" \
      -H "@${auth_header}" \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/rate_limit" || true
  )"
  remaining="$(awk -F': ' 'tolower($1)=="x-ratelimit-remaining" {gsub(/\r/,"",$2); print $2; exit}' "$headers")"
  reset="$(awk -F': ' 'tolower($1)=="x-ratelimit-reset" {gsub(/\r/,"",$2); print $2; exit}' "$headers")"
  resource="$(awk -F': ' 'tolower($1)=="x-ratelimit-resource" {gsub(/\r/,"",$2); print $2; exit}' "$headers")"
  rm -f "$headers" "$auth_header"
  trap - EXIT
  write_rate_limit_snapshot "${remaining:-}" "${reset:-}" "${resource:-}" "$label"
  if [[ "$status" == "403" || "$status" == "429" ]]; then
    log "token source=${label} probe HTTP ${status} remaining=${remaining:-?} reset=${reset:-?}"
    die "token source=${label} is rate limited; state recorded for a later invocation"
  fi
  if [[ "$status" != "200" ]]; then
    die "token source=${label} probe HTTP ${status}"
  fi
  if [[ -n "$remaining" && "$remaining" =~ ^[0-9]+$ ]] && (( remaining < 50 )); then
    log "warning: token source=${label} core remaining=${remaining}; prefer GraphQL cache and avoid REST"
  fi
}

select_token() {
  # Prints "source<TAB>token" on stdout so callers never guess which file won.
  local token=""
  if token="$(read_secret_file "$APP_TOKEN_FILE")"; then
    if app_token_unexpired; then
      log "using App installation token from ${APP_TOKEN_FILE}"
      printf 'app\t%s' "$token"
      return 0
    fi
    log "warning: ${APP_TOKEN_FILE} present but meta says expired; ignoring"
  fi
  if token="$(read_secret_file "$PAT_TOKEN_FILE")"; then
    log "warning: falling back to shared PAT at ${PAT_TOKEN_FILE}; App token preferred"
    printf 'pat\t%s' "$token"
    return 0
  fi
  die "no usable token: place App token at ${APP_TOKEN_FILE} or PAT at ${PAT_TOKEN_FILE}"
}

main() {
  local selected source token
  selected="$(select_token)"
  source="${selected%%$'\t'*}"
  token="${selected#*$'\t'}"
  [[ -n "$token" && "$token" != "$selected" ]] || die "internal token selection failed"
  probe_token_budget "$token" "$source"
  export GH_TOKEN="$token"
  export GITHUB_TOKEN="$token"
  if [[ "$#" -eq 0 ]]; then
    # Intentionally does not print the token (avoids shell-history leakage).
    log "GH_TOKEN exported in this process only. Re-run with a command, e.g.:"
    log "  $0 -- gh api user --jq .login"
    exit 0
  fi
  if [[ "$1" == "--" ]]; then
    shift
  fi
  exec "$@"
}

main "$@"
