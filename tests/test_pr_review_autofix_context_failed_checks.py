"""Coverage and fail-closed contracts for failed-check RCA evidence."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci import pr_review_autofix_context as context


def test_pr_changed_paths_keeps_only_safe_existing_unique_paths(monkeypatch) -> None:
    """RCA edit scope excludes removed, duplicate, unsafe, and control-plane paths."""
    pages = [
        [
            {"filename": "src/application.py", "status": "modified"},
            {"filename": "src/application.py", "status": "added"},
            {"filename": "src/removed.py", "status": "removed"},
            {"filename": ".github/workflows/untrusted.yml", "status": "modified"},
            {"filename": "docs/../escaped.md", "status": "modified"},
            {"filename": "", "status": "modified"},
        ],
        [
            {"filename": "tests/test_application.py", "status": None},
        ],
    ]
    calls: list[list[str]] = []

    def fake_run_json(args: list[str]) -> list[list[dict[str, object]]]:
        calls.append(args)
        return pages

    monkeypatch.setattr(context, "run_json", fake_run_json)

    assert context.pr_changed_paths("owner/repo", 17) == [
        "src/application.py",
        "tests/test_application.py",
    ]
    assert calls == [
        [
            "api",
            "repos/owner/repo/pulls/17/files",
            "--paginate",
            "--slurp",
        ]
    ]


def test_review_requires_rca_returns_false_without_failed_check_marker() -> None:
    """Ordinary reviews and nonfailure change requests never widen RCA scope."""
    assert not context.review_requires_rca([])
    assert not context.review_requires_rca(
        [
            {"state": "APPROVED", "body": "Coverage-evidence passed."},
            {"state": "COMMENTED", "body": "CodeQL failed in an old note."},
        ]
    )
    assert not context.review_requires_rca(
        [{"state": "CHANGES_REQUESTED", "body": "Please rename this symbol."}]
    )


def test_review_requires_rca_checks_every_change_request() -> None:
    """One exact-head failed-check review cannot be hidden by a later ordinary one."""
    assert context.review_requires_rca(
        [
            {
                "state": "CHANGES_REQUESTED",
                "body": "Coverage-evidence failed on this exact head.",
            },
            {
                "state": "CHANGES_REQUESTED",
                "body": "Please rename this symbol.",
            },
        ]
    )


def _bind_fake_collector(monkeypatch, tmp_path: Path) -> Path:
    """Point the module at one regular trusted sibling collector."""
    module_path = tmp_path / "pr_review_autofix_context.py"
    module_path.write_text("# test module anchor\n", encoding="utf-8")
    collector = tmp_path / "collect_failed_check_evidence.sh"
    collector.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setattr(context, "__file__", str(module_path))
    return collector


def test_collect_failed_check_evidence_runs_trusted_sibling_and_bounds_output(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """The collector receives exact identity and returns only the bounded report."""
    collector = _bind_fake_collector(monkeypatch, tmp_path)
    output = tmp_path / "failed-checks.md"
    seen: dict[str, object] = {}
    oversized = "x" * (context._MAX_FAILED_CHECK_EVIDENCE_CHARS + 9)

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen["args"] = args
        seen["kwargs"] = kwargs
        output.write_text(oversized, encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(context.subprocess, "run", fake_run)

    result = context.collect_failed_check_evidence(
        "owner/repo",
        19,
        "a" * 40,
        output,
    )

    assert result == oversized[: context._MAX_FAILED_CHECK_EVIDENCE_CHARS]
    assert seen["args"] == ["bash", str(collector), str(output)]
    kwargs = seen["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["check"] is False
    assert kwargs["shell"] is False
    assert kwargs["text"] is True
    env = kwargs["env"]
    assert isinstance(env, dict)
    assert env["GH_REPOSITORY"] == "owner/repo"
    assert env["PR_NUMBER"] == "19"
    assert env["HEAD_SHA"] == "a" * 40


@pytest.mark.parametrize("collector_kind", ["missing", "symlink"])
def test_collect_failed_check_evidence_rejects_untrusted_collector(
    monkeypatch,
    tmp_path: Path,
    collector_kind: str,
) -> None:
    """Missing and symlinked collector programs fail before subprocess execution."""
    module_path = tmp_path / "pr_review_autofix_context.py"
    module_path.write_text("# test module anchor\n", encoding="utf-8")
    monkeypatch.setattr(context, "__file__", str(module_path))
    collector = tmp_path / "collect_failed_check_evidence.sh"
    if collector_kind == "symlink":
        target = tmp_path / "collector-target.sh"
        target.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        collector.symlink_to(target)

    def unexpected_run(*args: object, **kwargs: object) -> None:
        raise AssertionError("untrusted collector must not execute")

    monkeypatch.setattr(context.subprocess, "run", unexpected_run)

    with pytest.raises(RuntimeError, match="trusted failed-check evidence collector"):
        context.collect_failed_check_evidence(
            "owner/repo",
            19,
            "a" * 40,
            tmp_path / "failed-checks.md",
        )


@pytest.mark.parametrize(
    ("stderr", "expected_detail"),
    [
        ("first diagnostic\nlast diagnostic\n", "last diagnostic"),
        ("", "unknown error"),
    ],
)
def test_collect_failed_check_evidence_surfaces_bounded_failure_detail(
    monkeypatch,
    tmp_path: Path,
    stderr: str,
    expected_detail: str,
) -> None:
    """Collector process failures remain fatal with one bounded terminal detail."""
    _bind_fake_collector(monkeypatch, tmp_path)

    def failed_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 7, stdout="", stderr=stderr)

    monkeypatch.setattr(context.subprocess, "run", failed_run)

    with pytest.raises(RuntimeError, match=expected_detail):
        context.collect_failed_check_evidence(
            "owner/repo",
            19,
            "a" * 40,
            tmp_path / "failed-checks.md",
        )


@pytest.mark.parametrize("output_kind", ["missing", "symlink"])
def test_collect_failed_check_evidence_rejects_nonregular_output(
    monkeypatch,
    tmp_path: Path,
    output_kind: str,
) -> None:
    """A successful process cannot authorize missing or symlinked evidence output."""
    _bind_fake_collector(monkeypatch, tmp_path)
    output = tmp_path / "failed-checks.md"

    def successful_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if output_kind == "symlink":
            target = tmp_path / "evidence-target.md"
            target.write_text("redacted", encoding="utf-8")
            output.symlink_to(target)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(context.subprocess, "run", successful_run)

    with pytest.raises(RuntimeError, match="produced no regular file"):
        context.collect_failed_check_evidence(
            "owner/repo",
            19,
            "a" * 40,
            output,
        )
