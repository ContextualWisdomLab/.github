"""Tests for host-managed OpenCode same-model session checkpoints."""

from __future__ import annotations

import inspect
import json
import os
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
    complete = "\n".join(
        [
            "opencode-review-control-v1",
            "adversarial_validation",
            '"result"',
            "Developer experience:",
            "User experience:",
        ]
    )
    assert missing_required_outputs(complete) == []


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


def test_classify_termination_covers_remaining_branches(tmp_path: Path) -> None:
    """Every bounded termination class is reachable from host evidence."""
    export_path = tmp_path / "export.json"
    export_path.write_text(_export_with_text("partial only"), encoding="utf-8")
    assert (
        classify_termination(
            json_path=tmp_path / "missing.jsonl",
            export_path=export_path,
            exit_code=0,
        )
        == "incomplete-control"
    )
    stderr = tmp_path / "stderr.txt"
    stderr.write_text("request timed out", encoding="utf-8")
    assert (
        classify_termination(
            json_path=tmp_path / "missing.jsonl",
            export_path=tmp_path / "missing-export.json",
            exit_code=1,
            stderr_path=stderr,
        )
        == "provider-timeout"
    )


def test_summarize_partial_assistant_handles_malformed_export(tmp_path: Path) -> None:
    """Malformed exports fail closed to empty metadata."""
    missing = summarize_partial_assistant(tmp_path / "missing.json")
    assert missing["assistant_text_present"] is False
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    assert summarize_partial_assistant(bad)["assistant_text_present"] is False
    weird = tmp_path / "weird.json"
    weird.write_text(
        json.dumps({"messages": ["not-a-dict", {"info": "x", "parts": "y"}]}),
        encoding="utf-8",
    )
    assert summarize_partial_assistant(weird)["assistant_text_present"] is False
    skipped = tmp_path / "skipped.json"
    skipped.write_text(
        json.dumps(
            {
                "messages": [
                    {"info": {"role": "user"}, "parts": [{"type": "text", "text": "x"}]},
                    {"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "  "}]},
                    {"info": {"role": "assistant"}, "parts": "not-a-list"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert summarize_partial_assistant(skipped)["assistant_text_present"] is False
    no_messages = tmp_path / "no-messages.json"
    no_messages.write_text(json.dumps({"messages": "not-a-list"}), encoding="utf-8")
    assert summarize_partial_assistant(no_messages)["assistant_text_present"] is False
    non_dict = tmp_path / "non-dict.json"
    non_dict.write_text(json.dumps(["not-a-dict"]), encoding="utf-8")
    assert summarize_partial_assistant(non_dict)["assistant_text_present"] is False


def test_load_checkpoint_repairs_invalid_documents(tmp_path: Path) -> None:
    """Invalid checkpoint files reset to an empty ledger."""
    from scripts.ci.opencode_review_session_checkpoint import _load_checkpoint

    path = tmp_path / "checkpoint.json"
    path.write_text("[]", encoding="utf-8")
    loaded = _load_checkpoint(path)
    assert loaded["attempts"] == []
    path.write_text("{", encoding="utf-8")
    assert _load_checkpoint(path)["schema"] == 1
    path.write_text(json.dumps({"attempts": "not-a-list"}), encoding="utf-8")
    assert _load_checkpoint(path)["attempts"] == []


def test_record_attempt_checkpoint_repairs_corrupt_history(tmp_path: Path) -> None:
    """Corrupt attempt history is replaced instead of crashing the host ledger."""
    export_path = tmp_path / "export.json"
    export_path.write_text(_export_with_text("partial"), encoding="utf-8")
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(json.dumps({"attempts": "bad-history"}), encoding="utf-8")
    record_attempt_checkpoint(
        checkpoint_path=checkpoint_path,
        model_candidate="contextual-orchestrator/orchestrator/free",
        attempt=1,
        head_sha="g" * 40,
        run_id="1",
        run_attempt="1",
        json_path=tmp_path / "run.jsonl",
        export_path=export_path,
        exit_code=1,
    )
    document = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert len(document["attempts"]) == 1


def test_build_continuation_appendix_truncates_large_payload(tmp_path: Path) -> None:
    """Continuation appendix stays within the configured byte budget."""
    export_path = tmp_path / "export.json"
    export_path.write_text(_export_with_text("partial"), encoding="utf-8")
    checkpoint_path = tmp_path / "checkpoint.json"
    record_attempt_checkpoint(
        checkpoint_path=checkpoint_path,
        model_candidate="contextual-orchestrator/orchestrator/free",
        attempt=1,
        head_sha="d" * 40,
        run_id="1",
        run_attempt="1",
        json_path=tmp_path / "run.jsonl",
        export_path=export_path,
        exit_code=1,
    )
    document = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    document["attempts"][0]["termination_reason"] = "x" * 9000
    document["attempts"][0]["missing_required_outputs"] = [
        f"marker-{index}-{'x' * 200}" for index in range(200)
    ]
    checkpoint_path.write_text(json.dumps(document), encoding="utf-8")
    appendix = build_continuation_appendix(checkpoint_path, budget=5)
    assert 0 < len(appendix.encode("utf-8")) <= 8192


def test_classify_termination_export_empty(tmp_path: Path) -> None:
    """Missing assistant export is classified separately from incomplete control."""
    assert (
        classify_termination(
            json_path=tmp_path / "run.jsonl",
            export_path=tmp_path / "missing.json",
            exit_code=0,
        )
        == "export-empty"
    )


def test_record_attempt_checkpoint_handles_non_list_parts(tmp_path: Path) -> None:
    """Partial text extraction skips malformed message parts safely."""
    export_path = tmp_path / "export.json"
    export_path.write_text(
        json.dumps(
            {
                "messages": [
                    {"parts": "not-a-list"},
                    {"info": {"role": "assistant"}, "parts": [{"text": "x"}]},
                ]
            }
        ),
        encoding="utf-8",
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    entry = record_attempt_checkpoint(
        checkpoint_path=checkpoint_path,
        model_candidate="contextual-orchestrator/orchestrator/free",
        attempt=1,
        head_sha="f" * 40,
        run_id="1",
        run_attempt="1",
        json_path=tmp_path / "run.jsonl",
        export_path=export_path,
        exit_code=1,
    )
    assert entry["missing_required_outputs"]


def test_record_attempt_checkpoint_handles_non_dict_export(tmp_path: Path) -> None:
    """Non-object export payloads do not leak partial text into checkpoints."""
    export_path = tmp_path / "export.json"
    export_path.write_text(json.dumps(["not-an-object"]), encoding="utf-8")
    checkpoint_path = tmp_path / "checkpoint.json"
    entry = record_attempt_checkpoint(
        checkpoint_path=checkpoint_path,
        model_candidate="contextual-orchestrator/orchestrator/free",
        attempt=1,
        head_sha="h" * 40,
        run_id="1",
        run_attempt="1",
        json_path=tmp_path / "run.jsonl",
        export_path=export_path,
        exit_code=1,
    )
    assert entry["missing_required_outputs"]


def test_record_attempt_checkpoint_skips_malformed_message_rows(tmp_path: Path) -> None:
    """Malformed export messages never become partial prompt replay."""
    export_path = tmp_path / "export.json"
    export_path.write_text(
        json.dumps(
            {
                "messages": [
                    "not-a-message",
                    {"parts": [{"type": "text", "text": 123}]},
                    {"info": {"role": "assistant"}, "parts": [{"type": "text"}]},
                ]
            }
        ),
        encoding="utf-8",
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    entry = record_attempt_checkpoint(
        checkpoint_path=checkpoint_path,
        model_candidate="contextual-orchestrator/orchestrator/free",
        attempt=1,
        head_sha="i" * 40,
        run_id="1",
        run_attempt="1",
        json_path=tmp_path / "run.jsonl",
        export_path=export_path,
        exit_code=1,
    )
    assert entry["missing_required_outputs"]


def test_record_attempt_checkpoint_without_export_file(tmp_path: Path) -> None:
    """Missing export files still produce a bounded checkpoint record."""
    checkpoint_path = tmp_path / "checkpoint.json"
    entry = record_attempt_checkpoint(
        checkpoint_path=checkpoint_path,
        model_candidate="contextual-orchestrator/orchestrator/free",
        attempt=1,
        head_sha="j" * 40,
        run_id="1",
        run_attempt="1",
        json_path=tmp_path / "run.jsonl",
        export_path=tmp_path / "missing-export.json",
        exit_code=1,
    )
    assert entry["partial_summary"]["assistant_text_present"] is False


def test_record_attempt_checkpoint_handles_unreadable_export(tmp_path: Path) -> None:
    """Unreadable export payloads fail closed during partial-text extraction."""
    export_path = tmp_path / "export.json"
    export_path.write_text("{", encoding="utf-8")
    checkpoint_path = tmp_path / "checkpoint.json"
    entry = record_attempt_checkpoint(
        checkpoint_path=checkpoint_path,
        model_candidate="contextual-orchestrator/orchestrator/free",
        attempt=1,
        head_sha="k" * 40,
        run_id="1",
        run_attempt="1",
        json_path=tmp_path / "run.jsonl",
        export_path=export_path,
        exit_code=1,
    )
    assert entry["missing_required_outputs"]


def test_record_attempt_checkpoint_handles_messages_not_list(tmp_path: Path) -> None:
    """Export objects without message lists do not produce partial replay text."""
    export_path = tmp_path / "export.json"
    export_path.write_text(json.dumps({"messages": "bad"}), encoding="utf-8")
    checkpoint_path = tmp_path / "checkpoint.json"
    entry = record_attempt_checkpoint(
        checkpoint_path=checkpoint_path,
        model_candidate="contextual-orchestrator/orchestrator/free",
        attempt=1,
        head_sha="l" * 40,
        run_id="1",
        run_attempt="1",
        json_path=tmp_path / "run.jsonl",
        export_path=export_path,
        exit_code=1,
    )
    assert entry["missing_required_outputs"]


def test_build_continuation_appendix_empty_and_invalid_last_entry(tmp_path: Path) -> None:
    """Empty or malformed checkpoint documents produce no appendix."""
    checkpoint_path = tmp_path / "checkpoint.json"
    assert build_continuation_appendix(checkpoint_path, budget=2) == ""
    checkpoint_path.write_text(json.dumps({"attempts": ["bad-entry"]}), encoding="utf-8")
    assert build_continuation_appendix(checkpoint_path, budget=2) == ""
    checkpoint_path.write_text(
        json.dumps(
            {
                "pinned_model": "contextual-orchestrator/orchestrator/free",
                "attempts": [
                    {
                        "attempt": 1,
                        "termination_reason": "invalid-control",
                        "partial_summary": "not-a-mapping",
                        "missing_required_outputs": "not-a-list",
                        "route_telemetry": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    appendix = build_continuation_appendix(checkpoint_path, budget=2)
    assert "Same-model continuation" in appendix
    assert "Partial assistant digest" not in appendix


def test_continuation_budget_empty_history_uses_no_budget(tmp_path: Path) -> None:
    """An empty history consumes no same-model continuation budget."""
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(json.dumps({"attempts": []}), encoding="utf-8")
    assert continuation_budget_remaining(checkpoint_path, budget=2) == 2


def test_continuation_budget_has_no_unreachable_coverage_clamp() -> None:
    """Budget decisions remain executable rather than hidden from coverage."""
    source = inspect.getsource(continuation_budget_remaining)
    assert "used < 0" not in source
    assert "pragma: no cover" not in source


def test_budget_cli_requires_explicit_authority(tmp_path: Path) -> None:
    """The CLI cannot invent a continuation budget when authority is absent."""
    environment = dict(os.environ)
    environment.pop("OPENCODE_SESSION_CONTINUATION_BUDGET", None)
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ci/opencode_review_session_checkpoint.py",
            "budget-remaining",
            "--checkpoint",
            str(tmp_path / "checkpoint.json"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )

    assert completed.returncode != 0
    assert "--budget" in completed.stderr


def test_main_entrypoint(tmp_path: Path) -> None:
    """Module entrypoint delegates to main()."""
    export_path = tmp_path / "export.json"
    export_path.write_text(_export_with_text("partial"), encoding="utf-8")
    checkpoint_path = tmp_path / "checkpoint.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ci/opencode_review_session_checkpoint.py",
            "budget-remaining",
            "--checkpoint",
            str(checkpoint_path),
            "--budget",
            "1",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "1"


def test_main_subcommands(tmp_path: Path) -> None:
    """CLI subcommands return bounded stdout for host orchestration."""
    from scripts.ci.opencode_review_session_checkpoint import main

    export_path = tmp_path / "export.json"
    export_path.write_text(_export_with_text("partial"), encoding="utf-8")
    checkpoint_path = tmp_path / "checkpoint.json"
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("base\n", encoding="utf-8")
    assert (
        main(
            [
                "record",
                "--checkpoint",
                str(checkpoint_path),
                "--model-candidate",
                "contextual-orchestrator/orchestrator/free",
                "--attempt",
                "1",
                "--head-sha",
                "e" * 40,
                "--run-id",
                "1",
                "--run-attempt",
                "1",
                "--json-path",
                str(tmp_path / "run.jsonl"),
                "--export-path",
                str(export_path),
                "--exit-code",
                "1",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "append-continuation",
                "--prompt",
                str(prompt_path),
                "--checkpoint",
                str(checkpoint_path),
                "--budget",
                "2",
            ]
        )
        == 0
    )
    assert main(["budget-remaining", "--checkpoint", str(checkpoint_path), "--budget", "2"]) == 0


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


def test_read_bounded_text_oserror_returns_empty(tmp_path: Path, monkeypatch) -> None:
    """Unreadable evidence files fail closed without raising."""
    from scripts.ci.opencode_review_session_checkpoint import _read_bounded_text

    path = tmp_path / "blocked.txt"
    path.write_text("x", encoding="utf-8")

    def _raise_oserror(*_args, **_kwargs):
        raise OSError("blocked")

    monkeypatch.setattr(path.__class__, "open", _raise_oserror)
    assert _read_bounded_text(path, 16) == ""


def test_record_attempt_checkpoint_keeps_assistant_text_parts_only(
    tmp_path: Path,
) -> None:
    """Partial text extraction ignores non-assistant and non-text parts."""
    export_path = tmp_path / "export.json"
    export_path.write_text(
        json.dumps(
            {
                "messages": [
                    {
                        "info": {"role": "user"},
                        "parts": [{"type": "text", "text": "ignore user"}],
                    },
                    {
                        "info": {"role": "assistant"},
                        "parts": [
                            {"type": "tool", "text": "ignore tool"},
                            {"type": "text", "text": "assistant partial"},
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    entry = record_attempt_checkpoint(
        checkpoint_path=checkpoint_path,
        model_candidate="contextual-orchestrator/orchestrator/free",
        attempt=1,
        head_sha="m" * 40,
        run_id="1",
        run_attempt="1",
        json_path=tmp_path / "run.jsonl",
        export_path=export_path,
        exit_code=1,
    )
    assert "opencode-review-control-v1" in entry["missing_required_outputs"]
    assert "assistant partial" not in json.dumps(entry)


def test_main_script_entrypoint(tmp_path: Path) -> None:
    """Running the script path exercises the __main__ entrypoint."""
    checkpoint_path = tmp_path / "checkpoint.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/ci/opencode_review_session_checkpoint.py",
            "budget-remaining",
            "--checkpoint",
            str(checkpoint_path),
            "--budget",
            "2",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "2"


def test_record_attempt_checkpoint_skips_non_list_attempt_container(
    tmp_path: Path, monkeypatch
) -> None:
    """A corrupt in-memory attempt container cannot append a new record."""
    from scripts.ci import opencode_review_session_checkpoint as checkpoint

    export_path = tmp_path / "export.json"
    export_path.write_text(_export_with_text("partial"), encoding="utf-8")
    checkpoint_path = tmp_path / "checkpoint.json"

    def _broken_load(_path: Path) -> dict:
        return {"schema": 1, "attempts": "bad-history"}

    monkeypatch.setattr(checkpoint, "_load_checkpoint", _broken_load)
    entry = checkpoint.record_attempt_checkpoint(
        checkpoint_path=checkpoint_path,
        model_candidate="contextual-orchestrator/orchestrator/free",
        attempt=1,
        head_sha="n" * 40,
        run_id="1",
        run_attempt="1",
        json_path=tmp_path / "run.jsonl",
        export_path=export_path,
        exit_code=1,
    )
    document = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert entry["attempt"] == 1
    assert document["attempts"] == "bad-history"


def test_record_attempt_checkpoint_skips_assistant_without_parts_list(
    tmp_path: Path,
) -> None:
    """Assistant messages without part lists do not contribute partial replay text."""
    export_path = tmp_path / "export.json"
    export_path.write_text(
        json.dumps({"messages": [{"info": {"role": "assistant"}, "parts": "bad"}]}),
        encoding="utf-8",
    )
    checkpoint_path = tmp_path / "checkpoint.json"
    entry = record_attempt_checkpoint(
        checkpoint_path=checkpoint_path,
        model_candidate="contextual-orchestrator/orchestrator/free",
        attempt=1,
        head_sha="o" * 40,
        run_id="1",
        run_attempt="1",
        json_path=tmp_path / "run.jsonl",
        export_path=export_path,
        exit_code=1,
    )
    assert entry["missing_required_outputs"]


def test_module_sys_path_insert_is_idempotent() -> None:
    """Re-importing the checkpoint module does not duplicate sys.path entries."""
    import importlib

    import scripts.ci.opencode_review_session_checkpoint as checkpoint

    root = str(checkpoint._REPO_ROOT)
    before = sys.path.count(root)
    importlib.reload(checkpoint)
    assert sys.path.count(root) == before


def test_main_unknown_command_exits(monkeypatch) -> None:
    """Unknown CLI commands fail closed after argument parsing."""
    from scripts.ci import opencode_review_session_checkpoint as checkpoint

    class Args:
        command = "not-a-real-command"

    monkeypatch.setattr(checkpoint, "parse_args", lambda _argv=None: Args())
    try:
        checkpoint.main([])
    except SystemExit as exc:
        assert "unknown command" in str(exc)
    else:
        raise AssertionError("expected SystemExit")
