#!/usr/bin/env python3
"""Auto-rebase cleanly-rebasable open PRs onto their base branch.

This scheduler mirrors ``pr_review_merge_scheduler`` and
``pr_review_fix_scheduler``: it runs per managed repository (``--repo`` /
``GITHUB_REPOSITORY``), enumerates that repository's OPEN pull requests, and
performs a bounded, idempotent maintenance action.

For each OPEN PR that is behind (or dirty against) its base branch and whose
head branch lives in the SAME repository (so the scheduler credential can push
it), the scheduler shallow-fetches the head and base refs, runs
``git rebase origin/<base>`` and, when the rebase applies with no conflicts,
force-pushes the rewritten branch with ``--force-with-lease``. When the rebase
conflicts it aborts, adds a ``needs-manual-rebase`` label (creating it if
missing), and posts a single hand-off comment -- it never force-pushes a
conflicted branch.

CI-cost tradeoff and guards
---------------------------
Rebasing rewrites a PR head, which re-triggers every head-driven required
workflow (OpenCode Review, Strix, security-scan). Those runs are expensive
under a limited Models budget, so this scheduler is deliberately conservative:

* Rate limit (``--max-per-run`` / ``AUTO_REBASE_MAX_PER_RUN``, default 10):
  caps how many PRs are rebased per run so one pass cannot trigger a
  repo-wide CI re-run storm. PRs are processed oldest-first.
* Human-activity guard (``--human-window-minutes`` /
  ``AUTO_REBASE_HUMAN_WINDOW_MINUTES``, default 30): a branch whose most recent
  commit was authored by a human within the window is skipped so the scheduler
  never rewrites work someone is actively pushing. Only bot/stale branches are
  auto-rebased.
* Already-clean guard: a PR that is MERGEABLE and up to date (clean, not behind)
  is never touched.
* Fork guard: cross-repository (fork) heads are skipped because the scheduler
  credential cannot push to them.
* Idempotent: a clean rebase leaves the branch up to date, so the next run skips
  it; a conflicted rebase is labeled ``needs-manual-rebase`` once and, while it
  stays DIRTY, is skipped on subsequent passes WITHOUT consuming a rate-limit
  slot -- so a backlog of old conflicted PRs never starves newer rebasable ones.
  If a labeled PR is later no longer DIRTY (a base change resolved the conflict),
  the stale label is removed and the rebase proceeds.
* ``--dry-run`` prints the plan (including the rate-limit cap) without any git or
  GitHub mutation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

try:
    from pr_review_merge_scheduler import (
        REST_MERGEABLE_STATE_MAP,
        gh_api_json,
        gh_graphql,
        is_transient_github_api_error,
        parse_github_datetime,
        run,
        run_with_env,
        scrub_sensitive_data,
        split_repo,
        validate_git_ref,
        validate_git_sha,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised only via package import
    from scripts.ci.pr_review_merge_scheduler import (
        REST_MERGEABLE_STATE_MAP,
        gh_api_json,
        gh_graphql,
        is_transient_github_api_error,
        parse_github_datetime,
        run,
        run_with_env,
        scrub_sensitive_data,
        split_repo,
        validate_git_ref,
        validate_git_sha,
    )


REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
OPEN_PRS_PAGE_SIZE = 25
LABELS_PAGE_SIZE = 50
DEFAULT_MAX_PER_RUN = 10
DEFAULT_HUMAN_WINDOW_MINUTES = 30
MANUAL_REBASE_LABEL = "needs-manual-rebase"
MANUAL_REBASE_LABEL_COLOR = "b60205"
MANUAL_REBASE_LABEL_DESCRIPTION = "Auto-rebase hit conflicts; a human or agent must rebase this branch manually."
CONFLICT_COMMENT_MARKER = "<!-- pr-auto-rebase needs-manual-rebase -->"
BEHIND_MERGE_STATES = {"BEHIND"}
DIRTY_MERGE_STATES = {"DIRTY", "CONFLICTING"}
CLEAN_MERGE_STATES = {"CLEAN", "HAS_HOOKS"}
GRAPHQL_TRANSPORT_FALLBACK_MARKERS = (
    "invalid UTF-8 string",
    "Resource limits for this query exceeded",
)
# Bot logins whose recent commits are safe to rewrite. Any login ending in
# "[bot]" is also treated as a bot, so this only needs the app-style accounts
# that push under a plain login.
KNOWN_BOT_LOGINS = {
    "opencode-agent",
    "opencode-agent[bot]",
    "github-actions",
    "github-actions[bot]",
    "dependabot",
    "dependabot[bot]",
    "strix-agent",
    "strix-agent[bot]",
}

OPEN_PRS_QUERY = """\
query($owner: String!, $name: String!, $pageSize: Int!, $labelPageSize: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: $pageSize, after: $cursor, states: OPEN, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        title
        isDraft
        mergeable
        mergeStateStatus
        baseRefName
        baseRefOid
        headRefName
        headRefOid
        isCrossRepository
        maintainerCanModify
        labels(first: $labelPageSize) { nodes { name } }
        headRepository { nameWithOwner }
        commits(last: 1) {
          nodes {
            commit {
              oid
              committedDate
              author { name user { login } }
            }
          }
        }
      }
    }
  }
}
"""


@dataclass
class Decision:
    """Auto-rebase decision for a single pull request."""

    pr: int
    action: str
    reason: str
    notes: tuple[str, ...] = field(default_factory=tuple)


def is_graphql_transport_failure(exc: Exception) -> bool:
    """Return whether a GraphQL failure is transport/capacity rather than schema or auth."""
    message = str(exc)
    folded = message.lower()
    if any(marker in message or marker.lower() in folded for marker in GRAPHQL_TRANSPORT_FALLBACK_MARKERS):
        return True
    return is_transient_github_api_error(exc)


def rest_auto_rebase_pr_node(repo: str, pr: dict[str, Any]) -> dict[str, Any]:
    """Convert a REST pull request into the GraphQL node the auto-rebase scheduler consumes."""
    number = int(pr["number"])
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    head_repo = head.get("repo") or {}
    head_repository_name = str(head_repo.get("full_name") or "").strip()
    same_repository = bool(head_repository_name) and (
        head_repository_name.lower() == repo.lower()
    )
    sha = str(head.get("sha") or "")
    merge_state = REST_MERGEABLE_STATE_MAP.get(
        str(pr.get("mergeable_state") or "").lower(),
        str(pr.get("mergeable_state") or "").upper(),
    )
    labels = [{"name": (label or {}).get("name")} for label in (pr.get("labels") or [])]
    commit_payload = gh_api_json(f"repos/{repo}/commits/{sha}") if sha and same_repository else {}
    commit_meta = (commit_payload or {}).get("commit") or {}
    author_login = ((commit_payload or {}).get("author") or {}).get("login")
    committed_date = (commit_meta.get("author") or {}).get("date") or (commit_meta.get("committer") or {}).get(
        "date"
    )
    return {
        "number": number,
        "title": pr.get("title"),
        "isDraft": bool(pr.get("draft")),
        "mergeable": pr.get("mergeable"),
        "mergeStateStatus": merge_state,
        "baseRefName": base.get("ref"),
        "baseRefOid": base.get("sha"),
        "headRefName": head.get("ref"),
        "headRefOid": sha,
        "isCrossRepository": not same_repository,
        "maintainerCanModify": bool(pr.get("maintainer_can_modify")),
        "labels": {"nodes": labels},
        "headRepository": (
            {
                "nameWithOwner": repo if same_repository else head_repository_name
            }
            if head_repository_name
            else None
        ),
        "commits": {
            "nodes": [
                {
                    "commit": {
                        "oid": sha,
                        "committedDate": committed_date,
                        "author": {
                            "name": (commit_meta.get("author") or {}).get("name"),
                            "user": {"login": author_login} if author_login else None,
                        },
                    }
                }
            ]
        },
    }


def fetch_open_prs_rest(repo: str, max_prs: int) -> list[dict[str, Any]]:
    """Fetch open pull requests through REST when GraphQL transport fails."""
    prs: list[dict[str, Any]] = []
    page = 1
    per_page = min(100, max_prs)
    while len(prs) < max_prs:
        path = (
            f"repos/{repo}/pulls?state=open&sort=created&direction=asc"
            f"&per_page={per_page}&page={page}"
        )
        payload = gh_api_json(path)
        if not payload:
            break
        for raw in payload:
            detail = raw
            state = str(raw.get("mergeable_state") or "").lower()
            if state in {"", "unknown"}:
                detail = gh_api_json(f"repos/{repo}/pulls/{int(raw['number'])}") or raw
            prs.append(rest_auto_rebase_pr_node(repo, detail))
            if len(prs) >= max_prs:
                break
        if len(payload) < per_page:
            break
        page += 1
    return prs[:max_prs]


def fetch_open_prs(repo: str, max_prs: int) -> list[dict[str, Any]]:
    """Fetch open pull requests oldest-first, paginating up to max_prs."""
    owner, name = split_repo(repo)
    prs: list[dict[str, Any]] = []
    cursor: str | None = None
    try:
        while len(prs) < max_prs:
            page_size = min(OPEN_PRS_PAGE_SIZE, max_prs - len(prs))
            fields: dict[str, str | int] = {
                "owner": owner,
                "name": name,
                "pageSize": page_size,
                "labelPageSize": LABELS_PAGE_SIZE,
            }
            if cursor:
                fields["cursor"] = cursor
            payload = gh_graphql(OPEN_PRS_QUERY, **fields)
            pr_page = payload["data"]["repository"]["pullRequests"]
            prs.extend(pr_page.get("nodes") or [])
            if not pr_page["pageInfo"]["hasNextPage"]:
                break
            cursor = pr_page["pageInfo"]["endCursor"]
    except (RuntimeError, json.JSONDecodeError) as exc:
        if is_graphql_transport_failure(exc):
            print(
                "GraphQL open-PR list failed with a transport/capacity error; falling back to REST",
                file=sys.stderr,
            )
            return fetch_open_prs_rest(repo, max_prs)
        raise
    return prs[:max_prs]


def merge_state(pr: dict[str, Any]) -> str:
    """Return the normalized GraphQL merge state for a pull request."""
    return (pr.get("mergeStateStatus") or "").upper()


def is_behind_base(pr: dict[str, Any]) -> bool:
    """Return whether the PR head is behind its base branch."""
    return merge_state(pr) in BEHIND_MERGE_STATES


def is_dirty(pr: dict[str, Any]) -> bool:
    """Return whether the PR conflicts with its base branch."""
    return merge_state(pr) in DIRTY_MERGE_STATES


def is_clean(pr: dict[str, Any]) -> bool:
    """Return whether the PR is mergeable and up to date with its base."""
    return merge_state(pr) in CLEAN_MERGE_STATES


def same_repository_head(repo: str, pr: dict[str, Any]) -> bool:
    """Return whether the PR head branch lives in the scanned repository."""
    return ((pr.get("headRepository") or {}).get("nameWithOwner") or "") == repo


def has_manual_rebase_label(pr: dict[str, Any]) -> bool:
    """Return whether the PR already carries the manual-rebase label."""
    nodes = ((pr.get("labels") or {}).get("nodes") or [])
    return any((node or {}).get("name") == MANUAL_REBASE_LABEL for node in nodes)


def last_commit(pr: dict[str, Any]) -> dict[str, Any]:
    """Return the most recent commit object for a pull request head."""
    nodes = ((pr.get("commits") or {}).get("nodes") or [])
    if not nodes:
        return {}
    return (nodes[-1] or {}).get("commit") or {}


def commit_author_is_bot(commit: dict[str, Any]) -> bool:
    """Return whether a commit's author is a known or ``[bot]``-suffixed bot."""
    author = commit.get("author") or {}
    login = ((author.get("user") or {}).get("login") or "").strip()
    name = (author.get("name") or "").strip()
    if login:
        if login.lower() in KNOWN_BOT_LOGINS or login.endswith("[bot]"):
            return True
        # A resolved non-bot GitHub user login is a human signal.
        return False
    # No linked GitHub user: fall back to the raw author name, and treat an
    # unknown author conservatively as human so active work is never rewritten.
    return name.endswith("[bot]")


