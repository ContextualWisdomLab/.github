"""Pure state core for durable, bounded review-worker admission."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass

REPOSITORY_RE = re.compile(r"^ContextualWisdomLab/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
COMPONENT_ORDER = {"opencode": 0, "noema": 1, "strix": 2}
ADMISSION_PERMISSIONS = ("contents: read", "pull-requests: read")


@dataclass(frozen=True)
class WorkerBoundary:
    credential: str
    permissions: tuple[str, ...]
    concurrency_namespace: str
    cancel_in_progress: bool = True

    def concurrency_group(self, request: AdmissionRequest) -> str:
        return (
            f"{self.concurrency_namespace}-{request.repository}-{request.pull_request}"
        )


WORKER_BOUNDARIES = {
    "opencode": WorkerBoundary(
        "opencode-app-oidc",
        ("contents: read", "pull-requests: read", "pull-requests: write"),
        "opencode-review",
    ),
    "noema": WorkerBoundary(
        "noema-reviewer",
        ("contents: read", "pull-requests: read", "pull-requests: write"),
        "noema-review",
    ),
    "strix": WorkerBoundary(
        "strix-provider-and-status-separated",
        ("contents: read", "pull-requests: read", "statuses: write", "id-token: write"),
        "strix-security-scan",
    ),
}


@dataclass(frozen=True)
class AdmissionRequest:
    repository: str
    pull_request: int
    head_sha: str
    component: str
    sequence: int

    @classmethod
    def create(
        cls,
        *,
        repository: str,
        pull_request: int,
        head_sha: str,
        component: str,
        sequence: int,
    ) -> AdmissionRequest:
        normalized_head = head_sha.lower()
        if not REPOSITORY_RE.fullmatch(repository):
            raise ValueError("repository is outside ContextualWisdomLab")
        if pull_request < 1:
            raise ValueError("pull request must be positive")
        if not SHA_RE.fullmatch(normalized_head):
            raise ValueError("head must be a full Git SHA")
        if component not in WORKER_BOUNDARIES:
            raise ValueError("unknown review component")
        if sequence < 1:
            raise ValueError("sequence must be positive")
        return cls(repository, pull_request, normalized_head, component, sequence)

    @property
    def identity(self) -> str:
        return f"{self.repository}#{self.pull_request}@{self.head_sha}:{self.component}"

    @property
    def stream(self) -> str:
        return f"{self.repository}#{self.pull_request}:{self.component}"


@dataclass(frozen=True)
class RequestRecord:
    request: AdmissionRequest
    status: str


@dataclass(frozen=True)
class DispatchLease:
    request: AdmissionRequest
    boundary: WorkerBoundary


@dataclass(frozen=True)
class ControllerState:
    records: dict[str, RequestRecord]
    latest_sequences: dict[str, int]

    @classmethod
    def empty(cls) -> ControllerState:
        return cls({}, {})

    def to_json(self) -> str:
        payload = {
            "latest_sequences": self.latest_sequences,
            "records": {
                identity: {
                    "request": asdict(record.request),
                    "status": record.status,
                }
                for identity, record in sorted(self.records.items())
            },
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, value: str) -> ControllerState:
        payload = json.loads(value)
        if not isinstance(payload, dict):
            raise TypeError("durable admission state must be an object")
        if not isinstance(payload.get("records", {}), dict) or not isinstance(
            payload.get("latest_sequences", {}), dict
        ):
            raise TypeError("durable admission state has invalid collections")
        records = {}
        for identity, raw in payload.get("records", {}).items():
            request = AdmissionRequest.create(**raw["request"])
            if identity != request.identity or raw["status"] not in {
                "queued",
                "dispatched",
                "complete",
                "stale",
            }:
                raise ValueError("invalid durable admission record")
            records[identity] = RequestRecord(request, raw["status"])
        latest = {
            str(key): int(sequence)
            for key, sequence in payload.get("latest_sequences", {}).items()
        }
        for record in records.values():
            if latest.get(record.request.stream, 0) < record.request.sequence:
                raise ValueError("durable admission sequence regressed")
        return cls(records, latest)


@dataclass(frozen=True)
class DispatchPlan:
    state: ControllerState
    dispatches: tuple[DispatchLease, ...]
    rejections: dict[str, str]


def plan_dispatches(
    state: ControllerState,
    requests: Iterable[AdmissionRequest],
    *,
    live_heads: Mapping[tuple[str, int], str],
    dispatch_budget: int,
) -> DispatchPlan:
    """Apply requests and lease at most ``dispatch_budget`` independent workers."""
    if dispatch_budget < 0:
        raise ValueError("dispatch budget must not be negative")
    records = dict(state.records)
    latest = dict(state.latest_sequences)
    rejections: dict[str, str] = {}
    seen: set[str] = set()

    for request in requests:
        prior_sequence = latest.get(request.stream, 0)
        if request.identity in seen:
            rejections[request.identity] = "duplicate"
            continue
        seen.add(request.identity)
        if request.identity in records:
            rejections[request.identity] = "idempotent"
            continue
        if request.sequence <= prior_sequence:
            rejections[request.identity] = "out_of_order"
            continue
        live_head = str(
            live_heads.get((request.repository, request.pull_request), "")
        ).lower()
        if request.head_sha != live_head:
            records[request.identity] = RequestRecord(request, "stale")
            latest[request.stream] = max(prior_sequence, request.sequence)
            rejections[request.identity] = "stale_head"
            continue
        for identity, record in tuple(records.items()):
            if (
                record.request.stream == request.stream
                and record.request.head_sha != request.head_sha
                and record.status == "queued"
            ):
                records[identity] = RequestRecord(record.request, "stale")
        records[request.identity] = RequestRecord(request, "queued")
        latest[request.stream] = request.sequence

    queued = sorted(
        (record for record in records.values() if record.status == "queued"),
        key=lambda record: (
            record.request.sequence,
            record.request.repository,
            record.request.pull_request,
            COMPONENT_ORDER[record.request.component],
        ),
    )
    dispatches = []
    for record in queued:
        if len(dispatches) >= dispatch_budget:
            break
        request = record.request
        live_head = str(
            live_heads.get((request.repository, request.pull_request), "")
        ).lower()
        if request.head_sha != live_head:
            records[request.identity] = RequestRecord(request, "stale")
            rejections[request.identity] = "stale_head"
            continue
        records[request.identity] = RequestRecord(request, "dispatched")
        dispatches.append(DispatchLease(request, WORKER_BOUNDARIES[request.component]))

    return DispatchPlan(ControllerState(records, latest), tuple(dispatches), rejections)


def require_publishable(lease: DispatchLease, *, live_head: str) -> None:
    """Fail closed immediately before a worker publishes its result."""
    if lease.request.head_sha != live_head.lower():
        raise ValueError("live head changed before publication")


def complete_dispatch(
    state: ControllerState,
    lease: DispatchLease,
    *,
    live_head: str,
) -> ControllerState:
    """Record terminal publication only after an exact-head compare-and-swap."""
    require_publishable(lease, live_head=live_head)
    record = state.records.get(lease.request.identity)
    if record is None or record.status != "dispatched":
        raise ValueError("request does not hold an active dispatch lease")
    records = dict(state.records)
    records[lease.request.identity] = RequestRecord(lease.request, "complete")
    return ControllerState(records, dict(state.latest_sequences))


def self_test() -> None:
    """Keep the scheduler's trusted-source smoke path bound to this core."""
    head = "a" * 40
    request = AdmissionRequest.create(
        repository="ContextualWisdomLab/example",
        pull_request=1,
        head_sha=head,
        component="opencode",
        sequence=1,
    )
    plan = plan_dispatches(
        ControllerState.empty(),
        [request, request],
        live_heads={(request.repository, request.pull_request): head},
        dispatch_budget=1,
    )
    assert len(plan.dispatches) == 1
    assert ControllerState.from_json(plan.state.to_json()) == plan.state
    completed = complete_dispatch(plan.state, plan.dispatches[0], live_head=head)
    assert completed.records[request.identity].status == "complete"
