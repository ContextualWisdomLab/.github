"""Pure state core for durable, bounded review-worker admission."""

from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

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
        if isinstance(pull_request, bool) or not isinstance(pull_request, int):
            raise TypeError("pull request must be an integer")
        if isinstance(sequence, bool) or not isinstance(sequence, int):
            raise TypeError("sequence must be an integer")
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
        if set(payload) - {"records", "latest_sequences"}:
            raise ValueError("durable admission state has unknown fields")
        records = {}
        for identity, raw in payload.get("records", {}).items():
            if not isinstance(identity, str) or not isinstance(raw, dict):
                raise TypeError("durable admission record has invalid shape")
            if set(raw) != {"request", "status"} or not isinstance(
                raw["request"], dict
            ):
                raise ValueError("invalid durable admission record")
            if set(raw["request"]) != {
                "repository",
                "pull_request",
                "head_sha",
                "component",
                "sequence",
            }:
                raise ValueError("invalid durable admission request")
            request = AdmissionRequest.create(**raw["request"])
            if identity != request.identity or raw["status"] not in {
                "queued",
                "dispatched",
                "complete",
                "stale",
            }:
                raise ValueError("invalid durable admission record")
            records[identity] = RequestRecord(request, raw["status"])
        latest = {}
        for key, sequence in payload.get("latest_sequences", {}).items():
            if (
                not isinstance(key, str)
                or isinstance(sequence, bool)
                or not isinstance(sequence, int)
                or sequence < 1
            ):
                raise ValueError("invalid durable admission sequence")
            latest[key] = sequence
        active_records = [
            record for record in records.values() if record.status != "stale"
        ]
        for record in active_records:
            if latest.get(record.request.stream, 0) < record.request.sequence:
                raise ValueError("durable admission sequence regressed")
        expected_streams = {record.request.stream for record in active_records}
        if set(latest) != expected_streams:
            raise ValueError("durable admission state has unknown streams")
        for stream in expected_streams:
            if latest[stream] != max(
                record.request.sequence
                for record in active_records
                if record.request.stream == stream
            ):
                raise ValueError("durable admission sequence is inconsistent")
        return cls(records, latest)


def _open_regular_nofollow(path: Path, flags: int, mode: int = 0o600) -> int:
    """Open one trusted local state file without following a symlink."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags | nofollow, mode)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise ValueError("admission state path is not a regular file")
    return descriptor


def _read_state(path: Path) -> ControllerState:
    descriptor = _open_regular_nofollow(path, os.O_RDONLY)
    try:
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            return ControllerState.from_json(stream.read())
    except UnicodeDecodeError as exc:
        raise ValueError("durable admission state is not UTF-8") from exc


def load_state_file(path: Path) -> ControllerState:
    """Load state, recovering only from the last atomically replaced snapshot."""
    path = Path(path)
    if path.is_symlink():
        raise ValueError("admission state path must not be a symlink")
    try:
        return _read_state(path)
    except FileNotFoundError:
        return ControllerState.empty()
    except (json.JSONDecodeError, TypeError, ValueError):
        backup = path.with_name(f"{path.name}.bak")
        if backup.is_symlink():
            raise ValueError("admission state backup must not be a symlink")
        try:
            return _read_state(backup)
        except FileNotFoundError:
            raise ValueError("durable admission state is corrupt and has no backup") from None


def _atomic_write(path: Path, value: str) -> None:
    """Replace one state snapshot atomically in its existing directory."""
    if path.is_symlink():
        raise ValueError("admission state path must not be a symlink")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def update_state_file(
    path: Path,
    update: Callable[[ControllerState], ControllerState],
) -> ControllerState:
    """Serialize concurrent read-modify-write transactions with recovery."""
    path = Path(path)
    lock_path = path.with_name(f"{path.name}.lock")
    if lock_path.is_symlink():
        raise ValueError("admission state lock must not be a symlink")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = _open_regular_nofollow(lock_path, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        state = load_state_file(path)
        updated = update(state)
        if not isinstance(updated, ControllerState):
            raise TypeError("state update must return ControllerState")
        _atomic_write(path, updated.to_json())
        _atomic_write(path.with_name(f"{path.name}.bak"), updated.to_json())
        return updated
    finally:
        os.close(descriptor)


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
    available_budget = max(
        0,
        dispatch_budget
        - sum(record.status == "dispatched" for record in records.values()),
    )
    for record in queued:
        if len(dispatches) >= available_budget:
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
    if lease.boundary != WORKER_BOUNDARIES.get(lease.request.component):
        raise ValueError("dispatch lease crossed its worker boundary")
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
