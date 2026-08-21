#!/usr/bin/env python3
"""Publish one exact pull-request head without bypassing branch rules.

The shortest path is the existing direct push. When GitHub rejects only that
push with the exact pull-request-required ``GH013`` diagnostic, this helper
publishes the commit to a user fork and opens a stacked pull request targeting
the original pull-request head branch.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote

try:
    from pr_review_merge_scheduler import (
        run,
        run_with_env,
        split_repo,
        validate_git_ref,
        validate_git_sha,
    )
except ModuleNotFoundError:  # pragma: no cover - package import only
    from scripts.ci.pr_review_merge_scheduler import (
        run,
        run_with_env,
        split_repo,
        validate_git_ref,
        validate_git_sha,
    )


PULL_REQUEST_REQUIRED = "Changes must be made through a pull request"
STACK_MARKER = "cwl-protected-publication"
SERVER_URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+(?::[0-9]+)?$")
KIND_TITLES = {
    "review": "fix(pr-{number}): publish protected review repair",
    "conflict": "merge(pr-{number}): publish protected conflict repair",
    "rebase": "chore(pr-{number}): publish protected clean rebase",
}


@dataclass(frozen=True)
class PublicationResult:
    """Describe the branch or stacked pull request that received a commit."""

    mode: str
    head_repository: str
    head_ref: str
    pull_number: int | None = None
    url: str | None = None


def stack_marker(repo: str, pr_number: int, expected_head_sha: str) -> str:
    """Return the exact idempotency marker for one original pull-request head."""

    return f"<!-- {STACK_MARKER} {repo}#{pr_number}@{expected_head_sha} -->"


def stack_body(repo: str, pr_number: int, expected_head_sha: str, kind: str) -> str:
    """Return the auditable body for a protected publication stack."""

    return "\n".join(
        (
            stack_marker(repo, pr_number, expected_head_sha),
            "",
            f"Publishes an automated {kind} commit for `{repo}#{pr_number}` at exact original head ",
            f"`{expected_head_sha}` after GitHub required a pull request for the target branch.",
            "",
            "This stacked pull request does not bypass the original pull request. Merge it only ",
            "after its current-head checks, independent approvals, and review threads satisfy the ",
            "normal repository rules; then re-review the updated original pull request.",
        )
    )


def _json(args: list[str], *, stdin: str | None = None) -> Any:
    """Run one GitHub CLI command and decode its required JSON response."""

    output = run(args, stdin=stdin)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub returned malformed JSON") from exc


def _server_url(value: str) -> str:
    """Return one canonical HTTPS Git server origin."""

    normalized = value.rstrip("/")
    if not SERVER_URL_RE.fullmatch(normalized):
        raise ValueError("server URL must be one canonical HTTPS origin")
    return normalized


def _git_auth_env(token: str, server_url: str) -> dict[str, str]:
    """Bind Git HTTPS authentication through environment-only configuration."""

    encoded = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env = os.environ.copy()
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"http.{server_url}/.extraheader",
            "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {encoded}",
        }
    )
    return env


def _git_head(workdir: str) -> str:
    """Return the validated commit currently checked out in a worktree."""

    output = run_with_env(["git", "-C", workdir, "rev-parse", "HEAD"], env=None)
    return validate_git_sha(output.strip())


def _push(
    workdir: str,
    repository: str,
    branch: str,
    *,
    token: str,
    server_url: str,
    force_with_lease: str | None = None,
) -> None:
    """Push HEAD to one explicit repository branch with hooks disabled."""

    args = ["git", "-C", workdir, "-c", "core.hooksPath=/dev/null", "push"]
    if force_with_lease is not None:
        args.append(f"--force-with-lease=refs/heads/{branch}:{force_with_lease}")
    args.extend(
        (
            f"{server_url}/{repository}.git",
            f"HEAD:refs/heads/{branch}",
        )
    )
    run_with_env(args, env=_git_auth_env(token, server_url))


def _requires_pull_request(exc: RuntimeError) -> bool:
    """Return whether GitHub rejected only because a pull request is required."""

    diagnostic = str(exc)
    return "GH013" in diagnostic and PULL_REQUEST_REQUIRED in diagnostic


def _original_pr(
    repo: str,
    pr_number: int,
    head_ref: str,
    expected_head_sha: str,
) -> dict[str, Any]:
    """Require the original open pull request to retain its exact head."""

    payload = _json(["gh", "api", f"repos/{repo}/pulls/{pr_number}"])
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned a malformed original pull request")
    head = payload.get("head") or {}
    head_repo = (head.get("repo") or {}).get("full_name")
    if payload.get("state") != "open":
        raise RuntimeError("original pull request is no longer open")
    if head_repo != repo or head.get("ref") != head_ref:
        raise RuntimeError("original pull request head repository or branch changed")
    if head.get("sha") != expected_head_sha:
        raise RuntimeError("original pull request head moved")
    return payload


def _user_login() -> str:
    """Return the authenticated user who can own a publication fork."""

    try:
        payload = _json(["gh", "api", "user"])
    except RuntimeError as exc:
        raise RuntimeError(
            "protected publication requires a user credential that can own a fork"
        ) from exc
    login = payload.get("login") if isinstance(payload, dict) else None
    if not isinstance(login, str) or not login:
        raise RuntimeError("GitHub user response did not contain a fork owner login")
    return split_repo(f"{login}/fork")[0]


def _repository_or_none(repo: str) -> dict[str, Any] | None:
    """Return a repository payload, using None only for a genuine 404."""

    try:
        payload = _json(["gh", "api", f"repos/{repo}"])
    except RuntimeError as exc:
        if "404" in str(exc) or "Not Found" in str(exc):
            return None
        raise
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned a malformed repository")
    return payload


def _ensure_fork(repo: str, actor: str) -> str:
    """Return the actor's verified fork, creating it when absent."""

    _, name = split_repo(repo)
    fork_repo = f"{actor}/{name}"
    payload = _repository_or_none(fork_repo)
    if payload is None:
        try:
            run(
                [
                    "gh",
                    "repo",
                    "fork",
                    repo,
                    "--clone=false",
                    "--remote=false",
                ]
            )
        except RuntimeError:
            if _repository_or_none(fork_repo) is None:
                raise
        payload = _repository_or_none(fork_repo)
    if payload is None:
        raise RuntimeError("GitHub did not materialize the requested user fork")
    parent = (payload.get("parent") or {}).get("full_name")
    owner = (payload.get("owner") or {}).get("login")
    if (
        payload.get("fork") is not True
        or str(payload.get("full_name") or "").casefold() != fork_repo.casefold()
        or str(parent or "").casefold() != repo.casefold()
        or str(owner or "").casefold() != actor.casefold()
    ):
        raise RuntimeError(f"{fork_repo} exists but is not the expected target-repository fork")
    return fork_repo


