#!/usr/bin/env python3
"""Run Noema LLM review and submit a non-OpenCode PR review verdict."""

from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from typing import Any


PRIMARY_REVIEW_AUTHORS = {
    "opencode-agent[bot]",
    "opencode-agent",
}
PRIMARY_REVIEW_MARKERS = (
    "OpenCode reviewed the current-head bounded evidence and found no blocking issues.",
    "Result: APPROVE",
    "opencode-review-control-v1",
)
REVIEW_BODY_HEAD_SHA_RE = re.compile(r"Head SHA:\s*`([0-9a-fA-F]{40})`")
IGNORED_RUNNING_CHECKS = {
    "approve-after-primary-review",
    "noema-review",
    "Required Noema Review",
}
FAILED_CONCLUSIONS = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
RUNNING_STATES = {"QUEUED", "IN_PROGRESS", "PENDING", "REQUESTED", "WAITING", "EXPECTED"}
MAX_DIFF_CHARS = 60000
MAX_CONTEXT_FILES = 12
MAX_FILE_CONTEXT_CHARS = 4000
MAX_REVIEW_CONTEXT_CHARS = 24000
MAX_THREAD_BODY_CHARS = 1200

ORCHESTRATOR_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
ORCHESTRATOR_VIA_FLAG = "NOEMA_LLM_VIA_ORCHESTRATOR"
ORCHESTRATOR_BASE_ENV = "CONTEXTUAL_ORCHESTRATOR_BASE_URL"

# ⚡ Bolt: Pre-compiled regex patterns to avoid recompilation on every scrub_sensitive_data call.
# Impact: Improves string processing performance in error reporting.
SENSITIVE_DATA_SCRUB_PATTERNS = (
    (re.compile(r'(?i)(bearer\s+)[^\s"\'\\]+'), r'\1***'),
    (re.compile(r'(?i)(token\s+)[^\s"\'\\]+'), r'\1***'),
    (re.compile(r'(?i)\b(?:github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9_]+)\b'), '***'),
    (re.compile(r'\b(sk-[A-Za-z0-9_-]+)'), '***'),
    (re.compile(r'\b(xox[baprs]-[A-Za-z0-9-]+)'), '***'),
    (re.compile(r'\b(AKIA[0-9A-Z]{16})'), '***'),
    (re.compile(r'(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|password|passwd|secret)\s*[:=]\s*)["\']?[^"\'\s]+["\']?'), r'\1***'),
    (re.compile(r'(?i)((?:authorization|proxy-authorization)\s*:\s*(?:bearer|basic)\s+)[A-Za-z0-9._~+\/=-]+'), r'\1***'),
)

