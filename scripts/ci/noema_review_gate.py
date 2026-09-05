#!/usr/bin/env python3
"""Run Noema LLM review and submit a non-OpenCode PR review verdict."""

from __future__ import annotations

import argparse
import ast
import base64
import hashlib
import http.client
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
# Wraps the start of the fixed-format footer submit_review() writes below the
# LLM-generated summary/findings text. This lets noema_review_handoff.py
# locate the footer by *position* (the trusted, machine-emitted span between
# this marker and the closing "<!-- noema-review-gate head_sha=... -->"
# comment) instead of by scanning for a content pattern that the LLM's own
# unsanitized output could coincidentally reproduce. Keep this literal in
# exact sync with NOEMA_REVIEW_FOOTER_MARKER in noema_review_handoff.py.
NOEMA_REVIEW_FOOTER_MARKER = "<!-- noema-review-gate-footer -->"
# Must stay byte-for-byte identical to NOEMA_REVIEW_MARKER in
# noema_review_handoff.py. Used only to isolate the closing marker's
# position, not as a content-pattern check — see
# _noema_review_footer_and_marker_tail().
NOEMA_REVIEW_CLOSING_MARKER_PREFIX = "<!-- noema-review-gate "
# Must stay byte-for-byte identical to NOEMA_MARKER_HEAD_RE in
# noema_review_handoff.py, so existing_noema_review() applies the exact same
# exact-head structural validation noema_review_state() requires before a
# review can suppress republication.
NOEMA_REVIEW_CLOSING_MARKER_RE = re.compile(
    r"<!-- noema-review-gate head_sha=([0-9a-fA-F]{40}) decision=[a-z_]+ -->"
)
# Must stay byte-for-byte identical to NOEMA_BODY_HEAD_RE in
# noema_review_handoff.py.
NOEMA_REVIEW_BODY_HEAD_RE = re.compile(r"^- Head SHA:\s*`([0-9a-fA-F]{40})`$", re.MULTILINE)
MAX_DIFF_CHARS = 60000
MAX_CONTEXT_FILES = 12
MAX_FILE_CONTEXT_CHARS = 4000
MAX_REVIEW_CONTEXT_CHARS = 24000
MAX_THREAD_BODY_CHARS = 1200
MAX_ALLOWED_LOCATIONS_JSON_BYTES = 32 * 1024
MAX_HTTP_ERROR_BODY_BYTES = 16 * 1024
DIFF_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
OBSERVED_REVIEW_PROBE_KINDS = frozenset(
    {
        "mutable_alias",
        "time_of_check_time_of_use",
        "execution_identity",
        "coercion_boundary",
        "test_oracle",
        "cross_contract",
        "authority_boundary",
        "dependency_context",
        "state_machine_race",
    }
)
OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS: dict[str, tuple[str, ...]] = {
    "mutable_alias": ("alias_origin", "mutation_attempt", "post_validation_observation"),
    "time_of_check_time_of_use": ("check_observation", "intervening_change", "use_observation"),
    "execution_identity": ("incoming_identity", "retained_identity", "mismatch_guard"),
    "coercion_boundary": ("raw_value", "conversion_path", "canonicality_guard"),
    "test_oracle": ("assertion_under_test", "negative_control", "distinguishing_observation"),
    "cross_contract": ("first_contract", "second_contract", "contradiction_or_alignment"),
    "authority_boundary": ("component_authority", "external_authority", "enforcement_boundary"),
    "dependency_context": ("dependency", "omitted_or_included_context", "causal_effect"),
    "state_machine_race": ("initial_state", "event_order", "invariant_observation"),
}
OBSERVED_REVIEW_PROBE_CLAIM_ROLES: dict[str, dict[str, str]] = {
    kind: {field: f"{kind}:{field}" for field in fields}
    for kind, fields in OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS.items()
}
SAFE_MODEL_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$")

ORCHESTRATOR_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1"})
ORCHESTRATOR_BASE_ENV = "CONTEXTUAL_ORCHESTRATOR_BASE_URL"
# OpenAI Chat Completions structured-output envelope for the verdict shape
# ``validate_substantive_verdict`` enforces. contextual-orchestrator's
# ``orchestrator/free`` sidecar is proven (ADR-0003) to be an OpenAI-
# COMPATIBLE endpoint, so the outer envelope (``type`` /
# ``json_schema.name`` / ``json_schema.strict`` / ``json_schema.schema``)
# must be OpenAI's specific wrapping convention -- not bare JSON Schema and
# not Claude's tool-forcing convention. Only the inner ``schema`` value is
# the general JSON Schema document. Whether the gateway correctly translates
# this OpenAI-shaped request for a non-OpenAI-compatible backend it may
# route to is contextual-orchestrator's own translation responsibility, not
# this caller's: adding per-provider format detection here would recreate
# the layering violation the repo owner already rejected in PR #1602 one
# level down. ``strict: true`` requires every property to be listed in
# ``required`` (a conditionally-absent field is expressed as a nullable
# type, e.g. ``["array", "null"]``, never an omitted key) and every object
# to set ``additionalProperties: false``.
#
# ``adversarial_validation.probes`` carries a ``minItems`` floor built fresh
# per request from ``_required_probe_count`` rather than a fixed number: per
# ADR-0035 (`contextual-orchestrator`), the gateway parses the returned
# content and validates it against this exact declared schema -- provider
# acceptance of ``response_format`` is not proof of conformance -- and makes
# one governed same-provider repair call on a violation before this ever
# reaches Noema's own ``validate_substantive_verdict`` second pass. Without
# this floor, an insufficient-probe verdict (schema-valid JSON, just too few
# probes) reaches that second pass and fails the whole review outright with
# no earlier, cheaper structural catch -- exactly what happened in
# `ContextualWisdomLab/ConceptWeave` run `33527145686`, job `99920767480`
# ("Noema adversarial validation requires at least 2 concrete probe(s)").
_NOEMA_REVIEWED_LINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "path": {"type": "string"},
        "line": {"type": "integer"},
        "side": {"type": "string", "enum": ["LEFT", "RIGHT"]},
        "analysis": {"type": "string"},
    },
    "required": ["path", "line", "side", "analysis"],
}
_NOEMA_PROBE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "path": {"type": "string"},
        "line": {"type": "integer"},
        "side": {"type": "string", "enum": ["LEFT", "RIGHT"]},
        "hypothesis": {"type": "string"},
        "attack_or_counterexample": {"type": "string"},
        "evidence": {"type": "string"},
        "outcome": {"type": "string", "enum": ["falsified", "confirmed"]},
    },
    "required": [
        "path",
        "line",
        "side",
        "hypothesis",
        "attack_or_counterexample",
        "evidence",
        "outcome",
    ],
}
_NOEMA_FINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "severity": {"type": "string", "enum": ["high", "medium", "low"]},
        "file": {"type": "string"},
        "line": {"type": "integer"},
        "side": {"type": "string", "enum": ["LEFT", "RIGHT"]},
        "message": {"type": "string"},
    },
    "required": ["severity", "file", "line", "side", "message"],
}
def _noema_verdict_json_schema(required_probes: int) -> dict[str, Any]:
    """Build the verdict JSON Schema with this request's exact probe floor.

    ``required_probes`` must come from ``_required_probe_count(diff,
    changed_paths)`` -- the same call ``validate_substantive_verdict`` uses
    -- so the gateway-enforced structural floor and the Python-side backstop
    can never silently diverge. The static per-field schemas above are safe
    to share by reference here since nothing in this module mutates them.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["approve", "request_changes", "comment"],
            },
            "summary": {"type": "string"},
            "reviewed_lines": {
                "type": ["array", "null"],
                "items": _NOEMA_REVIEWED_LINE_SCHEMA,
            },
            "adversarial_validation": {
                "type": ["object", "null"],
                "additionalProperties": False,
                "properties": {
                    "status": {"type": "string", "enum": ["passed", "failed"]},
                    "residual_risk": {"type": "string"},
                    "probes": {
                        "type": "array",
                        "minItems": required_probes,
                        "items": _NOEMA_PROBE_SCHEMA,
                    },
                },
                "required": ["status", "residual_risk", "probes"],
            },
            "findings": {"type": "array", "items": _NOEMA_FINDING_SCHEMA},
        },
        "required": [
            "decision",
            "summary",
            "reviewed_lines",
            "adversarial_validation",
            "findings",
        ],
    }


def _noema_verdict_response_format(required_probes: int) -> dict[str, Any]:
    """Build the OpenAI ``response_format`` envelope for this request's probe floor."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "noema_review_verdict",
            "strict": True,
            "schema": _noema_verdict_json_schema(required_probes),
        },
    }


