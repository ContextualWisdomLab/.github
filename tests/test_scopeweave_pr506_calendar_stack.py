from pathlib import Path

import pytest

from scripts.ci import scopeweave_pr506_calendar_stack as sut

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "scopeweave_pr506_calendar_stack.py"


def event_payload(*, number: int = 506, merged: bool = True, action: str = "closed") -> dict:
    return {
        "action": action,
        "repository": {"full_name": "ContextualWisdomLab/scopeweave"},
        "pull_request": {"number": number, "merged": merged},
    }


def test_control_plane_script_exists() -> None:
    assert SCRIPT.is_file(), "the trusted event handler must exist"


def test_validate_trigger_accepts_only_actual_scopeweave_506_merge() -> None:
    sut.validate_trigger(event_payload())


@pytest.mark.parametrize(
    "payload",
    [
        event_payload(merged=False),
        event_payload(number=505),
        event_payload(action="opened"),
        {
            **event_payload(),
            "repository": {"full_name": "ContextualWisdomLab/other"},
        },
    ],
)
def test_validate_trigger_rejects_every_non_target_event(payload: dict) -> None:
    with pytest.raises(Exception, match="ScopeWeave PR #506 actual merged event"):
        sut.validate_trigger(payload)


def test_prerequisite_requires_live_merge_inside_protected_develop() -> None:
    prerequisite = {
        "state": "closed",
        "merged": True,
        "merge_commit_sha": "a" * 40,
    }
    develop = {"name": "develop", "protected": True, "sha": "b" * 40}

    assert sut.prerequisite_resolved(prerequisite, develop, "ahead") is True
    assert sut.prerequisite_resolved(prerequisite, develop, "identical") is True
    assert sut.prerequisite_resolved(prerequisite, develop, "diverged") is False
    assert sut.prerequisite_resolved(
        prerequisite, {**develop, "protected": False}, "ahead"
    ) is False
    assert sut.prerequisite_resolved(
        {**prerequisite, "merged": False}, develop, "ahead"
    ) is False


def test_restack_plan_defers_child_when_first_pr_must_reconcile() -> None:
    plan = sut.assess_restack(
        protected_branch="develop",
        first_base_ref="feat/access-grant-domain-413",
        develop_to_first_status="diverged",
        first_head_ref="calendar-domain",
        second_base_ref="calendar-domain",
        first_to_second_status="ahead",
    )

    assert plan.first_action == "restack"
    assert plan.second_action == "restack-after-539"
    assert plan.review_ready_order == (539, 541)


def test_restack_plan_distinguishes_retarget_only_from_child_restack() -> None:
    plan = sut.assess_restack(
        protected_branch="develop",
        first_base_ref="feat/access-grant-domain-413",
        develop_to_first_status="ahead",
        first_head_ref="calendar-domain",
        second_base_ref="wrong-parent",
        first_to_second_status="diverged",
    )

    assert plan.first_action == "retarget"
    assert plan.second_action == "restack-now"


def test_restack_plan_is_stable_when_bases_and_ancestry_are_current() -> None:
    plan = sut.assess_restack(
        protected_branch="develop",
        first_base_ref="develop",
        develop_to_first_status="ahead",
        first_head_ref="calendar-domain",
        second_base_ref="calendar-domain",
        first_to_second_status="ahead",
    )

    assert plan.first_action == "none"
    assert plan.second_action == "none"


def test_check_summary_uses_latest_exact_context_and_flags_absent_required() -> None:
    summary = sut.summarize_checks(
        required_contexts=(
            "unit-and-api",
            "cloud-e2e",
            "Analyze (python)",
            "property fuzz",
        ),
        check_runs=(
            {
                "id": 1,
                "name": "unit-and-api",
                "status": "completed",
                "conclusion": "failure",
            },
            {
                "id": 2,
                "name": "unit-and-api",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "id": 3,
                "name": "cloud-e2e",
                "status": "in_progress",
                "conclusion": None,
            },
        ),
        statuses=(
            {"id": 4, "context": "Analyze (python)", "state": "success"},
        ),
    )

    assert summary.required_states == {
        "unit-and-api": "success",
        "cloud-e2e": "pending",
        "Analyze (python)": "success",
        "property fuzz": "absent",
    }
    assert summary.blockers == ("cloud-e2e:pending", "property fuzz:absent")
    assert summary.all_required_passing is False
    assert summary.counts["success"] == 2


