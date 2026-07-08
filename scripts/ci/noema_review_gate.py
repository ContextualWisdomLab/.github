#!/usr/bin/env python3
"""Run Noema LLM review and submit a non-OpenCode PR review verdict."""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import urllib.parse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


PRIMARY_REVIEW_AUTHORS = {
    "opencode-agent[bot]",
    "opencode-agent",
    "github-actions[bot]",
}
PRIMARY_REVIEW_MARKERS = (
    "OpenCode reviewed the current-head bounded evidence and found no blocking issues.",
    "Result: APPROVE",
    "opencode-review-control-v1",
)
IGNORED_RUNNING_CHECKS = {
    "approve-after-primary-review",
    "noema-review",
    "Required Noema Review",
}
FAILED_CONCLUSIONS = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
RUNNING_STATES = {"QUEUED", "IN_PROGRESS", "PENDING", "REQUESTED", "WAITING", "EXPECTED"}
MAX_DIFF_CHARS = 60000
DEFAULT_TOOL_FILE_CHARS = 200000

NOEMA_SYSTEM_PROMPT = (
    "You are Noema, an independent, complementary pull request reviewer for ContextualWisdomLab. "
    "A primary reviewer (OpenCode) has already approved the current head against the bounded diff, "
    "so restating diff-visible issues adds no value. Differentiate by investigating impact radius and "
    "cross-file correctness with your read-only tools: fetch full file contents when a diff is truncated "
    "or its cross-file behavior is unclear, read prior review threads to avoid repeating resolved feedback, "
    "and query the CodeGraph index for caller/impact context when it is available. Return request_changes "
    "only for concrete, blocking issues on the current head; otherwise approve, or comment for non-blocking "
    "observations."
)

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
        nodes { isResolved isOutdated }
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


def current_primary_approval(pr: dict[str, Any]) -> dict[str, Any] | None:
    """Return the current-head OpenCode approval when it matches the contract."""
    head_sha = str(pr.get("headRefOid") or "")
    reviews = (((pr.get("reviews") or {}).get("nodes")) or [])
    for review in reversed(reviews):
        if review_commit(review) != head_sha:
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
        if review_commit(review) == head_sha and str(review.get("state") or "").upper() == "CHANGES_REQUESTED":
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
        if review_author(review) == actor or marker in str(review.get("body") or ""):
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


@dataclass(frozen=True)
class NoemaSettings:
    """Immutable Noema configuration resolved from the KV/settings source."""

    llm_api_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "noema-default"
    review_token_source: str = "NOEMA_REVIEW_TOKEN"
    codegraph_index_path: str = ""
    max_tool_file_chars: int = DEFAULT_TOOL_FILE_CHARS


def _settings_snapshot(env: Mapping[str, str] | None) -> Mapping[str, str]:
    """Return the raw settings snapshot from an explicit source, a KV export, or the process boundary."""
    if env is not None:
        return env
    raw = os.environ.get("NOEMA_SETTINGS_JSON", "").strip()
    if raw:
        loaded = json.loads(raw)
        return {str(key): str(value) for key, value in loaded.items()}
    return os.environ


def load_settings(env: Mapping[str, str] | None = None) -> NoemaSettings:
    """Load Noema settings from the KV/settings source instead of scattered os.getenv reads."""
    snapshot = _settings_snapshot(env)

    def _get(key: str) -> str:
        """Return a trimmed string value from the settings snapshot for a single key."""
        return str(snapshot.get(key, "") or "").strip()

    raw_max = _get("NOEMA_TOOL_MAX_FILE_CHARS")
    try:
        max_tool_file_chars = int(raw_max) if raw_max else DEFAULT_TOOL_FILE_CHARS
    except ValueError:
        max_tool_file_chars = DEFAULT_TOOL_FILE_CHARS
    return NoemaSettings(
        llm_api_url=_get("NOEMA_LLM_API_URL"),
        llm_api_key=_get("NOEMA_LLM_API_KEY"),
        llm_model=_get("NOEMA_LLM_MODEL") or "noema-default",
        review_token_source=_get("NOEMA_REVIEW_TOKEN_SOURCE") or "NOEMA_REVIEW_TOKEN",
        codegraph_index_path=_get("NOEMA_CODEGRAPH_INDEX_PATH"),
        max_tool_file_chars=max_tool_file_chars,
    )


