#!/usr/bin/env bash
# Starts contextual-orchestrator as a same-job, loopback-only sidecar: checks out
# the org's own contextual-orchestrator repo at an immutable reviewed commit,
# installs its hash-locked dependencies, registers whichever of the five upstream
# provider credentials are present as job secrets into its KV, runs model auto-
# discovery + cost-based auto-enable, then serves on 127.0.0.1 with a freshly
# generated bearer token. Intended to be sourced/invoked as an early step in a
# job that later calls into OpenCode/Noema/Strix so they can use contextual-
# orchestrator as their LLM backend. Not for public/shared exposure: loopback-
# only, one ephemeral token per job run, torn down with the runner.
set -euo pipefail

: "${GITHUB_ENV:=/dev/null}"
: "${GITHUB_OUTPUT:=/dev/null}"
# Reviewed protected-main commit. Callers may override it only with another exact
# 40-hex commit SHA; mutable branches/tags are deliberately rejected because the
# checkout receives provider credentials later in this script.
: "${CONTEXTUAL_ORCHESTRATOR_REF:=7eb459ee72c37dead5d25f284dfa4546f149fbe1}"
: "${CONTEXTUAL_ORCHESTRATOR_PORT:=8000}"
: "${CONTEXTUAL_ORCHESTRATOR_ENABLE_CHEAPEST:=3}"
: "${CONTEXTUAL_ORCHESTRATOR_READY_TIMEOUT_SECONDS:=60}"

if [[ ! "$CONTEXTUAL_ORCHESTRATOR_REF" =~ ^[0-9a-fA-F]{40}$ ]]; then
	echo "ERROR: CONTEXTUAL_ORCHESTRATOR_REF must be an exact 40-character git commit SHA." >&2
	exit 2
fi
if [[ ! "$CONTEXTUAL_ORCHESTRATOR_PORT" =~ ^[0-9]+$ ]] || [ "$CONTEXTUAL_ORCHESTRATOR_PORT" -lt 1 ] || [ "$CONTEXTUAL_ORCHESTRATOR_PORT" -gt 65535 ]; then
	echo "ERROR: CONTEXTUAL_ORCHESTRATOR_PORT must be a valid TCP port." >&2
	exit 2
fi
if [[ ! "$CONTEXTUAL_ORCHESTRATOR_ENABLE_CHEAPEST" =~ ^[0-9]+$ ]]; then
	echo "ERROR: CONTEXTUAL_ORCHESTRATOR_ENABLE_CHEAPEST must be a non-negative integer." >&2
	exit 2
