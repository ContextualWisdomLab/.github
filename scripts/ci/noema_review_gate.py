#!/usr/bin/env python3
"""Run Noema LLM review and submit a non-OpenCode PR review verdict."""

from __future__ import annotations

import argparse
import ast
import base64
import http.client
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import threading
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

# This org's own recorded policy (docs/product-goal-directive.md line 65: "중앙 OpenCode, Strix,
# Noema는 모델당 두 시간 이상 걸릴 수 있음을 수용한다" -- central OpenCode, Strix, and Noema may
# legitimately take over two hours PER MODEL CALL, and the org accepts this) is stated per model
# call, not per review. A prior fix here (docs/product-technical-gap-baseline.md's 2026-08-31
# "recurring noema-review TimeoutError" entry) set this to 3600s, reasoning that call_llm's
# at-most-one repair-retry recursion made "two 1-hour attempts" equal the org's two-hour policy --
# that reasoning was itself a bug (Devin Review on ContextualWisdomLab/.github#1509): the repair
# retry only fires when the model's response FAILS validate_substantive_verdict (a content problem),
# never because the HTTP call itself ran long, so a single genuinely-slow-but-healthy call needing,
# say, 90 minutes would hit a 3600s timeout and fail even though it never needed a retry and stayed
# well within the org's per-model allowance. Each attempt -- the original call or the repair retry --
# is its own independent model call under this policy and must each get the full two-hour bound, not
# half of it split across the two. This is not merely policy-literal, either: read against evidence,
# the repair-retry prompt (see the `repair_error` branch in call_llm's prompt construction below)
# resends the SAME full diff and SAME full review_context as the original attempt, appending only two
# short instruction lines -- it asks the model to redo the entire review with corrected evidence, not
# a small patch -- so there is no evidence a repair attempt is typically cheaper or faster than the
# original call, and therefore no basis for giving it a smaller budget than the original.
LLM_REQUEST_TIMEOUT_SECONDS = 7200

# call_llm recurses at most once: the recursive call passes `repair_error`, and the
# `if repair_error: raise` guard immediately below the recursive call prevents a second recursion, so
# one review's worst-case call_llm duration is exactly two attempts at the full per-attempt bound
# above. Named so the two-attempt worst case is asserted and documented independently of the
# per-attempt value (tests/test_noema_review_gate.py pins both separately, per Devin Review's request
# to assert per-attempt and overall budgets separately rather than only their product). Sidecar
# startup/preflight (ADR-0005: up to ~180s healthz wait plus up to ~360s of Layer-2 gateway retries),
# diff/context fetch, and verdict submission add well under one more hour on top of this total, so
# noema-review.yml's `noema-review` job declares an explicit `timeout-minutes` safely above this bound
# instead of relying on GitHub Actions' implicit 360-minute (6-hour) default.
LLM_REQUEST_TOTAL_BUDGET_SECONDS = LLM_REQUEST_TIMEOUT_SECONDS * 2

ORCHESTRATOR_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
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


def _response_raw_socket(response: Any) -> Any | None:
    """Return the underlying socket of an open urllib HTTP response, or None.

    Used only to force-interrupt a still-blocked read once the monotonic
    deadline passes (see ``_read_response_body_within_deadline``). Not every
    response-like object exposes this (test doubles, for instance), so
    callers must tolerate ``None`` and fall back to the pre-read deadline
    check alone -- the same bound ``call_llm`` already applied before this
    helper existed.
    """
    try:
        return response.fp.raw._sock  # noqa: SLF001
    except AttributeError:
        return None


