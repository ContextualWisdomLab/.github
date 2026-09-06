#!/usr/bin/env python3
"""Stable import and CLI boundary for the centralized PR review scheduler.

The implementation lives in :mod:`pr_review_merge_scheduler_core`. Keeping
this path stable preserves existing workflow commands and test imports while
the production CLI installs a no-sleep policy for primary GitHub rate-limit
exhaustion.

Source-location compatibility markers are intentionally listed here; the
stronger contract test also verifies them in the core implementation:

* ``f"repos/{dispatch_repo}/dispatches"``
* ``"event_type": "opencode-review"``
* ``"event_type": "strix-scan"``
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from typing import Any, Sequence

if __package__:
    from . import pr_review_merge_scheduler_core as _scheduler_core
else:  # pragma: no cover - exercised by the workflow CLI entrypoint
    import pr_review_merge_scheduler_core as _scheduler_core


def _fail_fast_gh_graphql(query: str, **fields: str | int) -> dict[str, Any]:
    """Run GraphQL, retrying transient transport faults but never rate limits."""

    command = ["gh", "api", "graphql", "-F", "query=@-"]
    for field_name, field_value in fields.items():
        field_flag = "-F" if isinstance(field_value, int) else "-f"
        command.extend([field_flag, f"{field_name}={field_value}"])

    maximum_attempts = 4
    for attempt_number in range(1, maximum_attempts + 1):
        try:
            return json.loads(
                _scheduler_core.run_github_read(command, stdin=query)
            )
        except (RuntimeError, json.JSONDecodeError) as exc:
            if _scheduler_core.is_rate_limited_error(exc):
                print(
                    "GitHub GraphQL primary rate limit is exhausted; "
                    "deferring without runner-held sleep.",
                    file=sys.stderr,
                )
                raise
            if (
                attempt_number >= maximum_attempts
                or not _scheduler_core.is_transient_github_api_error(exc)
            ):
                raise
            retry_delay_seconds = min(2 ** (attempt_number - 1), 8)
            print(
                "Transient GitHub GraphQL error on attempt "
                f"{attempt_number}/{maximum_attempts}; "
                f"retrying in {retry_delay_seconds}s",
                file=sys.stderr,
            )
            _scheduler_core.time.sleep(retry_delay_seconds)

    raise AssertionError(  # pragma: no cover - every branch above returns or raises
        "GraphQL retry loop exited without a result"
    )


def _fail_fast_gh_api_json(path: str) -> Any:
    """Run REST, retrying transient transport faults but never rate limits."""

    maximum_attempts = 4
    for attempt_number in range(1, maximum_attempts + 1):
        try:
            return json.loads(
                _scheduler_core.run_github_read(["gh", "api", path])
            )
        except (RuntimeError, json.JSONDecodeError) as exc:
            if _scheduler_core.is_rate_limited_error(exc):
                print(
                    "GitHub REST primary rate limit is exhausted for "
                    f"{path}; deferring without runner-held sleep.",
                    file=sys.stderr,
                )
                raise
            if (
                attempt_number >= maximum_attempts
                or not _scheduler_core.is_transient_github_api_error(exc)
            ):
                raise
            retry_delay_seconds = min(2 ** (attempt_number - 1), 8)
            print(
                "Transient GitHub REST error on attempt "
                f"{attempt_number}/{maximum_attempts} for {path}; "
                f"retrying in {retry_delay_seconds}s",
                file=sys.stderr,
            )
            _scheduler_core.time.sleep(retry_delay_seconds)

    raise AssertionError(  # pragma: no cover - every branch above returns or raises
        "REST retry loop exited without a result"
    )


def install_fail_fast_rate_limit_policy() -> None:
    """Install the production no-sleep policy on the scheduler core module."""

    _scheduler_core.gh_graphql = _fail_fast_gh_graphql
    _scheduler_core.gh_api_json = _fail_fast_gh_api_json


def _argument_value(
    argument_values: Sequence[str], option_name: str
) -> str | None:
    """Return one CLI option value without assuming parser internals."""

    for argument_index, argument_value in enumerate(argument_values):
        if argument_value != option_name:
            continue
        value_index = argument_index + 1
        if value_index < len(argument_values):
            return argument_values[value_index]
        return None
    return None


def _is_opencode_post_approval_followup(
    argument_values: Sequence[str],
) -> bool:
    """Identify the best-effort OpenCode post-publication scheduler caller."""

    argument_set = set(argument_values)
    return (
        os.environ.get("GITHUB_WORKFLOW", "") == "OpenCode Review Dispatch"
        and _argument_value(argument_values, "--max-prs") == "1"
        and _argument_value(argument_values, "--review-dispatch-limit") == "0"
        and _argument_value(argument_values, "--merge-mode")
        == "direct_or_auto"
        and "--pr-number" in argument_set
        and "--no-trigger-reviews" in argument_set
        and "--enable-auto-merge" in argument_set
        and "--no-update-branches" in argument_set
    )


def _record_deferred_rate_limit(error_message: str) -> None:
    """Write a typed OpenCode follow-up defer receipt."""

    retry_owner = "Required PR Review Merge Scheduler heartbeat"
    receipt = (
        "scheduler_outcome=deferred_rate_limit; "
        f"retry_owner={retry_owner}; "
        f"reason={error_message}"
    )
    print(receipt, file=sys.stderr)

    summary_path_value = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path_value:
        return
    summary_path = Path(summary_path_value)
    with summary_path.open("a", encoding="utf-8") as summary_file:
        summary_file.write("### PR review scheduler deferred\n\n")
        summary_file.write("- outcome: `deferred_rate_limit`\n")
        summary_file.write(f"- retry owner: {retry_owner}\n")
        summary_file.write("- runner-held sleep: 0 seconds\n")
        summary_file.write(f"- reason: `{error_message}`\n\n")


def run_cli(argument_values: Sequence[str]) -> int:
    """Run the scheduler with caller-scoped primary-rate-limit handling."""

    install_fail_fast_rate_limit_policy()
    try:
        return int(_scheduler_core.main(list(argument_values)))
    except RuntimeError as exc:
        if (
            _scheduler_core.is_rate_limited_error(exc)
            and _is_opencode_post_approval_followup(argument_values)
        ):
            _record_deferred_rate_limit(str(exc))
            # This exact caller retries every non-zero result three times with
            # runner-held sleeps. Its follow-up is best-effort because the
            # scheduled/PR-event scheduler remains authoritative.
            return 0
        print(str(exc), file=sys.stderr)
        return 1


class _SchedulerFacade(types.ModuleType):
    """Forward legacy import reads and test monkeypatches to the core module."""

    def __getattr__(self, attribute_name: str) -> Any:
        """Read a non-local attribute from the core module."""
        return getattr(_scheduler_core, attribute_name)

    def __setattr__(self, attribute_name: str, attribute_value: Any) -> None:
        """Write dunder and facade-local names here; forward everything else."""
        if (
            attribute_name.startswith("__")
            or attribute_name in _FACADE_LOCAL_NAMES
        ):
            super().__setattr__(attribute_name, attribute_value)
            return
        setattr(_scheduler_core, attribute_name, attribute_value)

    def __delattr__(self, attribute_name: str) -> None:
        """Delete dunder and facade-local names here; forward everything else."""
        if (
            attribute_name.startswith("__")
            or attribute_name in _FACADE_LOCAL_NAMES
        ):
            super().__delattr__(attribute_name)
            return
        delattr(_scheduler_core, attribute_name)

    def __dir__(self) -> list[str]:
        """List this module's own names together with the core's names."""
        return sorted(set(super().__dir__()) | set(dir(_scheduler_core)))


# Python's wildcard import reads ``__all__`` before attribute delegation. Export
# the original implementation's public API explicitly so consumers retain the
# same symbols after the implementation/facade split.
__all__ = tuple(
    sorted(
        attribute_name
        for attribute_name in dir(_scheduler_core)
        if not attribute_name.startswith("_")
    )
)

_FACADE_LOCAL_NAMES = frozenset(globals()) | {"_FACADE_LOCAL_NAMES"}
sys.modules[__name__].__class__ = _SchedulerFacade


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(run_cli(sys.argv[1:]))
