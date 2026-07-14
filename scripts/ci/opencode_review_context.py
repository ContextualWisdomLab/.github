"""Resolve bounded OpenCode review context from a GitHub event payload."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path


CONTEXT_VALIDATORS = {
    "GH_REPOSITORY": re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z"),
    "PR_NUMBER": re.compile(r"[1-9][0-9]*\Z"),
    "PR_BASE_SHA": re.compile(r"[0-9a-fA-F]{40}\Z"),
    "PR_HEAD_SHA": re.compile(r"[0-9a-fA-F]{40}\Z"),
    "HEAD_SHA": re.compile(r"[0-9a-fA-F]{40}\Z"),
}


def load_event(path: Path) -> Mapping[str, object]:
    """Load a GitHub event payload as a JSON object."""
    try:
        event = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error::Could not read GitHub event payload for OpenCode review context: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if not isinstance(event, dict):
        print("::error::GitHub event payload for OpenCode review context was not a JSON object.", file=sys.stderr)
        raise SystemExit(1)
    return event


def object_value(value: object) -> Mapping[str, object]:
    """Return object mappings and coerce every other JSON value to an empty object."""
    return value if isinstance(value, dict) else {}


def resolve_context(event: Mapping[str, object], default_repository: str) -> dict[str, str]:
    """Resolve and validate the OpenCode review context values."""
    inputs = object_value(event.get("inputs"))
    client_payload = object_value(event.get("client_payload"))
    pull_request = object_value(event.get("pull_request"))
    base = object_value(pull_request.get("base"))
    head = object_value(pull_request.get("head"))
    base_repo = object_value(base.get("repo"))
    values = {
        "GH_REPOSITORY": str(
            base_repo.get("full_name")
            or inputs.get("target_repository")
            or client_payload.get("target_repository")
            or default_repository
            or ""
        ).strip(),
        "PR_NUMBER": str(
            pull_request.get("number")
            or inputs.get("pr_number")
            or client_payload.get("pr_number")
            or ""
        ).strip(),
        "PR_BASE_SHA": str(
            base.get("sha")
            or inputs.get("pr_base_sha")
            or client_payload.get("pr_base_sha")
            or ""
        ).strip(),
        "PR_HEAD_SHA": str(
            head.get("sha")
            or inputs.get("pr_head_sha")
            or client_payload.get("pr_head_sha")
            or ""
        ).strip(),
    }
    values["HEAD_SHA"] = values["PR_HEAD_SHA"]
    for name, pattern in CONTEXT_VALIDATORS.items():
        if not pattern.fullmatch(values[name]):
            print(f"::error::Invalid OpenCode review context value for {name}.", file=sys.stderr)
            raise SystemExit(1)
    # Free-text PR metadata for the review-language signal. It is arbitrary
    # author text, so it is not pattern-validated; it stays shell-safe because
    # write_shell_exports quotes every value with shlex.quote and consumers only
    # grep it as data. Sourcing this here (from the event payload, no API call)
    # keeps the preferred-language marker present even when gh pr view is
    # throttled, so the review-language contract can no longer fail open.
    values["PR_TITLE_FOR_LANGUAGE"] = str(pull_request.get("title") or "").strip()
    values["PR_BODY_FOR_LANGUAGE"] = str(pull_request.get("body") or "").strip()
    return values


def write_shell_exports(path: Path, values: Mapping[str, str]) -> None:
    """Write validated values as shell export statements."""
    path.write_text(
        "".join(f"export {name}={shlex.quote(value)}\n" for name, value in values.items()),
        encoding="utf-8",
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-path", required=True, type=Path)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--default-repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Resolve context files for the OpenCode review workflow."""
    args = parse_args(argv)
    event = load_event(args.event_path)
    values = resolve_context(event, args.default_repository)
    write_shell_exports(args.env_file, values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
