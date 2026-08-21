"""Contract and behavior tests for the read-only Actions queue collector."""

import importlib.util
from datetime import datetime, timezone
import io
import json
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/ci/actions_queue_health.py"
SPEC = importlib.util.spec_from_file_location("actions_queue_health", MODULE_PATH)
assert SPEC and SPEC.loader
queue_health = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(queue_health)


NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def test_queue_health_module_path_is_independent_of_working_directory() -> None:
    """Load production code from the repository root, not the caller's cwd."""
    expected = Path(__file__).resolve().parents[1] / "scripts/ci/actions_queue_health.py"
    assert MODULE_PATH == expected
    assert MODULE_PATH.is_file()


def pull_request(number: int = 1, head_sha: str = "head") -> dict:
    """Return a compact open pull-request fixture."""
    return {
        "number": number,
        "state": "open",
        "base": {"ref": "main", "repo": {"full_name": "owner/repo"}},
        "head": {"sha": head_sha},
        "updated_at": "2026-08-19T11:00:00Z",
    }


def workflow_run(
    run_id: int,
    *,
    head_sha: str = "head",
    pull_requests: list[dict] | None = None,
    status: str = "queued",
    jobs: list[dict] | None = None,
    workflow_name: str = "required-check",
    created_at: str = "2026-08-19T10:00:00Z",
) -> dict:
    """Return one raw workflow-run fixture."""
    return {
        "id": run_id,
        "name": workflow_name,
        "event": "pull_request",
        "status": status,
        "conclusion": "",
        "head_sha": head_sha,
        "created_at": created_at,
        "updated_at": created_at,
        "run_attempt": 1,
        "pull_requests": pull_requests or [],
        "jobs": jobs or [],
    }


def job(
    job_id: int,
    *,
    status: str = "queued",
    conclusion: str | None = None,
    runner_id: int | None = None,
    runner_name: str | None = None,
    name: str = "required-check",
) -> dict:
    """Return one raw workflow-job fixture."""
    return {
        "id": job_id,
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "runner_id": runner_id,
        "runner_name": runner_name,
        "steps": [],
    }


def report_snapshot() -> dict:
    """Return a fixture covering current, obsolete, unlinked, and terminal jobs."""
    return {
        "generated_at": "2026-08-19T11:00:00Z",
        "repositories": [
            {
                "full_name": "owner/repo",
                "pull_requests": [pull_request()],
                "runs": [
                    workflow_run(
                        10,
                        pull_requests=[{"number": 1, "head": {"sha": "head"}}],
                        jobs=[
                            job(100),
                            job(101, runner_id=7, runner_name="runner-7"),
                            job(102, status="waiting"),
                        ],
                    ),
                    workflow_run(
                        11,
                        head_sha="old",
                        pull_requests=[{"number": 1, "head": {"sha": "old"}}],
                        jobs=[job(110)],
                    ),
                    workflow_run(12, jobs=[job(120)]),
                    workflow_run(
                        13,
                        pull_requests=[{"number": 1, "head": {"sha": "head"}}],
                        jobs=[],
                        workflow_name="required-check",
                    ),
                    workflow_run(
                        14,
                        pull_requests=[{"number": 1, "head": {"sha": "head"}}],
                        status="completed",
                        jobs=[job(140, status="completed", conclusion="success")],
                    ),
                ],
            }
        ],
    }


@pytest.mark.parametrize("value", [None, "", "  ", "not-a-time", "2026-08-19T12:00:00"])
def test_parse_timestamp_rejects_ambiguous_or_invalid_values(value: object) -> None:
    """Reject missing, malformed, and timezone-free timestamps."""
    with pytest.raises(queue_health.QueueHealthError):
        queue_health.parse_timestamp(value)  # type: ignore[arg-type]


def test_parse_timestamp_normalises_z_and_offsets() -> None:
    """Normalize UTC and offset timestamps to the same instant."""
    assert queue_health.parse_timestamp("2026-08-19T12:00:00Z") == NOW
    assert queue_health.parse_timestamp("2026-08-19T21:00:00+09:00") == NOW


@pytest.mark.parametrize("value", ["owner", "owner/repo/extra", "../..", "./repo", "owner/.", 1])
def test_repository_name_rejects_non_repository_identifiers(value: object) -> None:
    """Reject malformed and traversal-like repository identifiers."""
    with pytest.raises(queue_health.QueueHealthError):
        queue_health._repository_name(value)


