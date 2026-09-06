#!/usr/bin/env python3
"""Queue-health CLI with stable identity and audit-provenance guarantees.

The shared collector implementation lives in ``actions_queue_health_core.py``.
This entrypoint owns the consistency boundary that binds active-run evidence to
a stable pull-request view, carries stable workflow identity, and exports the
exact timestamp used for queue-age calculations.
"""

from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
from urllib.parse import quote

_CORE_MODULE_PATH = Path(__file__).with_name("actions_queue_health_core.py")
_CORE_MODULE_SPEC = importlib.util.spec_from_file_location(
    "actions_queue_health_core", _CORE_MODULE_PATH
)
if _CORE_MODULE_SPEC is None or _CORE_MODULE_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError("unable to load queue-health core module")
_core_module = importlib.util.module_from_spec(_CORE_MODULE_SPEC)
sys.modules.setdefault("actions_queue_health_core", _core_module)
_CORE_MODULE_SPEC.loader.exec_module(_core_module)

for core_symbol_name, core_symbol in vars(_core_module).items():
    if not core_symbol_name.startswith("__"):
        globals()[core_symbol_name] = core_symbol

_CORE_NORMALISE_RUN = _core_module._normalise_run
_CORE_BUILD_REPORT = _core_module.build_report
TERMINAL_DIAGNOSTIC_STATUSES = ("startup_failure", "cancelled")
TARGET_TERMINAL_DIAGNOSTIC_STATUSES = ("cancelled",)
TERMINAL_DIAGNOSTIC_MAX_API_PAGES = MAX_API_PAGES