def _fork_ref_sha(fork_repo: str, branch: str) -> str | None:
    """Return a fork branch SHA, using None only when the ref is absent."""

    endpoint = f"repos/{fork_repo}/git/ref/heads/{quote(branch, safe='')}"
    try:
        payload = _json(["gh", "api", endpoint])
    except RuntimeError as exc:
        if "404" in str(exc) or "Not Found" in str(exc):
            return None
        raise
    sha = ((payload or {}).get("object") or {}).get("sha") if isinstance(payload, dict) else None
    if not isinstance(sha, str):
        raise RuntimeError("GitHub returned a malformed fork branch reference")
    return validate_git_sha(sha)


def _stack_result(
    payload: Any,
    *,
    repo: str,
    pr_number: int,
    expected_head_sha: str,
    local_head_sha: str,
    fork_repo: str,
    fork_ref: str,
    head_ref: str,
) -> PublicationResult:
    """Validate a stacked pull request and convert it to a result."""

    if not isinstance(payload, dict):
        raise RuntimeError("GitHub returned a malformed stacked pull request")
    number = payload.get("number")
    url = payload.get("html_url")
    base = payload.get("base") or {}
    head = payload.get("head") or {}
    if (
        payload.get("state") != "open"
        or not isinstance(number, int)
        or number < 1
        or not isinstance(url, str)
        or base.get("ref") != head_ref
        or head.get("ref") != fork_ref
        or head.get("sha") != local_head_sha
        or ((head.get("repo") or {}).get("full_name") or "").casefold()
        != fork_repo.casefold()
        or stack_marker(repo, pr_number, expected_head_sha)
        not in str(payload.get("body") or "")
    ):
        raise RuntimeError("stacked pull request does not match the protected publication")
    return PublicationResult("stacked", fork_repo, fork_ref, number, url)