class NoemaModelOutputError(RuntimeError):
    """Raised when untrusted model output violates the trusted verdict contract."""


class NoemaTransportError(RuntimeError):
    """Raised when the bounded review transport cannot produce usable evidence."""


TRUSTED_PROVENANCE_CITATION_RE = re.compile(
    r"\[receipt:(?P<receipt_id>[A-Za-z0-9][A-Za-z0-9._-]{0,79})\]"
)
EXECUTED_EVIDENCE_CLAIM_RE = re.compile(
    r"(?i)\b(?:runtime(?:\s+behavior)?|command(?:\s+(?:output|execution))?|"
    r"(?:cli|toolchain)\s+(?:help|output|execution))\s+"
    r"(?:confirms?|confirmed|shows?|shown|demonstrates?|demonstrated|proves?|proved|"
    r"returns?|returned|passes?|passed|fails?|failed|accepts?|accepted|rejects?|rejected)\b"
)
EXTERNAL_SOURCE_CLAIM_RE = re.compile(
    r"(?i)\b(?:official|upstream|vendor|external)\s+"
    r"(?:(?:[A-Za-z0-9._+-]+)\s+){0,3}"
    r"(?:documentation|docs?|reference|manual|help)\b[^.\n]{0,240}\b"
    r"(?:confirms?|confirmed|shows?|shown|states?|stated|documents?|documented|"
    r"agrees?|agreed|supports?|supported|rejects?|rejected)\b"
)


