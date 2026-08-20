#!/usr/bin/env bash
# Starts contextual-orchestrator as a same-job, loopback-only sidecar: checks out
# the org's own contextual-orchestrator repo at an immutable reviewed commit,
# installs its hash-locked dependencies, registers whichever of the five upstream
# provider credentials are present into a process-local KV, discovers and enables
# a bounded model pool, then serves it from the same Python process. The single
# process is essential: the default credential backend is intentionally
# process-local, so separate register/discover/serve CLI invocations would lose
# the credentials between phases.
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
if [[ ! "$CONTEXTUAL_ORCHESTRATOR_ENABLE_CHEAPEST" =~ ^[0-9]+$ ]] || [ "$CONTEXTUAL_ORCHESTRATOR_ENABLE_CHEAPEST" -lt 1 ]; then
	echo "ERROR: CONTEXTUAL_ORCHESTRATOR_ENABLE_CHEAPEST must be a positive integer." >&2
	exit 2
fi
if [[ ! "$CONTEXTUAL_ORCHESTRATOR_READY_TIMEOUT_SECONDS" =~ ^[0-9]+$ ]] || [ "$CONTEXTUAL_ORCHESTRATOR_READY_TIMEOUT_SECONDS" -lt 3 ]; then
	echo "ERROR: CONTEXTUAL_ORCHESTRATOR_READY_TIMEOUT_SECONDS must be an integer of at least 3 seconds." >&2
	exit 2
fi

PROVIDER_CREDENTIAL_NAMES=(
	BYTEZ_API_KEY
	NVIDIA_NIM_API_KEY
	NVIDIA_NIM_API_KEY_SUB
	OPENROUTER_API_KEY
	OPENAI_API_KEY
)

# Self-gating: callers can invoke this unconditionally from every workflow.
# With none of the five upstream provider credentials present, there is
# nothing for contextual-orchestrator to discover or serve, so no-op cleanly.
has_any_provider_credential=0
for credential_name in "${PROVIDER_CREDENTIAL_NAMES[@]}"; do
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
sidecar_pid=""
cleanup_failed_startup() {
	local exit_status=$?
	trap - EXIT
	if [ -n "$sidecar_pid" ] && kill -0 "$sidecar_pid" 2>/dev/null; then
		kill "$sidecar_pid" 2>/dev/null || true
		wait "$sidecar_pid" 2>/dev/null || true
	fi
	rm -rf -- "$RUNTIME_DIR"
	exit "$exit_status"
}
trap cleanup_failed_startup EXIT

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

TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
echo "::add-mask::$TOKEN"
LOG_FILE="$RUNTIME_DIR/sidecar.log"

# Register credentials, discover models, build the failover-capable orchestrator,
# and serve from one Python process. Source is imported directly from the exact
# reviewed checkout; no editable build backend or unpinned build dependency runs.
PYTHONPATH="$RUNTIME_DIR" \
CONTEXTUAL_ORCHESTRATOR_SIDECAR_TOKEN="$TOKEN" \
CONTEXTUAL_ORCHESTRATOR_SIDECAR_PORT="$CONTEXTUAL_ORCHESTRATOR_PORT" \
CONTEXTUAL_ORCHESTRATOR_SIDECAR_ENABLE_CHEAPEST="$CONTEXTUAL_ORCHESTRATOR_ENABLE_CHEAPEST" \
"$RUNTIME_DIR/.venv-sidecar/bin/python" - >"$LOG_FILE" 2>&1 <<'PY' &
from __future__ import annotations

from dataclasses import replace
import os

credential_names = (
    "BYTEZ_API_KEY",
    "NVIDIA_NIM_API_KEY",
    "NVIDIA_NIM_API_KEY_SUB",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
)
credentials: dict[str, str] = {}
for credential_name in credential_names:
    credential_value = os.environ.pop(credential_name, "")
    if credential_value:
        credentials[credential_name] = credential_value

