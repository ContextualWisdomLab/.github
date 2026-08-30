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

ORCHESTRATOR_PIN_SHA="${ORCHESTRATOR_PIN_SHA:-30c6d71680e659f25a0a433d4726ad0d437f9757}"
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
# Must equal contextual_orchestrator_review_launcher.py's
# _DISCOVERY_DIAGNOSTICS_COMPLETE_SENTINEL exactly (pinned by a contract test
# on both sides): the last line the launcher writes to stderr once discovery
# finishes, letting the shell script wait for a deterministic marker instead
# of guessing whether the async sanitizer has caught up.
SIDECAR_DISCOVERY_DIAGNOSTICS_SENTINEL="discovery_diagnostics_complete"
CATALOG_LIMIT="${ORCHESTRATOR_CATALOG_LIMIT:-12}"
# 2026-08-30: raised from 4. contextual_orchestrator_review_policy.py's
# family_cap groups nvidia_nim and nvidia_nim_sub as one outage-domain family
# and, per an exact-head evidence trail, currently that single family is the
# *only* one populating orchestrator/free (46 free rows, 100% nvidia_nim* --
# 23 distinct model ids shared by both keys). Candidate selection sorts
# eligible rows alphabetically by (provider, model) with no reliability
# awareness, so a family_cap of 4 deterministically admitted the same four
# alphabetically-first candidates on every run -- always including two
# NVIDIA-retired model ids (google/gemma-3-12b-it, google/gemma-3-4b-it;
# confirmed HTTP 404 on live preflight) plus two others that timed out in the
# same recovered run -- while never giving the other ~19 healthy free
# nvidia_nim* models in the same run's own discovery report a chance. This is
# not throughput tuning: it is the confirmed, reproducible root cause of
# orchestrator/free's "no provider route passed the Strix plain-chat
# preflight" failures (see docs/product-technical-gap-baseline.md's
# 2026-08-30 sidecar-preflight entries for the full evidence, including the
# exact discovery/preflight artifact this comment is based on).
# 8 is a deliberately moderate raise, not a wholesale removal of the cap. The
# picking loop below also stops at CATALOG_LIMIT (12) total regardless of
# family_cap, so the absolute worst case across any number of families was
# already REVIEW_PREFLIGHT_TIMEOUT_SECONDS (10s) x 12 = 120s before this
# change (reached once family_cap x distinct-families >= 12, i.e. >=3
# families at the old cap of 4) and stays 120s after it -- this raise does
# not move that pre-existing ceiling. What it does change is when that
# ceiling is reached and the typical case today: with the single family
# (nvidia_nim) that currently fills 100% of orchestrator/free, worst-case
# preflight time rises from ~40s (4 candidates) to ~80s (8 candidates); with
# exactly two distinct families it would now also reach the 120s ceiling
# (previously ~80s at family_cap=4). Both figures stay within the sidecar's
# existing 180s readiness-wait budget in the common case; this was reasoned
# from, not verified against, live provider timing, since this session has
# no access to the five provider credentials the sidecar's KV requires. If
# real hosted
# runs show this is still insufficient (all 8 still failing) or the added
# latency itself becomes the bottleneck, the more complete fix is a live
# provider /v1/models cross-check at discovery time to drop retired model ids
# before they ever reach preflight (scripts/ci/select_nvidia_nim_model.py
# already implements that exact pattern for a different, currently-unwired
# caller) rather than raising this further.
CATALOG_FAMILY_CAP="${ORCHESTRATOR_CATALOG_FAMILY_CAP:-8}"
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
# Stream stdout/stderr through the redacting sanitizer as two named, awaitable
# processes (not bare `> >(...)` substitutions, whose PIDs bash never exposes)
# so a failure handler can wait for the sanitizer to finish flushing before it
# reads the sanitized file — otherwise the read can race the still-draining
# pipe and silently show an empty/truncated diagnostic (the exact class of bug
# this sanitizer exists to avoid: see the 2026-08-30 sidecar-diagnostics gap
# baseline entry).
exec {orchestrator_stdout_fd}> >("$sidecar_python" -u "$SIDECAR_LOG_SANITIZER" > "$sidecar_stdout")
stdout_sanitizer_pid=$!
exec {orchestrator_stderr_fd}> >("$sidecar_python" -u "$SIDECAR_LOG_SANITIZER" > "$sidecar_stderr")
stderr_sanitizer_pid=$!
wait_for_sidecar_sanitizers() {
  wait "$stdout_sanitizer_pid" 2>/dev/null || true
  wait "$stderr_sanitizer_pid" 2>/dev/null || true
}

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
  >&"$orchestrator_stdout_fd" 2>&"$orchestrator_stderr_fd" &
