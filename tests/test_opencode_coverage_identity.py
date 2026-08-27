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