def test_load_allowlist_accepts_array_and_object_and_rejects_bad_inputs(tmp_path: Path) -> None:
    """Load both supported allowlist shapes and reject unsafe input files."""
    array_path = tmp_path / "array.json"
    array_path.write_text(json.dumps(["z/repo", "a/repo"]), encoding="utf-8")
    assert queue_health.load_allowlist(array_path) == ["a/repo", "z/repo"]

    object_path = tmp_path / "object.json"
    object_path.write_text(json.dumps({"repositories": ["a/repo"]}), encoding="utf-8")
    assert queue_health.load_allowlist(object_path) == ["a/repo"]

    for name, payload in (
        ("empty.json", []),
        ("missing-key.json", {}),
        ("duplicate.json", ["a/repo", "a/repo"]),
        ("invalid-repository.json", ["a repo"]),
    ):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(queue_health.QueueHealthError):
            queue_health.load_allowlist(path)

    (tmp_path / "invalid.json").write_text("{", encoding="utf-8")
    with pytest.raises(queue_health.QueueHealthError):
        queue_health.load_allowlist(tmp_path / "invalid.json")
    with pytest.raises(queue_health.QueueHealthError):
        queue_health.load_allowlist(tmp_path / "missing.json")


@pytest.mark.parametrize(
    "payload, key, expected",
    [
        ([{"id": 1}], "items", [{"id": 1}]),
        ({"items": [{"id": 2}]}, "items", [{"id": 2}]),
        ({"items": [{"id": 3}], "total_count": 1}, "items", [{"id": 3}]),
    ],
)
def test_list_payload_accepts_api_list_shapes(payload: object, key: str, expected: list[dict]) -> None:
    """Accept the bounded list response shapes emitted by GitHub APIs."""
    assert queue_health._list_payload(payload, key) == expected


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"items": "bad"},
        [{"id": 1}, "bad"],
        {"items": [{"id": 1}], "total_count": 2001},
        {"items": [{"id": 1}], "total_count": 0},
        {"items": [{"id": 1}], "total_count": True},
        {"items": [{"id": 1}], "total_count": "1"},
        {"items": [{"id": 1}], "total_count": []},
    ],
)
def test_list_payload_rejects_untrusted_shapes(payload: object) -> None:
    """Reject malformed, oversized, and dishonest list responses."""
    with pytest.raises(queue_health.QueueHealthError):
        queue_health._list_payload(payload, "items")


def test_list_payload_flattens_bounded_paginated_responses() -> None:
    """Flatten bounded pages while validating every page and total count."""
    assert queue_health._list_payload(
        {"_queue_health_pages": [[{"id": 1}], [{"id": 2}]]}, "items"
    ) == [{"id": 1}, {"id": 2}]
    assert queue_health._list_payload(
        {"_queue_health_pages": [{"items": [{"id": 3}], "total_count": 2}, {"items": [{"id": 4}], "total_count": 2}]},
        "items",
    ) == [{"id": 3}, {"id": 4}]
    for payload in (
        {"_queue_health_pages": []},
        {"_queue_health_pages": [[]] * (queue_health.MAX_API_PAGES + 1)},
        {"_queue_health_pages": [None]},
        {"_queue_health_pages": [{"items": "bad"}]},
        {"_queue_health_pages": [{"items": [{"id": 1}], "total_count": 3}, {"items": [{"id": 2}], "total_count": "2"}]},
    ):
        with pytest.raises(queue_health.QueueHealthError):
            queue_health._list_payload(payload, "items")
    assert queue_health._list_payload(
        {"_queue_health_pages": [{"items": [{"id": 1}], "total_count": 1}, {"items": [{"id": 2}], "total_count": 2}]},
        "items",
    ) == [{"id": 1}, {"id": 2}]


