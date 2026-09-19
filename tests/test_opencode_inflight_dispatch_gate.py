"""Tests for same-head OpenCode Review Dispatch in-flight dedupe."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from scripts.ci import opencode_inflight_dispatch_gate as gate

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "opencode-review.yml"

TARGET = "ContextualWisdomLab/pg-erd-cloud"
PR = 1183
HEAD = "9a759df24e8b714348ac2d240491f74ee3fc852d"


def test_dispatch_run_title_matches_workflow_run_name() -> None:
    """Title must match opencode-review-dispatch.yml run-name exactly."""
    assert (
        gate.dispatch_run_title(TARGET, PR, HEAD)
        == f"OpenCode Review Dispatch {TARGET}#{PR}@{HEAD}"
    )


def test_validate_inputs_rejects_non_canonical_values() -> None:
    """Malformed repo / PR / SHA fail closed before any Actions listing."""
    with pytest.raises(gate.InFlightDispatchError):
        gate.validate_inputs("../evil", "1183", HEAD)
    with pytest.raises(gate.InFlightDispatchError):
        gate.validate_inputs(TARGET, "0", HEAD)
    with pytest.raises(gate.InFlightDispatchError):
        gate.validate_inputs(TARGET, "1183", "9a759df")


def test_matching_inflight_runs_requires_exact_head() -> None:
    """Older-head and other-PR titles must not suppress a current-head dispatch."""
    runs: list[dict[str, Any]] = [
        {
            "id": 1,
            "display_title": gate.dispatch_run_title(TARGET, PR, HEAD),
        },
        {
            "id": 2,
            "display_title": gate.dispatch_run_title(
                TARGET, PR, "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            ),
        },
        {
            "id": 3,
            "display_title": gate.dispatch_run_title(
                "ContextualWisdomLab/appguardrail", PR, HEAD
            ),
        },
    ]
    matched = gate.matching_inflight_runs(
        runs, target_repository=TARGET, pr_number=PR, head_sha=HEAD
    )
    assert [run["id"] for run in matched] == [1]


def test_evaluate_inflight_reports_present_when_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queued exact-head central runs are present; caller must skip re-dispatch."""

    def fake_list(*, token: str, status: str, per_page: int = 100) -> list[dict[str, Any]]:
        assert token == "tok"
        if status == "queued":
            return [
                {
                    "id": 35412595263,
                    "display_title": gate.dispatch_run_title(TARGET, PR, HEAD),
                }
            ]
        return []

    monkeypatch.setattr(gate, "list_repository_dispatch_runs", fake_list)
    state, run_ids = gate.evaluate_inflight(
        target_repository=TARGET,
        pr_number=str(PR),
        head_sha=HEAD,
        token="tok",
    )
    assert state == "present"
    assert run_ids == ["35412595263"]


def test_evaluate_inflight_reports_missing_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No matching runs means the required path may post one dispatch."""

    monkeypatch.setattr(
        gate,
        "list_repository_dispatch_runs",
        lambda **_kwargs: [],
    )
    state, run_ids = gate.evaluate_inflight(
        target_repository=TARGET,
        pr_number=str(PR),
        head_sha=HEAD,
        token="tok",
    )
    assert state == "missing"
    assert run_ids == []


def test_required_workflow_skips_duplicate_dispatch_when_inflight() -> None:
    """Required OpenCode entrypoint must consult the in-flight gate before POST."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/ci/opencode_inflight_dispatch_gate.py" in workflow
    assert "Exact-head OpenCode Review Dispatch already queued or running" in workflow
    assert "duplicate repository_dispatch skipped" in workflow
    request = workflow.split("Request current-head OpenCode review execution\n", 1)[1]
    request = request.split("\n      - name: Fail closed without a current-head OpenCode verdict\n", 1)[0]
    assert "opencode_inflight_dispatch_gate.py" in request
    assert request.index("opencode_inflight_dispatch_gate.py") < request.index(
        "repos/ContextualWisdomLab/.github/dispatches"
    )
    assert '[ "$inflight_state" = "present" ]' in request
    assert '[ "$inflight_state" = "missing" ]' in request
    # Fail-closed verdict step remains after the dispatch step.
    assert "will rerun this failed job" in workflow
    assert "No APPROVED or CHANGES_REQUESTED from opencode-agent on the current head" in workflow