def head_commit_by_recent_human(pr: dict[str, Any], *, now: datetime, window_minutes: int) -> bool:
    """Return whether the head's newest commit is a human commit within the window."""
    if window_minutes <= 0:
        return False
    commit = last_commit(pr)
    if not commit or commit_author_is_bot(commit):
        return False
    committed = parse_github_datetime(commit.get("committedDate"))
    if committed is None:
        return False
    age_seconds = (now - committed).total_seconds()
    return 0 <= age_seconds < window_minutes * 60


def candidate_skip_reason(
    repo: str,
    pr: dict[str, Any],
    *,
    base_branch: str,
    now: datetime,
    human_window_minutes: int,
) -> str | None:
    """Return why a PR is not an auto-rebase candidate, or None if it is one."""
    if pr.get("isDraft"):
        return "draft PR"
    if not same_repository_head(repo, pr):
        head_repo = (pr.get("headRepository") or {}).get("nameWithOwner") or "<unknown>"
        return f"external fork head {head_repo} is not pushable by the scheduler credential"
    base_ref = pr.get("baseRefName") or ""
    if not base_ref:
        return "PR has no base branch"
    if base_ref != base_branch:
        return f"base branch is {base_ref}; expected {base_branch}"
    if is_clean(pr):
        return f"already mergeable and up to date (merge state {merge_state(pr) or 'CLEAN'}); nothing to rebase"
    if not (is_behind_base(pr) or is_dirty(pr)):
        return f"not behind base and not dirty (merge state {merge_state(pr) or 'UNKNOWN'})"
    if has_manual_rebase_label(pr) and is_dirty(pr):
        return (
            f"already labeled {MANUAL_REBASE_LABEL} and still dirty "
            f"(merge state {merge_state(pr) or 'DIRTY'}); awaiting manual rebase so it does not "
            "re-consume a rate-limit slot"
        )
    if head_commit_by_recent_human(pr, now=now, window_minutes=human_window_minutes):
        login = ((last_commit(pr).get("author") or {}).get("user") or {}).get("login") or "human"
        return (
            f"most recent commit is by human {login} within {human_window_minutes}m; "
            "skipping to avoid rewriting active work"
        )
    return None


