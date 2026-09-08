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
