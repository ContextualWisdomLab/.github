"""Regression coverage for the scheduler branches introduced by PR #1541."""

from __future__ import annotations

import pytest

from scripts.ci import pr_review_fix_scheduler as fix
from scripts.ci import pr_review_merge_scheduler as merge


def _pr(**overrides: object) -> dict[str, object]:
    """Return a minimal same-repository pull-request fixture."""
    value: dict[str, object] = {
        "number": 7,
        "isDraft": False,
        "baseRefName": "main",
        "baseRefOid": "b" * 40,
        "headRefName": "feature",
        "headRefOid": "a" * 40,
        "headRepository": {"nameWithOwner": "owner/repo"},
        "mergeStateStatus": "CLEAN",
        "reviews": {"nodes": []},
        "reviewThreads": {"nodes": []},
    }
    value.update(overrides)
    return value


def test_conflicted_draft_skips_before_repair_authority() -> None:
    """A conflicted draft remains a draft skip rather than an RCA dispatch."""
    args = fix.parse_args(["--repo", "owner/repo", "--base-branch", "main"])

    assert fix.inspect_pr(
        "owner/repo",
        _pr(isDraft=True, mergeStateStatus="DIRTY"),
        args,
    ) == ("skip", ("draft PR",))


def test_conflicted_unapproved_pr_fails_closed_without_repair_authority() -> None:
    """A conflict without explicit unreviewed-repair authority stays closed."""
    args = fix.parse_args(["--repo", "owner/repo", "--base-branch", "main"])

    assert fix.inspect_pr(
        "owner/repo",
        _pr(mergeStateStatus="DIRTY"),
        args,
    ) == ("skip", ("merge conflict is not authorized for repair",))


def test_workflow_name_rest_fallback_paginates_and_filters_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workflow identity pagination keeps only rows with usable names."""
    page_one = [{"check_suite_id": index, "name": f"workflow-{index}"} for index in range(99)]
    page_one.append({"check_suite_id": 99, "name": ""})
    calls: list[str] = []

    def fake_api(path: str) -> dict[str, object]:
        calls.append(path)
        if path.endswith("page=1"):
            return {"workflow_runs": page_one}
        return {"workflow_runs": [{"check_suite_id": 100, "name": "opencode-review"}]}

    monkeypatch.setattr(merge, "gh_api_json", fake_api)

    names = merge.fetch_workflow_names_by_check_suite_rest("owner/repo", "a" * 40)

    assert names[0] == "workflow-0"
    assert 99 not in names
    assert names[100] == "opencode-review"
    assert calls == [
        f"repos/owner/repo/actions/runs?head_sha={'a' * 40}&per_page=100&page=1",
        f"repos/owner/repo/actions/runs?head_sha={'a' * 40}&per_page=100&page=2",
    ]


def test_workflow_name_rest_fallback_treats_permission_denial_as_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inaccessible Actions inventory returns an empty fail-closed map."""

    def fake_api(_path: str) -> dict[str, object]:
        raise RuntimeError("Resource not accessible by integration")

    monkeypatch.setattr(merge, "gh_api_json", fake_api)

    assert merge.fetch_workflow_names_by_check_suite_rest("owner/repo", "a" * 40) == {}


def test_workflow_name_rest_fallback_propagates_unrelated_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transport failures other than permission denial remain visible."""

    def fake_api(_path: str) -> dict[str, object]:
        raise RuntimeError("gh: HTTP 502 (exhausted retries)")

    monkeypatch.setattr(merge, "gh_api_json", fake_api)

    with pytest.raises(RuntimeError, match="HTTP 502"):
        merge.fetch_workflow_names_by_check_suite_rest("owner/repo", "a" * 40)
