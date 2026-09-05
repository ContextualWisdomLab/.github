"""Drift-safe one-shot repair for PR #1629's remaining inference heuristics."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/ci/contextual_orchestrator_review_launcher.py"
SIDECAR = ROOT / "scripts/ci/contextual_orchestrator_review_sidecar.sh"
ADR = ROOT / "docs/adr/0005-sidecar-preflight-token-budget.md"
GAP = ROOT / "docs/product-technical-gap-baseline.md"
CHANGELOG = ROOT / "CHANGELOG.md"


def between(text: str, start: str, end: str, replacement: str, *, label: str) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"{label}: start anchor missing")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"{label}: end anchor missing")
    if text.find(start, start_index + 1) >= 0:
        raise RuntimeError(f"{label}: start anchor is not unique")
    return text[:start_index] + replacement + text[end_index:]


def repair_launcher() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    for needle in (
        "REVIEW_MAX_OUTPUT_TOKENS = 4096",
        "REVIEW_TEMPERATURE = 1.0",
        "REVIEW_PREFLIGHT_BASE_TOKENS = 16",
        "REVIEW_PREFLIGHT_ESCALATED_TOKENS = REVIEW_MAX_OUTPUT_TOKENS",
        'escalated_payload["max_tokens"] = REVIEW_PREFLIGHT_ESCALATED_TOKENS',
    ):
        if needle not in text:
            raise RuntimeError(f"launcher drift: missing {needle!r}")

    constants_start = "# Keep ordinary review turns portable across small zero-cost providers."
    constants_end_line = "REVIEW_PREFLIGHT_ESCALATED_TOKENS = REVIEW_MAX_OUTPUT_TOKENS\n"
    start_index = text.index(constants_start)
    end_index = text.index(constants_end_line, start_index) + len(constants_end_line)
    text = text[:start_index] + text[end_index:].lstrip("\n")

    replacement = '''def _preflight_review_agent(\n    agent: object, *, client: Any\n) -> tuple[object | None, dict[str, object]]:\n    """Observe one route once without allocating inference compute.\n\n    Startup needs evidence that an admitted route can answer the ordinary\n    OpenAI-compatible plain-chat shape. No validated model in this repository\n    identifies a token budget, sampling temperature, or retry count for that\n    observation, so provider defaults are left unspecified and the payload is\n    sent exactly once. Empty, truncated, or reasoning-only output is retained\n    as diagnostic evidence but cannot authorize a guessed second model call.\n    """\n    row: dict[str, object] = {\n        "agent_id": str(getattr(agent, "id", "")),\n        "provider": str(getattr(agent, "provider_name", "") or "unknown"),\n        "model": str(getattr(agent, "model", "")),\n        "attempts": 1,\n    }\n    payload: dict[str, object] = {\n        "model": getattr(agent, "model", ""),\n        "messages": [\n            {"role": "system", "content": "You are a helpful assistant."},\n            {"role": "user", "content": "Reply with just 'OK'."},\n        ],\n        "stream": False,\n    }\n    try:\n        response = _send_preflight_request(client, agent, payload)\n    except Exception as exc:  # noqa: BLE001 - sanitize at provider boundary\n        _record_provider_exception(row, exc)\n        return None, row\n\n    row["finish_reason"] = _response_finish_reason(response) or "unknown"\n    row["reasoning_without_content"] = _response_has_reasoning_without_content(response)\n    if _chat_response_has_text(response):\n        row["status"] = "ready"\n        return agent, row\n\n    row["status"] = "rejected"\n    row["error_type"] = "insufficient_preflight_evidence"\n    return None, row\n\n\ndef _preflight_review_agents(\n    agents: list[object], *, client: Any\n) -> tuple[list[object], dict[str, object]]:\n    """Probe every admitted route once with provider-account isolation.\n\n    Independent credential accounts may progress concurrently because this\n    changes transport scheduling only: it cannot alter candidate membership,\n    request count per route, generation controls, or output ordering. Routes\n    sharing one provider account stay serialized, and evidence is restored to\n    catalog order before publication.\n    """\n    if not agents:\n        report: dict[str, object] = {\n            "contract": "strix-plain-chat-preflight-v3",\n            "probed_count": 0,\n            "ready_count": 0,\n            "rejected_count": 0,\n            "routes": [],\n        }\n        raise ReviewPreflightError(\n            "no provider route passed the Strix plain-chat preflight", report\n        )\n\n    provider_lanes: dict[str, list[tuple[int, object]]] = {}\n    for index, agent in enumerate(agents):\n        account = str(getattr(agent, "provider_name", "") or "unknown")\n        provider_lanes.setdefault(account, []).append((index, agent))\n\n    def probe_lane(\n        lane: list[tuple[int, object]],\n    ) -> list[tuple[int, tuple[object | None, dict[str, object]]]]:\n        return [\n            (index, _preflight_review_agent(agent, client=client))\n            for index, agent in lane\n        ]\n\n    with ThreadPoolExecutor(\n        max_workers=len(provider_lanes), thread_name_prefix="review-preflight"\n    ) as executor:\n        futures = [executor.submit(probe_lane, lane) for lane in provider_lanes.values()]\n        indexed_outcomes = [\n            item for future in futures for item in future.result()\n        ]\n    indexed_outcomes.sort(key=lambda item: item[0])\n\n    viable: list[object] = []\n    routes: list[dict[str, object]] = []\n    for _index, (ready_agent, row) in indexed_outcomes:\n        routes.append(row)\n        if ready_agent is not None:\n            viable.append(ready_agent)\n\n    report = {\n        "contract": "strix-plain-chat-preflight-v3",\n        "probed_count": len(agents),\n        "ready_count": len(viable),\n        "rejected_count": len(agents) - len(viable),\n        "routes": routes,\n    }\n    if not viable:\n        raise ReviewPreflightError(\n            "no provider route passed the Strix plain-chat preflight", report\n        )\n    return viable, report\n\n\n'''
    text = between(
        text,
        "def _preflight_review_agent(",
        "def _log_preflight_rejections(",
        replacement,
        label="launcher preflight block",
    )

    old_client = '''    client = ModelClient(\n        timeout=None,\n        max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS,\n        max_retries=0,\n        temperature=REVIEW_TEMPERATURE,\n    )'''
    if text.count(old_client) != 2:
        raise RuntimeError(
            f"launcher client drift: expected two constructors, found {text.count(old_client)}"
        )
    text = text.replace(old_client, "    client = ModelClient(timeout=None, max_retries=0)")

    for forbidden in (
        "REVIEW_MAX_OUTPUT_TOKENS",
        "REVIEW_TEMPERATURE",
        "REVIEW_PREFLIGHT_BASE_TOKENS",
        "REVIEW_PREFLIGHT_ESCALATED_TOKENS",
        '"max_tokens"',
        '"temperature"',
        "_preflight_with_fallback",
        "escalations_used",
    ):
        if forbidden in text:
            raise RuntimeError(f"launcher repair incomplete: {forbidden!r} remains")
    LAUNCHER.write_text(text, encoding="utf-8")


def repair_sidecar() -> None:
    text = SIDECAR.read_text(encoding="utf-8")
    for needle in (
        '"temperature":1.0,"max_tokens":4096',
        'REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS="${REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS:-3}"',
    ):
        if needle not in text:
            raise RuntimeError(f"sidecar drift: missing {needle!r}")

    start = 'gateway_virtual_model="orchestrator/${orchestrator_pool}"'
    end = 'if ! "$sidecar_python" - "$gateway_preflight_response" "$preflight_report" "$gateway_attempt" <<\'PY\''
    replacement = r'''gateway_virtual_model="orchestrator/${orchestrator_pool}"
printf '{"model":"%s","messages":[{"role":"system","content":"You are a helpful assistant."},{"role":"user","content":"Reply with just '\''OK'\''."}],"stream":false}\n' \
  "$gateway_virtual_model" > "$gateway_preflight_request"
# One provider-default model-inference compatibility observation. The available
# evidence identifies no inference retry count, output-token allocation,
# temperature, or wall-clock deadline. A transport/non-2xx result therefore
# fails closed instead of manufacturing another model request.
gateway_attempt=1
gateway_http_status=""
if gateway_http_status="$(
  curl -sS \
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
    "error_type": "gateway_transport_failure" if not status else "gateway_rejected",
    "error_code": code,
    "http_status": status,
    "attempts": 1,
    "status": "rejected",
}
temporary = report_path.with_suffix(".tmp")
temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(report_path)
PY
  if [ -z "$gateway_http_status" ]; then
    fail "gateway preflight request could not reach the local sidecar"
  fi
  fail "gateway preflight returned HTTP ${gateway_http_status}"
fi
'''
    text = between(text, start, end, replacement, label="sidecar gateway preflight")
    for forbidden in (
        "REVIEW_PREFLIGHT_GATEWAY_MAX_ATTEMPTS",
        '"temperature":1.0',
        '"max_tokens":4096',
        "retrying (up to",
    ):
        if forbidden in text:
            raise RuntimeError(f"sidecar repair incomplete: {forbidden!r} remains")
    SIDECAR.write_text(text, encoding="utf-8")


def append_docs() -> None:
    adr = ADR.read_text(encoding="utf-8")
    heading = "## 2026-09-02 no-heuristics compute-allocation amendment"
    if heading not in adr:
        ADR.write_text(
            adr.rstrip()
            + '''\n\n## 2026-09-02 no-heuristics compute-allocation amendment\n\nThe historical 16-token base probe, 4096-token escalation/serving request,\n`temperature=1.0`, and three-attempt gateway retry were repository-authored\ninference allocations. A truncated or reasoning-only response proves only that\nthe observed request did not yield usable review text; it does not identify a\nstatistically justified next token budget, sampling value, or number of extra\nmodel calls. Those fixed values therefore cease to be decision authority.\nCentral review startup now makes exactly one provider-default plain-chat\ncompatibility observation per admitted route and one provider-default\nvirtual-pool observation. Missing, malformed, truncated, or transport-failed\nevidence fails closed. Provider-published `max_output_tokens` metadata may clamp\nan independently explicit request ceiling, but it does not determine how much\ngeneration the review sidecar should allocate.\n\nFugu, Conductor, TRINITY and documented learned-routing successors can justify\ncompute allocation only when their estimator is actually trained/evaluated for\nthis deployment and has executable provenance; their existence is not evidence\nfor the retired constants. HTTP failure classification likewise does not\nidentify a number of LLM inference replays.\n\n### Standards and research traceability (APA 7)\n\nFielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics* (RFC\n9110). Internet Engineering Task Force. https://www.rfc-editor.org/rfc/rfc9110\n\nOpenRouter. (2026). *OpenRouter API specification* [OpenAPI specification].\nhttps://openrouter.ai/openapi.yaml\n'''
            + "\n",
            encoding="utf-8",
        )

    gap = GAP.read_text(encoding="utf-8")
    gap_heading = "### 2026-09-02 — central review preflight compute allocation"
    if gap_heading not in gap:
        GAP.write_text(
            gap.rstrip()
            + '''\n\n### 2026-09-02 — central review preflight compute allocation\n\n**Live gap.** PR #1629's admission-only catalog repair still carried fixed\n`16 -> 4096` semantic token escalation, `temperature=1.0`, a 4096-token\nvirtual-pool request, and a three-attempt gateway inference retry. These values\nchanged model-call quantity or test-time compute without an identified\nstatistical/research model. Issues #1454 and #1458 already documented that the\nold probe/escalation policy could not prove serving-budget compatibility and\nthat bounded escalation allocation introduced order-dependent selection.\n\n**Causal owner and repair.** The shared owner is\n`scripts/ci/contextual_orchestrator_review_launcher.py` plus\n`scripts/ci/contextual_orchestrator_review_sidecar.sh`. The repair removes\nrepository-owned generation-token, temperature, and inference-retry allocation\nfrom startup. Each admitted route receives one provider-default compatibility\nobservation; insufficient response evidence fails closed as\n`insufficient_preflight_evidence`. The virtual-pool check is likewise exactly\none provider-default request. `timeout=None` and `max_retries=0` remain explicit\nnegative controls until contextual-orchestrator's library defaults are repaired\nby their canonical owner PR.\n\n**Executable evidence.**\n`tests/test_contextual_orchestrator_review_no_heuristic_compute.py` is the\nRED-before-repair contract. Historical escalation/retry cases stay in the\nnon-collectable case module as incident evidence; the collection shim replaces\ntheir forbidden policy oracle with the fail-closed contract. Exact-head hosted\nverification is required before merge; predecessor results do not count.\n\n**Basis.** RFC 9110 constrains HTTP semantics but does not identify a number of\nLLM inference retries. Provider-published output ceilings constrain an explicit\nrequest but do not identify a desired review-generation allocation. Without an\nindependently validated compute-allocation model, fail closed is the only\nnon-invented behavior.\n'''
            + "\n",
            encoding="utf-8",
        )

    changelog = CHANGELOG.read_text(encoding="utf-8")
    marker = "Removed review-sidecar inference allocation heuristics"
    if marker not in changelog:
        CHANGELOG.write_text(
            changelog.rstrip()
            + '''\n\n- (PR #1629 no-heuristics RCA) Removed review-sidecar inference allocation heuristics:\n  fixed 16/4096 token probes, repository-authored temperature, semantic\n  escalation, and the three-attempt gateway model retry. Startup now performs\n  one provider-default compatibility observation and fails closed when that\n  evidence is insufficient; no token/retry substitute is invented.\n'''
            + "\n",
            encoding="utf-8",
        )


def main() -> None:
    repair_launcher()
    repair_sidecar()
    append_docs()


if __name__ == "__main__":
    main()
