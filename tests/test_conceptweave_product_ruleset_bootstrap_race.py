from __future__ import annotations

import base64
import json

import pytest

from scripts.ci import reconcile_conceptweave_product_ruleset as p
from scripts.ci.reconcile_ruleset_governance import RulesetGovernanceError


def _manifest(blob_sha: object = "f" * 40) -> dict[str, object]:
    return {
        "schema_version": 1,
        "target_repository": p.TARGET_FULL_NAME,
        "target_branch": p.TARGET_BRANCH,
        "ruleset_name": p.RULESET_NAME,
        "ruleset_id": None,
        "required_check": p.PRODUCT_CHECK,
        "forbidden_check": p.METADATA_ONLY_CHECK,
        "product_workflow_blob_sha": blob_sha,
    }


def _workflow_payload(blob_sha: str) -> dict[str, object]:
    text = (
        "name: Product\n"
        "x: 'Product acceptance'\n"
        "y: 'Product metadata-only'\n"
        "concurrency:\n"
        "  cancel-in-progress: false\n"
    )
    return {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(text.encode()).decode(),
        "sha": blob_sha,
    }


def _prepare_bootstrap(monkeypatch: pytest.MonkeyPatch, *, target_main: str) -> list[bool]:
    created = [False]
    monkeypatch.setattr(p, "_assert_current_main", lambda _sha: None)
    monkeypatch.setattr(p, "_named_ruleset", lambda: None)
    monkeypatch.setattr(p, "_target_main_sha", lambda: target_main)
    monkeypatch.setattr(p, "_assert_target_main", lambda _sha: None)
    monkeypatch.setattr(p, "_assert_shape", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(p, "_latest_history_version", lambda _target: 1)
    monkeypatch.setattr(p, "_history_version_state", lambda _target, _version: {"id": 91})

    def create_evaluate_ruleset() -> dict[str, int]:
        created[0] = True
        return {"id": 91}

    monkeypatch.setattr(p, "_create_evaluate_ruleset", create_evaluate_ruleset)
    return created


def test_bootstrap_rechecks_protected_main_immediately_before_create(monkeypatch):
    expected = "a" * 40
    target_main = "b" * 40
    current_main_checks: list[str] = []
    created = False

    def assert_current_main(sha: str) -> None:
        current_main_checks.append(sha)
        if len(current_main_checks) == 2:
            raise RulesetGovernanceError("protected main advanced")

    def create_evaluate_ruleset():
        nonlocal created
        created = True
        return {"id": 91}

    monkeypatch.setattr(p, "_assert_current_main", assert_current_main)
    monkeypatch.setattr(p, "_named_ruleset", lambda: None)
    monkeypatch.setattr(p, "_target_main_sha", lambda: target_main)
    monkeypatch.setattr(
        p,
        "_assert_base_product_workflow",
        lambda _sha, **_kwargs: None,
    )
    monkeypatch.setattr(p, "_assert_target_main", lambda _sha: None)
    monkeypatch.setattr(p, "_create_evaluate_ruleset", create_evaluate_ruleset)

    with pytest.raises(RulesetGovernanceError, match="advanced"):
        p.bootstrap_product_ruleset(_manifest(), expected_main_sha=expected)

    assert current_main_checks == [expected, expected]
    assert created is False


def test_bootstrap_rejects_null_product_blob_before_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A staged null coordinate must never authorize evaluate-policy creation."""

    target_main = "b" * 40
    created = _prepare_bootstrap(monkeypatch, target_main=target_main)
    monkeypatch.setattr(
        p,
        "_assert_base_product_workflow",
        lambda _sha, **_kwargs: None,
    )

    with pytest.raises(RulesetGovernanceError, match="blob"):
        p.bootstrap_product_ruleset(
            _manifest(None),
            expected_main_sha="a" * 40,
        )

    assert created == [False]


def test_bootstrap_rejects_marker_compatible_product_blob_drift_before_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Markers are insufficient when protected Product bytes differ from review."""

    target_main = "b" * 40
    reviewed_blob = "c" * 40
    live_blob = "d" * 40
    created = _prepare_bootstrap(monkeypatch, target_main=target_main)
    monkeypatch.setattr(
        p,
        "_gh_api",
        lambda *_args, **_kwargs: _workflow_payload(live_blob),
    )

    with pytest.raises(RulesetGovernanceError, match="blob"):
        p.bootstrap_product_ruleset(
            _manifest(reviewed_blob),
            expected_main_sha="a" * 40,
        )

    assert created == [False]


def test_load_manifest_accepts_staged_legacy_shape_without_blob(tmp_path) -> None:
    """The staged loader still accepts the pre-coordinate reviewed manifest shape."""

    legacy = _manifest()
    legacy.pop("product_workflow_blob_sha")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")

    assert p.load_product_manifest(path) == legacy


def test_reviewed_product_blob_rejects_malformed_string_coordinate() -> None:
    """Mutation validation rejects a string that is not an immutable Git blob SHA."""

    with pytest.raises(RulesetGovernanceError, match="blob"):
        p._reviewed_product_workflow_blob(_manifest("not-a-git-sha"))