def test_check_summary_passes_only_when_every_required_context_succeeds() -> None:
    summary = sut.summarize_checks(
        required_contexts=("unit-and-api",),
        check_runs=(
            {
                "id": 8,
                "name": "unit-and-api",
                "status": "completed",
                "conclusion": "success",
            },
        ),
        statuses=(),
    )

    assert summary.all_required_passing is True
    assert summary.blockers == ()


def test_review_summary_binds_approval_and_change_request_to_exact_head() -> None:
    head_sha = "c" * 40
    summary = sut.summarize_reviews(
        head_sha=head_sha,
        author_login="cursor[bot]",
        reviews=(
            {
                "id": 1,
                "state": "APPROVED",
                "commit_id": "d" * 40,
                "user": {"login": "alice", "type": "User"},
            },
            {
                "id": 2,
                "state": "APPROVED",
                "commit_id": head_sha,
                "user": {"login": "cursor[bot]", "type": "Bot"},
            },
            {
                "id": 3,
                "state": "APPROVED",
                "commit_id": head_sha,
                "user": {"login": "bob", "type": "User"},
            },
            {
                "id": 4,
                "state": "CHANGES_REQUESTED",
                "commit_id": head_sha,
                "user": {"login": "carol", "type": "User"},
            },
        ),
        threads=(
            {"id": "resolved", "isResolved": True},
            {"id": "open", "isResolved": False},
        ),
    )

    assert summary.total_submissions == 4
    assert summary.current_approvals == ("bob", "cursor[bot]")
    assert summary.qualifying_independent_approvals == ("bob",)
    assert summary.current_changes_requested == ("carol",)
    assert summary.stale_reviewers == ("alice",)
    assert summary.unresolved_threads == 1


def test_review_summary_is_empty_without_formal_reviews_or_threads() -> None:
    summary = sut.summarize_reviews(
        head_sha="e" * 40,
        author_login="cursor[bot]",
        reviews=(),
        threads=(),
    )

    assert summary.total_submissions == 0
    assert summary.qualifying_independent_approvals == ()
    assert summary.current_changes_requested == ()
    assert summary.unresolved_threads == 0


def test_select_managed_comment_updates_only_exact_bot_owned_marker() -> None:
    comments = (
        {
            "id": 10,
            "body": "<!-- scopeweave-pr506-calendar-stack:v1 target=539 -->\nhuman",
            "user": {"login": "alice"},
        },
        {
            "id": 11,
            "body": "<!-- scopeweave-pr506-calendar-stack:v1 target=541 -->\nbot",
            "user": {"login": "github-actions[bot]"},
        },
        {
            "id": 12,
            "body": "<!-- scopeweave-pr506-calendar-stack:v1 target=539 -->\nbot",
            "user": {"login": "github-actions[bot]"},
        },
    )

    assert sut.select_managed_comment(comments, 539) == 12
    assert sut.select_managed_comment(comments, 541) == 11


def test_select_managed_comment_fails_closed_on_duplicate_bot_markers() -> None:
    marker = "<!-- scopeweave-pr506-calendar-stack:v1 target=539 -->"
    comments = (
        {"id": 1, "body": marker, "user": {"login": "github-actions[bot]"}},
        {"id": 2, "body": marker, "user": {"login": "github-actions[bot]"}},
    )

    with pytest.raises(Exception, match="duplicate managed comments"):
        sut.select_managed_comment(comments, 539)


def make_pr_state(
    number: int,
    *,
    head_ref: str,
    head_sha: str,
    base_ref: str,
    base_sha: str,
    draft: bool,
    merged: bool = False,
    state: str = "open",
    merge_commit_sha: str | None = None,
) -> object:
    return sut.PullRequestState(
        number=number,
        state=state,
        merged=merged,
        draft=draft,
        base_ref=base_ref,
        base_sha=base_sha,
        head_ref=head_ref,
        head_sha=head_sha,
        merge_commit_sha=merge_commit_sha,
        author_login="cursor[bot]" if number != 506 else "seonghobae",
        mergeable=True,
        mergeable_state="blocked" if draft else "clean",
    )


