"""Regression coverage for refreshed Noema GitHub App credentials."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / ".github" / "actions" / "noema-review" / "two_phase.py"


def _load_module() -> ModuleType:
    """Load the trusted two-phase helper from its workflow action path."""
    spec = importlib.util.spec_from_file_location(
        "noema_two_phase_refreshed_identity_under_test",
        MODULE_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_publication_validates_refreshed_token_as_the_same_bound_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """Token renewal changes lifetime, not the independently bound App identity."""
    module = _load_module()
    monkeypatch.setenv("NOEMA_REVIEW_ACTOR", "cwl-noema-review[bot]")
    monkeypatch.setenv("NOEMA_REVIEW_INSTALLATION_ID", "146401636")
    monkeypatch.setenv(
        "NOEMA_REVIEW_TOKEN_SOURCE",
        module.REFRESHED_APP_TOKEN_SOURCE,
    )

    assert module._reviewer_actor(allow_refreshed_app=True) == "cwl-noema-review[bot]"
    assert os.environ["NOEMA_REVIEW_TOKEN_SOURCE"] == module.REFRESHED_APP_TOKEN_SOURCE


def test_refreshed_token_path_retains_bot_identity_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Publication must not turn the refresh alias into a general identity bypass."""
    module = _load_module()
    monkeypatch.setenv("NOEMA_REVIEW_ACTOR", "seonghobae")
    monkeypatch.setenv("NOEMA_REVIEW_INSTALLATION_ID", "146401636")
    monkeypatch.setenv(
        "NOEMA_REVIEW_TOKEN_SOURCE",
        module.REFRESHED_APP_TOKEN_SOURCE,
    )

    with pytest.raises(RuntimeError, match="Noema GitHub App identity binding is invalid"):
        module._reviewer_actor(allow_refreshed_app=True)
    assert os.environ["NOEMA_REVIEW_TOKEN_SOURCE"] == module.REFRESHED_APP_TOKEN_SOURCE


def test_unrecognized_source_is_not_normalized(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the workflow-owned refresh marker may reuse canonical App validation."""
    module = _load_module()
    monkeypatch.setenv("NOEMA_REVIEW_ACTOR", "cwl-noema-review[bot]")
    monkeypatch.setenv("NOEMA_REVIEW_INSTALLATION_ID", "146401636")
    monkeypatch.setenv("NOEMA_REVIEW_TOKEN_SOURCE", "untrusted-app-alias")

    with pytest.raises(RuntimeError, match="Noema GitHub App identity binding is invalid"):
        module._reviewer_actor(allow_refreshed_app=True)
    assert os.environ["NOEMA_REVIEW_TOKEN_SOURCE"] == "untrusted-app-alias"


def test_actual_refreshed_publication_counts_only_as_exact_head_independent_app(
    monkeypatch, tmp_path,
):
    """Compose the real two-phase publisher and scheduler without remote writes."""
    import json
    from copy import deepcopy
    from scripts.ci import pr_review_merge_scheduler as scheduler
    from tests.test_review_ai_app_independence import app_review, pull_request, HEAD

    template = app_review(monkeypatch)
    module = _load_module()
    monkeypatch.setenv("NOEMA_REVIEW_ACTOR", "cwl-noema-review[bot]")
    monkeypatch.setenv("NOEMA_REVIEW_INSTALLATION_ID", "146401636")
    monkeypatch.setenv("NOEMA_REVIEW_TOKEN_SOURCE", module.REFRESHED_APP_TOKEN_SOURCE)
    live = {"state": "OPEN", "headRefOid": HEAD, "baseRefOid": "b" * 40,
            "isDraft": False, "reviews": {"nodes": []}}
    monkeypatch.setattr(module.gate, "fetch_pr", lambda *_: live)
    captured = []
    monkeypatch.setattr(module.gate, "run", lambda args, stdin=None: captured.append(json.loads(stdin)))
    envelope = tmp_path / "verdict.json"
    # Recover a substantive verdict through the existing fixture publisher's contract.
    verdict = {
        "decision": "approve", "summary": "Inspected exact-head publication.", "findings": [],
        "reviewed_lines": [{"path": "scripts/ci/example.py", "line": 2, "side": "RIGHT",
                            "analysis": "The exact-head guard rejects stale publication."}],
        "adversarial_validation": {"residual_risk": "Installation permission remains external.",
            "probes": [{"path": "scripts/ci/example.py", "line": 2, "side": "RIGHT",
                        "outcome": "falsified", "hypothesis": "Stale publication could pass.",
                        "evidence": "The live head comparison rejects stale publication."}]},
    }
    module._write_envelope(envelope, {"schema_version": 1,
        "repository": "ContextualWisdomLab/example", "pull_request_number": 7,
        "expected_head": HEAD, "expected_base": "b" * 40, "verdict": verdict})
    assert module.publish_verdict("ContextualWisdomLab/example", 7, HEAD, envelope) == 0
    assert len(captured) == 1 and captured[0]["commit_id"] == HEAD
    assert captured[0]["event"] == "APPROVE"
    assert module.REFRESHED_APP_TOKEN_SOURCE in captured[0]["body"]
    template["body"] = captured[0]["body"]
    pr = pull_request(template)
    assert scheduler.has_independent_current_head_approval(pr)
    for key, value in (("state", "COMMENTED"), ("commit", {"oid": "c" * 40}),
                       ("author", {"login": "unknown[bot]", "__typename": "Bot"})):
        rejected = deepcopy(pr)
        rejected["reviews"]["nodes"][0][key] = value
        assert not scheduler.has_independent_current_head_approval(rejected)
    assert not envelope.exists()
    assert os.environ["NOEMA_REVIEW_TOKEN_SOURCE"] == module.REFRESHED_APP_TOKEN_SOURCE
