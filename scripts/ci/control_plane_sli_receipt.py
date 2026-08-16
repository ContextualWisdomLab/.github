"""Build deterministic, bounded control-plane service-level indicator receipts.

The module consumes only a local, finite-cardinality evidence document. It does
not query GitHub, interpret reviews, or acquire any mutation authority.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "cwl.control-plane-sli/v1"
DEFER_REASON_CODES = frozenset(
    {
        "EXECUTABLE_NOW",
        "WAIT_CHECK_PENDING",
        "WAIT_DEPENDENCY",
        "WAIT_EXTERNAL_GOVERNANCE",
        "WAIT_PERMISSION",
        "WAIT_PROVIDER_COOLDOWN",
        "WAIT_RATE_LIMIT",
        "WAIT_REVIEW_PENDING",
        "WAIT_WRITER_LEASE",
    }
)
TRANSIENT_FAILURE_CLASSES = frozenset(
    {"capacity", "dns", "provider", "runner", "timeout", "transport"}
)

_REPOSITORY_RE = re.compile(r"^ContextualWisdomLab/[A-Za-z0-9._-]+$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_UTC_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$"
)
_TOP_LEVEL_FIELDS = frozenset({"repositories"})
_REPOSITORY_FIELDS = frozenset(
    {
        "repository",
        "protected_base_branch",
        "lanes",
        "retries",
        "writer_collisions_avoided",
        "transitions",
        "meta_intermediate_events",
        "meta_followed_by_substantive_action",
        "first_exit_sweep_work_discoveries",
        "run_budget_exhausted_handoffs",
        "user_redirection_incidents",
        "user_redirection_multi_lane_recoveries",
        "user_redirection_non_documentation_recoveries",
    }
)
_REPOSITORY_OPTIONAL_FIELDS = frozenset(
    {
        "user_redirection_incidents",
        "user_redirection_multi_lane_recoveries",
        "user_redirection_non_documentation_recoveries",
    }
)
_LANE_FIELDS = frozenset({"reason_code", "source_head_sha", "observed_at"})
_RETRY_FIELDS = frozenset({"failure_class", "attempts", "exhausted"})
_TRANSITION_FIELDS = frozenset(
    {
        "gate_clean_at",
        "protected_merge_at",
        "merge_revision_sha",
        "operational_acceptance_at",
    }
)
_MAX_REPOSITORIES = 1_000
_MAX_ITEMS_PER_REPOSITORY = 10_000


def _require_mapping(value: object, label: str) -> Mapping[str, Any]:
    """Return an object-shaped value or reject it with a field-specific error."""
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} keys must be strings")
    return value


def _require_fields(
    value: Mapping[str, Any],
    allowed: frozenset[str],
    label: str,
    *,
    optional: frozenset[str] = frozenset(),
) -> None:
    """Require known finite fields while allowing explicitly additive fields.

    ``optional`` exists for backwards-compatible additive metrics inside a
    versioned receipt schema. Unknown fields still fail closed, while legacy v1
    producers may omit the newly introduced finite counters.
    """
    unknown = set(value) - allowed
    missing = (allowed - optional) - set(value)
    if unknown:
        raise ValueError(f"{label} has unknown fields: {sorted(unknown)}")
    if missing:
        raise ValueError(f"{label} is missing fields: {sorted(missing)}")


def _require_list(value: object, label: str) -> Sequence[object]:
    """Return a bounded array while rejecting strings and oversized inputs."""
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be an array")
    if len(value) > _MAX_ITEMS_PER_REPOSITORY:
        raise ValueError(f"{label} exceeds the bounded item limit")
    return value


def _require_nonnegative_integer(value: object, label: str) -> int:
    """Return a real non-negative integer, explicitly excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _parse_timestamp(value: object, label: str) -> datetime:
    """Parse one explicitly UTC RFC 3339 timestamp ending in ``Z``."""
    if not isinstance(value, str) or _UTC_TIMESTAMP_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a UTC RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError(f"{label} must be a UTC RFC 3339 timestamp") from error
    return parsed


def _format_timestamp(value: datetime) -> str:
    """Format a datetime as a whole-second UTC RFC 3339 timestamp."""
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _validated_now(now: datetime | None) -> datetime:
    """Return an aware UTC observation time, using the current time if absent."""
    current = now or datetime.now(timezone.utc)
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError("now must be a timezone-aware datetime")
    return current.astimezone(timezone.utc)


def _load_strict_json(path: Path) -> object:
    """Load UTF-8 JSON while rejecting duplicate keys and non-finite numbers."""

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        """Build one JSON object only when every member name is unique."""
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON member: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        """Reject non-standard JSON number constants such as NaN and Infinity."""
        raise ValueError(f"non-finite JSON number: {value}")

    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read strict JSON input: {error}") from error