def test_render_report_contains_live_stack_evidence_and_order() -> None:
    checks = sut.CheckSummary(
        required_states={"unit-and-api": "success", "property fuzz": "absent"},
        counts={"success": 3},
        blockers=("property fuzz:absent",),
        all_required_passing=False,
    )
    reviews = sut.ReviewSummary(
        total_submissions=0,
        current_approvals=(),
        qualifying_independent_approvals=(),
        current_changes_requested=(),
        stale_reviewers=(),
        unresolved_threads=0,
    )
    audit = sut.StackAudit(
        develop=sut.DevelopState(
            name="develop",
            sha="b" * 40,
            protected=True,
            required_contexts=("unit-and-api", "property fuzz"),
        ),
        prerequisite=make_pr_state(
            506,
            head_ref="feat/access-grant-domain-413",
            head_sha="a" * 40,
            base_ref="develop",
            base_sha="1" * 40,
            draft=False,
            merged=True,
            state="closed",
            merge_commit_sha="9" * 40,
        ),
        prerequisite_resolved=True,
        merge_to_develop_status="ahead",
        first=sut.PullRequestAudit(
            pull_request=make_pr_state(
                539,
                head_ref="calendar-domain",
                head_sha="c" * 40,
                base_ref="feat/access-grant-domain-413",
                base_sha="a" * 40,
                draft=True,
            ),
            checks=checks,
            reviews=reviews,
        ),
        second=sut.PullRequestAudit(
            pull_request=make_pr_state(
                541,
                head_ref="calendar-sqlite",
                head_sha="d" * 40,
                base_ref="calendar-domain",
                base_sha="c" * 40,
                draft=True,
            ),
            checks=checks,
            reviews=reviews,
        ),
        prerequisite_to_first_status="ahead",
        develop_to_first_status="diverged",
        first_to_second_status="ahead",
        restack=sut.RestackAssessment(
            first_action="restack",
            second_action="restack-after-539",
        ),
    )

    report = sut.render_report(audit, target_pr=539)

    assert report.startswith(
        "<!-- scopeweave-pr506-calendar-stack:v1 target=539 -->"
    )
    assert "protected `develop@bbbbbbbbbbbb`" in report
    assert "#506 prerequisite: **resolved**" in report
    assert (
        "#539 `calendar-domain@cccccccccccc` → "
        "`feat/access-grant-domain-413@aaaaaaaaaaaa`"
    ) in report
    assert "Draft: **yes**" in report
    assert "`property fuzz`: `absent`" in report
    assert "formal submissions 0" in report
    assert "unresolved threads 0" in report
    assert "1. **#539 first**" in report
    assert "2. **#541 second**" in report
    assert "No source branch, Draft flag, base, review, or merge state was mutated" in report


def test_required_workflow_has_exact_merged_only_gate_and_trusted_checkout() -> None:
    workflow = ROOT / ".github" / "workflows" / "opencode-review.yml"
    text = workflow.read_text(encoding="utf-8")

    assert "types: [opened, synchronize, reopened, ready_for_review, closed]" in text
    assert "scopeweave-pr506-calendar-stack:" in text
    assert "github.repository == 'ContextualWisdomLab/scopeweave'" in text
    assert "github.event.action == 'closed'" in text
    assert "github.event.pull_request.number == 506" in text
    assert "github.event.pull_request.merged == true" in text
    assert "repository: ContextualWisdomLab/.github" in text
    assert "scripts/ci/scopeweave_pr506_calendar_stack.py" in text
    assert "issues: write" in text
    assert "pull-requests: read" in text


def pr_payload(
    number: int,
    *,
    head_ref: str,
    head_sha: str,
    base_ref: str,
    base_sha: str,
    draft: bool,
    state: str = "open",
    merged: bool = False,
    merge_commit_sha: str | None = None,
    author: str = "cursor[bot]",
) -> dict:
    return {
        "number": number,
        "state": state,
        "merged": merged,
        "draft": draft,
        "base": {
            "ref": base_ref,
            "sha": base_sha,
            "repo": {"full_name": "ContextualWisdomLab/scopeweave"},
        },
        "head": {
            "ref": head_ref,
            "sha": head_sha,
            "repo": {"full_name": "ContextualWisdomLab/scopeweave"},
        },
        "merge_commit_sha": merge_commit_sha,
        "user": {"login": author},
        "mergeable": True,
        "mergeable_state": "blocked" if draft else "clean",
    }


def branch_payload(*, sha: str = "b" * 40, protected: bool = True) -> dict:
    return {
        "name": "develop",
        "commit": {"sha": sha},
        "protected": protected,
        "protection": {
            "required_status_checks": {
                "contexts": ["unit-and-api", "property fuzz"]
            }
        },
    }


