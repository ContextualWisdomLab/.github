#!/usr/bin/env python3
"""Run Noema LLM review and submit a non-OpenCode PR review verdict."""

from __future__ import annotations

import argparse
import ast
import base64
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from typing import Any

from scripts.ci.opencode_review_normalize_output import changed_file_is_material


PRIMARY_REVIEW_AUTHORS = {
    "opencode-agent[bot]",
    "opencode-agent",
}
GITHUB_APP_BOT_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\[bot\]$")
MAX_DIFF_CHARS = 60000
MAX_CONTEXT_FILES = 12
MAX_FILE_CONTEXT_CHARS = 4000
MAX_REVIEW_CONTEXT_CHARS = 24000
MAX_THREAD_BODY_CHARS = 1200
DIFF_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")

ORCHESTRATOR_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
ORCHESTRATOR_BASE_ENV = "CONTEXTUAL_ORCHESTRATOR_BASE_URL"
# The standing operating directive already accepts central Strix/OpenCode/Noema
# review latency exceeding two hours per model (docs/product-goal-directive.md),
# and the repo owner separately raised the floor to at least three hours
# (owner comment, ContextualWisdomLab/.github#1438, 2026-09-01). Unlike the
# sidecar's own preflight self-check (ADR-0005, deliberately kept at
# 120s with its own bounded same-budget retry), this single call has no retry
# of its own -- a live reproduction (naruon#1486, job 99690488248, 2026-09-01)
# shows the gateway's own routing pool degraded (11/12 candidates rejected)
# picking its one remaining "ready" agent, whose real completion for a full PR
# diff then ran past the old 120s bound with nothing to fall back to, failing
# the entire required review. 10800s gives the gateway's own internal
# retry/failover machinery room to land on a working agent instead.
NOEMA_LLM_REQUEST_TIMEOUT_SECONDS = 10800
# The noema-review job carries no explicit timeout-minutes, so it is bounded
# only by the 360-minute (6h) maximum job execution time GitHub-hosted
# runners allow. call_llm can recurse once for a single validator-rejected
# repair (see the repair_error branch below); two independent
# NOEMA_LLM_REQUEST_TIMEOUT_SECONDS calls would total 21600s -- exactly that
# 6h ceiling, leaving zero room for sidecar provisioning or job cleanup and
# turning a fast 120s failure into a reliable 6h one (Devin Review,
# ContextualWisdomLab/.github#1438). This is the shared deadline across the
# initial call AND its one possible repair call combined: each call's own
# request timeout is capped to whatever remains of it.
NOEMA_LLM_TOTAL_BUDGET_SECONDS = 19800

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
    """Return the verified user or GitHub App bot login for the active token."""
    action_actor = os.environ.get("NOEMA_REVIEW_ACTOR", "").strip()
    installation_id = os.environ.get("NOEMA_REVIEW_INSTALLATION_ID", "").strip()
    if action_actor or installation_id:
        if (
            os.environ.get("NOEMA_REVIEW_TOKEN_SOURCE") != "noema-review-github-app"
            or not GITHUB_APP_BOT_RE.fullmatch(action_actor)
            or not installation_id.isdigit()
        ):
            raise RuntimeError("Noema GitHub App identity binding is invalid")
        return action_actor
    for args, suffix in (
        (["gh", "api", "user", "--jq", ".login"], ""),
        (["gh", "api", "/installation", "--jq", ".app_slug"], "[bot]"),
    ):
        try:
            identity = run(args).strip()
        except Exception:
            continue
        if identity:
            return f"{identity}{suffix}"
    return ""


def fetch_diff(repo: str, number: int) -> tuple[str, bool]:
    """Fetch the PR diff and truncate it to the bounded LLM prompt size."""
    diff = run(["gh", "api", f"repos/{repo}/pulls/{number}", "-H", "Accept: application/vnd.github.v3.diff"])
    truncated = len(diff) > MAX_DIFF_CHARS
    if truncated:
        diff = diff[:MAX_DIFF_CHARS]
    return diff, truncated