def test_github_json_is_read_only_and_rejects_failures() -> None:
    """Use safe read-only CLI arguments and fail closed on transport errors."""
    def success_runner(*args: object, **kwargs: object) -> CompletedProcess[str]:
        """Return one successful non-paginated API response."""
        assert args[0] == ["gh", "api", "repos/a/repo"]
        assert kwargs == {
            "capture_output": True,
            "text": True,
            "check": False,
            "timeout": 30,
        }
        return CompletedProcess([], 0, "[{\"id\": 1}]", "")

    assert queue_health.github_json("repos/a/repo", runner=success_runner) == [{"id": 1}]

    def paginated_runner(*args: object, **kwargs: object) -> CompletedProcess[str]:
        """Return one successful paginated API response."""
        assert args[0] == ["gh", "api", "--paginate", "--slurp", "repos/a/repo"]
        return CompletedProcess([], 0, "[[{\"id\": 1}]]", "")

    assert queue_health.github_json("repos/a/repo", paginate=True, runner=paginated_runner) == {
        "_queue_health_pages": [[{"id": 1}]]
    }
    for output in ("[]", json.dumps([{}] * (queue_health.MAX_API_PAGES + 1))):
        with pytest.raises(queue_health.QueueHealthError, match="page set"):
            queue_health.github_json(
                "repos/a/repo",
                paginate=True,
                runner=lambda *args, output=output, **kwargs: CompletedProcess([], 0, output, ""),
            )
    with pytest.raises(queue_health.QueueHealthError):
        queue_health.github_json("orgs/a/repos", runner=success_runner)

    def failed_runner(*args: object, **kwargs: object) -> CompletedProcess[str]:
        """Return a failed API response with stderr evidence."""
        return CompletedProcess([], 1, "fallback", "api failed")

    with pytest.raises(queue_health.QueueHealthError, match="api failed"):
        queue_health.github_json("repos/a/repo", runner=failed_runner)

    def stdout_failure_runner(*args: object, **kwargs: object) -> CompletedProcess[str]:
        """Return a failed API response with stdout-only evidence."""
        return CompletedProcess([], 1, "stdout failure", "")

    with pytest.raises(queue_health.QueueHealthError, match="stdout failure"):
        queue_health.github_json("repos/a/repo", runner=stdout_failure_runner)

    def empty_failure_runner(*args: object, **kwargs: object) -> CompletedProcess[str]:
        """Return a failed API response without diagnostic text."""
        return CompletedProcess([], 1, "", "")

    with pytest.raises(queue_health.QueueHealthError, match="GitHub API read failed"):
        queue_health.github_json("repos/a/repo", runner=empty_failure_runner)

    def invalid_json_runner(*args: object, **kwargs: object) -> CompletedProcess[str]:
        """Return a successful process containing invalid JSON."""
        return CompletedProcess([], 0, "not json", "")

    with pytest.raises(queue_health.QueueHealthError, match="invalid JSON"):
        queue_health.github_json("repos/a/repo", runner=invalid_json_runner)


def test_github_json_fails_closed_when_external_read_times_out() -> None:
    """A stalled GitHub CLI read must not occupy the workflow indefinitely."""
    def timeout_runner(*args: object, **kwargs: object) -> CompletedProcess[str]:
        """Raise the subprocess timeout seen by the production boundary."""
        raise TimeoutExpired(args[0], timeout=30)

    with pytest.raises(queue_health.QueueHealthError, match="timed out after 30 seconds"):
        queue_health.github_json("repos/a/repo", runner=timeout_runner)


def test_normalise_pull_request_preserves_exact_head_identity() -> None:
    """Retain exact pull-request identity and reject incomplete records."""
    normalized = queue_health._normalise_pull_request(pull_request())
    assert normalized["number"] == 1
    assert normalized["head_sha"] == "head"
    assert normalized["base_repository"] == "owner/repo"
    normalized_snapshot = queue_health._normalise_pull_request(
        {
            "number": 1,
            "state": "open",
            "base_ref": "main",
            "base_repository": "owner/repo",
            "head_sha": "head",
            "updated_at": "2026-08-19T11:00:00Z",
        },
        allow_normalized=True,
    )
    assert normalized_snapshot == {
        "number": 1,
        "state": "open",
        "base_ref": "main",
        "base_repository": "owner/repo",
        "head_sha": "head",
        "updated_at": "2026-08-19T11:00:00Z",
    }
    with pytest.raises(queue_health.IncompletePullRequestIdentity, match="normalized"):
        queue_health._normalise_pull_request(
            {"number": 1, "base_ref": "main"}, allow_normalized=True
        )
    with pytest.raises(queue_health.QueueHealthError, match="positive integer"):
        queue_health._normalise_pull_request(
            {
                "number": 0,
                "base_ref": "main",
                "base_repository": "owner/repo",
                "head_sha": "head",
                "updated_at": "2026-08-19T11:00:00Z",
            },
            allow_normalized=True,
        )
    for invalid in ({"number": True}, {"number": 0}, {"number": "1"}, "bad"):
        with pytest.raises(queue_health.QueueHealthError):
            queue_health._normalise_pull_request(invalid)  # type: ignore[arg-type]
    with pytest.raises(queue_health.IncompletePullRequestIdentity, match="head and base"):
        queue_health._normalise_pull_request({"number": 1, "head": {}, "base": "bad"})
    with pytest.raises(queue_health.QueueHealthError, match="positive integer"):
        queue_health._normalise_pull_request({"number": 0, "head": {}, "base": {}})


