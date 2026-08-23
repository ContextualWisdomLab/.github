"""Fail closed when a stale agent patch replays a pre-merge PR tree.

An asynchronous review or autofix agent can finish after a maintainer has merged
the current base into a PR branch.  If that agent then writes its old workspace
snapshot as a new commit, Git records a valid commit whose tree silently removes
everything learned from the base merge.  Ordinary tests can still pass because
the stale snapshot also restores its old tests.

This guard inspects the PR head history, finds the newest merge commit on the
first-parent path from the supplied base, and evaluates commits made after that
merge.  It blocks, regardless of diff size:

- an exact replay of any pre-merge first-parent tree;
- targeted unmerges of base work: any path whose post-merge content reverted
  exactly to its pre-merge first-parent content, discarding what the base
  merge brought in (observed in appguardrail#297, where a stale snapshot
  reverted an accessibility wrapper and deleted its regression tests in a
  push far below the bulk thresholds);
- test regression without replacement: post-merge commits deleting test files
  or reducing declared test cases while adding no replacement test file or
  declared test case in an existing test file;
- the conservative bulk-regression signature: at least five tracked files and
  500 lines removed, with deletions at least four times additions.

Every decision is printed with the exact SHAs, diff counts, and offending
paths so the failure is actionable.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


MAX_PRE_MERGE_ANCESTORS = 200
MIN_REMOVED_FILES = 5
MIN_DELETED_LINES = 500
MIN_DELETION_RATIO = 4
MAX_LISTED_PATHS = 10
TEST_DIR_SEGMENTS = frozenset({"tests", "test", "__tests__", "spec", "specs"})
TEST_CASE_PATTERNS = {
    ".bats": re.compile(r"(?m)^\s*@test\b"),
    ".go": re.compile(
        r"(?m)^\s*func\s+(?:Test|Benchmark|Fuzz)[A-Z0-9_][A-Za-z0-9_]*\s*\("
    ),
    ".js": re.compile(r"\b(?:it|test)(?:\.(?:concurrent|each|only|skip|todo))*\s*\("),
    ".jsx": re.compile(r"\b(?:it|test)(?:\.(?:concurrent|each|only|skip|todo))*\s*\("),
    ".r": re.compile(r"\b(?:testthat::)?test_that\s*\("),
    ".rs": re.compile(
        r"#\s*\[\s*(?:[A-Za-z_][A-Za-z0-9_:]*::)?test"
        r"(?:\s*\([^]]*\))?\s*\]"
    ),
    ".ts": re.compile(r"\b(?:it|test)(?:\.(?:concurrent|each|only|skip|todo))*\s*\("),
    ".tsx": re.compile(r"\b(?:it|test)(?:\.(?:concurrent|each|only|skip|todo))*\s*\("),
}


@dataclass(frozen=True)
class ReplayEvidence:
    """History and diff evidence used to make the replay decision."""

    base_sha: str
    head_sha: str
    merge_anchor: str | None = None
    post_merge_commits: int = 0
    exact_replay_of: str | None = None
    removed_files: int = 0
    added_lines: int = 0
    deleted_lines: int = 0
    unmerged_paths: tuple[str, ...] = ()
    regressed_test_paths: tuple[str, ...] = ()
    added_test_files: int = 0
    added_test_cases: int = 0

    @property
    def suspicious_bulk_regression(self) -> bool:
        """Return whether the post-merge delta matches the bulk replay signature."""
        return (
            self.removed_files >= MIN_REMOVED_FILES
            and self.deleted_lines >= MIN_DELETED_LINES
            and self.deleted_lines >= MIN_DELETION_RATIO * max(1, self.added_lines)
        )

    @property
    def unmerges_base_work(self) -> bool:
        """Return whether any path reverted exactly to its pre-merge content."""
        return bool(self.unmerged_paths)

    @property
    def suspicious_test_regression(self) -> bool:
        """Return whether test cases were lost with no replacement test evidence."""
        return (
            bool(self.regressed_test_paths)
            and self.added_test_files == 0
            and self.added_test_cases == 0
        )

    @property
    def blocked(self) -> bool:
        """Return whether any replay, unmerge, or test-regression evidence blocks the head."""
        return (
            self.exact_replay_of is not None
            or self.unmerges_base_work
            or self.suspicious_test_regression
            or self.suspicious_bulk_regression
        )


def git_output(repo_root: Path, args: Sequence[str]) -> str:
    """Run a read-only git command and return stripped standard output."""
    command_args = list(args)
    if command_args and command_args[0] == "diff":
        # A repository-local diff.ignoreSubmodules=all setting must not hide
        # attacker-controlled gitlink changes from replay evidence.
        command_args = [
            "diff",
            "--ignore-submodules=none",
            *(
                argument
                for argument in command_args[1:]
                if argument != "--ignore-submodules"
                and not argument.startswith("--ignore-submodules=")
            ),
        ]
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *command_args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
        raise RuntimeError(f"git {command_args[0]} failed: {detail[:500]}")
    return completed.stdout.strip()


def commit_tree(repo_root: Path, commit: str) -> str:
    """Return the tree object id for a commit."""
    return git_output(repo_root, ["rev-parse", f"{commit}^{{tree}}"])


def newest_base_merge(repo_root: Path, base_sha: str, head_sha: str) -> str | None:
    """Return the newest first-parent merge descended from the supplied base."""
    output = git_output(
        repo_root,
        [
            "rev-list",
            "--first-parent",
            "--merges",
            "--ancestry-path",
            f"{base_sha}..{head_sha}",
        ],
    )
    return output.splitlines()[0] if output else None


def exact_pre_merge_tree_replay(repo_root: Path, merge_anchor: str, head_sha: str) -> str | None:
    """Return the pre-merge ancestor whose tree exactly matches the current head."""
    head_tree = commit_tree(repo_root, head_sha)
    first_parent = git_output(repo_root, ["rev-parse", f"{merge_anchor}^1"])
    ancestors = git_output(
        repo_root,
        ["rev-list", f"--max-count={MAX_PRE_MERGE_ANCESTORS}", first_parent],
    )
    for ancestor in ancestors.splitlines():
        if commit_tree(repo_root, ancestor) == head_tree:
            return ancestor
    return None


def diff_statistics(repo_root: Path, start: str, end: str) -> tuple[int, int, int]:
    """Return removed-file, added-line, and deleted-line counts for a commit range."""
    deleted_paths = git_output(
        repo_root,
        ["diff", "--name-only", "--diff-filter=D", start, end],
    )
    removed_files = len(deleted_paths.splitlines()) if deleted_paths else 0
    added_lines = 0
    deleted_lines = 0
    numstat = git_output(repo_root, ["diff", "--numstat", start, end])
    for line in numstat.splitlines():
        fields = line.split("\t", 2)
        if len(fields) < 2 or not fields[0].isdigit() or not fields[1].isdigit():
            continue
        added_lines += int(fields[0])
        deleted_lines += int(fields[1])
    return removed_files, added_lines, deleted_lines


def is_test_path(path: str) -> bool:
    """Return whether a repository path looks like an automated test file."""
    parts = path.replace("\\", "/").split("/")
    if any(part in TEST_DIR_SEGMENTS for part in parts[:-1]):
        return True
    name = parts[-1]
    stem = name.split(".", 1)[0]
    return (
        stem.startswith("test_")
        or stem.endswith("_test")
        or ".spec." in name
        or ".test." in name
    )


def changed_paths(repo_root: Path, start: str, end: str) -> set[str]:
    """Return the set of paths whose content differs between two commits."""
    output = git_output(repo_root, ["diff", "--name-only", start, end])
    return {line for line in output.splitlines() if line}


def unmerged_base_paths(repo_root: Path, merge_anchor: str, head_sha: str) -> tuple[str, ...]:
    """Return post-merge paths reverted exactly to their pre-merge content.

    A path that changed after the merge anchor yet is byte-identical to the
    pre-merge first parent means the push discarded exactly what the base
    merge brought in for that path — the targeted-revert signature of a stale
    agent workspace snapshot, however small the diff.
    """
    since_merge = changed_paths(repo_root, merge_anchor, head_sha)
    since_pre_merge = changed_paths(repo_root, f"{merge_anchor}^1", head_sha)
    return tuple(sorted(since_merge - since_pre_merge))


def test_case_count(
    repo_root: Path,
    revision: str,
    path: str,
) -> int | None:
    """Return a supported test file's declared test-case count at one revision."""
    try:
        source = git_output(repo_root, ["show", f"{revision}:{path}"])
    except RuntimeError:
        return None

    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None
        return sum(
            isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            and node.name.startswith("test")
            for node in ast.walk(tree)
        )

    pattern = TEST_CASE_PATTERNS.get(suffix)
    return len(pattern.findall(source)) if pattern is not None else None