def _model_evidence_statements(verdict: dict[str, Any]) -> list[str]:
    """Return only model-authored prose that can assert review evidence."""
    statements: list[str] = []

    def append(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            statements.append(value)

    append(verdict.get("summary"))
    for reviewed in verdict.get("reviewed_lines") or []:
        if isinstance(reviewed, dict):
            append(reviewed.get("analysis"))
    validation = verdict.get("adversarial_validation")
    if isinstance(validation, dict):
        append(validation.get("residual_risk"))
        for probe in validation.get("probes") or []:
            if not isinstance(probe, dict):
                continue
            for field in ("hypothesis", "attack_or_counterexample", "evidence"):
                append(probe.get(field))
            class_evidence = probe.get("class_evidence")
            if isinstance(class_evidence, dict):
                for witness in class_evidence.values():
                    if isinstance(witness, dict):
                        append(witness.get("observation"))
    for finding in verdict.get("findings") or []:
        if isinstance(finding, dict):
            append(finding.get("message"))
    return statements


def validate_evidence_provenance(
    verdict: dict[str, Any],
    *,
    trusted_execution_receipt_ids: Sequence[str] = (),
    trusted_source_receipt_ids: Sequence[str] = (),
) -> None:
    """Reject claims of executed or external evidence without a typed receipt.

    Noema is isolated from command execution and network access. A model may
    reason from the supplied source and recommend a verification command, but
    it must not turn that recommendation into purported observed evidence.
    Future trusted preprocessors can authorize a claim only by supplying a
    typed receipt ID out-of-band and requiring the model to cite that ID in the
    same evidence statement.
    """
    for statement in _model_evidence_statements(verdict):
        cited_ids = {
            match.group("receipt_id")
            for match in TRUSTED_PROVENANCE_CITATION_RE.finditer(statement)
        }
        if EXECUTED_EVIDENCE_CLAIM_RE.search(statement) and not (
            cited_ids & set(trusted_execution_receipt_ids)
        ):
            raise NoemaModelOutputError(
                "Noema evidence provenance requires a trusted execution receipt"
            )
        if EXTERNAL_SOURCE_CLAIM_RE.search(statement) and not (
            cited_ids & set(trusted_source_receipt_ids)
        ):
            raise NoemaModelOutputError(
                "Noema evidence provenance requires a trusted external-source receipt"
            )



def _stable_failure_diagnostic(exc: BaseException) -> str:
    """Return actionable trusted diagnostics without reflecting model values."""
    message = scrub_sensitive_data(str(exc)) or type(exc).__name__
    if not isinstance(exc, NoemaModelOutputError):
        return message

    # Model-output exceptions are raised only by deterministic parsing and
    # validation code. Preserve those static/structural diagnostics because
    # they tell the corrective model and operators exactly which contract was
    # violated. The one validator that embeds an untrusted model value is the
    # unsupported-decision check; redact that value. Unknown model-output
    # exception text fails closed to a stable code rather than being reflected.
    if message.startswith("Noema LLM returned unsupported decision:"):
        return "Noema LLM returned unsupported decision"
    trusted_prefixes = (
        "Noema LLM response ",
        "Noema LLM request_changes ",
        "Noema formal verdict ",
        "Noema reviewed line ",
        "Noema adversarial validation ",
        "Noema adversarial probe ",
        "Noema approve ",
        "Noema request_changes ",
        "Noema evidence provenance ",
    )
    if message.startswith(trusted_prefixes):
        return message
    return "model-output-contract-invalid"

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
      state
      headRefOid
      baseRefOid
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


def require_expected_head(pr: dict[str, Any], expected_head_sha: str) -> None:
    """Fail closed unless the pull request is open at the expected commit."""
    if not re.fullmatch(r"[0-9a-fA-F]{40}", expected_head_sha):
        raise RuntimeError("Expected pull request head must be a full commit SHA")
    live_head_sha = str(pr.get("headRefOid") or "")
    if (
        str(pr.get("state") or "").upper() != "OPEN"
        or live_head_sha.lower() != expected_head_sha.lower()
    ):
        raise RuntimeError(
            "Pull request is closed or its head changed before Noema review: "
            f"expected {expected_head_sha}, observed {live_head_sha or '<missing>'}"
        )


def review_author(review: dict[str, Any]) -> str:
    """Return the normalized author login from a review node."""
    return ((review.get("author") or {}).get("login") or "").strip()


def review_commit(review: dict[str, Any]) -> str:
    """Return the review commit oid from a review node."""
    return ((review.get("commit") or {}).get("oid") or "").strip()


def _noema_review_footer_and_marker_tail(body: str) -> tuple[str, str]:
    """Return the trusted footer span and marker tail of a Noema review body.

    Mirrors ``noema_review_handoff.py``'s ``_isolate_trusted_footer()`` and
    ``_isolate_trusted_marker_tail()`` exactly: both spans are located by
    *position*, strictly between the machine-emitted
    ``NOEMA_REVIEW_FOOTER_MARKER`` and (for the footer span) the closing
    ``<!-- noema-review-gate head_sha=... decision=... -->`` comment, never by
    scanning for a content pattern the LLM's own unsanitized summary/findings
    text could coincidentally reproduce. Returns ``("", "")`` when the footer
    marker is absent, so the caller's exact-one-match check fails closed.
    """
    marker_tail_parts = body.rsplit(NOEMA_REVIEW_FOOTER_MARKER, 1)
    marker_tail = marker_tail_parts[1] if len(marker_tail_parts) == 2 else ""

    before_closing_marker = body.rsplit(NOEMA_REVIEW_CLOSING_MARKER_PREFIX, 1)[0]
    footer_parts = before_closing_marker.rsplit(NOEMA_REVIEW_FOOTER_MARKER, 1)
    footer_text = footer_parts[1] if len(footer_parts) == 2 else ""
    return footer_text, marker_tail


def existing_noema_review(pr: dict[str, Any], actor: str) -> bool:
    """Return whether Noema already posted a trusted verdict for the current head.

    Applies the exact same exact-head structural validation
    ``noema_review_handoff.py``'s ``noema_review_state()`` requires before
    accepting a review as a valid current-head verdict — not just marker
    presence. A review whose markers are both present but whose body-side
    bullet or closing-marker SHA is missing, malformed, or duplicated (for
    example a hand-edited or corrupted review, or one predating the footer
    marker) is a review ``noema_review_state()`` can never recognize as a
    valid current-head verdict; treating it as "already reviewed" here would
    let it silently suppress every future publish attempt for an otherwise
    unchanged head, stalling the PR forever.
    """
    head_sha = str(pr.get("headRefOid") or "")
    for review in (((pr.get("reviews") or {}).get("nodes")) or []):
        if review_commit(review) != head_sha:
            continue
        if str(review.get("state") or "").upper() not in {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}:
            continue
        if not actor or review_author(review) != actor:
            continue
        body = str(review.get("body") or "")
        footer_text, marker_tail = _noema_review_footer_and_marker_tail(body)
        marker_heads = NOEMA_REVIEW_CLOSING_MARKER_RE.findall(marker_tail)
        body_heads = NOEMA_REVIEW_BODY_HEAD_RE.findall(footer_text)
        if len(marker_heads) != 1 or len(body_heads) != 1:
            continue
        if marker_heads[0].lower() != head_sha.lower() or body_heads[0].lower() != head_sha.lower():
            continue
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
        marker = "[overlong changed line content omitted]"
        bounded = diff[: MAX_DIFF_CHARS - len(marker) - 2]
        complete, separator, partial = bounded.rpartition("\n")
        if not separator:
            return diff[:MAX_DIFF_CHARS], truncated
        last_hunk = max(complete.rfind("\n@@"), 0 if complete.startswith("@@") else -1)
        last_file = max(complete.rfind("\ndiff --git "), 0 if complete.startswith("diff --git ") else -1)
        inside_hunk = last_hunk > last_file
        if partial.startswith(("+", "-")) and (
            inside_hunk or not partial.startswith(("+++", "---"))
        ):
            complete += f"\n{partial[0]}{marker}"
        diff = complete
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


def changed_diff_line_texts(diff: str) -> dict[tuple[str, int, str], str]:
    """Return exact changed-side source text keyed by canonical diff location."""
    texts: dict[tuple[str, int, str], str] = {}
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
            continue
        if not in_hunk and raw_line.startswith("+++ "):
            new_path = parse_diff_path(raw_line[4:], "b/")
            continue
        match = DIFF_HUNK_RE.match(raw_line)
        if match:
            old_line, new_line = map(int, match.groups())
            in_hunk = True
            continue
        if not in_hunk or raw_line.startswith(r"\ No newline"):
            continue
        if raw_line.startswith("+"):
            if not new_path:
                return {}
            source_text = raw_line[1:]
            if source_text != "[overlong changed line content omitted]":
                texts[(new_path, new_line, "RIGHT")] = source_text
            new_line += 1
        elif raw_line.startswith("-"):
            if not old_path:
                return {}
            source_text = raw_line[1:]
            if source_text != "[overlong changed line content omitted]":
                texts[(old_path, old_line, "LEFT")] = source_text
            old_line += 1
        else:
            old_line += 1
            new_line += 1
    return texts


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


def _canonical_changed_location(record: dict[str, Any], label: str) -> tuple[str, int, str]:
    """Return a canonical changed-side location without bool/int coercion."""
    path_value = record.get("path")
    line_value = record.get("line")
    side_value = record.get("side")
    if not isinstance(path_value, str) or not path_value.strip():
        raise NoemaModelOutputError(f"{label} requires a canonical changed-side path")
    if type(line_value) is not int or line_value <= 0:
        raise NoemaModelOutputError(f"{label} requires a canonical positive integer line")
    if side_value not in {"LEFT", "RIGHT"}:
        raise NoemaModelOutputError(f"{label} requires canonical LEFT/RIGHT side")
    return (path_value, line_value, side_value)


def _validate_observed_probe_class_evidence(
    probe: dict[str, Any],
    probe_kind: str,
    index: int,
    location: tuple[str, int, str],
    diff: str,
) -> None:
    """Require defect-class witnesses to bind to the probe's exact changed line."""
    class_evidence = probe.get("class_evidence")
    required_fields = OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS[probe_kind]
    if not isinstance(class_evidence, dict) or set(class_evidence) != set(required_fields):
        expected = ", ".join(required_fields)
        raise NoemaModelOutputError(
            f"Noema adversarial probe {index} class_evidence for {probe_kind} "
            f"must contain exactly: {expected}"
        )
    normalized_observations: list[str] = []
    source_texts = changed_diff_line_texts(diff)
    for field in required_fields:
        source_ref = class_evidence.get(field)
        if not isinstance(source_ref, dict) or set(source_ref) != {
            "path",
            "line",
            "side",
            "source_excerpt",
            "claim_role",
            "observation",
        }:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} requires "
                "path, line, side, exact source_excerpt, class-specific claim_role, and non-empty observation"
            )
        source_location = _canonical_changed_location(
            source_ref, f"Noema adversarial probe {index} class_evidence.{field}"
        )
        if source_location != location:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} must bind to "
                "the probe location"
            )
        expected_excerpt = source_texts.get(source_location)
        source_excerpt = source_ref.get("source_excerpt")
        if (
            not isinstance(source_excerpt, str)
            or expected_excerpt is None
            or source_excerpt != expected_excerpt
        ):
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} requires the "
                "exact changed-line source_excerpt"
            )
        observation = source_ref.get("observation")
        if not isinstance(observation, str) or not observation.strip():
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} requires a "
                "non-empty observation"
            )
        if len(observation) > MAX_THREAD_BODY_CHARS:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} observation "
                f"exceeds {MAX_THREAD_BODY_CHARS} characters"
            )
        source_marker = source_excerpt if source_excerpt else "<blank>"
        if source_marker not in observation:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} observation "
                "must quote the exact source_excerpt (or <blank> for an empty line)"
            )
        expected_claim_role = OBSERVED_REVIEW_PROBE_CLAIM_ROLES[probe_kind][field]
        claim_role = source_ref.get("claim_role")
        if claim_role != expected_claim_role:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {index} class_evidence.{field} claim_role "
                f"must be {expected_claim_role!r}"
            )
        normalized_observations.append(observation.strip().casefold())
    if len(set(normalized_observations)) != len(normalized_observations):
        raise NoemaModelOutputError(
            f"Noema adversarial probe {index} requires distinct class-specific observations"
        )


def _required_probe_count(diff: str, changed_paths: Sequence[str] = ()) -> int:
    """Return the minimum adversarial-probe count a formal verdict must carry.

    This is the single source of truth shared by the structured-output schema
    and deterministic local validator. Executable/test/workflow changes require
    two distinct probes; other diffs require one. The bound is cardinality-
    based and independent of repository path count, so a near-MAX_DIFF_CHARS
    review remains representable within the gateway output budget.
    """
    locations = changed_diff_locations(diff)
    all_changed_paths = set(changed_paths) or {path for path, _line, _side in locations}
    return 2 if any(changed_file_is_material(path) for path in all_changed_paths) else 1


def _entry_ordinal(position: int, total: int) -> str:
    """Return an unambiguous 1-based array-position label for diagnostics."""
    return f"entry {position}/{total} (array index {position - 1}, not a source line)"