def test_parse_live_pr_and_develop_reject_untrusted_shapes() -> None:
    parsed_pr = sut.parse_pull_request(
        pr_payload(
            539,
            head_ref="calendar-domain",
            head_sha="c" * 40,
            base_ref="feat/access-grant-domain-413",
            base_sha="a" * 40,
            draft=True,
        ),
        expected_number=539,
    )
    parsed_branch = sut.parse_develop(branch_payload())

    assert parsed_pr.head_ref == "calendar-domain"
    assert parsed_branch.required_contexts == ("unit-and-api", "property fuzz")

    wrong_repo = pr_payload(
        539,
        head_ref="calendar-domain",
        head_sha="c" * 40,
        base_ref="develop",
        base_sha="b" * 40,
        draft=True,
    )
    wrong_repo["head"]["repo"]["full_name"] = "attacker/fork"
    with pytest.raises(Exception, match="same-repository"):
        sut.parse_pull_request(wrong_repo, expected_number=539)

    with pytest.raises(Exception, match="invalid pull request"):
        sut.parse_pull_request(
            {**pr_payload(
                539,
                head_ref="calendar-domain",
                head_sha="bad",
                base_ref="develop",
                base_sha="b" * 40,
                draft=True,
            )},
            expected_number=539,
        )

    with pytest.raises(Exception, match="protected develop"):
        sut.parse_develop(branch_payload(protected=False))


class FakeApi:
    def __init__(self, responses: dict, threads: dict[int, list] | None = None) -> None:
        self.responses = responses
        self.threads = threads or {}
        self.calls: list[tuple] = []
        self.mutations: list[tuple] = []

    def get(self, path: str) -> object:
        self.calls.append(("GET", path))
        value = self.responses[path]
        return value() if callable(value) else value

    def get_paginated_list(self, path: str, *, key: str | None = None) -> list:
        self.calls.append(("GET_ALL", path, key))
        value = self.responses[path]
        if key is not None and isinstance(value, dict):
            return list(value[key])
        return list(value)

    def review_threads(self, pr_number: int) -> list:
        self.calls.append(("THREADS", pr_number))
        return list(self.threads.get(pr_number, []))

    def post(self, path: str, payload: dict) -> object:
        self.mutations.append(("POST", path, payload))
        return {"id": 999}

    def patch(self, path: str, payload: dict) -> object:
        self.mutations.append(("PATCH", path, payload))
        return {"id": int(path.rsplit("/", 1)[1])}


def live_api_responses() -> dict:
    repo = "/repos/ContextualWisdomLab/scopeweave"
    prerequisite_head = "a" * 40
    prerequisite_merge = "9" * 40
    develop_sha = "b" * 40
    first_head = "c" * 40
    second_head = "d" * 40
    return {
        f"{repo}/pulls/506": pr_payload(
            506,
            head_ref="feat/access-grant-domain-413",
            head_sha=prerequisite_head,
            base_ref="develop",
            base_sha="1" * 40,
            draft=False,
            state="closed",
            merged=True,
            merge_commit_sha=prerequisite_merge,
            author="seonghobae",
        ),
        f"{repo}/branches/develop": branch_payload(sha=develop_sha),
        f"{repo}/pulls/539": pr_payload(
            539,
            head_ref="calendar-domain",
            head_sha=first_head,
            base_ref="feat/access-grant-domain-413",
            base_sha=prerequisite_head,
            draft=True,
        ),
        f"{repo}/pulls/541": pr_payload(
            541,
            head_ref="calendar-sqlite",
            head_sha=second_head,
            base_ref="calendar-domain",
            base_sha=first_head,
            draft=True,
        ),
        f"{repo}/compare/{prerequisite_merge}...{develop_sha}": {"status": "ahead"},
        f"{repo}/compare/{prerequisite_head}...{first_head}": {"status": "ahead"},
        f"{repo}/compare/{develop_sha}...{first_head}": {"status": "diverged"},
        f"{repo}/compare/{first_head}...{second_head}": {"status": "ahead"},
        f"{repo}/commits/{first_head}/check-runs": {
            "check_runs": [
                {
                    "id": 1,
                    "name": "unit-and-api",
                    "status": "completed",
                    "conclusion": "success",
                }
            ]
        },
        f"{repo}/commits/{first_head}/status": {
            "statuses": [
                {"id": 2, "context": "property fuzz", "state": "success"}
            ]
        },
        f"{repo}/pulls/539/reviews": [],
        f"{repo}/commits/{second_head}/check-runs": {
            "check_runs": [
                {
                    "id": 3,
                    "name": "unit-and-api",
                    "status": "completed",
                    "conclusion": "success",
                }
            ]
        },
        f"{repo}/commits/{second_head}/status": {
            "statuses": [
                {"id": 4, "context": "property fuzz", "state": "success"}
            ]
        },
        f"{repo}/pulls/541/reviews": [],
        f"{repo}/issues/539/comments": [],
        f"{repo}/issues/541/comments": [],
    }


