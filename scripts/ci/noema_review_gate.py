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
from pathlib import Path
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


def codegraph_context_root() -> Path:
    """Return the workspace root that may contain CodeGraph context files."""
    raw = os.environ.get("GITHUB_WORKSPACE", "").strip() or os.getcwd()
    return Path(raw).resolve()


def confined_codegraph_context_path(path: str, root: Path) -> Path | None:
    """Return the resolved path when it cannot escape the workspace root."""
    candidate = Path(path)
    if ".." in candidate.parts:
        return None
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if not resolved.is_relative_to(root):
        return None
    return resolved


def load_codegraph_context() -> str:
    """Load optional precomputed CodeGraph context for structural review evidence."""
    path = os.environ.get("NOEMA_CODEGRAPH_CONTEXT_PATH", "").strip()
    if not path:
        return ""
    confined = confined_codegraph_context_path(path, codegraph_context_root())
    if confined is None:
        return "CodeGraph context unavailable: path escapes the workspace."
    try:
        with confined.open(encoding="utf-8") as handle:
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
    if stripped.startswith("{"):
        return json.loads(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("Noema LLM response did not contain a JSON object")
    return json.loads(stripped[start : end + 1])


def call_llm(
    repo: str,
    number: int,
    pr: dict[str, Any],
    diff: str,
    truncated: bool,
    review_context: str = "",
) -> dict[str, Any]:
    """Call the configured OpenAI-compatible LLM endpoint for a review verdict."""
    api_url = os.environ.get("NOEMA_LLM_API_URL", "").strip()
    api_key = os.environ.get("NOEMA_LLM_API_KEY", "").strip()
    model = os.environ.get("NOEMA_LLM_MODEL", "").strip() or "noema-default"
    if not api_url or not api_key:
        raise RuntimeError("Noema LLM review unavailable: NOEMA_LLM_API_URL or NOEMA_LLM_API_KEY is not configured.")
    if not (api_url.lower().startswith("http://") or api_url.lower().startswith("https://")):
        raise ValueError(
            "URL scheme must be http or https; NOEMA_LLM_API_URL must start "
            "with http:// or https:// to prevent SSRF vulnerabilities"
        )
    parsed = urllib.parse.urlparse(api_url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("URL scheme must be http or https; NOEMA_LLM_API_URL must start with http:// or https://")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("URL must have a valid hostname")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        raise ValueError("URL cannot target localhost")
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        pass
    else:
        for result in addrinfo:
            ip_str = result[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
                raise ValueError("URL cannot target internal IP addresses")

    prompt = {
        "role": "user",
        "content": "\n".join(
            [
                "You are Noema, an independent pull request reviewer for ContextualWisdomLab.",
                "Review the PR diff plus the additional changed-file, review-thread, and CodeGraph context for correctness, security, maintainability, and behavioral regressions.",
                "Return only JSON with this shape:",
                '{"decision":"approve|request_changes|comment","summary":"...","findings":[{"severity":"high|medium|low","file":"path","line":1,"message":"..."}]}',
                "Use request_changes only for blocking, concrete issues. Use approve when no blocking issue is found.",
                f"Repository: {repo}",
                f"PR: #{number}",
                f"Title: {pr.get('title') or ''}",
                f"Head SHA: {pr.get('headRefOid') or ''}",
                f"Diff truncated: {truncated}",
                "Additional context:",
                review_context or "No additional context was available.",
                "Diff:",
                diff,
            ]
        ),
    }
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": "Return strict JSON only. Do not include markdown."},
            prompt,
        ],
    }
    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(NoRedirectHandler())
    with opener.open(request, timeout=120) as response:  # nosec B310
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    verdict = extract_json_object(content)
    decision = str(verdict.get("decision") or "").strip().lower()
    if decision not in {"approve", "request_changes", "comment"}:
        raise RuntimeError(f"Noema LLM returned unsupported decision: {decision!r}")
    return verdict


def format_findings(findings: Any) -> list[str]:
    """Format bounded LLM findings for a GitHub review body."""
    if not isinstance(findings, list):
        return []
    lines: list[str] = []
    for finding in findings[:20]:
        if not isinstance(finding, dict):
            continue
        severity = str(finding.get("severity") or "info")
        file_name = str(finding.get("file") or "unknown")
        line = finding.get("line")
        location = f"{file_name}:{line}" if isinstance(line, int) and line > 0 else file_name
        message = str(finding.get("message") or "").strip()
        if message:
            lines.append(f"- [{severity}] {location}: {message}")
    return lines


def submit_review(repo: str, number: int, pr: dict[str, Any], actor: str, verdict: dict[str, Any]) -> None:
    """Submit the Noema review verdict to the pull request."""
    head_sha = str(pr.get("headRefOid") or "")
    decision = str(verdict.get("decision") or "comment").lower()
    event = "APPROVE" if decision == "approve" else "REQUEST_CHANGES" if decision == "request_changes" else "COMMENT"
    source = os.environ.get("NOEMA_REVIEW_TOKEN_SOURCE") or "NOEMA_REVIEW_TOKEN"
    summary = str(verdict.get("summary") or "Noema completed an independent LLM review.").strip()
    findings = format_findings(verdict.get("findings"))
    body = "\n".join(
        [
            "## Noema LLM review",
            "",
            summary,
            "",
            "### Findings",
            *(findings or ["- No blocking findings."]),
            "",
            f"- Result: {event}",
            f"- Head SHA: `{head_sha}`",
            f"- Reviewer credential: `{source}`",
            f"- Actor: `{actor or 'unknown'}`",
            "",
            f"<!-- noema-review-gate head_sha={head_sha} decision={decision} -->",
        ]
    )
    payload = {
        "commit_id": head_sha,
        "event": event,
        "body": body,
    }
    run(
        ["gh", "api", "-X", "POST", f"repos/{repo}/pulls/{number}/reviews", "--input", "-"],
        stdin=json.dumps(payload),
    )
    print(f"Noema {event} review submitted for {repo}#{number} at {head_sha}.")


def inspect_and_review(repo: str, number: int) -> int:
    """Inspect PR state and submit Noema's LLM review when gates are clean."""
    pr = fetch_pr(repo, number)
    actor = current_actor()
    if actor in PRIMARY_REVIEW_AUTHORS:
        print(
            f"Current token actor {actor!r} is already a primary review actor; "
            "Noema review skipped so GitHub receives an independent reviewer."
        )
        return 0
    if pr.get("isDraft"):
        print("PR is draft; Noema review skipped.")
        return 0
    if not current_primary_approval(pr):
        print(
            "Current head does not have a primary OpenCode approval; "
            "Noema cannot skip as success because that made the required "
            "check look like a review."
        )
        return 1
    if existing_noema_review(pr, actor):
        print("Current head already has a Noema review; nothing to do.")
        return 0
    if has_current_changes_requested(pr):
        print("Current head has requested changes; Noema review skipped.")
        return 0
    if has_unresolved_threads(pr):
        print("PR has unresolved review threads; Noema review skipped.")
        return 0
    blockers = blocking_checks(pr)
    if blockers:
        print("Blocking checks remain; Noema review skipped:")
        for blocker in blockers:
            print(f"- {blocker}")
        return 0
    diff, truncated = fetch_diff(repo, number)
    review_context = build_review_context(repo, number, pr)
    verdict = call_llm(repo, number, pr, diff, truncated, review_context)
    submit_review(repo, number, pr, actor, verdict)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse Noema review gate command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Run the Noema review gate command."""
    args = parse_args(argv)
    if args.pr_number <= 0:
        raise SystemExit("--pr-number must be positive")
    return inspect_and_review(args.repo, args.pr_number)


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main(sys.argv[1:]))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