def test_normalise_job_preserves_runner_assignment_and_fails_closed() -> None:
    """Retain runner evidence while rejecting malformed job identities."""
    normalized = queue_health._normalise_job(job(1, runner_id=3, runner_name="runner"))
    assert normalized["runner_id"] == 3
    assert normalized["steps_count"] == 0
    assert queue_health._normalise_job(
        {"id": 2, "status": "queued", "runner_id": "bad", "steps": "bad"}
    )["runner_id"] == 0
    assert queue_health._normalise_job({"id": 3, "runner_id": True})["runner_id"] == 0
    for invalid in ({"id": True}, {"id": 0}, {"id": "1"}, "bad"):
        with pytest.raises(queue_health.QueueHealthError):
            queue_health._normalise_job(invalid)  # type: ignore[arg-type]


def test_normalise_run_validates_links_jobs_and_fallback_names() -> None:
    """Normalize workflow links and jobs with bounded fallback values."""
    normalized = queue_health._normalise_run(
        "owner/repo",
        {
            "id": 1,
            "workflow_name": "fallback-name",
            "pull_requests": [{"number": 2, "head": {"sha": "sha"}}],
        },
        [job(2)],
    )
    assert normalized["workflow_name"] == "fallback-name"
    assert normalized["pull_requests"] == [{"number": 2, "head_sha": "sha"}]
    assert queue_health._normalise_run("owner/repo", {"id": 2, "pull_requests": None}, [])["pull_requests"] == []
    assert queue_health._normalise_run(
        "owner/repo", {"id": 3, "pull_requests": [{"number": 1, "head": None}]}, []
    )["pull_requests"] == [{"number": 1, "head_sha": ""}]

    for invalid_run, invalid_jobs in (
        ("bad", []),
        ({"id": True}, []),
        ({"id": 0}, []),
        ({"id": 1}, "bad"),
        ({"id": 1, "pull_requests": "bad"}, []),
        ({"id": 1, "pull_requests": [{"number": 0}]}, []),
        ({"id": 1, "pull_requests": [{"number": 1, "head": "bad"}]}, []),
        ({"id": 1}, ["bad"]),
    ):
        with pytest.raises(queue_health.QueueHealthError):
            queue_health._normalise_run("owner/repo", invalid_run, invalid_jobs)  # type: ignore[arg-type]


