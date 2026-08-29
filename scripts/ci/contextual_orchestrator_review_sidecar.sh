#!/usr/bin/env bash
# Provision the vendored contextual-orchestrator review sidecar on a GitHub
# Actions runner and export the loopback URL plus a private bearer-file path to
# $GITHUB_ENV (when set). The raw bearer must never cross a step boundary in the
# runner environment because GitHub renders that environment before a later
# step can issue its own add-mask command.
#
# The five provider secrets arrive as bootstrap transport only (Actions env) and
# are registered into the process-local KV by the launcher in the SAME process
# that performs live model discovery and serves requests — never read back at
# request time. The in-process free-priced discovery evidence is turned into a
# ZDR-prioritized, provider-family-diverse agents catalog by
# scripts/ci/contextual_orchestrator_review_policy.py for the `orchestrator/free`
# (fail-closed zero-cost) pool.
set -euo pipefail

ORCHESTRATOR_PIN_SHA="${ORCHESTRATOR_PIN_SHA:-b21645116b352967e50fc497b87eb745b9cc8c61}"
ORCHESTRATOR_GIT_URL="${ORCHESTRATOR_GIT_URL:-https://github.com/ContextualWisdomLab/contextual-orchestrator.git}"
# The Strix gate and Noema SSRF guard accept this one process-local origin.
# Keep it fixed so an environment override cannot create an unvalidated sidecar.
ORCHESTRATOR_PORT="18080"
ORCHESTRATOR_HOST="127.0.0.1"
ORCHESTRATOR_SOURCE="${RUNNER_TEMP:-/tmp}/contextual-orchestrator"
ORCHESTRATOR_WORK="${RUNNER_TEMP:-/tmp}/contextual-orchestrator-review"
# The Strix artifact collector uploads this workspace-relative directory. Other
# review consumers retain the same safe evidence locally without changing their
# model or credential contract.
STRIX_EVIDENCE_DIR="${GITHUB_WORKSPACE:-$ORCHESTRATOR_WORK}/strix_runs"
ORCHESTRATOR_LAUNCHER="${ORCHESTRATOR_LAUNCHER:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/contextual_orchestrator_review_launcher.py}"
ORG_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SIDECAR_LOG_SANITIZER="$ORG_REPO_ROOT/scripts/ci/sanitize_contextual_orchestrator_sidecar_stream.py"
CATALOG_LIMIT="${ORCHESTRATOR_CATALOG_LIMIT:-24}"
CATALOG_FAMILY_CAP="${ORCHESTRATOR_CATALOG_FAMILY_CAP:-24}"
ORCHESTRATOR_GITHUB_ENV="${GITHUB_ENV:-}"
sidecar_python="$(command -v python3)"

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

ORCHESTRATOR_TOKEN="${ORCHESTRATOR_TOKEN:-$($sidecar_python -c 'import secrets; print(secrets.token_urlsafe(32))')}"
case "$ORCHESTRATOR_TOKEN" in
  *$'\r'*|*$'\n'*) fail "ORCHESTRATOR_TOKEN must not contain CR or LF" ;;
esac
# Mask the bearer before clone, dependency installation, launcher startup, or
# health diagnostics can emit it. Later masking is too late for earlier logs,
# but workflow commands are safe only on an Actions runner; elsewhere this
# would print the raw bearer to ordinary stdout.
if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
  printf '::add-mask::%s\n' "$ORCHESTRATOR_TOKEN"
fi

if [ -L "$STRIX_EVIDENCE_DIR" ]; then
  fail "Strix evidence directory must not be a symbolic link"
fi
if [ ! -f "$SIDECAR_LOG_SANITIZER" ] || [ -L "$SIDECAR_LOG_SANITIZER" ]; then
  fail "sidecar log sanitizer must be a regular, non-symlink file"
fi
mkdir -p "$ORCHESTRATOR_WORK" "$STRIX_EVIDENCE_DIR"
chmod 700 -- "$ORCHESTRATOR_WORK" "$STRIX_EVIDENCE_DIR"
token_file="$ORCHESTRATOR_WORK/bearer.token"
(
  umask 077
  printf '%s' "$ORCHESTRATOR_TOKEN" > "$token_file"
)
chmod 600 -- "$token_file"
rm -rf "$ORCHESTRATOR_SOURCE"
log "vendoring contextual-orchestrator @ ${ORCHESTRATOR_PIN_SHA}"
git clone --quiet --filter=blob:none --no-checkout "$ORCHESTRATOR_GIT_URL" "$ORCHESTRATOR_SOURCE"
git -C "$ORCHESTRATOR_SOURCE" -c advice.detachedHead=false checkout --quiet "$ORCHESTRATOR_PIN_SHA"
checked_out="$(git -C "$ORCHESTRATOR_SOURCE" rev-parse HEAD)"
if [ "$checked_out" != "$ORCHESTRATOR_PIN_SHA" ]; then
  fail "vendored HEAD ${checked_out} != pin ${ORCHESTRATOR_PIN_SHA}"
