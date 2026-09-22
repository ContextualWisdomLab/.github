"""Close merge, execution-contract, and sandbox defensive branch coverage."""

from __future__ import annotations

import itertools
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import pr_review_merge_scheduler as merge_scheduler
from scripts.ci import r_coverage_peer_gate
from scripts.ci import review_execution_contracts as execution_contracts
from scripts.ci import sandboxed_verify, sandboxed_web_e2e


def test_merge_scheduler_blocked_wait_reason_names_unsatisfied_review_policy() -> None:
    """BLOCKED mergeability identifies a non-approved GitHub review decision."""

    reason = merge_scheduler.auto_merge_wait_reason(
        "BLOCKED", {"reviewDecision": "CHANGES_REQUESTED"}
    )
    assert "CHANGES_REQUESTED" in reason
    assert "required approving review" in reason


def test_merge_scheduler_conflict_summary_without_changed_file_hints() -> None:
    """Conflict guidance remains actionable when no changed-file hint is available."""

    decision = merge_scheduler.Decision(
        pr=7,
        action="wait",
        reason="merge conflict: DIRTY; base=main, head=feature",
    )
    lines = merge_scheduler.conflict_repair_summary([decision])
    assert "### Conflict repair" in lines
    assert "Changed files to inspect first:" not in lines


def test_merge_scheduler_restamp_summary_ignores_unrelated_notes() -> None:
    """Only notes describing the last-push refresh are rendered as restamp evidence."""

    decision = merge_scheduler.Decision(
        pr=8,
        action="restamp",
        reason="last-push approval head refresh required",
        notes=("unrelated note",),
    )
    lines = merge_scheduler.last_push_approval_restamp_summary([decision])
    assert any("PR #8" in line for line in lines)
    assert "  - unrelated note" not in lines


def test_r_description_indented_line_before_suggests_is_ignored() -> None:
    """Continuation text outside Suggests does not enter the dependency set."""

    assert r_coverage_peer_gate.declared_suggests(
        "Package: demo\n  stray continuation\nSuggests: testthat, covr\n"
    ) == {"testthat", "covr"}


def test_execution_contract_helpers_cover_duplicate_unknown_and_minimal_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Defensive command indexing and minimal package branches stay deterministic."""

    bucket: dict[str, list[str]] = {}
    execution_contracts.add_unique(bucket, "test", "")
    execution_contracts.add_unique(bucket, "test", "pytest")
    execution_contracts.add_unique(bucket, "test", "pytest")
    assert bucket == {"test": ["pytest"]}

    contracts: dict[str, Any] = {"test_commands": []}
    execution_contracts.add_command_indexes(
        contracts, {"unknown": ["ignored"], "test": ["pytest"]}
    )
    assert contracts["test_commands"] == ["pytest"]

    package = tmp_path / "package.json"
    package.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(execution_contracts, "package_runner", lambda _path: "bun")
    node = execution_contracts.discover_package_json(package, tmp_path)
    assert node["commands"] == {}

    pyproject = tmp_path / "minimal" / "pyproject.toml"
    pyproject.parent.mkdir()
    pyproject.write_text("[project]\nname='minimal'\n", encoding="utf-8")
    python_contract = execution_contracts.discover_pyproject(pyproject, tmp_path)
    assert python_contract["commands"]["security"]
    assert "test" not in python_contract["commands"]
    assert "lint" not in python_contract["commands"]


def test_execution_contract_discovery_skips_packaged_and_ignored_surfaces(
    tmp_path: Path,
) -> None:
    """Manifest-backed source and ignored virtual-environment manifests take false branches."""

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "go.mod").write_text("module example.invalid/demo\n", encoding="utf-8")
    (repo / "main.go").write_text("package main\n", encoding="utf-8")
    assert not any(
        item["language"] == "go"
        for item in execution_contracts.discover_unpackaged_surfaces(repo)
    )

    node_modules = repo / "node_modules" / "pkg"
    node_modules.mkdir(parents=True)
    (node_modules / "package.json").write_text("{}", encoding="utf-8")
    venv = repo / ".venv"
    venv.mkdir()
    (venv / "pyproject.toml").write_text("[project]\nname='ignored'\n", encoding="utf-8")
    (repo / "Dockerfile").mkdir()
    result = execution_contracts.discover_contracts(repo)
    assert result["node"] == []
    assert result["python"] == []
    assert result["docker"] == []


def test_sandboxed_verify_timeout_with_no_streams_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A timeout without captured streams still returns the stable timeout code."""

    repo = tmp_path / "repo"
    repo.mkdir()

    def timeout_runner(
        command: list[str], _cwd: Path, _env: dict[str, str], timeout: int
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, timeout, output=None, stderr=None)

    monkeypatch.setattr(sandboxed_verify, "run_command", timeout_runner)
    assert sandboxed_verify.main(
        ["--repo-root", str(repo), "--timeout", "1", "--", "true"]
    ) == 124
    captured = capsys.readouterr()
    assert "command timed out" in captured.err


def test_web_readiness_retries_5xx_and_timeout_without_streams(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A 5xx is not ready, and a streamless E2E timeout remains deterministic."""

    class RunningProcess:
        def poll(self) -> None:
            return None

    class Response:
        status = 503

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

    class Opener:
        def open(self, _url: str, timeout: int) -> Response:
            assert timeout == 2
            return Response()

    ticks = itertools.chain([0.0, 0.0], itertools.repeat(2.0))
    monkeypatch.setattr(
        sandboxed_web_e2e.urllib.request, "build_opener", lambda *_args: Opener()
    )
    monkeypatch.setattr(
        sandboxed_web_e2e.time, "monotonic", lambda: next(ticks)
    )
    monkeypatch.setattr(sandboxed_web_e2e.time, "sleep", lambda _seconds: None)
    service = sandboxed_web_e2e.Service(
        "web", "serve", RunningProcess(), tmp_path / "web.log"  # type: ignore[arg-type]
    )
    assert not sandboxed_web_e2e.wait_for_url("http://127.0.0.1:8000", 1, service)

    monkeypatch.setattr(sandboxed_web_e2e.time, "monotonic", lambda: 2.0)

    repo = tmp_path / "repo"
    repo.mkdir()

    class DoneProcess:
        def poll(self) -> int:
            return 0

    def start_service(
        label: str,
        command: str,
        _cwd: Path,
        _env: dict[str, str],
        logs_dir: Path,
    ) -> sandboxed_web_e2e.Service:
        log_path = logs_dir / f"{label}.log"
        log_path.write_text("", encoding="utf-8")
        return sandboxed_web_e2e.Service(
            label, command, DoneProcess(), log_path  # type: ignore[arg-type]
        )

    def timeout_runner(
        command: str, _cwd: Path, _env: dict[str, str], timeout: int
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, timeout, output=None, stderr=None)

    monkeypatch.setattr(sandboxed_web_e2e, "start_service", start_service)
    monkeypatch.setattr(sandboxed_web_e2e, "wait_for_url", lambda *_args: True)
    monkeypatch.setattr(sandboxed_web_e2e, "run_shell", timeout_runner)
    monkeypatch.setattr(sandboxed_web_e2e, "stop_service", lambda _service: None)
    assert sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--backend-cmd",
            "backend",
            "--frontend-cmd",
            "frontend",
            "--e2e-cmd",
            "e2e",
            "--e2e-timeout",
            "1",
        ]
    ) == 124
    assert "e2e command timed out" in capsys.readouterr().err