def test_collect_snapshot_deduplicates_status_views_and_preserves_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deduplicate status views and isolate malformed repository evidence."""
    queued_current = workflow_run(10, pull_requests=[{"number": 1, "head": {"sha": "head"}}])
    current = workflow_run(
        12,
        status="in_progress",
        pull_requests=[{"number": 1, "head": {"sha": "head"}}],
        jobs=[job(100)],
    )
    unlinked = workflow_run(11, jobs=[])
    responses = {
        "repos/owner/repo": {"default_branch": "main"},
        "repos/owner/repo/pulls?state=open&per_page=100": [pull_request()],
        "repos/owner/repo/actions/runs?status=queued&per_page=50": [queued_current, current],
        "repos/owner/repo/actions/runs?status=in_progress&per_page=50": [current, unlinked],
        "repos/owner/repo/actions/runs/12/jobs?per_page=100": {"jobs": [job(100)]},
    }

    def runner(args: list[str], **kwargs: object) -> CompletedProcess[str]:
        """Return the deterministic API response for each requested endpoint."""
        payload = responses[args[-1]]
        if "--paginate" in args:
            payload = [payload]
        return CompletedProcess(args, 0, json.dumps(payload), "")

    snapshot = queue_health.collect_snapshot(["owner/repo"], runner=runner, generated_at="2026-08-19T11:00:00Z")
    assert snapshot["repositories"][0]["runs"][0]["id"] == 10
    assert [run["id"] for run in snapshot["repositories"][0]["runs"]] == [10, 11, 12]
    assert snapshot["repositories"][0]["default_branch"] == "main"
    report = queue_health.build_report(snapshot, now=NOW)
    assert report["summary"]["observed_job_count"] == 3
    assert report["summary"]["current_head_pending_count"] == 2

    with pytest.raises(queue_health.QueueHealthError):
        queue_health.collect_snapshot(["owner/repo", "owner/repo"], runner=runner)
    with pytest.raises(queue_health.QueueHealthError):
        queue_health.collect_snapshot(["owner/repo"], runner=runner, generated_at="bad")

    bad_responses = dict(responses)
    bad_responses["repos/owner/repo"] = []

    def bad_metadata_runner(args: list[str], **kwargs: object) -> CompletedProcess[str]:
        """Return malformed repository metadata for the isolation case."""
        payload = bad_responses[args[-1]]
        if "--paginate" in args:
            payload = [payload]
        return CompletedProcess(args, 0, json.dumps(payload), "")

    bad_snapshot = queue_health.collect_snapshot(["owner/repo"], runner=bad_metadata_runner)
    assert bad_snapshot["repositories"] == []
    assert bad_snapshot["collection_errors"][0]["repository"] == "owner/repo"

    invalid_run_responses = dict(responses)
    invalid_run_responses["repos/owner/repo/actions/runs?status=queued&per_page=50"] = [{"id": 0}]

    def invalid_run_runner(args: list[str], **kwargs: object) -> CompletedProcess[str]:
        """Return an invalid workflow-run identity for the isolation case."""
        payload = invalid_run_responses[args[-1]]
        if "--paginate" in args:
            payload = [payload]
        return CompletedProcess(args, 0, json.dumps(payload), "")

    invalid_run_snapshot = queue_health.collect_snapshot(["owner/repo"], runner=invalid_run_runner)
    assert invalid_run_snapshot["repositories"] == []
    assert invalid_run_snapshot["collection_errors"][0]["repository"] == "owner/repo"

    bad_pull = pull_request()
    bad_pull["base"] = "temporarily incomplete"
    retry_calls = 0
    sleep_calls: list[float] = []
    monkeypatch.setattr(queue_health.time, "sleep", sleep_calls.append)

    def retry_runner(args: list[str], **kwargs: object) -> CompletedProcess[str]:
        """Return one incomplete pull response followed by a valid response."""
        nonlocal retry_calls
        payload = responses[args[-1]]
        if args[-1] == "repos/owner/repo/pulls?state=open&per_page=100":
            retry_calls += 1
            payload = [bad_pull] if retry_calls == 1 else payload
        if "--paginate" in args:
            payload = [payload]
        return CompletedProcess(args, 0, json.dumps(payload), "")

    queue_health.collect_snapshot(["owner/repo"], runner=retry_runner)
    assert retry_calls == 2
    assert sleep_calls == [queue_health.PULL_REQUEST_RETRY_DELAY_SECONDS]

    def persistent_bad_runner(args: list[str], **kwargs: object) -> CompletedProcess[str]:
        """Return an incomplete pull response on every retry."""
        payload = [bad_pull] if args[-1] == "repos/owner/repo/pulls?state=open&per_page=100" else responses[args[-1]]
        if "--paginate" in args:
            payload = [payload]
        return CompletedProcess(args, 0, json.dumps(payload), "")

    persistent_bad_snapshot = queue_health.collect_snapshot(
        ["owner/repo"], runner=persistent_bad_runner
    )
    assert persistent_bad_snapshot["repositories"] == []
    assert persistent_bad_snapshot["collection_errors"][0]["repository"] == "owner/repo"

    bad_number = pull_request(number=0)

    def invalid_pull_runner(args: list[str], **kwargs: object) -> CompletedProcess[str]:
        """Return a pull request with an invalid number."""
        payload = (
            [bad_number]
            if args[-1] == "repos/owner/repo/pulls?state=open&per_page=100"
            else responses[args[-1]]
        )
        if "--paginate" in args:
            payload = [payload]
        return CompletedProcess(args, 0, json.dumps(payload), "")

    invalid_pull_snapshot = queue_health.collect_snapshot(
        ["owner/repo"], runner=invalid_pull_runner
    )
    assert invalid_pull_snapshot["repositories"] == []
    assert invalid_pull_snapshot["collection_errors"][0]["repository"] == "owner/repo"


def test_collect_snapshot_isolates_repository_errors_and_reports_incomplete_evidence() -> None:
    """Continue healthy collection while recording one repository's failure."""
    def runner(args: list[str], **kwargs: object) -> CompletedProcess[str]:
        """Return a rate-limit failure for one repository and valid data for another."""
        path = args[-1]
        if path == "repos/bad/repo":
            return CompletedProcess(args, 1, "", "rate limit")
        if path == "repos/good/repo":
            payload: object = {"default_branch": "main"}
        elif path == "repos/good/repo/pulls?state=open&per_page=100":
            payload = []
        elif "/actions/runs?status=" in path:
            payload = []
        else:  # pragma: no cover - a new endpoint must be explicitly governed
            raise AssertionError(f"unexpected endpoint: {path}")
        if "--paginate" in args:
            payload = [payload]
        return CompletedProcess(args, 0, json.dumps(payload), "")

    snapshot = queue_health.collect_snapshot(
        ["bad/repo", "good/repo"], runner=runner, generated_at="2026-08-19T11:00:00Z"
    )
    assert [item["full_name"] for item in snapshot["repositories"]] == ["good/repo"]
    assert snapshot["collection_errors"] == [
        {"repository": "bad/repo", "error": "GitHub API read failed for repos/bad/repo: rate limit"}
    ]

    report = queue_health.build_report(snapshot, now=NOW)
    assert report["summary"]["collection_error_count"] == 1
    assert report["collection_errors"] == snapshot["collection_errors"]
    assert "bad/repo" in queue_health.render_html(report)