fi
requirements_lock="$ORCHESTRATOR_SOURCE/requirements.lock"
if [ ! -f "$requirements_lock" ]; then
  fail "vendored orchestrator is missing its hash-pinned requirements.lock"
fi
log "installing hash-pinned orchestrator dependencies at ${checked_out}"
"$sidecar_python" -m pip install --quiet --disable-pip-version-check --no-cache-dir \
  --require-hashes \
  --no-deps \
  -r "$requirements_lock"
PYTHONPATH="$ORCHESTRATOR_SOURCE:$ORG_REPO_ROOT" "$sidecar_python" -c \
  'from contextual_orchestrator.credentials import get_credential; from contextual_orchestrator.model_discovery import discover_all_models, free_discovered_models; from contextual_orchestrator.orchestrator import ModelClient, TaskOrchestrator, load_agents; from contextual_orchestrator.review_gateway import register_review_credentials; from contextual_orchestrator.server import SecurityConfig, serve'
PYTHONPATH="$ORCHESTRATOR_SOURCE:$ORG_REPO_ROOT" "$sidecar_python" - <<'PY'
import http.client
import contextlib
import io
import json
import threading

from contextual_orchestrator.orchestrator import ModelAgent, ModelClient, TaskOrchestrator
from contextual_orchestrator.server import SecurityConfig, build_server
from scripts.ci.contextual_orchestrator_review_launcher import REVIEW_MAX_BODY_BYTES

accepted_size = 64 * 1024 + 1
assert accepted_size < REVIEW_MAX_BODY_BYTES


class CaptureClient(ModelClient):
    def __init__(self):
        super().__init__(max_output_tokens=1)
        self.proxy_payloads = []

    def proxy_send(self, agent, endpoint, payload):
        self.proxy_payloads.append(json.loads(json.dumps(payload, ensure_ascii=False)))
        return super().proxy_send(agent, endpoint, payload)


client = CaptureClient()
orchestrator = TaskOrchestrator(
    [ModelAgent(id="body_limit_probe", model="openai/gpt-5")],
    client=client,
)
server = build_server(
    orchestrator,
    host="127.0.0.1",
    port=0,
    security=SecurityConfig(auth_token="contract", max_body_bytes=REVIEW_MAX_BODY_BYTES),
)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
    expected_rejection_log = io.StringIO()
    with contextlib.redirect_stderr(expected_rejection_log):
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=b"",
            headers={
                "Authorization": "Bearer contract",
                "Content-Type": "application/json",
                "Content-Length": str(REVIEW_MAX_BODY_BYTES + 1),
            },
        )
        response = connection.getresponse()
        assert response.status == 413, response.status
        response.read()
    assert "request_failed status=413 code=request_too_large" in expected_rejection_log.getvalue()
    connection.close()

    def post_payload(payload):
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        connection = http.client.HTTPConnection(
            "127.0.0.1", server.server_address[1], timeout=5
        )
        try:
            connection.request(
                "POST",
                "/v1/chat/completions",
                body=encoded,
                headers={
                    "Authorization": "Bearer contract",
                    "Content-Type": "application/json",
                    "Content-Length": str(len(encoded)),
                },
            )
            response = connection.getresponse()
            result = json.loads(response.read().decode("utf-8"))
            return response.status, result, len(encoded)
        finally:
            connection.close()

    large_status, large_body, encoded_size = post_payload({
        "model": "openai/gpt-5",
        "messages": [{"role": "user", "content": "x" * accepted_size}],
    })
    assert large_status == 200, large_body
    assert encoded_size > accepted_size

    for description_length in (1025, 1026, 2000):
        prefix = "preserve bytes – 🙂 "
        description = prefix + ("x" * (description_length - len(prefix)))
        status, body, _ = post_payload({
            "model": "openai/gpt-5",
            "messages": [{"role": "user", "content": "probe"}],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "scan_target",
                    "description": description,
                    "parameters": {"type": "object", "properties": {}},
                },
            }],
        })
        assert status == 200, body
        assert len(description) == description_length
        forwarded = client.proxy_payloads[-1]["tools"][0]["function"]["description"]
        assert forwarded.encode("utf-8") == description.encode("utf-8")
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)
PY