def test_file_changes(repo_root: Path, start: str, end: str) -> tuple[tuple[str, ...], int]:
    """Return deleted or test-case-reducing paths and the added-test-file count."""
    regressed: set[str] = set()
    added_files = 0
    for line in git_output(repo_root, ["diff", "--name-status", start, end]).splitlines():
        fields = line.split("\t")
        if len(fields) < 2 or not is_test_path(fields[-1]):
            continue
        status = fields[0][:1]
        if status == "D":
            regressed.add(fields[-1])
        elif status == "A":
            added_files += 1
    for line in git_output(
        repo_root,
        ["diff", "--diff-filter=M", "--numstat", start, end],
    ).splitlines():
        fields = line.split("\t", 2)
        if len(fields) < 3 or not fields[0].isdigit() or not fields[1].isdigit():
            continue
        path = fields[2]
        if not is_test_path(path) or int(fields[1]) <= int(fields[0]):
            continue
        before_count = test_case_count(repo_root, start, path)
        after_count = test_case_count(repo_root, end, path)
        if before_count is None or after_count is None or after_count < before_count:
            regressed.add(path)
    return tuple(sorted(regressed)), added_files


def added_existing_test_cases(repo_root: Path, start: str, end: str) -> int:
    """Return declared test cases added to test files that exist at both revisions."""
    added_cases = 0
    for line in git_output(
        repo_root,
        ["diff", "--diff-filter=M", "--numstat", start, end],
    ).splitlines():
        fields = line.split("\t", 2)
        if len(fields) < 3 or not fields[0].isdigit() or not fields[1].isdigit():
            continue
        path = fields[2]
        if not is_test_path(path):
            continue
        before_count = test_case_count(repo_root, start, path)
        after_count = test_case_count(repo_root, end, path)
        if before_count is not None and after_count is not None and after_count > before_count:
            added_cases += after_count - before_count
    return added_cases