@pytest.mark.parametrize(
    "collection_errors",
    [
        "bad",
        [None],
        [{"repository": "../..", "error": "bad"}],
        [{"repository": "owner/repo", "error": 1}],
    ],
)
def test_build_report_rejects_malformed_collection_errors(collection_errors: object) -> None:
    """Reject malformed collection errors without inventing missing evidence."""
    snapshot = report_snapshot()
    snapshot["collection_errors"] = collection_errors
    with pytest.raises(queue_health.QueueHealthError):
        queue_health.build_report(snapshot, now=NOW)

    snapshot["collection_errors"] = None
    assert queue_health.build_report(snapshot, now=NOW)["summary"]["collection_error_count"] == 0


def test_collect_snapshot_bounds_workflow_run_payloads_to_fifty_items() -> None:
    """Avoid oversized Actions run responses while retaining bounded pagination."""
    requested_paths: list[str] = []

    def runner(args: list[str], **kwargs: object) -> CompletedProcess[str]:
        """Return empty bounded run pages and record the requested endpoints."""
        path = args[-1]
        requested_paths.append(path)
        if path == "repos/owner/repo":
            payload: object = {"default_branch": "main"}
        elif path == "repos/owner/repo/pulls?state=open&per_page=100":
            payload = []
        elif "/actions/runs?status=" in path:
            payload = {"total_count": 0, "workflow_runs": []}
        else:  # pragma: no cover - a new endpoint must be explicitly governed
            raise AssertionError(f"unexpected endpoint: {path}")
        if "--paginate" in args:
            payload = [payload]
        return CompletedProcess(args, 0, json.dumps(payload), "")

    queue_health.collect_snapshot(
        ["owner/repo"], runner=runner, generated_at="2026-08-19T11:00:00Z"
    )

    run_paths = [path for path in requested_paths if "/actions/runs?status=" in path]
    assert run_paths == [
        "repos/owner/repo/actions/runs?status=in_progress&per_page=50",
        "repos/owner/repo/actions/runs?status=queued&per_page=50",
    ]