def test_collect_stack_audit_refetches_all_live_evidence() -> None:
    api = FakeApi(live_api_responses())

    audit = sut.collect_stack_audit(api, event_payload())

    assert audit.prerequisite_resolved is True
    assert audit.develop.sha == "b" * 40
    assert audit.first.pull_request.head_sha == "c" * 40
    assert audit.second.pull_request.base_sha == "c" * 40
    assert audit.first.checks.all_required_passing is True
    assert audit.second.reviews.total_submissions == 0
    assert audit.restack.first_action == "restack"
    assert audit.restack.second_action == "restack-after-539"
    assert ("THREADS", 539) in api.calls
    assert ("THREADS", 541) in api.calls


def test_collect_stack_audit_rejects_live_unmerged_prerequisite() -> None:
    responses = live_api_responses()
    responses["/repos/ContextualWisdomLab/scopeweave/pulls/506"] = {
        **responses["/repos/ContextualWisdomLab/scopeweave/pulls/506"],
        "state": "open",
        "merged": False,
        "merge_commit_sha": None,
    }
    api = FakeApi(responses)

    with pytest.raises(Exception, match="live #506 is not merged"):
        sut.collect_stack_audit(api, event_payload())

    assert not api.mutations


def test_upsert_report_creates_updates_and_noops_exact_bot_comment() -> None:
    repo = "/repos/ContextualWisdomLab/scopeweave"
    marker = sut.managed_marker(539)

    create_api = FakeApi({f"{repo}/issues/539/comments": []})
    assert sut.upsert_report(create_api, 539, marker + "\nnew") == "created"
    assert create_api.mutations == [
        ("POST", f"{repo}/issues/539/comments", {"body": marker + "\nnew"})
    ]

    update_api = FakeApi(
        {
            f"{repo}/issues/539/comments": [
                {
                    "id": 7,
                    "body": marker + "\nold",
                    "user": {"login": "github-actions[bot]"},
                }
            ]
        }
    )
    assert sut.upsert_report(update_api, 539, marker + "\nnew") == "updated"
    assert update_api.mutations == [
        ("PATCH", f"{repo}/issues/comments/7", {"body": marker + "\nnew"})
    ]

    noop_api = FakeApi(
        {
            f"{repo}/issues/539/comments": [
                {
                    "id": 8,
                    "body": marker + "\nnew",
                    "user": {"login": "github-actions[bot]"},
                }
            ]
        }
    )
    assert sut.upsert_report(noop_api, 539, marker + "\nnew") == "unchanged"
    assert noop_api.mutations == []


def test_execute_publishes_one_combined_report_to_each_calendar_pr(tmp_path: Path) -> None:
    api = FakeApi(live_api_responses())
    summary_path = tmp_path / "summary.md"

    result = sut.execute(api, event_payload(), summary_path=summary_path)

    assert result == {539: "created", 541: "created"}
    assert [mutation[1] for mutation in api.mutations] == [
        "/repos/ContextualWisdomLab/scopeweave/issues/539/comments",
        "/repos/ContextualWisdomLab/scopeweave/issues/541/comments",
    ]
    summary = summary_path.read_text(encoding="utf-8")
    assert "#506 merge-triggered calendar-subscription stack audit" in summary
    assert "target=539" not in summary


class FakeHttpResponse:
    def __init__(self, payload: object) -> None:
        import json

        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def read(self, amount: int = -1) -> bytes:
        return self.body if amount < 0 else self.body[:amount]


def test_github_api_binds_token_method_payload_and_allowed_path() -> None:
    import json

    captured: list[tuple] = []

    def opener(request, timeout: int):
        captured.append((request, timeout))
        return FakeHttpResponse({"ok": True})

    api = sut.GitHubApi("secret-token", opener=opener, timeout=7)
    result = api.post(
        "/repos/ContextualWisdomLab/scopeweave/issues/539/comments",
        {"body": "hello"},
    )

    assert result == {"ok": True}
    request, timeout = captured[0]
    assert timeout == 7
    assert request.method == "POST"
    assert request.full_url.endswith("/issues/539/comments")
    assert request.get_header("Authorization") == "Bearer secret-token"
    assert json.loads(request.data.decode("utf-8")) == {"body": "hello"}

    with pytest.raises(Exception, match="disallowed GitHub API path"):
        api.get("/repos/attacker/repo/pulls/1")


