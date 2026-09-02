#!/usr/bin/env python3
"""One-shot exact-guarded repair for PR #1672 Noema heuristics."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts/ci/noema_review_gate.py"


def one(text, old, new, name):
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{name}: expected one match, found {n}")
    return text.replace(old, new, 1)


def span(text, start, end, new, name):
    if text.count(start) != 1 or text.count(end) != 1:
        raise RuntimeError(f"{name}: span guard mismatch")
    left = text.index(start)
    right = text.index(end, left)
    return text[:left] + new + text[right:]


s = GATE.read_text()
s = one(s, "import contextlib\n", "", "contextlib")
s = one(s, "import signal\n", "", "signal")
s = one(s, "from scripts.ci.opencode_review_normalize_output import changed_file_is_material\n\n\n", "", "filename inference")
s = span(s, "# NOT DATA-DERIVED -- UNRESOLVED, flagged for an explicit owner decision.\n", "NOEMA_REPAIR_DEADLINE_SECONDS = 15 * 60\n\n", "", "deadline comment")
s = one(s, "NOEMA_REPAIR_DEADLINE_SECONDS = 15 * 60\n\n", "", "deadline")
s = re.sub(r'\nclass NoemaRepairDeadlineExceeded\(TimeoutError\):\n    """.*?"""\n\n', '\n', s, count=1, flags=re.S)
if "class NoemaRepairDeadlineExceeded" in s:
    raise RuntimeError("deadline exception survived")

s = one(s, '                "enum": ["approve", "request_changes", "comment"],\n', '                "enum": ["request_changes", "comment"],\n', "schema decision")
s = one(s, "def _noema_verdict_json_schema(required_probes: int) -> dict[str, Any]:\n", "def _noema_verdict_json_schema() -> dict[str, Any]:\n", "schema signature")
s = one(s, '                        "minItems": required_probes,\n', "", "probe quota")
s = one(s, "def _noema_verdict_response_format(required_probes: int) -> dict[str, Any]:\n", "def _noema_verdict_response_format() -> dict[str, Any]:\n", "format signature")
s = one(s, '            "schema": _noema_verdict_json_schema(required_probes),\n', '            "schema": _noema_verdict_json_schema(),\n', "format schema")
s = span(s, "def _required_probe_count(diff: str, changed_paths: Sequence[str] = ()) -> int:\n", "def validate_substantive_verdict(\n", "", "filename probe quota")

s = one(s, '    if decision == "comment":\n        return\n', '    if decision == "comment":\n        return\n    if decision == "approve":\n        raise NoemaModelOutputError(\n            "Noema caller does not authorize approve without an independently governed admission design"\n        )\n    if decision != "request_changes":\n        raise NoemaModelOutputError("Noema formal verdict decision is unsupported")\n', "fail-closed approval")
s = one(s, '    expected_status = "passed" if decision == "approve" else "failed"\n', '    expected_status = "failed"\n', "status policy")
s = one(s, '    required_probes = _required_probe_count(diff, changed_paths)\n    if not isinstance(probes, list) or len(probes) < required_probes:\n        raise NoemaModelOutputError(f"Noema adversarial validation requires at least {required_probes} concrete probe(s)")\n', '    if not isinstance(probes, list):\n        raise NoemaModelOutputError("Noema adversarial validation probes must be a list")\n', "probe quota validation")
s = one(s, '        if not confirmed or not confirmed.intersection(finding_locations):\n            raise NoemaModelOutputError("Noema request_changes requires a confirmed probe on a published finding")\n', '        if not finding_locations or not finding_locations.issubset(confirmed):\n            raise NoemaModelOutputError(\n                "Noema request_changes requires a confirmed probe for every published finding"\n            )\n', "finding witness")

s = span(s, "@contextlib.contextmanager\ndef _repair_wall_clock_deadline(seconds: float):\n", "class StaleHeadDuringRepairRetryError(RuntimeError):\n", "", "deadline context")
s = one(s, '    if isinstance(exc, NoemaRepairDeadlineExceeded):\n        return "deadline_exceeded"\n', "", "deadline classifier")
s = one(s, '    model = os.environ.get("NOEMA_LLM_MODEL", "").strip() or "noema-default"\n', '    model = os.environ.get("NOEMA_LLM_MODEL", "").strip()\n', "model fallback")
s = one(s, '    reject_private_llm_url(api_url)\n', '    if model != "orchestrator/free":\n        raise RuntimeError("Noema LLM review requires model pool orchestrator/free")\n    if is_retry:\n        raise RuntimeError("Noema caller-owned model retry is disabled")\n    reject_private_llm_url(api_url)\n', "model pool guard")
s = one(s, '                "Every formal verdict must cite exact changed-side lines. APPROVE requires falsifying concrete regression hypotheses; source or test changes require at least two distinct probes and other changes require at least one. REQUEST_CHANGES requires a confirmed probe at a finding location.",\n', '                "This caller has no evidence-backed admission design for APPROVE. REQUEST_CHANGES requires a confirmed probe at every published finding location; otherwise return COMMENT.",\n', "prompt quota")
s = one(s, '        "temperature": 0,\n', "", "sampling temperature")
s = one(s, '        "response_format": _noema_verdict_response_format(\n            _required_probe_count(diff, changed_paths)\n        ),\n', '        "response_format": _noema_verdict_response_format(),\n', "response format call")
s = one(s, '            if decision not in {"approve", "request_changes", "comment"}:\n', '            if decision not in {"request_changes", "comment"}:\n', "runtime decision")

s = span(s, '        deadline_context = (\n', '            raw = decode_llm_response_body(raw_bytes)\n', '        with opener.open(request) as response:  # nosec B310\n            phase_reached = "reading"\n            raw_bytes = response.read()\n        phase_reached = "decoding"\n', "single transport attempt")
s = span(s, '        if is_retry:\n', '    attempt_elapsed = time.monotonic() - attempt_started\n', '        print(\n            f"::warning::Noema single attempt outcome={outcome} phase={phase_reached} "\n            f"duration={attempt_elapsed:.1f}s served_model={served_model_note}; "\n            "failed closed without caller retry."\n        )\n        if isinstance(exc, NoemaModelOutputError):\n            raise\n        if isinstance(exc, (urllib.error.URLError, http.client.HTTPException, OSError)):\n            raise NoemaTransportError(\n                f"Noema single-attempt transport failed closed: {current_failure}"\n            ) from exc\n        raise\n', "retry recursion")

for forbidden in ("NOEMA_REPAIR_DEADLINE_SECONDS", "_repair_wall_clock_deadline", "_required_probe_count", '"temperature": 0', "changed_file_is_material", "NoemaRepairDeadlineExceeded", "return call_llm("):
    if forbidden in s:
        raise RuntimeError(f"forbidden heuristic survived: {forbidden}")
GATE.write_text(s)


def append(path, marker, text):
    p = ROOT / path
    current = p.read_text()
    if marker not in current:
        p.write_text(current.rstrip() + "\n\n" + text.strip() + "\n")


basis = "Fielding, R., Nottingham, M., & Reschke, J. (2022). HTTP semantics (RFC 9110). Internet Engineering Task Force. https://doi.org/10.17487/RFC9110"
append("docs/doctoring/noema-repair-attempt-telemetry.md", "NOEMA-NO-HEURISTICS-FAIL-CLOSED-2026-09-02", f"<!-- NOEMA-NO-HEURISTICS-FAIL-CLOSED-2026-09-02 -->\n## 2026-09-02 no-heuristics amendment\nThe causal owner imposed an unsupported 900-second corrective deadline/second POST, temperature=0, and filename-derived 2-versus-1 probe quota. Noema now requests exactly orchestrator/free once without caller sampling/timeout/retry allocation. LLM APPROVE is fail-closed because no independently governed admission design exists. Every blocking finding requires a confirmed probe at that exact changed-side location; no replacement quota is invented.\n\nAPA 7: {basis}")
append("docs/product-technical-gap-baseline.md", "GAP-NOEMA-NO-HEURISTICS-FAIL-CLOSED-2026-09-02", f"<!-- GAP-NOEMA-NO-HEURISTICS-FAIL-CLOSED-2026-09-02 -->\n### 2026-09-02 — Noema caller inference/evidence policy\nCausal owner: scripts/ci/noema_review_gate.py. Removed fixed repair deadline/retry, fixed sampling temperature, filename-derived probe quota, and unsupported LLM approval admission. REQUEST_CHANGES now requires an exact confirmed witness for every published finding. Exact-head tests are authoritative. APA 7: {basis}")
append("docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md", "ADR0003-NOEMA-NO-HEURISTICS-FAIL-CLOSED-2026-09-02", f"<!-- ADR0003-NOEMA-NO-HEURISTICS-FAIL-CLOSED-2026-09-02 -->\n### 2026-09-02 amendment — Noema caller policy\nNoema MUST request exactly orchestrator/free and MUST NOT impose a repository-authored sampling temperature, inference deadline, automatic model retry, fallback order, or filename-derived evidence quota. APPROVE is not admissible without an independently governed admission design. Blocking findings require exact confirmed changed-line witnesses. APA 7: {basis}")
append("CHANGELOG.md", "NOEMA-NO-HEURISTICS-FAIL-CLOSED-CHANGELOG-2026-09-02", "<!-- NOEMA-NO-HEURISTICS-FAIL-CLOSED-CHANGELOG-2026-09-02 -->\n- 2026-09-02: Noema removed caller sampling, fixed repair deadline/automatic retry, filename probe quotas, and unsupported LLM approval admission; blocking findings require exact confirmed witnesses.")
print("PR #1672 fail-closed no-heuristics repair applied")