sidecar_pid=$!
# Close our own copies of the write ends now that the sidecar process holds
# its own duplicated fds. If these stayed open in this shell, the sanitizer
# process substitutions would never see EOF (and never exit) once the sidecar
# itself closes its fds, since a process substitution's reader only finishes
# after every writer has closed.
exec {orchestrator_stdout_fd}>&- {orchestrator_stderr_fd}>&-
cleanup_sidecar_on_error() {
  status=$?
  if [ "$status" -ne 0 ]; then
    publish_sidecar_evidence || true
    log "stopping failed sidecar (pid $sidecar_pid)"
    kill "$sidecar_pid" 2>/dev/null || true
    wait "$sidecar_pid" 2>/dev/null || true
    wait_for_sidecar_sanitizers
  fi
}
trap cleanup_sidecar_on_error EXIT

i=0
until curl -fsSL --max-time 2 "http://${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT}/healthz" >/dev/null 2>&1; do
  if ! kill -0 "$sidecar_pid" 2>/dev/null; then
    sidecar_status=0
    wait "$sidecar_pid" || sidecar_status=$?
    # The sidecar has fully exited (confirmed above), so its stderr pipe has
    # already sent EOF; draining the sanitizer here cannot hang, and it
    # guarantees $sidecar_stderr holds everything the sidecar wrote before we
    # read it for the failure message below.
    wait_for_sidecar_sanitizers
    # $preflight_report is written by the launcher's own ReviewPreflightError
    # handler before it exits (see contextual_orchestrator_review_launcher.py
    # main()), so it can hold real per-route evidence (agent_id/provider/
    # model/status/error_type/http_status -- schema-bounded, never raw
    # provider content or secrets) even though the generic exception message
    # above never does. Previously this file was only ever surfaced by
    # Strix's separate artifact-upload step, leaving every other workflow
    # (noema-review, opencode-review) blind to *why* every candidate route
    # was rejected. Printing it here puts that evidence in the one place
    # every workflow's job log already is.
    if [ -s "$preflight_report" ]; then
      log "sidecar preflight route evidence: $(sed -n '1,80p' "$preflight_report" | tr '\n' ' ')"
    fi
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
# A successful startup never re-reads $sidecar_stderr otherwise: only the
# failure branches above embed it in their ::error:: message. A partial,
# non-fatal provider discovery failure (e.g. one bad credential) would
# otherwise be silently invisible to every workflow except Strix's artifact
# upload -- print it into the always-visible job log too. The launcher
# always emits a "discovery_diagnostics_complete" sentinel as the LAST line
# it writes to stderr before this point in its own execution (discovery
# finishes strictly before the server can start accepting the healthz
# request that just succeeded above); waiting for the sanitizer to pass
# that same sentinel through -- rather than guessing from file size or a
# fixed sleep -- deterministically proves every earlier discovery-error
# line has already reached $sidecar_stderr too, since the sanitizer
# processes its input strictly in order.
sentinel_wait=0
until grep -qx "$SIDECAR_DISCOVERY_DIAGNOSTICS_SENTINEL" "$sidecar_stderr" 2>/dev/null; do
  sentinel_wait=$((sentinel_wait + 1))
  if [ "$sentinel_wait" -ge 25 ]; then
    log "sidecar startup warnings: sanitizer did not confirm discovery diagnostics within 5s; showing partial evidence"
    break
  fi
  sleep 0.2
done
sidecar_startup_warnings="$(grep -vx "$SIDECAR_DISCOVERY_DIAGNOSTICS_SENTINEL" "$sidecar_stderr" 2>/dev/null | sed -n '1,20p' || true)"
if [ -n "$sidecar_startup_warnings" ]; then
  log "sidecar startup warnings (non-fatal): $sidecar_startup_warnings"
fi

