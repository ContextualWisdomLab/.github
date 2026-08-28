#!/usr/bin/env bash
# Provision the vendored contextual-orchestrator review sidecar on a GitHub
# Actions runner and export CONTEXTUAL_ORCHESTRATOR_BASE_URL / _TOKEN to
# $GITHUB_ENV (when set).
#
# The five provider secrets arrive as bootstrap transport only (Actions env) and
# are registered into the process-local KV by the launcher in the SAME process
# that performs live model discovery and serves requests — never read back at
# request time. The in-process free-priced discovery evidence is turned into a
# ZDR-prioritized, provider-family-diverse agents catalog by
# scripts/ci/contextual_orchestrator_review_policy.py for the `orchestrator/free`
# (fail-closed zero-cost) pool.
set -euo pipefail

ORCHESTRATOR_PIN_SHA="${ORCHESTRATOR_PIN_SHA:-c60ec889bdd1b8dd0b2be53e60d7b758a4ece6b7}"
ORCHESTRATOR_GIT_URL="${ORCHESTRATOR_GIT_URL:-https://github.com/ContextualWisdomLab/contextual-orchestrator.git}"
ORCHESTRATOR_PORT="${ORCHESTRATOR_PORT:-18080}"
ORCHESTRATOR_HOST="${ORCHESTRATOR_HOST:-127.0.0.1}"
ORCHESTRATOR_SOURCE="${RUNNER_TEMP:-/tmp}/contextual-orchestrator"
ORCHESTRATOR_WORK="${RUNNER_TEMP:-/tmp}/contextual-orchestrator-review"
ORCHESTRATOR_SITE_PACKAGES="$ORCHESTRATOR_WORK/site-packages"
ORCHESTRATOR_LAUNCHER="${ORCHESTRATOR_LAUNCHER:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/contextual_orchestrator_review_launcher.py}"
ORG_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CATALOG_LIMIT="${ORCHESTRATOR_CATALOG_LIMIT:-12}"
CATALOG_FAMILY_CAP="${ORCHESTRATOR_CATALOG_FAMILY_CAP:-4}"
ORCHESTRATOR_GITHUB_ENV="${GITHUB_ENV:-}"

log() { printf '[contextual-orchestrator-sidecar] %s\n' "$*"; }

fail() { log "error: $*" >&2; exit 1; }

# Require at least one of the five provider secrets so we never boot an empty
# (or mock) pool. Missing individual secrets are allowed — discovery skips the
# unregistered provider — matching the review gateway contract.
provider_secret_count=0
for secret_name in BYTEZ_API_KEY NVIDIA_NIM_API_KEY NVIDIA_NIM_API_KEY_SUB OPENROUTER_API_KEY OPENAI_API_KEY; do
  if [ -n "${!secret_name:-}" ]; then
    provider_secret_count=$((provider_secret_count + 1))
  fi
done
if [ "$provider_secret_count" -lt 1 ]; then
  fail "at least one of BYTEZ_API_KEY / NVIDIA_NIM_API_KEY / NVIDIA_NIM_API_KEY_SUB / OPENROUTER_API_KEY / OPENAI_API_KEY is required"
fi
log "provider secrets present: $provider_secret_count of 5"

ORCHESTRATOR_TOKEN="${ORCHESTRATOR_TOKEN:-$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')}"
case "$ORCHESTRATOR_TOKEN" in
  *$'\r'*|*$'\n'*) fail "ORCHESTRATOR_TOKEN must not contain carriage returns or newlines" ;;
esac

mkdir -p "$ORCHESTRATOR_WORK"
rm -rf "$ORCHESTRATOR_SOURCE" "$ORCHESTRATOR_SITE_PACKAGES"
mkdir -p "$ORCHESTRATOR_SITE_PACKAGES"
log "vendoring contextual-orchestrator @ ${ORCHESTRATOR_PIN_SHA}"
git clone --quiet --filter=blob:none --no-checkout "$ORCHESTRATOR_GIT_URL" "$ORCHESTRATOR_SOURCE"
git -C "$ORCHESTRATOR_SOURCE" -c advice.detachedHead=false checkout --quiet "$ORCHESTRATOR_PIN_SHA"
checked_out="$(git -C "$ORCHESTRATOR_SOURCE" rev-parse HEAD)"
if [ "$checked_out" != "$ORCHESTRATOR_PIN_SHA" ]; then
  fail "vendored HEAD ${checked_out} != pin ${ORCHESTRATOR_PIN_SHA}"
