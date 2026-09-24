from __future__ import annotations

import base64
from datetime import datetime, timezone

import pytest

from scripts.ci import reconcile_conceptweave_product_ruleset as p
from scripts.ci.reconcile_ruleset_governance import RulesetGovernanceError


def _manifest(ruleset_id: int, blob_sha: object = "f" * 40) -> dict[str, object]:
    return {
        "schema_version": 1,
        "target_repository": p.TARGET_FULL_NAME,
        "target_branch": p.TARGET_BRANCH,
        "ruleset_name": p.RULESET_NAME,
        "ruleset_id": ruleset_id,
        "required_check": p.PRODUCT_CHECK,
        "forbidden_check": p.METADATA_ONLY_CHECK,
        "product_workflow_blob_sha": blob_sha,
    }


def _live(ruleset_id: int, *, enforcement: str = "evaluate") -> dict[str, object]:
    return {
        "id": ruleset_id,
        "source_type": "Organization",
        "source": p.ORGANIZATION,
        **p._desired(enforcement=enforcement),
    }


def _prepare_activation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ruleset_id: int,
) -> tuple[list[bool], list[bool]]:
    canary_called = [False]
    put_called = [False]
    state = {"enforcement": "evaluate"}

    monkeypatch.setattr(p, "_assert_current_main", lambda _sha: None)
    monkeypatch.setattr(p, "_assert_target_main", lambda _sha: None)
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": ruleset_id})
    monkeypatch.setattr(
        p,
        "_live",
        lambda _target: _live(ruleset_id, enforcement=state["enforcement"]),
    )
    monkeypatch.setattr(
        p,
        "_latest_base_retarget",
        lambda _pr: datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc),
    )

    def canary_evidence(**_kwargs: object) -> tuple[str, str]:
        canary_called[0] = True
        return "a" * 40, "b" * 40

    monkeypatch.setattr(p, "_canary_evidence", canary_evidence)
    monkeypatch.setattr(p, "_assert_evaluate_rule_suite", lambda **_kwargs: None)
    monkeypatch.setattr(p, "_latest_history_version", lambda _target: 4)
    monkeypatch.setattr(p, "_verify_ruleset_history_transition", lambda *_args, **_kwargs: None)

    def api(method: str, _endpoint: str, **_kwargs: object) -> dict[str, object]:
        if method == "PUT":
            put_called[0] = True
            state["enforcement"] = "active"
        return {}

    monkeypatch.setattr(p, "_gh_api", api)
    return canary_called, put_called


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


def test_activation_aborts_when_conceptweave_main_advances_after_canary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not activate from evaluate evidence whose protected target base went stale."""

    ruleset_id = 30
    base_sha = "a" * 40
    head_sha = "b" * 40
    target_checks = 0
    put_called = False
    current = _live(ruleset_id)

    monkeypatch.setattr(p, "_assert_current_main", lambda _sha: None)
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": ruleset_id})
    monkeypatch.setattr(p, "_live", lambda _target: current)
    monkeypatch.setattr(
        p,
        "_latest_base_retarget",
        lambda _pr: datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        p,
        "_canary_evidence",
        lambda **_kwargs: (base_sha, head_sha),
    )
    monkeypatch.setattr(p, "_assert_evaluate_rule_suite", lambda **_kwargs: None)
    monkeypatch.setattr(p, "_latest_history_version", lambda _target: 4)

    def assert_target_main(_sha: str) -> None:
        nonlocal target_checks
        target_checks += 1
        if target_checks == 2:
            raise RulesetGovernanceError("ConceptWeave protected main advanced")

    monkeypatch.setattr(p, "_assert_target_main", assert_target_main)

    def api(method: str, _endpoint: str, **_kwargs: object) -> dict[str, object]:
        nonlocal put_called
        if method == "PUT":
            put_called = True
        return {}

    monkeypatch.setattr(p, "_gh_api", api)

    with pytest.raises(RulesetGovernanceError, match="protected main advanced"):
        p.activate_product_ruleset(
            _manifest(ruleset_id),
            expected_main_sha="d" * 40,
            canary_pr=5,
            canary_run_id=77,
        )

    assert target_checks == 2
    assert put_called is False


def test_activation_rejects_null_product_blob_before_canary_or_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Activation cannot consume canary evidence until Product source is pinned."""

    canary_called, put_called = _prepare_activation(monkeypatch, ruleset_id=31)

    with pytest.raises(RulesetGovernanceError, match="blob"):
        p.activate_product_ruleset(
            _manifest(31, None),
            expected_main_sha="d" * 40,
            canary_pr=5,
            canary_run_id=77,
        )

    assert canary_called == [False]
    assert put_called == [False]