def _open_stack(
    repo: str,
    pr_number: int,
    expected_head_sha: str,
    local_head_sha: str,
    fork_repo: str,
    fork_ref: str,
    head_ref: str,
) -> PublicationResult | None:
    """Return the sole open stack for one deterministic fork branch."""

    actor, _ = split_repo(fork_repo)
    query = (
        f"repos/{repo}/pulls?state=open&base={quote(head_ref, safe='')}"
        f"&head={quote(f'{actor}:{fork_ref}', safe='')}&per_page=2"
    )
    payload = _json(["gh", "api", query])
    if not isinstance(payload, list):
        raise RuntimeError("GitHub returned a malformed stacked pull-request list")
    if len(payload) > 1:
        raise RuntimeError("multiple live stacked pull requests claim one publication branch")
    if not payload:
        return None
    return _stack_result(
        payload[0],
        repo=repo,
        pr_number=pr_number,
        expected_head_sha=expected_head_sha,
        local_head_sha=local_head_sha,
        fork_repo=fork_repo,
        fork_ref=fork_ref,
        head_ref=head_ref,
    )


def _publication_branch(
    fork_repo: str,
    pr_number: int,
    expected_head_sha: str,
    local_head_sha: str,
) -> str:
    """Choose a non-overwriting deterministic fork publication branch."""

    primary = f"cwl-autofix/pr-{pr_number}-{expected_head_sha[:12]}"
    primary_sha = _fork_ref_sha(fork_repo, primary)
    if primary_sha is None or primary_sha == local_head_sha:
        return primary
    secondary = f"{primary}-{local_head_sha[:12]}"
    secondary_sha = _fork_ref_sha(fork_repo, secondary)
    if secondary_sha is not None and secondary_sha != local_head_sha:
        raise RuntimeError("protected publication branch prefix collision")
    return secondary