def summarize_paths(paths: Sequence[str]) -> str:
    """Render a bounded, comma-separated path list for the report."""
    listed = ", ".join(paths[:MAX_LISTED_PATHS])
    extra = len(paths) - MAX_LISTED_PATHS
    return f"{listed} (+{extra} more)" if extra > 0 else listed


def collect_evidence(repo_root: Path, base_sha: str, head_sha: str) -> ReplayEvidence:
    """Collect exact-tree and bulk-diff evidence for the supplied PR head."""
    git_output(repo_root, ["rev-parse", "--verify", f"{base_sha}^{{commit}}"])
    git_output(repo_root, ["rev-parse", "--verify", f"{head_sha}^{{commit}}"])
    merge_anchor = newest_base_merge(repo_root, base_sha, head_sha)
    if merge_anchor is None:
        return ReplayEvidence(base_sha=base_sha, head_sha=head_sha)

    post_merge_commits = int(
        git_output(repo_root, ["rev-list", "--count", f"{merge_anchor}..{head_sha}"])
    )
    if post_merge_commits == 0:
        return ReplayEvidence(
            base_sha=base_sha,
            head_sha=head_sha,
            merge_anchor=merge_anchor,
        )

    exact_replay = exact_pre_merge_tree_replay(repo_root, merge_anchor, head_sha)
    removed_files, added_lines, deleted_lines = diff_statistics(
        repo_root,
        merge_anchor,
        head_sha,
    )
    unmerged = unmerged_base_paths(repo_root, merge_anchor, head_sha)
    regressed_tests, added_test_files = test_file_changes(repo_root, merge_anchor, head_sha)
    added_test_cases = added_existing_test_cases(repo_root, merge_anchor, head_sha)
    return ReplayEvidence(
        base_sha=base_sha,
        head_sha=head_sha,
        merge_anchor=merge_anchor,
        post_merge_commits=post_merge_commits,
        exact_replay_of=exact_replay,
        removed_files=removed_files,
        added_lines=added_lines,
        deleted_lines=deleted_lines,
        unmerged_paths=unmerged,
        regressed_test_paths=regressed_tests,
        added_test_files=added_test_files,
        added_test_cases=added_test_cases,
    )


