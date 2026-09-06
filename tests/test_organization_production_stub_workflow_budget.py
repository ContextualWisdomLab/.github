from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

WORKFLOW_PATH = Path(".github/workflows/organization-production-stub-scan.yml")


def selector_script() -> str:
    """Return the embedded repository-selection program from the workflow."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    marker = "python3 - <<'PY'\n"
    block = text.split(marker, 1)[1].split("\n          PY", 1)[0]
    return textwrap.dedent(block)


def run_selector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    repositories: list[dict[str, object]],
    *,
    event_name: str,
    epoch_hour: int,
    max_repositories: int,
    continuation_offset: int = 0,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Execute the embedded selector with deterministic inputs and return its receipt."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "repositories.json").write_text(
        json.dumps(repositories), encoding="utf-8"
    )
    for name, value in {
        "RUNNER_TEMP": str(tmp_path),
        "EVENT_NAME": event_name,
        "SHARD_COUNT": "12",
        "MAX_REPOSITORIES_PER_RUN": str(max_repositories),
        "CONTINUATION_OFFSET": str(continuation_offset),
        "SELECTION_EPOCH_HOUR": str(epoch_hour),
    }.items():
        monkeypatch.setenv(name, value)

    exec(compile(selector_script(), "<workflow-selector>", "exec"), {})

    selected = json.loads(
        (tmp_path / "selected-repositories.json").read_text(encoding="utf-8")
    )
    receipt = json.loads(
        (tmp_path / "selection-receipt.json").read_text(encoding="utf-8")
    )
    return selected, receipt


def repositories(count: int) -> list[dict[str, object]]:
    """Build a stable sorted repository inventory for selection tests."""
    return [
        {
            "full_name": f"ContextualWisdomLab/repository-{index:03d}",
            "default_branch": "main",
            "has_issues": True,
        }
        for index in range(count)
    ]


def test_workflow_declares_a_hard_selection_budget_and_continuation_receipt() -> None:
    """Prevent max-parallel from being mistaken for a bound on matrix cardinality."""
    text = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "MAX_REPOSITORIES_PER_RUN: '12'" in text
    assert (
        "CONTINUATION_OFFSET: ${{ github.event.client_payload.continuation_offset || '0' }}"
        in text
    )
    assert "selection-receipt.json" in text
    assert "deferred_repository_count" in text
    assert "next_continuation_offset" in text
    assert "max_repositories_per_run" in text


def test_schedule_rotates_a_bounded_window_without_starving_the_shard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Advance a deterministic window each time the same shard recurs."""
    inventory = repositories(240)

    first, first_receipt = run_selector(
        tmp_path / "first",
        monkeypatch,
        inventory,
        event_name="schedule",
        epoch_hour=0,
        max_repositories=3,
    )
    second, second_receipt = run_selector(
        tmp_path / "second",
        monkeypatch,
        inventory,
        event_name="schedule",
        epoch_hour=12,
        max_repositories=3,
    )

    assert len(first) == len(second) == 3
    assert {item["full_name"] for item in first}.isdisjoint(
        {item["full_name"] for item in second}
    )
    assert first_receipt["eligible_repository_count"] > 3
    assert first_receipt["deferred_repository_count"] > 0
    assert second_receipt["continuation_offset"] == 3
    assert first_receipt["selection_mode"] == "scheduled_shard"


def test_dispatch_uses_explicit_bounded_offsets_for_full_fleet_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expose deterministic operator replay instead of silently creating an unbounded matrix."""
    inventory = repositories(10)

    selected, receipt = run_selector(
        tmp_path,
        monkeypatch,
        inventory,
        event_name="repository_dispatch",
        epoch_hour=0,
        max_repositories=4,
        continuation_offset=4,
    )

    assert [item["full_name"] for item in selected] == [
        f"ContextualWisdomLab/repository-{index:03d}" for index in range(4, 8)
    ]
    assert receipt == {
        "complete": False,
        "continuation_offset": 4,
        "deferred_repository_count": 2,
        "eligible_repository_count": 10,
        "max_repositories_per_run": 4,
        "next_continuation_offset": 8,
        "scheduled_shard": None,
        "schema": "cwl.implementation-completeness-selection/v1",
        "selected_repository_count": 4,
        "selection_mode": "dispatch_continuation",
    }


def test_empty_scheduled_shard_is_a_successful_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Treat an empty hash shard as normal hourly operation rather than failure."""
    selected, receipt = run_selector(
        tmp_path,
        monkeypatch,
        [],
        event_name="schedule",
        epoch_hour=0,
        max_repositories=12,
    )

    assert selected == []
    assert receipt["eligible_repository_count"] == 0
    assert receipt["selected_repository_count"] == 0
    assert receipt["complete"] is True


def test_dispatch_rejects_an_out_of_range_continuation_offset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed when a replay offset cannot identify any repository."""
    with pytest.raises(SystemExit, match="CONTINUATION_OFFSET"):
        run_selector(
            tmp_path,
            monkeypatch,
            repositories(2),
            event_name="repository_dispatch",
            epoch_hour=0,
            max_repositories=1,
            continuation_offset=2,
        )
