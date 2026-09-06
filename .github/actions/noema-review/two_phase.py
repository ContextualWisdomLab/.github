#!/usr/bin/env python3
"""Prepare and publish Noema verdicts across short-lived reviewer credentials.

The model phase can legitimately outlive a one-hour GitHub App installation
credential. This trusted helper therefore seals the already validated model
verdict to a runner-local file, then a later workflow step reopens that file
only after the reviewer credential has been refreshed. Publication always
re-fetches the live pull request and verifies its exact head and base before
submitting any review evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ci import noema_review_gate as gate  # noqa: E402

ENVELOPE_SCHEMA_VERSION = 1
MAX_ENVELOPE_BYTES = 2 * 1024 * 1024
CANONICAL_APP_TOKEN_SOURCE = "noema-review-github-app"
REFRESHED_APP_TOKEN_SOURCE = "noema-review-github-app-refresh"


def _canonical_head(value: str) -> str:
    """Return one canonical lowercase Git SHA or fail closed."""
    head = value.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise RuntimeError("Noema two-phase handoff requires a canonical 40-character Git SHA")
    return head


def _canonical_base(pull_request: dict[str, Any]) -> str:
    """Return the exact base commit that defined the reviewed diff/context."""
    base = str(pull_request.get("baseRefOid") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise RuntimeError("Noema two-phase handoff requires a canonical 40-character base SHA")
    return base


def _current_actor(*, allow_refreshed_app: bool) -> str:
    """Validate the refresh marker through the existing canonical App gate."""
    token_source = os.environ.get("NOEMA_REVIEW_TOKEN_SOURCE")
    if not (
        allow_refreshed_app
        and token_source == REFRESHED_APP_TOKEN_SOURCE
    ):
        return gate.current_actor()

    os.environ["NOEMA_REVIEW_TOKEN_SOURCE"] = CANONICAL_APP_TOKEN_SOURCE
    try:
        return gate.current_actor()
    finally:
        os.environ["NOEMA_REVIEW_TOKEN_SOURCE"] = token_source


def _reviewer_actor(*, allow_refreshed_app: bool = False) -> str:
    """Return a verified independent reviewer actor for the active token."""
    actor = _current_actor(allow_refreshed_app=allow_refreshed_app)
    if not actor:
        raise RuntimeError("Noema reviewer identity could not be verified")
    if actor in gate.PRIMARY_REVIEW_AUTHORS:
        raise RuntimeError(
            f"Current token actor {actor!r} is already a primary review actor; "
            "Noema requires an independent reviewer credential."
        )
    return actor


def _write_envelope(path: Path, payload: dict[str, Any]) -> None:
    """Create one private, non-following runner-local verdict envelope."""
    encoded = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
    if len(encoded) > MAX_ENVELOPE_BYTES:
        raise RuntimeError("Noema verdict envelope exceeds the bounded handoff size")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
            raise RuntimeError("Noema verdict envelope target is not a private regular file")
        view = memoryview(encoded)
        written = 0
        while written < len(view):
            count = os.write(fd, view[written:])
            if count <= 0:
                raise RuntimeError("Noema verdict envelope write made no forward progress")
            written += count
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        path.unlink(missing_ok=True)
        raise
    else:
        os.close(fd)


def _read_envelope(path: Path) -> dict[str, Any]:
    """Read and validate one sealed runner-local verdict envelope."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError("Noema verdict envelope is unavailable for publication") from exc
    try:
        file_stat = os.fstat(fd)
        if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
            raise RuntimeError("Noema verdict envelope is not a regular single-link file")
        if file_stat.st_mode & 0o077:
            raise RuntimeError("Noema verdict envelope permissions are broader than owner-only")
        if file_stat.st_size <= 0 or file_stat.st_size > MAX_ENVELOPE_BYTES:
            raise RuntimeError("Noema verdict envelope size is outside the bounded contract")
        chunks: list[bytes] = []
        remaining = MAX_ENVELOPE_BYTES + 1
        while remaining > 0:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_ENVELOPE_BYTES:
            raise RuntimeError("Noema verdict envelope exceeded the bounded read limit")
    finally:
        os.close(fd)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Noema verdict envelope is malformed") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Noema verdict envelope root must be an object")
    return payload


def _model_work_eligibility(
    repo: str,
    number: int,
    expected_head: str,
) -> tuple[str, dict[str, Any], str, str] | None:
    """Return the validated review identity when this head still needs model work."""
    expected = _canonical_head(expected_head)
    pull_request = gate.fetch_pr(repo, number)
    try:
        gate.require_expected_head(pull_request, expected)
    except RuntimeError:
        print("Pull request is closed or stale; Noema verdict preparation skipped.")
        return None
    expected_base = _canonical_base(pull_request)
    actor = _reviewer_actor()
    if pull_request.get("isDraft"):
        print("PR is draft; Noema verdict preparation skipped.")
        return None
    if gate.existing_noema_review(pull_request, actor):
        print("Current head already has a Noema review; verdict preparation skipped.")
        return None
    return expected, pull_request, expected_base, actor