def _normalise_run(
    repository_name: str,
    workflow_run: dict[str, Any],
    workflow_jobs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Normalize one run while preserving stable GitHub workflow identity."""
    if not isinstance(workflow_run, dict):
        raise QueueHealthError("workflow run must be an object")
    workflow_id = workflow_run.get("workflow_id")
    if workflow_id is not None and (
        isinstance(workflow_id, bool)
        or not isinstance(workflow_id, int)
        or workflow_id <= 0
    ):
        raise QueueHealthError("workflow id must be a positive integer")

    normalized_run = _CORE_NORMALISE_RUN(
        repository_name, workflow_run, workflow_jobs
    )
    workflow_name = normalized_run["workflow_name"]
    normalized_run["workflow_id"] = workflow_id
    normalized_run["workflow_identity"] = (
        f"workflow_id:{workflow_id}"
        if workflow_id is not None
        else f"workflow_name:{workflow_name}"
    )
    return normalized_run


_core_module._normalise_run = _normalise_run


def _read_pull_request_snapshot(
    pulls_endpoint: str, *, runner: Runner
) -> list[dict[str, Any]]:
    """Read and normalize one bounded open-pull-request identity snapshot."""
    pull_request_entries = _list_payload(
        github_json(pulls_endpoint, paginate=True, runner=runner),
        "pulls",
        max_items=MAX_API_PAGE_SIZE * MAX_API_PAGES,
    )
    return sorted(
        (_normalise_pull_request(pull_request) for pull_request in pull_request_entries),
        key=lambda pull_request: pull_request["number"],
    )


def _pull_request_identity_view(
    pull_requests: list[dict[str, Any]],
) -> dict[int, tuple[str, str]]:
    """Return the number/state/head view that must stay stable during collection."""
    return {
        pull_request["number"]: (
            str(pull_request.get("state") or ""),
            str(pull_request.get("head_sha") or ""),
        )
        for pull_request in pull_requests
    }


def collect_snapshot(
    repositories: Sequence[str],
    *,
    runner: Runner = subprocess.run,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Collect active and pre-job terminal evidence bound to stable PR identities."""
    validated_repositories = sorted(
        {_repository_name(repository_name) for repository_name in repositories}
    )
    if len(validated_repositories) != len(repositories):
        raise QueueHealthError("collection repository list contains duplicates")

    snapshot_timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    parse_timestamp(snapshot_timestamp)
    collected_repositories: list[dict[str, Any]] = []
    collection_errors: list[dict[str, str]] = []
    active_statuses = ("in_progress", "pending", "queued", "requested", "waiting")

    for repository_name in validated_repositories:
        try:
            repository_metadata = github_json(
                f"repos/{repository_name}", runner=runner
            )
            if not isinstance(repository_metadata, dict):
                raise QueueHealthError(
                    f"repository metadata for {repository_name} is not an object"
                )
            pulls_endpoint = (
                f"repos/{repository_name}/pulls?state=open&per_page={MAX_API_PAGE_SIZE}"
            )
            initial_pull_requests: list[dict[str, Any]] | None
            try:
                initial_pull_requests = _read_pull_request_snapshot(
                    pulls_endpoint, runner=runner
                )
            except IncompletePullRequestIdentity:
                initial_pull_requests = None
                time.sleep(PULL_REQUEST_RETRY_DELAY_SECONDS)
        except QueueHealthError as collection_error:
            collection_errors.append(
                {"repository": repository_name, "error": str(collection_error)}
            )
            continue

        try:
            active_snapshots: list[dict[int, dict[str, Any]]] = []
            for status_order in (active_statuses, tuple(reversed(active_statuses))):
                active_snapshot: dict[int, dict[str, Any]] = {}
                for workflow_status in status_order:
                    workflow_runs = _list_payload(
                        github_json(
                            f"repos/{repository_name}/actions/runs?status={workflow_status}"
                            f"&per_page={WORKFLOW_RUN_PAGE_SIZE}",
                            paginate=True,
                            max_pages=ACTIVE_RUN_MAX_API_PAGES,
                            runner=runner,
                        ),
                        "workflow_runs",
                        max_items=(
                            WORKFLOW_RUN_PAGE_SIZE * ACTIVE_RUN_MAX_API_PAGES
                        ),
                    )
                    for workflow_run in workflow_runs:
                        workflow_run_id = workflow_run.get("id")
                        if (
                            isinstance(workflow_run_id, bool)
                            or not isinstance(workflow_run_id, int)
                            or workflow_run_id <= 0
                        ):
                            raise QueueHealthError(
                                "workflow run id must be a positive integer"
                            )
                        active_snapshot[workflow_run_id] = workflow_run
                active_snapshots.append(active_snapshot)

            first_snapshot, second_snapshot = active_snapshots
            first_run_states = {
                workflow_run_id: str(workflow_run.get("status") or "").upper()
                for workflow_run_id, workflow_run in first_snapshot.items()
            }
            second_run_states = {
                workflow_run_id: str(workflow_run.get("status") or "").upper()
                for workflow_run_id, workflow_run in second_snapshot.items()
            }
            if first_run_states != second_run_states:
                raise QueueHealthError(
                    "active workflow run snapshot changed during collection"
                )

            try:
                final_pull_requests = _read_pull_request_snapshot(
                    pulls_endpoint, runner=runner
                )
            except IncompletePullRequestIdentity as identity_error:
                if initial_pull_requests is None:
                    raise QueueHealthError(
                        "pull-request identity validation failed: "
                        f"{identity_error}"
                    ) from identity_error
                time.sleep(PULL_REQUEST_RETRY_DELAY_SECONDS)
                try:
                    final_pull_requests = _read_pull_request_snapshot(
                        pulls_endpoint, runner=runner
                    )
                except QueueHealthError as retry_error:
                    raise QueueHealthError(
                        "pull-request identity validation failed: "
                        f"{retry_error}"
                    ) from retry_error

            if initial_pull_requests is not None and (
                _pull_request_identity_view(initial_pull_requests)
                != _pull_request_identity_view(final_pull_requests)
            ):
                raise QueueHealthError(
                    "pull-request identity snapshot changed during collection"
                )

            pull_requests_by_number = {
                pull_request["number"]: pull_request
                for pull_request in final_pull_requests
            }
            terminal_diagnostic_snapshot: dict[int, dict[str, Any]] = {}
            current_head_shas = sorted(
                {pull_request["head_sha"] for pull_request in final_pull_requests}
            )
            for current_head_sha in current_head_shas:
                encoded_head_sha = quote(current_head_sha, safe="")
                workflow_runs = _list_payload(
                    github_json(
                        f"repos/{repository_name}/actions/runs?status=completed"
                        f"&head_sha={encoded_head_sha}"
                        f"&per_page={WORKFLOW_RUN_PAGE_SIZE}",
                        paginate=True,
                        max_pages=TERMINAL_DIAGNOSTIC_MAX_API_PAGES,
                        runner=runner,
                    ),
                    "workflow_runs",
                    max_items=(
                        WORKFLOW_RUN_PAGE_SIZE * TERMINAL_DIAGNOSTIC_MAX_API_PAGES
                    ),
                )
                for workflow_run in workflow_runs:
                    if str(workflow_run.get("conclusion") or "").lower() not in (
                        TERMINAL_DIAGNOSTIC_STATUSES
                    ):
                        continue
                    workflow_run_id = workflow_run.get("id")
                    if (
                        isinstance(workflow_run_id, bool)
                        or not isinstance(workflow_run_id, int)
                        or workflow_run_id <= 0
                    ):
                        raise QueueHealthError(
                            "workflow run id must be a positive integer"
                        )
                    terminal_diagnostic_snapshot[workflow_run_id] = workflow_run

            for terminal_status in TARGET_TERMINAL_DIAGNOSTIC_STATUSES:
                target_workflow_runs = _list_payload(
                    github_json(
                        f"repos/{repository_name}/actions/runs?status={terminal_status}"
                        "&event=pull_request_target"
                        f"&per_page={WORKFLOW_RUN_PAGE_SIZE}",
                        paginate=True,
                        max_pages=TERMINAL_DIAGNOSTIC_MAX_API_PAGES,
                        runner=runner,
                    ),
                    "workflow_runs",
                    max_items=(
                        WORKFLOW_RUN_PAGE_SIZE * TERMINAL_DIAGNOSTIC_MAX_API_PAGES
                    ),
                )
                for workflow_run in target_workflow_runs:
                    normalized_candidate = _normalise_run(
                        repository_name, workflow_run, []
                    )
                    identity_state, _ = _run_identity(
                        normalized_candidate, pull_requests_by_number
                    )
                    if identity_state != "current_head":
                        continue
                    terminal_diagnostic_snapshot[normalized_candidate["id"]] = (
                        workflow_run
                    )

            observed_snapshot = dict(second_snapshot)
            observed_snapshot.update(terminal_diagnostic_snapshot)
            runs_by_id: dict[int, dict[str, Any]] = {}
            for workflow_run_id, workflow_run in observed_snapshot.items():
                normalized_run = _normalise_run(
                    repository_name, workflow_run, []
                )
                identity_state, _ = _run_identity(
                    normalized_run, pull_requests_by_number
                )
                needs_job_evidence = (
                    identity_state == "current_head"
                    and (
                        normalized_run["status"] in {"IN_PROGRESS", "WAITING"}
                        or normalized_run["conclusion"]
                        in {status.upper() for status in TERMINAL_DIAGNOSTIC_STATUSES}
                    )
                )
                if not needs_job_evidence:
                    runs_by_id[workflow_run_id] = normalized_run
                    continue

                jobs_payload = github_json(
                    f"repos/{repository_name}/actions/runs/{workflow_run_id}/jobs"
                    f"?per_page={MAX_API_PAGE_SIZE}",
                    paginate=True,
                    runner=runner,
                )
                workflow_jobs = _list_payload(
                    jobs_payload,
                    "jobs",
                    max_items=MAX_API_PAGE_SIZE * MAX_API_PAGES,
                )
                runs_by_id[workflow_run_id] = _normalise_run(
                    repository_name, workflow_run, workflow_jobs
                )

            try:
                post_evidence_pull_requests = _read_pull_request_snapshot(
                    pulls_endpoint, runner=runner
                )
            except IncompletePullRequestIdentity:
                time.sleep(PULL_REQUEST_RETRY_DELAY_SECONDS)
                try:
                    post_evidence_pull_requests = _read_pull_request_snapshot(
                        pulls_endpoint, runner=runner
                    )
                except QueueHealthError as retry_error:
                    raise QueueHealthError(
                        "pull-request identity validation failed: "
                        f"{retry_error}"
                    ) from retry_error
            if (
                _pull_request_identity_view(final_pull_requests)
                != _pull_request_identity_view(post_evidence_pull_requests)
            ):
                raise QueueHealthError(
                    "pull-request identity snapshot changed during evidence collection"
                )
        except QueueHealthError as collection_error:
            collection_errors.append(
                {"repository": repository_name, "error": str(collection_error)}
            )
            continue

        collected_repositories.append(
            {
                "full_name": repository_name,
                "default_branch": str(
                    repository_metadata.get("default_branch") or ""
                ),
                "pull_requests": final_pull_requests,
                "runs": sorted(
                    runs_by_id.values(), key=lambda workflow_run: workflow_run["id"]
                ),
            }
        )

    return {
        "generated_at": snapshot_timestamp,
        "repositories": collected_repositories,
        "collection_errors": collection_errors,
    }


def _normalized_snapshot_runs(
    snapshot: dict[str, Any],
) -> dict[tuple[str, int], dict[str, Any]]:
    """Index normalized run metadata for additive report provenance fields."""
    normalized_runs: dict[tuple[str, int], dict[str, Any]] = {}
    snapshot_repositories = snapshot.get("repositories")
    if not isinstance(snapshot_repositories, list):
        return normalized_runs
    for repository_entry in snapshot_repositories:
        if not isinstance(repository_entry, dict):
            continue
        repository_name = repository_entry.get("full_name")
        workflow_runs = repository_entry.get("runs") or []
        if not isinstance(repository_name, str) or not isinstance(workflow_runs, list):
            continue
        for workflow_run in workflow_runs:
            if not isinstance(workflow_run, dict):
                continue
            workflow_jobs = workflow_run.get("jobs") or []
            if not isinstance(workflow_jobs, list):
                workflow_jobs = []
            normalized_run = _normalise_run(
                repository_name, workflow_run, workflow_jobs
            )
            normalized_runs[(repository_name, normalized_run["id"])] = normalized_run
    return normalized_runs


def build_report(
    snapshot: dict[str, Any],
    *,
    now: datetime | None = None,
    queue_age_slo_seconds: int = DEFAULT_QUEUE_AGE_SLO_SECONDS,
) -> dict[str, Any]:
    """Build the v1 report with stable workflow identity and age provenance."""
    normalized_runs = _normalized_snapshot_runs(snapshot)
    report = _CORE_BUILD_REPORT(
        snapshot,
        now=now,
        queue_age_slo_seconds=queue_age_slo_seconds,
    )

    for report_row in report["runs"]:
        run_metadata = normalized_runs.get(
            (report_row["repository"], report_row["run_id"])
        )
        if run_metadata is None:  # pragma: no cover - core report guarantees the row.
            continue
        report_row["workflow_id"] = run_metadata["workflow_id"]
        report_row["workflow_identity"] = run_metadata["workflow_identity"]
        report_row["run_conclusion"] = run_metadata.get("conclusion", "")
        report_row["jobs_materialized"] = bool(run_metadata["jobs"])
        matching_job = next(
            (
                workflow_job
                for workflow_job in run_metadata["jobs"]
                if workflow_job["id"] == report_row["job_id"]
            ),
            None,
        )
        report_row["admission_state"] = (
            "runner_assigned" if report_row["runner_assigned"] else "runner_not_assigned"
        )
        if matching_job and matching_job.get("created_at"):
            report_row["queue_age_started_at"] = matching_job["created_at"]
            report_row["queue_age_source"] = "job_created_at"
        else:
            report_row["queue_age_started_at"] = run_metadata.get("created_at", "")
            report_row["queue_age_source"] = "run_created_at"
        if (
            report_row["identity_state"] == "current_head"
            and report_row["run_conclusion"] == "STARTUP_FAILURE"
            and not report_row["jobs_materialized"]
        ):
            report_row["admission_state"] = "startup_failure_before_job_materialization"
            report_row["blocker"] = "startup_failure_before_job_materialization"
            report_row["recommended_action"] = (
                "inspect_actions_control_plane_without_leaf_bypass"
            )
        elif (
            report_row["identity_state"] == "current_head"
            and report_row["run_conclusion"] == "CANCELLED"
            and matching_job is not None
            and matching_job.get("conclusion") == "CANCELLED"
            and not report_row["runner_assigned"]
            and matching_job.get("steps_count") == 0
        ):
            report_row["admission_state"] = "cancelled_before_runner_assignment"
            report_row["blocker"] = "cancelled_before_runner_assignment"
            report_row["recommended_action"] = (
                "inspect_actions_control_plane_without_leaf_bypass"
            )

    current_pending_rows = [
        report_row
        for report_row in report["runs"]
        if report_row["is_pending"]
        and report_row["identity_state"] == "current_head"
    ]
    lane_run_ids: dict[tuple[str, int, str], set[int]] = {}
    lane_workflow_names: dict[tuple[str, int, str], str] = {}
    for report_row in current_pending_rows:
        lane_identity = (
            report_row["repository"],
            report_row["pull_request_number"],
            report_row["workflow_identity"],
        )
        lane_run_ids.setdefault(lane_identity, set()).add(report_row["run_id"])
        lane_workflow_names.setdefault(
            lane_identity, report_row["workflow_name"]
        )

    duplicate_pending_lanes = [
        {
            "repository": lane_identity[0],
            "pull_request_number": lane_identity[1],
            "workflow_identity": lane_identity[2],
            "workflow_name": lane_workflow_names[lane_identity],
            "count": len(workflow_run_ids),
        }
        for lane_identity, workflow_run_ids in sorted(lane_run_ids.items())
        if len(workflow_run_ids) > 1
    ]
    report["duplicate_pending_lanes"] = duplicate_pending_lanes
    report["summary"]["duplicate_pending_lane_count"] = len(
        duplicate_pending_lanes
    )
    cancelled_before_runner_assignment_count = sum(
        report_row.get("admission_state") == "cancelled_before_runner_assignment"
        for report_row in report["runs"]
    )
    report["summary"]["cancelled_before_runner_assignment_count"] = (
        cancelled_before_runner_assignment_count
    )
    if cancelled_before_runner_assignment_count:
        external_action = (
            "Inspect Actions runner admission, billing/usage, runner-group policy, "
            "scheduler capacity, and cancellation provenance; cancelled pre-runner "
            "evidence remains incomplete."
        )
        if external_action not in report["summary"]["external_actions"]:
            report["summary"]["external_actions"].append(external_action)
            report["summary"]["external_actions"].sort()
    return report


def main(
    argv: Sequence[str] | None = None, *, stderr: TextIO = sys.stderr
) -> int:
    """Collect or load a snapshot, write reports, and return a stable CLI status."""
    cli_arguments = parse_args(argv)
    try:
        queue_snapshot = (
            load_snapshot(cli_arguments.snapshot)
            if cli_arguments.snapshot
            else collect_snapshot(load_allowlist(cli_arguments.allowlist))
        )
        evaluation_time = (
            parse_timestamp(cli_arguments.now)
            if cli_arguments.now
            else datetime.now(timezone.utc)
        )
        queue_report = build_report(
            queue_snapshot,
            now=evaluation_time,
            queue_age_slo_seconds=cli_arguments.queue_age_slo_seconds,
        )
        write_reports(
            queue_report, cli_arguments.output_json, cli_arguments.output_html
        )
    except (OSError, QueueHealthError, ValueError) as report_error:
        print(f"ERROR: queue-health report failed: {report_error}", file=stderr)
        return 2

    breach_count = queue_report["summary"]["unassigned_slo_breached_count"]
    if breach_count:
        print(
            "::warning::Actions queue-health found "
            f"{breach_count} unassigned current-head SLO breach(es)."
        )
    print(
        "QUEUE_HEALTH_RESULT="
        f"observed={queue_report['summary']['observed_job_count']} "
        f"pending={queue_report['summary']['pending_job_count']} "
        f"slo_breaches={breach_count}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through CLI tests.
    raise SystemExit(main())