def candidate_state_note(pr: dict[str, Any]) -> str:
    """Return a compact description of why a PR was selected for rebase."""
    if is_behind_base(pr):
        return "behind base"
    if is_dirty(pr):
        return "dirty against base"
    return f"merge state {merge_state(pr) or 'UNKNOWN'}"


def scheduler_token() -> str:
    """Return the git/GitHub credential the workflow wired through GH_TOKEN."""
    token = (os.environ.get("GH_TOKEN") or "").strip()
    if not token:
        raise RuntimeError(
            "GH_TOKEN is required for git push; configure the workflow to pass the OpenCode app "
            "token (or a PR-write token) through GH_TOKEN"
        )
    return token


def authenticated_remote_url(repo: str, token: str) -> str:
    """Return an app-token-authenticated HTTPS remote URL for git operations."""
    return f"https://x-access-token:{token}@github.com/{repo}.git"


def git(workdir: str, args: Sequence[str], *, env: dict[str, str] | None = None) -> str:
    """Run a git command inside ``workdir`` and return stdout (scrubbed on failure)."""
    argv = ["git", "-C", workdir, *args]
    if env is not None:
        merged = os.environ.copy()
        merged.update(env)
        return run_with_env(argv, env=merged)
    return run(argv)


def fetch_pr_refs(workdir: str, repo: str, head_ref: str, base_ref: str, *, token: str) -> None:
    """Initialize a work repo and fetch only the PR head and base refs."""
    url = authenticated_remote_url(repo, token)
    env = {"GIT_TERMINAL_PROMPT": "0"}
    git(workdir, ["init", "--quiet"], env=env)
    git(workdir, ["config", "user.name", "pr-auto-rebase[bot]"], env=env)
    git(workdir, ["config", "user.email", "pr-auto-rebase@users.noreply.github.com"], env=env)
    git(workdir, ["remote", "add", "origin", url], env=env)
    git(
        workdir,
        [
            "fetch",
            "--no-tags",
            "--prune",
            "origin",
            f"+refs/heads/{base_ref}:refs/remotes/origin/{base_ref}",
            f"+refs/heads/{head_ref}:refs/remotes/origin/{head_ref}",
        ],
        env=env,
    )
    git(workdir, ["checkout", "-B", head_ref, f"refs/remotes/origin/{head_ref}"], env=env)