def test_github_api_paginates_rest_lists_and_keyed_objects() -> None:
    import json
    from urllib.parse import parse_qs, urlparse

    def opener(request, timeout: int):
        del timeout
        page = int(parse_qs(urlparse(request.full_url).query)["page"][0])
        if "check-runs" in request.full_url:
            payload = {
                "check_runs": (
                    [{"id": i} for i in range(100)]
                    if page == 1
                    else [{"id": 101}]
                )
            }
        else:
            payload = ([{"id": i} for i in range(100)] if page == 1 else [{"id": 101}])
        return FakeHttpResponse(json.loads(json.dumps(payload)))

    api = sut.GitHubApi("token", opener=opener)
    keyed = api.get_paginated_list(
        "/repos/ContextualWisdomLab/scopeweave/commits/" + "a" * 40 + "/check-runs",
        key="check_runs",
    )
    plain = api.get_paginated_list(
        "/repos/ContextualWisdomLab/scopeweave/pulls/539/reviews"
    )

    assert len(keyed) == 101
    assert len(plain) == 101


def test_github_api_paginates_graphql_review_threads() -> None:
    import json

    requests: list[dict] = []

    def opener(request, timeout: int):
        del timeout
        body = json.loads(request.data.decode("utf-8"))
        requests.append(body)
        cursor = body["variables"].get("cursor")
        nodes = (
            [{"id": "first", "isResolved": False}]
            if cursor is None
            else [{"id": "second", "isResolved": True}]
        )
        page_info = (
            {"hasNextPage": True, "endCursor": "cursor-1"}
            if cursor is None
            else {"hasNextPage": False, "endCursor": None}
        )
        return FakeHttpResponse(
            {
                "data": {
                    "repository": {
                        "pullRequest": {
                            "reviewThreads": {
                                "nodes": nodes,
                                "pageInfo": page_info,
                            }
                        }
                    }
                }
            }
        )

    api = sut.GitHubApi("token", opener=opener)
    threads = api.review_threads(539)

    assert [thread["id"] for thread in threads] == ["first", "second"]
    assert requests[0]["variables"]["number"] == 539
    assert requests[1]["variables"]["cursor"] == "cursor-1"


def test_main_reads_exact_event_file_and_reports_publication(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    import json

    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event_payload()), encoding="utf-8")
    summary_path = tmp_path / "summary.md"
    fake_api = object()
    observed: dict = {}

    monkeypatch.setenv("GITHUB_TOKEN", "token")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    monkeypatch.setattr(sut, "GitHubApi", lambda token: fake_api)

    def fake_execute(api, event, *, summary_path):
        observed.update(api=api, event=event, summary_path=summary_path)
        return {539: "created", 541: "updated"}

    monkeypatch.setattr(sut, "execute", fake_execute)

    assert sut.main(["--event-path", str(event_path)]) == 0
    assert observed == {
        "api": fake_api,
        "event": event_payload(),
        "summary_path": str(summary_path),
    }
    assert json.loads(capsys.readouterr().out) == {
        "539": "created",
        "541": "updated",
    }


def test_main_fails_closed_without_token(monkeypatch, tmp_path: Path, capsys) -> None:
    import json

    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event_payload()), encoding="utf-8")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    assert sut.main(["--event-path", str(event_path)]) == 1
    assert "GITHUB_TOKEN is required" in capsys.readouterr().err


def test_check_summary_ignores_malformed_and_older_duplicate_evidence() -> None:
    summary = sut.summarize_checks(
        required_contexts=("shared", "status-only", "unknown-run"),
        check_runs=(
            {"id": 1, "name": None, "status": "completed", "conclusion": "success"},
            {"id": 5, "name": "shared", "status": "completed", "conclusion": "success"},
            {"id": 4, "name": "shared", "status": "completed", "conclusion": "failure"},
            {"id": 6, "name": "unknown-run", "status": "completed", "conclusion": None},
        ),
        statuses=(
            {"id": 1, "context": None, "state": "success"},
            {"id": 5, "context": "status-only", "state": None},
            {"id": 4, "context": "status-only", "state": "failure"},
            {"id": 7, "context": "shared", "state": "failure"},
        ),
    )

    assert summary.required_states == {
        "shared": "success",
        "status-only": "unknown",
        "unknown-run": "unknown",
    }