def scrub_sensitive_data(text: str | None) -> str | None:
    """Mask sensitive tokens in text to prevent secret leakage."""
    if not text:
        return text
    for pattern, repl in SENSITIVE_DATA_SCRUB_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def run(args: Sequence[str], *, stdin: str | None = None) -> str:
    """Run a command without invoking a shell and return stdout."""
    if isinstance(args, str):
        raise TypeError("run() requires argv, not a shell command string")
    completed = subprocess.run(
        list(args),
        input=stdin,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        scrubbed_stderr = scrub_sensitive_data(completed.stderr.strip())
        raise RuntimeError(
            f"Command failed ({completed.returncode}): {args[0]}\n{scrubbed_stderr}"
        )
    return completed.stdout


def split_repo(repo: str) -> tuple[str, str]:
    """Split an owner/name repository string into owner and repository."""
    owner, name = repo.split("/", 1)
    if not owner or not name:
        raise ValueError(f"repo must be owner/name, got {repo!r}")
    return owner, name


def graphql(query: str, **fields: str | int) -> dict[str, Any]:
    """Call GitHub GraphQL through gh and return parsed JSON."""
    args = ["gh", "api", "graphql", "-F", "query=@-"]
    for key, value in fields.items():
        args.extend(["-F" if isinstance(value, int) else "-f", f"{key}={value}"])
    return json.loads(run(args, stdin=query))


PR_QUERY = """\
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number
      title
      body
      isDraft
      headRefOid
      reviewDecision
      reviewThreads(first: 100) {
        nodes {
          isResolved
          isOutdated
          path
          line
          comments(first: 20) {
            nodes {
              body
              author { login }
            }
          }
        }
      }
      reviews(last: 100) {
        nodes {
          state
          body
          author { login }
          commit { oid }
        }
      }
      statusCheckRollup {
        contexts(first: 100) {
          nodes {
            __typename
            ... on CheckRun {
              name
              status
              conclusion
              checkSuite {
                workflowRun {
                  workflow { name }
                }
              }
            }
            ... on StatusContext {
              context
              state
            }
          }
        }
      }
    }
  }
}
"""


def fetch_pr(repo: str, number: int) -> dict[str, Any]:
    """Fetch the pull request data required for Noema review gating."""
    owner, name = split_repo(repo)
    data = graphql(PR_QUERY, owner=owner, name=name, number=number)
    pr = data.get("data", {}).get("repository", {}).get("pullRequest")
    if not pr:
        raise RuntimeError(f"PR #{number} was not found in {repo}")
    return pr


def review_author(review: dict[str, Any]) -> str:
    """Return the normalized author login from a review node."""
    return ((review.get("author") or {}).get("login") or "").strip()


def review_commit(review: dict[str, Any]) -> str:
    """Return the review commit oid from a review node."""
    return ((review.get("commit") or {}).get("oid") or "").strip()


def review_body_head_sha(review: dict[str, Any]) -> str | None:
    """Return the last explicit current-head SHA recorded in a review body."""
    matches = REVIEW_BODY_HEAD_SHA_RE.findall(str(review.get("body") or ""))
    return matches[-1] if matches else None


def review_matches_current_head(review: dict[str, Any], head_sha: str) -> bool:
    """Return whether commit and explicit review-body evidence match the live head."""
    if not head_sha or review_commit(review) != head_sha:
        return False
    body_head = review_body_head_sha(review)
    return body_head is None or body_head.lower() == head_sha.lower()


def current_primary_approval(pr: dict[str, Any]) -> dict[str, Any] | None:
    """Return the current-head OpenCode approval when it matches the contract."""
    head_sha = str(pr.get("headRefOid") or "")
    reviews = (((pr.get("reviews") or {}).get("nodes")) or [])
    for review in reversed(reviews):
        if not review_matches_current_head(review, head_sha):
            continue
        if str(review.get("state") or "").upper() != "APPROVED":
            continue
        body = str(review.get("body") or "")
        author = review_author(review)
        if author in PRIMARY_REVIEW_AUTHORS and any(marker in body for marker in PRIMARY_REVIEW_MARKERS):
            return review
    return None


def has_current_changes_requested(pr: dict[str, Any]) -> bool:
    """Return whether the current head has any changes-requested review."""
    head_sha = str(pr.get("headRefOid") or "")
    reviews = (((pr.get("reviews") or {}).get("nodes")) or [])
    for review in reversed(reviews):
        if review_matches_current_head(review, head_sha) and str(review.get("state") or "").upper() == "CHANGES_REQUESTED":
            return True
    return False


def has_unresolved_threads(pr: dict[str, Any]) -> bool:
    """Return whether any non-outdated review thread is unresolved."""
    threads = (((pr.get("reviewThreads") or {}).get("nodes")) or [])
    return any(not thread.get("isResolved") and not thread.get("isOutdated") for thread in threads)


def check_label(node: dict[str, Any]) -> str:
    """Return a human-readable label for a status context or check run."""
    if node.get("__typename") == "StatusContext":
        return str(node.get("context") or "")
    workflow = ((((node.get("checkSuite") or {}).get("workflowRun") or {}).get("workflow") or {}).get("name") or "")
    name = str(node.get("name") or "")
    return f"{workflow} / {name}" if workflow else name


def blocking_checks(pr: dict[str, Any]) -> list[str]:
    """Return check contexts that should block Noema review."""
    contexts = ((((pr.get("statusCheckRollup") or {}).get("contexts") or {}).get("nodes")) or [])
    blockers: list[str] = []
    for node in contexts:
        label = check_label(node)
        if label in IGNORED_RUNNING_CHECKS or str(node.get("name") or "") in IGNORED_RUNNING_CHECKS:
            continue
        if node.get("__typename") == "StatusContext":
            state = str(node.get("state") or "").upper()
            if state not in {"SUCCESS", "NEUTRAL"}:
                blockers.append(f"{label}: {state}")
            continue
        status = str(node.get("status") or "").upper()
        conclusion = str(node.get("conclusion") or "").upper()
        if conclusion in FAILED_CONCLUSIONS:
            blockers.append(f"{label}: {conclusion}")
        elif status in RUNNING_STATES and conclusion not in {"SUCCESS", "NEUTRAL", "SKIPPED"}:
            blockers.append(f"{label}: {status}")
    return blockers


def existing_noema_review(pr: dict[str, Any], actor: str) -> bool:
    """Return whether Noema already reviewed the current head."""
    head_sha = str(pr.get("headRefOid") or "")
    marker = "<!-- noema-review-gate"
    for review in (((pr.get("reviews") or {}).get("nodes")) or []):
        if review_commit(review) != head_sha:
            continue
        if str(review.get("state") or "").upper() not in {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}:
            continue
        if (
            actor
            and review_author(review) == actor
            and marker in str(review.get("body") or "")
        ):
            return True
    return False


def current_actor() -> str:
    """Return the login for the active gh token, or empty string on failure."""
    try:
        return run(["gh", "api", "user", "--jq", ".login"]).strip()
    except Exception:
        return ""


def fetch_diff(repo: str, number: int) -> tuple[str, bool]:
    """Fetch the PR diff and truncate it to the bounded LLM prompt size."""
    diff = run(["gh", "api", f"repos/{repo}/pulls/{number}", "-H", "Accept: application/vnd.github.v3.diff"])
    truncated = len(diff) > MAX_DIFF_CHARS
    if truncated:
        diff = diff[:MAX_DIFF_CHARS]
    return diff, truncated


def truncate_text(text: str, limit: int) -> str:
    """Return text shortened to limit characters with an explicit truncation note."""
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n[truncated {omitted} characters]"


def fetch_changed_file_paths(repo: str, number: int) -> list[str]:
    """Fetch changed file paths for the pull request."""
    output = run(
        [
            "gh",
            "api",
            f"repos/{repo}/pulls/{number}/files",
            "--paginate",
            "--jq",
            ".[].filename",
        ]
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def fetch_head_file_content(repo: str, path: str, head_sha: str) -> str:
    """Fetch a changed file's current-head text content through the GitHub API."""
    encoded_path = urllib.parse.quote(path, safe="/")
    encoded_ref = urllib.parse.quote(head_sha, safe="")
    content = run(
        [
            "gh",
            "api",
            f"repos/{repo}/contents/{encoded_path}?ref={encoded_ref}",
            "--jq",
            ".content // empty",
        ]
    )
    compact = "".join(content.split())
    if not compact:
        return ""
    return base64.b64decode(compact).decode("utf-8", errors="replace")


def changed_file_context(repo: str, number: int, head_sha: str) -> str:
    """Build bounded changed-file context for cross-file review reasoning."""
    if not head_sha:
        return "Changed file context unavailable: missing PR head SHA."
    paths = fetch_changed_file_paths(repo, number)
    if not paths:
        return "Changed file context unavailable: PR reported no changed files."
    sections: list[str] = []
    for path in paths[:MAX_CONTEXT_FILES]:
        try:
            content = fetch_head_file_content(repo, path, head_sha)
        except RuntimeError as exc:
            reason = scrub_sensitive_data(str(exc)) or "unknown error"
            sections.append(f"### {path}\nUnavailable from head content API: {reason}")
            continue
        if not content:
            sections.append(f"### {path}\nNo UTF-8 text content available from head content API.")
            continue
        sections.append(f"### {path}\n{truncate_text(content, MAX_FILE_CONTEXT_CHARS)}")
    if len(paths) > MAX_CONTEXT_FILES:
        sections.append(f"[{len(paths) - MAX_CONTEXT_FILES} changed files omitted from context budget]")
    return "\n\n".join(sections)


def review_thread_context(pr: dict[str, Any]) -> str:
    """Build bounded prior review-thread context so Noema can avoid duplicate comments."""
    lines: list[str] = []
    threads = (((pr.get("reviewThreads") or {}).get("nodes")) or [])
    for thread in threads:
        comments = (((thread.get("comments") or {}).get("nodes")) or [])
        if not comments:
            continue
        state = "outdated" if thread.get("isOutdated") else "resolved" if thread.get("isResolved") else "open"
        location = str(thread.get("path") or "unknown")
        line = thread.get("line")
        if isinstance(line, int) and line > 0:
            location = f"{location}:{line}"
        lines.append(f"- Thread {state} at {location}:")
        for comment in comments:
            author = ((comment.get("author") or {}).get("login") or "unknown").strip()
            body = truncate_text(str(comment.get("body") or "").strip(), MAX_THREAD_BODY_CHARS)
            if body:
                lines.append(f"  - {author}: {body}")
    return "\n".join(lines)


def load_codegraph_context() -> str:
    """Load optional precomputed CodeGraph context for structural review evidence."""
    path = os.environ.get("NOEMA_CODEGRAPH_CONTEXT_PATH", "").strip()
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as handle:
            return truncate_text(handle.read(), MAX_REVIEW_CONTEXT_CHARS)
    except OSError as exc:
        return f"CodeGraph context unavailable: {exc}"


def build_review_context(repo: str, number: int, pr: dict[str, Any]) -> str:
    """Build bounded non-diff context for the Noema reviewer."""
    sections: list[str] = []
    codegraph = load_codegraph_context()
    if codegraph:
        sections.append("## CodeGraph context\n" + codegraph)
    threads = review_thread_context(pr)
    if threads:
        sections.append("## Prior review threads\n" + threads)
    files = changed_file_context(repo, number, str(pr.get("headRefOid") or ""))
    if files:
        sections.append("## Changed file context\n" + files)
    return truncate_text("\n\n".join(sections), MAX_REVIEW_CONTEXT_CHARS)


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """A URL opener handler that refuses to follow redirects to prevent SSRF."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        """Raise an HTTPError instead of following the redirect."""
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract a JSON object from a strict or lightly wrapped LLM response."""
    stripped = text.strip()
    if stripped.startswith("{ "):
        return json.loads(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("Noema LLM response did not contain a JSON object")
    return json.loads(stripped[start : end + 1])
