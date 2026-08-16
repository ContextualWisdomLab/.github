#!/usr/bin/env python3
"""Coordinate bounded commercial-readiness work across an organization.

The coordinator deliberately does not implement code review, branch repair, or
product development itself. It discovers repositories that do not already have
an active writer, revalidates their exact live state immediately before a
mutation, and dispatches at most one central review-repair run and one
repository-local product-development run per invocation.
"""

from __future__ import annotations

import argparse
import base64
import dataclasses
import enum
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import quote


DEFAULT_ORGANIZATION = "ContextualWisdomLab"
ORGANIZATION_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
ENTRYPOINT_MARKER = "# cwl-org-commercial-entrypoint: v1"
CENTRAL_REPOSITORY = f"{DEFAULT_ORGANIZATION}/.github"
CENTRAL_REPAIR_EVENT = "pr-review-fix-scheduler"
ACTIVE_RUN_STATES = frozenset({"queued", "in_progress", "waiting", "pending", "requested"})
WRITER_SIGNAL_RE = re.compile(
    r"(?:hourly|commercial|product[ _-]*development|autonomous|readiness|"
    r"maintenance|review[ _-]*repair|review[ _-]*fix|maintainer|pr[ _-]*disposition)",
    re.IGNORECASE,
)
MERGE_SCHEDULER_RE = re.compile(
    r"(?:required[ _-]*pr[ _-]*review[ _-]*merge[ _-]*scheduler|"
    r"pr-review-merge-scheduler)",
    re.IGNORECASE,
)
SCHEDULE_RE = re.compile(r"(?m)^\s*schedule\s*:")
WORKFLOW_DISPATCH_RE = re.compile(r"(?m)^\s*workflow_dispatch\s*:")


class GitHubError(RuntimeError):
    """Represent a bounded GitHub API or authentication failure."""


class SnapshotChanged(RuntimeError):
    """Signal that a repository moved while one snapshot was materialized."""


class ActionKind(str, enum.Enum):
    """Supported coordinator mutation classes."""

    REVIEW_REPAIR = "review_repair"
    PRODUCT_DEVELOPMENT = "product_development"


@dataclasses.dataclass(frozen=True)
class WorkflowRecord:
    """Describe one repository workflow and its exact inspected source."""

    workflow_id: int
    name: str
    path: str
    state: str
    content_sha: str
    content: str | None


@dataclasses.dataclass(frozen=True)
class RunRecord:
    """Describe one workflow run that may hold a live writer lease."""

    run_id: int
    name: str
    path: str
    status: str
    head_sha: str


@dataclasses.dataclass(frozen=True)
class PullRequestRecord:
    """Describe the exact pull-request fields used by the selection policy."""

    number: int
    draft: bool
    base_ref: str
    head_sha: str
    updated_at: str


