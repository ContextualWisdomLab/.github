#!/usr/bin/env python3
"""Produce a read-only, exact-head GitHub Actions queue-health report.

The collector intentionally treats queued, cancelled, skipped, missing, and
unlinked evidence as incomplete.  It never cancels runs, changes branches, or
turns an unavailable runner into a successful check.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable, Sequence, TextIO


REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
QUEUE_STATES = {"QUEUED", "IN_PROGRESS"}
TERMINAL_STATES = {"COMPLETED"}
DEFAULT_QUEUE_AGE_SLO_SECONDS = 900
SCHEMA_VERSION = "actions.queue_health.v1"
MAX_API_PAGE_SIZE = 100
MAX_API_PAGES = 20
PAGINATED_PAGES_KEY = "_queue_health_pages"
Runner = Callable[..., subprocess.CompletedProcess[str]]


class QueueHealthError(ValueError):
    """Raised when a queue-health input or trusted read is invalid."""


def parse_timestamp(value: str) -> datetime:
    """Parse an explicit UTC timestamp and reject ambiguous local time."""
    if not isinstance(value, str) or not value.strip():
        raise QueueHealthError("timestamp must be a non-empty string")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise QueueHealthError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise QueueHealthError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _repository_name(value: Any) -> str:
    """Validate and return one owner/repository identifier."""
    if not isinstance(value, str) or not REPOSITORY_PATTERN.fullmatch(value):
        raise QueueHealthError(f"invalid repository identifier: {value!r}")
    return value


def load_allowlist(path: Path) -> list[str]:
    """Load a unique, sorted repository allowlist from a JSON array/object."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QueueHealthError(f"unable to load repository allowlist: {exc}") from exc
    values = payload.get("repositories") if isinstance(payload, dict) else payload
    if not isinstance(values, list) or not values:
        raise QueueHealthError("repository allowlist must be a non-empty JSON array")
    repositories = sorted({_repository_name(value) for value in values})
    if len(repositories) != len(values):
        raise QueueHealthError("repository allowlist contains duplicates")
    return repositories


def _list_payload(payload: Any, key: str) -> list[dict[str, Any]]:
    """Extract a bounded GitHub list response without guessing its shape."""
    declared_total_counts: list[Any] = []
    if isinstance(payload, dict) and PAGINATED_PAGES_KEY in payload:
        pages = payload[PAGINATED_PAGES_KEY]
        if not isinstance(pages, list) or not pages or len(pages) > MAX_API_PAGES:
            raise QueueHealthError(f"GitHub response field {key!r} exceeds the bounded page count")
        page_values = []
        for page in pages:
            if isinstance(page, list):
                page_values.extend(page)
            elif isinstance(page, dict):
                page_items = page.get(key)
                if not isinstance(page_items, list):
                    raise QueueHealthError(f"GitHub response field {key!r} page must contain an array")
                page_values.extend(page_items)
                if "total_count" in page:
                    declared_total_counts.append(page["total_count"])
            else:
                raise QueueHealthError(f"GitHub response field {key!r} page must be an array or object")
        values = page_values
    else:
        values = payload if isinstance(payload, list) else payload.get(key) if isinstance(payload, dict) else None
        if isinstance(payload, dict) and "total_count" in payload:
            declared_total_counts.append(payload["total_count"])
    if not isinstance(values, list) or not all(isinstance(value, dict) for value in values):
        raise QueueHealthError(f"GitHub response field {key!r} must be an array of objects")
    if declared_total_counts:
        if any(isinstance(total_count, bool) or not isinstance(total_count, int) for total_count in declared_total_counts):
            raise QueueHealthError(f"GitHub response field {key!r} has invalid total counts")
        total_count = max(declared_total_counts)
        if total_count < len(values) or total_count > MAX_API_PAGE_SIZE * MAX_API_PAGES:
            raise QueueHealthError(f"GitHub response field {key!r} exceeds the bounded page size")
    return values