def try_rebase(workdir: str, base_ref: str) -> bool:
    """Rebase HEAD onto ``origin/<base_ref>``; abort and return False on conflict."""
    env = {"GIT_TERMINAL_PROMPT": "0"}
    try:
        git(workdir, ["rebase", f"refs/remotes/origin/{base_ref}"], env=env)
    except RuntimeError:
        try:
            git(workdir, ["rebase", "--abort"], env=env)
        except RuntimeError:
            pass
        return False
    return True


def push_force_with_lease(
    workdir: str,
    repo: str,
    head_ref: str,
    expected_head_sha: str,
    *,
    token: str,
) -> None:
    """Force-push the rebased branch, leased against the previously observed head."""
    url = authenticated_remote_url(repo, token)
    env = {"GIT_TERMINAL_PROMPT": "0"}
    git(
        workdir,
        [
            "push",
            f"--force-with-lease=refs/heads/{head_ref}:{expected_head_sha}",
            url,
            f"HEAD:refs/heads/{head_ref}",
        ],
        env=env,
    )


def ensure_manual_rebase_label(repo: str, *, dry_run: bool) -> None:
    """Create the manual-rebase label if it does not already exist."""
    if dry_run:
        return
    try:
        run(
            [
                "gh",
                "api",
                "-X",
                "POST",
                f"repos/{repo}/labels",
                "-f",
                f"name={MANUAL_REBASE_LABEL}",
                "-f",
                f"color={MANUAL_REBASE_LABEL_COLOR}",
                "-f",
                f"description={MANUAL_REBASE_LABEL_DESCRIPTION}",
            ]
        )
    except RuntimeError as exc:
        if "already_exists" not in str(exc).lower():
            raise


