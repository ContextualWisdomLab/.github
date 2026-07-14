#!/usr/bin/env python3
"""Emit structured security findings into the appguardrail tracker.

The central Strix workflow (``.github/workflows/strix.yml``) writes one Markdown
report per vulnerability under ``strix_runs/<run>/vulnerabilities/*.md``. This
module parses those reports into normalized finding records and reconciles them
against issues in ``ContextualWisdomLab/appguardrail``:

GitHub Code Scanning alerts can be included explicitly alongside Strix reports.
The two sources share the same reconciliation path while retaining distinct
labels and stable source identities.

* one open issue per distinct finding (deduplicated by a stable content hash),
* body refreshed on every run, a comment added only when severity or location
  changed,
* close-on-fix for issues whose finding disappeared — but only from a *complete
  full-repo* scan. A PR-scoped scan (``--scope pr``) inspects just the PR's
  changed files, so an absent finding means "outside this PR", never "fixed";
  such scans create/update/reopen findings but never close, preventing a clean
  PR from wiping out every open finding in files it never touched.

Authentication and GitHub API failures are fail-closed and visible in the job
log. Dry-run behavior is available only through an explicit ``--dry-run`` flag;
an absent token never produces a misleading successful collection run.

GitHub access is funneled through :class:`GitHubIssueClient`, a thin ``gh api``
wrapper that is injected so tests can substitute an in-memory fake. All parsing,
hashing, content rendering and operation planning are pure functions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_ISSUES_REPO = "ContextualWisdomLab/appguardrail"
DEFAULT_TOKEN_ENV = "STRIX_ISSUE_APP_TOKEN"
DEFAULT_CODE_SCANNING_TOKEN_ENV = "CODE_SCANNING_SOURCE_TOKEN"
MIN_ACTIONABLE_SEVERITY = "MEDIUM"
MIN_ACTIONABLE_SEVERITY_RANK = 2
MAX_REPORT_BYTES = 1024 * 1024
MAX_REPORT_FILES = 200
MAX_TITLE_CHARS = 240
MAX_FIELD_CHARS = 1000
MAX_SECTION_CHARS = 8000
REPOSITORY_RE = re.compile(r"^ContextualWisdomLab/[A-Za-z0-9_.-]+$")
HEAD_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
PR_NUMBER_RE = re.compile(r"^[1-9][0-9]*$")
RUN_URL_RE = re.compile(
    r"^https://github\.com/ContextualWisdomLab/[A-Za-z0-9_.-]+/actions/runs/"
    r"[1-9][0-9]*(?:/attempts/[1-9][0-9]*)?$"
)
# Scan scope values. Only a FULL-repo scan sees every finding, so only a full
# scan may conclude that an absent finding is fixed and close its issue. A
# PR-scoped scan only inspects the PR's changed files, so a finding's absence
# means "not in this PR" — never "fixed" — and must not close anything.
SCOPE_FULL = "full"
SCOPE_PR = "pr"
FINDING_MARKER_PREFIX = "<!-- strix-finding:"
SEVERITY_MARKER_PREFIX = "<!-- strix-severity:"
LOCATION_MARKER_PREFIX = "<!-- strix-location:"
SOURCE_MARKER_PREFIX = "<!-- security-source:"
SHORT_HASH_LENGTH = 12

SEVERITY_ORDER = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "NONE": 0,
    "INFO": 0,
    "INFORMATIONAL": 0,
}

# Field-line regexes tolerate optional Markdown bullets/bold, e.g.
# "- **Severity:** HIGH" or "Severity: HIGH".
_FIELD_PREFIX = r"^[\s>*_`-]*\**\s*"


def _field_pattern(names: str) -> re.Pattern[str]:
    """Compile a case-insensitive field-line regex for the given field names."""
    return re.compile(
        _FIELD_PREFIX + rf"(?:{names})\**\s*:\**\s*(.+?)\s*$",
        re.IGNORECASE,
    )


TITLE_RE = _field_pattern("Title")
SEVERITY_RE = _field_pattern("Severity")
CVSS_SCORE_RE = _field_pattern("CVSS Score|CVSS")
CVSS_VECTOR_RE = _field_pattern("CVSS Vector|Vector")
TARGET_RE = _field_pattern("Target")
ENDPOINT_RE = _field_pattern("Endpoint")
METHOD_RE = _field_pattern("Method")
MODEL_RE = _field_pattern("Model")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
SECTION_RE = re.compile(
    _FIELD_PREFIX + r"(Description|Impact|Remediation)\s*:\s*\**\s*(.*?)\s*$",
    re.IGNORECASE,
)
CODE_LOCATIONS_HEADER_RE = re.compile(
    _FIELD_PREFIX + r"Code Locations?\s*:?\s*\**\s*$", re.IGNORECASE
)
# path:line or path:line-range, path allows repo-relative and /workspace forms.
LOCATION_RE = re.compile(
    r"(?P<path>(?:/workspace/|/tmp/strix-pr-scope\.[^\s:`]+/)?[A-Za-z0-9_][A-Za-z0-9_./\[\]-]*\.[A-Za-z0-9_]+)"
    r":(?P<start>\d+)(?:-(?P<end>\d+))?"
)


@dataclass
class Finding:
    """A single normalized security finding from Strix or Code Scanning."""

    source_repo: str
    title: str
    severity: str
    code_location: str
    cvss: str = ""
    cvss_vector: str = ""
    target: str = ""
    endpoint: str = ""
    method: str = ""
    model: str = ""
    description: str = ""
    impact: str = ""
    remediation: str = ""
    source_file: str = ""
    source_kind: str = "strix"
    dedup_identity: str = ""

    @property
    def normalized_location(self) -> str:
        """Return the code location used for dedup (empty locations collapse)."""
        return normalize_location(self.code_location)

    @property
    def finding_hash(self) -> str:
        """Return the stable dedup hash for this finding."""
        if self.dedup_identity:
            payload = "\n".join(
                [
                    self.source_repo.strip(),
                    self.source_kind.strip().casefold(),
                    self.dedup_identity.strip().casefold(),
                ]
            )
            return hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return finding_dedup_hash(self.source_repo, self.title, self.code_location)

    @property
    def short_hash(self) -> str:
        """Return the shortened dedup hash used in labels."""
        return self.finding_hash[:SHORT_HASH_LENGTH]


@dataclass
class Operation:
    """A planned issue mutation (create/update/comment/close)."""

    action: str
    finding_hash: str
    short_hash: str
    title: str
    issue_number: int | None = None
    reason: str = ""
    labels: list[str] = field(default_factory=list)
    body: str = ""
    comment: str = ""

    def describe(self) -> str:
        """Return a single-line human-readable summary of the operation."""
        target = f"#{self.issue_number}" if self.issue_number is not None else "new"
        detail = f" ({self.reason})" if self.reason else ""
        return (
            f"{self.action.upper()} {target} [{self.short_hash}] {self.title}{detail}"
        )


def severity_rank(severity: str) -> int:
    """Return a numeric rank for a severity label (unknown severities rank -1)."""
    return SEVERITY_ORDER.get((severity or "").strip().upper(), -1)


def is_actionable_severity(severity: str) -> bool:
    """Return whether ``severity`` meets the organization Medium+ policy."""
    return severity_rank(severity) >= MIN_ACTIONABLE_SEVERITY_RANK


def sanitize_report_text(value: str, *, limit: int) -> str:
    """Bound untrusted report text and neutralize issue-control syntax."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value or "")
    text = text.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    text = re.sub(r"@(?=[A-Za-z0-9])", "@\u200b", text)
    return text[:limit]


