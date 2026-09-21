"""All-429 sidecar preflight is routed into ADR-0031's bounded re-dispatch (#2148).

Fixtures are synthetic but follow the measured ``strix-plain-chat-preflight-v2``
schema of the 17 real failures (late-life-anxiety-reanalysis#218, job
106085557453): every route ``status=rejected`` with ``http_status=429`` and no
``retry_after_s``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import noema_preflight_capacity as capacity
from scripts.ci import noema_review_gate as gate

HEAD = "e2393877" + "0" * 32


def _route(index: int, **overrides: object) -> dict[str, object]:
    """Return one rejected-429 route row in the launcher's sanitized schema."""
    row: dict[str, object] = {
        "agent_id": f"openrouter-{index}",
        "provider": "openrouter",
        "model": f"vendor/model-{index}:free",
        "attempts": 1,
        "status": "rejected",
        "error_type": "HTTPError",
        "http_status": 429,
    }
    row.update(overrides)
    return row


def _report(routes: list[dict[str, object]], **overrides: object) -> dict[str, object]:
    """Return a failed preflight report shaped like the measured 5-candidate case."""
    report: dict[str, object] = {
        "contract": "strix-plain-chat-preflight-v2",
        "candidate_count": len(routes),
        "probed_count": len(routes),
        "ready_count": 0,
        "deferred_count": 0,
        "rejected_count": len(routes),
        "skipped_count": 0,
        "postponed_probed_count": 3,
        "target_ready": 8,
        "probe_budget": 12,
        "account_skip_after_429": 2,
        "escalations_used": 0,
        "escalation_budget": 4,
        "routes": routes,
    }
    report.update(overrides)
    return report


def _all_429(count: int = 5) -> dict[str, object]:
    """Return the measured all-429 failure shape."""
    return _report([_route(index) for index in range(count)])


def _run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: object | None,
         *, attempt: str = "0", raw: str | None = None) -> dict[str, str]:
    """Run the CLI against one preflight file and return its GitHub outputs."""
    report_path = tmp_path / "contextual-orchestrator-preflight.json"
    if raw is not None:
        report_path.write_text(raw, encoding="utf-8")
    elif payload is not None:
        report_path.write_text(json.dumps(payload), encoding="utf-8")
    output_path = tmp_path / "github_output"
    output_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    monkeypatch.setenv("NOEMA_TRANSPORT_RETRY_ATTEMPT", attempt)
    assert capacity.main(["--preflight-report", str(report_path), "--expected-head", HEAD]) == 0
    outputs: dict[str, str] = {}
    for line in output_path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        outputs[key] = value
    return outputs


@pytest.mark.parametrize("count", [4, 5])
def test_measured_all_429_preflight_is_capacity_and_eligible(tmp_path, monkeypatch, count):
    """Both measured failure shapes schedule the same bounded re-dispatch."""
    outputs = _run(tmp_path, monkeypatch, _all_429(count))
    expected_delay = gate.transport_redispatch_delay_seconds(
        transport_retry_attempt=0, head_sha=HEAD
    )
    assert outputs == {
        "transport_capacity_unavailable": "true",
        "transport_retry_eligible": "true",
        "transport_http_status": "429",
        "provider_attempt_count": str(count),
        "transport_retry_delay_seconds": str(expected_delay),
        "transport_retry_next_attempt": "1",
    }
    assert gate.TRANSPORT_REDISPATCH_JITTER_MIN_SECONDS <= expected_delay
    assert expected_delay <= gate.TRANSPORT_REDISPATCH_JITTER_MAX_SECONDS


def test_second_attempt_advances_the_shared_counter(tmp_path, monkeypatch):
    """The preflight path consumes the same NOEMA_TRANSPORT_RETRY_ATTEMPT counter."""
    outputs = _run(tmp_path, monkeypatch, _all_429(), attempt="1")
    assert outputs["transport_retry_eligible"] == "true"
    assert outputs["transport_retry_next_attempt"] == "2"


def test_exhausted_attempts_stay_capacity_but_not_eligible(tmp_path, monkeypatch, capsys):
    """At the ADR-0031 bound the run fails closed with no further re-dispatch."""
    attempt = str(gate.MAX_TRANSPORT_REDISPATCH_ATTEMPTS)
    outputs = _run(tmp_path, monkeypatch, _all_429(), attempt=attempt)
    assert outputs["transport_capacity_unavailable"] == "true"
    assert outputs["transport_retry_eligible"] == "false"
    assert "transport_retry_delay_seconds" not in outputs
    assert "transport_retry_next_attempt" not in outputs
    assert "Review remains required" in capsys.readouterr().out