def _format_location(path: Any, line: Any, side: Any) -> str:
    """Format one rejected path/line/side citation without coercing its types."""
    return f"path={path!r} line={line!r} side={side!r}"


def _nearby_changed_locations(
    locations: set[tuple[str, int, str]], path: Any, line: Any, *, limit: int = 5
) -> str:
    """Return a bounded nearest-line hint for the rejected path."""
    if not isinstance(path, str):
        return ""
    same_path = [location for location in locations if location[0] == path]
    if not same_path:
        return ""
    if isinstance(line, int):
        same_path.sort(key=lambda location: (abs(location[1] - line), location[1], location[2]))
    else:
        same_path.sort(key=lambda location: (location[1], location[2]))
    sample = ", ".join(f"{p}:{ln} ({s})" for p, ln, s in same_path[:limit])
    remaining = len(same_path) - limit
    more = f", +{remaining} more" if remaining > 0 else ""
    return f"; nearest changed lines for {path}: {sample}{more}"


def validate_substantive_verdict(
    verdict: dict[str, Any], diff: str, changed_paths: Sequence[str] = ()
) -> None:
    """Reject formal verdicts without exact changed-line/adversarial evidence."""
    decision = str(verdict.get("decision") or "").lower()
    if decision == "comment":
        return
    locations = changed_diff_locations(diff)
    if not locations:
        raise RuntimeError("Noema formal verdict requires parseable changed-line evidence")

    reviewed_lines = verdict.get("reviewed_lines")
    if not isinstance(reviewed_lines, list) or not reviewed_lines:
        raise NoemaModelOutputError("Noema formal verdict requires at least one reviewed changed line")
    reviewed_total = len(reviewed_lines)
    for position, reviewed in enumerate(reviewed_lines, start=1):
        entry = _entry_ordinal(position, reviewed_total)
        if not isinstance(reviewed, dict):
            raise NoemaModelOutputError(f"Noema reviewed line {entry} must be an object")
        location = _canonical_changed_location(reviewed, f"Noema reviewed line {entry}")
        if location not in locations:
            path, line, side = location
            raise NoemaModelOutputError(
                f"Noema reviewed line {entry} cites {_format_location(path, line, side)}, "
                f"which is not an exact changed-side line"
                f"{_nearby_changed_locations(locations, path, line)}"
            )
        analysis = reviewed.get("analysis")
        if not isinstance(analysis, str) or not analysis.strip():
            raise NoemaModelOutputError(f"Noema reviewed line {entry} requires concrete analysis")

    validation = verdict.get("adversarial_validation")
    if not isinstance(validation, dict):
        raise NoemaModelOutputError("Noema formal verdict requires adversarial_validation")
    status = validation.get("status")
    expected_status = "passed" if decision == "approve" else "failed"
    if status != expected_status:
        raise NoemaModelOutputError(f"Noema {decision} requires adversarial_validation.status={expected_status}")
    residual_risk = validation.get("residual_risk")
    if not isinstance(residual_risk, str) or not residual_risk.strip():
        raise NoemaModelOutputError("Noema adversarial validation requires residual_risk")
    probes = validation.get("probes")
    required_probes = _required_probe_count(diff, changed_paths)
    if not isinstance(probes, list) or len(probes) < required_probes:
        raise NoemaModelOutputError(
            f"Noema adversarial validation requires at least {required_probes} concrete probe(s)"
        )

    confirmed: set[tuple[str, int, str]] = set()
    identities: set[tuple[Any, ...]] = set()
    probe_kinds: set[str] = set()
    enforce_observed_taxonomy = bool(changed_paths)
    probes_total = len(probes)
    for position, probe in enumerate(probes, start=1):
        entry = _entry_ordinal(position, probes_total)
        if not isinstance(probe, dict):
            raise NoemaModelOutputError(f"Noema adversarial probe {entry} must be an object")
        location = _canonical_changed_location(probe, f"Noema adversarial probe {entry}")
        if location not in locations:
            path, line, side = location
            raise NoemaModelOutputError(
                f"Noema adversarial probe {entry} cites {_format_location(path, line, side)}, "
                f"which is not an exact changed-side line"
                f"{_nearby_changed_locations(locations, path, line)}"
            )
        for field in ("hypothesis", "attack_or_counterexample", "evidence"):
            value = probe.get(field)
            if not isinstance(value, str) or not value.strip():
                raise NoemaModelOutputError(f"Noema adversarial probe {entry} requires {field}")
        outcome = probe.get("outcome")
        if outcome not in {"falsified", "confirmed"}:
            raise NoemaModelOutputError(
                f"Noema adversarial probe {entry} outcome must be falsified or confirmed"
            )
        if enforce_observed_taxonomy:
            probe_kind = probe.get("probe_kind")
            if not isinstance(probe_kind, str) or probe_kind not in OBSERVED_REVIEW_PROBE_KINDS:
                raise NoemaModelOutputError(
                    f"Noema adversarial probe {entry} requires probe_kind from the observed defect taxonomy"
                )
            _validate_observed_probe_class_evidence(probe, probe_kind, position, location, diff)
            probe_kinds.add(probe_kind)
        identity = (
            *location,
            probe["hypothesis"].strip().casefold(),
            probe["attack_or_counterexample"].strip().casefold(),
        )
        if identity in identities:
            raise NoemaModelOutputError(f"Noema adversarial probe {entry} duplicates an earlier probe")
        identities.add(identity)
        if outcome == "confirmed":
            confirmed.add((str(probe["path"]), int(probe["line"]), str(probe["side"])))

    if enforce_observed_taxonomy and len(probe_kinds) < required_probes:
        raise NoemaModelOutputError(
            f"Noema {decision} requires at least {required_probes} distinct probe_kind values"
        )

    if decision == "approve" and confirmed:
        raise NoemaModelOutputError("Noema approve cannot contain a confirmed adversarial probe")
    if decision == "request_changes":
        finding_locations = {
            (str(finding.get("file") or ""), finding.get("line"), str(finding.get("side") or ""))
            for finding in verdict.get("findings") or []
            if isinstance(finding, dict)
        }
        if not confirmed or not confirmed.intersection(finding_locations):
            raise NoemaModelOutputError(
                "Noema request_changes requires a confirmed probe on a published finding"
            )


def truncate_text(text: str, limit: int) -> str:
    """Return text shortened to limit characters with an explicit truncation note."""
    if len(text) <= limit:
        return text
    omitted = len(text) - limit
    return f"{text[:limit]}\n[truncated {omitted} characters]"


def fetch_changed_files(repo: str, number: int) -> list[tuple[str, str]]:
    """Fetch changed paths and statuses without corrupting whitespace in paths.

    The Files API is projected to one JSON-encoded two-element array per file.
    JSON escaping preserves tabs, newlines, and edge spaces inside ``filename``
    while keeping pagination output line-delimited and parseable. Malformed
    records fail closed instead of being reinterpreted as another path/status.
    """
    output = run(
        [
            "gh",
            "api",
            f"repos/{repo}/pulls/{number}/files",
            "--paginate",
            "--jq",
            r'.[] | [.filename, .status] | @json',
        ]
    )
    files: list[tuple[str, str]] = []
    for line in output.splitlines():
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError("GitHub changed-file response was malformed") from exc
        if (
            not isinstance(record, list)
            or len(record) != 2
            or type(record[0]) is not str
            or not record[0]
            or type(record[1]) is not str
            or not record[1]
        ):
            raise RuntimeError("GitHub changed-file response was malformed")
        files.append((record[0], record[1]))
    return files


def fetch_file_content_at_ref(repo: str, path: str, ref: str) -> str:
    """Fetch one repository text file at an exact Git ref through GitHub."""
    encoded_path = urllib.parse.quote(path, safe="/")
    encoded_ref = urllib.parse.quote(ref, safe="")
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


