#!/usr/bin/env python3
"""Bind one QSR job's checkout, cwd, output, and cleanup to one source and run."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

WORKFLOW_SOURCE = "${{ github.event.pull_request.head.sha || github.sha }}"
WORKFLOW_CLEANUP_PATH = (
    "qsr-job/${{ github.job }}/${{ github.run_id }}/${{ github.run_attempt }}/"
    + WORKFLOW_SOURCE
)
WORKFLOW_CHECKOUT_PATH = WORKFLOW_CLEANUP_PATH + "/checkout"
WORKFLOW_OUTPUT_PATH = WORKFLOW_CLEANUP_PATH + "/output"

_JOB = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62})")
_RUN = re.compile(r"[1-9][0-9]{0,19}")
_HEAD = re.compile(r"[0-9a-f]{40}")
_ROLES = ("checkout", "cwd", "output", "cleanup")


class SourceRunPathError(ValueError):
    """A checkout, cwd, output, or cleanup path is not bound to this source and run."""


def _require_identity(job: str, source: str, run_id: str, run_attempt: str) -> None:
    """Reject a job, source, or run identity that can escape its own path."""
    if _JOB.fullmatch(job) is None:
        raise SourceRunPathError("invalid job identity")
    if _HEAD.fullmatch(source) is None:
        raise SourceRunPathError("invalid source identity")
    if _RUN.fullmatch(run_id) is None:
        raise SourceRunPathError("invalid run identity")
    if _RUN.fullmatch(run_attempt) is None:
        raise SourceRunPathError("invalid run identity")


def relative_paths(job: str, source: str, run_id: str, run_attempt: str) -> dict[str, str]:
    """Return workspace-relative paths for one job, source HEAD, and run attempt."""
    _require_identity(job, source, run_id, run_attempt)
    cleanup = f"qsr-job/{job}/{run_id}/{run_attempt}/{source}"
    checkout = f"{cleanup}/checkout"
    return {
        "checkout": checkout,
        "cwd": checkout,
        "output": f"{cleanup}/output",
        "cleanup": cleanup,
    }


def _inside(path: Path, parent: Path) -> bool:
    """Return whether resolved path is parent or a descendant of parent."""
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def bind_source_run_paths(
    workspace: Path,
    *,
    job: str,
    source: str,
    run_id: str,
    run_attempt: str,
    evidence_roots: tuple[Path, ...] = (),
    tool_roots: tuple[Path, ...] = (),
) -> dict[str, Path]:
    """Resolve the four paths under workspace and refuse evidence or tool mixing."""
    relative = relative_paths(job, source, run_id, run_attempt)
    root = Path(workspace)
    if root.is_symlink() or not root.is_dir():
        raise SourceRunPathError("workspace is not a real directory")
    paths = {role: root / relative[role] for role in _ROLES}
    foreigners = tuple(evidence_roots) + tuple(tool_roots)
    for foreign in foreigners:
        if not foreign.is_absolute():
            raise SourceRunPathError("evidence or tool directory must be absolute")
        for path in paths.values():
            if _inside(path, foreign) or _inside(foreign, path):
                raise SourceRunPathError("path mixes with evidence or tool directory")
    return paths


def prepare_source_run_paths(paths: dict[str, Path]) -> None:
    """Create this run's cleanup root and output directory, refusing existing nodes."""
    for key in ("cleanup", "output"):
        path = paths[key]
        if path.is_symlink() or path.exists():
            raise SourceRunPathError(f"{key} already exists")
    paths["cleanup"].parent.mkdir(parents=True, exist_ok=True)
    os.mkdir(paths["cleanup"], 0o700)
    os.mkdir(paths["output"], 0o700)
    os.chmod(paths["cleanup"], 0o700)
    os.chmod(paths["output"], 0o700)


def main(argv: list[str] | None = None) -> int:
    """Print the four bound paths as JSON. Return 1 when the contract refuses."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--tool", type=Path, action="append", default=[])
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args(argv)
    try:
        paths = bind_source_run_paths(
            args.workspace,
            job=args.job,
            source=args.source,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            evidence_roots=tuple(args.evidence),
            tool_roots=tuple(args.tool),
        )
        if args.prepare:
            prepare_source_run_paths(paths)
    except SourceRunPathError as exc:
        print(f"SRC03-PATH-001: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps({role: str(paths[role]) for role in _ROLES}, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