fi
if [[ ! "$CONTEXTUAL_ORCHESTRATOR_READY_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || [ "$CONTEXTUAL_ORCHESTRATOR_READY_TIMEOUT_SECONDS" -lt 3 ]; then
	echo "ERROR: CONTEXTUAL_ORCHESTRATOR_READY_TIMEOUT_SECONDS must be an integer of at least 3 seconds." >&2
	exit 2
fi

# Self-gating: callers can invoke this unconditionally from every workflow.
# With none of the five upstream provider credentials present, there is
# nothing for contextual-orchestrator to discover or serve, so no-op cleanly
# (exit 0, CONTEXTUAL_ORCHESTRATOR_BASE_URL left unset) rather than making
# every caller duplicate this check in workflow YAML `if:` conditions.
has_any_provider_credential=0
for credential_name in BYTEZ_API_KEY NVIDIA_NIM_API_KEY NVIDIA_NIM_API_KEY_SUB OPENROUTER_API_KEY OPENAI_API_KEY; do
	if [ -n "${!credential_name:-}" ]; then
		has_any_provider_credential=1
		break
	fi
done
if [ "$has_any_provider_credential" -eq 0 ]; then
	echo "No upstream provider credentials are configured; skipping the contextual-orchestrator sidecar."
	exit 0
fi

RUNTIME_DIR="$(mktemp -d)"
cleanup_checkout() {
	rm -rf -- "$RUNTIME_DIR"
}
trap cleanup_checkout EXIT

echo "Checking out ContextualWisdomLab/contextual-orchestrator@${CONTEXTUAL_ORCHESTRATOR_REF}..."
git init --quiet "$RUNTIME_DIR"
git -C "$RUNTIME_DIR" remote add origin https://github.com/ContextualWisdomLab/contextual-orchestrator.git
git -C "$RUNTIME_DIR" fetch --quiet --depth 1 origin "$CONTEXTUAL_ORCHESTRATOR_REF"
git -C "$RUNTIME_DIR" checkout --quiet FETCH_HEAD
resolved_source_sha="$(git -C "$RUNTIME_DIR" rev-parse HEAD)"
if [ "$resolved_source_sha" != "$CONTEXTUAL_ORCHESTRATOR_REF" ]; then
	echo "ERROR: contextual-orchestrator checkout did not resolve to the reviewed commit SHA." >&2
	exit 2
fi

# Validate the pinned source license and every lock dependency's artifact
# license before creating a venv, installing packages, or importing source.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/validate_contextual_orchestrator_licenses.py" "$RUNTIME_DIR"

python3 -m venv "$RUNTIME_DIR/.venv-sidecar"
# shellcheck disable=SC1091
source "$RUNTIME_DIR/.venv-sidecar/bin/activate"
python -m pip install --quiet --require-hashes -r "$RUNTIME_DIR/requirements.lock"
python -m pip install --quiet --no-deps -e "$RUNTIME_DIR"

# Register only the credentials this job actually has; discovery silently
# skips any provider whose credential is missing (see model_discovery.py).
for credential_name in BYTEZ_API_KEY NVIDIA_NIM_API_KEY NVIDIA_NIM_API_KEY_SUB OPENROUTER_API_KEY OPENAI_API_KEY; do
	if [ -n "${!credential_name:-}" ]; then
		python -m contextual_orchestrator register-credential \
			--name "$credential_name" --from-env "$credential_name"
	fi
done

POOL_DB="$RUNTIME_DIR/agent-pool.db"
echo "Discovering models and auto-enabling the ${CONTEXTUAL_ORCHESTRATOR_ENABLE_CHEAPEST} cheapest..."
python -m contextual_orchestrator discover-models \
	--agents-db "$POOL_DB" \
	--enable-cheapest "$CONTEXTUAL_ORCHESTRATOR_ENABLE_CHEAPEST"

TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
echo "::add-mask::$TOKEN"

LOG_FILE="$RUNTIME_DIR/sidecar.log"
(
	cd "$RUNTIME_DIR"
	python -m contextual_orchestrator --serve \
		--agents examples/agents.mock.json \
		--agents-db "$POOL_DB" \
		--host 127.0.0.1 --port "$CONTEXTUAL_ORCHESTRATOR_PORT" \
		--auth-token "$TOKEN" \
		>"$LOG_FILE" 2>&1 &
	echo $! >"$RUNTIME_DIR/sidecar.pid"
)
# The checkout is only needed to launch the server; once it's up, remove the
# EXIT trap so the running process (and its still-open log/pool files) survive
# for the rest of the job. The server holds its own open file handles, so
# deleting the directory entry is safe on Linux runners even with it running.
trap - EXIT

BASE_URL="http://127.0.0.1:${CONTEXTUAL_ORCHESTRATOR_PORT}/v1"
deadline=$((SECONDS + CONTEXTUAL_ORCHESTRATOR_READY_TIMEOUT_SECONDS))
until curl --connect-timeout 1 --max-time 2 -fsS "http://127.0.0.1:${CONTEXTUAL_ORCHESTRATOR_PORT}/healthz" >/dev/null 2>&1; do
	if [ "$SECONDS" -ge "$deadline" ]; then
		echo "ERROR: contextual-orchestrator sidecar did not become ready within ${CONTEXTUAL_ORCHESTRATOR_READY_TIMEOUT_SECONDS}s." >&2
		tail -n 200 "$LOG_FILE" >&2 || true
		exit 1
	fi
	sleep 1
done
echo "contextual-orchestrator sidecar ready at $BASE_URL"

{
	echo "CONTEXTUAL_ORCHESTRATOR_BASE_URL=$BASE_URL"
	echo "CONTEXTUAL_ORCHESTRATOR_TOKEN=$TOKEN"
} >>"$GITHUB_ENV"
echo "contextual_orchestrator_base_url=$BASE_URL" >>"$GITHUB_OUTPUT"