def github_json(path: str, *, paginate: bool = False, runner: Runner = subprocess.run) -> Any:
    """Read one GitHub REST endpoint through ``gh`` without shell evaluation."""
    if not path.startswith("repos/"):
        raise QueueHealthError(f"GitHub endpoint is outside repository scope: {path}")
    command = ["gh", "api"]
    if paginate:
        command.extend(("--paginate", "--slurp"))
    command.append(path)
    result = runner(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "GitHub API read failed").strip()
        raise QueueHealthError(f"GitHub API read failed for {path}: {detail[:400]}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise QueueHealthError(f"GitHub API returned invalid JSON for {path}") from exc
    if paginate:
        if not isinstance(payload, list) or not payload or len(payload) > MAX_API_PAGES:
            raise QueueHealthError(f"GitHub API returned an unbounded page set for {path}")
        return {PAGINATED_PAGES_KEY: payload}
    return payload


def _normalise_pull_request(pull_request: dict[str, Any]) -> dict[str, Any]:
    """Keep only exact-head identity fields needed for queue classification."""
    if not isinstance(pull_request, dict):
        raise QueueHealthError("pull request entry must be an object")
    number = pull_request.get("number")
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        raise QueueHealthError("pull request number must be a positive integer")
    if "head_sha" in pull_request or "base_ref" in pull_request:
        canonical = {
            "base_ref": pull_request.get("base_ref", ""),
            "base_repository": pull_request.get("base_repository", ""),
            "head_sha": pull_request.get("head_sha", ""),
            "updated_at": pull_request.get("updated_at", ""),
        }
        if not all(isinstance(value, str) for value in canonical.values()):
            raise QueueHealthError("normalized pull request identity fields must be strings")
        return {
            "number": number,
            "state": pull_request.get("state", "open"),
            **canonical,
        }
    head = pull_request.get("head")
    base = pull_request.get("base")
    if not isinstance(head, dict) or not isinstance(base, dict):
        raise QueueHealthError("pull request head and base must be objects")
    return {
        "number": number,
        "state": pull_request.get("state", "open"),
        "base_ref": base.get("ref", ""),
        "base_repository": (base.get("repo") or {}).get("full_name", "")
        if isinstance(base.get("repo"), dict)
        else "",
        "head_sha": head.get("sha", ""),
        "updated_at": pull_request.get("updated_at", ""),
    }


def _normalise_job(job: dict[str, Any]) -> dict[str, Any]:
    """Keep job state and runner assignment evidence without log contents."""
    if not isinstance(job, dict):
        raise QueueHealthError("workflow job entry must be an object")
    job_id = job.get("id")
    if isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0:
        raise QueueHealthError("job id must be a positive integer")
    runner_id = job.get("runner_id")
    if isinstance(runner_id, bool) or not isinstance(runner_id, int):
        runner_id = 0
    return {
        "id": job_id,
        "name": str(job.get("name") or "unnamed job"),
        "status": str(job.get("status") or "").upper(),
        "conclusion": str(job.get("conclusion") or "").upper(),
        "runner_id": runner_id,
        "runner_name": str(job.get("runner_name") or ""),
        "steps_count": len(job.get("steps") or []) if isinstance(job.get("steps"), list) else 0,
    }


def _normalise_run(repository: str, run: dict[str, Any], jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Keep run identity and job state required for deterministic reporting."""
    if not isinstance(run, dict):
        raise QueueHealthError("workflow run entry must be an object")
    if not isinstance(jobs, list) or not all(isinstance(job, dict) for job in jobs):
        raise QueueHealthError("workflow run jobs must be an array of objects")
    run_id = run.get("id")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        raise QueueHealthError("workflow run id must be a positive integer")
    pull_requests = run.get("pull_requests", [])
    if pull_requests is None:
        pull_requests = []
    if not isinstance(pull_requests, list) or not all(isinstance(item, dict) for item in pull_requests):
        raise QueueHealthError("workflow run pull_requests must be an array of objects")
    links = []
    for item in pull_requests:
        number = item.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise QueueHealthError("workflow run pull request number must be positive")
        head = item.get("head", {})
        if head is None:
            head = {}
        if not isinstance(head, dict):
            raise QueueHealthError("workflow run pull request head must be an object")
        links.append({"number": number, "head_sha": str(head.get("sha") or "")})
    return {
        "repository": repository,
        "id": run_id,
        "workflow_name": str(run.get("name") or run.get("workflow_name") or "unnamed workflow"),
        "event": str(run.get("event") or "unknown"),
        "status": str(run.get("status") or "").upper(),
        "conclusion": str(run.get("conclusion") or "").upper(),
        "head_sha": str(run.get("head_sha") or ""),
        "created_at": str(run.get("created_at") or ""),
        "updated_at": str(run.get("updated_at") or ""),
        "run_attempt": run.get("run_attempt", 1),
        "concurrency_group": str(run.get("concurrency_group") or "unavailable_from_actions_api"),
        "pull_requests": sorted(links, key=lambda item: item["number"]),
        "jobs": sorted((_normalise_job(job) for job in jobs), key=lambda item: item["id"]),
    }


def collect_snapshot(
    repositories: Sequence[str],
    *,
    runner: Runner = subprocess.run,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Collect bounded queued/in-progress run and job data using read-only API calls."""
    validated = sorted({_repository_name(repository) for repository in repositories})
    if len(validated) != len(repositories):
        raise QueueHealthError("collection repository list contains duplicates")
    collected_repositories: list[dict[str, Any]] = []
    for repository in validated:
        metadata = github_json(f"repos/{repository}", runner=runner)
        if not isinstance(metadata, dict):
            raise QueueHealthError(f"repository metadata for {repository} is not an object")
        pulls_endpoint = f"repos/{repository}/pulls?state=open&per_page={MAX_API_PAGE_SIZE}"
        pull_requests = _list_payload(
            github_json(pulls_endpoint, paginate=True, runner=runner),
            "pulls",
        )
        try:
            normalized_pull_requests = sorted(
                (_normalise_pull_request(item) for item in pull_requests),
                key=lambda item: item["number"],
            )
        except QueueHealthError as exc:
            if str(exc) != "pull request head and base must be objects":
                raise QueueHealthError(
                    f"pull-request identity validation failed for {repository}: {exc}"
                ) from exc
            retry_pull_requests = _list_payload(
                github_json(pulls_endpoint, paginate=True, runner=runner),
                "pulls",
            )
            try:
                normalized_pull_requests = sorted(
                    (_normalise_pull_request(item) for item in retry_pull_requests),
                    key=lambda item: item["number"],
                )
            except QueueHealthError as retry_exc:
                raise QueueHealthError(
                    f"pull-request identity validation failed for {repository}: {retry_exc}"
                ) from retry_exc
        pull_requests_by_number = {item["number"]: item for item in normalized_pull_requests}
        runs_by_id: dict[int, dict[str, Any]] = {}
        for status in ("in_progress", "queued"):
            runs = _list_payload(
                github_json(
                    f"repos/{repository}/actions/runs?status={status}&per_page={MAX_API_PAGE_SIZE}",
                    paginate=True,
                    runner=runner,
                ),
                "workflow_runs",
            )
            for run in runs:
                run_id = run.get("id")
                if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
                    raise QueueHealthError("workflow run id must be a positive integer")
                if run_id in runs_by_id:
                    continue
                candidate = _normalise_run(repository, run, [])
                identity, _ = _run_identity(candidate, pull_requests_by_number)
                if identity != "current_head" or candidate["status"] == "QUEUED":
                    runs_by_id[run_id] = candidate
                    continue
                jobs_payload = github_json(
                    f"repos/{repository}/actions/runs/{run_id}/jobs?per_page={MAX_API_PAGE_SIZE}",
                    paginate=True,
                    runner=runner,
                )
                jobs = _list_payload(jobs_payload, "jobs")
                runs_by_id[run_id] = _normalise_run(repository, run, jobs)
        collected_repositories.append(
            {
                "full_name": repository,
                "default_branch": str(metadata.get("default_branch") or ""),
                "pull_requests": normalized_pull_requests,
                "runs": sorted(runs_by_id.values(), key=lambda item: item["id"]),
            }
        )
    timestamp = generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    parse_timestamp(timestamp)
    return {"generated_at": timestamp, "repositories": collected_repositories}


def load_snapshot(path: Path) -> dict[str, Any]:
    """Load a JSON snapshot for offline, deterministic report generation."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QueueHealthError(f"unable to load queue-health snapshot: {exc}") from exc
    if not isinstance(payload, dict):
        raise QueueHealthError("queue-health snapshot root must be an object")
    return payload


def _run_identity(run: dict[str, Any], pull_requests: dict[int, dict[str, Any]]) -> tuple[str, int | None]:
    """Resolve one run to current-head, obsolete, or unlinked identity."""
    links = run.get("pull_requests") or []
    for link in links:
        number = link.get("number")
        pull_request = pull_requests.get(number)
        if pull_request and pull_request.get("head_sha") == run.get("head_sha"):
            return "current_head", number
    if links:
        return "obsolete", links[0].get("number")
    return "unlinked", None


def _job_state(job: dict[str, Any]) -> tuple[str, bool, bool]:
    """Return normalized execution state, pending flag, and runner assignment."""
    status = str(job.get("status") or "").upper()
    conclusion = str(job.get("conclusion") or "").upper()
    assigned = bool(job.get("runner_name")) or (isinstance(job.get("runner_id"), int) and job.get("runner_id", 0) > 0)
    if status in QUEUE_STATES:
        return ("queued_assigned" if assigned else "queued_unassigned"), True, assigned
    if status in TERMINAL_STATES or conclusion:
        return "terminal", False, assigned
    return "unknown", False, assigned


def _format_age(created_at: str, now: datetime) -> int:
    """Return non-negative queue age seconds from an explicit timestamp."""
    created = parse_timestamp(created_at)
    return max(0, int((now - created).total_seconds()))


def build_report(
    snapshot: dict[str, Any],
    *,
    now: datetime | None = None,
    queue_age_slo_seconds: int = DEFAULT_QUEUE_AGE_SLO_SECONDS,
) -> dict[str, Any]:
    """Classify every observed job without treating incomplete evidence as success."""
    if queue_age_slo_seconds < 0:
        raise QueueHealthError("queue age SLO must not be negative")
    generated_at = parse_timestamp(snapshot.get("generated_at"))
    if now is not None and (not isinstance(now, datetime) or now.tzinfo is None):
        raise QueueHealthError("evaluation time must include a timezone")
    report_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    repositories = snapshot.get("repositories")
    if not isinstance(repositories, list):
        raise QueueHealthError("queue-health snapshot repositories must be an array")

    rows: list[dict[str, Any]] = []
    for repository in repositories:
        if not isinstance(repository, dict):
            raise QueueHealthError("queue-health repository entry must be an object")
        full_name = _repository_name(repository.get("full_name"))
        pull_request_entries = repository.get("pull_requests", [])
        if pull_request_entries is None:
            pull_request_entries = []
        if not isinstance(pull_request_entries, list):
            raise QueueHealthError(f"pull requests for {full_name} must be an array")
        pull_requests: dict[int, dict[str, Any]] = {}
        for pull_request in pull_request_entries:
            normalized = _normalise_pull_request(pull_request)
            if normalized["number"] in pull_requests:
                raise QueueHealthError(f"duplicate pull request {normalized['number']} for {full_name}")
            pull_requests[normalized["number"]] = normalized
        runs = repository.get("runs", [])
        if runs is None:
            runs = []
        if not isinstance(runs, list):
            raise QueueHealthError(f"runs for {full_name} must be an array")
        run_ids: set[int] = set()
        for raw_run in runs:
            if not isinstance(raw_run, dict):
                raise QueueHealthError("workflow run entry must be an object")
            raw_jobs = raw_run.get("jobs", [])
            if raw_jobs is None:
                raw_jobs = []
            if not isinstance(raw_jobs, list):
                raise QueueHealthError("workflow run jobs must be an array")
            run = _normalise_run(full_name, raw_run, raw_jobs)
            if run["id"] in run_ids:
                raise QueueHealthError(f"duplicate workflow run {run['id']} for {full_name}")
            run_ids.add(run["id"])
            identity, pull_request_number = _run_identity(run, pull_requests)
            jobs = run["jobs"]
            for job in jobs or [{"id": run["id"], "name": "run", "status": run.get("status")}]:
                state, pending, assigned = _job_state(job)
                age_seconds = _format_age(run.get("created_at"), report_now)
                slo_breached = pending and age_seconds > queue_age_slo_seconds
                if identity == "obsolete":
                    blocker = "obsolete_run_requires_identity_confirmed_cleanup"
                    action = "owner_cleanup_after_exact_identity_confirmation"
                elif identity == "unlinked":
                    blocker = "run_not_linked_to_pull_request"
                    action = "reconcile_run_identity_before_cleanup"
                elif pending and not assigned and slo_breached:
                    blocker = "external_runner_assignment_or_capacity"
                    action = "owner_check_runner_billing_policy_and_concurrency"
                elif pending:
                    blocker = "current_head_required_evidence_incomplete"
                    action = "wait_for_runner_or_escalate_after_slo"
                else:
                    blocker = None
                    action = "none"
                rows.append(
                    {
                        "repository": full_name,
                        "workflow_name": run.get("workflow_name", "unnamed workflow"),
                        "run_id": run.get("id"),
                        "run_attempt": run.get("run_attempt", 1),
                        "job_id": job.get("id"),
                        "job_name": job.get("name", "unnamed job"),
                        "event": run.get("event", "unknown"),
                        "head_sha": run.get("head_sha", ""),
                        "pull_request_number": pull_request_number,
                        "identity_state": identity,
                        "status": job.get("status", ""),
                        "conclusion": job.get("conclusion", ""),
                        "execution_state": state,
                        "runner_assigned": assigned,
                        "created_at": run.get("created_at", ""),
                        "updated_at": run.get("updated_at", ""),
                        "queue_age_seconds": age_seconds,
                        "slo_breached": slo_breached,
                        "concurrency_group": run.get("concurrency_group", "unavailable_from_actions_api"),
                        "obsolete": identity == "obsolete",
                        "blocker": blocker,
                        "recommended_action": action,
                    }
                )

    rows.sort(key=lambda row: (row["repository"], row["run_id"], row["job_id"]))
    pending = [row for row in rows if row["execution_state"].startswith("queued_")]
    current_pending = [row for row in pending if row["identity_state"] == "current_head"]
    lane_counts = Counter(
        (row["repository"], row["pull_request_number"], row["workflow_name"])
        for row in current_pending
        if row["pull_request_number"] is not None
    )
    duplicate_lanes = [
        {"repository": key[0], "pull_request_number": key[1], "workflow_name": key[2], "count": count}
        for key, count in sorted(lane_counts.items())
        if count > 1
    ]
    external_actions = sorted(
        {
            "Inspect GitHub-hosted runner assignment, Actions billing/usage, runner-group policy, environment approval, and concurrency saturation; queued evidence remains incomplete."
            for row in rows
            if row["blocker"] == "external_runner_assignment_or_capacity"
        }
    )
    summary = {
        "observed_job_count": len(rows),
        "pending_job_count": len(pending),
        "current_head_pending_count": len(current_pending),
        "unassigned_slo_breached_count": sum(
            row["identity_state"] == "current_head"
            and row["execution_state"] == "queued_unassigned"
            and row["slo_breached"]
            for row in rows
        ),
        "obsolete_job_count": sum(row["obsolete"] for row in rows),
        "unlinked_job_count": sum(row["identity_state"] == "unlinked" for row in rows),
        "duplicate_pending_lane_count": len(duplicate_lanes),
        "terminal_job_count": sum(row["execution_state"] == "terminal" for row in rows),
        "external_actions": external_actions,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "evaluated_at": report_now.isoformat().replace("+00:00", "Z"),
        "queue_age_slo_seconds": queue_age_slo_seconds,
        "repositories": sorted(_repository_name(repository["full_name"]) for repository in repositories),
        "summary": summary,
        "duplicate_pending_lanes": duplicate_lanes,
        "runs": rows,
        "limitations": [
            "The Actions REST API does not expose the evaluated concurrency group for every run; unavailable values are reported explicitly.",
            "This read-only slice never cancels runs or changes branch/check state.",
        ],
    }


def render_html(report: dict[str, Any]) -> str:
    """Render a keyboard-readable HTML report with escaped untrusted fields."""
    summary = report["summary"]
    rows = report["runs"]
    table_rows = []
    for row in rows:
        table_rows.append(
            "<tr>"
            + f'<th scope="row">{html.escape(str(row["repository"]))}</th>'
            + "".join(
                f"<td>{html.escape(str(row[field]))}</td>"
                for field in (
                    "workflow_name",
                    "run_id",
                    "job_name",
                    "identity_state",
                    "execution_state",
                    "head_sha",
                    "queue_age_seconds",
                    "blocker",
                )
            )
            + "</tr>"
        )
    body = "".join(table_rows) or '<tr><th scope="row" colspan="9">No queued or in-progress jobs observed.</th></tr>'
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">'
        "<title>GitHub Actions queue health</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:2rem}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #bbb;padding:.4rem;text-align:left}"
        "th{background:#eee}</style></head><body>"
        '<main aria-live="polite">'
        "<h1>GitHub Actions queue health</h1>"
        f"<p>Evaluated at <time>{html.escape(report['evaluated_at'])}</time>; queue-age SLO: {report['queue_age_slo_seconds']} seconds.</p>"
        f"<p>Observed jobs: {summary['observed_job_count']}; current-head pending: {summary['current_head_pending_count']}; SLO breaches: {summary['unassigned_slo_breached_count']}.</p>"
        '<table><caption>Run and job evidence; queued evidence is not a passing check.</caption>'
        "<thead><tr>"
        + "".join(f"<th scope=\"col\">{field.replace('_', ' ').title()}</th>" for field in (
            "repository", "workflow_name", "run_id", "job_name", "identity_state", "execution_state", "head_sha", "queue_age_seconds", "blocker"
        ))
        + f"</tr></thead><tbody>{body}</tbody></table></main></body></html>\n"
    )


def write_reports(report: dict[str, Any], json_path: Path, html_path: Path) -> None:
    """Write deterministic JSON and accessible HTML reports."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    html_path.write_text(render_html(report), encoding="utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse live-collection or offline-report CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path)
    source.add_argument("--allowlist", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-html", type=Path, required=True)
    parser.add_argument("--queue-age-slo-seconds", type=int, default=DEFAULT_QUEUE_AGE_SLO_SECONDS)
    parser.add_argument("--now", help="Explicit timezone-aware evaluation time for deterministic reports")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None, *, stderr: TextIO = sys.stderr) -> int:
    """Collect or load a snapshot, write reports, and return a stable CLI status."""
    args = parse_args(argv)
    try:
        snapshot = load_snapshot(args.snapshot) if args.snapshot else collect_snapshot(load_allowlist(args.allowlist))
        now = parse_timestamp(args.now) if args.now else datetime.now(timezone.utc)
        report = build_report(
            snapshot,
            now=now,
            queue_age_slo_seconds=args.queue_age_slo_seconds,
        )
        write_reports(report, args.output_json, args.output_html)
    except (OSError, QueueHealthError, ValueError) as exc:
        print(f"ERROR: queue-health report failed: {exc}", file=stderr)
        return 2
    breaches = report["summary"]["unassigned_slo_breached_count"]
    if breaches:
        print(f"::warning::Actions queue-health found {breaches} unassigned current-head SLO breach(es).")
    print(
        "QUEUE_HEALTH_RESULT="
        f"observed={report['summary']['observed_job_count']} "
        f"pending={report['summary']['pending_job_count']} "
        f"slo_breaches={breaches}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI tests.
    raise SystemExit(main())
