"""Regressions for Noema's long-running prepare-phase GitHub credential boundary."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "noema-review.yml"
MODULE_PATH = ROOT / ".github" / "actions" / "noema-review" / "two_phase.py"
HEAD = "a" * 40
BASE = "b" * 40


def _load_module() -> ModuleType:
    """Load the trusted two-phase helper from its workflow-owned path."""
    spec = importlib.util.spec_from_file_location("noema_prepare_control_token_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _step_block(text: str, name: str) -> str:
    """Return one exact named workflow step without borrowing sibling evidence."""
    marker = f"      - name: {name}\n"
    start = text.index(marker)
    next_step = text.find("\n      - name: ", start + len(marker))
    return text[start:] if next_step < 0 else text[start:next_step]


def _patch_prepare_gate(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> None:
    """Make prepare deterministic while preserving token-observation seams."""
    monkeypatch.setattr(
        module.gate,
        "fetch_pr",
        lambda _repo, _number: {
            "isDraft": False,
            "headRefOid": HEAD,
            "baseRefOid": BASE,
        },
    )
    monkeypatch.setattr(module.gate, "require_expected_head", lambda _pr, _head: None)
    monkeypatch.setattr(module.gate, "current_actor", lambda: "cwl-noema-review[bot]")
    monkeypatch.setattr(module.gate, "PRIMARY_REVIEW_AUTHORS", frozenset({"seonghobae"}))
    monkeypatch.setattr(module.gate, "existing_noema_review", lambda _pr, _actor: False)
    monkeypatch.setattr(module.gate, "fetch_diff", lambda _repo, _number: ("diff", False))
    monkeypatch.setattr(module.gate, "fetch_changed_files", lambda _repo, _number: [("src/a.py", "MODIFIED")])
    monkeypatch.setattr(module.gate, "build_review_context", lambda *_args: "context")


def test_workflow_supplies_job_lifetime_read_token_only_to_prepare() -> None:
    """Long model work must use the job token for later read-only stale-head checks."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    prepare = _step_block(workflow, "Prepare Noema model verdict")
    publish = _step_block(workflow, "Publish prepared Noema verdict on the exact live head")

    assert "NOEMA_PREPARE_CONTROL_TOKEN: ${{ github.token }}" in prepare
    assert "NOEMA_PREPARE_CONTROL_TOKEN" not in publish
    assert "github.token" not in publish


def test_prepare_switches_post_model_github_reads_to_job_token_and_restores_reviewer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reviewer identity is checked first; model-time stale reads use job-lifetime authority."""
    module = _load_module()
    reviewer_token = "short-lived-reviewer-token"
    control_token = "job-lifetime-read-token"
    monkeypatch.setenv("GH_TOKEN", reviewer_token)
    monkeypatch.setenv("NOEMA_REVIEW_TOKEN_SOURCE", module.CANONICAL_APP_TOKEN_SOURCE)
    monkeypatch.setenv("NOEMA_PREPARE_CONTROL_TOKEN", control_token)
    _patch_prepare_gate(monkeypatch, module)
    observed: list[str | None] = []

    def call_llm(*_args: object) -> dict[str, str]:
        observed.append(os.environ.get("GH_TOKEN"))
        return {"decision": "approve", "summary": "bounded"}

    monkeypatch.setattr(module.gate, "call_llm", call_llm)
    envelope = tmp_path / "verdict.json"

    assert module.prepare_verdict("ContextualWisdomLab/example", 7, HEAD, envelope) == 0
    assert observed == [control_token]
    assert os.environ["GH_TOKEN"] == reviewer_token
    assert envelope.exists()


def test_prepare_fails_closed_if_app_review_has_no_job_lifetime_control_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An App-backed long review never silently falls back to its expiring token."""
    module = _load_module()
    monkeypatch.setenv("GH_TOKEN", "short-lived-reviewer-token")
    monkeypatch.setenv("NOEMA_REVIEW_TOKEN_SOURCE", module.CANONICAL_APP_TOKEN_SOURCE)
    monkeypatch.delenv("NOEMA_PREPARE_CONTROL_TOKEN", raising=False)
    _patch_prepare_gate(monkeypatch, module)
    monkeypatch.setattr(module.gate, "call_llm", lambda *_args: pytest.fail("model must not start"))

    with pytest.raises(RuntimeError, match="prepare control token"):
        module.prepare_verdict(
            "ContextualWisdomLab/example",
            7,
            HEAD,
            tmp_path / "verdict.json",
        )