def fetch_merge_base_sha(repo: str, base_sha: str, head_sha: str) -> str:
    """Return the immutable merge-base SHA for the current base/head pair."""
    if not re.fullmatch(r"[0-9a-fA-F]{40}", base_sha):
        raise RuntimeError("PR base SHA was unavailable or malformed")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha):
        raise RuntimeError("PR head SHA was unavailable or malformed")
    merge_base = run(
        [
            "gh",
            "api",
            f"repos/{repo}/compare/{base_sha}...{head_sha}",
            "--jq",
            ".merge_base_commit.sha // empty",
        ]
    ).strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", merge_base):
        raise RuntimeError("GitHub compare response did not contain a valid merge-base SHA")
    return merge_base.lower()


def removed_file_context_section(
    repo: str,
    path: str,
    merge_base_sha: str,
    merge_base_error: str = "",
) -> str:
    """Build review context for a file deleted relative to the merge base.

    A deleted path does not exist at the PR head. Its relevant pre-deletion
    evidence is therefore the immutable merge base shared by the current base
    and reviewed head, not the moving tip of the base branch. When merge-base
    discovery or content retrieval is unavailable, the context records that
    bounded evidence failure explicitly rather than inventing head content.
    """
    if merge_base_error:
        return (
            f"### {path}\n[File removed in this PR.] "
            f"Merge-base lookup unavailable: {merge_base_error}"
        )
    if not merge_base_sha:
        return (
            f"### {path}\n[File removed in this PR — no head-side content applicable; "
            "merge-base SHA unavailable for pre-deletion content.]"
        )
    try:
        content = fetch_file_content_at_ref(repo, path, merge_base_sha)
    except RuntimeError as exc:
        reason = scrub_sensitive_data(str(exc)) or "unknown error"
        return (
            f"### {path}\n[File removed in this PR.] "
            f"Unavailable from merge-base content API: {reason}"
        )
    if not content:
        return (
            f"### {path}\n[File removed in this PR — no UTF-8 text content "
            "available from merge-base content API.]"
        )
    return (
        f"### {path}\n[File removed in this PR. Pre-deletion content at merge base "
        f"`{merge_base_sha}`:]\n{truncate_text(content, MAX_FILE_CONTEXT_CHARS)}"
    )


def changed_file_context(
    repo: str,
    number: int,
    head_sha: str,
    base_sha: str = "",
    changed_files: Sequence[tuple[str, str]] | None = None,
) -> str:
    """Build bounded changed-file context from one status-preserving snapshot."""
    if not head_sha:
        return "Changed file context unavailable: missing PR head SHA."
    files = list(changed_files) if changed_files is not None else fetch_changed_files(repo, number)
    if not files:
        return "Changed file context unavailable: PR reported no changed files."

    merge_base_sha = ""
    merge_base_error = ""
    if any(status == "removed" for _path, status in files[:MAX_CONTEXT_FILES]):
        try:
            merge_base_sha = fetch_merge_base_sha(repo, base_sha, head_sha)
        except RuntimeError as exc:
            merge_base_error = scrub_sensitive_data(str(exc)) or "unknown error"

    sections: list[str] = []
    for path, status in files[:MAX_CONTEXT_FILES]:
        if status == "removed":
            sections.append(
                removed_file_context_section(
                    repo, path, merge_base_sha, merge_base_error
                )
            )
            continue
        try:
            content = fetch_file_content_at_ref(repo, path, head_sha)
        except RuntimeError as exc:
            reason = scrub_sensitive_data(str(exc)) or "unknown error"
            sections.append(f"### {path}\nUnavailable from head content API: {reason}")
            continue
        if not content:
            sections.append(f"### {path}\nNo UTF-8 text content available from head content API.")
            continue
        sections.append(f"### {path}\n{truncate_text(content, MAX_FILE_CONTEXT_CHARS)}")
    if len(files) > MAX_CONTEXT_FILES:
        sections.append(f"[{len(files) - MAX_CONTEXT_FILES} changed files omitted from context budget]")
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


def build_review_context(
    repo: str,
    number: int,
    pr: dict[str, Any],
    changed_files: Sequence[tuple[str, str]] | None = None,
) -> str:
    """Build bounded non-diff context from review threads and changed files."""
    sections: list[str] = []
    threads = review_thread_context(pr)
    if threads:
        sections.append("## Prior review threads\n" + threads)
    files = changed_file_context(
        repo,
        number,
        str(pr.get("headRefOid") or ""),
        str(pr.get("baseRefOid") or ""),
        changed_files,
    )
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


def _json_nesting_within_bound(text: str, start: int, max_depth: int) -> bool:
    """Return whether the ``{``/``[`` nesting at ``text[start]`` stays within bound.

    A lightweight, string-literal-aware bracket-type stack: walks forward
    from ``start`` (a ``{``), ignoring any ``{``/``[``/``}``/``]`` characters
    that appear inside a JSON string literal, and returns ``True`` as soon as
    the opening brace's matching close is found without nesting exceeding
    ``max_depth``, or ``False`` the moment ``max_depth`` is exceeded. Running
    off the end of ``text`` without closing (an unterminated candidate) is
    reported as within bound — that shape is already a decode failure
    ``json.JSONDecoder.raw_decode`` reports on its own; this function's only
    job is bounding nesting *depth*, not validating overall JSON shape.

    A closer that does not match the innermost open bracket's type (a ``]``
    where the enclosing container is a ``{``, or vice versa) is a no-op: it
    does not pop the stack. A plain up/down counter that treated ``{``/``[``
    interchangeably would let such a mismatched closer prematurely signal
    "the outer bracket is closed" while genuinely deeper structure follows,
    under-counting the real nesting depth ``raw_decode`` would encounter on
    this exact candidate (Devin review on PR #1507).

    This check runs before ``raw_decode`` is attempted on a candidate, ahead
    of and independent of ``json.JSONDecoder``'s own recursion behavior —
    see ``extract_json_object``'s docstring for why that behavior cannot be
    trusted to reject excessive nesting on its own.
    """
    stack: list[str] = []
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append(char)
            if len(stack) > max_depth:
                return False
        elif char == "}":
            if stack and stack[-1] == "{":
                stack.pop()
                if not stack:
                    # Only "{" can empty the stack: text[start] is always
                    # "{" (this function's own contract), so it is always
                    # the bottom-most, last-popped element; a "]" popping
                    # an inner "[" can never reach an empty stack itself.
                    return True
        elif char == "]" and stack and stack[-1] == "[":
            stack.pop()
    return True


MAX_JSON_NESTING_DEPTH = 100


