"""Fail when a repository tracks paths that differ only by letter case.

Git stores paths byte-exactly, so a tree can contain both ``.jules/x.md``
and ``.Jules/x.md``. On case-insensitive filesystems (macOS APFS default,
Windows) both names resolve to one file: every fresh clone or worktree then
reports one of them as modified, ``git status`` can never be clean, and the
two blobs silently diverge (ContextualWisdomLab/fast-mlsirm#1860).

The gate lists the tracked paths of the checked-out tree, folds them with
``str.casefold`` and fails on any group with more than one distinct spelling.
It never rewrites or merges files; consolidation is a per-repository decision.

Exit codes: ``0`` no collisions, ``1`` collisions found, ``2`` the tracked path
list could not be read (fails closed: an unverified tree is not a clean tree).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

COLLISION = 1
TOOL_ERROR = 2


def find_case_collisions(paths: Iterable[str]) -> dict[str, list[str]]:
    """Return ``{folded_path: [distinct spellings...]}`` for colliding paths.

    Each path and every one of its parent directories is folded, so
    ``a/B/x`` and ``a/b/y`` collide on the directory ``a/b`` even though the
    leaf names differ.
    """
    spellings: dict[str, set[str]] = {}
    for raw in paths:
        path = raw.strip("\n")
        if not path:
            continue
        parts = path.split("/")
        for depth in range(1, len(parts) + 1):
            prefix = "/".join(parts[:depth])
            spellings.setdefault(prefix.casefold(), set()).add(prefix)
    return {key: sorted(names) for key, names in sorted(spellings.items()) if len(names) > 1}


def tracked_paths(repo_root: Path) -> list[str]:
    """Return the tracked paths of ``repo_root`` from ``git ls-files -z``."""
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        capture_output=True,
        check=True,
        shell=False,
    )
    return [entry.decode("utf-8", errors="surrogateescape") for entry in completed.stdout.split(b"\0") if entry]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; see module docstring for the exit-code contract."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="git checkout to inspect (default: .)")
    parser.add_argument("--paths-file", type=Path, help="newline-separated path list to inspect instead of git ls-files")
    args = parser.parse_args(argv)

    try:
        if args.paths_file is not None:
            paths = args.paths_file.read_text(encoding="utf-8").splitlines()
        else:
            paths = tracked_paths(args.repo_root)
    except (OSError, subprocess.CalledProcessError, UnicodeDecodeError) as exc:
        print(f"::error::tracked-path-case gate could not read the tracked path list: {exc}", file=sys.stderr)
        return TOOL_ERROR

    collisions = find_case_collisions(paths)
    if not collisions:
        print(f"tracked-path-case: {len(paths)} tracked paths, no case-only collisions.")
        return 0
    for folded, names in collisions.items():
        print(f"::error::tracked paths differ only by case: {', '.join(names)} (folded: {folded})")
    print(
        f"tracked-path-case: {len(collisions)} collision group(s). Consolidate each group into one spelling "
        "(git mv / git rm --cached) so the tree checks out cleanly on case-insensitive filesystems.",
        file=sys.stderr,
    )
    return COLLISION


if __name__ == "__main__":
    raise SystemExit(main())
