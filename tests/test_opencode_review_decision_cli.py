"""Serialization and CLI tests for OpenCode decision envelopes."""

from __future__ import annotations

import importlib.util
import json
import runpy
import sys
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).resolve().parent
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

from opencode_review_decision_test_support import MODULE_PATH, decision, envelope, finding


def test_direct_module_load_registers_its_support_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A path-based invocation must make sibling decision modules importable."""
    module_dir = str(MODULE_PATH.parent)
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry != module_dir])
    spec = importlib.util.spec_from_file_location(
        "opencode_review_decision_direct", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert sys.path[0] == module_dir


def test_markdown_keeps_findings_and_infrastructure_blockers_separate() -> None:
    """Human summaries never render infrastructure failure as a source line."""
    report = decision.build_decision(
        envelope(findings=[finding()], coverage_state="failure")
    )
    markdown = decision.render_markdown(report)
    assert "## Semantic findings" in markdown
    assert "scripts/ci/example.py:12" in markdown
    assert "## Infrastructure and policy blockers" in markdown
    blocker_section = markdown.split("## Infrastructure and policy blockers", 1)[1]
    assert "coverage" in blocker_section
    assert ".github/workflows/opencode-review.yml:1" not in blocker_section


def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(tmp_path: Path) -> None:
    """Decision evidence rejects ambiguous JSON and numeric extensions."""
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":"1.0","schema_version":"1.0"}')
    with pytest.raises(decision.DecisionValidationError, match="duplicate JSON key"):
        decision.load_json(duplicate)

    nonfinite = tmp_path / "nonfinite.json"
    nonfinite.write_text('{"line": NaN}')
    with pytest.raises(decision.DecisionValidationError, match="non-finite JSON number"):
        decision.load_json(nonfinite)


def test_cli_writes_atomic_json_and_markdown_with_stable_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI publishes both decision views atomically or rejects the input."""
    source = tmp_path / "input.json"
    json_output = tmp_path / "nested" / "decision.json"
    markdown_output = tmp_path / "nested" / "decision.md"
    source.write_text(json.dumps(envelope()), encoding="utf-8")
    assert (
        decision.main(
            [
                "--input",
                str(source),
                "--json-output",
                str(json_output),
                "--markdown-output",
                str(markdown_output),
            ]
        )
        == 0
    )
    assert json.loads(json_output.read_text(encoding="utf-8"))["merge_readiness"] == "READY"
    assert "Review verdict: **APPROVE**" in markdown_output.read_text(encoding="utf-8")
    assert not json_output.with_name(f".{json_output.name}.tmp").exists()
    assert not markdown_output.with_name(f".{markdown_output.name}.tmp").exists()

    source.write_text("[]", encoding="utf-8")
    assert (
        decision.main(
            [
                "--input",
                str(source),
                "--json-output",
                str(json_output),
                "--markdown-output",
                str(markdown_output),
            ]
        )
        == 2
    )
    assert "decision evidence rejected" in capsys.readouterr().err


def test_module_entrypoint_routes_through_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Direct script execution uses the same tested CLI boundary."""
    source = tmp_path / "input.json"
    json_output = tmp_path / "decision.json"
    markdown_output = tmp_path / "decision.md"
    source.write_text(json.dumps(envelope()), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            str(MODULE_PATH),
            "--input",
            str(source),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ],
    )
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(MODULE_PATH), run_name="__main__")
    assert json_output.exists() and markdown_output.exists()


def test_public_production_callables_have_docstrings() -> None:
    """Every production class and function remains beginner-readable."""
    missing = [
        name
        for name, value in vars(decision).items()
        if not name.startswith("_")
        and (isinstance(value, type) or callable(value))
        and getattr(value, "__module__", None) == decision.__name__
        and not getattr(value, "__doc__", None)
    ]
    assert missing == []


def test_load_json_wraps_syntax_and_filesystem_errors(tmp_path: Path) -> None:
    """Malformed or unavailable evidence files must produce bounded stable errors."""
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(decision.DecisionValidationError, match="cannot load"):
        decision.load_json(malformed)
    with pytest.raises(decision.DecisionValidationError, match="cannot load"):
        decision.load_json(tmp_path / "absent.json")