def format_report(evidence: ReplayEvidence) -> str:
    """Render a complete, human-readable pass or failure report."""
    lines = [
        "# PR Head Replay Guard",
        f"- Base SHA: {evidence.base_sha}",
        f"- Head SHA: {evidence.head_sha}",
        f"- Merge anchor: {evidence.merge_anchor or 'none'}",
        f"- Post-merge commits: {evidence.post_merge_commits}",
        f"- Post-merge removed files: {evidence.removed_files}",
        f"- Post-merge added/deleted lines: {evidence.added_lines}/{evidence.deleted_lines}",
        f"- Paths reverted to pre-merge content: {summarize_paths(evidence.unmerged_paths) or 'none'}",
        f"- Regressed test files: {summarize_paths(evidence.regressed_test_paths) or 'none'}",
        f"- Added test files: {evidence.added_test_files}",
        f"- Added declared test cases in existing files: {evidence.added_test_cases}",
    ]
    reasons = []
    if evidence.exact_replay_of is not None:
        reasons.append(
            "current HEAD exactly replays the tree of pre-merge ancestor "
            f"{evidence.exact_replay_of}; a stale agent workspace discarded the base merge."
        )
    if evidence.unmerges_base_work:
        reasons.append(
            "post-merge commits reverted base-merged work back to its exact pre-merge "
            f"content (unmerged base work): {summarize_paths(evidence.unmerged_paths)}."
        )
    if evidence.suspicious_test_regression:
        reasons.append(
            "post-merge commits deleted test files or reduced declared test cases "
            "without replacement test-file or existing-file declared test-case evidence: "
            f"{summarize_paths(evidence.regressed_test_paths)}."
        )
    if evidence.suspicious_bulk_regression:
        reasons.append(
            "post-merge changes match the stale bulk-replay signature "
            f"(removed files >= {MIN_REMOVED_FILES}, deleted lines >= {MIN_DELETED_LINES}, "
            f"deletion/addition ratio >= {MIN_DELETION_RATIO}:1)."
        )
    if reasons:
        lines.append("- Result: FAIL")
        lines.extend(f"- Reason: {reason}" for reason in reasons)
    elif evidence.merge_anchor is None:
        lines.extend(
            [
                "- Result: PASS",
                "- Reason: no base-descended merge commit exists on the PR first-parent path; "
                "there is no post-merge replay surface.",
            ]
        )
    elif evidence.post_merge_commits == 0:
        lines.extend(
            [
                "- Result: PASS",
                "- Reason: current HEAD is the latest base merge anchor; no later commit can replay a stale tree.",
            ]
        )
    else:
        lines.extend(
            [
                "- Result: PASS",
                "- Reason: post-merge changes neither match a pre-merge tree, revert base-merged work, "
                "regress tests without replacement, nor exceed the conservative bulk-regression thresholds.",
            ]
        )
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the replay guard and return non-zero for blocked or unevaluable heads."""
    args = parse_args(argv)
    try:
        evidence = collect_evidence(args.repo_root, args.base_sha, args.head_sha)
    except RuntimeError as exc:
        print("# PR Head Replay Guard")
        print("- Result: FAIL")
        print(f"- Reason: replay evidence could not be evaluated: {exc}")
        return 2
    print(format_report(evidence))
    return 1 if evidence.blocked else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