def test_review_summary_ignores_invalid_reviewers_and_older_duplicate_states() -> None:
    head_sha = "a" * 40
    summary = sut.summarize_reviews(
        head_sha=head_sha,
        author_login="author",
        reviews=(
            {"id": 1, "state": "APPROVED", "commit_id": head_sha, "user": None},
            {
                "id": 5,
                "state": "COMMENTED",
                "commit_id": head_sha,
                "user": {"login": "alice", "type": "User"},
            },
            {
                "id": 4,
                "state": "APPROVED",
                "commit_id": head_sha,
                "user": {"login": "alice", "type": "User"},
            },
            {
                "id": 6,
                "state": "APPROVED",
                "commit_id": head_sha,
                "user": {"login": "robot[bot]", "type": "User"},
            },
        ),
        threads=(),
    )

    assert summary.total_submissions == 4
    assert summary.current_approvals == ("robot[bot]",)
    assert summary.qualifying_independent_approvals == ()


def test_small_formatting_and_validation_fail_closed_paths() -> None:
    assert sut._format_checks(sut.CheckSummary()) == "- required contexts: none declared"
    with pytest.raises(Exception, match="managed comment target"):
        sut.managed_marker(500)
    with pytest.raises(Exception, match="invalid GitHub comparison"):
        sut.comparison_status({"status": "unknown"})

    branch = branch_payload()
    branch.pop("protection")
    assert sut.parse_develop(branch).required_contexts == ()


def test_render_report_rejects_unbounded_comment() -> None:
    from dataclasses import replace

    audit = sut.collect_stack_audit(FakeApi(live_api_responses()), event_payload())
    huge_checks = sut.CheckSummary(
        required_states={"x" * 61_000: "success"},
        counts={"success": 1},
        blockers=(),
        all_required_passing=True,
    )
    audit = replace(
        audit,
        first=replace(audit.first, checks=huge_checks),
    )

    with pytest.raises(Exception, match="exceeds the bounded comment size"):
        sut.render_report(audit, target_pr=539)


def test_upsert_report_rejects_unmarked_body_and_execute_supports_no_summary() -> None:
    with pytest.raises(Exception, match="missing its exact marker"):
        sut.upsert_report(FakeApi({}), 539, "not managed")

    api = FakeApi(live_api_responses())
    assert sut.execute(api, event_payload(), summary_path=None) == {
        539: "created",
        541: "created",
    }


class RawHttpResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "RawHttpResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        return False

    def read(self, amount: int = -1) -> bytes:
        return self.body if amount < 0 else self.body[:amount]


@pytest.mark.parametrize("token", ["", "   ", None])
def test_github_api_rejects_missing_tokens(token) -> None:
    with pytest.raises(Exception, match="GITHUB_TOKEN is required"):
        sut.GitHubApi(token)


@pytest.mark.parametrize("timeout", [0, 121, "20"])
def test_github_api_rejects_invalid_timeouts(timeout) -> None:
    with pytest.raises(Exception, match="timeout must be between"):
        sut.GitHubApi("token", timeout=timeout)


@pytest.mark.parametrize("path", ["", None, "/" + "x" * 2_048])
def test_github_api_rejects_malformed_paths(path) -> None:
    api = sut.GitHubApi("token", opener=lambda request, timeout: None)
    with pytest.raises(Exception, match="disallowed GitHub API path"):
        api.get(path)


def test_github_api_rejects_methods_get_payloads_and_oversized_payloads() -> None:
    api = sut.GitHubApi("token", opener=lambda request, timeout: None)
    path = "/repos/ContextualWisdomLab/scopeweave/pulls/539"
    with pytest.raises(Exception, match="disallowed GitHub API method"):
        api._request("DELETE", path)
    with pytest.raises(Exception, match="GET requests cannot carry"):
        api._request("GET", path, {"unexpected": True})
    with pytest.raises(Exception, match="payload exceeds"):
        api.post(
            "/repos/ContextualWisdomLab/scopeweave/issues/539/comments",
            {"body": "x" * (300 * 1024)},
        )


def test_github_api_patch_uses_patch_method() -> None:
    captured = []

    def opener(request, timeout):
        captured.append((request.method, timeout))
        return FakeHttpResponse({"ok": True})

    api = sut.GitHubApi("token", opener=opener)
    assert api.patch(
        "/repos/ContextualWisdomLab/scopeweave/issues/comments/7",
        {"body": "updated"},
    ) == {"ok": True}
    assert captured == [("PATCH", 20)]