def _arm_deadline_watchdog(raw_socket: Any, remaining: float) -> tuple[threading.Timer | None, threading.Event]:
    """Arm a watchdog that force-closes ``raw_socket``'s read side once ``remaining`` elapses.

    Shared by every phase of a ``call_llm`` HTTP attempt that can block past
    its ``effective_deadline`` on the same underlying socket: ``connect()``
    (request transmission and status-line/header receipt happen on the same
    socket afterward, still inside the same ``opener.open()`` call -- see
    ``_deadline_guarded_connection`` below) and ``response.read()`` (see
    ``_read_response_body_within_deadline``). A socket ``timeout=`` only
    bounds each individual blocking operation (``connect()``, or one
    ``recv()``) against inactivity; a peer that keeps sending small amounts
    of data at intervals shorter than that per-op timeout can keep the whole
    call blocked far past an absolute deadline even though no single
    operation ever times out on its own.

    Uses ``shutdown(SHUT_RDWR)`` rather than ``close()`` because only the
    former reliably unblocks a concurrent blocking read on the same socket
    from another thread. ``remaining`` is clamped to zero so an
    already-elapsed deadline still arms an (immediately-firing) timer instead
    of silently skipping protection. Returns the started ``threading.Timer``
    (``None`` if ``raw_socket`` is ``None`` -- a socket-like object that
    doesn't exist yet or doesn't expose one, e.g. test doubles) and the
    ``threading.Event`` the timer sets when it fires, so the caller can
    distinguish "the deadline is why this call raised" from any other
    failure once the guarded operation returns or raises.
    """
    timed_out = threading.Event()
    watchdog: threading.Timer | None = None
    if raw_socket is not None:

        def _expire() -> None:
            """Mark the deadline as passed and force-close the read side."""
            timed_out.set()
            try:
                raw_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        watchdog = threading.Timer(max(remaining, 0.0), _expire)
        watchdog.daemon = True
        watchdog.start()
    return watchdog, timed_out


