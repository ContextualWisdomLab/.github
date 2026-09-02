#!/usr/bin/env python3
"""One-shot exact-guarded repair for PR #1672 Noema decision heuristics."""

from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts/ci/noema_review_gate.py"
TELEMETRY_TEST = ROOT / "tests/test_noema_repair_attempt_telemetry.py"


def replace_once(text: str, old: str, new: str, *, owner: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{owner}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_span(text: str, start: str, end: str, replacement: str, *, owner: str) -> str:
    start_count = text.count(start)
    end_count = text.count(end)
    if start_count != 1 or end_count != 1:
        raise RuntimeError(
            f"{owner}: guard mismatch start={start_count} end={end_count}"
        )
    left = text.index(start)
    right = text.index(end, left)
    return text[:left] + replacement + text[right:]


source = GATE.read_text()

source = replace_once(source, "import contextlib\n", "", owner="contextlib import")
source = replace_once(source, "import signal\n", "", owner="signal import")
source = replace_once(
    source,
    "from scripts.ci.opencode_review_normalize_output import changed_file_is_material\n\n\n",
    "",
    owner="material-name inference import",
)

constant_start = "# NOT DATA-DERIVED -- UNRESOLVED, flagged for an explicit owner decision.\n"
constant_end = "NOEMA_REPAIR_DEADLINE_SECONDS = 15 * 60\n\n"
source = replace_span(source, constant_start, constant_end, "", owner="repair deadline heuristic")
source = replace_once(source, constant_end, "", owner="repair deadline constant") if constant_end in source else source

probe_comment_start = "# ``adversarial_validation.probes`` carries a ``minItems`` floor built fresh\n"
probe_comment_end = "_NOEMA_REVIEWED_LINE_SCHEMA: dict[str, Any] = {\n"
new_probe_comment = """# No repository-authored probe-count floor is encoded in this schema. A fixed\n# cardinality such as source/test=2 and other=1 is not identified by a\n# statistical model, standard, or validated experiment. Formal APPROVE instead\n# uses an executable set-completeness contract in validate_substantive_verdict:\n# every exact changed-side location in an untruncated diff must be represented\n# by reviewed evidence and a falsified adversarial probe. REQUEST_CHANGES uses\n# the logically necessary witness relation between a confirmed probe and a\n# published finding. If complete evidence is unavailable, approval fails closed.\n"""
source = replace_span(
    source,
    probe_comment_start,
    probe_comment_end,
    new_probe_comment,
    owner="probe-count schema commentary",
)

source = replace_once(
    source,
    "def _noema_verdict_json_schema(required_probes: int) -> dict[str, Any]:\n    \"\"\"Build the verdict JSON Schema with this request's exact probe floor.\n\n    ``required_probes`` must come from ``_required_probe_count(diff,\n    changed_paths)`` -- the same call ``validate_substantive_verdict`` uses\n    -- so the gateway-enforced structural floor and the Python-side backstop\n    can never silently diverge. The static per-field schemas above are safe\n    to share by reference here since nothing in this module mutates them.\n    \"\"\"\n",
    "def _noema_verdict_json_schema() -> dict[str, Any]:\n    \"\"\"Build the structural verdict schema without an invented count floor.\"\"\"\n",
    owner="schema function signature",
)
source = replace_once(
    source,
    '                        "minItems": required_probes,\n',
    "",
    owner="schema minItems heuristic",
)
source = replace_once(
    source,
    "def _noema_verdict_response_format(required_probes: int) -> dict[str, Any]:\n    \"\"\"Build the OpenAI ``response_format`` envelope for this request's probe floor.\"\"\"\n",
    "def _noema_verdict_response_format() -> dict[str, Any]:\n    \"\"\"Build the OpenAI ``response_format`` envelope for the verdict shape.\"\"\"\n",
    owner="response format signature",
)
source = replace_once(
    source,
    '            "schema": _noema_verdict_json_schema(required_probes),\n',
    '            "schema": _noema_verdict_json_schema(),\n',
    owner="response format schema call",
)

source = re.sub(
    r"\nclass NoemaRepairDeadlineExceeded\(TimeoutError\):\n(?:    .*\n)+?\n",
    "\n",
    source,
    count=1,
)
if "class NoemaRepairDeadlineExceeded" in source:
    raise RuntimeError("deadline exception class was not removed")

required_probe_start = "def _required_probe_count(diff: str, changed_paths: Sequence[str] = ()) -> int:\n"
validate_start = "def validate_substantive_verdict(\n"
source = replace_span(
    source,
    required_probe_start,
    validate_start,
    "",
    owner="name-based probe-count policy",
)

new_validate = '''def validate_substantive_verdict(\n    verdict: dict[str, Any],\n    diff: str,\n    changed_paths: Sequence[str] = (),\n    *,\n    truncated: bool = False,\n) -> None:\n    """Reject formal verdicts unless their changed-side evidence is complete.\n\n    APPROVE is an exact finite-set completeness claim, not a thresholded score:\n    on an untruncated diff, reviewed-line locations and falsified probe locations\n    must each equal the set of every changed-side location. REQUEST_CHANGES uses\n    a confirmed probe at a published finding location as its blocking witness.\n    ``changed_paths`` is retained for API compatibility but does not drive any\n    filename-based evidence allocation.\n    """\n    del changed_paths\n    decision = str(verdict.get("decision") or "").lower()\n    if decision == "comment":\n        return\n    if decision not in {"approve", "request_changes"}:\n        raise NoemaModelOutputError("Noema formal verdict decision is unsupported")\n    if decision == "approve" and truncated:\n        raise NoemaModelOutputError(\n            "Noema approve requires complete untruncated diff evidence"\n        )\n\n    locations = changed_diff_locations(diff)\n    if not locations:\n        raise RuntimeError("Noema formal verdict requires parseable changed-line evidence")\n\n    reviewed_lines = verdict.get("reviewed_lines")\n    if not isinstance(reviewed_lines, list) or not reviewed_lines:\n        raise NoemaModelOutputError("Noema formal verdict requires reviewed changed-line evidence")\n    reviewed_locations: set[tuple[str, int, str]] = set()\n    for index, reviewed in enumerate(reviewed_lines, start=1):\n        if not isinstance(reviewed, dict):\n            raise NoemaModelOutputError(f"Noema reviewed line {index} must be an object")\n        location = (reviewed.get("path"), reviewed.get("line"), reviewed.get("side"))\n        if location not in locations:\n            raise NoemaModelOutputError(f"Noema reviewed line {index} is not an exact changed-side line")\n        analysis = reviewed.get("analysis")\n        if not isinstance(analysis, str) or not analysis.strip():\n            raise NoemaModelOutputError(f"Noema reviewed line {index} requires concrete analysis")\n        reviewed_locations.add((str(location[0]), int(location[1]), str(location[2])))\n\n    if decision == "approve" and reviewed_locations != locations:\n        raise NoemaModelOutputError(\n            "Noema approve requires reviewed evidence for every changed-side line"\n        )\n\n    validation = verdict.get("adversarial_validation")\n    if not isinstance(validation, dict):\n        raise NoemaModelOutputError("Noema formal verdict requires adversarial_validation")\n    status = validation.get("status")\n    expected_status = "passed" if decision == "approve" else "failed"\n    if status != expected_status:\n        raise NoemaModelOutputError(\n            f"Noema {decision} requires adversarial_validation.status={expected_status}"\n        )\n    residual_risk = validation.get("residual_risk")\n    if not isinstance(residual_risk, str) or not residual_risk.strip():\n        raise NoemaModelOutputError("Noema adversarial validation requires residual_risk")\n    probes = validation.get("probes")\n    if not isinstance(probes, list):\n        raise NoemaModelOutputError("Noema adversarial validation probes must be a list")\n\n    confirmed: set[tuple[str, int, str]] = set()\n    probe_locations: set[tuple[str, int, str]] = set()\n    identities: set[tuple[Any, ...]] = set()\n    for index, probe in enumerate(probes, start=1):\n        if not isinstance(probe, dict):\n            raise NoemaModelOutputError(f"Noema adversarial probe {index} must be an object")\n        location = (probe.get("path"), probe.get("line"), probe.get("side"))\n        if location not in locations:\n            raise NoemaModelOutputError(f"Noema adversarial probe {index} is not an exact changed-side line")\n        for field in ("hypothesis", "attack_or_counterexample", "evidence"):\n            value = probe.get(field)\n            if not isinstance(value, str) or not value.strip():\n                raise NoemaModelOutputError(f"Noema adversarial probe {index} requires {field}")\n        outcome = probe.get("outcome")\n        if outcome not in {"falsified", "confirmed"}:\n            raise NoemaModelOutputError(\n                f"Noema adversarial probe {index} outcome must be falsified or confirmed"\n            )\n        normalized_location = (\n            str(probe["path"]), int(probe["line"]), str(probe["side"])\n        )\n        identity = (\n            *normalized_location,\n            probe["hypothesis"].strip().casefold(),\n            probe["attack_or_counterexample"].strip().casefold(),\n        )\n        if identity in identities:\n            raise NoemaModelOutputError(f"Noema adversarial probe {index} duplicates an earlier probe")\n        identities.add(identity)\n        probe_locations.add(normalized_location)\n        if outcome == "confirmed":\n            confirmed.add(normalized_location)\n\n    if decision == "approve":\n        if confirmed:\n            raise NoemaModelOutputError("Noema approve cannot contain a confirmed adversarial probe")\n        if probe_locations != locations:\n            raise NoemaModelOutputError(\n                "Noema approve requires a falsified adversarial probe for every changed-side line"\n            )\n    if decision == "request_changes":\n        finding_locations = {\n            (\n                str(finding.get("file") or ""),\n                finding.get("line"),\n                str(finding.get("side") or ""),\n            )\n            for finding in verdict.get("findings") or []\n            if isinstance(finding, dict)\n        }\n        if not confirmed or not confirmed.intersection(finding_locations):\n            raise NoemaModelOutputError(\n                "Noema request_changes requires a confirmed probe on a published finding"\n            )\n\n\n'''
source = replace_span(
    source,
    validate_start,
    "def truncate_text(text: str, limit: int) -> str:\n",
    new_validate,
    owner="formal verdict policy",
)

repair_deadline_start = "@contextlib.contextmanager\ndef _repair_wall_clock_deadline(seconds: float):\n"
classify_start = "def _classify_attempt_outcome(exc: BaseException) -> str:\n"
source = replace_span(
    source,
    repair_deadline_start,
    classify_start,
    "",
    owner="network repair deadline and retry classes",
)

new_classify = '''def _classify_attempt_outcome(exc: BaseException) -> str:\n    """Return a stable single-attempt outcome class for telemetry."""\n    if isinstance(exc, NoemaModelOutputError):\n        return "malformed_output"\n    if isinstance(exc, (urllib.error.URLError, http.client.HTTPException, OSError)):\n        return "transport_error"\n    return "runtime_error"\n\n\n'''
source = replace_span(
    source,
    classify_start,
    "def call_llm(\n",
    new_classify,
    owner="attempt classifier",
)

new_call = '''def call_llm(\n    repo: str,\n    number: int,\n    pr: dict[str, Any],\n    diff: str,\n    truncated: bool,\n    expected_head: str,\n    review_context: str = "",\n    changed_paths: Sequence[str] = (),\n) -> dict[str, Any]:\n    """Call the central orchestrator exactly once and fail closed on bad evidence.\n\n    This caller does not allocate sampling temperature, token budget, timeout,\n    retry count, or fallback order. Those decisions belong to the central\n    orchestrator only when backed by its governed evidence. A malformed or\n    failed response therefore ends this review attempt; the caller never\n    performs an ad-hoc second network/model attempt.\n    """\n    del expected_head\n    api_url = os.environ.get("NOEMA_LLM_API_URL", "").strip()\n    api_key = os.environ.get("NOEMA_LLM_API_KEY", "").strip()\n    model = os.environ.get("NOEMA_LLM_MODEL", "").strip()\n    if not api_url or not api_key:\n        raise RuntimeError(\n            "Noema LLM review unavailable: NOEMA_LLM_API_URL or "\n            "NOEMA_LLM_API_KEY is not configured."\n        )\n    if model != "orchestrator/free":\n        raise RuntimeError("Noema LLM review requires model pool orchestrator/free")\n    reject_private_llm_url(api_url)\n\n    allowed_locations = [\n        {"path": path, "line": line, "side": side}\n        for path, line, side in sorted(changed_diff_locations(diff))\n    ]\n    location_example = (\n        allowed_locations[0]\n        if allowed_locations\n        else {"path": "path", "line": 0, "side": "RIGHT"}\n    )\n    prompt = {\n        "role": "user",\n        "content": "\\n".join(\n            [\n                "You are Noema, an independent pull request reviewer for ContextualWisdomLab.",\n                "Review the PR diff plus the additional changed-file and review-thread context for correctness, security, maintainability, and behavioral regressions.",\n                "Return only JSON with this shape:",\n                json.dumps(\n                    {\n                        "decision": "approve|request_changes|comment",\n                        "summary": "...",\n                        "reviewed_lines": [{**location_example, "analysis": "..."}],\n                        "adversarial_validation": {\n                            "status": "passed|failed",\n                            "residual_risk": "...",\n                            "probes": [\n                                {\n                                    **location_example,\n                                    "hypothesis": "...",\n                                    "attack_or_counterexample": "...",\n                                    "evidence": "observed or source-traced result",\n                                    "outcome": "falsified|confirmed",\n                                }\n                            ],\n                        },\n                        "findings": [\n                            {\n                                "severity": "high|medium|low",\n                                "file": location_example["path"],\n                                "line": location_example["line"],\n                                "side": location_example["side"],\n                                "message": "...",\n                            }\n                        ],\n                    },\n                    separators=(",", ":"),\n                ),\n                "APPROVE is permitted only when reviewed_lines and falsified adversarial probes cover every exact changed-side location in the supplied, untruncated diff. If the diff is truncated or evidence is incomplete, do not APPROVE; fail closed to COMMENT or REQUEST_CHANGES with concrete evidence. REQUEST_CHANGES requires a confirmed probe at a published finding location.",\n                "Use request_changes only for blocking, concrete issues. A generic no-issues statement is not review evidence.",\n                f"Repository: {repo}",\n                f"PR: #{number}",\n                f"Title: {pr.get('title') or ''}",\n                f"Head SHA: {pr.get('headRefOid') or ''}",\n                f"Diff truncated: {truncated}",\n                "Additional context:",\n                review_context or "No additional context was available.",\n                "Diff:",\n                diff,\n            ]\n        ),\n    }\n    payload = {\n        "model": model,\n        "response_format": _noema_verdict_response_format(),\n        "messages": [\n            {"role": "system", "content": "Return strict JSON only. Do not include markdown."},\n            prompt,\n        ],\n    }\n    request = urllib.request.Request(\n        api_url,\n        data=json.dumps(payload).encode("utf-8"),\n        headers={\n            "authorization": f"Bearer {api_key}",\n            "content-type": "application/json",\n        },\n        method="POST",\n    )\n    opener = urllib.request.build_opener(NoRedirectHandler())\n    attempt_started = time.monotonic()\n    phase_reached = "connecting"\n    served_model: str | None = None\n    try:\n        with opener.open(request) as response:  # nosec B310\n            phase_reached = "reading"\n            raw_bytes = response.read()\n        phase_reached = "decoding"\n        raw = decode_llm_response_body(raw_bytes)\n        served_model = _extract_served_model(raw)\n        content = extract_llm_message_content(raw)\n        verdict = extract_json_object(content)\n        phase_reached = "validating"\n        decision = str(verdict.get("decision") or "").strip().lower()\n        if decision not in {"approve", "request_changes", "comment"}:\n            raise NoemaModelOutputError(\n                f"Noema LLM returned unsupported decision: {decision!r}"\n            )\n        summary = verdict.get("summary")\n        if not isinstance(summary, str) or not summary.strip():\n            raise NoemaModelOutputError(\n                "Noema LLM response did not contain a substantive summary"\n            )\n        findings = verdict.get("findings")\n        if not isinstance(findings, list) or any(\n            not isinstance(finding, dict) for finding in findings\n        ):\n            raise NoemaModelOutputError(\n                "Noema LLM response findings must be a list of objects"\n            )\n        for finding in findings:\n            if (\n                finding.get("severity") not in {"high", "medium", "low"}\n                or not isinstance(finding.get("file"), str)\n                or not finding["file"].strip()\n                or type(finding.get("line")) is not int\n                or finding["line"] <= 0\n                or finding.get("side") not in {"RIGHT", "LEFT"}\n                or not isinstance(finding.get("message"), str)\n                or not finding["message"].strip()\n            ):\n                raise NoemaModelOutputError(\n                    "Noema LLM response contained a malformed finding"\n                )\n        if decision == "request_changes" and not findings:\n            raise NoemaModelOutputError(\n                "Noema LLM request_changes response did not contain a substantive finding"\n            )\n        validate_substantive_verdict(\n            verdict, diff, changed_paths, truncated=truncated\n        )\n    except (RuntimeError, urllib.error.URLError, http.client.HTTPException, OSError) as exc:\n        attempt_elapsed = time.monotonic() - attempt_started\n        outcome = _classify_attempt_outcome(exc)\n        current_failure = _stable_failure_diagnostic(exc)\n        served_model_note = served_model or "unknown"\n        print(\n            f"::warning::Noema single attempt outcome={outcome} "\n            f"phase={phase_reached} duration={attempt_elapsed:.1f}s "\n            f"served_model={served_model_note}; failed closed without caller retry."\n        )\n        if isinstance(exc, NoemaModelOutputError):\n            raise\n        if isinstance(exc, (urllib.error.URLError, http.client.HTTPException, OSError)):\n            raise NoemaTransportError(\n                "Noema single-attempt transport failed closed; "\n                f"failure: {type(exc).__name__}: {current_failure}; "\n                f"duration={attempt_elapsed:.1f}s, phase={phase_reached}, "\n                f"served_model={served_model_note}"\n            ) from exc\n        raise\n    attempt_elapsed = time.monotonic() - attempt_started\n    print(\n        f"::notice::Noema single attempt outcome=success "\n        f"duration={attempt_elapsed:.1f}s served_model={served_model or 'unknown'}"\n    )\n    return verdict\n\n\n'''
source = replace_span(
    source,
    "def call_llm(\n",
    "def format_findings(findings: Any) -> list[str]:\n",
    new_call,
    owner="single-attempt Noema LLM path",
)

if any(
    forbidden in source
    for forbidden in (
        "NOEMA_REPAIR_DEADLINE_SECONDS",
        "_repair_wall_clock_deadline",
        "_required_probe_count",
        '"temperature": 0',
        "changed_file_is_material",
        "NoemaRepairDeadlineExceeded",
    )
):
    raise RuntimeError("forbidden heuristic owner survived production repair")

GATE.write_text(source)

TELEMETRY_TEST.write_text('''"""Regression coverage for Noema's single-attempt governed transport."""\n\nimport json\n\nimport pytest\n\nfrom scripts.ci import noema_review_gate as gate\n\n\nDIFF = """diff --git a/README.md b/README.md\nindex 1111111..2222222 100644\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n"""\n\n\ndef _comment_verdict() -> dict:\n    return {"decision": "comment", "summary": "Evidence is incomplete.", "findings": []}\n\n\nclass _JsonResponse:\n    def __init__(self, body: dict):\n        self._body = body\n\n    def __enter__(self):\n        return self\n\n    def __exit__(self, *_args):\n        return None\n\n    def read(self):\n        return json.dumps(self._body).encode()\n\n\ndef _configure(monkeypatch):\n    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")\n    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")\n    monkeypatch.setenv("NOEMA_LLM_MODEL", "orchestrator/free")\n\n\ndef test_response_format_is_structural_without_probe_cardinality_or_sampling(monkeypatch):\n    _configure(monkeypatch)\n    head_sha = "a" * 40\n    requests = []\n\n    def open_response(_opener, request, **_kwargs):\n        requests.append(request)\n        return _JsonResponse(\n            {"model": "provider/model", "choices": [{"message": {"content": json.dumps(_comment_verdict())}}]}\n        )\n\n    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", open_response)\n    verdict = gate.call_llm(\n        "owner/repo", 7, {"title": "test", "headRefOid": head_sha}, DIFF, False, head_sha\n    )\n    assert verdict == _comment_verdict()\n    assert len(requests) == 1\n    payload = json.loads(requests[0].data)\n    assert payload["model"] == "orchestrator/free"\n    assert "temperature" not in payload\n    probes = payload["response_format"]["json_schema"]["schema"]["properties"][\n        "adversarial_validation"\n    ]["properties"]["probes"]\n    assert "minItems" not in probes\n\n\ndef test_wrong_model_pool_fails_closed_before_transport(monkeypatch):\n    _configure(monkeypatch)\n    monkeypatch.setenv("NOEMA_LLM_MODEL", "provider/model")\n    with pytest.raises(RuntimeError, match="requires model pool orchestrator/free"):\n        gate.call_llm(\n            "owner/repo", 7, {"title": "test", "headRefOid": "b" * 40}, DIFF, False, "b" * 40\n        )\n\n\ndef test_malformed_model_output_is_not_retried_by_noema(monkeypatch, capsys):\n    _configure(monkeypatch)\n    calls = 0\n\n    def open_response(_opener, _request, **_kwargs):\n        nonlocal calls\n        calls += 1\n        return _JsonResponse({"choices": [{"message": {"content": "not-json"}}]})\n\n    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", open_response)\n    with pytest.raises(gate.NoemaModelOutputError):\n        gate.call_llm(\n            "owner/repo", 7, {"title": "test", "headRefOid": "c" * 40}, DIFF, False, "c" * 40\n        )\n    assert calls == 1\n    assert "failed closed without caller retry" in capsys.readouterr().out\n\n\ndef test_served_model_telemetry_reads_envelope_model_field(monkeypatch, capsys):\n    _configure(monkeypatch)\n    monkeypatch.setattr(\n        gate.urllib.request.OpenerDirector,\n        "open",\n        lambda *_a, **_k: _JsonResponse(\n            {"model": "some-provider/some-model-v1", "choices": [{"message": {"content": json.dumps(_comment_verdict())}}]}\n        ),\n    )\n    gate.call_llm(\n        "owner/repo", 7, {"title": "test", "headRefOid": "d" * 40}, DIFF, False, "d" * 40\n    )\n    notice = capsys.readouterr().out\n    assert "Noema single attempt outcome=success" in notice\n    assert "served_model=some-provider/some-model-v1" in notice\n\n\n@pytest.mark.parametrize(\n    ("raw", "expected"),\n    [\n        ('{"model": "provider/model-x", "choices": []}', "provider/model-x"),\n        ('{"choices": []}', None),\n        ('{"model": 5, "choices": []}', None),\n        ("not json", None),\n    ],\n)\ndef test_extract_served_model_is_best_effort(raw, expected):\n    assert gate._extract_served_model(raw) == expected\n\n\ndef test_classify_attempt_outcome_preserves_failure_family():\n    import urllib.error\n\n    assert gate._classify_attempt_outcome(gate.NoemaModelOutputError("bad")) == "malformed_output"\n    assert gate._classify_attempt_outcome(urllib.error.URLError("boom")) == "transport_error"\n    assert gate._classify_attempt_outcome(RuntimeError("boom")) == "runtime_error"\n''')


def append_once(path: Path, marker: str, block: str) -> None:
    if not path.exists():
        raise RuntimeError(f"required traceability document missing: {path}")
    text = path.read_text()
    if marker not in text:
        path.write_text(text.rstrip() + "\n\n" + block.rstrip() + "\n")


append_once(
    ROOT / "docs/doctoring/noema-repair-attempt-telemetry.md",
    "NOEMA-NO-HEURISTICS-2026-09-02",
    '''<!-- NOEMA-NO-HEURISTICS-2026-09-02 -->\n## 2026-09-02 no-heuristics causal repair\n\nExact-head RCA found three caller-owned decision heuristics in `noema_review_gate.py`: an unsupported 900-second repair deadline plus automatic second model call, repository-authored `temperature=0`, and a filename-classified 2-versus-1 adversarial-probe floor. None was identified by a statistical model, authoritative standard, or validated experiment. Noema now makes one `orchestrator/free` request with no caller-authored sampling/timeout/retry allocation and fails closed on malformed or failed transport. APPROVE no longer uses a count threshold: it is the finite-set equality claim that reviewed locations and falsified probe locations each cover every changed-side location in an untruncated diff. Truncation therefore cannot authorize approval. REQUEST_CHANGES retains only the logical witness requirement that a confirmed probe coincide with a published finding.\n\nThe automatic network retry was also inconsistent with HTTP semantics for a POST unless the client knows the operation is idempotent or can establish that the original request was not applied. Noema has no such evidence for an LLM generation request, so the caller does not retry it.\n\nReference (APA 7): Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics (RFC 9110)*. Internet Engineering Task Force. https://doi.org/10.17487/RFC9110\n''',
)
append_once(
    ROOT / "docs/product-technical-gap-baseline.md",
    "GAP-NOEMA-HEURISTIC-EVIDENCE-2026-09-02",
    '''<!-- GAP-NOEMA-HEURISTIC-EVIDENCE-2026-09-02 -->\n### Gap closure: Noema caller-owned inference/evidence heuristics (2026-09-02)\n\n- **Causal owner:** `scripts/ci/noema_review_gate.py`.\n- **Live gap:** a fixed repair deadline/second LLM call, fixed sampling temperature, and filename-dependent probe-count floor affected review evidence and approval without an identified model or standard.\n- **Repair:** one `orchestrator/free` request, no caller sampling/timeout/retry allocation, exact changed-location set completeness for APPROVE, and fail-closed approval on truncated evidence.\n- **Executable provenance:** `tests/test_noema_no_heuristic_evidence_policy.py` plus `tests/test_noema_repair_attempt_telemetry.py`; exact-head Actions must be green before merge.\n- **Basis:** finite-set equality for evidence completeness; RFC 9110 automatic-retry constraints for non-idempotent requests. Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics (RFC 9110)*. Internet Engineering Task Force. https://doi.org/10.17487/RFC9110\n''',
)
append_once(
    ROOT / "docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md",
    "ADR0003-NOEMA-NO-HEURISTICS-2026-09-02",
    '''<!-- ADR0003-NOEMA-NO-HEURISTICS-2026-09-02 -->\n### 2026-09-02 amendment: caller inference allocation and review evidence\n\nNoema callers MUST request exactly `orchestrator/free` and MUST NOT impose a repository-authored temperature, inference timeout, automatic model retry count, model fallback order, or filename-derived evidence quota. When a model response or transport fails and no independently governed retry design is available, the caller fails closed. APPROVE requires complete evidence over the finite set of exact changed-side locations and is forbidden when the supplied diff is truncated. This replaces the prior 2/1 probe quota and 900-second corrective retry with an executable mathematical completeness contract.\n\nReference (APA 7): Fielding, R., Nottingham, M., & Reschke, J. (2022). *HTTP semantics (RFC 9110)*. Internet Engineering Task Force. https://doi.org/10.17487/RFC9110\n''',
)
append_once(
    ROOT / "CHANGELOG.md",
    "NOEMA-NO-HEURISTICS-CHANGELOG-2026-09-02",
    '''<!-- NOEMA-NO-HEURISTICS-CHANGELOG-2026-09-02 -->\n- 2026-09-02: Noema review now fails closed without caller-owned sampling, timeout, automatic network/model retry, or filename-based probe quotas; APPROVE uses exact changed-side set completeness and is prohibited for truncated diff evidence.\n''',
)

print("PR #1672 no-heuristics owner repair applied")