def test_github_api_normalizes_transport_and_response_failures(monkeypatch) -> None:
    from urllib.error import HTTPError, URLError

    path = "/repos/ContextualWisdomLab/scopeweave/pulls/539"

    failures = (
        (
            lambda request, timeout: (_ for _ in ()).throw(
                HTTPError(request.full_url, 403, "forbidden", None, None)
            ),
            r"HTTP failure \(403\)",
        ),
        (lambda request, timeout: (_ for _ in ()).throw(URLError("offline")), "transport failure"),
        (lambda request, timeout: (_ for _ in ()).throw(TimeoutError()), "timed out"),
    )
    for opener, message in failures:
        with pytest.raises(Exception, match=message):
            sut.GitHubApi("token", opener=opener).get(path)

    monkeypatch.setattr(sut, "_MAX_RESPONSE_BYTES", 4)
    with pytest.raises(Exception, match="response exceeds"):
        sut.GitHubApi("token", opener=lambda request, timeout: RawHttpResponse(b"12345")).get(path)

    monkeypatch.setattr(sut, "_MAX_RESPONSE_BYTES", 128)
    with pytest.raises(Exception, match="invalid JSON"):
        sut.GitHubApi(
            "token",
            opener=lambda request, timeout: RawHttpResponse(b"not-json"),
        ).get(path)


def test_github_api_rejects_invalid_rest_pages_and_page_exhaustion(monkeypatch) -> None:
    path = "/repos/ContextualWisdomLab/scopeweave/commits/" + "a" * 40 + "/check-runs"

    api = sut.GitHubApi("token", opener=lambda request, timeout: FakeHttpResponse([]))
    with pytest.raises(Exception, match="invalid list shape"):
        api.get_paginated_list(path, key="check_runs")

    monkeypatch.setattr(sut, "_MAX_PAGES", 1)
    api = sut.GitHubApi(
        "token",
        opener=lambda request, timeout: FakeHttpResponse(
            {"check_runs": [{"id": value} for value in range(100)]}
        ),
    )
    with pytest.raises(Exception, match="pagination exceeded"):
        api.get_paginated_list(path, key="check_runs")


def graphql_payload(*, nodes=None, has_next=False, cursor=None) -> dict:
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [] if nodes is None else nodes,
                        "pageInfo": {
                            "hasNextPage": has_next,
                            "endCursor": cursor,
                        },
                    }
                }
            }
        }
    }


def test_github_api_rejects_invalid_review_thread_targets_and_shapes() -> None:
    with pytest.raises(Exception, match="target must be"):
        sut.GitHubApi("token", opener=lambda request, timeout: None).review_threads(500)

    responses = (
        ({"errors": [{"message": "no"}]}, "query failed"),
        ({"data": {}}, "response is invalid"),
        (graphql_payload(nodes=[1]), "review thread is invalid"),
        (graphql_payload(has_next=True, cursor=None), "cursor is invalid"),
    )
    for payload, message in responses:
        api = sut.GitHubApi(
            "token", opener=lambda request, timeout, value=payload: FakeHttpResponse(value)
        )
        with pytest.raises(Exception, match=message):
            api.review_threads(539)


def test_github_api_rejects_graphql_page_exhaustion(monkeypatch) -> None:
    monkeypatch.setattr(sut, "_MAX_PAGES", 1)
    api = sut.GitHubApi(
        "token",
        opener=lambda request, timeout: FakeHttpResponse(
            graphql_payload(has_next=True, cursor="next")
        ),
    )
    with pytest.raises(Exception, match="GraphQL pagination exceeded"):
        api.review_threads(539)


def test_load_event_rejects_unreadable_oversized_invalid_and_nonobject_files(
    monkeypatch, tmp_path: Path
) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(Exception, match="unable to read"):
        sut._load_event(str(missing))

    monkeypatch.setattr(sut, "_MAX_EVENT_BYTES", 4)
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"12345")
    with pytest.raises(Exception, match="exceeds the bound"):
        sut._load_event(str(oversized))

    monkeypatch.setattr(sut, "_MAX_EVENT_BYTES", 128)
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not-json", encoding="utf-8")
    with pytest.raises(Exception, match="invalid JSON"):
        sut._load_event(str(invalid))

    nonobject = tmp_path / "list.json"
    nonobject.write_text("[]", encoding="utf-8")
    with pytest.raises(Exception, match="must be a JSON object"):
        sut._load_event(str(nonobject))


def test_module_entrypoint_exits_through_main(monkeypatch, tmp_path: Path) -> None:
    import runpy
    import sys

    event_path = tmp_path / "event.json"
    event_path.write_text("{}", encoding="utf-8")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--event-path", str(event_path)])

    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert error.value.code == 1
