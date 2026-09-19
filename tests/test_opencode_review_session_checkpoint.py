"""Tests for host-managed OpenCode same-model session checkpoints."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.ci.opencode_review_session_checkpoint import (
    append_continuation_to_prompt,
    build_continuation_appendix,
    classify_termination,
    continuation_budget_remaining,
    missing_required_outputs,
    record_attempt_checkpoint,
    summarize_partial_assistant,
)


def _export_with_text(text: str) -> str:
    return json.dumps(
        {
            "messages": [
                {
                    "info": {"role": "assistant"},
                    "parts": [{"type": "text", "text": text}],
                }
            ]
        }
    )


def test_summarize_partial_assistant_never_returns_raw_text(tmp_path: Path) -> None:
    """Checkpoint metadata stays digest-only."""
    export_path = tmp_path / "export.json"
    export_path.write_text(
        _export_with_text("secret partial body\nopencode-review-control-v1"),
        encoding="utf-8",
    )
    summary = summarize_partial_assistant(export_path)
    assert summary["assistant_text_present"] is True
    assert summary["has_control_sentinel"] is True
    assert "secret" not in json.dumps(summary)


def test_missing_required_outputs_lists_absent_markers() -> None:
    """Incomplete control output records which contract markers are still missing."""
    missing = missing_required_outputs("partial progress only")
    assert "opencode-review-control-v1" in missing
    assert "adversarial_validation" in missing


def test_classify_termination_detects_provider_fatal(tmp_path: Path) -> None:
    """Fatal provider signatures classify as bounded termination reasons."""
    json_path = tmp_path / "run.jsonl"
    json_path.write_text(
        '{"type":"error","error":{"name":"ContextOverflowError","data":{}}}\n',
        encoding="utf-8",
    )
    reason = classify_termination(
        json_path=json_path,
        export_path=tmp_path / "missing.json",
        exit_code=1,
    )
    assert reason == "provider-fatal"


def test_record_and_continue_preserves_route_evidence(tmp_path: Path) -> None:
    """Same-model retries carry route telemetry without replaying provider bodies."""
    export_path = tmp_path / "export.json"
    export_path.write_text(_export_with_text("in progress"), encoding="utf-8")
    route_path = tmp_path / "route.json"
    route_path.write_text(
        json.dumps(
            {
                "error": {
                    "detail": {
                        "model": "orchestrator/free",
                        "terminal_reason": "rate_limited",
                        "attempts": [
                            {
                                "provider_name": "openrouter",
                                "phase": "connecting",
                                "attempt_number": 1,
                                "provider_status": 429,
                            }
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    record_attempt_checkpoint(
        checkpoint_path=checkpoint_path,
        model_candidate="contextual-orchestrator/orchestrator/free",
        attempt=1,
        head_sha="a" * 40,
        run_id="35401977816",
        run_attempt="1",
        json_path=tmp_path / "run.jsonl",
        export_path=export_path,
        exit_code=1,
        route_evidence_path=route_path,
    )
    appendix = build_continuation_appendix(checkpoint_path, budget=2)
    assert "contextual-orchestrator/orchestrator/free" in appendix
    assert "termination reason" in appendix.casefold()
    assert "route evidence" in appendix.casefold()
    assert "provider_attempt_count=1" in appendix
    assert "in progress" not in appendix


def test_append_continuation_respects_budget(tmp_path: Path) -> None:
    """Continuation budget is explicit and fails closed when exhausted."""
    export_path = tmp_path / "export.json"
    export_path.write_text(_export_with_text("partial"), encoding="utf-8")
    checkpoint_path = tmp_path / "checkpoint.json"
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("base prompt\n", encoding="utf-8")
    for attempt in (1, 2, 3):
        record_attempt_checkpoint(
            checkpoint_path=checkpoint_path,
            model_candidate="contextual-orchestrator/orchestrator/free",
            attempt=attempt,
            head_sha="b" * 40,
            run_id="35452307646",
            run_attempt="1",
            json_path=tmp_path / f"run-{attempt}.jsonl",
            export_path=export_path,
            exit_code=1,
        )
    assert continuation_budget_remaining(checkpoint_path, budget=2) == 0
    before = prompt_path.read_text(encoding="utf-8")
    remaining = append_continuation_to_prompt(prompt_path, checkpoint_path, budget=2)
    assert remaining == 0
    assert prompt_path.read_text(encoding="utf-8") == before


def test_cli_record_emits_bounded_json(tmp_path: Path) -> None:
    """The checkpoint CLI prints only bounded metadata to stdout."""
    export_path = tmp_path / "export.json"
    export_path.write_text(_export_with_text("partial"), encoding="utf-8")
    checkpoint_path = tmp_path / "checkpoint.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ci/opencode_review_session_checkpoint.py",
            "record",
            "--checkpoint",
            str(checkpoint_path),
            "--model-candidate",
            "contextual-orchestrator/orchestrator/free",
            "--attempt",
            "1",
            "--head-sha",
            "c" * 40,
            "--run-id",
            "35452307646",
            "--run-attempt",
            "1",
            "--json-path",
            str(tmp_path / "run.jsonl"),
            "--export-path",
            str(export_path),
            "--exit-code",
            "1",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    payload = json.loads(completed.stdout.strip())
    assert "termination_reason" in payload
    assert "partial" not in completed.stdout