def _create_stack(
    workdir: str,
    repo: str,
    pr_number: int,
    head_ref: str,
    expected_head_sha: str,
    local_head_sha: str,
    kind: str,
    *,
    token: str,
    server_url: str,
) -> PublicationResult:
    """Publish to a verified fork and create or reuse one upstream stack."""

    actor = _user_login()
    fork_repo = _ensure_fork(repo, actor)
    primary = f"cwl-autofix/pr-{pr_number}-{expected_head_sha[:12]}"
    existing = _open_stack(
        repo, pr_number, expected_head_sha, local_head_sha, fork_repo, primary, head_ref
    )
    if existing is not None:
        return existing
    fork_ref = _publication_branch(
        fork_repo, pr_number, expected_head_sha, local_head_sha
    )
    existing = _open_stack(
        repo, pr_number, expected_head_sha, local_head_sha, fork_repo, fork_ref, head_ref
    )
    if existing is not None:
        return existing
    if _fork_ref_sha(fork_repo, fork_ref) != local_head_sha:
        _push(
            workdir,
            fork_repo,
            fork_ref,
            token=token,
            server_url=server_url,
        )
    if _fork_ref_sha(fork_repo, fork_ref) != local_head_sha:
        raise RuntimeError("fork branch did not reach the validated local head")
    _original_pr(repo, pr_number, head_ref, expected_head_sha)
    existing = _open_stack(
        repo, pr_number, expected_head_sha, local_head_sha, fork_repo, fork_ref, head_ref
    )
    if existing is not None:
        return existing
    request = {
        "title": KIND_TITLES[kind].format(number=pr_number),
        "head": f"{actor}:{fork_ref}",
        "base": head_ref,
        "body": stack_body(repo, pr_number, expected_head_sha, kind),
        "maintainer_can_modify": False,
    }
    try:
        payload = _json(
            ["gh", "api", "-X", "POST", f"repos/{repo}/pulls", "--input", "-"],
            stdin=json.dumps(request, sort_keys=True),
        )
    except RuntimeError:
        existing = _open_stack(
            repo, pr_number, expected_head_sha, local_head_sha, fork_repo, fork_ref, head_ref
        )
        if existing is not None:
            return existing
        raise
    result = _stack_result(
        payload,
        repo=repo,
        pr_number=pr_number,
        expected_head_sha=expected_head_sha,
        local_head_sha=local_head_sha,
        fork_repo=fork_repo,
        fork_ref=fork_ref,
        head_ref=head_ref,
    )
    try:
        _original_pr(repo, pr_number, head_ref, expected_head_sha)
    except RuntimeError as exc:
        try:
            run(
                [
                    "gh",
                    "api",
                    "-X",
                    "PATCH",
                    f"repos/{repo}/pulls/{result.pull_number}",
                    "-f",
                    "state=closed",
                ]
            )
        except RuntimeError as close_exc:
            raise RuntimeError(
                "original head moved after stack creation and stale stack closure failed"
            ) from close_exc
        raise RuntimeError("original head moved after stack creation; stale stack closed") from exc
    return result


def publish_head(
    workdir: str,
    repo: str,
    pr_number: int,
    head_ref: str,
    expected_head_sha: str,
    *,
    token: str,
    kind: str,
    force_with_lease: bool = False,
    server_url: str = "https://github.com",
) -> PublicationResult:
    """Publish HEAD directly or through one protected stacked pull request."""

    split_repo(repo)
    if pr_number < 1:
        raise ValueError("pull request number must be positive")
    head_ref = validate_git_ref(head_ref)
    expected_head_sha = validate_git_sha(expected_head_sha)
    if kind not in KIND_TITLES:
        raise ValueError("publication kind must be review, conflict, or rebase")
    if not token:
        raise ValueError("GitHub mutation token is required")
    server_url = _server_url(server_url)
    local_head_sha = _git_head(workdir)
    _original_pr(repo, pr_number, head_ref, expected_head_sha)
    try:
        _push(
            workdir,
            repo,
            head_ref,
            token=token,
            server_url=server_url,
            force_with_lease=expected_head_sha if force_with_lease else None,
        )
    except RuntimeError as exc:
        if not _requires_pull_request(exc):
            raise
        _original_pr(repo, pr_number, head_ref, expected_head_sha)
        return _create_stack(
            workdir,
            repo,
            pr_number,
            head_ref,
            expected_head_sha,
            local_head_sha,
            kind,
            token=token,
            server_url=server_url,
        )
    _original_pr(repo, pr_number, head_ref, local_head_sha)
    return PublicationResult("direct", repo, head_ref)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the protected publication command-line contract."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--head-ref", required=True)
    parser.add_argument("--expected-head-sha", required=True)
    parser.add_argument("--kind", required=True, choices=tuple(KIND_TITLES))
    parser.add_argument("--force-with-lease", action="store_true")
    parser.add_argument(
        "--server-url",
        default=os.environ.get("GITHUB_SERVER_URL", "https://github.com"),
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Run one publication and print its machine-readable result."""

    args = parse_args(argv)
    result = publish_head(
        args.workdir,
        args.repo,
        args.pr_number,
        args.head_ref,
        args.expected_head_sha,
        token=os.environ.get("GH_TOKEN", ""),
        kind=args.kind,
        force_with_lease=args.force_with_lease,
        server_url=args.server_url,
    )
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through workflow CLI
    raise SystemExit(main(sys.argv[1:]))
