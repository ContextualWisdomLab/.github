"""Fail closed when a stale agent patch replays a pre-merge PR tree.

An asynchronous review or autofix agent can finish after a maintainer has merged
the current base into a PR branch.  If that agent then writes its old workspace
snapshot as a new commit, Git records a valid commit whose tree silently removes
everything learned from the base merge.  Ordinary tests can still pass because
the stale snapshot also restores its old tests.

This guard inspects the PR head history, finds the newest merge commit on the
first-parent path from the supplied base, and evaluates commits made after that
merge.  It blocks an exact replay of any pre-merge first-parent tree.  It also
blocks a conservative bulk-regression signature: at least five tracked files and
500 lines removed, with deletions at least four times additions.  Every decision
is printed with the exact SHAs and diff counts so the failure is actionable.
"""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


MAX_PRE_MERGE_ANCESTORS = 200
MIN_REMOVED_FILES = 5
MIN_DELETED_LINES = 500
MIN_DELETION_RATIO = 4


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

    @property
    def suspicious_bulk_regression(self) -> bool:
        """Return whether the post-merge delta matches the bulk replay signature."""
        return (
            self.removed_files >= MIN_REMOVED_FILES
            and self.deleted_lines >= MIN_DELETED_LINES
            and self.deleted_lines >= MIN_DELETION_RATIO * max(1, self.added_lines)
        )

    @property
    def blocked(self) -> bool:
        """Return whether exact-tree or bulk-regression evidence blocks the head."""
        return self.exact_replay_of is not None or self.suspicious_bulk_regression


def git_output(repo_root: Path, args: Sequence[str]) -> str:
    """Run a read-only git command and return stripped standard output."""
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
        raise RuntimeError(f"git {args[0]} failed: {detail[:500]}")
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
    return ReplayEvidence(
        base_sha=base_sha,
        head_sha=head_sha,
        merge_anchor=merge_anchor,
        post_merge_commits=post_merge_commits,
        exact_replay_of=exact_replay,
        removed_files=removed_files,
        added_lines=added_lines,
        deleted_lines=deleted_lines,
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
    ]
    if evidence.exact_replay_of is not None:
        lines.extend(
            [
                "- Result: FAIL",
                "- Reason: current HEAD exactly replays the tree of pre-merge ancestor "
                f"{evidence.exact_replay_of}; a stale agent workspace discarded the base merge.",
            ]
        )
    elif evidence.suspicious_bulk_regression:
        lines.extend(
            [
                "- Result: FAIL",
                "- Reason: post-merge changes match the stale bulk-replay signature "
                f"(removed files >= {MIN_REMOVED_FILES}, deleted lines >= {MIN_DELETED_LINES}, "
                f"deletion/addition ratio >= {MIN_DELETION_RATIO}:1).",
            ]
        )
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
                "- Reason: post-merge changes neither match a pre-merge tree nor exceed the conservative bulk-regression thresholds.",
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