def test_canary_admission_rejects_marker_compatible_product_blob_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact reviewed Product blob is part of canary admission, not just markers."""

    reviewed_blob = "c" * 40
    live_blob = "d" * 40
    base_sha = "a" * 40
    head_sha = "b" * 40

    def api(method: str, endpoint: str, **_kwargs: object) -> dict[str, object]:
        if endpoint.endswith("pulls/5"):
            return {
                "state": "open",
                "draft": False,
                "head": {"sha": head_sha},
                "base": {"ref": "main", "sha": base_sha},
            }
        if f"contents/{p.PRODUCT_WORKFLOW_PATH}" in endpoint:
            return _workflow_payload(live_blob)
        raise AssertionError((method, endpoint))

    monkeypatch.setattr(p, "_gh_api", api)
    monkeypatch.setattr(p, "_assert_target_main", lambda _sha: None)
    monkeypatch.setattr(
        p,
        "_latest_base_retarget",
        lambda _pr: datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(RulesetGovernanceError, match="blob"):
        p._canary_evidence(
            pr_number=5,
            run_id=77,
            expected_blob_sha=reviewed_blob,
        )


def test_activation_revalidates_product_blob_immediately_before_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Product source drift after canary evidence must abort before active PUT."""

    reviewed_blob = "c" * 40
    _canary_called, put_called = _prepare_activation(monkeypatch, ruleset_id=32)
    blob_checks: list[tuple[str, object]] = []

    def assert_product_blob(
        base_sha: str,
        *,
        expected_blob_sha: str | None = None,
    ) -> None:
        blob_checks.append((base_sha, expected_blob_sha))
        if expected_blob_sha == reviewed_blob:
            raise RulesetGovernanceError("protected-base Product workflow blob drifted")

    monkeypatch.setattr(p, "_assert_base_product_workflow", assert_product_blob)

    with pytest.raises(RulesetGovernanceError, match="blob"):
        p.activate_product_ruleset(
            _manifest(32, reviewed_blob),
            expected_main_sha="d" * 40,
            canary_pr=5,
            canary_run_id=77,
        )

    assert blob_checks
    assert put_called == [False]


def test_retarget_provenance_rejects_later_commit_without_created_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Committed timeline events have no common created_at field; sequence is authoritative."""

    monkeypatch.setattr(
        p,
        "_gh_api_list",
        lambda *_args, **_kwargs: [
            {
                "event": "base_ref_changed",
                "created_at": "2026-09-23T00:00:00Z",
            },
            {
                "event": "committed",
                "sha": "c" * 40,
            },
        ],
    )

    with pytest.raises(RulesetGovernanceError, match="source commit"):
        p._latest_base_retarget(5)


@pytest.mark.parametrize("drifted_ref", ["owner", "target"])
def test_activation_rechecks_both_protected_refs_after_final_blob_read(
    monkeypatch: pytest.MonkeyPatch,
    drifted_ref: str,
) -> None:
    """A ref that advances during final blob validation must block active PUT."""

    ruleset_id = 33
    expected_main = "d" * 40
    base_sha = "a" * 40
    reviewed_blob = "c" * 40
    _canary_called, put_called = _prepare_activation(monkeypatch, ruleset_id=ruleset_id)
    state = {"owner": expected_main, "target": base_sha}
    blob_checks = 0

    def assert_current_main(expected: str) -> None:
        if state["owner"] != expected:
            raise RulesetGovernanceError(".github protected main advanced")

    def assert_target_main(expected: str) -> None:
        if state["target"] != expected:
            raise RulesetGovernanceError("ConceptWeave protected main advanced")

    def assert_product_blob(
        checked_base_sha: str,
        *,
        expected_blob_sha: str | None = None,
    ) -> None:
        nonlocal blob_checks
        assert checked_base_sha == base_sha
        assert expected_blob_sha == reviewed_blob
        blob_checks += 1
        state[drifted_ref] = "e" * 40

    monkeypatch.setattr(p, "_assert_current_main", assert_current_main)
    monkeypatch.setattr(p, "_assert_target_main", assert_target_main)
    monkeypatch.setattr(p, "_assert_base_product_workflow", assert_product_blob)

    with pytest.raises(RulesetGovernanceError, match="advanced"):
        p.activate_product_ruleset(
            _manifest(ruleset_id, reviewed_blob),
            expected_main_sha=expected_main,
            canary_pr=5,
            canary_run_id=77,
        )

    assert blob_checks == 1
    assert put_called == [False]