# Exercise the exact OpenAI-compatible endpoint and model name Strix uses. A
# process can be healthy while the coordinator/model-group path still raises an
# internal error, which is the failure this contract prevents from reaching the
# scanner step.
gateway_virtual_model="orchestrator/${orchestrator_pool}"
# max_tokens must match REVIEW_MAX_OUTPUT_TOKENS (the launcher's own escalated
# per-agent routing-probe budget, ADR-0005): observed behavior was an agent the
# routing probe already proved "ready" at that budget failing this separate
# end-to-end check with a spurious 502 invalid_structured_output at a much
# smaller budget, even though the model itself is healthy. The exact
# field-level cause was never captured (the sidecar's log sanitizer strips raw
# provider payloads by design), so treat any specific mechanism as a
# hypothesis, not fact. See "2026-08-30 sidecar preflight max_tokens
# desynchronized from the routing probe" (and its 2026-08-30 correction) in
# ContextualWisdomLab/contextual-orchestrator's own
# docs/product-technical-gap-baseline.md for the evidence that is actually
# captured (downloaded strix-reports artifact,
# ContextualWisdomLab/contextual-orchestrator#912 run 33304076516).
printf '{"model":"%s","messages":[{"role":"system","content":"You are a helpful assistant."},{"role":"user","content":"Reply with just '\''OK'\''."}],"temperature":1.0,"max_tokens":4096,"stream":false}\n' \
  "$gateway_virtual_model" > "$gateway_preflight_request"
# 30s (this check's previous bound) is too tight for a real completion from a
# reasoning-capable free-tier model: exact-evidence reproduction (Strix run
# 33306775025 on ContextualWisdomLab/contextual-orchestrator#921, job
# 99244624298) shows the routing probe marking a DeepSeek NIM route "ready"
# in 18s, then this identical request against that same healthy route being
# cut off by curl's own timeout at exactly 30.0s -- "gateway preflight
# request could not reach the local sidecar" is this curl failure, not an
# actual connectivity problem. This required-workflow job already budgets
# 120 minutes (see timeout-minutes in strix.yml/noema-review.yml), and the
# org's own stated policy accepts multi-hour central review latency in
# favor of accuracy over speed -- a 30s bound on one preflight self-check
# contradicted that policy and rejected a route the routing probe had just
# proven healthy. 120s keeps this a bounded, fail-closed check while giving
# a real reasoning generation room to finish. This value is deliberately kept
# unchanged by ADR-0005 -- shortening it would regress the fix just described.
#
# ADR-0005 Trigger A: this request goes to the virtual pool, not one pinned
# candidate, so a transport failure or non-2xx status here (unreachable
# process, timeout, upstream error) is retried with a fresh attempt at the
# SAME budget, up to REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS total attempts --
# a same-budget retry may or may not land on a different underlying candidate
# (route diversity here is a best-effort hope, not a verified guarantee: the
# gateway's internal routing behavior on a failed attempt is not confirmed),
# but it is strictly better than one unconditional attempt with no recovery
# path, which is what let a single transient hang block every required review
# org-wide (live reproduction: ContextualWisdomLab/.github#1449, job
# 99253418179, curl timing out at exactly 120002ms with zero bytes received).
# Trigger B (a response IS received, empty content, finish_reason=="length" or
# a populated reasoning field) is deliberately NOT retried here: that response
# is still HTTP 200, so the gateway's own routing already recorded that
# attempt as "successful" before this script inspects content -- a same-budget
# retry is more likely to repeat the same candidate than diversify away from
# it, so retrying would not help (Devin Review's 4th-round finding on
# ADR-0005; verified directly against contextual-orchestrator's server.py,
# which exposes no parameter to exclude or deprioritize a specific candidate
# on a retry).
REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS="${REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS:-3}"
# A malformed override (non-numeric, empty, or zero) must fail closed instead
# of silently disabling the bound: `[ "$gateway_attempt" -ge "$X" ]` with a
# non-integer `$X` is itself a bash integer-comparison error, not a false
# result, so the retry loop below would keep looping (never satisfying its
# own exit test) until the surrounding CI job's own timeout kills it instead
# of this check ever rejecting bad configuration on its own.
case "$REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS" in
  ''|*[!0-9]*|0) fail "REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS must be a positive integer" ;;
