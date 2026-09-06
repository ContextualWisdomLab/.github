"""Regression tests for exact-head canonical coverage-evidence quoting."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import opencode_coverage_identity as identity


def coverage_check(
    *,
    head: str,
    conclusion: str = "success",
    workflow: str = "Required OpenCode Review",
    name: str = "coverage-evidence",
    status: str = "completed",
) -> dict[str, object]:
    """Build one GitHub check-run object for coverage identity tests."""
    return {
        "name": name,
        "head_sha": head,
        "status": status,
        "conclusion": conclusion,
        "check_suite": {"workflow_run": {"workflow": {"name": workflow}}},
    }


def test_kaefa_78_and_75_reject_false_failure_quotes() -> None:
    """Canonical exact-head success must not be quoted as coverage failure."""
    for head in (identity.KAEFA_78_HEAD, identity.KAEFA_75_HEAD):
        checks = [coverage_check(head=head, conclusion="success")]
        assert identity.terminal_coverage_result(checks, head) == "success"
        with pytest.raises(identity.CoverageQuoteError, match="does not match"):
            identity.assert_quoted_matches("failure", checks, head)
        assert identity.assert_quoted_matches("success", checks, head) == "success"


def test_kaefa_79_missing_canonical_check_fails_closed() -> None:
    """A stub-only head without canonical coverage-evidence cannot be quoted."""
    with pytest.raises(identity.CoverageQuoteError, match="no completed canonical"):
        identity.terminal_coverage_result([], identity.KAEFA_79_HEAD)


def test_identity_helpers_cover_malformed_and_noncanonical_checks() -> None:
    """Malformed SHA, other workflows, and in-progress checks fail closed."""
    assert identity.normalize_result("SUCCESS") == "success"
    assert identity.normalize_result("nope") == "unknown"
    assert identity.check_head_sha({"headSha": "abc"}) == "abc"
    assert identity.check_workflow_name({"checkSuite": {"workflowRun": {}}}) == ""
    assert identity.check_workflow_name({"app": {"name": "GitHub Actions"}}) == ""
    assert identity.check_workflow_name({"check_suite": "bad"}) == ""
    assert identity.check_workflow_name({"check_suite": {"workflow_run": "bad"}}) == ""
    assert identity.check_workflow_name({"app": "nope"}) == ""
    assert identity.check_run_id({"checkSuite": {"workflowRun": {"databaseId": 123}}}) == "123"
    assert identity.check_run_id({"check_suite": {"workflow_run": {"id": "bad"}}}) == ""
    assert identity.check_run_id({"check_suite": {"workflow_run": "bad"}}) == ""
    assert identity.check_run_id({"check_suite": "bad"}) == ""
    assert identity.check_run_id(
        {"detailsUrl": "https://github.com/acme/repo/actions/runs/456/job/789"}
    ) == "456"
    assert identity.check_run_id({"details_url": "https://github.com/acme/repo/checks/1"}) == ""
    head = identity.KAEFA_78_HEAD
    with pytest.raises(identity.CoverageQuoteError, match="40-character"):
        identity.terminal_coverage_result([], "deadbeef")
    in_progress = coverage_check(head=head, status="in_progress", conclusion="")
    assert identity.is_canonical_coverage_check(in_progress, head) is False
    other = coverage_check(head=head, name="strix")
    assert identity.is_canonical_coverage_check(other, head) is False
    wrong_head = coverage_check(head=identity.KAEFA_75_HEAD)
    assert identity.is_canonical_coverage_check(wrong_head, head) is False
    unnamed = coverage_check(head=head, workflow="")
    unnamed["check_suite"] = {"workflow_run": {"workflow": {}}}
    assert identity.terminal_coverage_result([unnamed], head) == "success"
    string_workflow = coverage_check(head=head)
    string_workflow["check_suite"] = {"workflow_run": {"workflow": "Required OpenCode Review"}}
    string_workflow["app"] = {"name": "GitHub Actions"}
    assert identity.check_workflow_name(string_workflow) == ""
    missing_conclusion = coverage_check(head=head, conclusion="")
    with pytest.raises(identity.CoverageQuoteError, match="non-terminal"):
        identity.terminal_coverage_result([missing_conclusion], head)


def test_app_only_check_run_is_still_canonical() -> None:
    """A completed exact-head check with only an app.name (the real REST shape,
    which never carries check_suite.workflow_run) must still be accepted."""
    head = identity.KAEFA_78_HEAD
    app_only = coverage_check(head=head, conclusion="success")
    app_only["check_suite"] = {}
    app_only["app"] = {"name": "GitHub Actions"}
    assert identity.check_workflow_name(app_only) == ""
    assert identity.is_canonical_coverage_check(app_only, head) is True
    assert identity.terminal_coverage_result([app_only], head) == "success"


def test_load_and_cli_verify_quoted_success(tmp_path: Path, capsys, monkeypatch) -> None:
    """CLI prints the canonical result and annotates quote mismatches."""
    head = identity.KAEFA_78_HEAD
    payload = {"check_runs": [coverage_check(head=head, conclusion="success")]}
    path = tmp_path / "checks.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert identity.main(
        ["--head-sha", head, "--quoted-result", "success", "--check-runs-file", str(path)]
    ) == 0
    assert capsys.readouterr().out.strip() == "success"

    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert identity.main(
        ["--head-sha", head, "--quoted-result", "failure", "--check-runs-file", str(path)]
    ) == 1
    err = capsys.readouterr().err
    assert "does not match" in err
    assert "Coverage identity failure" in summary.read_text(encoding="utf-8")

    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert identity.main(["--head-sha", head, "--quoted-result", "success"]) == 1
    array_path = tmp_path / "array.json"
    array_path.write_text(json.dumps([coverage_check(head=head)]), encoding="utf-8")
    assert identity.main(
        ["--head-sha", head, "--quoted-result", "success", "--check-runs-file", str(array_path)]
    ) == 0
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert identity.main(
        ["--head-sha", head, "--quoted-result", "success", "--check-runs-file", str(bad)]
    ) == 1
    stdin_payload = json.dumps([coverage_check(head=head, conclusion="success")])
    monkeypatch.setattr(identity.sys, "stdin", type("Stdin", (), {"read": lambda self: stdin_payload})())
    assert identity.load_check_runs("-")[0]["name"] == "coverage-evidence"
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert identity.main(
        ["--head-sha", head, "--quoted-result", "success", "--check-runs-file", str(broken)]
    ) == 1


def test_fetch_check_runs_rejects_unvalidated_repo_and_head_sha(monkeypatch) -> None:
    """A malformed --repo or --head-sha never reaches the gh api path string."""

    def unexpected_run(args, **kwargs):
        raise AssertionError(f"gh must not be invoked with unvalidated input: {args!r}")

    monkeypatch.setattr(identity.subprocess, "run", unexpected_run)
    with pytest.raises(identity.CoverageQuoteError, match="owner/repo"):
        identity.fetch_check_runs("../evil", identity.KAEFA_78_HEAD)
    with pytest.raises(identity.CoverageQuoteError, match="40-character"):
        identity.fetch_check_runs("ContextualWisdomLab/kaefa", "not-a-sha")


def test_repository_identity_accepts_leading_dot_but_rejects_path_segments() -> None:
    """Central dot repositories are valid while dot paths and options fail closed."""
    assert identity.REPO_RE.fullmatch("ContextualWisdomLab/.github")
    assert not identity.REPO_RE.fullmatch("owner/.")
    assert not identity.REPO_RE.fullmatch("owner/..")
    assert not identity.REPO_RE.fullmatch("owner/-repo")



def test_fetch_check_runs_retries_transient_github_read_failure(monkeypatch) -> None:
    """A transient 429 is retried before exact-head identity fails closed."""
    page = {
        "check_runs": [
            coverage_check(head=identity.KAEFA_78_HEAD, conclusion="success")
        ]
    }
    responses = [
        type(
            "Completed",
            (),
            {"returncode": 1, "stdout": "", "stderr": "HTTP 429 rate limit exceeded"},
        )(),
        type(
            "Completed",
            (),
            {"returncode": 0, "stdout": json.dumps([page]), "stderr": ""},
        )(),
    ]
    calls = 0

    def fake_run(args, **kwargs):
        nonlocal calls
        calls += 1
        return responses.pop(0)

    monkeypatch.setattr(identity, "RETRY_DELAYS", (0, 0, 0), raising=False)
    monkeypatch.setattr(identity.subprocess, "run", fake_run)

    loaded = identity.fetch_check_runs(
        "ContextualWisdomLab/kaefa", identity.KAEFA_78_HEAD
    )

    assert calls == 2
    assert loaded[0]["name"] == "coverage-evidence"


def test_fetch_check_runs_retries_bare_http_502(monkeypatch) -> None:
    """A bare HTTP 502 status exercises the numeric transient matcher."""
    page = {
        "check_runs": [
            coverage_check(head=identity.KAEFA_78_HEAD, conclusion="success")
        ]
    }
    responses = [
        type(
            "Completed",
            (),
            {"returncode": 1, "stdout": "", "stderr": "HTTP 502 Bad Gateway"},
        )(),
        type(
            "Completed",
            (),
            {"returncode": 0, "stdout": json.dumps([page]), "stderr": ""},
        )(),
    ]

    monkeypatch.setattr(identity, "RETRY_DELAYS", (0, 0, 0))
    monkeypatch.setattr(
        identity.subprocess, "run", lambda args, **kwargs: responses.pop(0)
    )

    assert identity.fetch_check_runs(
        "ContextualWisdomLab/kaefa", identity.KAEFA_78_HEAD
    )

def test_fetch_check_runs_parses_pages(monkeypatch) -> None:
    """Paginated gh output and error paths stay fail-closed."""
    page = {
        "check_runs": [
            coverage_check(head=identity.KAEFA_78_HEAD, conclusion="success")
        ]
    }

    def fake_run(args, **kwargs):
        assert args[0] == "gh"
        assert "--paginate" in args
        assert "--slurp" in args
        return type("Completed", (), {"returncode": 0, "stdout": json.dumps([page]), "stderr": ""})()

    monkeypatch.setattr(identity.subprocess, "run", fake_run)
    loaded = identity.fetch_check_runs("ContextualWisdomLab/kaefa", identity.KAEFA_78_HEAD)
    assert loaded[0]["name"] == "coverage-evidence"

    def fake_object(args, **kwargs):
        return type(
            "Completed",
            (),
            {"returncode": 0, "stdout": json.dumps(page), "stderr": ""},
        )()

    monkeypatch.setattr(identity.subprocess, "run", fake_object)
    assert identity.fetch_check_runs("ContextualWisdomLab/kaefa", identity.KAEFA_78_HEAD)

    def fake_fail(args, **kwargs):
        return type("Completed", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()

    monkeypatch.setattr(identity.subprocess, "run", fake_fail)
    with pytest.raises(identity.CoverageQuoteError, match="lookup failed"):
        identity.fetch_check_runs("ContextualWisdomLab/kaefa", identity.KAEFA_78_HEAD)

    def fake_bad_json(args, **kwargs):
        return type("Completed", (), {"returncode": 0, "stdout": '"nope"', "stderr": ""})()

    monkeypatch.setattr(identity.subprocess, "run", fake_bad_json)
    with pytest.raises(identity.CoverageQuoteError, match="malformed"):
        identity.fetch_check_runs("ContextualWisdomLab/kaefa", identity.KAEFA_78_HEAD)

    def fake_list_objects(args, **kwargs):
        return type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps([coverage_check(head=identity.KAEFA_78_HEAD)]),
                "stderr": "",
            },
        )()

    monkeypatch.setattr(identity.subprocess, "run", fake_list_objects)
    assert identity.fetch_check_runs("ContextualWisdomLab/kaefa", identity.KAEFA_78_HEAD)

    def fake_mixed_pages(args, **kwargs):
        return type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    [
                        {"check_runs": [coverage_check(head=identity.KAEFA_78_HEAD)]},
                        coverage_check(head=identity.KAEFA_78_HEAD),
                        "skip",
                    ]
                ),
                "stderr": "",
            },
        )()

    monkeypatch.setattr(identity.subprocess, "run", fake_mixed_pages)
    assert len(identity.fetch_check_runs("ContextualWisdomLab/kaefa", identity.KAEFA_78_HEAD)) == 2

    monkeypatch.setattr(
        identity,
        "fetch_check_runs",
        lambda repo, head: [coverage_check(head=head, conclusion="success")],
    )
    assert (
        identity.main(
            [
                "--repo",
                "ContextualWisdomLab/kaefa",
                "--head-sha",
                identity.KAEFA_78_HEAD,
                "--quoted-result",
                "success",
            ]
        )
        == 0
    )


def test_fetch_check_runs_exercises_delay_and_empty_retry_policy(monkeypatch) -> None:
    """A configured delay is honored, while an empty retry policy fails closed."""
    sleeps: list[float] = []
    monkeypatch.setattr(identity, "RETRY_DELAYS", (0.01,))
    monkeypatch.setattr(identity.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        identity.subprocess,
        "run",
        lambda args, **kwargs: type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps({"check_runs": []}),
                "stderr": "",
            },
        )(),
    )

    assert identity.fetch_check_runs(
        "ContextualWisdomLab/kaefa", identity.KAEFA_78_HEAD
    ) == []
    assert sleeps == [0.01]

    monkeypatch.setattr(identity, "RETRY_DELAYS", ())
    with pytest.raises(identity.CoverageQuoteError, match="after retries"):
        identity.fetch_check_runs(
            "ContextualWisdomLab/kaefa", identity.KAEFA_78_HEAD
        )


def dispatch_run(
    *,
    run_id: str,
    target_repo: str,
    pr_number: int,
    head_sha: str,
    workflow_repo: str = "ContextualWisdomLab/.github",
) -> dict[str, object]:
    """Build the trusted central repository_dispatch run identity."""
    return {
        "id": int(run_id),
        "event": "repository_dispatch",
        "name": (
            f"OpenCode Review Dispatch {target_repo}#{pr_number}@{head_sha}"
        ),
        "display_title": (
            f"OpenCode Review Dispatch {target_repo}#{pr_number}@{head_sha}"
        ),
        "repository": {"full_name": workflow_repo},
    }


def coverage_job(
    *,
    conclusion: str = "success",
    name: str = "coverage-evidence",
    status: str = "completed",
    run_id: str = "33112315024",
) -> dict[str, object]:
    """Build one Actions job from the current workflow run."""
    return {
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "run_id": int(run_id),
    }


def test_repository_dispatch_coverage_binds_to_current_central_run_job() -> None:
    """Coverage authority is the completed job in the exact central dispatch run."""
    run_id = "33112315024"
    target_repo = "ContextualWisdomLab/scopeweave"
    run = dispatch_run(
        run_id=run_id,
        target_repo=target_repo,
        pr_number=523,
        head_sha=identity.KAEFA_78_HEAD,
    )
    jobs = [coverage_job(conclusion="failure")]

    assert identity.terminal_dispatch_coverage_result(
        run,
        jobs,
        workflow_repo="ContextualWisdomLab/.github",
        target_repo=target_repo,
        pr_number="523",
        head_sha=identity.KAEFA_78_HEAD,
        run_id=run_id,
    ) == "failure"


def test_repository_dispatch_coverage_accepts_legacy_base_workflow_name() -> None:
    """Older fixtures may expose the workflow name instead of the run-name."""
    run_id = "33112315024"
    target_repo = "ContextualWisdomLab/scopeweave"
    run = dispatch_run(
        run_id=run_id,
        target_repo=target_repo,
        pr_number=523,
        head_sha=identity.KAEFA_78_HEAD,
    )
    run["name"] = "OpenCode Review Dispatch"

    assert identity.terminal_dispatch_coverage_result(
        run,
        [coverage_job()],
        workflow_repo="ContextualWisdomLab/.github",
        target_repo=target_repo,
        pr_number="523",
        head_sha=identity.KAEFA_78_HEAD,
        run_id=run_id,
    ) == "success"


def test_repository_dispatch_coverage_rejects_job_from_another_run() -> None:
    """A same-named completed job from a different run is never authoritative."""
    run_id = "33112315024"
    target_repo = "ContextualWisdomLab/scopeweave"
    run = dispatch_run(
        run_id=run_id,
        target_repo=target_repo,
        pr_number=523,
        head_sha=identity.KAEFA_78_HEAD,
    )

    with pytest.raises(identity.CoverageQuoteError, match="job run id"):
        identity.terminal_dispatch_coverage_result(
            run,
            [coverage_job(run_id="33112315023")],
            workflow_repo="ContextualWisdomLab/.github",
            target_repo=target_repo,
            pr_number="523",
            head_sha=identity.KAEFA_78_HEAD,
            run_id=run_id,
        )


@pytest.mark.parametrize(
    ("overrides", "run_mutation", "match"),
    (
        ({"workflow_repo": "../bad"}, {}, "workflow repository"),
        ({"target_repo": "../bad"}, {}, "target repository"),
        ({"pr_number": "not-a-number"}, {}, "pull request number"),
        ({"pr_number": "0"}, {}, "pull request number"),
        ({"head_sha": "deadbeef"}, {}, "40-character"),
        ({"run_id": "not-a-run"}, {}, "numeric workflow run id"),
        ({}, {"id": 33112315023}, "run id"),
        ({}, {"repository": "malformed"}, "repository"),
    ),
)
def test_repository_dispatch_coverage_rejects_invalid_boundaries(
    overrides: dict[str, str], run_mutation: dict[str, object], match: str
) -> None:
    """Every externally supplied dispatch identity component is fail-closed."""
    run_id = "33112315024"
    target_repo = "ContextualWisdomLab/scopeweave"
    run = dispatch_run(
        run_id=run_id,
        target_repo=target_repo,
        pr_number=523,
        head_sha=identity.KAEFA_78_HEAD,
    )
    run.update(run_mutation)
    arguments = {
        "workflow_repo": "ContextualWisdomLab/.github",
        "target_repo": target_repo,
        "pr_number": "523",
        "head_sha": identity.KAEFA_78_HEAD,
        "run_id": run_id,
    }
    arguments.update(overrides)

    with pytest.raises(identity.CoverageQuoteError, match=match):
        identity.terminal_dispatch_coverage_result(run, [coverage_job()], **arguments)


def test_repository_dispatch_coverage_rejects_nonterminal_conclusion() -> None:
    """A completed job without a terminal conclusion remains non-passing."""
    run_id = "33112315024"
    target_repo = "ContextualWisdomLab/scopeweave"
    run = dispatch_run(
        run_id=run_id,
        target_repo=target_repo,
        pr_number=523,
        head_sha=identity.KAEFA_78_HEAD,
    )

    with pytest.raises(identity.CoverageQuoteError, match="non-terminal"):
        identity.terminal_dispatch_coverage_result(
            run,
            [coverage_job(conclusion="")],
            workflow_repo="ContextualWisdomLab/.github",
            target_repo=target_repo,
            pr_number="523",
            head_sha=identity.KAEFA_78_HEAD,
            run_id=run_id,
        )


def test_terminal_coverage_rejects_malformed_run_id() -> None:
    """Optional check-run binding accepts only a numeric Actions run id."""
    with pytest.raises(identity.CoverageQuoteError, match="numeric workflow run id"):
        identity.terminal_coverage_result(
            [coverage_check(head=identity.KAEFA_78_HEAD)],
            identity.KAEFA_78_HEAD,
            run_id="bad",
        )


@pytest.mark.parametrize(
    ("mutation", "match"),
    (
        ({"event": "pull_request"}, "repository_dispatch"),
        ({"name": "Other Workflow"}, "workflow"),
        ({"display_title": "OpenCode Review Dispatch spoof"}, "target"),
        ({"repository": {"full_name": "ContextualWisdomLab/scopeweave"}}, "repository"),
    ),
)
def test_repository_dispatch_coverage_rejects_wrong_run_identity(
    mutation: dict[str, object], match: str
) -> None:
    """A same-named job from another event/workflow/target/repository is non-passing."""
    run_id = "33112315024"
    target_repo = "ContextualWisdomLab/scopeweave"
    run = dispatch_run(
        run_id=run_id,
        target_repo=target_repo,
        pr_number=523,
        head_sha=identity.KAEFA_78_HEAD,
    )
    run.update(mutation)

    with pytest.raises(identity.CoverageQuoteError, match=match):
        identity.terminal_dispatch_coverage_result(
            run,
            [coverage_job()],
            workflow_repo="ContextualWisdomLab/.github",
            target_repo=target_repo,
            pr_number="523",
            head_sha=identity.KAEFA_78_HEAD,
            run_id=run_id,
        )


@pytest.mark.parametrize(
    "jobs",
    (
        [],
        [coverage_job(status="in_progress", conclusion="")],
        [coverage_job(), coverage_job()],
        [coverage_job(name="coverage-source-tree")],
    ),
)
def test_repository_dispatch_coverage_requires_one_completed_exact_job(
    jobs: list[dict[str, object]],
) -> None:
    """Absent, pending, ambiguous, or differently named jobs fail closed."""
    run_id = "33112315024"
    target_repo = "ContextualWisdomLab/scopeweave"
    run = dispatch_run(
        run_id=run_id,
        target_repo=target_repo,
        pr_number=523,
        head_sha=identity.KAEFA_78_HEAD,
    )

    with pytest.raises(identity.CoverageQuoteError, match="coverage-evidence"):
        identity.terminal_dispatch_coverage_result(
            run,
            jobs,
            workflow_repo="ContextualWisdomLab/.github",
            target_repo=target_repo,
            pr_number="523",
            head_sha=identity.KAEFA_78_HEAD,
            run_id=run_id,
        )


def test_run_gh_json_retries_transient_errors_and_honors_delay(monkeypatch) -> None:
    """Central workflow reads retry only authenticated transient failures."""
    responses = [
        type(
            "Completed",
            (),
            {"returncode": 1, "stdout": "", "stderr": "HTTP 503 unavailable"},
        )(),
        type(
            "Completed",
            (),
            {"returncode": 0, "stdout": json.dumps({"id": 123}), "stderr": ""},
        )(),
    ]
    sleeps: list[float] = []
    monkeypatch.setattr(identity, "RETRY_DELAYS", (0, 0.01))
    monkeypatch.setattr(identity.time, "sleep", sleeps.append)
    monkeypatch.setattr(
        identity.subprocess, "run", lambda args, **kwargs: responses.pop(0)
    )

    assert identity._run_gh_json(["gh", "api", "example"]) == {"id": 123}
    assert sleeps == [0.01]


def test_run_gh_json_fails_closed_on_terminal_and_exhausted_reads(monkeypatch) -> None:
    """Non-transient failures and an unavailable retry policy never fabricate JSON."""
    monkeypatch.setattr(identity, "RETRY_DELAYS", (0,))
    monkeypatch.setattr(
        identity.subprocess,
        "run",
        lambda args, **kwargs: type(
            "Completed", (), {"returncode": 1, "stdout": "", "stderr": "denied"}
        )(),
    )
    with pytest.raises(identity.CoverageQuoteError, match="workflow lookup failed"):
        identity._run_gh_json(["gh", "api", "example"])

    monkeypatch.setattr(identity, "RETRY_DELAYS", ())
    with pytest.raises(identity.CoverageQuoteError, match="after retries"):
        identity._run_gh_json(["gh", "api", "example"])


def test_fetch_dispatch_workflow_run_validates_identity_and_shape(monkeypatch) -> None:
    """The exact workflow-run reader validates inputs and the returned object."""
    calls: list[list[str]] = []
    monkeypatch.setattr(
        identity,
        "_run_gh_json",
        lambda args: calls.append(args) or {"id": 33112315024},
    )
    assert identity.fetch_dispatch_workflow_run(
        "ContextualWisdomLab/.github", "33112315024"
    )["id"] == 33112315024
    assert calls == [
        [
            "gh",
            "api",
            "repos/ContextualWisdomLab/.github/actions/runs/33112315024",
        ]
    ]

    with pytest.raises(identity.CoverageQuoteError, match="workflow repository"):
        identity.fetch_dispatch_workflow_run("../bad", "33112315024")
    with pytest.raises(identity.CoverageQuoteError, match="numeric workflow run id"):
        identity.fetch_dispatch_workflow_run("ContextualWisdomLab/.github", "bad")
    monkeypatch.setattr(identity, "_run_gh_json", lambda args: [])
    with pytest.raises(identity.CoverageQuoteError, match="malformed JSON"):
        identity.fetch_dispatch_workflow_run(
            "ContextualWisdomLab/.github", "33112315024"
        )


def test_fetch_dispatch_workflow_jobs_validates_pages_and_filters(monkeypatch) -> None:
    """Latest-attempt job pages are validated and non-object entries ignored."""
    monkeypatch.setattr(
        identity,
        "_run_gh_json",
        lambda args: [
            {"jobs": [coverage_job(), "malformed"]},
            {"jobs": [coverage_job(name="opencode-review")]},
        ],
    )
    jobs = identity.fetch_dispatch_workflow_jobs(
        "ContextualWisdomLab/.github", "33112315024"
    )
    assert [job["name"] for job in jobs] == ["coverage-evidence", "opencode-review"]

    monkeypatch.setattr(identity, "_run_gh_json", lambda args: {"jobs": []})
    assert identity.fetch_dispatch_workflow_jobs(
        "ContextualWisdomLab/.github", "33112315024"
    ) == []
    with pytest.raises(identity.CoverageQuoteError, match="workflow repository"):
        identity.fetch_dispatch_workflow_jobs("../bad", "33112315024")
    with pytest.raises(identity.CoverageQuoteError, match="numeric workflow run id"):
        identity.fetch_dispatch_workflow_jobs("ContextualWisdomLab/.github", "bad")
    monkeypatch.setattr(identity, "_run_gh_json", lambda args: [{"jobs": "bad"}])
    with pytest.raises(identity.CoverageQuoteError, match="malformed JSON"):
        identity.fetch_dispatch_workflow_jobs(
            "ContextualWisdomLab/.github", "33112315024"
        )


def test_dispatch_cli_quotes_only_the_exact_current_run(
    monkeypatch, capsys
) -> None:
    """CLI dispatch mode succeeds only when current-run evidence matches its quote."""
    run_id = "33112315024"
    target_repo = "ContextualWisdomLab/scopeweave"
    monkeypatch.setattr(
        identity,
        "fetch_dispatch_workflow_run",
        lambda workflow_repo, current_run_id: dispatch_run(
            run_id=current_run_id,
            target_repo=target_repo,
            pr_number=523,
            head_sha=identity.KAEFA_78_HEAD,
        ),
    )
    monkeypatch.setattr(
        identity,
        "fetch_dispatch_workflow_jobs",
        lambda workflow_repo, current_run_id: [coverage_job(run_id=current_run_id)],
    )
    args = [
        "--workflow-repo",
        "ContextualWisdomLab/.github",
        "--repo",
        target_repo,
        "--pr-number",
        "523",
        "--head-sha",
        identity.KAEFA_78_HEAD,
        "--run-id",
        run_id,
        "--quoted-result",
        "success",
    ]

    assert identity.main(args) == 0
    assert capsys.readouterr().out.strip() == "success"
    args[-1] = "failure"
    assert identity.main(args) == 1
    assert "does not match" in capsys.readouterr().err

    missing = [item for item in args if item not in {"--repo", target_repo}]
    assert identity.main(missing) == 1
    assert "needs target repo" in capsys.readouterr().err