def test_main_prints_state(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI prints only the machine state on stdout for the workflow branch."""

    monkeypatch.setenv("GH_TOKEN", "tok")
    monkeypatch.setattr(
        gate,
        "evaluate_inflight",
        lambda **_kwargs: ("missing", []),
    )
    assert gate.main(
        [
            "--target-repository",
            TARGET,
            "--pr-number",
            str(PR),
            "--head-sha",
            HEAD,
        ]
    ) == 0
    assert capsys.readouterr().out.strip() == "missing"


def test_main_prints_present_run_ids_on_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Present state lists matching run ids on stderr for operators."""

    monkeypatch.setenv("GH_TOKEN", "tok")
    monkeypatch.setattr(
        gate,
        "evaluate_inflight",
        lambda **_kwargs: ("present", ["99"]),
    )
    assert (
        gate.main(
            [
                "--target-repository",
                TARGET,
                "--pr-number",
                str(PR),
                "--head-sha",
                HEAD,
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out.strip() == "present"
    assert "99" in captured.err


def test_main_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing token fails closed before listing Actions runs."""

    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert (
        gate.main(
            [
                "--target-repository",
                TARGET,
                "--pr-number",
                str(PR),
                "--head-sha",
                HEAD,
            ]
        )
        == 2
    )


def test_main_maps_inflight_errors(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """InFlightDispatchError becomes exit 2 with an error annotation."""

    monkeypatch.setenv("GH_TOKEN", "tok")

    def boom(**_kwargs: object) -> tuple[str, list[str]]:
        raise gate.InFlightDispatchError("nope")

    monkeypatch.setattr(gate, "evaluate_inflight", boom)
    assert (
        gate.main(
            [
                "--target-repository",
                TARGET,
                "--pr-number",
                str(PR),
                "--head-sha",
                HEAD,
            ]
        )
        == 2
    )
    assert "nope" in capsys.readouterr().err


def test_gh_api_json_rejects_nonzero_and_non_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Transport and parse failures stay fail-closed."""

    class _Done:
        def __init__(self, code: int, stdout: str = "", stderr: str = "") -> None:
            self.returncode = code
            self.stdout = stdout
            self.stderr = stderr

    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_a, **_k: _Done(1, stderr="boom"),
    )
    with pytest.raises(gate.InFlightDispatchError, match="failed"):
        gate._gh_api_json(["repos/x/y"], token="t")

    monkeypatch.setattr(
        gate.subprocess,
        "run",
        lambda *_a, **_k: _Done(0, stdout="not-json"),
    )
    with pytest.raises(gate.InFlightDispatchError, match="non-JSON"):
        gate._gh_api_json(["repos/x/y"], token="t")


def test_list_repository_dispatch_runs_filters_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only mapping workflow_runs entries are retained."""

    monkeypatch.setattr(
        gate,
        "_gh_api_json",
        lambda *_a, **_k: {"workflow_runs": [{"id": 1}, "skip", {"id": 2}]},
    )
    runs = gate.list_repository_dispatch_runs(token="t", status="queued")
    assert [run["id"] for run in runs] == [1, 2]

    monkeypatch.setattr(gate, "_gh_api_json", lambda *_a, **_k: [])
    with pytest.raises(gate.InFlightDispatchError, match="not an object"):
        gate.list_repository_dispatch_runs(token="t", status="queued")

    monkeypatch.setattr(gate, "_gh_api_json", lambda *_a, **_k: {"workflow_runs": None})
    assert gate.list_repository_dispatch_runs(token="t", status="queued") == []


def test_evaluate_inflight_ignores_runs_without_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Title matches without an id do not count as present."""

    monkeypatch.setattr(
        gate,
        "list_repository_dispatch_runs",
        lambda **_k: [
            {"display_title": gate.dispatch_run_title(TARGET, PR, HEAD)},
        ],
    )
    state, run_ids = gate.evaluate_inflight(
        target_repository=TARGET,
        pr_number=str(PR),
        head_sha=HEAD,
        token="tok",
    )
    assert state == "missing"
    assert run_ids == []
