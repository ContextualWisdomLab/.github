from __future__ import annotations

import json
from pathlib import Path

import pytest

from organization_commercial_readiness_fixtures import (
    FailingDispatchClient,
    FakeClient,
    manual_workflow,
    pull,
    repository_payload,
    snapshot,
    workflow,
)
from scripts.ci.organization_commercial_readiness_loop import (
    ActionKind,
    GitHubError,
    PlanItem,
    SnapshotChanged,
    _open_private_output,
    main,
    run_once,
)


def test_run_dispatches_one_repair_and_one_independent_product() -> None:
    """Unchanged exact state authorizes one bounded action of each class."""
    review = snapshot("ContextualWisdomLab/review", pulls=(pull(1),))
    product = snapshot(
        "ContextualWisdomLab/product", workflows=(manual_workflow(workflow_id=17),)
    )
    client = FakeClient(
        [repository_payload("review"), repository_payload("product")],
        {review.full_name: [review, review], product.full_name: [product, product]},
    )
    report = run_once(client, organization="ContextualWisdomLab", rotation_seed=0)
    assert client.dispatched_repairs == [(review.full_name, "main")]
    assert client.dispatched_products == [(product.full_name, 17, "main")]
    assert [action.status for action in report.actions] == ["dispatched", "dispatched"]
    assert json.loads(report.to_json())["inspected_repositories"] == 2


def test_drift_new_lease_and_refetch_error_skip_only_the_target() -> None:
    """Pre-dispatch movement invalidates selection without reusing old evidence."""
    review = snapshot("ContextualWisdomLab/review", pulls=(pull(1),))
    moved = snapshot(
        review.full_name, default_sha="b" * 40, pulls=(pull(1, head_sha="c" * 40),)
    )
    product = snapshot("ContextualWisdomLab/product", workflows=(manual_workflow(),))
    newly_leased = snapshot(
        product.full_name,
        workflows=(
            manual_workflow(),
            workflow(
                workflow_id=8,
                content='on:\n  schedule:\n    - cron: "9 * * * *"\n',
            ),
        ),
    )
    broken = snapshot("ContextualWisdomLab/broken", pulls=(pull(2),))
    client = FakeClient(
        [
            repository_payload("review"),
            repository_payload("product"),
            repository_payload("broken"),
        ],
        {
            review.full_name: [review, moved],
            product.full_name: [product, newly_leased],
            broken.full_name: [broken, SnapshotChanged("moved")],
        },
    )
    report = run_once(
        client,
        organization="ContextualWisdomLab",
        rotation_seed=0,
        max_review_dispatches=2,
    )
    assert [item.status for item in report.actions] == [
        "skipped_refetch_error",
        "skipped_state_changed",
        "skipped_writer_lease",
    ]


def test_initial_errors_leases_and_dry_run_are_reported() -> None:
    """An inaccessible repo is contained; initial leases and dry-run stay explicit."""
    leased = snapshot(
        "ContextualWisdomLab/leased",
        workflows=(workflow(content='on:\n  schedule:\n    - cron: "7 * * * *"\n'),),
    )
    review = snapshot("ContextualWisdomLab/review", pulls=(pull(1),))
    client = FakeClient(
        [
            repository_payload("broken"),
            repository_payload("leased"),
            repository_payload("review"),
        ],
        {
            "ContextualWisdomLab/broken": [GitHubError("forbidden")],
            leased.full_name: [leased],
            review.full_name: [review, review],
        },
    )
    report = run_once(
        client,
        organization="ContextualWisdomLab",
        rotation_seed=0,
        dry_run=True,
    )
    assert report.inspection_errors == (
        ("ContextualWisdomLab/broken", "GitHubError: forbidden"),
    )
    assert report.leased_repositories == (leased.full_name,)
    assert report.actions[0].status == "dry_run"
    assert not client.dispatched_repairs


def test_dispatch_failures_and_invalid_internal_product_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API rejection and an impossible product plan both fail closed per action."""
    review = snapshot("ContextualWisdomLab/review", pulls=(pull(1),))
    failing = FailingDispatchClient(
        [repository_payload("review")], {review.full_name: [review, review]}
    )
    assert run_once(
        failing, organization="ContextualWisdomLab", rotation_seed=0
    ).actions[0].status == "dispatch_failed"

    product = snapshot("ContextualWisdomLab/product")
    invalid = PlanItem(
        ActionKind.PRODUCT_DEVELOPMENT,
        product.full_name,
        "main",
        product.fingerprint,
        None,
    )
    monkeypatch.setattr(
        "scripts.ci.organization_commercial_readiness_loop.build_plan",
        lambda *_args, **_kwargs: (invalid,),
    )
    client = FakeClient(
        [repository_payload("product")], {product.full_name: [product, product]}
    )
    assert run_once(
        client, organization="ContextualWisdomLab", rotation_seed=0
    ).actions[0].status == "dispatch_failed"


def test_main_writes_file_summary_stdout_and_failure_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI output and invalid configuration have deterministic exit behavior."""
    review = snapshot("ContextualWisdomLab/review", pulls=(pull(1),))
    client = FakeClient(
        [repository_payload("review")], {review.full_name: [review, review]}
    )
    output, summary = tmp_path / "report.json", tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert main(
        ["--rotation-seed", "2", "--json-output", str(output)],
        client_factory=lambda: client,
    ) == 0
    assert json.loads(output.read_text())["actions"][0]["status"] == "dispatched"
    assert "ContextualWisdomLab/review" in summary.read_text()

    empty = FakeClient([], {})
    monkeypatch.delenv("GITHUB_STEP_SUMMARY")
    assert main(
        ["--max-repositories", "0", "--max-review-dispatches", "0"],
        client_factory=lambda: empty,
    ) == 0
    assert '"inspected_repositories": 0' in capsys.readouterr().out

    assert main(
        ["--organization", "bad organization"], client_factory=lambda: empty
    ) == 2
    assert "invalid organization" in capsys.readouterr().err
    assert main(
        [], client_factory=lambda: (_ for _ in ()).throw(GitHubError("auth"))
    ) == 2
    assert "GitHubError: auth" in capsys.readouterr().err
    assert main(["--max-repositories", "-1"], client_factory=lambda: empty) == 2


def test_private_outputs_reject_symbolic_links(tmp_path: Path) -> None:
    """The coordinator cannot overwrite a report or summary symlink."""

    target = tmp_path / "target.txt"
    target.write_text("keep\n", encoding="utf-8")
    report = tmp_path / "report.json"
    report.symlink_to(target)

    with pytest.raises(ValueError, match="symbolic link"):
        _open_private_output(report, append=False)

    assert target.read_text(encoding="utf-8") == "keep\n"


def test_main_creates_missing_json_output_parent(tmp_path: Path) -> None:
    """A nested CLI report path preserves the established create-parent contract."""

    output = tmp_path / "nested" / "reports" / "report.json"
    empty = FakeClient([], {})

    assert not output.parent.exists()
    assert main(
        [
            "--max-repositories",
            "0",
            "--max-review-dispatches",
            "0",
            "--json-output",
            str(output),
        ],
        client_factory=lambda: empty,
    ) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["inspected_repositories"] == 0