def add_manual_rebase_label(repo: str, number: int, *, dry_run: bool) -> None:
    """Add the manual-rebase label to a pull request (idempotent)."""
    if dry_run:
        return
    run(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{repo}/issues/{number}/labels",
            "-f",
            f"labels[]={MANUAL_REBASE_LABEL}",
        ]
    )


def remove_manual_rebase_label(repo: str, number: int, *, dry_run: bool) -> None:
    """Remove a stale manual-rebase label from a PR that is no longer dirty."""
    if dry_run:
        return
    try:
        run(
            [
                "gh",
                "api",
                "-X",
                "DELETE",
                f"repos/{repo}/issues/{number}/labels/{MANUAL_REBASE_LABEL}",
            ]
        )
    except RuntimeError as exc:
        # A 404 means the label was already removed (e.g. by a human); tolerate it.
        if "404" not in str(exc) and "not found" not in str(exc).lower():
            raise


def conflict_comment_exists(repo: str, number: int) -> bool:
    """Return whether a manual-rebase hand-off comment already exists on the PR."""
    pages = run(
        [
            "gh",
            "api",
            f"repos/{repo}/issues/{number}/comments",
            "--paginate",
            "--slurp",
        ]
    )

    for page in json.loads(pages or "[]"):
        for comment in page:
            if CONFLICT_COMMENT_MARKER in str(comment.get("body") or ""):
                return True
    return False