auth_token = os.environ.pop("CONTEXTUAL_ORCHESTRATOR_SIDECAR_TOKEN", "")
port_text = os.environ.pop("CONTEXTUAL_ORCHESTRATOR_SIDECAR_PORT", "")
enable_text = os.environ.pop("CONTEXTUAL_ORCHESTRATOR_SIDECAR_ENABLE_CHEAPEST", "")
if not credentials:
    raise RuntimeError("no provider credentials survived sidecar bootstrap")
if not auth_token:
    raise RuntimeError("sidecar authentication token is missing")

port = int(port_text)
enable_cheapest = int(enable_text)
if not 1 <= port <= 65535:
    raise RuntimeError("sidecar port is outside the valid range")
if enable_cheapest < 1:
    raise RuntimeError("sidecar model count must be positive")

from contextual_orchestrator import TaskOrchestrator, register_credential
from contextual_orchestrator.cost_ledger import PriceBook
from contextual_orchestrator.kv_config import InMemoryConfigStore
from contextual_orchestrator.model_discovery import (
    agent_from_discovered,
    discover_all_models,
    refresh_price_book,
    select_top_n_cheapest_discovered_agents,
)
from contextual_orchestrator.orchestrator import ModelClient
from contextual_orchestrator.server import SecurityConfig, serve

for credential_name, credential_value in credentials.items():
    register_credential(credential_name, credential_value)
credentials.clear()

discovered_models, discovery_errors = discover_all_models()
if not discovered_models:
    providers_with_errors = sorted(
        {getattr(error, "provider_name", "unknown") for error in discovery_errors}
    )
    provider_summary = ",".join(providers_with_errors) or "none"
    raise RuntimeError(
        "model discovery returned no candidates; providers_with_errors="
        + provider_summary
    )

price_book = PriceBook(InMemoryConfigStore())
refresh_price_book(discovered_models, price_book)
selected_models = select_top_n_cheapest_discovered_agents(
    discovered_models,
    price_book,
    enable_cheapest,
)
if not selected_models:
    raise RuntimeError("model discovery produced no enableable candidates")

active_agents = [
    replace(agent_from_discovered(model), disabled=False)
    for model in selected_models
]
orchestrator = TaskOrchestrator(active_agents, client=ModelClient())
serve(
    orchestrator,
    host="127.0.0.1",
    port=port,
    security=SecurityConfig(auth_token=auth_token),
)
PY
sidecar_pid="$!"

# The shell no longer needs provider keys; prevent readiness probes or any other
# child process in this step from inheriting them.
for credential_name in "${PROVIDER_CREDENTIAL_NAMES[@]}"; do
	unset "$credential_name"
done

BASE_URL="http://127.0.0.1:${CONTEXTUAL_ORCHESTRATOR_PORT}/v1"
deadline=$((SECONDS + CONTEXTUAL_ORCHESTRATOR_READY_TIMEOUT_SECONDS))
until curl --connect-timeout 1 --max-time 2 -fsS "http://127.0.0.1:${CONTEXTUAL_ORCHESTRATOR_PORT}/healthz" >/dev/null 2>&1; do
	if ! kill -0 "$sidecar_pid" 2>/dev/null; then
		echo "ERROR: contextual-orchestrator sidecar exited before becoming ready." >&2
		tail -n 200 "$LOG_FILE" >&2 || true
		exit 1
	fi
	if [ "$SECONDS" -ge "$deadline" ]; then
		echo "ERROR: contextual-orchestrator sidecar did not become ready within ${CONTEXTUAL_ORCHESTRATOR_READY_TIMEOUT_SECONDS}s." >&2
		tail -n 200 "$LOG_FILE" >&2 || true
		exit 1
	fi
	sleep 1
done
echo "contextual-orchestrator sidecar ready at $BASE_URL"

# Keep the process and its exact-SHA checkout alive for the remainder of the
# GitHub job. The runner tears them down at job completion. Failed startup paths
# retain the EXIT trap above and therefore kill the child and remove the checkout.
trap - EXIT

{
	echo "CONTEXTUAL_ORCHESTRATOR_BASE_URL=$BASE_URL"
	echo "CONTEXTUAL_ORCHESTRATOR_TOKEN=$TOKEN"
} >>"$GITHUB_ENV"
echo "contextual_orchestrator_base_url=$BASE_URL" >>"$GITHUB_OUTPUT"