esac
gateway_attempt=1
gateway_http_status=""
while :; do
  if gateway_http_status="$(
    curl -sS --max-time 120 \
      -o "$gateway_preflight_response" \
      -w '%{http_code}' \
      -X POST \
      -H "Authorization: Bearer ${ORCHESTRATOR_TOKEN}" \
      -H 'Content-Type: application/json' \
      --data-binary "@$gateway_preflight_request" \
      "http://${ORCHESTRATOR_HOST}:${ORCHESTRATOR_PORT}/v1/chat/completions"
  )"; then
    :
  else
    gateway_http_status=""
  fi
  if [ "$gateway_http_status" = "200" ]; then
    break
  fi
  if [ "$gateway_attempt" -ge "$REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS" ]; then
    if [ -z "$gateway_http_status" ]; then
      # Every configured attempt exhausted with no usable HTTP response at
      # all (Trigger A never resolved) -- record that before failing closed,
      # using the same sanitize-then-atomic-replace pattern as the non-2xx
      # and invalid-content paths below, so this exact failure case (the one
      # telemetry matters most for) does not leave zero evidence trail.
      "$sidecar_python" - "$preflight_report" "$gateway_attempt" <<'PY'
import json
from pathlib import Path
import sys

report_path = Path(sys.argv[1])
attempts = int(sys.argv[2]) if sys.argv[2].isdecimal() else 0
try:
    report = json.loads(report_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError):
    report = {}
report["gateway"] = {
    "endpoint": "chat/completions",
    "error_type": "gateway_transport_exhausted",
    "attempts": attempts,
    "status": "rejected",
}
temporary = report_path.with_suffix(".tmp")
temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(report_path)
PY
      fail "gateway preflight request could not reach the local sidecar after ${gateway_attempt} attempts"
    fi
    "$sidecar_python" - "$preflight_report" "$gateway_preflight_response" "$gateway_http_status" "$gateway_attempt" <<'PY'
import json
from pathlib import Path
import re
import sys

report_path = Path(sys.argv[1])
response_path = Path(sys.argv[2])
status_text = sys.argv[3]
attempts = int(sys.argv[4]) if sys.argv[4].isdecimal() else 0
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
    # ADR-0005: a non-2xx on a retry (attempts > 1) is not honestly
    # attributable to any one candidate's ceiling -- the virtual pool's
    # routing is not pinned across separate HTTP calls -- so it is
    # recorded distinctly from a first-attempt rejection instead of
    # implying candidate-ceiling evidence it cannot support.
    "error_type": "gateway_retry_rejected" if attempts > 1 else "gateway_rejected",
    "error_code": code,
    "http_status": status,
    "attempts": attempts,
    "status": "rejected",
}
temporary = report_path.with_suffix(".tmp")
temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(report_path)
PY
    fail "gateway preflight returned HTTP ${gateway_http_status} after ${gateway_attempt} attempts"
  fi
  log "gateway preflight attempt ${gateway_attempt} did not reach the sidecar cleanly (status=${gateway_http_status:-unreachable}); retrying (up to ${REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS} attempts)"
  gateway_attempt=$((gateway_attempt + 1))
done
if ! "$sidecar_python" - "$gateway_preflight_response" "$preflight_report" "$gateway_attempt" <<'PY'
import json
from pathlib import Path
import sys

response_path = Path(sys.argv[1])
report_path = Path(sys.argv[2])
attempts = int(sys.argv[3]) if sys.argv[3].isdecimal() else 0
try:
    response = json.loads(response_path.read_text(encoding="utf-8"))
    choices = response.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else None
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str) and content.strip():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["gateway"] = {
            "endpoint": "chat/completions",
            "status": "ready",
            "attempts": attempts,
        }
        temporary = report_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(report_path)
        raise SystemExit(0)
    # ADR-0005 Trigger B, deliberately not retried at this layer (see the
    # comment above the curl loop): record which budget-too-small signature,
    # if any, matched -- for diagnosis only, since this response is a
    # terminal outcome here regardless of which one it is.
    finish_reason = first.get("finish_reason") if isinstance(first, dict) else None
    if not isinstance(finish_reason, str) or not finish_reason:
        finish_reason = None
    elif len(finish_reason) > 32 or not all(
        character.isalnum() or character == "_" for character in finish_reason
    ):
        finish_reason = "unknown"
    reasoning_without_content = isinstance(message, dict) and bool(message.get("reasoning"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["gateway"] = {
        "endpoint": "chat/completions",
        "status": "rejected",
        "error_type": "invalid_chat_response",
        "finish_reason": finish_reason or "unknown",
        "reasoning_without_content": reasoning_without_content,
        "attempts": attempts,
    }
    temporary = report_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(report_path)
except (OSError, json.JSONDecodeError, IndexError, TypeError):
    pass
raise SystemExit(1)
PY
then
  fail "gateway preflight returned unusable chat content"
fi
log "gateway chat/completions preflight confirmed (attempt ${gateway_attempt}/${REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS})"

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
