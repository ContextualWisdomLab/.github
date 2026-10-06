#!/usr/bin/env python3
"""Admit a release commit only on a protected production branch lineage.

The repository default branch is the control plane that dispatches the
caller workflow. It is production authority only for GitHub Flow, where
that default branch is protected ``main`` or ``master``. Git Flow
repositories whose default branch is ``develop`` must name a protected
``main`` or ``master`` and the release commit must be an ancestor of that
branch tip. Develop-only ancestry is rejected. An unprotected production
branch fails closed.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

PRODUCTION_BRANCH_NAMES = frozenset({"main", "master"})
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


class ReleaseBranchAuthorityError(RuntimeError):
    """Fail-closed release admission failure."""


def _require_branch_name(name: str, *, role: str) -> str:
    """Reject empty, traversal, or multi-component ref names."""

    if (
        not name
        or name.startswith(("/", "-", "."))
        or ".." in name
        or "@{" in name
        or _BRANCH_RE.fullmatch(name) is None
    ):
        raise ReleaseBranchAuthorityError(f"{role} is not a single safe ref component")
    return name


def resolve_production_branch(default_branch: str, production_branch: str) -> str:
    """Return ``main`` or ``master`` for this repository's release authority.

    An empty ``production_branch`` uses the default branch when that default
    is already ``main`` or ``master``. Any other default, including
    ``develop``, fails closed until the caller names ``main`` or ``master``.
    """

    default_name = _require_branch_name(default_branch, role="default branch")
    requested = production_branch
    if requested:
        production_name = _require_branch_name(requested, role="production branch")
        if production_name not in PRODUCTION_BRANCH_NAMES:
            raise ReleaseBranchAuthorityError("production branch must be main or master")
        return production_name
    if default_name in PRODUCTION_BRANCH_NAMES:
        return default_name
    raise ReleaseBranchAuthorityError(
        "production branch authority is required when the default branch is not main or master"
    )


def admit_protected_production_lineage(
    *,
    production_branch: str,
    release_commit: str,
    production_tip: str,
    production_protected: bool,
    release_is_ancestor_of_production_tip: bool,
) -> None:
    """Admit ``release_commit`` when it is on a protected production tip."""

    if production_branch not in PRODUCTION_BRANCH_NAMES:
        raise ReleaseBranchAuthorityError("production branch must be main or master")
    if _SHA_RE.fullmatch(release_commit) is None or _SHA_RE.fullmatch(production_tip) is None:
        raise ReleaseBranchAuthorityError(
            "release_commit must be a canonical 40-character lowercase SHA-1"
        )
    if type(production_protected) is not bool:
        raise ReleaseBranchAuthorityError("production branch protection status is not a boolean")
    if not production_protected:
        raise ReleaseBranchAuthorityError("production branch is not protected")
    if not release_is_ancestor_of_production_tip:
        raise ReleaseBranchAuthorityError(
            "release commit must be an ancestor of the protected production branch"
        )


def production_remote_tip(repo: Path, production_branch: str) -> str:
    """Return ``refs/remotes/origin/<production_branch>`` as a full SHA."""

    if production_branch not in PRODUCTION_BRANCH_NAMES:
        raise ReleaseBranchAuthorityError("production branch must be main or master")
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "rev-parse",
            "--verify",
            f"refs/remotes/origin/{production_branch}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    tip = completed.stdout.strip()
    if completed.returncode != 0 or _SHA_RE.fullmatch(tip) is None:
        raise ReleaseBranchAuthorityError("production tip is unavailable")
    return tip


def release_is_ancestor(repo: Path, release_commit: str, production_tip: str) -> bool:
    """Return whether ``release_commit`` is contained in ``production_tip``."""

    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "merge-base",
            "--is-ancestor",
            release_commit,
            production_tip,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def evaluate_release_authority(
    repo: Path,
    *,
    default_branch: str,
    production_branch: str,
    release_commit: str,
    production_protected: bool,
) -> str:
    """Resolve production authority and admit ``release_commit`` against its tip."""

    resolved = resolve_production_branch(default_branch, production_branch)
    tip = production_remote_tip(repo, resolved)
    admit_protected_production_lineage(
        production_branch=resolved,
        release_commit=release_commit,
        production_tip=tip,
        production_protected=production_protected,
        release_is_ancestor_of_production_tip=release_is_ancestor(repo, release_commit, tip),
    )
    return resolved


def _build_parser() -> argparse.ArgumentParser:
    """Build the workflow CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--default-branch", required=True)
    parser.add_argument("--production-branch", default="")
    parser.add_argument("--release-commit", default="")
    parser.add_argument("--protected", choices=("true", "false"))
    parser.add_argument("--repo", default=".")
    parser.add_argument("--resolve-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Resolve or admit a release. Failures print one line on stderr."""

    args = _build_parser().parse_args(argv)
    try:
        if args.resolve_only:
            resolved = resolve_production_branch(args.default_branch, args.production_branch)
        else:
            if args.protected is None:
                raise ReleaseBranchAuthorityError(
                    "production branch protection status is not a boolean"
                )
            resolved = evaluate_release_authority(
                Path(args.repo),
                default_branch=args.default_branch,
                production_branch=args.production_branch,
                release_commit=args.release_commit,
                production_protected=args.protected == "true",
            )
    except ReleaseBranchAuthorityError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(resolved)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
