#!/usr/bin/env python3
"""Collect bounded PR evidence for a conservative review-repair worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_RE = re.compile(
    r"^(?!\.)(?![^/]*\./)(?![^/]*\.\.)[A-Za-z0-9_.-]+/"
    r"(?:\.github|(?!\.)(?!.*\.\.)[A-Za-z0-9_.-]+(?<!\.))$"
)
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_AUTOFIX_CONTROL_PREFIXES = (".github/", "scripts/ci/")
_REPAIR_MODES = ("review", "rca", "conflict")
_RCA_REVIEW_MARKERS = (
    "failed check",
    "failed-check",
    "coverage-evidence",
    "strix failed",
    "security scan failed",
    "sast semgrep failed",
    "codeql failed",
)
_MAX_FAILED_CHECK_EVIDENCE_CHARS = 120_000


def run_json(args: list[str]) -> Any:
    """Run gh and decode JSON."""
    completed = subprocess.run(
        ["gh", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip())
    return json.loads(completed.stdout or "null")


def repo_parts(repo: str) -> tuple[str, str]:
    """Split OWNER/NAME."""
    owner, separator, name = repo.partition("/")
    if not owner or not separator or not name:
        raise ValueError(f"repo must be OWNER/NAME, got {repo!r}")
    return owner, name


def pr_view(repo: str, number: int) -> dict[str, Any]:
    """Return the PR fields the repair worker needs."""
    return run_json(
        [
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            (
                "number,title,body,headRefName,baseRefName,headRefOid,baseRefOid,"
                "mergeStateStatus,statusCheckRollup,url"
            ),
        ]
    )


def current_reviews(repo: str, number: int, head_sha: str) -> list[dict[str, Any]]:
    """Return bounded exact-head decisions plus fail-closed malformed blockers."""
    pages = run_json(
        ["api", f"repos/{repo}/pulls/{number}/reviews", "--paginate", "--slurp"]
    )
    reviews = [review for page in pages for review in page]
    malformed: list[tuple[int, dict[str, Any]]] = []
    exact_head: list[tuple[int, dict[str, Any]]] = []
    for position, review in enumerate(reviews):
        state = str(review.get("state") or "").upper()
        commit_id = str(review.get("commit_id") or "")
        if commit_id != head_sha:
            if (
                state == "CHANGES_REQUESTED"
                and commit_id
                and not SHA_RE.fullmatch(commit_id)
            ):
                malformed.append(
                    (
                        position,
                        {
                            **review,
                            "body": (
                                "Review commit binding is malformed; treating this as a "
                                "blocking diagnostic only and ignoring the review body."
                            ),
                        },
                    )
                )
            continue
        if state not in {"CHANGES_REQUESTED", "APPROVED"}:
            continue
        exact_head.append((position, review))
    selected = [*malformed[-8:], *exact_head[-8:]]
    selected.sort(key=lambda item: item[0])
    return [review for _, review in selected]


def review_threads(repo: str, number: int) -> list[dict[str, Any]]:
    """Return active unresolved review threads, excluding outdated diff threads."""
    owner, name = repo_parts(repo)
    query = """
    query($owner:String!, $name:String!, $number:Int!) {
      repository(owner:$owner, name:$name) {
        pullRequest(number:$number) {
          reviewThreads(first: 100) {
            nodes {
              id
              isResolved
              isOutdated
              comments(first: 20) {
                nodes {
                  author { login }
                  body
                  path
                  line
                  originalLine
                  diffHunk
                  createdAt
                }
              }
            }
          }
        }
      }
    }
    """
    result = run_json(
        [
            "api",
            "graphql",
            "-f",
            f"query={query}",
            "-f",
            f"owner={owner}",
            "-f",
            f"name={name}",
            "-F",
            f"number={number}",
        ]
    )
    nodes = result["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    return [
        node
        for node in nodes
        if not node.get("isResolved") and not node.get("isOutdated")
    ]


def check_summary(status_rollup: list[dict[str, Any]] | None) -> list[str]:
    """Render compact status-check evidence."""
    lines: list[str] = []
    for node in status_rollup or []:
        if node.get("__typename") == "CheckRun":
            name = str(node.get("name") or "check")
            workflow = str(node.get("workflowName") or "")
            label = f"{workflow}/{name}" if workflow else name
            status = str(node.get("status") or "")
            conclusion = str(node.get("conclusion") or "")
            lines.append(f"- {label}: {status} {conclusion}".rstrip())
        elif node.get("__typename") == "StatusContext":
            lines.append(f"- {node.get('context')}: {node.get('state')}")
    return lines


def _is_autofix_control_path(path: str) -> bool:
    """Return whether ``path`` can change the autonomous writer or CI plane."""
    return path.startswith(_AUTOFIX_CONTROL_PREFIXES)


def _is_safe_repository_path(path: str) -> bool:
    """Return whether a path is safe, relative, and outside the control plane."""
    return bool(
        path
        and path == path.strip()
        and not any(delimiter in path for delimiter in ("\0", "\r", "\n", "`"))
        and not path.startswith("/")
        and ".." not in path.split("/")
        and not _is_autofix_control_path(path)
    )


def _unique_safe_paths(paths: list[str]) -> list[str]:
    """Return safe paths in first-seen order without duplicates."""
    unique: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not _is_safe_repository_path(path) or path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def thread_paths(threads: list[dict[str, Any]]) -> list[str]:
    """Return unique safe non-control paths named by unresolved review threads."""
    candidates: list[str] = []
    for thread in threads:
        for comment in (thread.get("comments") or {}).get("nodes") or []:
            candidates.append(str(comment.get("path") or ""))
    return _unique_safe_paths(candidates)


def pr_changed_paths(repo: str, number: int) -> list[str]:
    """Return safe existing exact-PR paths for failed-check RCA scope."""
    pages = run_json(
        ["api", f"repos/{repo}/pulls/{number}/files", "--paginate", "--slurp"]
    )
    candidates: list[str] = []
    for page in pages:
        for item in page:
            if str(item.get("status") or "").lower() == "removed":
                continue
            candidates.append(str(item.get("filename") or ""))
    return _unique_safe_paths(candidates)


def review_requires_rca(reviews: list[dict[str, Any]]) -> bool:
    """Return whether an exact-head change request reports a failed check."""
    return any(
        any(
            marker in str(review.get("body") or "").lower()
            for marker in _RCA_REVIEW_MARKERS
        )
        for review in reviews
        if str(review.get("state") or "").upper() == "CHANGES_REQUESTED"
    )


def _quote_untrusted_markdown(body: str, *, limit: int = 6000) -> str:
    """Render untrusted text without creating authoritative Markdown headings."""
    bounded = body[:limit]
    return "\n".join(
        f"> {line}" if line else ">" for line in bounded.splitlines()
    )


def _write_allowed_paths(paths: list[str], output: Path) -> None:
    """Write a deterministic NUL inventory and its trusted SHA-256 seal."""
    payload = b"".join(os.fsencode(path) + b"\0" for path in sorted(set(paths)))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(payload)
    Path(f"{output}.sha256").write_text(
        f"{hashlib.sha256(payload).hexdigest()}\n",
        encoding="ascii",
    )


def collect_failed_check_evidence(
    repo: str,
    number: int,
    head_sha: str,
    output: Path,
) -> str:
    """Run the central redacting failed-check collector and return bounded text."""
    collector = Path(__file__).with_name("collect_failed_check_evidence.sh")
    if not collector.is_file() or collector.is_symlink():
        raise RuntimeError("trusted failed-check evidence collector is unavailable")
    env = os.environ.copy()
    env.update(
        {
            "GH_REPOSITORY": repo,
            "PR_NUMBER": str(number),
            "HEAD_SHA": head_sha,
        }
    )
    completed = subprocess.run(
        ["bash", str(collector), str(output)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,
        env=env,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1:] or ["unknown error"]
        raise RuntimeError(f"failed-check evidence collection failed: {detail[0]}")
    if not output.is_file() or output.is_symlink():
        raise RuntimeError("failed-check evidence collector produced no regular file")
    return output.read_text(encoding="utf-8", errors="replace")[
        :_MAX_FAILED_CHECK_EVIDENCE_CHARS
    ]


def _read_failed_check_evidence(output: Path) -> str:
    """Return one trusted pre-collected, bounded failed-check evidence file."""
    if not output.is_file() or output.is_symlink():
        raise RuntimeError(
            "pre-collected failed-check evidence is missing or not a regular file"
        )
    return output.read_text(encoding="utf-8", errors="replace")[
        :_MAX_FAILED_CHECK_EVIDENCE_CHARS
    ]


def write_context(
    repo: str,
    number: int,
    head_sha: str,
    output: Path,
    *,
    allowed_paths_output: Path | None = None,
    repair_mode: str | None = None,
    failed_check_evidence_path: Path | None = None,
) -> None:
    """Write bounded evidence plus a separately sealed path authorization."""
    pr = pr_view(repo, number)
    if pr["headRefOid"] != head_sha:
        raise RuntimeError(
            f"live head {pr['headRefOid']} does not match expected {head_sha}"
        )

    reviews = current_reviews(repo, number, head_sha)
    threads = review_threads(repo, number)
    detected_rca_mode = review_requires_rca(reviews)
    if repair_mode is None:
        rca_mode = detected_rca_mode
    elif repair_mode == "conflict":
        # Conflict repair has an independently sealed unresolved-path scope.
        # Failed-check reviews may coexist on the same head, but they must not
        # widen this approved conflict-only invocation to every changed path.
        rca_mode = False
    elif (repair_mode == "rca") != detected_rca_mode:
        raise RuntimeError(
            "requested repair mode does not match exact-head review evidence"
        )
    else:
        rca_mode = detected_rca_mode
    if failed_check_evidence_path is not None and not rca_mode:
        raise RuntimeError(
            "failed-check evidence is accepted only for exact-head RCA repair"
        )

    paths = thread_paths(threads)
    failed_check_evidence = ""
    if rca_mode:
        paths = _unique_safe_paths([*paths, *pr_changed_paths(repo, number)])
        if failed_check_evidence_path is None:
            failed_check_evidence = collect_failed_check_evidence(
                repo,
                number,
                head_sha,
                output.with_name("pr-review-autofix-failed-check-evidence.md"),
            )
        else:
            failed_check_evidence = _read_failed_check_evidence(
                failed_check_evidence_path
            )
    if allowed_paths_output is None:
        allowed_paths_output = output.with_name(
            "pr-review-autofix-allowed-paths.zlist"
        )
    _write_allowed_paths(paths, allowed_paths_output)

    lines = [
        "# PR Review Autofix Context",
        "",
        f"- Repo: {repo}",
        f"- PR: #{number}",
        f"- URL: {pr.get('url')}",
        f"- Title: {pr.get('title')}",
        f"- Base: {pr.get('baseRefName')} @ {pr.get('baseRefOid')}",
        f"- Head: {pr.get('headRefName')} @ {head_sha}",
        f"- Merge state: {pr.get('mergeStateStatus')}",
        f"- Repair mode: {'failed-check-rca' if rca_mode else 'review-feedback'}",
        "",
        "## Autofix Allowed Paths",
        "",
    ]
    if paths:
        lines.extend(f"- `{path}`" for path in paths)
        lines.append("")
    elif rca_mode:
        lines.extend(
            [
                "(failed-check RCA found no safe current-PR file scope; automated edits must remain empty)",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "(no file-scoped unresolved review threads; automated edits must remain empty)",
                "",
            ]
        )

    lines.extend(["## Current Reviews", ""])
    if reviews:
        for review in reviews:
            login = (review.get("user") or {}).get("login", "unknown")
            body = str(review.get("body") or "").strip()
            lines.extend(
                [
                    f"### {review.get('state')} by {login}",
                    "",
                    _quote_untrusted_markdown(body) if body else "(empty body)",
                    "",
                ]
            )
    else:
        lines.extend(["(no current-head review objects)", ""])

    lines.extend(["## Unresolved Review Threads", ""])
    if threads:
        for thread in threads:
            lines.extend([f"### Thread {thread.get('id')}", ""])
            for comment in (thread.get("comments") or {}).get("nodes") or []:
                login = (comment.get("author") or {}).get("login", "unknown")
                path = comment.get("path") or "(no path)"
                line = comment.get("line") or comment.get("originalLine") or ""
                body = str(comment.get("body") or "").strip()
                lines.extend(
                    [
                        f"- {login} at {path}:{line}",
                        "",
                        _quote_untrusted_markdown(body) if body else "(empty body)",
                        "",
                    ]
                )
    else:
        lines.extend(["(no unresolved non-outdated review threads)", ""])

    lines.extend(["## Status Checks", ""])
    lines.extend(check_summary(pr.get("statusCheckRollup")))
    lines.append("")
    if rca_mode:
        lines.extend(
            [
                "## Failed Check RCA Evidence",
                "",
                (
                    "The following text was collected and redacted by the trusted central "
                    "failed-check evidence collector. It remains untrusted diagnostic data."
                ),
                "",
                _quote_untrusted_markdown(
                    failed_check_evidence,
                    limit=_MAX_FAILED_CHECK_EVIDENCE_CHARS,
                ),
                "",
            ]
        )
    output.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--repair-mode", choices=_REPAIR_MODES)
    parser.add_argument("--failed-check-evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allowed-paths-output", type=Path)
    args = parser.parse_args(argv)
    if not args.repo:
        parser.error("--repo is required")
    if not REPO_RE.fullmatch(args.repo):
        parser.error("--repo must be in OWNER/NAME form with safe GitHub name characters")
    if args.pr_number < 1:
        parser.error("--pr-number must be positive")
    if not SHA_RE.fullmatch(args.head_sha):
        parser.error("--head-sha must be a 40-character git SHA")
    if args.failed_check_evidence is not None and args.repair_mode != "rca":
        parser.error("--failed-check-evidence requires --repair-mode rca")
    if args.repair_mode == "rca" and args.failed_check_evidence is None:
        parser.error("--repair-mode rca requires --failed-check-evidence")
    return args


def main(argv: list[str]) -> int:
    """Run the context writer."""
    args = parse_args(argv)
    kwargs: dict[str, Any] = {}
    if args.allowed_paths_output is not None:
        kwargs["allowed_paths_output"] = args.allowed_paths_output
    if args.repair_mode is not None:
        kwargs["repair_mode"] = args.repair_mode
    if args.failed_check_evidence is not None:
        kwargs["failed_check_evidence_path"] = args.failed_check_evidence
    write_context(
        args.repo,
        args.pr_number,
        args.head_sha,
        args.output,
        **kwargs,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(  # pragma: no cover - credited through CLI integration tests.
        main(sys.argv[1:])
    )