def post_conflict_comment(repo: str, pr: dict[str, Any], base_ref: str, *, dry_run: bool) -> bool:
    """Post the manual-rebase hand-off comment once; return whether it was posted."""
    number = int(pr["number"])
    if dry_run:
        return False
    if conflict_comment_exists(repo, number):
        return False
    body = "\n".join(
        [
            CONFLICT_COMMENT_MARKER,
            "",
            f"Auto-rebase onto `{base_ref}` hit merge conflicts, so this branch was left unchanged "
            f"and labeled `{MANUAL_REBASE_LABEL}`.",
            "",
            "Resolve it manually or with an agent:",
            "",
            f"- `gh pr checkout {number}`",
            f"- `git fetch origin {base_ref}`",
            f"- `git rebase origin/{base_ref}`  (resolve conflicts, then `git rebase --continue`)",
            "- `git push --force-with-lease`",
        ]
    )
    run(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{repo}/issues/{number}/comments",
            "-f",
            f"body={body}",
        ]
    )
    return True


def label_conflicted_pr(repo: str, pr: dict[str, Any], base_ref: str, *, dry_run: bool) -> tuple[str, ...]:
    """Label a conflicted PR and post the one-time hand-off comment."""
    number = int(pr["number"])
    ensure_manual_rebase_label(repo, dry_run=dry_run)
    add_manual_rebase_label(repo, number, dry_run=dry_run)
    commented = post_conflict_comment(repo, pr, base_ref, dry_run=dry_run)
    notes = [f"labeled {MANUAL_REBASE_LABEL}"]
    notes.append("posted hand-off comment" if commented else "hand-off comment already present")
    return tuple(notes)


def perform_rebase(repo: str, pr: dict[str, Any], *, dry_run: bool) -> Decision:
    """Rebase one candidate PR, force-pushing on success or labeling on conflict."""
    number = int(pr["number"])
    head_ref = validate_git_ref(pr["headRefName"])
    base_ref = validate_git_ref(pr["baseRefName"])
    expected_head_sha = validate_git_sha(pr["headRefOid"])
    token = scheduler_token()
    # A candidate reaching this point that still carries the manual-rebase label
    # is no longer dirty (labeled-and-dirty PRs are skipped upstream): its
    # conflict was resolved by a later base change, so clear the stale label and
    # let the rebase proceed instead of leaving it permanently blocked.
    stale_label_notes: tuple[str, ...] = ()
    if has_manual_rebase_label(pr):
        remove_manual_rebase_label(repo, number, dry_run=dry_run)
        stale_label_notes = (f"removed stale {MANUAL_REBASE_LABEL} label (no longer dirty)",)
    with tempfile.TemporaryDirectory(prefix="pr-auto-rebase-") as workdir:
        fetch_pr_refs(workdir, repo, head_ref, base_ref, token=token)
        if not try_rebase(workdir, base_ref):
            notes = label_conflicted_pr(repo, pr, base_ref, dry_run=dry_run)
            return Decision(
                number,
                "labeled",
                f"rebase onto {base_ref} conflicts; aborted and left branch unchanged",
                stale_label_notes + notes,
            )
        push_force_with_lease(workdir, repo, head_ref, expected_head_sha, token=token)
    return Decision(
        number,
        "rebased",
        f"clean rebase onto {base_ref}; force-pushed head with lease",
        stale_label_notes + (f"previous head {expected_head_sha[:12]}",),
    )