fi
log "installing vendored orchestrator at ${checked_out}"
python3 -m pip install --quiet --disable-pip-version-check --no-cache-dir --target "$ORCHESTRATOR_SITE_PACKAGES" "$ORCHESTRATOR_SOURCE"

discovery_report="$ORCHESTRATOR_WORK/discovery-free.json"
zdr_feed="$ORCHESTRATOR_WORK/openrouter-zdr-endpoints.json"
catalog_file="$ORCHESTRATOR_WORK/agents.review.json"
policy_report="$ORCHESTRATOR_WORK/policy-report.json"

# Optional authoritative ZDR route feed. Failure is non-fatal: the policy falls
# back to the dated static attestation table in scripts/ci/zdr_policy.py.
if curl -fsSL --max-time 15 "https://openrouter.ai/api/v1/endpoints/zdr" -o "$zdr_feed" 2>/dev/null; then
  log "using live OpenRouter ZDR endpoint feed"
  zdr_args=(--zdr-endpoints "$zdr_feed")
else
  log "ZDR endpoint feed unavailable; using dated static attestation table"
  zdr_args=()
fi

log "starting review sidecar on ${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT}"
cp "$ORCHESTRATOR_LAUNCHER" "$ORCHESTRATOR_WORK/launch_sidecar.py"
export ORCHESTRATOR_CATALOG_LIMIT="$CATALOG_LIMIT"
export ORCHESTRATOR_CATALOG_FAMILY_CAP="$CATALOG_FAMILY_CAP"
PYTHONPATH="$ORCHESTRATOR_SITE_PACKAGES:$ORCHESTRATOR_SOURCE:$ORG_REPO_ROOT" \
  CONTEXTUAL_ORCHESTRATOR_TOKEN="$ORCHESTRATOR_TOKEN" \
  "$(command -v python3)" "$ORCHESTRATOR_WORK/launch_sidecar.py" \
    --host "$ORCHESTRATOR_HOST" \
    --port "$ORCHESTRATOR_PORT" \
    --discovery-out "$discovery_report" \
    --catalog-out "$catalog_file" \
    --report-out "$policy_report" \
    "${zdr_args[@]}" \
> "$ORCHESTRATOR_WORK/sidecar.stdout" 2> "$ORCHESTRATOR_WORK/sidecar.stderr" &
sidecar_pid=$!
cleanup_sidecar_on_error() {
  status=$?
  if [ "$status" -ne 0 ]; then
    log "stopping failed sidecar (pid $sidecar_pid)"
    kill "$sidecar_pid" 2>/dev/null || true
    wait "$sidecar_pid" 2>/dev/null || true
  fi
}
trap cleanup_sidecar_on_error EXIT

i=0
until curl -fsSL --max-time 2 "http://${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT}/healthz" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -ge 60 ]; then
    fail "sidecar did not become healthy; stderr: $(sed -n '1,10p' "$ORCHESTRATOR_WORK/sidecar.stderr")"
  fi
  sleep 1
done
log "healthz confirmed after ${i}s (pid $sidecar_pid)"

printf '::add-mask::%s\n' "$ORCHESTRATOR_TOKEN"
if [ -n "$ORCHESTRATOR_GITHUB_ENV" ]; then
  {
    printf 'CONTEXTUAL_ORCHESTRATOR_BASE_URL=http://%s:%s\n' "$ORCHESTRATOR_HOST" "$ORCHESTRATOR_PORT"
    printf 'CONTEXTUAL_ORCHESTRATOR_TOKEN=%s\n' "$ORCHESTRATOR_TOKEN"
    printf 'CONTEXTUAL_ORCHESTRATOR_EVIDENCE=%s\n' "$policy_report"
  } >> "$ORCHESTRATOR_GITHUB_ENV"
  log "exported gateway env to $ORCHESTRATOR_GITHUB_ENV"
else
  log "base_url=http://${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT}"
fi

log "policy evidence summary:"
sed -n '1,80p' "$policy_report" || true