discovery_report="$ORCHESTRATOR_WORK/discovery-free.json"
zdr_feed="$ORCHESTRATOR_WORK/openrouter-zdr-endpoints.json"
catalog_file="$ORCHESTRATOR_WORK/agents.review.json"
policy_report="$ORCHESTRATOR_WORK/policy-report.json"
preflight_report="$STRIX_EVIDENCE_DIR/contextual-orchestrator-preflight.json"
sidecar_stdout="$STRIX_EVIDENCE_DIR/contextual-orchestrator-sidecar.stdout.log"
sidecar_stderr="$STRIX_EVIDENCE_DIR/contextual-orchestrator-sidecar.stderr.log"
gateway_preflight_request="$ORCHESTRATOR_WORK/gateway-preflight-request.json"
gateway_preflight_response="$ORCHESTRATOR_WORK/gateway-preflight.json"
(
  umask 077
  : > "$preflight_report"
  : > "$sidecar_stdout"
  : > "$sidecar_stderr"
  : > "$gateway_preflight_request"
  : > "$gateway_preflight_response"
)

publish_sidecar_evidence() {
  if [ -f "$discovery_report" ] && [ ! -L "$discovery_report" ]; then
    cp -- "$discovery_report" "$STRIX_EVIDENCE_DIR/contextual-orchestrator-discovery.json"
  fi
  if [ -f "$catalog_file" ] && [ ! -L "$catalog_file" ]; then
    cp -- "$catalog_file" "$STRIX_EVIDENCE_DIR/contextual-orchestrator-agents.json"
  fi
  if [ -f "$policy_report" ] && [ ! -L "$policy_report" ]; then
    cp -- "$policy_report" "$STRIX_EVIDENCE_DIR/contextual-orchestrator-policy.json"
  fi
}

# Optional authoritative ZDR route feed. Failure is non-fatal: the policy falls
# back to the dated static attestation table in scripts/ci/zdr_policy.py.
if curl -fsSL --max-time 15 "https://openrouter.ai/api/v1/endpoints/zdr" -o "$zdr_feed" 2>/dev/null; then
  log "using live OpenRouter ZDR endpoint feed"
  zdr_args=(--zdr-endpoints "$zdr_feed")
else
  log "ZDR endpoint feed unavailable; using dated static attestation table"
  zdr_args=()
fi

case "${CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR:-false}" in
  true)
    privacy_args=(--require-zdr)
    log "private/internal target: requiring attested ZDR routes"
    ;;
  false|"")
    privacy_args=()
    ;;
  *)
    fail "CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR must be true or false"
    ;;
esac

orchestrator_pool="${CONTEXTUAL_ORCHESTRATOR_POOL:-free}"
case "$orchestrator_pool" in
  free|auto)
    pool_args=(--pool "$orchestrator_pool")
    ;;
  *)
    fail "CONTEXTUAL_ORCHESTRATOR_POOL must be free or auto"
    ;;
esac

log "starting review sidecar on ${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT}"
cp "$ORCHESTRATOR_LAUNCHER" "$ORCHESTRATOR_WORK/launch_sidecar.py"
export ORCHESTRATOR_CATALOG_LIMIT="$CATALOG_LIMIT"
export ORCHESTRATOR_CATALOG_FAMILY_CAP="$CATALOG_FAMILY_CAP"
PYTHONPATH="$ORCHESTRATOR_SOURCE:$ORG_REPO_ROOT" \
  CONTEXTUAL_ORCHESTRATOR_TOKEN="$ORCHESTRATOR_TOKEN" \
  "$sidecar_python" "$ORCHESTRATOR_WORK/launch_sidecar.py" \
    --host "$ORCHESTRATOR_HOST" \
    --port "$ORCHESTRATOR_PORT" \
    --discovery-out "$discovery_report" \
    --catalog-out "$catalog_file" \
    --report-out "$policy_report" \
    --preflight-out "$preflight_report" \
    "${zdr_args[@]}" \
    "${privacy_args[@]}" \
    "${pool_args[@]}" \
> >("$sidecar_python" -u "$SIDECAR_LOG_SANITIZER" > "$sidecar_stdout") \
2> >("$sidecar_python" -u "$SIDECAR_LOG_SANITIZER" > "$sidecar_stderr") &
sidecar_pid=$!
cleanup_sidecar_on_error() {
  status=$?
  if [ "$status" -ne 0 ]; then
    publish_sidecar_evidence || true
    log "stopping failed sidecar (pid $sidecar_pid)"
    kill "$sidecar_pid" 2>/dev/null || true
    wait "$sidecar_pid" 2>/dev/null || true
  fi
}
trap cleanup_sidecar_on_error EXIT