def test_in_cap_retry_after_is_honored_as_the_longest_stated_wait(tmp_path, monkeypatch):
    """A provider Retry-After within the existing cap replaces the jitter."""
    routes = [_route(0, retry_after_s=5), _route(1, retry_after_s=40), _route(2)]
    outputs = _run(tmp_path, monkeypatch, _report(routes))
    assert outputs["transport_retry_delay_seconds"] == "40"
    assert outputs["transport_retry_eligible"] == "true"


@pytest.mark.parametrize("value", [0, gate.TRANSPORT_REDISPATCH_RETRY_AFTER_MAX_SECONDS + 1, "5", True])
def test_out_of_cap_retry_after_falls_back_to_jitter(tmp_path, monkeypatch, value):
    """An out-of-range or non-int Retry-After neither widens the cap nor kills eligibility."""
    outputs = _run(tmp_path, monkeypatch, _report([_route(0, retry_after_s=value), _route(1)]))
    expected_delay = gate.transport_redispatch_delay_seconds(
        transport_retry_attempt=0, head_sha=HEAD
    )
    assert outputs["transport_retry_delay_seconds"] == str(expected_delay)
    assert outputs["transport_retry_eligible"] == "true"


def test_deferred_429_rows_count_as_capacity(tmp_path, monkeypatch):
    """A deferred 429 row is still a capacity answer."""
    routes = [_route(0, status="deferred"), _route(1)]
    outputs = _run(tmp_path, monkeypatch, _report(routes, deferred_count=1))
    assert outputs["transport_capacity_unavailable"] == "true"


def test_nested_primary_attempt_must_also_be_all_429(tmp_path, monkeypatch):
    """A fallback-stage report counts only when its nested primary stage is all-429 too."""
    good = _report([_route(0)], primary_attempt=_all_429(3))
    assert _run(tmp_path, monkeypatch, good)["transport_capacity_unavailable"] == "true"
    bad_primary = _report([_route(1, http_status=404)])
    bad = _report([_route(0)], primary_attempt=bad_primary)
    assert _run(tmp_path, monkeypatch, bad)["transport_capacity_unavailable"] == "false"


NOT_CAPACITY_REPORTS = {
    "404_and_429_mix": _report([_route(0), _route(1, http_status=404)]),
    "500_and_429_mix": _report([_route(0), _route(1, http_status=500)]),
    "remote_disconnected_and_429_mix": _report(
        [_route(0), {k: v for k, v in _route(1, error_type="RemoteDisconnected").items()
                     if k != "http_status"}]
    ),
    "escalation_budget_exhausted": _report(
        [_route(0), {k: v for k, v in _route(1, error_type="escalation_budget_exhausted").items()
                     if k != "http_status"}]
    ),
    "string_429": _report([_route(0, http_status="429")]),
    "bool_status": _report([_route(0, http_status=True)]),
    "ready_route_present": _report([_route(0), _route(1, status="ready")], ready_count=1),
    "ready_row_with_zero_count": _report([_route(0), _route(1, status="ready")]),
    "ready_count_positive": _report([_route(0)], ready_count=1),
    "ready_count_bool": _report([_route(0)], ready_count=False),
    "zero_candidates": _report([], candidate_count=0, probed_count=0),
    "probed_count_missing": {k: v for k, v in _all_429().items() if k != "probed_count"},
    "routes_count_mismatch": _report([_route(0)], probed_count=2),
    "routes_not_list": {**_report([_route(0)]), "routes": {"0": _route(0)}},
    "route_not_dict": _report([_route(0), "429"], probed_count=2),
    "wrong_contract": _report([_route(0)], contract="strix-plain-chat-preflight-v1"),
    "primary_attempt_not_dict": _report([_route(0)], primary_attempt=["x"]),
    "json_list": [_route(0)],
}


@pytest.mark.parametrize("name", sorted(NOT_CAPACITY_REPORTS))
def test_anything_but_all_429_keeps_plain_failure(tmp_path, monkeypatch, name):
    """Non-429 rejections and out-of-contract evidence are never capacity."""
    outputs = _run(tmp_path, monkeypatch, NOT_CAPACITY_REPORTS[name])
    assert outputs == {
        "transport_capacity_unavailable": "false",
        "transport_retry_eligible": "false",
    }


