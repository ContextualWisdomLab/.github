from __future__ import annotations

import base64

import pytest

from scripts.ci import reconcile_conceptweave_product_ruleset as p
from scripts.ci.reconcile_ruleset_governance import RulesetGovernanceError


def _live_payload(
    ruleset_id: int,
    *,
    enforcement: str = "evaluate",
    integration_id: int | None = None,
) -> dict[str, object]:
    return {
        "id": ruleset_id,
        "source_type": "Repository",
        "source": p.TARGET_FULL_NAME,
        **p._desired(enforcement=enforcement, integration_id=integration_id),
    }


def test_activation_aborts_when_conceptweave_main_advances_after_canary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not activate from a canary whose protected target base has gone stale."""

    ruleset_id = 30
    pr_number = 5
    run_id = 77
    base_sha = "a" * 40
    head_sha = "b" * 40
    advanced_main_sha = "c" * 40
    workflow = (
        "name: Product\n"
        "acceptance: 'Product acceptance'\n"
        "metadata: 'Product metadata-only'\n"
    )
    main_reads = 0
    put_called = False

    def api(method: str, endpoint: str, **kwargs: object) -> dict[str, object]:
        nonlocal main_reads, put_called
        if endpoint.endswith(f"pulls/{pr_number}"):
            return {
                "state": "open",
                "draft": False,
                "head": {"sha": head_sha},
                "base": {"ref": p.TARGET_BRANCH, "sha": base_sha},
            }
        if endpoint.endswith(f"git/ref/heads/{p.TARGET_BRANCH}"):
            main_reads += 1
            current = base_sha if main_reads == 1 else advanced_main_sha
            return {"object": {"sha": current}}
        if f"contents/{p.PRODUCT_WORKFLOW_PATH}" in endpoint:
            return {
                "type": "file",
                "encoding": "base64",
                "content": base64.b64encode(workflow.encode()).decode(),
            }
        if endpoint.endswith(f"actions/runs/{run_id}"):
            return {
                "name": p.PRODUCT_WORKFLOW_NAME,
                "event": "pull_request",
                "head_sha": head_sha,
                "status": "completed",
                "conclusion": "success",
                "check_suite_id": 900,
                "pull_requests": [
                    {
                        "number": pr_number,
                        "head": {"sha": head_sha},
                        "base": {"sha": base_sha},
                    }
                ],
            }
        if f"actions/runs/{run_id}/jobs" in endpoint:
            return {
                "jobs": [
                    {
                        "name": p.PRODUCT_CHECK,
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            }
        if "check-runs" in endpoint:
            return {
                "check_runs": [
                    {
                        "name": p.PRODUCT_CHECK,
                        "check_suite": {"id": 900},
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 15368},
                    }
                ]
            }
        if method == "PUT":
            put_called = True
            return {}
        raise AssertionError(endpoint)

    live_reads = 0
    before = _live_payload(ruleset_id)
    after = _live_payload(ruleset_id, enforcement="active", integration_id=15368)

    def live(_target: object) -> dict[str, object]:
        nonlocal live_reads
        live_reads += 1
        return before if live_reads <= 2 else after

    monkeypatch.setattr(p, "_assert_current_main", lambda _sha: None)
    monkeypatch.setattr(p, "_named_ruleset", lambda: {"id": ruleset_id})
    monkeypatch.setattr(p, "_assert_target_provenance", lambda *_args: None)
    monkeypatch.setattr(p, "_live", live)
    monkeypatch.setattr(p, "_latest_history_version", lambda _target: 4)
    monkeypatch.setattr(p, "_verify_ruleset_history_transition", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(p, "_gh_api", api)

    with pytest.raises(RulesetGovernanceError, match="current protected main"):
        p.activate_product_ruleset(
            {"ruleset_id": ruleset_id},
            expected_main_sha="d" * 40,
            canary_pr=pr_number,
            canary_run_id=run_id,
        )

    assert main_reads >= 2
    assert put_called is False
