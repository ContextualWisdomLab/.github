#!/usr/bin/env python3
"""Apply reviewed npm workspace resolver cleanup and remove this helper."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESOLVER = ROOT / "scripts/ci/npm_workspace_install_root.py"
MAIN_TEST = ROOT / "tests/test_npm_workspace_install_root.py"
HARDENING_TEST = ROOT / "tests/test_npm_workspace_install_root_hardening.py"
SUPPORT = ROOT / "tests/npm_workspace_test_support.py"
SELF = ROOT / "scripts/ci/finalize_npm_workspace_review_feedback.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace exactly one reviewed fragment and fail closed on branch drift."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_resolver(text: str) -> str:
    """Extract the cached matcher and simplify ancestor traversal."""
    old_matcher = '''def _is_declared_workspace(relative_package: PurePosixPath, patterns: list[str]) -> bool:
    """Return whether a path fully matches one anchored workspace pattern."""
    path_parts = relative_package.parts

    for pattern in patterns:
        pattern_parts = tuple(pattern.split("/"))

        @lru_cache(maxsize=None)
        def matches(path_index: int, pattern_index: int) -> bool:
            """Match anchored single-segment globs and recursive ``**`` tokens."""
            if pattern_index == len(pattern_parts):
                return path_index == len(path_parts)
            token = pattern_parts[pattern_index]
            if token == "**":
                return matches(path_index, pattern_index + 1) or (
                    path_index < len(path_parts)
                    and matches(path_index + 1, pattern_index)
                )
            if path_index >= len(path_parts):
                return False
            return fnmatch.fnmatchcase(path_parts[path_index], token) and matches(
                path_index + 1,
                pattern_index + 1,
            )

        if matches(0, 0):
            return True
    return False
'''
    new_matcher = '''@lru_cache(maxsize=4096)
def _segments_match(
    path_parts: tuple[str, ...],
    pattern_parts: tuple[str, ...],
) -> bool:
    """Match anchored workspace path segments, including recursive ``**`` tokens."""
    if not pattern_parts:
        return not path_parts
    token = pattern_parts[0]
    if token == "**":
        return _segments_match(path_parts, pattern_parts[1:]) or (
            bool(path_parts) and _segments_match(path_parts[1:], pattern_parts)
        )
    if not path_parts:
        return False
    return fnmatch.fnmatchcase(path_parts[0], token) and _segments_match(
        path_parts[1:],
        pattern_parts[1:],
    )


def _is_declared_workspace(relative_package: PurePosixPath, patterns: list[str]) -> bool:
    """Return whether a path fully matches one anchored workspace pattern."""
    path_parts = relative_package.parts
    return any(
        _segments_match(path_parts, tuple(pattern.split("/"))) for pattern in patterns
    )
'''
    text = replace_once(text, old_matcher, new_matcher, "cached workspace matcher")
    return replace_once(
        text,
        '''        parent = candidate.parent
        candidate = parent if parent != PurePosixPath("") else PurePosixPath(".")
''',
        '''        candidate = candidate.parent
''',
        "ancestor traversal",
    )


def support_module() -> str:
    """Return the shared deterministic Git/JSON fixture helpers."""
    return '''"""Shared deterministic fixtures for npm workspace resolver tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def run_git(repo: Path, *args: str) -> str:
    """Run one fixture Git command and return stripped standard output."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def write_json(path: Path, payload: object) -> None:
    """Write deterministic UTF-8 JSON for one fixture file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\\n", encoding="utf-8")


def commit_all(repo: Path, message: str = "fixture") -> str:
    """Commit every fixture path and return the exact revision SHA."""
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", message)
    return run_git(repo, "rev-parse", "HEAD")
'''


def patch_main_test(text: str) -> str:
    """Reuse shared helpers and depend directly on pathlib's public type."""
    text = replace_once(text, "import subprocess\n", "", "main subprocess import")
    text = replace_once(
        text,
        "from pathlib import Path\n",
        "from pathlib import Path, PurePosixPath\n",
        "main pathlib import",
    )
    text = replace_once(
        text,
        """from scripts.ci.npm_workspace_install_root import ResolutionError, resolve_install_root


def _git(repo: Path, *args: str) -> str:
    """Run one fixture Git command and return stripped stdout."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


""",
        """from scripts.ci.npm_workspace_install_root import ResolutionError, resolve_install_root
from tests.npm_workspace_test_support import (
    commit_all as _commit,
    run_git as _git,
    write_json as _write_json,
)


""",
        "main shared git helper import",
    )
    text = replace_once(
        text,
        """def _write_json(path: Path, payload: object) -> None:
    """Write deterministic JSON for one test fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _commit(repo: Path, message: str = "fixture") -> str:
    """Commit all fixture files and return the exact commit SHA."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


""",
        "",
        "main shared JSON and commit helpers",
    )
    return replace_once(
        text,
        '            module.PurePosixPath("package.json"),',
        '            PurePosixPath("package.json"),',
        "direct PurePosixPath use",
    )


def patch_hardening_test(text: str) -> str:
    """Reuse shared helpers and remove the platform-specific external deletion."""
    text = replace_once(text, "import subprocess\n", "import shutil\n", "hardening imports")
    text = replace_once(
        text,
        """from scripts.ci.npm_workspace_install_root import ResolutionError, resolve_install_root


def _git(repo: Path, *args: str) -> str:
    """Run one fixture Git command and return stripped standard output."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


""",
        """from scripts.ci.npm_workspace_install_root import ResolutionError, resolve_install_root
from tests.npm_workspace_test_support import (
    commit_all as _commit,
    run_git as _git,
    write_json as _write_json,
)


""",
        "hardening shared git helper import",
    )
    text = replace_once(
        text,
        """def _write_json(path: Path, payload: object) -> None:
    """Write deterministic UTF-8 JSON for a fixture file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _commit(repo: Path, message: str = "fixture") -> str:
    """Commit every fixture path and return the exact revision SHA."""
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


""",
        "",
        "hardening shared JSON and commit helpers",
    )
    return replace_once(
        text,
        '    subprocess.run(["rm", "-rf", str(repo / "apps")], check=True)\n',
        '    shutil.rmtree(repo / "apps")\n',
        "portable fixture deletion",
    )


def main() -> int:
    """Prepare every file before publishing the reviewed cleanup atomically."""
    if SUPPORT.exists():
        raise RuntimeError("shared npm workspace test support already exists")
    resolver = patch_resolver(RESOLVER.read_text(encoding="utf-8"))
    main_test = patch_main_test(MAIN_TEST.read_text(encoding="utf-8"))
    hardening_test = patch_hardening_test(HARDENING_TEST.read_text(encoding="utf-8"))

    RESOLVER.write_text(resolver, encoding="utf-8")
    MAIN_TEST.write_text(main_test, encoding="utf-8")
    HARDENING_TEST.write_text(hardening_test, encoding="utf-8")
    SUPPORT.write_text(support_module(), encoding="utf-8")
    SELF.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