def changed_diff_locations(diff: str) -> set[tuple[str, int, str]]:
    """Return exact LEFT/RIGHT changed-line locations from a unified diff."""
    locations: set[tuple[str, int, str]] = set()
    old_path = new_path = ""
    old_line = new_line = 0
    in_hunk = False
    for raw_line in diff.splitlines():
        if raw_line.startswith("diff --git "):
            old_path = new_path = ""
            in_hunk = False
            continue
        if not in_hunk and raw_line.startswith("--- "):
            old_path = parse_diff_path(raw_line[4:], "a/")
            in_hunk = False
            continue
        if not in_hunk and raw_line.startswith("+++ "):
            new_path = parse_diff_path(raw_line[4:], "b/")
            in_hunk = False
            continue
        match = DIFF_HUNK_RE.match(raw_line)
        if match:
            old_line, new_line = map(int, match.groups())
            in_hunk = True
            continue
        if not in_hunk or raw_line.startswith("\\ No newline"):
            continue
        if raw_line.startswith("+"):
            if not new_path:
                return set()
            locations.add((new_path, new_line, "RIGHT"))
            new_line += 1
        elif raw_line.startswith("-"):
            if not old_path:
                return set()
            locations.add((old_path, old_line, "LEFT"))
            old_line += 1
        else:
            old_line += 1
            new_line += 1
    return locations


def parse_diff_path(raw: str, prefix: str) -> str:
    """Decode a Git unified-diff path, including C-quoted UTF-8 paths."""
    value = raw.split("\t", 1)[0]
    if value == "/dev/null":
        return ""
    if value.startswith('"'):
        try:
            decoded = ast.literal_eval(value)
            value = decoded.encode("latin-1").decode("utf-8")
        except (SyntaxError, ValueError, UnicodeError):
            return ""
    return value.removeprefix(prefix)