def _read_response_body_within_deadline(response: Any, deadline: float) -> bytes:
    """Read an HTTP response body without exceeding a monotonic deadline.

    ``opener.open(..., timeout=...)`` bounds only the connection phase and
    each individual blocking socket read (CPython's documented
    ``urllib.request``/``socket`` timeout semantics) -- it does not bound the
    total time spent in ``response.read()``. A server that keeps trickling
    small amounts of data at intervals shorter than that per-read timeout
    could otherwise keep ``response.read()`` blocked well past the caller's
    ``deadline`` -- ``call_llm`` passes the earlier of this attempt's own
    ``LLM_REQUEST_TIMEOUT_SECONDS`` bound and the outer
    ``LLM_REQUEST_TOTAL_BUDGET_SECONDS`` backstop, so this helper enforces
    whichever of the two is closer: ``io.BufferedReader.read()`` issues as
    many underlying socket reads as it takes to reach EOF, and each one
    individually satisfies the per-read timeout even though their sum does
    not, so re-checking the deadline only *between* whole ``read()`` calls
    would never see the pathological case in time.

    Instead, arm a watchdog timer (``_arm_deadline_watchdog``) for the
    remaining budget that force-closes the read side of the socket if it
    fires before ``response.read()`` returns on its own, then read the body
    in one call exactly as before. If the watchdog fired, raise the same
    bounded, fail-closed ``RuntimeError`` this module already uses
    elsewhere, whether the interrupted read raised an ``OSError`` or
    returned a truncated body without one.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError(
            "Noema LLM request exceeded LLM_REQUEST_TOTAL_BUDGET_SECONDS "
            "before the response body could be read"
        )
    raw_socket = _response_raw_socket(response)
    watchdog, timed_out = _arm_deadline_watchdog(raw_socket, remaining)
    try:
        body = response.read()
    except OSError as exc:
        if timed_out.is_set():
            raise RuntimeError(
                "Noema LLM request exceeded LLM_REQUEST_TOTAL_BUDGET_SECONDS "
                "while reading the response body"
            ) from exc
        raise
    finally:
        if watchdog is not None:
            watchdog.cancel()
    if timed_out.is_set():
        raise RuntimeError(
            "Noema LLM request exceeded LLM_REQUEST_TOTAL_BUDGET_SECONDS "
            "while reading the response body"
        )
    return body


def _deadline_guarded_connection(base: type, deadline: float, state: dict[str, Any]) -> type:
    """Build an ``http.client`` connection subclass that watchdog-guards ``connect()``.

    ``opener.open(request, timeout=...)`` -- covering TCP connect, TLS
    handshake, request transmission, and status-line/header receipt -- can
    itself be kept blocked well past ``effective_deadline`` by a peer that
    trickles response HEADER bytes slowly (one byte every ``timeout -
    epsilon`` seconds), for exactly the reason ``_arm_deadline_watchdog``'s
    docstring gives: ``timeout=`` bounds only each individual blocking
    socket operation, not the call's total wall time. This is the same
    vulnerability class ``_read_response_body_within_deadline`` already
    fixes for the body, one phase earlier (ContextualWisdomLab/.github#1509,
    Devin Review): that watchdog only starts once ``opener.open()`` has
    already returned, i.e. once headers are fully received, so it cannot
    protect anything that happens before then.

    ``urllib.request`` gives no way to guard ``opener.open()`` from the
    outside -- the socket it blocks on does not exist until a connection
    object is constructed deep inside it, and by the time ``opener.open()``
    returns or raises it is too late to have protected the call. So this
    subclasses the connection itself instead: the instant ``connect()``
    hands back a live socket, arm the same shared watchdog
    ``_read_response_body_within_deadline`` uses via
    ``_arm_deadline_watchdog``, on that exact socket. Request transmission
    and status-line/header receipt (``h.request()``/``h.getresponse()`` in
    ``AbstractHTTPHandler.do_open``) happen on that same socket immediately
    afterward, still inside this same ``connect()`` caller's
    ``opener.open()`` frame, so one watchdog covers both.

    ``state`` is a plain ``dict`` the caller owns and can always inspect
    afterward, whether ``opener.open()`` returns or raises, since the
    connection object itself is never handed back on either path -- see
    ``_open_response_within_deadline``, which interprets it.

    This does not, and cannot cheaply, extend the same guarantee to the TLS
    handshake that happens *inside* ``connect()`` for an HTTPS base class:
    the ``ssl`` module detaches the plain socket's file descriptor into a
    new ``SSLSocket`` partway through wrapping it, so a watchdog armed on
    the pre-wrap socket object would be shutting down an already-invalidated
    descriptor by the time a slow handshake is actually blocked, and a
    watchdog armed on the post-wrap ``SSLSocket`` cannot exist until the
    (synchronous, on-connect) handshake has already finished. See
    ``call_llm``'s docstring for why this is accepted as a known, reported
    residual gap rather than chased here.
    """

    class _DeadlineGuardedConnection(base):  # type: ignore[misc]
        """``base`` whose socket is watchdog-armed the instant ``connect()`` returns."""

        def connect(self) -> None:
            """Connect via the base class, then arm the shared deadline watchdog."""
            super().connect()
            state["watchdog"], state["timed_out"] = _arm_deadline_watchdog(
                self.sock, deadline - time.monotonic()
            )

    return _DeadlineGuardedConnection


class _DeadlineHTTPHandler(urllib.request.HTTPHandler):
    """HTTPHandler that opens connections via a caller-supplied connection class.

    Used by ``call_llm`` to swap in a ``_deadline_guarded_connection`` result
    without otherwise changing how ``urllib.request`` builds and issues the
    request (see ``_deadline_guarded_connection``'s docstring for why).
    """

    def __init__(self, connection_class: type) -> None:
        """Store the watchdog-guarded connection class to use for every request."""
        super().__init__()
        self._connection_class = connection_class

    def http_open(self, req: urllib.request.Request) -> Any:
        """Open the request using the watchdog-guarded HTTP connection class."""
        return self.do_open(self._connection_class, req)


class _DeadlineHTTPSHandler(urllib.request.HTTPSHandler):
    """HTTPSHandler that opens connections via a caller-supplied connection class.

    Mirrors ``_DeadlineHTTPHandler`` for ``https://`` targets, forwarding the
    same ``context``/``check_hostname`` a stock ``HTTPSHandler`` would so TLS
    verification behavior is unchanged.
    """

    def __init__(self, connection_class: type) -> None:
        """Store the watchdog-guarded connection class to use for every request."""
        super().__init__()
        self._connection_class = connection_class

    def https_open(self, req: urllib.request.Request) -> Any:
        """Open the request using the watchdog-guarded HTTPS connection class."""
        return self.do_open(
            self._connection_class,
            req,
            context=self._context,
            check_hostname=self._check_hostname,
        )


def _open_response_within_deadline(
    opener: urllib.request.OpenerDirector,
    request: urllib.request.Request,
    attempt_timeout: float,
    deadline: float,
    watchdog_state: dict[str, Any],
) -> Any:
    """Open ``request`` through ``opener``, failing closed if the header-phase deadline fires.

    ``opener`` must already be built with connection classes
    (``_deadline_guarded_connection`` via ``_DeadlineHTTPHandler`` /
    ``_DeadlineHTTPSHandler``) that populate ``watchdog_state["watchdog"]``
    and ``watchdog_state["timed_out"]`` the instant their socket connects --
    this function only interprets that state around the call, exactly as
    ``_read_response_body_within_deadline`` interprets its own watchdog's
    state around ``response.read()``. Mirrors that function's outcomes: an
    ``OSError`` raised after the watchdog fired becomes the module's
    bounded, fail-closed ``RuntimeError``; an ``OSError`` raised for an
    unrelated reason (including one raised before ``connect()`` ever ran,
    e.g. a DNS failure, when ``watchdog_state`` is still empty) propagates
    unchanged; and a response handed back despite the watchdog having
    already fired -- for example because its own ``shutdown()`` call failed
    -- is rejected rather than trusted.
    """
    try:
        response = opener.open(request, timeout=attempt_timeout)  # nosec B310
    except OSError as exc:
        timed_out = watchdog_state.get("timed_out")
        if timed_out is not None and timed_out.is_set():
            raise RuntimeError(
                "Noema LLM request exceeded LLM_REQUEST_TOTAL_BUDGET_SECONDS "
                "before the response headers could be read"
            ) from exc
        raise
    finally:
        watchdog = watchdog_state.get("watchdog")
        if watchdog is not None:
            watchdog.cancel()
    timed_out = watchdog_state.get("timed_out")
    if timed_out is not None and timed_out.is_set():
        raise RuntimeError(
            "Noema LLM request exceeded LLM_REQUEST_TOTAL_BUDGET_SECONDS "
            "before the response headers could be read"
        )
    return response


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
    """Call the configured OpenAI-compatible LLM endpoint for a review verdict.

    ``deadline`` is the outer ``call_start_time + LLM_REQUEST_TOTAL_BUDGET_SECONDS``
    ``time.monotonic()`` bound shared across the original attempt and its
    at-most-one repair retry -- a defense-in-depth backstop on the *pair*
    together, not a budget either attempt draws down from individually. Each
    attempt (the original call, and the repair retry if the model's response
    fails validation) instead gets its own fresh ``attempt_start_time`` here
    and its own full ``LLM_REQUEST_TIMEOUT_SECONDS`` from that point, per this
    org's per-model-call policy (see the comment above
    ``LLM_REQUEST_TIMEOUT_SECONDS``). An earlier version of this function
    reused the shared ``deadline`` directly as the response-read watchdog's
    deadline for both attempts, so a slow-but-healthy original attempt could
    run for up to the *entire* ``LLM_REQUEST_TOTAL_BUDGET_SECONDS`` before
    being cut off, silently starving a subsequent repair retry of its fair
    two-hour share (ContextualWisdomLab/.github#1509, Devin Review).
    ``effective_deadline`` below -- the earlier of this attempt's own bound
    and the outer backstop -- is what is actually enforced against this
    attempt's connection, response headers, and response body; ``deadline``
    itself is only re-checked, unchanged, as the outer backstop each time
    this function (or its repair-retry recursion) starts. Callers should
    leave ``deadline`` unset; it is set once here on the first (non-retry)
    call and threaded through the recursive repair-retry call below
    unchanged, so both attempts share the same outer backstop.

    ``opener.open(request, timeout=attempt_timeout)`` itself -- not just the
    subsequent ``response.read()`` -- is also watchdog-guarded against
    ``effective_deadline`` (``_open_response_within_deadline``, backed by
    ``_deadline_guarded_connection``): a peer that trickles response HEADER
    bytes slowly can otherwise keep ``opener.open()`` blocked well past
    ``effective_deadline`` for the same reason a trickled body could keep
    ``response.read()`` blocked, since ``timeout=`` bounds only individual
    blocking socket operations, not either call's total wall time
    (ContextualWisdomLab/.github#1509, Devin Review). Together, the two
    watchdogs bound every phase of one HTTP attempt that can block on this
    module's own socket: connect, request transmission, status-line/header
    receipt, and body receipt (including any chunked-transfer trailers,
    which are consumed inside the same guarded ``response.read()`` call).
    The one phase neither watchdog reaches is the TLS handshake performed
    *inside* ``connect()`` for an ``https://`` target -- seeing why is
    ``_deadline_guarded_connection``'s docstring; this is a known, reported
    residual gap, not silently accepted.
    """
    attempt_start_time = time.monotonic()
    if deadline is None:
        deadline = attempt_start_time + LLM_REQUEST_TOTAL_BUDGET_SECONDS
    if deadline - attempt_start_time <= 0:
        raise RuntimeError(
            "Noema LLM request exceeded LLM_REQUEST_TOTAL_BUDGET_SECONDS before this attempt could start"
        )
    attempt_deadline = attempt_start_time + LLM_REQUEST_TIMEOUT_SECONDS
    effective_deadline = min(attempt_deadline, deadline)
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
    watchdog_state: dict[str, Any] = {}
    opener = urllib.request.build_opener(
        NoRedirectHandler(),
        _DeadlineHTTPHandler(_deadline_guarded_connection(http.client.HTTPConnection, effective_deadline, watchdog_state)),
        _DeadlineHTTPSHandler(_deadline_guarded_connection(http.client.HTTPSConnection, effective_deadline, watchdog_state)),
    )
    attempt_timeout = effective_deadline - attempt_start_time
    with _open_response_within_deadline(
        opener, request, attempt_timeout, effective_deadline, watchdog_state
    ) as response:
        raw = _read_response_body_within_deadline(response, effective_deadline).decode("utf-8")
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
            deadline=deadline,
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


def run_review_phase(repo: str, number: int) -> dict[str, Any] | None:
    """Run pre-flight checks and the LLM review call, without submitting.

    Returns ``None`` when the review is skipped (draft PR, or the current
    head already has a Noema review) so a caller can skip minting a fresh
    submission credential and the submission step entirely. On success,
    returns the JSON-serializable state (``pr``, ``actor``, ``verdict``)
    ``submit_pending_verdict`` needs to submit the review later, potentially
    under a different (freshly minted) credential -- see that function's
    docstring for why the credential used here is not assumed still valid.
    """
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
        return None
    if existing_noema_review(pr, actor):
        print("Current head already has a Noema review; nothing to do.")
        return None
    diff, truncated = fetch_diff(repo, number)
    changed_paths = fetch_changed_file_paths(repo, number)
    review_context = build_review_context(repo, number, pr)
    verdict = call_llm(repo, number, pr, diff, truncated, review_context, changed_paths)
    return {"pr": pr, "actor": actor, "verdict": verdict}


def write_review_state(state_path: str, state: dict[str, Any]) -> None:
    """Persist review-phase output as JSON for a later submission phase to read."""
    with open(state_path, "w", encoding="utf-8") as handle:
        json.dump(state, handle)


def load_review_state(state_path: str) -> dict[str, Any] | None:
    """Load review-phase JSON output, or ``None`` when no verdict is pending."""
    if not os.path.exists(state_path):
        return None
    with open(state_path, encoding="utf-8") as handle:
        return json.load(handle)


def submit_pending_verdict(repo: str, number: int, state: dict[str, Any]) -> None:
    """Submit a previously computed verdict under the current credential.

    ``call_llm`` may run for up to ``LLM_REQUEST_TOTAL_BUDGET_SECONDS`` (4
    hours), long enough to outlive the GitHub App installation token or
    OIDC-exchanged token that was valid when ``run_review_phase`` computed the
    verdict -- installation tokens are short-lived (about one hour). The
    noema-review workflow therefore mints a fresh submission credential after
    ``run_review_phase`` returns and before calling this function. Re-verify
    the reviewer identity against that fresh credential rather than trusting
    the identity recorded in ``state``, so a rebinding of
    ``NOEMA_REVIEW_ACTOR``/``NOEMA_REVIEW_INSTALLATION_ID`` to a different
    identity between the two phases is refused instead of silently trusted --
    this preserves the same verified-reviewer-identity guarantee
    ``run_review_phase`` already enforced, under the new credential.

    The same multi-hour window means a new commit can land on the PR between
    when ``run_review_phase`` persisted ``state["pr"]["headRefOid"]`` and when
    this function actually runs. Re-fetch the PR here and compare the fresh
    ``headRefOid`` against the persisted one before submitting: this org's own
    exact-head evidence model treats a review attached to a commit other than
    the one it was computed against as invalid (see
    ``PR_GOVERNANCE_AUDIT.md``: "Old approvals and old checks are not merge
    evidence after the head SHA changes"), so a head mismatch here must abort
    the submission rather than silently post a verdict against a stale diff.
    """
    actor = current_actor()
    if not actor:
        raise RuntimeError("Noema reviewer identity could not be verified")
    if actor != state["actor"]:
        raise RuntimeError(
            f"Noema submission credential identity {actor!r} does not match the "
            f"identity {state['actor']!r} that computed the verdict; refusing to "
            "submit under a different identity."
        )
    persisted_head = str((state.get("pr") or {}).get("headRefOid") or "")
    current_head = str(fetch_pr(repo, number).get("headRefOid") or "")
    if current_head != persisted_head:
        raise RuntimeError(
            f"Noema PR head changed from {persisted_head!r} to {current_head!r} "
            "between the review and submission phases; refusing to submit a "
            "verdict computed against a stale commit."
        )
    submit_review(repo, number, state["pr"], actor, state["verdict"])


def inspect_and_review(repo: str, number: int) -> int:
    """Inspect PR state and submit Noema's independent LLM review in one pass.

    Single-process convenience path: runs the review and submits it under the
    same credential throughout, with no fresh-credential remint between the
    two. The noema-review workflow itself instead runs the review and submit
    phases as two separate CLI invocations (``--phase review`` /
    ``--phase submit``) bracketing a fresh credential mint, since a single
    long-running review can outlive one credential's lifetime -- see
    ``run_review_phase`` and ``submit_pending_verdict``.
    """
    state = run_review_phase(repo, number)
    if state is None:
        return 0
    submit_review(repo, number, state["pr"], state["actor"], state["verdict"])
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse Noema review gate command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument(
        "--phase",
        choices=("review", "submit"),
        default=None,
        help=(
            "Run only the review phase (computes and persists a verdict) or only "
            "the submit phase (submits a previously persisted verdict), so the "
            "caller can mint a fresh submission credential between them. Requires "
            "--state-file. Omit both for the legacy single-process path."
        ),
    )
    parser.add_argument(
        "--state-file",
        default=None,
        help="Path used to hand the computed verdict from the review phase to the "
        "submit phase. Required together with --phase.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Run the Noema review gate command."""
    args = parse_args(argv)
    if args.pr_number <= 0:
        raise SystemExit("--pr-number must be positive")
    if args.phase is None:
        return inspect_and_review(args.repo, args.pr_number)
    if not args.state_file:
        raise SystemExit("--state-file is required with --phase")
    if args.phase == "review":
        state = run_review_phase(args.repo, args.pr_number)
        if state is not None:
            write_review_state(args.state_file, state)
        return 0
    state = load_review_state(args.state_file)
    if state is None:
        print("No pending Noema verdict to submit; nothing to do.")
        return 0
    submit_pending_verdict(args.repo, args.pr_number, state)
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main(sys.argv[1:]))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