def inline_code(value: str) -> str:
    """Return report text safe for a single-backtick Markdown code span."""
    return sanitize_report_text(value, limit=MAX_FIELD_CHARS).replace("`", "'")


def validated_source_repo(value: str) -> str:
    """Validate an organization-owned source repository argument."""
    if not REPOSITORY_RE.fullmatch(value or ""):
        raise argparse.ArgumentTypeError(
            "source repository must match ContextualWisdomLab/<safe-name>"
        )
    return value


def validated_issues_repo(value: str) -> str:
    """Restrict issue writes to the designated AppGuardrail tracker."""
    if value != DEFAULT_ISSUES_REPO:
        raise argparse.ArgumentTypeError(
            f"issues repository must be exactly {DEFAULT_ISSUES_REPO}"
        )
    return value


def validated_pr_number(value: str) -> str:
    """Validate an optional positive pull-request number."""
    if value and not PR_NUMBER_RE.fullmatch(value):
        raise argparse.ArgumentTypeError("PR number must be a positive integer")
    return value


def validated_head_sha(value: str) -> str:
    """Validate an optional immutable Git commit SHA."""
    if value and not HEAD_SHA_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "head SHA must be a 40-character hexadecimal commit"
        )
    return value.lower()


def validated_run_url(value: str) -> str:
    """Validate an optional organization-owned GitHub Actions run URL."""
    if value and not RUN_URL_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "run URL must identify a ContextualWisdomLab GitHub Actions run"
        )
    return value


def validated_run_dir(value: str) -> Path:
    """Resolve an existing non-symlink directory containing Strix reports."""
    path = Path(value)
    try:
        if path.is_symlink() or not path.is_dir():
            raise argparse.ArgumentTypeError(
                "run directory must be an existing non-symlink directory"
            )
        return path.resolve(strict=True)
    except OSError as exc:
        raise argparse.ArgumentTypeError(
            f"run directory could not be resolved: {exc}"
        ) from exc


def validated_token_env(value: str) -> str:
    """Restrict credential lookup to the designated App token variable."""
    if value != DEFAULT_TOKEN_ENV:
        raise argparse.ArgumentTypeError(
            f"token environment variable must be exactly {DEFAULT_TOKEN_ENV}"
        )
    return value


def validated_code_scanning_token_env(value: str) -> str:
    """Restrict source alert reads to the designated App token variable."""
    if value != DEFAULT_CODE_SCANNING_TOKEN_ENV:
        raise argparse.ArgumentTypeError(
            "Code Scanning token environment variable must be exactly "
            f"{DEFAULT_CODE_SCANNING_TOKEN_ENV}"
        )
    return value


def normalize_location(location: str) -> str:
    """Normalize a code location string for stable hashing/comparison.

    Strips ``/workspace/<repo>/`` and PR-scope sandbox prefixes so the same file
    hashes identically across runs, and collapses whitespace.
    """
    value = (location or "").strip()
    if not value:
        return ""
    value = re.sub(r"^/tmp/strix-pr-scope\.[^/]+/", "", value)
    value = re.sub(r"^/workspace/[^/]+/", "", value)
    value = value.lstrip("/")
    return value