@pytest.mark.parametrize("raw", ["", "   \n", "{not json", "[" * 5000])
def test_empty_or_malformed_report_keeps_plain_failure(tmp_path, monkeypatch, raw):
    """The sidecar truncates the report at start; early failures leave it empty."""
    outputs = _run(tmp_path, monkeypatch, None, raw=raw)
    assert outputs["transport_capacity_unavailable"] == "false"
    assert outputs["transport_retry_eligible"] == "false"


def test_non_utf8_report_keeps_plain_failure(tmp_path, monkeypatch):
    """Undecodable bytes are not capacity evidence."""
    (tmp_path / "contextual-orchestrator-preflight.json").write_bytes(b"\xff\xfe{")
    outputs = _run(tmp_path, monkeypatch, None)
    assert outputs["transport_capacity_unavailable"] == "false"


def test_missing_report_keeps_plain_failure(tmp_path, monkeypatch):
    """A sidecar that failed before creating evidence is not capacity."""
    outputs = _run(tmp_path, monkeypatch, None)
    assert outputs["transport_capacity_unavailable"] == "false"


def test_directory_report_path_keeps_plain_failure(tmp_path, monkeypatch):
    """An unreadable report path is not capacity."""
    (tmp_path / "contextual-orchestrator-preflight.json").mkdir()
    outputs = _run(tmp_path, monkeypatch, None)
    assert outputs["transport_capacity_unavailable"] == "false"


def test_oversized_report_keeps_plain_failure(tmp_path, monkeypatch):
    """The classifier reads a bounded prefix and rejects anything larger."""
    padded = _all_429()
    padded["padding"] = "x" * capacity.MAX_PREFLIGHT_REPORT_BYTES
    outputs = _run(tmp_path, monkeypatch, padded)
    assert outputs["transport_capacity_unavailable"] == "false"


def test_noncanonical_head_emits_no_redispatch_outputs(tmp_path, monkeypatch, capsys):
    """A malformed expected head cannot key a delay or a continuation."""
    report_path = tmp_path / "preflight.json"
    report_path.write_text(json.dumps(_all_429()), encoding="utf-8")
    output_path = tmp_path / "github_output"
    output_path.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_path))
    argv = ["--preflight-report", str(report_path), "--expected-head", HEAD.upper()]
    assert capacity.main(argv) == 0
    assert output_path.read_text(encoding="utf-8") == ""
    assert "canonical" in capsys.readouterr().out


def test_eligible_run_prints_a_capacity_notice(tmp_path, monkeypatch, capsys):
    """The job log names the preflight capacity class and the scheduled attempt."""
    _run(tmp_path, monkeypatch, _all_429())
    out = capsys.readouterr().out
    assert "::notice::" in out
    assert "all-429" in out
    assert f"attempt 1/{gate.MAX_TRANSPORT_REDISPATCH_ATTEMPTS}" in out


def test_workflow_invocation_needs_only_the_standard_library(tmp_path):
    """The classify step runs on the runner's bare python3 after the sidecar failed.

    defusedxml is installed only by the later HWP reader step, which is skipped
    once provisioning fails, so the script's import closure must be stdlib-only.
    """
    script = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "noema_preflight_capacity.py"
    report_path = tmp_path / "contextual-orchestrator-preflight.json"
    report_path.write_text(json.dumps(_all_429()), encoding="utf-8")
    output_path = tmp_path / "github_output"
    output_path.write_text("", encoding="utf-8")
    wrapper = (
        "import runpy, sys\n"
        "sys.modules['defusedxml'] = None\n"
        "sys.argv = sys.argv[1:]\n"
        "runpy.run_path(sys.argv[0], run_name='__main__')\n"
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "GITHUB_OUTPUT": str(output_path),
        "NOEMA_TRANSPORT_RETRY_ATTEMPT": "0",
    }
    result = subprocess.run(
        [sys.executable, "-c", wrapper, str(script),
         "--preflight-report", str(report_path), "--expected-head", HEAD],
        cwd=tmp_path, env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    written = output_path.read_text(encoding="utf-8")
    assert "transport_capacity_unavailable=true\n" in written
    assert "transport_retry_eligible=true\n" in written
    assert "transport_retry_next_attempt=1\n" in written