@dataclasses.dataclass(frozen=True)
class RepositorySnapshot:
    """Bind repository selection evidence to one stable default-branch state."""

    full_name: str
    default_branch: str
    default_sha: str
    workflows: tuple[WorkflowRecord, ...]
    active_runs: tuple[RunRecord, ...]
    open_pulls: tuple[PullRequestRecord, ...]

    @property
    def fingerprint(self) -> str:
        """Return a deterministic digest independent of API result ordering."""
        payload = {
            "full_name": self.full_name,
            "default_branch": self.default_branch,
            "default_sha": self.default_sha,
            "workflows": sorted(
                (
                    item.workflow_id,
                    item.name,
                    item.path,
                    item.state,
                    item.content_sha,
                )
                for item in self.workflows
            ),
            "active_runs": sorted(
                (item.run_id, item.name, item.path, item.status, item.head_sha)
                for item in self.active_runs
            ),
            "open_pulls": sorted(
                (
                    item.number,
                    item.draft,
                    item.base_ref,
                    item.head_sha,
                    item.updated_at,
                )
                for item in self.open_pulls
            ),
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclasses.dataclass(frozen=True)
class PlanItem:
    """Describe one bounded mutation selected from an initial snapshot."""

    kind: ActionKind
    repository: str
    default_branch: str
    expected_fingerprint: str
    workflow_id: int | None = None


@dataclasses.dataclass(frozen=True)
class ActionResult:
    """Record the outcome of one revalidated coordinator action."""

    kind: ActionKind
    repository: str
    status: str
    detail: str


@dataclasses.dataclass(frozen=True)
class RunReport:
    """Provide machine-readable and operator-readable evidence for one run."""

    organization: str
    inspected_repositories: int
    leased_repositories: tuple[str, ...]
    inspection_errors: tuple[tuple[str, str], ...]
    actions: tuple[ActionResult, ...]
    dry_run: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of this report."""
        return {
            "organization": self.organization,
            "inspected_repositories": self.inspected_repositories,
            "leased_repositories": list(self.leased_repositories),
            "inspection_errors": [
                {"repository": repository, "error": error}
                for repository, error in self.inspection_errors
            ],
            "actions": [
                {
                    "kind": action.kind.value,
                    "repository": action.repository,
                    "status": action.status,
                    "detail": action.detail,
                }
                for action in self.actions
            ],
            "dry_run": self.dry_run,
        }

    def to_json(self) -> str:
        """Serialize this report as stable UTF-8 JSON text."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)

    def to_markdown(self) -> str:
        """Render a concise GitHub Actions job summary."""
        lines = [
            "# Organization commercial-readiness coordinator",
            "",
            f"- Organization: `{self.organization}`",
            f"- Repositories inspected: **{self.inspected_repositories}**",
            f"- Repositories leased to dedicated writers: **{len(self.leased_repositories)}**",
            f"- Inspection errors: **{len(self.inspection_errors)}**",
            f"- Dry run: **{'yes' if self.dry_run else 'no'}**",
            "",
            "## Actions",
            "",
            "| Kind | Repository | Status | Detail |",
            "|---|---|---|---|",
        ]
        if self.actions:
            for action in self.actions:
                detail = action.detail.replace("|", "\\|").replace("\n", " ")
                lines.append(
                    f"| `{action.kind.value}` | `{action.repository}` | "
                    f"`{action.status}` | {detail} |"
                )
        else:
            lines.append("| — | — | `no_action` | No safe target was selected. |")
        if self.inspection_errors:
            lines.extend(["", "## Inspection errors", ""])
            for repository, error in self.inspection_errors:
                lines.append(f"- `{repository}`: {error}")
        return "\n".join(lines) + "\n"


class GitHubClient:
    """Use the GitHub CLI as an authenticated, bounded REST transport."""

    def __init__(self, token: str, *, timeout_seconds: int = 60) -> None:
        if not token:
            raise GitHubError("GH_TOKEN is required for organization coordination")
        self._token = token
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> GitHubClient:
        """Build a client without accepting the repository-scoped GITHUB_TOKEN."""
        values = os.environ if environ is None else environ
        token = str(values.get("GH_TOKEN") or "").strip()
        if not token:
            raise GitHubError("GH_TOKEN is required; no GITHUB_TOKEN fallback is permitted")
        return cls(token)

    def _redact_credential(self, value: str) -> str:
        """Remove the exact GitHub credential before any diagnostic truncation."""
        return value.replace(self._token, "[REDACTED]")

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: Any = None,
    ) -> Any:
        """Call one GitHub REST endpoint and decode a bounded JSON response."""
        normalized_method = method.upper()
        safe_path = self._redact_credential(path)
        args = ["gh", "api"]
        if normalized_method != "GET":
            args.extend(["--method", normalized_method])
        args.append(path)
        input_text: str | None = None
        if payload is not None:
            args.extend(["--input", "-"])
            input_text = json.dumps(payload, separators=(",", ":"))
        try:
            completed = subprocess.run(
                args,
                input=input_text,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                env={**os.environ, "GH_TOKEN": self._token},
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise GitHubError(f"GitHub API transport failed: {type(exc).__name__}") from exc
        if completed.returncode != 0:
            raw = (completed.stderr or completed.stdout or "GitHub API request failed").strip()
            bounded = self._redact_credential(raw)[-900:]
            raise GitHubError(
                f"GitHub API {normalized_method} {safe_path} failed: {bounded}"
            )
        text = completed.stdout.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise GitHubError(
                f"GitHub API returned invalid JSON for {safe_path}"
            ) from exc

    def list_repositories(self, organization: str) -> list[dict[str, Any]]:
        """Return every repository visible to the coordinator installation."""
        repositories: list[dict[str, Any]] = []
        page = 1
        while True:
            result = self.request(
                f"/orgs/{organization}/repos?type=all&sort=full_name&per_page=100&page={page}"
            )
            batch = list(result or [])
            repositories.extend(batch)
            if len(batch) < 100:
                return repositories
            page += 1

    def default_branch_sha(self, repository: str, default_branch: str) -> str:
        """Resolve one exact commit for the repository default branch."""
        branch_ref = quote(default_branch, safe="")
        result = self.request(f"/repos/{repository}/commits/{branch_ref}")
        sha = str((result or {}).get("sha") or "")
        if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
            raise GitHubError(f"repository {repository} returned an invalid default-branch SHA")
        return sha.lower()

    def list_workflows(self, repository: str, exact_ref: str) -> tuple[WorkflowRecord, ...]:
        """Return workflow metadata and exact source only for writer candidates."""
        workflows: list[WorkflowRecord] = []
        page = 1
        while True:
            result = self.request(
                f"/repos/{repository}/actions/workflows?per_page=100&page={page}"
            )
            batch = list((result or {}).get("workflows") or [])
            for raw in batch:
                workflow_id = int(raw.get("id") or 0)
                path = str(raw.get("path") or "")
                name = str(raw.get("name") or path)
                state = str(raw.get("state") or "unknown")
                content: str | None = None
                content_sha = ""
                if (
                    path
                    and not path.startswith("dynamic/")
                    and _writer_signal(name, path)
                ):
                    encoded_path = quote(path, safe="/")
                    try:
                        source = self.request(
                            f"/repos/{repository}/contents/{encoded_path}?ref={exact_ref}"
                        )
                        if (
                            isinstance(source, dict)
                            and source.get("type") == "file"
                            and int(source.get("size") or 0) <= 1_048_576
                            and source.get("encoding") == "base64"
                        ):
                            decoded = base64.b64decode(
                                str(source.get("content") or ""), validate=True
                            )
                            content = decoded.decode("utf-8")
                            content_sha = str(source.get("sha") or "")
                    except (GitHubError, ValueError, UnicodeDecodeError):
                        content = None
                        content_sha = ""
                workflows.append(
                    WorkflowRecord(
                        workflow_id=workflow_id,
                        name=name,
                        path=path,
                        state=state,
                        content_sha=content_sha,
                        content=content,
                    )
                )
            if len(batch) < 100:
                return tuple(workflows)
            page += 1

    def list_active_runs(self, repository: str) -> tuple[RunRecord, ...]:
        """Return all queued and running workflow evidence for writer lease detection."""
        records: list[RunRecord] = []
        for status in ("queued", "in_progress", "waiting", "pending", "requested"):
            page = 1
            while True:
                result = self.request(
                    f"/repos/{repository}/actions/runs?status={status}&per_page=100&page={page}"
                )
                batch = list((result or {}).get("workflow_runs") or [])
                for raw in batch:
                    records.append(
                        RunRecord(
                            run_id=int(raw.get("id") or 0),
                            name=str(raw.get("name") or ""),
                            path=str(raw.get("path") or ""),
                            status=str(raw.get("status") or status),
                            head_sha=str(raw.get("head_sha") or ""),
                        )
                    )
                if len(batch) < 100:
                    break
                page += 1
        return tuple(records)

    def list_open_pulls(self, repository: str) -> tuple[PullRequestRecord, ...]:
        """Return all open pull requests with exact stack and head identity."""
        records: list[PullRequestRecord] = []
        page = 1
        while True:
            result = self.request(
                f"/repos/{repository}/pulls?state=open&per_page=100&page={page}"
            )
            batch = list(result or [])
            for raw in batch:
                records.append(
                    PullRequestRecord(
                        number=int(raw.get("number") or 0),
                        draft=bool(raw.get("draft")),
                        base_ref=str((raw.get("base") or {}).get("ref") or ""),
                        head_sha=str((raw.get("head") or {}).get("sha") or ""),
                        updated_at=str(raw.get("updated_at") or ""),
                    )
                )
            if len(batch) < 100:
                return tuple(records)
            page += 1

    def snapshot(self, repository: str, default_branch: str) -> RepositorySnapshot:
        """Materialize one snapshot and reject concurrent default-branch movement."""
        before = self.default_branch_sha(repository, default_branch)
        workflows = self.list_workflows(repository, before)
        runs = self.list_active_runs(repository)
        pulls = self.list_open_pulls(repository)
        after = self.default_branch_sha(repository, default_branch)
        if before != after:
            raise SnapshotChanged(
                f"default branch moved while inspecting {repository}: {before} -> {after}"
            )
        return RepositorySnapshot(
            full_name=repository,
            default_branch=default_branch,
            default_sha=before,
            workflows=workflows,
            active_runs=runs,
            open_pulls=pulls,
        )

    def dispatch_review_repair(self, repository: str, base_branch: str) -> None:
        """Ask the established central scheduler for one bounded repair attempt."""
        self.request(
            f"/repos/{CENTRAL_REPOSITORY}/dispatches",
            method="POST",
            payload={
                "event_type": CENTRAL_REPAIR_EVENT,
                "client_payload": {
                    "target_repository": repository,
                    "base_branch": base_branch,
                    "max_prs": "50",
                    "max_dispatches": "1",
                    "retry_hours": "1",
                    "dry_run": False,
                },
            },
        )

    def dispatch_product_workflow(
        self, repository: str, workflow_id: int, default_branch: str
    ) -> None:
        """Dispatch an explicitly opted-in repository-local development entrypoint."""
        self.request(
            f"/repos/{repository}/actions/workflows/{workflow_id}/dispatches",
            method="POST",
            payload={"ref": default_branch},
        )


def _writer_signal(name: str, path: str) -> bool:
    """Return whether workflow identity indicates a repository writer."""
    identity = f"{name}\n{path}"
    return bool(WRITER_SIGNAL_RE.search(identity)) and not bool(
        MERGE_SCHEDULER_RE.search(identity)
    )


def is_dedicated_writer_workflow(workflow: WorkflowRecord) -> bool:
    """Return whether an active scheduled workflow owns the repository writer lease."""
    if workflow.state != "active" or not _writer_signal(workflow.name, workflow.path):
        return False
    if workflow.content is None:
        return True
    return bool(SCHEDULE_RE.search(workflow.content))


def is_live_writer_run(run: RunRecord) -> bool:
    """Return whether a queued or running high-signal workflow owns a live lease."""
    return run.status in ACTIVE_RUN_STATES and _writer_signal(run.name, run.path)


def is_manual_product_entrypoint(workflow: WorkflowRecord) -> bool:
    """Return whether a workflow explicitly opts in to central product dispatch."""
    source = workflow.content
    if workflow.state != "active" or source is None:
        return False
    return all(
        (
            ENTRYPOINT_MARKER in source,
            bool(WORKFLOW_DISPATCH_RE.search(source)),
            not bool(SCHEDULE_RE.search(source)),
            "NVIDIA_NIM_API_KEY" in source,
            "COPILOT_GITHUB_TOKEN" not in source,
            "concurrency:" in source,
            _writer_signal(workflow.name, workflow.path),
        )
    )


def repository_is_eligible(repository: Mapping[str, Any], organization: str) -> bool:
    """Return whether one owned repository can participate in organization coordination."""
    full_name = str(repository.get("full_name") or "")
    permissions = repository.get("permissions") or {}
    write_capable = any(bool(permissions.get(key)) for key in ("push", "maintain", "admin"))
    return all(
        (
            full_name.startswith(f"{organization}/"),
            full_name != f"{organization}/.github",
            not bool(repository.get("archived")),
            not bool(repository.get("disabled")),
            not bool(repository.get("fork")),
            bool(repository.get("default_branch")),
            write_capable,
        )
    )


def choose_rotating(items: Sequence[Any], seed: int, limit: int) -> tuple[Any, ...]:
    """Choose a bounded cyclic window so later repositories are not starved."""
    if not items or limit <= 0:
        return ()
    count = min(limit, len(items))
    start = seed % len(items)
    return tuple(items[(start + offset) % len(items)] for offset in range(count))


def _has_writer_lease(snapshot: RepositorySnapshot) -> bool:
    """Return whether static or live evidence assigns this repository elsewhere."""
    return any(is_dedicated_writer_workflow(item) for item in snapshot.workflows) or any(
        is_live_writer_run(item) for item in snapshot.active_runs
    )


def _eligible_review_snapshot(snapshot: RepositorySnapshot) -> bool:
    """Return whether generic review repair is safe for at least one direct PR."""
    return any(
        not pull.draft and pull.base_ref == snapshot.default_branch
        for pull in snapshot.open_pulls
    )


def _manual_product_workflow(snapshot: RepositorySnapshot) -> WorkflowRecord | None:
    """Return the first deterministic opted-in manual development entrypoint."""
    matches = sorted(
        (item for item in snapshot.workflows if is_manual_product_entrypoint(item)),
        key=lambda item: (item.path, item.workflow_id),
    )
    return matches[0] if matches else None


def build_plan(
    snapshots: Iterable[RepositorySnapshot],
    *,
    rotation_seed: int,
    max_review_dispatches: int = 1,
    max_development_dispatches: int = 1,
) -> tuple[PlanItem, ...]:
    """Select independent bounded review and product targets from exact snapshots."""
    usable = tuple(
        sorted(
            (
                item
                for item in snapshots
                if item.full_name != CENTRAL_REPOSITORY and not _has_writer_lease(item)
            ),
            key=lambda item: item.full_name,
        )
    )
    review_candidates = tuple(item for item in usable if _eligible_review_snapshot(item))
    development_candidates = tuple(
        (item, workflow)
        for item in usable
        if not item.open_pulls
        for workflow in (_manual_product_workflow(item),)
        if workflow is not None
    )
    plan: list[PlanItem] = []
    for item in choose_rotating(review_candidates, rotation_seed, max_review_dispatches):
        plan.append(
            PlanItem(
                kind=ActionKind.REVIEW_REPAIR,
                repository=item.full_name,
                default_branch=item.default_branch,
                expected_fingerprint=item.fingerprint,
            )
        )
    for item, workflow in choose_rotating(
        development_candidates, rotation_seed, max_development_dispatches
    ):
        plan.append(
            PlanItem(
                kind=ActionKind.PRODUCT_DEVELOPMENT,
                repository=item.full_name,
                default_branch=item.default_branch,
                expected_fingerprint=item.fingerprint,
                workflow_id=workflow.workflow_id,
            )
        )
    return tuple(plan)


def _bounded_error(exc: BaseException) -> str:
    """Return a stable, bounded error description without stack or credential data."""
    text = f"{type(exc).__name__}: {exc}".replace("\n", " ")
    return text[:1000]


def run_once(
    client: Any,
    *,
    organization: str,
    rotation_seed: int,
    max_repositories: int = 200,
    max_review_dispatches: int = 1,
    max_development_dispatches: int = 1,
    dry_run: bool = False,
) -> RunReport:
    """Inspect the organization, revalidate targets, and dispatch bounded work."""
    if organization != DEFAULT_ORGANIZATION:
        raise GitHubError(
            f"organization must be {DEFAULT_ORGANIZATION}; foreign control planes are not supported"
        )
    raw_repositories = client.list_repositories(organization)
    eligible = sorted(
        (
            item
            for item in raw_repositories
            if repository_is_eligible(item, organization)
        ),
        key=lambda item: str(item.get("full_name") or ""),
    )
    selected_repositories = choose_rotating(eligible, rotation_seed, max_repositories)
    snapshots: list[RepositorySnapshot] = []
    errors: list[tuple[str, str]] = []
    leased: list[str] = []
    for repository in selected_repositories:
        full_name = str(repository["full_name"])
        default_branch = str(repository["default_branch"])
        try:
            current = client.snapshot(full_name, default_branch)
        except (GitHubError, SnapshotChanged) as exc:
            errors.append((full_name, _bounded_error(exc)))
            continue
        snapshots.append(current)
        if _has_writer_lease(current):
            leased.append(full_name)
    plan = build_plan(
        snapshots,
        rotation_seed=rotation_seed,
        max_review_dispatches=max_review_dispatches,
        max_development_dispatches=max_development_dispatches,
    )
    actions: list[ActionResult] = []
    for item in plan:
        try:
            live = client.snapshot(item.repository, item.default_branch)
        except (GitHubError, SnapshotChanged) as exc:
            actions.append(
                ActionResult(
                    kind=item.kind,
                    repository=item.repository,
                    status="skipped_refetch_error",
                    detail=_bounded_error(exc),
                )
            )
            continue
        if _has_writer_lease(live):
            actions.append(
                ActionResult(
                    kind=item.kind,
                    repository=item.repository,
                    status="skipped_writer_lease",
                    detail="a dedicated or live writer appeared before dispatch",
                )
            )
            continue
        if live.fingerprint != item.expected_fingerprint:
            actions.append(
                ActionResult(
                    kind=item.kind,
                    repository=item.repository,
                    status="skipped_state_changed",
                    detail="repository, workflow, run, or pull-request state moved before dispatch",
                )
            )
            continue
        if dry_run:
            actions.append(
                ActionResult(
                    kind=item.kind,
                    repository=item.repository,
                    status="dry_run",
                    detail="exact state revalidated; mutation intentionally suppressed",
                )
            )
            continue
        try:
            if item.kind is ActionKind.REVIEW_REPAIR:
                client.dispatch_review_repair(item.repository, item.default_branch)
            else:
                if item.workflow_id is None:
                    raise GitHubError("product-development plan omitted workflow identity")
                client.dispatch_product_workflow(
                    item.repository, item.workflow_id, item.default_branch
                )
        except GitHubError as exc:
            actions.append(
                ActionResult(
                    kind=item.kind,
                    repository=item.repository,
                    status="dispatch_failed",
                    detail=_bounded_error(exc),
                )
            )
        else:
            actions.append(
                ActionResult(
                    kind=item.kind,
                    repository=item.repository,
                    status="dispatched",
                    detail="exact state revalidated and bounded workflow dispatched",
                )
            )
    return RunReport(
        organization=organization,
        inspected_repositories=len(snapshots),
        leased_repositories=tuple(sorted(leased)),
        inspection_errors=tuple(errors),
        actions=tuple(actions),
        dry_run=dry_run,
    )


def _non_negative_int(value: str) -> int:
    """Parse one non-negative integer command-line bound."""
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be zero or greater")
    return parsed


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser used by workflow and local dry runs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--organization", default=DEFAULT_ORGANIZATION)
    parser.add_argument("--rotation-seed", type=int, default=0)
    parser.add_argument("--max-repositories", type=_non_negative_int, default=200)
    parser.add_argument("--max-review-dispatches", type=_non_negative_int, default=1)
    parser.add_argument("--max-development-dispatches", type=_non_negative_int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-output", type=Path)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    client_factory: Callable[[], Any] | None = None,
) -> int:
    """Run the coordinator CLI and persist auditable receipts."""
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    if not ORGANIZATION_RE.fullmatch(args.organization):
        print("invalid organization", file=sys.stderr)
        return 2
    factory = client_factory or GitHubClient.from_environment
    try:
        client = factory()
        report = run_once(
            client,
            organization=args.organization,
            rotation_seed=args.rotation_seed,
            max_repositories=args.max_repositories,
            max_review_dispatches=args.max_review_dispatches,
            max_development_dispatches=args.max_development_dispatches,
            dry_run=args.dry_run,
        )
    except (GitHubError, SnapshotChanged, ValueError) as exc:
        print(_bounded_error(exc), file=sys.stderr)
        return 2
    text = report.to_json() + "\n"
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as handle:
            handle.write(report.to_markdown())
    all_selected_inspections_failed = (
        report.inspected_repositories == 0 and bool(report.inspection_errors)
    )
    all_planned_dispatches_failed = bool(report.actions) and all(
        action.status == "dispatch_failed" for action in report.actions
    )
    return 1 if all_selected_inspections_failed or all_planned_dispatches_failed else 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())