def _strip_trailing_commas_outside_strings(text: str) -> str:
    """Remove only a genuine trailing comma after a complete JSON value.

    Missing-value forms such as ``[,]``, ``{,}``, ``[1,,]`` and ``{"a":,}``
    remain malformed and therefore fail closed. String contents are untouched.
    """
    result: list[str] = []
    in_string = False
    escaped = False
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < length and text[lookahead] in " \t\r\n":
                lookahead += 1
            previous = len(result) - 1
            while previous >= 0 and result[previous] in " \t\r\n":
                previous -= 1
            prior = result[previous] if previous >= 0 else ""
            value_ending = prior in {'"', '}', ']'} or prior.isdigit() or prior in {'e', 'l'}
            if lookahead < length and text[lookahead] in "}]" and value_ending:
                index += 1
                continue
        result.append(char)
        index += 1
    return "".join(result)


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract a JSON object, retrying once through a lossless local repair.

    Delegates to ``_extract_json_object_once``. If that fails, this makes
    exactly one additional attempt against
    ``_strip_trailing_commas_outside_strings(text)`` -- a deterministic,
    semantically lossless fixup for the single well-known trailing-comma
    malformation class -- before giving up. This is a local, non-network
    second chance: it can resolve some malformed-JSON cases without ever
    spending the bounded repair path's network round trip and wall-clock
    budget, and it emits a ``::notice::`` (no raw content) when it is what
    actually rescued the response, since that is itself useful repair-path
    telemetry. It does not attempt to guess-repair any other malformation
    shape; those still fail closed exactly as before.
    """
    try:
        return _extract_json_object_once(text)
    except NoemaModelOutputError:
        repaired = _strip_trailing_commas_outside_strings(text.strip())
        if repaired == text.strip():
            raise
        verdict = _extract_json_object_once(repaired)
        return verdict


def _extract_json_object_once(text: str) -> dict[str, Any]:
    """Extract a JSON object from a strict or lightly wrapped LLM response.

    Fails closed with ``NoemaModelOutputError`` — the same "no usable verdict" failure
    path ``call_llm`` already raises for an unsupported decision, a missing
    summary, or a malformed finding — instead of letting a malformed or
    truncated LLM response's ``json.JSONDecodeError`` propagate as an
    unhandled exception and crash the review job. Only top-level brace groups
    are candidates: a ``{`` is a candidate only while a bracket-type stack
    (tracking ``{``/``[`` opens against their own matching ``}``/``]``
    closes) is empty, so a valid nested object cannot escape a malformed
    outer *object or array* wrapper. Every candidate starts at a ``{``,
    making each successful parse a JSON object (``dict``); only the decode
    failure itself needs converting. Once a top-level candidate begins, a
    decode failure rejects the response rather than scanning forward to a
    later verdict; multiple objects remain supported only when the first
    candidate decodes successfully.

    A closer that cannot legally match the innermost open bracket — nothing
    open at all, or the innermost open bracket is the other type — stops
    candidate discovery outright instead of being a no-op on the stack. Only
    ignoring the mismatch (popping nothing, but continuing to scan) is not
    enough: a *later*, otherwise-well-formed ``[``/``]`` or ``{``/``}`` pair
    can still legitimately re-close the stack down to empty despite the
    earlier mismatch, so a subsequent ``{`` would again be seen as a fresh
    top-level candidate even though the response as a whole was never
    cleanly-formed JSON (Devin review on PR #1507, e.g. ``[} ] {...}``: the
    stray ``}`` is a no-op, but the following ``]`` still validly closes the
    ``[``, and the ``{`` after that would wrongly look top-level again). Any
    closer this malformed anywhere in the response is treated as proof the
    whole response cannot be trusted to contain a clean top-level object
    from that point on, not just proof that one bracket group failed to
    close.

    The raised diagnostic never embeds the raw (or scrubbed) model response.
    This is a ``pull_request_target`` workflow whose Actions logs are public
    on this org's public repos, and ``scrub_sensitive_data`` is a finite,
    pattern-based scrubber: an LLM can echo back or hallucinate a credential
    in a shape none of its patterns recognize (mid-sentence, base64-wrapped,
    or simply a shape nobody anticipated). A regex allowlist of known secret
    *shapes* cannot be a complete defense, so instead of trying to perfect
    it, the raw content is never logged at all. Only a length and a SHA-256
    content fingerprint are logged — enough to correlate repeat failures for
    the same underlying (unlogged) response without exposing its bytes.

    Excessive nesting is rejected by an explicit ``_json_nesting_within_bound``
    check against ``MAX_JSON_NESTING_DEPTH`` (100 — generously above the
    verdict schema's own real maximum of roughly 5 levels: object ->
    ``findings``/``reviewed_lines``/``adversarial_validation.probes`` ->
    each list's object entries), evaluated *before* ``raw_decode`` is ever
    attempted, rather than by trusting ``json.JSONDecoder``'s own recursion
    behavior to raise on deep input. That behavior is not a stable contract:
    a real ``depth = max(20_000, sys.getrecursionlimit() * 2)`` nested-array
    payload raises ``RecursionError`` from the C-accelerated scanner on
    Python 3.11-3.13, but is decoded successfully (no exception at all) on
    the Python 3.14.7 hosted runner this job actually runs on (job
    99642234627, commit ``ec23350e``:
    ``test_extract_json_object_fails_closed_on_excessive_nesting`` failed
    with "DID NOT RAISE RuntimeError" against that exact real payload).
    Relying on ``RecursionError`` alone would make this fail-closed guarantee
    a property of whichever CPython version happens to run the job, not of
    this function. The explicit bound removes that dependency; a residual
    ``except RecursionError`` is kept only as defense-in-depth for whatever
    lies within the bound (``RecursionError`` is itself a ``RuntimeError``
    subclass, so even an unhandled one here would already surface through
    ``call_llm``'s own ``except RuntimeError`` around this call and every
    post-decode field read).
    """
    stripped = text.strip()
    decoder = json.JSONDecoder()
    decode_error: json.JSONDecodeError | None = None
    candidate_starts: list[int] = []
    stack: list[str] = []
    in_string = False
    escaped = False
    for index, character in enumerate(stripped):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            if not stack:
                candidate_starts.append(index)
            stack.append("{")
        elif character == "[":
            stack.append("[")
        elif character == "}":
            if not stack or stack[-1] != "{":
                # A closer that cannot legally appear here (nothing open, or
                # the innermost open bracket is a "[") is proof this response
                # is not cleanly-formed JSON at all, not just proof that one
                # bracket group failed to close. Stop finding new candidates
                # rather than let bracket-type matching alone "resync" past
                # it and treat a later, structurally-unrelated { as a fresh
                # top-level verdict (Devin review on PR #1507).
                break
            stack.pop()
        elif character == "]":
            if not stack or stack[-1] != "[":
                break
            stack.pop()

    for start in candidate_starts:
        if not _json_nesting_within_bound(stripped, start, MAX_JSON_NESTING_DEPTH):
            decode_error = json.JSONDecodeError(
                f"JSON nesting exceeds the bounded limit ({MAX_JSON_NESTING_DEPTH} levels)",
                stripped,
                start,
            )
            break
        try:
            candidate, _end = decoder.raw_decode(stripped, start)
        except RecursionError:
            decode_error = json.JSONDecodeError(
                "JSON nesting exceeds decoder limit", stripped, start
            )
            break
        except json.JSONDecodeError as exc:
            decode_error = exc
            break
        return candidate

    if "{" not in stripped:
        raise NoemaModelOutputError("Noema LLM response did not contain a JSON object")

    exc = decode_error or json.JSONDecodeError(
        "No JSON object could be decoded", stripped, 0
    )
    try:
        raise exc
    except json.JSONDecodeError as exc:
        fingerprint = hashlib.sha256(
            stripped.encode("utf-8", errors="surrogatepass")
        ).hexdigest()[:16]
        raise NoemaModelOutputError(
            f"Noema LLM response was not valid JSON ({exc}). Raw model output "
            "is not logged here (this pull_request_target workflow's logs "
            "are public and a finite secret-scrub pattern list cannot "
            "guarantee an LLM-echoed or hallucinated credential in an "
            f"unrecognized shape is caught): response length={len(stripped)} "
            f"chars, sha256={fingerprint}."
        ) from exc


def extract_llm_message_content(raw: str) -> str:
    """Parse and validate the OpenAI-compatible chat-completion HTTP envelope.

    Fails closed with the same bounded ``RuntimeError`` ``call_llm`` already
    uses for an unusable verdict, instead of letting a malformed gateway
    reply crash the review job before it ever reaches the verdict-JSON
    repair boundary handled by ``extract_json_object``. Covers a non-JSON
    raw body, a non-object top-level JSON value, a wrong-shaped ``choices``
    or ``message`` field, and non-string ``content`` — each rejected with an
    explicit ``isinstance`` check rather than a broad ``except``, so a
    genuine programming error elsewhere in this module still surfaces as
    itself. A missing or empty ``choices``/``message``/``content`` is left
    to fall through to an empty string, matching the original code's
    leniency for an absent (not malformed) field; ``extract_json_object``
    already fails closed on empty content.

    None of the raised messages embed any part of the untrusted response
    body — only JSON-value type names, which cannot carry a credential.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NoemaModelOutputError(f"Noema LLM response body was not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise NoemaModelOutputError(
            f"Noema LLM response body was not a JSON object (got {type(data).__name__})"
        )
    choices = data.get("choices")
    if not choices:
        choices = [{}]
    elif not isinstance(choices, list):
        raise NoemaModelOutputError(
            f"Noema LLM response 'choices' was not a list (got {type(choices).__name__})"
        )
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise NoemaModelOutputError(
            "Noema LLM response choices[0] was not a JSON object "
            f"(got {type(first_choice).__name__})"
        )
    message = first_choice.get("message")
    if not message:
        message = {}
    elif not isinstance(message, dict):
        raise NoemaModelOutputError(
            f"Noema LLM response 'message' was not a JSON object (got {type(message).__name__})"
        )
    content = message.get("content")
    if not content:
        content = ""
    elif not isinstance(content, str):
        raise NoemaModelOutputError(
            f"Noema LLM response 'content' was not a string (got {type(content).__name__})"
        )
    return content.strip()


def decode_llm_response_body(raw_bytes: bytes) -> str:
    """Decode the raw gateway HTTP response body as UTF-8 text.

    Devin Review bug finding on PR #1507 round 3: a gateway reply containing
    invalid UTF-8 used to raise ``UnicodeDecodeError`` at the plain
    ``response.read().decode("utf-8")`` call in ``call_llm``, before that
    body ever reached ``extract_llm_message_content`` or the verdict-JSON
    repair boundary. That crashed the required review check with an
    unhandled traceback instead of getting the same one-time schema-repair
    retry every other malformed-envelope shape already gets. Call this
    inside ``call_llm``'s existing repair-retry ``try`` block so a decode
    failure converts to the same bounded ``RuntimeError`` and gets the same
    fail-closed treatment.

    The raised diagnostic never embeds the raw response bytes — not even
    the undecodable fragment. Only a length and a SHA-256 content
    fingerprint are logged, matching ``extract_json_object``'s no-raw-content
    pattern: a body containing invalid UTF-8 could still contain a
    credential-adjacent byte sequence, and this is a ``pull_request_target``
    workflow whose Actions logs are public on this org's public repos.
    """
    try:
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        fingerprint = hashlib.sha256(raw_bytes).hexdigest()[:16]
        raise NoemaModelOutputError(
            f"Noema LLM response body was not valid UTF-8 ({exc}). Raw "
            "response bytes are not logged here (this pull_request_target "
            "workflow's logs are public and a finite secret-scrub pattern "
            "list cannot guarantee an LLM-echoed or hallucinated credential "
            "in an unrecognized byte sequence is caught): response "
            f"length={len(raw_bytes)} bytes, sha256={fingerprint}."
        ) from exc


def _extract_served_model(raw: str) -> str | None:
    """Return a bounded, scrubbed, single-line UTF-8-printable serving model id."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return _safe_model_identifier(data.get("model"))


def _safe_model_identifier(value: Any) -> str | None:
    """Accept only a conservative, bounded model identifier safe for public logs."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not SAFE_MODEL_IDENTIFIER_RE.fullmatch(candidate):
        return None
    return candidate


def _extract_http_error_telemetry(exc: urllib.error.HTTPError) -> dict[str, str | int]:
    """Read bounded, allowlisted gateway failure telemetry without raw diagnostics.

    The response body is never returned or logged. Only the canonical
    ``error.detail`` receipt fields are allowed; malformed, oversized, or
    unexpected envelopes fail closed to no telemetry.
    """
    try:
        raw_bytes = exc.read(MAX_HTTP_ERROR_BODY_BYTES + 1)
    except (AttributeError, OSError, ValueError, http.client.HTTPException):
        return {}
    if len(raw_bytes) > MAX_HTTP_ERROR_BODY_BYTES:
        return {}
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    error = payload.get("error")
    if not isinstance(error, dict):
        return {}
    detail = error.get("detail")
    if not isinstance(detail, dict):
        return {}
    telemetry: dict[str, str | int] = {}
    model = _safe_model_identifier(detail.get("model"))
    terminal_reason = _safe_model_identifier(detail.get("terminal_reason"))
    attempts = detail.get("attempts")
    if model is not None:
        telemetry["served_model"] = model
    if terminal_reason is not None:
        telemetry["terminal_reason"] = terminal_reason
    if isinstance(attempts, list) and attempts and len(attempts) <= 64:
        last_attempt = attempts[-1]
        if isinstance(last_attempt, dict):
            provider_name = _safe_model_identifier(last_attempt.get("provider_name"))
            phase = _safe_model_identifier(last_attempt.get("phase"))
            attempt_number = last_attempt.get("attempt_number")
            provider_status = last_attempt.get("provider_status")
            if provider_name is not None:
                telemetry["provider_name"] = provider_name
            if phase is not None:
                telemetry["upstream_phase"] = phase
            if type(attempt_number) is int and 1 <= attempt_number <= 64:
                telemetry["attempt_number"] = attempt_number
            if type(provider_status) is int and 100 <= provider_status <= 599:
                telemetry["upstream_status"] = provider_status
    return telemetry


def _extract_http_error_served_model(exc: urllib.error.HTTPError) -> str | None:
    """Return the safe served model from one bounded gateway error envelope."""
    model = _extract_http_error_telemetry(exc).get("served_model")
    return model if isinstance(model, str) else None


def _format_gateway_error_telemetry(telemetry: dict[str, str | int]) -> str:
    """Format only allowlisted scalar receipt fields for a public Actions log."""
    ordered_keys = (
        "provider_name",
        "upstream_phase",
        "attempt_number",
        "upstream_status",
        "terminal_reason",
    )
    return " ".join(
        f"{key}={telemetry[key]}" for key in ordered_keys if key in telemetry
    )


def _bounded_allowed_locations_json(allowed_locations: Sequence[dict[str, Any]]) -> str:
    """Serialize the largest location prefix that fits the prompt byte budget."""
    total_count = len(allowed_locations)

    def render(count: int) -> str:
        """Serialize the first `count` locations, flagged as truncated if fewer than all."""
        return json.dumps(
            {
                "total_count": total_count,
                "truncated": count < total_count,
                "locations": list(allowed_locations[:count]),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    low = 0
    high = total_count
    while low < high:
        midpoint = (low + high + 1) // 2
        if len(render(midpoint).encode("utf-8")) <= MAX_ALLOWED_LOCATIONS_JSON_BYTES:
            low = midpoint
        else:
            high = midpoint - 1
    return render(low)


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
    expected_head: str,
    review_context: str = "",
    changed_paths: Sequence[str] = (),
) -> dict[str, Any]:
    """Issue exactly one structured-output request through contextual-orchestrator.

    The gateway owns provider discovery, schema repair, candidate exclusion,
    failover, and model timeouts. This caller therefore performs one request,
    carries no fixed model wall-clock deadline or sampling temperature, and
    fails closed if the gateway does not return a locally valid verdict.
    Publication still performs a fresh exact-head check after model work.
    """
    api_url = os.environ.get("NOEMA_LLM_API_URL", "").strip()
    api_key = os.environ.get("NOEMA_LLM_API_KEY", "").strip()
    model = os.environ.get("NOEMA_LLM_MODEL", "").strip() or "orchestrator/free"
    if not api_url or not api_key:
        raise RuntimeError(
            "Noema LLM review unavailable: NOEMA_LLM_API_URL or NOEMA_LLM_API_KEY is not configured."
        )
    reject_private_llm_url(api_url)

    allowed_locations = [
        {"path": path, "line": line, "side": side}
        for path, line, side in sorted(changed_diff_locations(diff))
    ]
    location_example = allowed_locations[0] if allowed_locations else {
        "path": "path", "line": 0, "side": "RIGHT"
    }
    allowed_locations_json = _bounded_allowed_locations_json(allowed_locations)
    prompt = {
        "role": "user",
        "content": "\n".join(
            [
                "You are Noema, an independent pull request reviewer for ContextualWisdomLab.",
                "Review the PR diff plus the additional changed-file and review-thread context for correctness, security, maintainability, and behavioral regressions.",
                "Return only JSON with the declared response_format schema.",
                "Every formal verdict must cite exact changed-side lines. APPROVE requires falsifying concrete regression hypotheses; material source or test changes require at least two distinct probe_kind values and other changes require at least one. REQUEST_CHANGES requires a confirmed probe at a finding location.",
                "Use only path, line, and side tuples listed in the bounded allowed-locations JSON below. If it is truncated, omit a formal verdict for any location not listed instead of guessing.",
                f"Allowed changed-side locations: {allowed_locations_json}",
                f"Location shape example: {json.dumps(location_example, separators=(',', ':'))}",
                "Observed defect taxonomy and required source-bound class_evidence keys: "
                + json.dumps(
                    {kind: list(fields) for kind, fields in OBSERVED_REVIEW_PROBE_EVIDENCE_FIELDS.items()},
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "Every class_evidence witness must include path, line, side, source_excerpt, claim_role, and observation. source_excerpt must be the exact cited changed-side line, including an empty string for a blank line; an overlong-line omission marker is never source evidence. claim_role is the exact class-and-field role emitted by the schema. The observation must quote that exact source_excerpt (or <blank>) and explain the claimed behavior. The deterministic gate validates source identity and the structural role; it deliberately does not guess causality from an English relation-word list.",
                "Actively attack mutable alias/immutability escapes, time-of-check/time-of-use or changing-getter behavior, execution/tenant/request identity confusion, coercion boundaries, weak or vacuous test oracles, cross-file/cross-document contract contradictions, internal-vs-external authority overreach, missing causal dependency context, and security/reliability state-machine races. For automation or CI that mutates a branch or source and then relies on later events, verify that the mutation uses a workflow-starting credential/actor and that downstream required checks can actually be created on the successor head. Distinguish confirmed defects from falsified hypotheses; do not manufacture findings to satisfy the taxonomy.",
                "Use request_changes only for blocking, concrete issues. A generic no-issues statement is not review evidence.",
                "You cannot execute commands or access external documentation in this review. Do not claim that runtime behavior, command output, help text, or external documentation confirmed a conclusion unless the additional context contains a trusted receipt and your evidence cites its exact [receipt:<id>]. No trusted receipts are supplied by this workflow today. State source reasoning and verification directions as such.",
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
        "response_format": _noema_verdict_response_format(
            _required_probe_count(diff, changed_paths)
        ),
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
    attempt_started = time.monotonic()
    active_phase = "connecting"
    served_model: str | None = None
    try:
        with opener.open(request) as response:  # nosec B310
            active_phase = "reading"
            raw_bytes = response.read()
        active_phase = "decoding"
        raw = decode_llm_response_body(raw_bytes)
        served_model = _extract_served_model(raw)
        content = extract_llm_message_content(raw)
        verdict = extract_json_object(content)
        active_phase = "validating"
        decision = str(verdict.get("decision") or "").strip().lower()
        if decision not in {"approve", "request_changes", "comment"}:
            raise NoemaModelOutputError(
                f"Noema LLM returned unsupported decision: {decision!r}"
            )
        summary = verdict.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise NoemaModelOutputError(
                "Noema LLM response did not contain a substantive summary"
            )
        findings = verdict.get("findings")
        if not isinstance(findings, list) or any(
            not isinstance(finding, dict) for finding in findings
        ):
            raise NoemaModelOutputError(
                "Noema LLM response findings must be a list of objects"
            )
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
                raise NoemaModelOutputError(
                    "Noema LLM response contained a malformed finding"
                )
        if decision == "request_changes" and not findings:
            raise NoemaModelOutputError(
                "Noema LLM request_changes response did not contain a substantive finding"
            )
        validate_substantive_verdict(verdict, diff, changed_paths)
        validate_evidence_provenance(verdict)
    except (RuntimeError, urllib.error.URLError, http.client.HTTPException, OSError) as exc:
        gateway_telemetry: dict[str, str | int] = {}
        if isinstance(exc, urllib.error.HTTPError):
            active_phase = "response_error"
            gateway_telemetry = _extract_http_error_telemetry(exc)
            model_value = gateway_telemetry.get("served_model")
            served_model = model_value if isinstance(model_value, str) else None
        elapsed = time.monotonic() - attempt_started
        current_failure = _stable_failure_diagnostic(exc)
        model_note = served_model or "unknown"
        gateway_note = _format_gateway_error_telemetry(gateway_telemetry)
        print(
            f"::warning::Noema gateway attempt outcome=failed phase={active_phase} "
            f"duration={elapsed:.1f}s served_model={model_note}; "
            "caller attempts=1 (gateway owns repair/failover)."
            + (f" gateway {gateway_note}" if gateway_note else "")
        )
        suffix = (
            f"; caller attempts=1, duration={elapsed:.1f}s, "
            f"phase={active_phase}, served_model={model_note}"
            + (f", gateway {gateway_note}" if gateway_note else "")
        )
        if isinstance(exc, NoemaModelOutputError):
            raise NoemaModelOutputError(
                f"Noema model output failed local validation: {current_failure}{suffix}"
            ) from None
        if isinstance(exc, (urllib.error.URLError, http.client.HTTPException, OSError)):
            raise NoemaTransportError(
                f"Noema gateway transport failed: {type(exc).__name__}: {current_failure}{suffix}"
            ) from exc
        raise RuntimeError(
            f"Noema review failed closed: {current_failure}{suffix}"
        ) from exc
    elapsed = time.monotonic() - attempt_started
    print(
        f"::notice::Noema gateway attempt outcome=success phase={active_phase} "
        f"duration={elapsed:.1f}s served_model={served_model or 'unknown'}; "
        "caller attempts=1."
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
                f"- [{probe.get('probe_kind') or 'legacy'}] `{probe.get('path')}:{probe.get('line')} ({probe.get('side')})` "
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
            NOEMA_REVIEW_FOOTER_MARKER,
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


def inspect_and_review(repo: str, number: int, expected_head: str) -> int:
    """Inspect PR state and submit Noema's independent LLM review.

    ``expected_head`` is normalized defensively before the stale-head
    comparisons below and the post-model publication check. The CLI and
    workflow require canonical lowercase SHA input so equivalent casing
    cannot split the workflow concurrency group.
    """
    expected_head = expected_head.strip().lower()
    pr = fetch_pr(repo, number)
    try:
        require_expected_head(pr, expected_head)
    except RuntimeError:
        print("Pull request is closed or its trigger head is stale; Noema review skipped before model work.")
        return 0
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
    changed_files = fetch_changed_files(repo, number)
    changed_paths = tuple(path for path, _status in changed_files)
    review_context = build_review_context(repo, number, pr, changed_files)
    verdict = call_llm(repo, number, pr, diff, truncated, expected_head, review_context, changed_paths)
    current_pr = fetch_pr(repo, number)
    try:
        require_expected_head(current_pr, expected_head)
    except RuntimeError:
        print("Pull request closed or its head changed during review; stale verdict was not published.")
        return 0
    submit_review(repo, number, current_pr, actor, verdict)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse Noema review gate command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--expected-head", required=True)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Run the Noema review gate command."""
    args = parse_args(argv)
    if args.pr_number <= 0:
        raise SystemExit("--pr-number must be positive")
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_head):
        raise SystemExit(
            "--expected-head must be a canonical lowercase 40-character Git SHA"
        )
    return inspect_and_review(args.repo, args.pr_number, args.expected_head)


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main(sys.argv[1:]))
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