def finding_dedup_hash(source_repo: str, title: str, code_location: str) -> str:
    """Return the SHA-256 dedup key for a finding.

    Key = sha256(source_repo + '\\n' + title + '\\n' + normalized_code_location).
    Titles are whitespace-collapsed so cosmetic wrapping differences do not fork
    the identity of a finding.
    """
    normalized_title = re.sub(r"\s+", " ", (title or "").strip())
    payload = "\n".join(
        [
            (source_repo or "").strip(),
            normalized_title,
            normalize_location(code_location),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _match_field(pattern: re.Pattern[str], line: str) -> str | None:
    """Return the captured field value for ``line`` or ``None``."""
    match = pattern.match(line)
    if match:
        return match.group(1).strip().strip("*").strip("`").strip()
    return None


def parse_finding_markdown(
    text: str, source_repo: str, source_file: str = ""
) -> Finding | None:
    """Parse one Strix vulnerability Markdown report into a :class:`Finding`.

    Returns ``None`` when the report has no title (i.e. is not a real finding).
    Missing fields are tolerated; a finding with no code location keeps an empty
    location (still deduplicated by repo+title).
    """
    lines = text.splitlines()
    title = ""
    field_values = {
        "severity": "",
        "cvss": "",
        "cvss_vector": "",
        "target": "",
        "endpoint": "",
        "method": "",
        "model": "",
    }
    location = ""
    explicit_title = False
    section_text: dict[str, list[str]] = {
        "description": [],
        "impact": [],
        "remediation": [],
    }
    current_section: str | None = None
    in_code_locations = False

    for raw_line in lines:
        line = raw_line.rstrip()

        heading = HEADING_RE.match(line)
        if heading:
            candidate = heading.group(1).strip()
            heading_name = candidate.rstrip(":").strip().casefold()
            if heading_name in section_text:
                current_section = heading_name
                in_code_locations = False
                continue
            if heading_name in {"code location", "code locations"}:
                current_section = None
                in_code_locations = True
                continue
            # Ignore generic report banners as titles.
            if not title and heading_name not in {
                "vulnerability report",
                "strix",
                "findings",
            }:
                title = candidate
            current_section = None
            in_code_locations = False
            continue

        for pattern, setter in (
            (TITLE_RE, "title"),
            (SEVERITY_RE, "severity"),
            (CVSS_VECTOR_RE, "cvss_vector"),
            (CVSS_SCORE_RE, "cvss"),
            (TARGET_RE, "target"),
            (ENDPOINT_RE, "endpoint"),
            (METHOD_RE, "method"),
            (MODEL_RE, "model"),
        ):
            value = _match_field(pattern, line)
            if value is not None:
                if setter == "title":
                    title = value
                    explicit_title = True
                else:
                    field_values[setter] = (
                        value.upper() if setter == "severity" else value
                    )
                current_section = None
                in_code_locations = False
                break
        else:
            section = SECTION_RE.match(line)
            if section:
                current_section = section.group(1).lower()
                in_code_locations = False
                inline_section = section.group(2).strip()
                if inline_section:
                    section_text[current_section].append(inline_section)
                continue
            if CODE_LOCATIONS_HEADER_RE.match(line):
                in_code_locations = True
                current_section = None
                continue
            if in_code_locations or not location:
                loc_match = LOCATION_RE.search(line)
                if loc_match and (in_code_locations or _looks_like_location_line(line)):
                    location = _format_location(loc_match)
                    in_code_locations = False
                    continue
            if current_section and line.strip():
                section_text[current_section].append(line.strip())

    severity = field_values["severity"]
    cvss = field_values["cvss"]
    cvss_vector = field_values["cvss_vector"]
    target = field_values["target"]
    endpoint = field_values["endpoint"]
    method = field_values["method"]
    model = field_values["model"]

    # Fall back to any location anywhere in the report.
    if not location:
        loc_match = LOCATION_RE.search(text)
        if loc_match:
            location = _format_location(loc_match)

    # A heading alone is only a finding when it carries a real finding signal.
    has_finding_signal = (
        explicit_title or bool(severity) or bool(location) or bool(cvss)
    )
    if not title or not has_finding_signal:
        return None

    severity = severity if severity_rank(severity) >= 0 else severity.upper()

    return Finding(
        source_repo=source_repo,
        title=sanitize_report_text(
            re.sub(r"\s+", " ", title).strip(), limit=MAX_TITLE_CHARS
        ),
        severity=severity,
        code_location=location,
        cvss=sanitize_report_text(cvss, limit=MAX_FIELD_CHARS),
        cvss_vector=sanitize_report_text(cvss_vector, limit=MAX_FIELD_CHARS),
        target=sanitize_report_text(target, limit=MAX_FIELD_CHARS),
        endpoint=sanitize_report_text(endpoint, limit=MAX_FIELD_CHARS),
        method=sanitize_report_text(method, limit=MAX_FIELD_CHARS),
        model=sanitize_report_text(model, limit=MAX_FIELD_CHARS),
        description=sanitize_report_text(
            " ".join(section_text["description"]).strip(), limit=MAX_SECTION_CHARS
        ),
        impact=sanitize_report_text(
            " ".join(section_text["impact"]).strip(), limit=MAX_SECTION_CHARS
        ),
        remediation=sanitize_report_text(
            " ".join(section_text["remediation"]).strip(), limit=MAX_SECTION_CHARS
        ),
        source_file=source_file,
    )


def _looks_like_location_line(line: str) -> bool:
    """Return whether a non-section line plausibly introduces a code location."""
    lowered = line.lower()
    return any(key in lowered for key in ("location", "file", "path", "line"))


def _format_location(match: re.Match[str]) -> str:
    """Render a location regex match as ``path:start[-end]``."""
    path = match.group("path").strip()
    start = match.group("start")
    end = match.group("end")
    if end and end != start:
        return f"{path}:{start}-{end}"
    return f"{path}:{start}"


def iter_vulnerability_files(run_dir: Path) -> list[Path]:
    """Return sorted ``vulnerabilities/*.md`` report paths beneath ``run_dir``.

    Accepts either a single run directory or a parent containing multiple runs;
    symlinked report files/directories are skipped for safety.
    """
    if not run_dir.is_dir():
        return []
    results: list[Path] = []
    for vuln_dir in sorted(run_dir.rglob("vulnerabilities")):
        if not vuln_dir.is_dir() or vuln_dir.is_symlink():
            continue
        for report in sorted(vuln_dir.glob("*.md")):
            if report.is_file() and not report.is_symlink():
                results.append(report)
    if len(results) > MAX_REPORT_FILES:
        raise RuntimeError(
            f"Strix report count {len(results)} exceeds bounded limit {MAX_REPORT_FILES}"
        )
    return results


def parse_run_dir(run_dir: Path, source_repo: str) -> list[Finding]:
    """Parse every vulnerability report under ``run_dir`` into findings.

    Findings are deduplicated by hash within the run so repeated model reports of
    the same vulnerability collapse to a single record.
    """
    findings: dict[str, Finding] = {}
    for report in iter_vulnerability_files(run_dir):
        try:
            report_size = report.stat().st_size
            if report_size > MAX_REPORT_BYTES:
                raise RuntimeError(
                    f"Strix report {report.name} is {report_size} bytes; "
                    f"limit is {MAX_REPORT_BYTES}"
                )
            text = report.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise RuntimeError(f"Could not read Strix report {report}: {exc}") from exc
        finding = parse_finding_markdown(text, source_repo, source_file=report.name)
        if finding is None:
            continue
        if severity_rank(finding.severity) < 0:
            raise RuntimeError(
                f"Strix report {report.name} has a finding without a recognized "
                f"severity: {finding.title}"
            )
        existing = findings.get(finding.finding_hash)
        # Prefer the higher-severity variant when duplicates disagree.
        if existing is None or severity_rank(finding.severity) > severity_rank(
            existing.severity
        ):
            findings[finding.finding_hash] = finding
    return list(findings.values())


def code_scanning_severity(alert: dict[str, Any]) -> str:
    """Return an organization severity for one GitHub Code Scanning alert."""
    rule = alert.get("rule") if isinstance(alert.get("rule"), dict) else {}
    security_level = str(rule.get("security_severity_level") or "").upper()
    if security_level in SEVERITY_ORDER and security_level not in {"NONE", "INFO"}:
        return security_level
    return {
        "ERROR": "HIGH",
        "WARNING": "MEDIUM",
        "NOTE": "LOW",
        "NONE": "INFO",
    }.get(str(rule.get("severity") or "").upper(), "INFO")


def parse_code_scanning_alert(
    alert: dict[str, Any], source_repo: str
) -> Finding | None:
    """Convert one open GitHub Code Scanning alert into a normalized finding."""
    if str(alert.get("state") or "").casefold() != "open":
        return None
    try:
        alert_number = int(alert["number"])
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("Code Scanning returned an open alert without a number")
    if alert_number <= 0:
        raise RuntimeError("Code Scanning returned a non-positive alert number")

    rule = alert.get("rule") if isinstance(alert.get("rule"), dict) else {}
    tool = alert.get("tool") if isinstance(alert.get("tool"), dict) else {}
    instance = (
        alert.get("most_recent_instance")
        if isinstance(alert.get("most_recent_instance"), dict)
        else {}
    )
    location = (
        instance.get("location") if isinstance(instance.get("location"), dict) else {}
    )
    message = (
        instance.get("message") if isinstance(instance.get("message"), dict) else {}
    )
    path = str(location.get("path") or "").strip()
    if path.casefold().startswith("no file associated"):
        path = ""
    code_location = ""
    if path:
        try:
            start = max(1, int(location.get("start_line") or 1))
            end = max(start, int(location.get("end_line") or start))
        except (TypeError, ValueError):
            start = end = 1
        code_location = f"{path}:{start}" if start == end else f"{path}:{start}-{end}"

    rule_id = str(rule.get("id") or rule.get("name") or "unknown-rule")
    description = str(rule.get("description") or rule.get("name") or rule_id)
    tool_name = str(tool.get("name") or "GitHub Code Scanning")
    alert_url = (
        f"https://github.com/{source_repo}/security/code-scanning/{alert_number}"
    )
    return Finding(
        source_repo=source_repo,
        title=sanitize_report_text(
            f"{tool_name} {rule_id}: {description} (alert #{alert_number})",
            limit=MAX_TITLE_CHARS,
        ),
        severity=code_scanning_severity(alert),
        code_location=code_location,
        target=alert_url,
        model=sanitize_report_text(tool_name, limit=MAX_FIELD_CHARS),
        description=sanitize_report_text(
            str(message.get("text") or ""), limit=MAX_SECTION_CHARS
        ),
        impact=sanitize_report_text(
            str(rule.get("full_description") or ""), limit=MAX_SECTION_CHARS
        ),
        remediation=sanitize_report_text(
            str(rule.get("help") or ""), limit=MAX_SECTION_CHARS
        ),
        source_file=f"code-scanning-alert-{alert_number}",
        source_kind="code-scanning",
        dedup_identity=f"alert:{alert_number}",
    )


def parse_code_scanning_alerts(
    alerts: Sequence[dict[str, Any]], source_repo: str
) -> list[Finding]:
    """Parse and deduplicate all open Code Scanning alerts from one API read."""
    findings: dict[str, Finding] = {}
    for alert in alerts:
        if not isinstance(alert, dict):
            raise RuntimeError("Code Scanning returned a non-object alert")
        finding = parse_code_scanning_alert(alert, source_repo)
        if finding is not None:
            findings[finding.finding_hash] = finding
    return list(findings.values())


def _source_links(context: "EmitContext") -> list[str]:
    """Return Markdown links back to the scanned source repo/PR/commit."""
    links: list[str] = [f"- Source repository: `{context.source_repo}`"]
    base = f"https://github.com/{context.source_repo}"
    if context.pr_number:
        links.append(f"- Pull request: {base}/pull/{context.pr_number}")
    if context.head_sha:
        links.append(f"- Head commit: {base}/commit/{context.head_sha}")
    if context.run_url:
        links.append(f"- Security workflow run: {context.run_url}")
    return links


def build_issue_title(finding: Finding) -> str:
    """Return the issue title for a finding."""
    repo_short = finding.source_repo.split("/")[-1]
    location = finding.code_location or "no-location"
    severity = finding.severity or "UNKNOWN"
    title = (
        f"[{finding.source_kind}] {repo_short} {severity}: {finding.title} ({location})"
    )
    return sanitize_report_text(title, limit=MAX_TITLE_CHARS)


def build_issue_labels(finding: Finding) -> list[str]:
    """Return the label set for a finding's issue."""
    repo_short = finding.source_repo.split("/")[-1]
    severity = (finding.severity or "unknown").lower()
    return [
        finding.source_kind,
        "security",
        f"repo:{repo_short}",
        f"severity:{severity}",
    ]


def build_issue_body(finding: Finding, context: "EmitContext") -> str:
    """Return the full issue body Markdown, including hidden reconciliation markers."""
    location = inline_code(finding.code_location or "(no code location reported)")
    parts: list[str] = [
        f"## {finding.title}",
        "",
        f"- Severity: **{finding.severity or 'UNKNOWN'}**",
        f"- Code location: `{location}`",
    ]
    if finding.cvss:
        parts.append(f"- CVSS score: {finding.cvss}")
    if finding.cvss_vector:
        parts.append(f"- CVSS vector: `{inline_code(finding.cvss_vector)}`")
    if finding.target:
        parts.append(f"- Target: `{inline_code(finding.target)}`")
    if finding.endpoint:
        parts.append(f"- Endpoint: `{inline_code(finding.endpoint)}`")
    if finding.method:
        parts.append(f"- Method: `{inline_code(finding.method)}`")
    if finding.model:
        parts.append(f"- Detected by model: `{inline_code(finding.model)}`")
    parts.append("")
    parts.extend(_source_links(context))
    if finding.description:
        parts += ["", "### Description", "", finding.description]
    if finding.impact:
        parts += ["", "### Impact", "", finding.impact]
    if finding.remediation:
        parts += ["", "### Remediation", "", finding.remediation]
    parts += [
        "",
        "---",
        "_Filed automatically by the source-side security issue emitter. "
        "Do not edit the markers below; they drive deduplication and close-on-fix._",
        "",
        f"{FINDING_MARKER_PREFIX} {finding.finding_hash} -->",
        f"{SEVERITY_MARKER_PREFIX} {finding.severity or 'UNKNOWN'} -->",
        f"{LOCATION_MARKER_PREFIX} {finding.normalized_location} -->",
        f"{SOURCE_MARKER_PREFIX} {finding.source_kind} -->",
    ]
    return "\n".join(parts)


def marker_value(body: str, prefix: str) -> str:
    """Return the value stored in a hidden ``<!-- prefix VALUE -->`` marker."""
    escaped = re.escape(prefix)
    match = re.search(escaped + r"\s*(.+?)\s*-->", body or "")
    return match.group(1).strip() if match else ""


def issue_finding_hash(issue: dict[str, Any]) -> str:
    """Return the finding hash recorded on an existing issue (label or marker)."""
    marker = marker_value(str(issue.get("body") or ""), FINDING_MARKER_PREFIX)
    if marker:
        return marker
    for label in _issue_label_names(issue):
        if label.startswith("strix-finding:"):
            return label.split(":", 1)[1]
    return ""


def _issue_label_names(issue: dict[str, Any]) -> list[str]:
    """Return label names for an issue, tolerating string or object labels."""
    names: list[str] = []
    for label in issue.get("labels") or []:
        if isinstance(label, dict):
            name = label.get("name")
        else:
            name = label
        if name:
            names.append(str(name))
    return names


@dataclass
class EmitContext:
    """Immutable context describing the scanned source and run."""

    source_repo: str
    issues_repo: str = DEFAULT_ISSUES_REPO
    pr_number: str = ""
    head_sha: str = ""
    run_url: str = ""
    scan_complete: bool = False
    # Scan scope: SCOPE_FULL only for full-repo push/schedule runs. Defaults to
    # SCOPE_PR (the safe value) so any unset/unknown scope disables close-on-fix.
    scan_scope: str = SCOPE_PR

    @property
    def close_on_fix_enabled(self) -> bool:
        """Return whether close-on-fix may run for this scan.

        Both guards must hold: the scan finished cleanly (``scan_complete``) and
        it covered the whole repository (``scan_scope == SCOPE_FULL``). A
        PR-scoped or unknown-scope scan only inspects the PR's changed files, so
        a finding's absence never proves it was fixed and must not close issues.
        """
        return self.scan_complete and self.scan_scope == SCOPE_FULL


def plan_operations(
    findings: Sequence[Finding],
    existing_issues: Sequence[dict[str, Any]],
    context: EmitContext,
) -> list[Operation]:
    """Compute the create/update/comment/close plan for a scan.

    ``existing_issues`` are the issues already present in the tracker for this
    source repo scope (any state). Pure function: performs no I/O so the
    reconciliation logic — including the close-on-fix set difference and both
    the incomplete-scan and PR-scope guards — is directly testable. Close-on-fix
    runs only when ``context.close_on_fix_enabled`` (clean full-repo scan); a
    PR-scoped scan creates/updates/reopens findings but never closes.
    """
    by_hash: dict[str, dict[str, Any]] = {}
    for issue in existing_issues:
        found_hash = issue_finding_hash(issue)
        if found_hash:
            by_hash.setdefault(found_hash, issue)

    operations: list[Operation] = []
    current_hashes: set[str] = set()

    for finding in findings:
        current_hashes.add(finding.finding_hash)
        body = build_issue_body(finding, context)
        labels = build_issue_labels(finding)
        existing = by_hash.get(finding.finding_hash)
        if existing is None:
            operations.append(
                Operation(
                    action="create",
                    finding_hash=finding.finding_hash,
                    short_hash=finding.short_hash,
                    title=build_issue_title(finding),
                    reason="new finding",
                    labels=labels,
                    body=body,
                )
            )
            continue

        number = _issue_number(existing)
        old_body = str(existing.get("body") or "")
        old_severity = marker_value(old_body, SEVERITY_MARKER_PREFIX)
        # Strix identities pin repo+title+location; Code Scanning identities pin
        # repo+source+alert number so a moved alert refreshes the same issue.
        severity_changed = (
            bool(old_severity)
            and old_severity.upper() != (finding.severity or "UNKNOWN").upper()
        )
        reopened = str(existing.get("state") or "").lower() == "closed"

        reason = "reopen (finding still present)" if reopened else "refresh finding"
        operations.append(
            Operation(
                action="update",
                finding_hash=finding.finding_hash,
                short_hash=finding.short_hash,
                title=build_issue_title(finding),
                issue_number=number,
                reason=reason,
                labels=labels,
                body=body,
            )
        )
        if severity_changed:
            change = f"severity {old_severity} -> {finding.severity or 'UNKNOWN'}"
            operations.append(
                Operation(
                    action="comment",
                    finding_hash=finding.finding_hash,
                    short_hash=finding.short_hash,
                    title=build_issue_title(finding),
                    issue_number=number,
                    reason=change,
                    comment=f"Security finding changed: {change}.",
                )
            )

    if context.close_on_fix_enabled:
        for issue in existing_issues:
            if str(issue.get("state") or "").lower() != "open":
                continue
            found_hash = issue_finding_hash(issue)
            if not found_hash or found_hash in current_hashes:
                continue
            resolved_ref = context.head_sha or "the latest scan"
            operations.append(
                Operation(
                    action="close",
                    finding_hash=found_hash,
                    short_hash=found_hash[:SHORT_HASH_LENGTH],
                    title=str(issue.get("title") or ""),
                    issue_number=_issue_number(issue),
                    reason="finding no longer present",
                    comment=f"Resolved on {resolved_ref}: this security finding is no longer "
                    f"reported for `{context.source_repo}`. Closing automatically.",
                )
            )

    return operations


def _issue_number(issue: dict[str, Any]) -> int | None:
    """Return the integer issue number, or ``None`` when unparseable."""
    try:
        return int(issue["number"])
    except (KeyError, TypeError, ValueError):
        return None


class GitHubCodeScanningClient:
    """Read open Code Scanning alerts with a source-repository App token."""

    def __init__(self, repo: str, token: str) -> None:
        """Store the source repository and its security-events read token."""
        self.repo = repo
        self._token = token

    def list_open_alerts(self) -> list[dict[str, Any]]:
        """Return every open Code Scanning alert after a complete paginated read."""
        env = dict(os.environ)
        env["GH_TOKEN"] = self._token
        result = subprocess.run(  # noqa: S603 - fixed gh argv, no shell
            [
                "gh",
                "api",
                "--paginate",
                "--slurp",
                "-X",
                "GET",
                f"repos/{self.repo}/code-scanning/alerts",
                "-f",
                "state=open",
                "-f",
                "per_page=100",
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(_scrub(result.stderr.strip() or "gh command failed"))
        try:
            pages = json.loads(result.stdout or "[]")
            return [
                alert for page in pages for alert in page if isinstance(alert, dict)
            ]
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Code Scanning API returned invalid JSON") from exc


class GitHubIssueClient:
    """Thin ``gh api`` wrapper for issue reads/writes in the tracker repo."""

    def __init__(self, repo: str, token: str) -> None:
        """Store the target repo and the GitHub App token used for ``gh``."""
        self.repo = repo
        self._token = token

    def _run(self, args: Sequence[str], *, stdin: str | None = None) -> str:
        """Invoke ``gh`` with the App token in the environment and return stdout."""
        env = dict(os.environ)
        env["GH_TOKEN"] = self._token
        result = subprocess.run(  # noqa: S603 - fixed gh argv, no shell
            ["gh", *args],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(_scrub(result.stderr.strip() or "gh command failed"))
        return result.stdout

    def list_scope_issues(self, repo_short: str) -> list[dict[str, Any]]:
        """Return tracked security issues for one source repository (any state)."""
        raw = self._run(
            [
                "api",
                "--paginate",
                "--slurp",
                "-X",
                "GET",
                f"repos/{self.repo}/issues",
                "-f",
                "state=all",
                "-f",
                f"labels=repo:{repo_short}",
                "-f",
                "per_page=100",
            ]
        )
        pages = json.loads(raw or "[]")
        tracked_kinds = {"strix", "code-scanning"}
        return [
            issue
            for page in pages
            for issue in page
            if "pull_request" not in issue
            and tracked_kinds.intersection(_issue_label_names(issue))
        ]

    def ensure_labels(self, labels: Sequence[str]) -> None:
        """Create missing tracker labels before an issue mutation references them."""
        raw = self._run(
            [
                "api",
                "--paginate",
                "--slurp",
                "-X",
                "GET",
                f"repos/{self.repo}/labels",
                "-f",
                "per_page=100",
            ]
        )
        pages = json.loads(raw or "[]")
        existing = {
            str(label.get("name") or "")
            for page in pages
            for label in page
            if isinstance(label, dict)
        }
        for label in sorted(set(labels) - existing):
            color, description = label_style(label)
            payload = json.dumps(
                {"name": label, "color": color, "description": description}
            )
            try:
                self._run(
                    [
                        "api",
                        "-X",
                        "POST",
                        f"repos/{self.repo}/labels",
                        "--input",
                        "-",
                    ],
                    stdin=payload,
                )
            except RuntimeError as exc:
                if "already_exists" not in str(exc).casefold():
                    raise

    def create_issue(self, title: str, body: str, labels: Sequence[str]) -> None:
        """Create a new issue with the given title/body/labels."""
        payload = json.dumps({"title": title, "body": body, "labels": list(labels)})
        self._run(
            ["api", "-X", "POST", f"repos/{self.repo}/issues", "--input", "-"],
            stdin=payload,
        )

    def update_issue(self, number: int, body: str, labels: Sequence[str]) -> None:
        """Refresh an issue body/labels and ensure it is open."""
        payload = json.dumps({"body": body, "labels": list(labels), "state": "open"})
        self._run(
            [
                "api",
                "-X",
                "PATCH",
                f"repos/{self.repo}/issues/{number}",
                "--input",
                "-",
            ],
            stdin=payload,
        )

    def comment_issue(self, number: int, comment: str) -> None:
        """Post a comment on an issue."""
        payload = json.dumps({"body": comment})
        self._run(
            [
                "api",
                "-X",
                "POST",
                f"repos/{self.repo}/issues/{number}/comments",
                "--input",
                "-",
            ],
            stdin=payload,
        )

    def close_issue(self, number: int, comment: str) -> None:
        """Comment on and close an issue."""
        self.comment_issue(number, comment)
        payload = json.dumps({"state": "closed", "state_reason": "completed"})
        self._run(
            [
                "api",
                "-X",
                "PATCH",
                f"repos/{self.repo}/issues/{number}",
                "--input",
                "-",
            ],
            stdin=payload,
        )


_TOKEN_RE = re.compile(r"gh[opsu]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}")


def _scrub(text: str) -> str:
    """Redact anything resembling a GitHub token from a message."""
    return _TOKEN_RE.sub("***", text or "")


def label_style(label: str) -> tuple[str, str]:
    """Return a stable color and description for an emitter-owned label."""
    if label == "strix":
        return "5319e7", "Finding produced by the Strix security workflow"
    if label == "code-scanning":
        return "1d76db", "Finding mirrored from GitHub Code Scanning"
    if label == "security":
        return "d73a4a", "Security vulnerability or security-governance work"
    if label.startswith("severity:critical"):
        return "b60205", "Critical-severity security finding"
    if label.startswith("severity:high"):
        return "d93f0b", "High-severity security finding"
    if label.startswith("severity:medium"):
        return "fbca04", "Medium-severity security finding"
    if label.startswith("severity:low"):
        return "fef2c0", "Low-severity security or governance finding"
    if label.startswith("severity:info"):
        return "d4c5f9", "Informational security or governance finding"
    if label.startswith("repo:"):
        return "0e8a16", "Source repository for this organization security finding"
    return "cfd3d7", "Security finding classification"


def execute_plan(
    operations: Iterable[Operation],
    client: GitHubIssueClient | None,
    *,
    dry_run: bool,
    log: Any = None,
) -> dict[str, int]:
    """Apply (or, in dry-run, log) the planned operations.

    Returns a per-action count summary. Every operation is attempted, but any
    mutation failure increments ``error`` so the caller can fail the workflow.
    """
    emit = log or print
    counts: dict[str, int] = {
        "create": 0,
        "update": 0,
        "comment": 0,
        "close": 0,
        "error": 0,
    }
    for op in operations:
        if dry_run or client is None:
            emit(f"DRY-RUN: would {op.describe()}")
            counts[op.action] = counts.get(op.action, 0) + 1
            continue
        try:
            if op.action == "create":
                client.create_issue(op.title, op.body, op.labels)
            elif op.action == "update":
                client.update_issue(int(op.issue_number), op.body, op.labels)
            elif op.action == "comment":
                client.comment_issue(int(op.issue_number), op.comment)
            elif op.action == "close":
                client.close_issue(int(op.issue_number), op.comment)
            else:
                raise ValueError(f"unsupported issue operation: {op.action}")
            counts[op.action] = counts.get(op.action, 0) + 1
            emit(f"OK: {op.describe()}")
        except Exception as exc:  # noqa: BLE001 - continue to expose all failures
            counts["error"] += 1
            emit(
                f"::error::Strix issue emit failed for {op.describe()}: {_scrub(str(exc))}"
            )
    return counts


def build_arg_parser() -> argparse.ArgumentParser:
    """Return the command-line argument parser."""
    parser = argparse.ArgumentParser(
        description="Emit per-finding Strix issues into appguardrail."
    )
    parser.add_argument(
        "--run-dir",
        required=True,
        type=validated_run_dir,
        help="Directory containing strix_runs vulnerability reports.",
    )
    parser.add_argument(
        "--source-repo",
        required=True,
        type=validated_source_repo,
        help="Scanned repository in owner/name form.",
    )
    parser.add_argument(
        "--issues-repo",
        default=DEFAULT_ISSUES_REPO,
        type=validated_issues_repo,
        help="Tracker repository in owner/name form.",
    )
    parser.add_argument(
        "--pr-number",
        default="",
        type=validated_pr_number,
        help="Pull request number, if the scan was PR-scoped.",
    )
    parser.add_argument(
        "--head-sha",
        default="",
        type=validated_head_sha,
        help="Scanned head commit SHA.",
    )
    parser.add_argument(
        "--run-url",
        default="",
        type=validated_run_url,
        help="URL of the Strix workflow run.",
    )
    parser.add_argument(
        "--scan-complete",
        action="store_true",
        help="Set only when the scan finished cleanly; required to enable close-on-fix.",
    )
    parser.add_argument(
        "--scope",
        choices=(SCOPE_FULL, SCOPE_PR),
        default=SCOPE_PR,
        help=(
            "Scan scope: 'full' for a whole-repo push/schedule scan (enables "
            "close-on-fix), 'pr' for a PR-scoped scan of changed files only "
            "(never closes issues). Defaults to the safe 'pr' value."
        ),
    )
    parser.add_argument(
        "--token-env",
        default=DEFAULT_TOKEN_ENV,
        type=validated_token_env,
        help="Env var holding the GitHub App token.",
    )
    parser.add_argument(
        "--include-code-scanning",
        action="store_true",
        help="Read and reconcile all open GitHub Code Scanning alerts.",
    )
    parser.add_argument(
        "--code-scanning-token-env",
        default=DEFAULT_CODE_SCANNING_TOKEN_ENV,
        type=validated_code_scanning_token_env,
        help="Env var holding the source-repository security-events read token.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan and log operations without mutating GitHub.",
    )
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. Parses findings, plans operations, and applies them."""
    args = build_arg_parser().parse_args(argv)
    context = EmitContext(
        source_repo=args.source_repo,
        issues_repo=args.issues_repo,
        pr_number=str(args.pr_number or ""),
        head_sha=str(args.head_sha or ""),
        run_url=str(args.run_url or ""),
        scan_complete=bool(args.scan_complete),
        scan_scope=args.scope,
    )

    try:
        parsed_findings = parse_run_dir(args.run_dir, context.source_repo)
    except RuntimeError as exc:
        print(
            f"::error::Strix issue emitter could not parse reports: {_scrub(str(exc))}"
        )
        return 1
    strix_finding_count = len(parsed_findings)
    code_scanning_findings: list[Finding] = []
    if args.include_code_scanning:
        source_token = os.environ.get(args.code_scanning_token_env, "").strip()
        if not source_token:
            print(
                f"::error::{args.code_scanning_token_env} is not set; GitHub Code "
                "Scanning alerts cannot be read or reconciled. Provision the Noema "
                "GitHub App with security-events read permission."
            )
            return 2
        try:
            alerts = GitHubCodeScanningClient(
                context.source_repo, source_token
            ).list_open_alerts()
            code_scanning_findings = parse_code_scanning_alerts(
                alerts, context.source_repo
            )
        except RuntimeError as exc:
            print(
                "::error::Could not read GitHub Code Scanning alerts; refusing "
                f"an incomplete reconciliation: {_scrub(str(exc))}"
            )
            return 1
        parsed_findings.extend(code_scanning_findings)
        print(
            f"Read {len(alerts)} open GitHub Code Scanning alert(s); normalized "
            f"{len(code_scanning_findings)} finding(s) for reconciliation."
        )
    unknown_severity = [
        finding for finding in parsed_findings if severity_rank(finding.severity) < 0
    ]
    if unknown_severity:
        titles = ", ".join(finding.title for finding in unknown_severity[:5])
        print(
            "::error::Strix issue emitter found report(s) without a recognized "
            f"severity; refusing reconciliation so findings are not lost: {titles}"
        )
        return 1
    findings = [
        finding
        for finding in parsed_findings
        if finding.source_kind == "code-scanning"
        or is_actionable_severity(finding.severity)
    ]
    skipped = len(
        [
            finding
            for finding in parsed_findings
            if finding.source_kind == "strix"
            and not is_actionable_severity(finding.severity)
        ]
    )
    print(
        f"Parsed {strix_finding_count} distinct Strix finding(s) from {args.run_dir}; "
        f"{strix_finding_count - skipped} meet the {MIN_ACTIONABLE_SEVERITY}+ "
        f"issue policy; prepared {len(findings)} tracker finding(s), including "
        f"{len(code_scanning_findings)} Code Scanning alert(s); {skipped} "
        "lower-severity Strix finding(s) were not filed."
    )
    if not context.scan_complete:
        print("Scan not marked complete: close-on-fix is disabled for this run.")
    elif context.scan_scope != SCOPE_FULL:
        print(
            f"Scan scope is '{context.scan_scope}' (PR-scoped): close-on-fix is disabled; "
            "absent findings are treated as out-of-scope, not fixed."
        )

    token = os.environ.get(args.token_env, "").strip()
    dry_run = bool(args.dry_run)
    if not dry_run and not token:
        print(
            f"::error::{args.token_env} is not set; AppGuardrail issue collection "
            "cannot mutate or reconcile findings. Provision the Noema GitHub App "
            "with Issues write permission or pass --dry-run explicitly."
        )
        return 2

    repo_short = context.source_repo.split("/")[-1]
    client: GitHubIssueClient | None = None
    existing_issues: list[dict[str, Any]] = []
    if not dry_run:
        client = GitHubIssueClient(context.issues_repo, token)
        try:
            existing_issues = client.list_scope_issues(repo_short)
        except Exception as exc:  # noqa: BLE001 - API errors must fail visibly
            print(
                "::error::Could not read existing AppGuardrail issues; refusing "
                f"an incomplete reconciliation: {_scrub(str(exc))}"
            )
            return 1

    if not findings and not (context.close_on_fix_enabled and existing_issues):
        print("No findings and nothing to reconcile; exiting.")
        return 0

    operations = plan_operations(findings, existing_issues, context)
    if client is not None:
        labels = sorted(
            {label for operation in operations for label in operation.labels}
        )
        try:
            client.ensure_labels(labels)
        except Exception as exc:  # noqa: BLE001 - label bootstrap is required
            print(
                "::error::Could not provision AppGuardrail issue labels; refusing "
                f"partial issue writes: {_scrub(str(exc))}"
            )
            return 1
    counts = execute_plan(operations, client, dry_run=dry_run)
    print(
        "Security issue emit summary: "
        + ", ".join(
            f"{key}={counts.get(key, 0)}"
            for key in ("create", "update", "comment", "close", "error")
        )
        + (" (dry-run)" if dry_run else "")
    )
    return 1 if counts["error"] else 0


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(run())