def admit_model_work(repo: str, number: int, expected_head: str, path: Path) -> int:
    """Record whether the current review needs the expensive model sidecar."""
    eligibility = _model_work_eligibility(repo, number, expected_head)
    if eligibility is None:
        return 0
    expected, _pull_request, expected_base, _actor = eligibility
    _write_envelope(
        path,
        {
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "repository": repo,
            "pull_request_number": number,
            "expected_head": expected,
            "expected_base": expected_base,
        },
    )
    return 0


def prepare_verdict(repo: str, number: int, expected_head: str, path: Path) -> int:
    """Run model review and seal its verdict without publishing GitHub evidence."""
    eligibility = _model_work_eligibility(repo, number, expected_head)
    if eligibility is None:
        return 0
    expected, pull_request, expected_base, _actor = eligibility

    diff, truncated = gate.fetch_diff(repo, number)
    changed_files = gate.fetch_changed_files(repo, number)
    changed_paths = tuple(file_path for file_path, _status in changed_files)
    review_context = gate.build_review_context(repo, number, pull_request, changed_files)
    verdict = gate.call_llm(
        repo,
        number,
        pull_request,
        diff,
        truncated,
        expected,
        review_context,
        changed_paths,
    )

    _write_envelope(
        path,
        {
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "repository": repo,
            "pull_request_number": number,
            "expected_head": expected,
            "expected_base": expected_base,
            "verdict": verdict,
        },
    )
    print(
        f"Prepared Noema verdict for {repo}#{number} at head {expected} / base {expected_base}; "
        "publication is deferred."
    )
    return 0


def publish_verdict(repo: str, number: int, expected_head: str, path: Path) -> int:
    """Publish a prepared verdict only with fresh exact-head/base reviewer authority."""
    expected = _canonical_head(expected_head)
    try:
        payload = _read_envelope(path)
        required_keys = {
            "schema_version",
            "repository",
            "pull_request_number",
            "expected_head",
            "expected_base",
            "verdict",
        }
        if set(payload) != required_keys:
            raise RuntimeError("Noema verdict envelope fields do not match the trusted schema")
        if payload["schema_version"] != ENVELOPE_SCHEMA_VERSION:
            raise RuntimeError("Noema verdict envelope schema version is unsupported")
        if payload["repository"] != repo or payload["pull_request_number"] != number:
            raise RuntimeError("Noema verdict envelope target identity does not match publication")
        if payload["expected_head"] != expected:
            raise RuntimeError("Noema verdict envelope head does not match publication")
        expected_base = str(payload["expected_base"]).strip().lower()
        if not re.fullmatch(r"[0-9a-f]{40}", expected_base):
            raise RuntimeError("Noema verdict envelope base does not contain a canonical Git SHA")
        verdict = payload["verdict"]
        if not isinstance(verdict, dict):
            raise RuntimeError("Noema verdict envelope verdict must be an object")

        current_pull_request = gate.fetch_pr(repo, number)
        try:
            gate.require_expected_head(current_pull_request, expected)
        except RuntimeError:
            print("Pull request closed or advanced after model review; prepared verdict was not published.")
            return 0
        if _canonical_base(current_pull_request) != expected_base:
            print("Pull request base advanced after model review; stale prepared verdict was not published.")
            return 0
        actor = _reviewer_actor(allow_refreshed_app=True)
        if current_pull_request.get("isDraft"):
            print("PR became draft after model review; prepared verdict was not published.")
            return 0
        if gate.existing_noema_review(current_pull_request, actor):
            print("Current head already has a Noema review; duplicate publication skipped.")
            return 0
        gate.submit_review(repo, number, current_pull_request, actor, verdict)
        return 0
    finally:
        path.unlink(missing_ok=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the trusted two-phase handoff command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--expected-head", required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--admit-model-file", type=Path)
    modes.add_argument("--prepare-verdict-file", type=Path)
    modes.add_argument("--publish-verdict-file", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Execute the selected prepare or publication phase."""
    args = parse_args(argv)
    if args.pr_number <= 0:
        raise SystemExit("--pr-number must be positive")
    if args.admit_model_file is not None:
        return admit_model_work(args.repo, args.pr_number, args.expected_head, args.admit_model_file)
    if args.prepare_verdict_file is not None:
        return prepare_verdict(args.repo, args.pr_number, args.expected_head, args.prepare_verdict_file)
    return publish_verdict(args.repo, args.pr_number, args.expected_head, args.publish_verdict_file)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