i=0
until curl -fsSL --max-time 2 "http://${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT}/healthz" >/dev/null 2>&1; do
  if ! kill -0 "$sidecar_pid" 2>/dev/null; then
    sidecar_status=0
    wait "$sidecar_pid" || sidecar_status=$?
    fail "sidecar exited before healthz (status ${sidecar_status}); stderr: $(sed -n '1,20p' "$sidecar_stderr")"
  fi
  i=$((i + 1))
  if [ "$i" -ge 180 ]; then
    fail "sidecar did not become healthy; stderr: $(sed -n '1,20p' "$sidecar_stderr")"
  fi
  sleep 1
done
if [ ! -s "$preflight_report" ]; then
  fail "sidecar became healthy without runtime preflight evidence"
fi
publish_sidecar_evidence
log "healthz and provider-route preflight confirmed after ${i}s (pid $sidecar_pid)"

# Exercise the exact OpenAI-compatible endpoint and model name Strix uses. A
# process can be healthy while the coordinator/model-group path still raises an
# internal error, which is the failure this contract prevents from reaching the
# scanner step.
gateway_virtual_model="orchestrator/${orchestrator_pool}"
printf '{"model":"%s","messages":[{"role":"system","content":"You are a helpful assistant."},{"role":"user","content":"Reply with just '\''OK'\''."}],"temperature":1.0,"max_tokens":16,"stream":false}\n' \
  "$gateway_virtual_model" > "$gateway_preflight_request"
set +e
gateway_http_status="$(
  curl -sS --max-time 30 \
    -o "$gateway_preflight_response" \
    -w '%{http_code}' \
    -X POST \
    -H "Authorization: Bearer ${ORCHESTRATOR_TOKEN}" \
    -H 'Content-Type: application/json' \
    --data-binary "@$gateway_preflight_request" \
    "http://${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT}/v1/chat/completions"
)"
gateway_curl_status=$?
set -e
if [ "$gateway_curl_status" -ne 0 ]; then
  gateway_transport_status="transport_error"
  if [ "$gateway_curl_status" -eq 28 ]; then
    gateway_transport_status="transport_timeout"
  fi
  fail "gateway preflight ${gateway_transport_status} (curl exit ${gateway_curl_status})"
fi
if [ "$gateway_http_status" != "200" ]; then
  "$sidecar_python" - "$preflight_report" "$gateway_preflight_response" "$gateway_http_status" <<'PY'
import json
from pathlib import Path
import re
import sys

report_path = Path(sys.argv[1])
response_path = Path(sys.argv[2])
status_text = sys.argv[3]
try:
    report = json.loads(report_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    report = {}
try:
    response = json.loads(response_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    response = {}
error = response.get("error") if isinstance(response, dict) else None
code = error.get("code") if isinstance(error, dict) else None
if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", code):
    code = "unknown_error"
status = int(status_text) if status_text.isdecimal() else 0
report["gateway"] = {
    "endpoint": "chat/completions",
    "error_code": code,
    "http_status": status,
    "status": "rejected",
}
temporary = report_path.with_suffix(".tmp")
temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(report_path)
PY
  fail "gateway preflight returned HTTP ${gateway_http_status}"
fi
if ! "$sidecar_python" - "$gateway_preflight_response" "$preflight_report" <<'PY'
import json
from pathlib import Path
import sys

response_path = Path(sys.argv[1])
report_path = Path(sys.argv[2])
try:
    response = json.loads(response_path.read_text(encoding="utf-8"))
    choices = response.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else None
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("missing chat content")
    report = json.loads(report_path.read_text(encoding="utf-8"))
except (OSError, ValueError, json.JSONDecodeError, IndexError, TypeError):
    raise SystemExit(1)
report["gateway"] = {
    "endpoint": "chat/completions",
    "status": "ready",
}
temporary = report_path.with_suffix(".tmp")
temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(report_path)
PY
then
  fail "gateway preflight returned unusable chat content"
fi
log "gateway chat/completions preflight confirmed"

if [ -n "$ORCHESTRATOR_GITHUB_ENV" ]; then
  {
    printf 'CONTEXTUAL_ORCHESTRATOR_BASE_URL=http://%s:%s\n' "$ORCHESTRATOR_HOST" "$ORCHESTRATOR_PORT"
    printf 'CONTEXTUAL_ORCHESTRATOR_TOKEN_FILE=%s\n' "$token_file"
    printf 'CONTEXTUAL_ORCHESTRATOR_EVIDENCE=%s\n' "$policy_report"
    printf 'CONTEXTUAL_ORCHESTRATOR_PREFLIGHT_EVIDENCE=%s\n' "$preflight_report"
  } >> "$ORCHESTRATOR_GITHUB_ENV"
  log "exported gateway env to $ORCHESTRATOR_GITHUB_ENV"
else
  log "base_url=http://${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT}"
fi

log "policy evidence summary:"
sed -n '1,80p' "$policy_report" || true
log "runtime preflight summary:"
sed -n '1,160p' "$preflight_report" || true