class ReviewFinding(BaseModel):
    """A single Noema finding matching the historical {severity,file,line,message} shape."""

    severity: Literal["high", "medium", "low"] = "low"
    file: str = "unknown"
    line: int | None = None
    message: str = ""


class ReviewVerdict(BaseModel):
    """Structured Noema verdict matching the historical {decision,summary,findings[]} schema."""

    decision: Literal["approve", "request_changes", "comment"]
    summary: str = ""
    findings: list[ReviewFinding] = Field(default_factory=list)


@dataclass
class ReviewDeps:
    """Read-only dependencies exposed to Noema agent tools for a single PR review."""

    repo: str
    number: int
    head_sha: str
    settings: NoemaSettings


def validate_llm_endpoint(api_url: str) -> None:
    """Validate the configured LLM endpoint URL to prevent SSRF to internal targets."""
    parsed = urllib.parse.urlparse(api_url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("URL scheme must be http or https")
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("URL must have a valid hostname")
    if hostname in {"localhost", "localhost.localdomain"} or hostname.endswith(".localhost"):
        raise ValueError("URL cannot target localhost")
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return
    for result in addrinfo:
        ip_str = result[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise ValueError("URL cannot target internal IP addresses")


def derive_openai_base_url(api_url: str) -> str:
    """Derive an OpenAI-compatible base URL from the configured chat-completions endpoint."""
    trimmed = api_url.strip().rstrip("/")
    suffix = "/chat/completions"
    if trimmed.endswith(suffix):
        trimmed = trimmed[: -len(suffix)]
    return trimmed or api_url.strip()


def _tool_error(prefix: str, exc: Exception) -> str:
    """Return a scrubbed, agent-visible error string for a failed read-only tool call."""
    return f"error: {prefix}: {scrub_sensitive_data(str(exc)) or 'command failed'}"


def tool_fetch_changed_file(deps: ReviewDeps, path: str) -> str:
    """Return the full current-head contents of a changed file beyond the diff truncation."""
    clean = path.strip()
    if not clean or clean.startswith("/") or ".." in clean.split("/"):
        return f"error: refusing to fetch unsafe path {path!r}"
    quoted = urllib.parse.quote(clean)
    args = ["gh", "api", f"repos/{deps.repo}/contents/{quoted}", "-H", "Accept: application/vnd.github.raw"]
    if deps.head_sha:
        args.extend(["-f", f"ref={deps.head_sha}"])
    try:
        content = run(args)
    except RuntimeError as exc:
        return _tool_error(f"unable to fetch {clean}", exc)
    limit = deps.settings.max_tool_file_chars
    if len(content) > limit:
        content = content[:limit] + "\n...[truncated]..."
    return content


def tool_fetch_review_threads(deps: ReviewDeps) -> str:
    """Return prior inline review comments so Noema complements rather than repeats them."""
    try:
        raw = run(["gh", "api", f"repos/{deps.repo}/pulls/{deps.number}/comments", "--paginate"])
    except RuntimeError as exc:
        return _tool_error("unable to fetch review threads", exc)
    try:
        comments = json.loads(raw) if raw.strip() else []
    except json.JSONDecodeError:
        return "error: review thread response was not valid JSON"
    lines: list[str] = []
    for comment in comments[:50]:
        if not isinstance(comment, dict):
            continue
        author = ((comment.get("user") or {}).get("login")) or "unknown"
        comment_path = comment.get("path") or "unknown"
        comment_line = comment.get("line") or comment.get("original_line")
        body = str(comment.get("body") or "").strip().replace("\n", " ")
        location = f"{comment_path}:{comment_line}" if comment_line else str(comment_path)
        lines.append(f"- {author} @ {location}: {body}")
    return "\n".join(lines) if lines else "No prior inline review comments."


def tool_query_codegraph(deps: ReviewDeps, query: str) -> str:
    """Query the target repo CodeGraph index for caller/impact context when configured."""
    index = deps.settings.codegraph_index_path.strip()
    if not index:
        return "CodeGraph index is not configured; impact-radius lookups are unavailable."
    cleaned = query.strip()
    if not cleaned:
        return "error: codegraph query was empty"
    try:
        return run(["codegraph", "explore", "-p", index, cleaned])
    except RuntimeError as exc:
        return _tool_error("codegraph query failed", exc)


def build_review_prompt(repo: str, number: int, pr: dict[str, Any], diff: str, truncated: bool) -> str:
    """Build the initial Noema review instruction referencing the bounded diff and available tools."""
    return "\n".join(
        [
            f"Repository: {repo}",
            f"PR: #{number}",
            f"Title: {pr.get('title') or ''}",
            f"Head SHA: {pr.get('headRefOid') or ''}",
            f"Diff truncated at {MAX_DIFF_CHARS} chars: {truncated}",
            "Investigate impact radius and cross-file correctness using your read-only tools before deciding.",
            "Diff:",
            diff,
        ]
    )


def build_review_model(settings: NoemaSettings) -> Model:
    """Construct an OpenAI-compatible chat model from validated Noema settings."""
    provider = OpenAIProvider(base_url=derive_openai_base_url(settings.llm_api_url), api_key=settings.llm_api_key)
    return OpenAIChatModel(settings.llm_model, provider=provider)


def build_review_agent(settings: NoemaSettings, model: Model | None = None) -> Agent[ReviewDeps, ReviewVerdict]:
    """Build the Noema Pydantic-AI review agent with read-only PR inspection tools."""
    agent: Agent[ReviewDeps, ReviewVerdict] = Agent(
        model or build_review_model(settings),
        output_type=ReviewVerdict,
        deps_type=ReviewDeps,
        system_prompt=NOEMA_SYSTEM_PROMPT,
        retries=2,
    )

    @agent.tool
    def fetch_changed_file(ctx: RunContext[ReviewDeps], path: str) -> str:
        """Return the full current-head contents of a changed file (beyond the diff truncation)."""
        return tool_fetch_changed_file(ctx.deps, path)

    @agent.tool
    def fetch_review_threads(ctx: RunContext[ReviewDeps]) -> str:
        """Return prior inline review comments so Noema avoids duplicating resolved feedback."""
        return tool_fetch_review_threads(ctx.deps)

    @agent.tool
    def query_codegraph(ctx: RunContext[ReviewDeps], query: str) -> str:
        """Query the target repo CodeGraph index for caller/impact context (if configured)."""
        return tool_query_codegraph(ctx.deps, query)

    return agent


def call_llm(
    repo: str,
    number: int,
    pr: dict[str, Any],
    diff: str,
    truncated: bool,
    *,
    settings: NoemaSettings | None = None,
    agent: Agent[ReviewDeps, ReviewVerdict] | None = None,
) -> dict[str, Any] | None:
    """Run the Noema Pydantic-AI review agent and return a {decision,summary,findings} verdict."""
    resolved = settings if settings is not None else load_settings()
    if not resolved.llm_api_url or not resolved.llm_api_key:
        print("Noema LLM review unavailable: NOEMA_LLM_API_URL or NOEMA_LLM_API_KEY is not configured.")
        return None
    validate_llm_endpoint(resolved.llm_api_url)
    review_agent = agent if agent is not None else build_review_agent(resolved)
    deps = ReviewDeps(
        repo=repo,
        number=number,
        head_sha=str(pr.get("headRefOid") or ""),
        settings=resolved,
    )
    result = review_agent.run_sync(build_review_prompt(repo, number, pr, diff, truncated), deps=deps)
    return result.output.model_dump()


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


def submit_review(
    repo: str,
    number: int,
    pr: dict[str, Any],
    actor: str,
    verdict: dict[str, Any],
    settings: NoemaSettings | None = None,
) -> None:
    """Submit the Noema review verdict to the pull request."""
    head_sha = str(pr.get("headRefOid") or "")
    decision = str(verdict.get("decision") or "comment").lower()
    event = "APPROVE" if decision == "approve" else "REQUEST_CHANGES" if decision == "request_changes" else "COMMENT"
    source = (settings if settings is not None else load_settings()).review_token_source
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
    if existing_noema_review(pr, actor):
        print("Current head already has a Noema review; nothing to do.")
        return 0
    if not current_primary_approval(pr):
        print("Current head does not have a primary OpenCode approval; Noema review skipped.")
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
    settings = load_settings()
    verdict = call_llm(repo, number, pr, diff, truncated, settings=settings)
    if verdict is None:
        return 0
    submit_review(repo, number, pr, actor, verdict, settings=settings)
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