def summarize_error(exc: Exception) -> str:
    """Return a bounded, secret-scrubbed one-line summary of a failure."""
    text = scrub_sensitive_data(str(exc)) or "error"
    first_line = text.strip().splitlines()[0] if text.strip() else "error"
    return first_line[:300]


def process_queue(args: argparse.Namespace) -> int:
    """Inspect open PRs and perform bounded, guarded auto-rebases."""
    now = datetime.now(timezone.utc)
    prs = fetch_open_prs(args.repo, args.max_prs)
    decisions: list[Decision] = []
    rebases_used = 0
    for pr in prs:
        number = int(pr.get("number") or 0)
        skip_reason = candidate_skip_reason(
            args.repo,
            pr,
            base_branch=args.base_branch,
            now=now,
            human_window_minutes=args.human_window_minutes,
        )
        if skip_reason is not None:
            decisions.append(Decision(number, "skip", skip_reason))
            continue
        if rebases_used >= args.max_per_run:
            decisions.append(
                Decision(number, "skip", f"rate limit reached ({args.max_per_run} rebases/run); process next run")
            )
            continue
        rebases_used += 1
        if args.dry_run:
            decisions.append(
                Decision(number, "would_rebase", f"candidate ({candidate_state_note(pr)}); dry-run, no git mutation")
            )
            continue
        try:
            decisions.append(perform_rebase(args.repo, pr, dry_run=args.dry_run))
        except (RuntimeError, KeyError, ValueError) as exc:
            decisions.append(Decision(number, "error", summarize_error(exc)))
    print_summary(decisions, dry_run=args.dry_run, base_branch=args.base_branch)
    return 0


def print_summary(decisions: list[Decision], *, dry_run: bool, base_branch: str) -> None:
    """Print human-readable and machine-readable auto-rebase decisions."""

    counts: dict[str, int] = {}
    for decision in decisions:
        counts[decision.action] = counts.get(decision.action, 0) + 1
        suffix = f" ({'; '.join(decision.notes)})" if decision.notes else ""
        print(f"PR #{decision.pr}: {decision.action}: {decision.reason}{suffix}")
    write_actions_summary(decisions, counts=counts, dry_run=dry_run, base_branch=base_branch)
    print(
        json.dumps(
            {
                "schema_version": "pr-auto-rebase/v1",
                "base_branch": base_branch,
                "dry_run": dry_run,
                "inspected": len(decisions),
                "counts": counts,
                "decisions": [
                    {
                        "pr": decision.pr,
                        "action": decision.action,
                        "reason": decision.reason,
                        "notes": list(decision.notes),
                    }
                    for decision in decisions
                ],
            },
            sort_keys=True,
        )
    )