def validate_substantive_verdict(
    verdict: dict[str, Any], diff: str, changed_paths: Sequence[str] = ()
) -> None:
    """Reject formal verdicts without changed-line and adversarial evidence."""
    decision = str(verdict.get("decision") or "").lower()
    if decision == "comment":
        return
    locations = changed_diff_locations(diff)
    if not locations:
        raise RuntimeError("Noema formal verdict requires parseable changed-line evidence")

    reviewed_lines = verdict.get("reviewed_lines")
    if not isinstance(reviewed_lines, list) or not reviewed_lines:
        raise RuntimeError("Noema formal verdict requires at least one reviewed changed line")
    for index, reviewed in enumerate(reviewed_lines, start=1):
        if not isinstance(reviewed, dict):
            raise RuntimeError(f"Noema reviewed line {index} must be an object")
        location = (reviewed.get("path"), reviewed.get("line"), reviewed.get("side"))
        if location not in locations:
            raise RuntimeError(f"Noema reviewed line {index} is not an exact changed-side line")
        analysis = reviewed.get("analysis")
        if not isinstance(analysis, str) or not analysis.strip():
            raise RuntimeError(f"Noema reviewed line {index} requires concrete analysis")

    validation = verdict.get("adversarial_validation")
    if not isinstance(validation, dict):
        raise RuntimeError("Noema formal verdict requires adversarial_validation")
    status = validation.get("status")
    expected_status = "passed" if decision == "approve" else "failed"
    if status != expected_status:
        raise RuntimeError(f"Noema {decision} requires adversarial_validation.status={expected_status}")
    residual_risk = validation.get("residual_risk")
    if not isinstance(residual_risk, str) or not residual_risk.strip():
        raise RuntimeError("Noema adversarial validation requires residual_risk")
    probes = validation.get("probes")
    all_changed_paths = set(changed_paths) or {path for path, _line, _side in locations}
    required_probes = 2 if any(changed_file_is_material(path) for path in all_changed_paths) else 1
    if not isinstance(probes, list) or len(probes) < required_probes:
        raise RuntimeError(f"Noema adversarial validation requires at least {required_probes} concrete probe(s)")

    confirmed: set[tuple[str, int, str]] = set()
    identities: set[tuple[Any, ...]] = set()
    for index, probe in enumerate(probes, start=1):
        if not isinstance(probe, dict):
            raise RuntimeError(f"Noema adversarial probe {index} must be an object")
        location = (probe.get("path"), probe.get("line"), probe.get("side"))
        if location not in locations:
            raise RuntimeError(f"Noema adversarial probe {index} is not an exact changed-side line")
        for field in ("hypothesis", "attack_or_counterexample", "evidence"):
            value = probe.get(field)
            if not isinstance(value, str) or not value.strip():
                raise RuntimeError(f"Noema adversarial probe {index} requires {field}")
        outcome = probe.get("outcome")
        if outcome not in {"falsified", "confirmed"}:
            raise RuntimeError(f"Noema adversarial probe {index} outcome must be falsified or confirmed")
        identity = (*location, probe["hypothesis"].strip().casefold(), probe["attack_or_counterexample"].strip().casefold())
        if identity in identities:
            raise RuntimeError(f"Noema adversarial probe {index} duplicates an earlier probe")
        identities.add(identity)
        if outcome == "confirmed":
            confirmed.add((str(probe["path"]), int(probe["line"]), str(probe["side"])))

    if decision == "approve" and confirmed:
        raise RuntimeError("Noema approve cannot contain a confirmed adversarial probe")
    if decision == "request_changes":
        finding_locations = {
            (str(finding.get("file") or ""), finding.get("line"), str(finding.get("side") or ""))
            for finding in verdict.get("findings") or []
            if isinstance(finding, dict)
        }
        if not confirmed or not confirmed.intersection(finding_locations):
            raise RuntimeError("Noema request_changes requires a confirmed probe on a published finding")


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
    if stripped.startswith("{"):
        return json.loads(stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise RuntimeError("Noema LLM response did not contain a JSON object")
    return json.loads(stripped[start : end + 1])


def _truthy_env(name: str) -> bool:
    """Return whether a process environment flag is an explicit truthy value."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _is_loopback_literal_host(hostname: str) -> bool:
    """Return whether hostname is the sidecar loopback literal 127.0.0.1 or ::1."""
    return hostname in ORCHESTRATOR_LOOPBACK_HOSTS


def _http_origin(parsed: urllib.parse.ParseResult) -> tuple[str, str, int] | None:
    """Return scheme, hostname, and port for a credential-free http(s) URL."""
    scheme = (parsed.scheme or "").lower()
    hostname = (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not hostname:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    try:
        port = parsed.port
    except ValueError:
        return None
    if port is None:
        port = 443 if scheme == "https" else 80
    return (scheme, hostname, port)


def is_allowed_orchestrator_sidecar_url(api_url: str) -> bool:
    """Return True only for the process-local orchestrator sidecar loopback origin.

    ``localhost`` and other private hosts stay rejected. A loopback literal
    (``127.0.0.1`` / ``::1``) is allowed only when it matches the exact
    ``CONTEXTUAL_ORCHESTRATOR_BASE_URL`` origin. The via-orchestrator marker is
    metadata only and never widens this allowlist.
    """
    origin = _http_origin(urllib.parse.urlparse(api_url))
    if origin is None:
        return False
    scheme, hostname, port = origin
    if not _is_loopback_literal_host(hostname):
        return False
    sidecar = os.environ.get(ORCHESTRATOR_BASE_ENV, "").strip()
    if not sidecar:
        return False
    sidecar_origin = _http_origin(urllib.parse.urlparse(sidecar))
    if sidecar_origin is None:
        return False
    sidecar_scheme, sidecar_host, sidecar_port = sidecar_origin
    if not _is_loopback_literal_host(sidecar_host):
        return False
    return (scheme, hostname, port) == (sidecar_scheme, sidecar_host, sidecar_port)


def reject_private_llm_url(api_url: str) -> None:
    """Reject non-sidecar localhost, private, and non-http(s) LLM targets."""
    if not (api_url.lower().startswith("http://") or api_url.lower().startswith("https://")):
        raise ValueError(
            "URL scheme must be http or https; NOEMA_LLM_API_URL must start "
            "with http:// or https:// to prevent SSRF vulnerabilities"
        )
    parsed = urllib.parse.urlparse(api_url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(
            "URL scheme must be http or https; NOEMA_LLM_API_URL must start "
            "with http:// or https://"
        )
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("URL must have a valid hostname")
    if is_allowed_orchestrator_sidecar_url(api_url):
        return
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


def call_llm(
    repo: str,
    number: int,
    pr: dict[str, Any],
    diff: str,
    truncated: bool,
    review_context: str = "",
    changed_paths: Sequence[str] = (),
    repair_error: str = "",
    deadline: float | None = None,
) -> dict[str, Any]:
    """Call the configured OpenAI-compatible LLM endpoint for a review verdict."""
    if deadline is None:
        deadline = time.monotonic() + NOEMA_LLM_TOTAL_BUDGET_SECONDS
    # deadline is an absolute monotonic timestamp shared across the initial
    # call and its one possible repair call, by design: response parsing and
    # validate_substantive_verdict's own processing time between them also
    # count against it, not just network time, so the shared wall-clock
    # ceiling holds regardless of where the time goes.
    remaining_budget = deadline - time.monotonic()
    if remaining_budget <= 0:
        raise TimeoutError("Noema LLM review exhausted its total request budget")
    request_timeout = min(NOEMA_LLM_REQUEST_TIMEOUT_SECONDS, remaining_budget)
    api_url = os.environ.get("NOEMA_LLM_API_URL", "").strip()
    api_key = os.environ.get("NOEMA_LLM_API_KEY", "").strip()
    model = os.environ.get("NOEMA_LLM_MODEL", "").strip() or "noema-default"
    if not api_url or not api_key:
        raise RuntimeError("Noema LLM review unavailable: NOEMA_LLM_API_URL or NOEMA_LLM_API_KEY is not configured.")
    reject_private_llm_url(api_url)

    prompt = {
        "role": "user",
        "content": "\n".join(
            [
                "You are Noema, an independent pull request reviewer for ContextualWisdomLab.",
                "Review the PR diff plus the additional changed-file, review-thread, and CodeGraph context for correctness, security, maintainability, and behavioral regressions.",
                "Return only JSON with this shape:",
                '{"decision":"approve|request_changes|comment","summary":"...","reviewed_lines":[{"path":"path","line":1,"side":"RIGHT|LEFT","analysis":"..."}],"adversarial_validation":{"status":"passed|failed","residual_risk":"...","probes":[{"path":"path","line":1,"side":"RIGHT|LEFT","hypothesis":"...","attack_or_counterexample":"...","evidence":"observed or source-traced result","outcome":"falsified|confirmed"}]},"findings":[{"severity":"high|medium|low","file":"path","line":1,"side":"RIGHT|LEFT","message":"..."}]}',
                "Every formal verdict must cite exact changed-side lines. APPROVE requires falsifying concrete regression hypotheses; source or test changes require at least two distinct probes and other changes require at least one. REQUEST_CHANGES requires a confirmed probe at a finding location.",
                "Use request_changes only for blocking, concrete issues. A generic no-issues statement is not review evidence.",
                *(
                    [
                        f"Your prior verdict was rejected by the trusted validator: {repair_error}",
                        "Return one corrected JSON verdict using only exact changed-side locations from the supplied diff.",
                    ]
                    if repair_error
                    else []
                ),
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
    with opener.open(request, timeout=request_timeout) as response:  # nosec B310
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
    verdict = extract_json_object(content)
    decision = str(verdict.get("decision") or "").strip().lower()
    if decision not in {"approve", "request_changes", "comment"}:
        raise RuntimeError(f"Noema LLM returned unsupported decision: {decision!r}")
    summary = verdict.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise RuntimeError("Noema LLM response did not contain a substantive summary")
    findings = verdict.get("findings")
    if not isinstance(findings, list) or any(not isinstance(finding, dict) for finding in findings):
        raise RuntimeError("Noema LLM response findings must be a list of objects")
    for finding in findings:
        if (
            finding.get("severity") not in {"high", "medium", "low"}
            or not isinstance(finding.get("file"), str)
            or not finding["file"].strip()
            or type(finding.get("line")) is not int
            or finding["line"] <= 0
            or finding.get("side") not in {"RIGHT", "LEFT"}
            or not isinstance(finding.get("message"), str)
            or not finding["message"].strip()
        ):
            raise RuntimeError("Noema LLM response contained a malformed finding")
    if decision == "request_changes" and not findings:
        raise RuntimeError("Noema LLM request_changes response did not contain a substantive finding")
    try:
        validate_substantive_verdict(verdict, diff, changed_paths)
    except RuntimeError as exc:
        if repair_error:
            raise
        return call_llm(
            repo,
            number,
            pr,
            diff,
            truncated,
            review_context,
            changed_paths,
            str(exc),
            deadline,
        )
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
        side = str(finding.get("side") or "")
        location = f"{file_name}:{line} ({side})" if isinstance(line, int) and line > 0 else file_name
        message = str(finding.get("message") or "").strip()
        if message:
            lines.append(f"- [{severity}] {location}: {message}")
    return lines


def format_review_evidence(verdict: dict[str, Any]) -> list[str]:
    """Render the bounded changed-line analyses and adversarial probes."""
    lines = ["### Reviewed changed lines"]
    for reviewed in (verdict.get("reviewed_lines") or [])[:20]:
        if isinstance(reviewed, dict):
            lines.append(
                f"- `{reviewed.get('path')}:{reviewed.get('line')} ({reviewed.get('side')})`: "
                f"{str(reviewed.get('analysis') or '').strip()}"
            )
    validation = verdict.get("adversarial_validation") or {}
    lines.extend(["", "### Adversarial validation"])
    for probe in (validation.get("probes") or [])[:20]:
        if isinstance(probe, dict):
            lines.append(
                f"- `{probe.get('path')}:{probe.get('line')} ({probe.get('side')})` "
                f"{probe.get('outcome')}: {str(probe.get('hypothesis') or '').strip()} — "
                f"{str(probe.get('evidence') or '').strip()}"
            )
    lines.append(f"- Residual risk: {str(validation.get('residual_risk') or '').strip()}")
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
            *format_review_evidence(verdict),
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
    """Inspect PR state and submit Noema's independent LLM review."""
    pr = fetch_pr(repo, number)
    actor = current_actor()
    if not actor:
        raise RuntimeError("Noema reviewer identity could not be verified")
    if actor in PRIMARY_REVIEW_AUTHORS:
        raise RuntimeError(
            f"Current token actor {actor!r} is already a primary review actor; "
            "Noema requires an independent reviewer credential."
        )
    if pr.get("isDraft"):
        print("PR is draft; Noema review skipped.")
        return 0
    if existing_noema_review(pr, actor):
        print("Current head already has a Noema review; nothing to do.")
        return 0
    diff, truncated = fetch_diff(repo, number)
    changed_paths = fetch_changed_file_paths(repo, number)
    review_context = build_review_context(repo, number, pr)
    verdict = call_llm(repo, number, pr, diff, truncated, review_context, changed_paths)
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
