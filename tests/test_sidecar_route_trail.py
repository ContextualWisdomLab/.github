"""Regression tests for the sidecar candidate-trail summary."""

from __future__ import annotations

from pathlib import Path

from scripts.ci import sidecar_route_trail as trail

REQ = "b838563db7f541a7a32ba4e335291bd9"

# Synthetic replica of Actions run 36166447802's serving trail (no secrets,
# no request content): preflight probes carry request_id=-, the serving
# request tries six ready NVIDIA routes before the two deferred OpenRouter
# routes that answer 429.
RUN_36166447802_SHAPE = f"""\
provider_discovery_failed provider=bytez code=http_status_500
2026-09-25 23:27:39,816 provider_attempt agent_id=openrouter_ling_fin_free model=m attempt=1/1 request_id=-
2026-09-25 23:27:39,862 provider_attempt_failed agent_id=openrouter_ling_fin_free model=m attempt=1 error_type=HTTPError transient=True provider_status=429 request_id=- error_message=<omitted>
2026-09-25 23:38:20,229 provider_attempt agent_id=nvidia_nim_gemma_4_31b model=m attempt=1/1 request_id={REQ}
2026-09-25 23:42:29,182 provider_attempt agent_id=nvidia_nim_gemma_4_31b model=m attempt=1/1 request_id={REQ}
2026-09-25 23:47:07,175 provider_attempt_failed agent_id=nvidia_nim_gemma_4_31b model=m attempt=1 error_type=RemoteDisconnected transient=True provider_status=None request_id={REQ} error_message=<omitted>
2026-09-25 23:47:07,175 provider_one_shot_call_failed agent_id=nvidia_nim_gemma_4_31b model=m attempts=1 final_error_type=RemoteDisconnected transient=True request_id={REQ}
2026-09-25 23:47:07,176 circuit_failure agent_id=nvidia_nim_gemma_4_31b failures=1.0 threshold=3
2026-09-25 23:47:07,190 provider_attempt agent_id=nvidia_nim_sub_gemma_4_31b model=m attempt=1/1 request_id={REQ}
2026-09-25 23:52:09,251 provider_attempt_failed agent_id=nvidia_nim_sub_gemma_4_31b model=m attempt=1 error_type=HTTPError transient=True provider_status=504 request_id={REQ} error_message=<omitted>
2026-09-25 23:52:09,321 provider_attempt agent_id=nvidia_nim_llama_vision model=m attempt=1/1 request_id={REQ}
2026-09-25 23:52:21,097 circuit_failure agent_id=nvidia_nim_llama_vision failures=1.0 threshold=3
2026-09-25 23:55:41,514 provider_attempt agent_id=openrouter_ling_fin_free model=m attempt=1/1 request_id={REQ}
2026-09-25 23:55:41,625 provider_attempt_failed agent_id=openrouter_ling_fin_free model=m attempt=1 error_type=HTTPError transient=True provider_status=429 request_id={REQ} error_message=<omitted>
2026-09-25 23:55:41,625 circuit_failure agent_id=openrouter_ling_fin_free failures=1.0 threshold=3
"""


def test_run_shape_reports_every_candidate_not_only_the_final_429() -> None:
    """The annotation lists each serving candidate in order with its own outcome."""

    request_id, entries = trail.summarize(RUN_36166447802_SHAPE.splitlines())
    assert request_id == REQ
    assert [e["agent_id"] for e in entries] == [
        "nvidia_nim_gemma_4_31b",
        "nvidia_nim_sub_gemma_4_31b",
        "nvidia_nim_llama_vision",
        "openrouter_ling_fin_free",
    ]
    assert [e["outcome"] for e in entries] == [
        "disconnect",
        "http_504",
        "invalid_response",
        "http_429",
    ]
    line = trail.format_annotation(request_id, entries)
    assert line.startswith("::notice title=SIDECAR_CANDIDATE_TRAIL::request b838563d tried 4 candidate(s)")
    assert "1) nvidia_nim_gemma_4_31b disconnect after 526.9s" in line
    assert "2) nvidia_nim_sub_gemma_4_31b http_504 after 302.1s" in line
    assert "3) nvidia_nim_llama_vision invalid_response after 11.8s" in line
    assert "4) openrouter_ling_fin_free http_429 after 0.1s" in line
    assert "over 1041.4s" in line
    assert "Outcomes: disconnect=1, http_429=1, http_504=1, invalid_response=1." in line


def test_failure_outcome_labels_are_bounded() -> None:
    """Transport errors map to fixed labels and never echo arbitrary text."""

    assert trail._failure_outcome({"provider_status": "503"}) == "http_503"
    assert trail._failure_outcome({"error_type": "ReadTimeout"}) == "timeout"
    assert trail._failure_outcome({"error_type": "ConnectionResetError"}) == "disconnect"
    assert trail._failure_outcome({"error_type": "URLError"}) == "urlerror"
    assert trail._failure_outcome({"error_type": "<script>"}) == "transport_error"


def test_preflight_only_and_malformed_lines_yield_nothing() -> None:
    """No serving request id means no annotation; malformed rows are skipped."""

    lines = [
        "garbage",
        "2026-09-25 23:27:39,816 provider_attempt agent_id=Bad-Agent request_id=" + REQ,
        "2026-09-25 23:27:39,816 provider_attempt agent_id=ok_agent request_id=-",
        "2026-09-25 23:27:39,900 circuit_failure agent_id=ok_agent failures=1.0",
        "2026-09-25 23:27:39,900 provider_attempt_failed agent_id=other_agent request_id=" + REQ,
    ]
    assert trail.summarize(lines) is None


def test_unfinished_candidate_and_truncated_listing() -> None:
    """A candidate with no failure keeps a neutral label; long trails are capped."""

    lines = [
        f"2026-09-25 10:00:{i:02d},000 provider_attempt agent_id=agent_{i} request_id={REQ}"
        for i in range(trail.MAX_LISTED_CANDIDATES + 2)
    ]
    request_id, entries = trail.summarize(lines)
    line = trail.format_annotation(request_id, entries)
    assert f"tried {trail.MAX_LISTED_CANDIDATES + 2} candidate(s)" in line
    assert "no_failure_recorded after 0.0s" in line
    assert "... 2 more" in line


def test_main_is_always_non_fatal(tmp_path: Path, capsys) -> None:
    """The CLI prints the annotation when it can and exits 0 in every case."""

    log = tmp_path / "sidecar.stderr.log"
    log.write_text(RUN_36166447802_SHAPE, encoding="utf-8")
    assert trail.main(["prog", str(log)]) == 0
    assert "SIDECAR_CANDIDATE_TRAIL" in capsys.readouterr().out
    assert trail.main(["prog", str(tmp_path / "missing.log")]) == 0
    assert trail.main(["prog"]) == 0
    assert "usage:" in capsys.readouterr().err
    empty = tmp_path / "empty.log"
    empty.write_text("", encoding="utf-8")
    assert trail.main(["prog", str(empty)]) == 0
    assert capsys.readouterr().out == ""