def test_load_snapshot_and_identity_helpers(tmp_path: Path) -> None:
    """Load offline snapshots and classify current, obsolete, and unlinked runs."""
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(report_snapshot()), encoding="utf-8")
    assert queue_health.load_snapshot(path)["generated_at"] == "2026-08-19T11:00:00Z"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(queue_health.QueueHealthError):
        queue_health.load_snapshot(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(queue_health.QueueHealthError):
        queue_health.load_snapshot(path)
    with pytest.raises(queue_health.QueueHealthError):
        queue_health.load_snapshot(tmp_path / "missing.json")

    current_run = {"head_sha": "head", "pull_requests": [{"number": 1}]}
    assert queue_health._run_identity(current_run, {1: {"head_sha": "head"}}) == ("current_head", 1)
    assert queue_health._run_identity(current_run, {1: {"head_sha": "other"}}) == ("obsolete", 1)
    assert queue_health._run_identity({"pull_requests": []}, {}) == ("unlinked", None)


def test_job_state_and_queue_age_cover_pending_terminal_and_unknown_paths() -> None:
    """Classify job assignment states and calculate bounded queue age."""
    assert queue_health._job_state({"status": "queued", "runner_id": 1}) == ("queued_assigned", True, True)
    assert queue_health._job_state({"status": "in_progress", "runner_name": "runner"}) == (
        "queued_assigned",
        True,
        True,
    )
    assert queue_health._job_state({"status": "queued"}) == ("queued_unassigned", True, False)
    assert queue_health._job_state({"status": "completed"}) == ("terminal", False, False)
    assert queue_health._job_state({"status": "", "conclusion": "failure"}) == ("terminal", False, False)
    assert queue_health._job_state({"status": "waiting"}) == ("unknown", False, False)
    assert queue_health._format_age("2026-08-19T10:00:00Z", NOW) == 7200
    assert queue_health._format_age("2026-08-19T13:00:00Z", NOW) == 0
    with pytest.raises(queue_health.QueueHealthError):
        queue_health._format_age("bad", NOW)


def test_build_report_classifies_exact_head_and_external_blockers() -> None:
    """Report exact-head, stale, unlinked, terminal, and SLO evidence separately."""
    report = queue_health.build_report(report_snapshot(), now=NOW, queue_age_slo_seconds=900)
    assert report["schema_version"] == "actions.queue_health.v1"
    assert report["summary"]["observed_job_count"] == 7
    assert report["summary"]["pending_job_count"] == 5
    assert report["summary"]["current_head_pending_count"] == 3
    assert report["summary"]["unassigned_slo_breached_count"] == 2
    assert report["summary"]["obsolete_job_count"] == 1
    assert report["summary"]["unlinked_job_count"] == 1
    assert report["summary"]["duplicate_pending_lane_count"] == 1
    assert report["summary"]["terminal_job_count"] == 1
    assert report["duplicate_pending_lanes"][0]["count"] == 3
    assert any(row["blocker"] == "obsolete_run_requires_identity_confirmed_cleanup" for row in report["runs"])
    assert any(row["blocker"] == "run_not_linked_to_pull_request" for row in report["runs"])
    assert report["runs"] == sorted(report["runs"], key=lambda row: (row["repository"], row["run_id"], row["job_id"]))
    assert queue_health.build_report(report_snapshot(), now=NOW, queue_age_slo_seconds=7200)["summary"]["unassigned_slo_breached_count"] == 0
    assert queue_health.build_report(report_snapshot(), queue_age_slo_seconds=0)["summary"]["observed_job_count"] == 7


@pytest.mark.parametrize(
    "snapshot, message",
    [
        ({"generated_at": "2026-08-19T11:00:00Z", "repositories": "bad"}, "repositories"),
        ({"generated_at": "2026-08-19T11:00:00Z", "repositories": ["bad"]}, "repository entry"),
        (
            {"generated_at": "2026-08-19T11:00:00Z", "repositories": [{"full_name": "owner/repo", "pull_requests": "bad", "runs": []}]},
            "pull requests",
        ),
        (
            {"generated_at": "2026-08-19T11:00:00Z", "repositories": [{"full_name": "owner/repo", "pull_requests": [], "runs": "bad"}]},
            "runs",
        ),
        (
            {"generated_at": "2026-08-19T11:00:00Z", "repositories": [{"full_name": "owner/repo", "pull_requests": [], "runs": ["bad"]}]},
            "workflow run entry",
        ),
    ],
)
def test_build_report_rejects_malformed_snapshot_shapes(snapshot: dict, message: str) -> None:
    """Reject malformed snapshot containers before counting jobs."""
    with pytest.raises(queue_health.QueueHealthError, match=message):
        queue_health.build_report(snapshot, now=NOW)


def test_build_report_rejects_duplicate_and_invalid_entries() -> None:
    """Reject duplicate identities and invalid report boundaries."""
    duplicate_repository = report_snapshot()
    duplicate_repository["repositories"].append(
        dict(duplicate_repository["repositories"][0])
    )
    with pytest.raises(queue_health.QueueHealthError, match="duplicate repository entry"):
        queue_health.build_report(duplicate_repository, now=NOW)

    duplicate_pr = report_snapshot()
    duplicate_pr["repositories"][0]["pull_requests"].append(pull_request(1, "other"))
    with pytest.raises(queue_health.QueueHealthError, match="duplicate pull request"):
        queue_health.build_report(duplicate_pr, now=NOW)

    duplicate_run = report_snapshot()
    duplicate_run["repositories"][0]["runs"].append(workflow_run(10))
    with pytest.raises(queue_health.QueueHealthError, match="duplicate workflow run"):
        queue_health.build_report(duplicate_run, now=NOW)

    invalid_jobs = report_snapshot()
    invalid_jobs["repositories"][0]["runs"][0]["jobs"] = "bad"
    with pytest.raises(queue_health.QueueHealthError, match="jobs"):
        queue_health.build_report(invalid_jobs, now=NOW)

    with pytest.raises(queue_health.QueueHealthError, match="negative"):
        queue_health.build_report(report_snapshot(), now=NOW, queue_age_slo_seconds=-1)
    with pytest.raises(queue_health.QueueHealthError, match="timestamp"):
        queue_health.build_report({"generated_at": "bad", "repositories": []}, now=NOW)
    with pytest.raises(queue_health.QueueHealthError, match="evaluation time"):
        queue_health.build_report(report_snapshot(), now=datetime(2026, 8, 19, 12, 0))

    for key in ("pull_requests", "runs"):
        null_entry = {"generated_at": "2026-08-19T11:00:00Z", "repositories": [{"full_name": "owner/repo", key: None}]}
        assert queue_health.build_report(null_entry, now=NOW)["summary"]["observed_job_count"] == 0
    null_jobs = {
        "generated_at": "2026-08-19T11:00:00Z",
        "repositories": [{"full_name": "owner/repo", "runs": [{"id": 1, "created_at": "2026-08-19T10:00:00Z", "jobs": None}]}],
    }
    assert queue_health.build_report(null_jobs, now=NOW)["summary"]["observed_job_count"] == 1


def test_render_and_write_reports_escape_fields_and_support_empty_reports(tmp_path: Path) -> None:
    """Escape HTML fields and write both populated and empty reports."""
    report = queue_health.build_report(report_snapshot(), now=NOW)
    report["runs"][0]["blocker"] = "<script>alert(1)</script>"
    rendered = queue_health.render_html(report)
    assert "&lt;script&gt;" in rendered
    assert '<th scope="row">owner/repo</th>' in rendered
    assert "queue-age SLO: 900 seconds" in rendered

    empty = queue_health.build_report({"generated_at": "2026-08-19T11:00:00Z", "repositories": []}, now=NOW)
    assert "No queued or in-progress jobs observed." in queue_health.render_html(empty)

    json_path = tmp_path / "nested" / "report.json"
    html_path = tmp_path / "nested" / "report.html"
    queue_health.write_reports(report, json_path, html_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["schema_version"] == "actions.queue_health.v1"
    assert "<html" in html_path.read_text(encoding="utf-8")


def test_cli_arguments_and_main_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Exercise snapshot mode, allowlist mode, and bounded CLI failures."""
    args = queue_health.parse_args(
        ["--snapshot", "snapshot.json", "--output-json", "out.json", "--output-html", "out.html"]
    )
    assert args.snapshot == Path("snapshot.json")
    args = queue_health.parse_args(
        ["--allowlist", "allowlist.json", "--output-json", "out.json", "--output-html", "out.html"]
    )
    assert args.allowlist == Path("allowlist.json")
    with pytest.raises(SystemExit):
        queue_health.parse_args(["--snapshot", "a", "--allowlist", "b", "--output-json", "o", "--output-html", "h"])

    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(report_snapshot()), encoding="utf-8")
    json_path = tmp_path / "out.json"
    html_path = tmp_path / "out.html"
    assert queue_health.main(
        [
            "--snapshot",
            str(snapshot_path),
            "--output-json",
            str(json_path),
            "--output-html",
            str(html_path),
            "--now",
            "2026-08-19T12:00:00Z",
        ]
    ) == 0
    assert "QUEUE_HEALTH_RESULT=" in capsys.readouterr().out

    empty_snapshot_path = tmp_path / "empty-snapshot.json"
    empty_snapshot_path.write_text(
        json.dumps({"generated_at": "2026-08-19T11:00:00Z", "repositories": []}),
        encoding="utf-8",
    )
    assert queue_health.main(
        [
            "--snapshot",
            str(empty_snapshot_path),
            "--output-json",
            str(json_path),
            "--output-html",
            str(html_path),
            "--now",
            "2026-08-19T12:00:00Z",
        ]
    ) == 0
    assert "::warning::" not in capsys.readouterr().out

    error = io.StringIO()
    assert queue_health.main(
        ["--snapshot", str(tmp_path / "missing.json"), "--output-json", "o", "--output-html", "h"],
        stderr=error,
    ) == 2
    assert "ERROR:" in error.getvalue()

    allowlist_path = tmp_path / "allowlist.json"
    allowlist_path.write_text(json.dumps(["owner/repo"]), encoding="utf-8")
    original_collect = queue_health.collect_snapshot
    queue_health.collect_snapshot = lambda repositories: report_snapshot()  # type: ignore[assignment]
    try:
        assert queue_health.main(
            ["--allowlist", str(allowlist_path), "--output-json", str(json_path), "--output-html", str(html_path)]
        ) == 0
    finally:
        queue_health.collect_snapshot = original_collect
    assert "QUEUE_HEALTH_RESULT=" in capsys.readouterr().out