def build_receipt(
    payload: Mapping[str, object], *, now: datetime | None = None
) -> dict[str, object]:
    """Validate bounded evidence and return its canonical aggregate receipt.

    The result intentionally reports descriptive counts and durations only. It
    never treats a check, review, status, or model result as merge authority.
    User-redirection counters measure scheduler recovery outcomes without
    introducing repository names, comments, model text, or other unbounded
    labels into the emitted receipt.
    """
    current = _validated_now(now)
    root = _require_mapping(payload, "payload")
    _require_fields(root, _TOP_LEVEL_FIELDS, "payload")
    repositories = _require_list(root["repositories"], "repositories")
    if len(repositories) > _MAX_REPOSITORIES:
        raise ValueError("repositories exceeds the bounded repository limit")

    seen_repositories: set[str] = set()
    executable_ages: list[int] = []
    deferred_ages: dict[str, list[int]] = {}
    wait_counts: dict[str, int] = {}
    retry_attempts: dict[str, int] = {}
    retry_exhaustions: dict[str, int] = {}
    gate_to_merge: list[int] = []
    merge_to_acceptance: list[int] = []
    acceptance_debt = 0
    writer_collisions = 0
    meta_events = 0
    meta_actions = 0
    exit_discoveries = 0
    budget_handoffs = 0
    redirection_incidents = 0
    redirection_multi_lane_recoveries = 0
    redirection_non_documentation_recoveries = 0

    normalized_repositories: list[tuple[str, Mapping[str, Any]]] = []
    for index, raw_repository in enumerate(repositories):
        repository = _require_mapping(raw_repository, f"repositories[{index}]")
        _require_fields(
            repository,
            _REPOSITORY_FIELDS,
            f"repositories[{index}]",
            optional=_REPOSITORY_OPTIONAL_FIELDS,
        )
        name = repository["repository"]
        if not isinstance(name, str) or _REPOSITORY_RE.fullmatch(name) is None:
            raise ValueError("repository must be a ContextualWisdomLab repository name")
        if name in seen_repositories:
            raise ValueError(f"duplicate repository: {name}")
        seen_repositories.add(name)
        branch = repository["protected_base_branch"]
        if (
            not isinstance(branch, str)
            or not branch
            or branch.startswith("/")
            or branch.endswith("/")
            or ".." in branch
            or "//" in branch
            or _BRANCH_RE.fullmatch(branch) is None
        ):
            raise ValueError("protected_base_branch is invalid")
        normalized_repositories.append((name, repository))

    for name, repository in sorted(normalized_repositories):
        lanes = _require_list(repository["lanes"], f"{name}.lanes")
        seen_lanes: set[tuple[str, str, datetime]] = set()
        for index, raw_lane in enumerate(lanes):
            lane = _require_mapping(raw_lane, f"{name}.lanes[{index}]")
            _require_fields(lane, _LANE_FIELDS, f"{name}.lanes[{index}]")
            reason = lane["reason_code"]
            sha = lane["source_head_sha"]
            observed_value = lane["observed_at"]
            if not isinstance(reason, str) or reason not in DEFER_REASON_CODES:
                raise ValueError("unknown lane reason_code")
            if not isinstance(sha, str) or _SHA_RE.fullmatch(sha) is None:
                raise ValueError("source_head_sha must be exactly 40 lowercase hex characters")
            observed = _parse_timestamp(observed_value, "observed_at")
            if observed > current:
                raise ValueError("observed_at is in the future")
            identity = (reason, sha, observed)
            if identity in seen_lanes:
                raise ValueError(f"duplicate lane identity in {name}")
            seen_lanes.add(identity)
            age = int((current - observed).total_seconds())
            if reason == "EXECUTABLE_NOW":
                executable_ages.append(age)
            else:
                deferred_ages.setdefault(reason, []).append(age)
                wait_counts[reason] = wait_counts.get(reason, 0) + 1

        retries = _require_list(repository["retries"], f"{name}.retries")
        for index, raw_retry in enumerate(retries):
            retry = _require_mapping(raw_retry, f"{name}.retries[{index}]")
            _require_fields(retry, _RETRY_FIELDS, f"{name}.retries[{index}]")
            failure_class = retry["failure_class"]
            if (
                not isinstance(failure_class, str)
                or failure_class not in TRANSIENT_FAILURE_CLASSES
            ):
                raise ValueError("unknown transient failure_class")
            attempts = _require_nonnegative_integer(retry["attempts"], "attempts")
            exhausted = retry["exhausted"]
            if not isinstance(exhausted, bool):
                raise ValueError("exhausted must be a boolean")
            retry_attempts[failure_class] = retry_attempts.get(failure_class, 0) + attempts
            if exhausted:
                retry_exhaustions[failure_class] = retry_exhaustions.get(failure_class, 0) + 1

        transitions = _require_list(repository["transitions"], f"{name}.transitions")
        for index, raw_transition in enumerate(transitions):
            transition = _require_mapping(raw_transition, f"{name}.transitions[{index}]")
            _require_fields(
                transition, _TRANSITION_FIELDS, f"{name}.transitions[{index}]"
            )
            merge_sha = transition["merge_revision_sha"]
            if not isinstance(merge_sha, str) or _SHA_RE.fullmatch(merge_sha) is None:
                raise ValueError("merge_revision_sha must be exactly 40 lowercase hex characters")
            gate = _parse_timestamp(transition["gate_clean_at"], "gate_clean_at")
            merge = _parse_timestamp(
                transition["protected_merge_at"], "protected_merge_at"
            )
            acceptance_value = transition["operational_acceptance_at"]
            acceptance = (
                None
                if acceptance_value is None
                else _parse_timestamp(acceptance_value, "operational_acceptance_at")
            )
            if gate > merge or (acceptance is not None and merge > acceptance):
                raise ValueError("transition timestamps are out of order")
            if merge > current or (acceptance is not None and acceptance > current):
                raise ValueError("transition timestamp is in the future")
            gate_to_merge.append(int((merge - gate).total_seconds()))
            if acceptance is None:
                acceptance_debt += 1
            else:
                merge_to_acceptance.append(int((acceptance - merge).total_seconds()))

        writer_collisions += _require_nonnegative_integer(
            repository["writer_collisions_avoided"], "writer_collisions_avoided"
        )
        meta_events += _require_nonnegative_integer(
            repository["meta_intermediate_events"], "meta_intermediate_events"
        )
        meta_actions += _require_nonnegative_integer(
            repository["meta_followed_by_substantive_action"],
            "meta_followed_by_substantive_action",
        )
        exit_discoveries += _require_nonnegative_integer(
            repository["first_exit_sweep_work_discoveries"],
            "first_exit_sweep_work_discoveries",
        )
        budget_handoffs += _require_nonnegative_integer(
            repository["run_budget_exhausted_handoffs"],
            "run_budget_exhausted_handoffs",
        )
        repository_redirections = _require_nonnegative_integer(
            repository.get("user_redirection_incidents", 0),
            "user_redirection_incidents",
        )
        repository_multi_lane = _require_nonnegative_integer(
            repository.get("user_redirection_multi_lane_recoveries", 0),
            "user_redirection_multi_lane_recoveries",
        )
        repository_non_documentation = _require_nonnegative_integer(
            repository.get("user_redirection_non_documentation_recoveries", 0),
            "user_redirection_non_documentation_recoveries",
        )
        if repository_multi_lane > repository_redirections:
            raise ValueError(
                "user_redirection_multi_lane_recoveries cannot exceed incidents"
            )
        if repository_non_documentation > repository_redirections:
            raise ValueError(
                "user_redirection_non_documentation_recoveries cannot exceed incidents"
            )
        redirection_incidents += repository_redirections
        redirection_multi_lane_recoveries += repository_multi_lane
        redirection_non_documentation_recoveries += repository_non_documentation

    return {
        "schema": SCHEMA,
        "generated_at": _format_timestamp(current),
        "repository_count": len(repositories),
        "oldest_executable_lane_age_seconds": max(executable_ages, default=None),
        "deferred_lane_age_seconds_by_reason": {
            reason: max(ages) for reason, ages in sorted(deferred_ages.items())
        },
        "wait_counts_by_reason": dict(sorted(wait_counts.items())),
        "transient_retry_attempts_by_class": dict(sorted(retry_attempts.items())),
        "transient_retry_exhaustions_by_class": dict(
            sorted(retry_exhaustions.items())
        ),
        "writer_collisions_avoided": writer_collisions,
        "gate_clean_to_protected_merge_seconds": sorted(gate_to_merge),
        "protected_merge_to_acceptance_seconds": sorted(merge_to_acceptance),
        "operational_acceptance_debt_count": acceptance_debt,
        "meta_intermediate_events": meta_events,
        "meta_followed_by_substantive_action": meta_actions,
        "first_exit_sweep_work_discoveries": exit_discoveries,
        "run_budget_exhausted_handoffs": budget_handoffs,
        "user_redirection_incidents": redirection_incidents,
        "user_redirection_multi_lane_recoveries": redirection_multi_lane_recoveries,
        "user_redirection_non_documentation_recoveries": (
            redirection_non_documentation_recoveries
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Read bounded local evidence and print one canonical JSON receipt."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--now", help="Optional UTC RFC 3339 observation time")
    arguments = parser.parse_args(argv)
    observed_now = (
        None if arguments.now is None else _parse_timestamp(arguments.now, "now")
    )
    payload = _load_strict_json(arguments.input)
    receipt = build_receipt(_require_mapping(payload, "payload"), now=observed_now)
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI wrapper
    raise SystemExit(main())