def markdown_cell(value: object) -> str:
    """Escape a value for a compact GitHub Actions summary table cell."""
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def write_actions_summary(
    decisions: list[Decision],
    *,
    counts: dict[str, int],
    dry_run: bool,
    base_branch: str,
) -> None:
    """Append auto-rebase decisions to the GitHub Actions step summary."""

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "## PR auto-rebase scheduler",
        "",
        f"- Base branch: `{base_branch}`",
        f"- Dry run: `{str(dry_run).lower()}`",
        f"- Inspected PRs: `{len(decisions)}`",
        f"- Actions: `{json.dumps(counts, sort_keys=True)}`",
        "",
        "| PR | Action | Reason |",
        "| ---: | --- | --- |",
    ]
    lines.extend(
        f"| #{decision.pr} | {markdown_cell(decision.action)} | {markdown_cell(decision.reason)} |"
        for decision in decisions
    )
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def self_test() -> int:
    """Exercise auto-rebase invariants without GitHub or git access."""
    now = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
    bot_commit = {"author": {"name": "opencode-agent", "user": {"login": "opencode-agent"}}}
    human_commit = {"author": {"name": "Ada Lovelace", "user": {"login": "ada"}}}
    assert commit_author_is_bot(bot_commit)
    assert commit_author_is_bot({"author": {"name": "x", "user": {"login": "dependabot[bot]"}}})
    assert not commit_author_is_bot(human_commit)

    def make_pr(**overrides: Any) -> dict[str, Any]:
        """Return a minimal PR payload for self-test assertions."""
        base = {
            "number": 1,
            "isDraft": False,
            "mergeStateStatus": "BEHIND",
            "baseRefName": "main",
            "baseRefOid": "b" * 40,
            "headRefName": "feature",
            "headRefOid": "a" * 40,
            "headRepository": {"nameWithOwner": "owner/repo"},
            "commits": {"nodes": [{"commit": {"committedDate": "2026-07-01T00:00:00Z", **bot_commit}}]},
        }
        base.update(overrides)
        return base

    assert candidate_skip_reason("owner/repo", make_pr(), base_branch="main", now=now, human_window_minutes=30) is None
    assert "draft" in candidate_skip_reason(
        "owner/repo", make_pr(isDraft=True), base_branch="main", now=now, human_window_minutes=30
    )
    assert "fork" in candidate_skip_reason(
        "owner/repo",
        make_pr(headRepository={"nameWithOwner": "fork/repo"}),
        base_branch="main",
        now=now,
        human_window_minutes=30,
    )
    assert "up to date" in candidate_skip_reason(
        "owner/repo", make_pr(mergeStateStatus="CLEAN"), base_branch="main", now=now, human_window_minutes=30
    )
    assert "not behind" in candidate_skip_reason(
        "owner/repo", make_pr(mergeStateStatus="BLOCKED"), base_branch="main", now=now, human_window_minutes=30
    )
    assert candidate_skip_reason(
        "owner/repo", make_pr(mergeStateStatus="DIRTY"), base_branch="main", now=now, human_window_minutes=30
    ) is None
    recent_human = make_pr(
        commits={"nodes": [{"commit": {"committedDate": "2026-07-08T11:45:00Z", **human_commit}}]}
    )
    assert "active work" in candidate_skip_reason(
        "owner/repo", recent_human, base_branch="main", now=now, human_window_minutes=30
    )
    stale_human = make_pr(
        commits={"nodes": [{"commit": {"committedDate": "2026-07-08T10:00:00Z", **human_commit}}]}
    )
    assert candidate_skip_reason(
        "owner/repo", stale_human, base_branch="main", now=now, human_window_minutes=30
    ) is None
    print("self-test passed")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse auto-rebase scheduler CLI arguments."""
    parser = argparse.ArgumentParser(description="Auto-rebase cleanly-rebasable open PRs onto their base branch.")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--base-branch", default=os.environ.get("DEFAULT_BRANCH", ""))
    parser.add_argument("--max-prs", type=int, default=100)
    parser.add_argument(
        "--max-per-run",
        type=int,
        default=int(os.environ.get("AUTO_REBASE_MAX_PER_RUN", str(DEFAULT_MAX_PER_RUN))),
        help="Maximum PRs to rebase per run (rate limit against CI re-run storms).",
    )
    parser.add_argument(
        "--human-window-minutes",
        type=int,
        default=int(os.environ.get("AUTO_REBASE_HUMAN_WINDOW_MINUTES", str(DEFAULT_HUMAN_WINDOW_MINUTES))),
        help="Skip branches whose newest commit is a human commit within this many minutes.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return args
    if not args.repo:
        parser.error("--repo is required")
    if not REPO_RE.fullmatch(args.repo):
        parser.error("--repo must be in OWNER/NAME form")
    if not args.base_branch:
        parser.error("--base-branch is required")
    if args.max_prs < 1:
        parser.error("--max-prs must be positive")
    if args.max_per_run < 0:
        parser.error("--max-per-run must not be negative")
    if args.human_window_minutes < 0:
        parser.error("--human-window-minutes must not be negative")
    return args


def main(argv: list[str]) -> int:
    """Run the auto-rebase scheduler CLI."""
    args = parse_args(argv)
    if args.self_test:
        return self_test()
    return process_queue(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
