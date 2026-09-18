#!/usr/bin/env python3
"""Bind Strix PR findings and remediation claims to authenticated evidence.

Issue #2159: a PR security verdict must distinguish an exact base→head delta
finding from debt found in unchanged protected-base source. Findings attributed
to the PR delta must map to the authenticated changed-file inventory (including
renames) and, when a line is claimed, to a changed hunk. Unchanged paths are
published as ``repository_baseline`` or ``context_dependency`` evidence — never
described as introduced by the PR.

Issue #2168: remediation prose must fail closed when ``apply_patch`` (or an
equivalent edit tool) misses the materialized scan workspace. A report may not
claim a fix was applied unless the changed bytes are re-read from that workspace
and the expected diff is present. Source-repository mutation requires an exact
commit receipt; isolated sandbox edits stay labeled as scan-workspace only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
APPLY_PATCH_FAILURE_RE = re.compile(
    r"(?:WorkspaceReadNotFoundError|ApplyPatchFileNotFoundError|"
    r"apply_patch\s+missing\s+file|"
    r"file\s+not\s+found:\s*/workspace/)",
    re.IGNORECASE,
)
ALREADY_APPLIED_RE = re.compile(
    r"(?:already\s+applied|fix\s+applied|syntax[- ]verified|"
    r"remediation\s+(?:was\s+)?(?:already\s+)?applied)",
    re.IGNORECASE,
)
SAFE_PATH_RE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9_./ \[\]@+-]+$")
MAX_CHANGED_FILES = 3_000
MAX_PAGES = 31


class EvidenceScope(str, Enum):
    """Provenance label for one Strix source finding."""

    PR_DELTA = "pr_delta"
    REPOSITORY_BASELINE = "repository_baseline"
    CONTEXT_DEPENDENCY = "context_dependency"
    UNMAPPED = "unmapped"


class RemediationState(str, Enum):
    """Machine-checkable remediation progress for one finding."""

    FINDING_CONFIRMED = "finding_confirmed"
    FIX_PROPOSED = "fix_proposed"
    FIX_APPLIED_IN_SCAN_WORKSPACE = "fix_applied_in_scan_workspace"
    FIX_VALIDATED = "fix_validated"
    FIX_COMMITTED_TO_SOURCE = "fix_committed_to_source"
    REMEDIATION_FAILED = "remediation_failed"


class EvidenceBindingError(ValueError):
    """Raised when authenticated Strix evidence cannot be established."""


OpenJson = Callable[[str, str], Any]


@dataclass(frozen=True)
class PullRequestBinding:
    """Authenticated repository/PR/base/head tuple for finding attribution."""

    repository: str
    pull_request: int
    state: str
    base_ref: str
    base_sha: str
    head_sha: str

    def require_live_open(self) -> None:
        """Fail closed unless the binding names an open PR with full SHAs."""

        if not isinstance(self.repository, str) or "/" not in self.repository:
            raise EvidenceBindingError("repository must be owner/name")
        if not isinstance(self.pull_request, int) or self.pull_request <= 0:
            raise EvidenceBindingError("pull_request must be a positive integer")
        if self.state != "open":
            raise EvidenceBindingError("pull request must be live and open")
        if not isinstance(self.base_ref, str) or not self.base_ref.strip():
            raise EvidenceBindingError("base_ref is required")
        if not FULL_SHA_RE.fullmatch(self.base_sha):
            raise EvidenceBindingError("base_sha must be a full 40-character commit SHA")
        if not FULL_SHA_RE.fullmatch(self.head_sha):
            raise EvidenceBindingError("head_sha must be a full 40-character commit SHA")
        if self.base_sha == self.head_sha:
            raise EvidenceBindingError("base_sha and head_sha must differ")


@dataclass(frozen=True)
class ChangedPath:
    """One authenticated GitHub changed-file row with optional hunk lines."""

    path: str
    status: str
    previous_path: str | None = None
    changed_lines: frozenset[int] = frozenset()
    patch_available: bool = True


@dataclass(frozen=True)
class FindingLocation:
    """A source location claimed by a Strix finding."""

    path: str
    start_line: int | None = None
    end_line: int | None = None


@dataclass(frozen=True)
class FindingScopeVerdict:
    """Classification of one finding against the authenticated PR delta."""

    scope: EvidenceScope
    path: str
    reason: str


@dataclass(frozen=True)
class ToolEvent:
    """One scanner tool outcome that must constrain remediation claims."""

    tool: str
    success: bool
    target_path: str
    detail: str = ""


@dataclass(frozen=True)
class RemediationVerdict:
    """Fail-closed remediation state derived from tools and workspace bytes."""

    state: RemediationState
    reason: str
    allows_already_applied_claim: bool


def parse_changed_lines_from_patch(patch: str) -> frozenset[int]:
    """Return 1-based head-side line numbers touched by a unified diff patch."""

    lines: set[int] = set()
    current: int | None = None
    for raw in patch.splitlines():
        match = HUNK_HEADER_RE.match(raw)
        if match:
            start = int(match.group(1))
            count = int(match.group(2) or "1")
            current = None if count == 0 else start
            continue
        if current is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            lines.add(current)
            current += 1
        elif raw.startswith("-") and not raw.startswith("---"):
            continue
        elif raw.startswith("\\"):
            continue
        else:
            current += 1
    return frozenset(lines)


def _require_safe_relative_path(path: str) -> str:
    """Reject absolute, empty, and traversal paths before attribution."""

    cleaned = path.strip()
    if not cleaned or not SAFE_PATH_RE.fullmatch(cleaned):
        raise EvidenceBindingError(f"finding path is unsafe: {path!r}")
    return cleaned


def load_changed_paths_from_github(
    api_url: str,
    repository: str,
    pull_request: int,
    token: str,
    opener: OpenJson | None = None,
) -> tuple[ChangedPath, ...]:
    """Materialize the complete GitHub changed-file inventory with renames."""

    open_json = opener or default_github_opener
    files: list[ChangedPath] = []
    for page in range(1, MAX_PAGES + 1):
        url = (
            f"{api_url.rstrip('/')}/repos/{repository}/pulls/{pull_request}/files"
            f"?per_page=100&page={page}"
        )
        payload = open_json(url, token)
        if not isinstance(payload, list):
            raise EvidenceBindingError("GitHub changed-file evidence is not a JSON array")
        for item in payload:
            if not isinstance(item, Mapping):
                raise EvidenceBindingError("GitHub changed-file entry is not an object")
            path = item.get("filename")
            status = item.get("status")
            raw_patch = item.get("patch")
            previous = item.get("previous_filename")
            if not isinstance(path, str) or not path or not isinstance(status, str):
                raise EvidenceBindingError("GitHub changed-file entry has invalid fields")
            if previous is not None and not isinstance(previous, str):
                raise EvidenceBindingError("GitHub renamed entry has invalid previous_filename")
            patch = "" if raw_patch is None else raw_patch
            if not isinstance(patch, str):
                raise EvidenceBindingError("GitHub changed-file patch must be a string or null")
            files.append(
                ChangedPath(
                    path=_require_safe_relative_path(path),
                    status=status,
                    previous_path=(
                        _require_safe_relative_path(previous) if previous else None
                    ),
                    changed_lines=(
                        parse_changed_lines_from_patch(patch) if raw_patch is not None else frozenset()
                    ),
                    patch_available=raw_patch is not None,
                )
            )
            if len(files) > MAX_CHANGED_FILES:
                raise EvidenceBindingError(
                    f"GitHub changed-file pagination exceeded {MAX_CHANGED_FILES} files"
                )
        if len(payload) < 100:
            return tuple(files)
    raise EvidenceBindingError(  # pragma: no cover - page cap is unreachable while MAX_CHANGED_FILES holds
        f"GitHub changed-file pagination exceeded {MAX_CHANGED_FILES} files"
    )


def _require_github_api_https_url(url: str) -> str:
    """Reject non-HTTPS and non-api.github.com URLs before urllib opens them."""

    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.hostname != "api.github.com"
        or parsed.port not in (None, 443)
        or parsed.params
        or parsed.fragment
    ):
        raise EvidenceBindingError(
            "GitHub API URL must be https://api.github.com/... without credentials"
        )
    return url


def default_github_opener(url: str, token: str) -> Any:
    """Fetch one GitHub API JSON document with a bounded Authorization header."""

    if not token:
        raise EvidenceBindingError("GitHub token is required for changed-file evidence")
    safe_url = _require_github_api_https_url(url)
    request = Request(
        safe_url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "contextualwisdomlab-strix-evidence-binding",
        },
        method="GET",
    )
    try:
        # Scheme/host already fail-closed above; keep the audited suppressions that
        # the trusted-uv download sink uses for the same urllib HTTPS pattern.
        with urlopen(  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected  # nosec B310
            request,
            timeout=30,
        ) as response:
            payload = response.read()
    except HTTPError as exc:
        raise EvidenceBindingError(
            f"GitHub changed-file request failed with HTTP {exc.code}"
        ) from exc
    except URLError as exc:
        raise EvidenceBindingError(
            f"GitHub changed-file request failed: {type(exc).__name__}"
        ) from exc
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceBindingError("GitHub changed-file response is not JSON") from exc


def changed_path_index(changed_paths: Sequence[ChangedPath]) -> dict[str, ChangedPath]:
    """Index changed paths by current and previous (rename) names."""

    index: dict[str, ChangedPath] = {}
    for entry in changed_paths:
        index[entry.path] = entry
        if entry.previous_path:
            index[entry.previous_path] = entry
    return index


def require_matching_report_head(
    binding: PullRequestBinding,
    report_head_sha: str | None,
) -> None:
    """Reject stale-head reports that do not match the live PR head."""

    binding.require_live_open()
    if report_head_sha is None or not FULL_SHA_RE.fullmatch(report_head_sha):
        raise EvidenceBindingError("report head SHA is missing or malformed")
    if report_head_sha != binding.head_sha:
        raise EvidenceBindingError(
            "stale-head report: report head SHA does not match live PR head"
        )


def require_matching_report_base(
    binding: PullRequestBinding,
    report_base_sha: str | None,
) -> None:
    """Reject stacked-base reports that do not match the authenticated base."""

    binding.require_live_open()
    if report_base_sha is None or not FULL_SHA_RE.fullmatch(report_base_sha):
        raise EvidenceBindingError("report base SHA is missing or malformed")
    if report_base_sha != binding.base_sha:
        raise EvidenceBindingError(
            "stacked-base report: report base SHA does not match authenticated base"
        )


def classify_finding_scope(
    binding: PullRequestBinding,
    changed_paths: Sequence[ChangedPath],
    location: FindingLocation,
    *,
    context_dependency_paths: frozenset[str] = frozenset(),
    report_head_sha: str | None = None,
    report_base_sha: str | None = None,
) -> FindingScopeVerdict:
    """Classify one finding as PR-delta, baseline, context, or unmapped."""

    binding.require_live_open()
    if not changed_paths and not context_dependency_paths:
        raise EvidenceBindingError(
            "authenticated changed-file inventory could not be established"
        )
    if report_head_sha is not None:
        require_matching_report_head(binding, report_head_sha)
    if report_base_sha is not None:
        require_matching_report_base(binding, report_base_sha)

    try:
        path = _require_safe_relative_path(location.path)
    except EvidenceBindingError:
        return FindingScopeVerdict(
            scope=EvidenceScope.UNMAPPED,
            path=location.path,
            reason="finding path provenance could not be established",
        )

    index = changed_path_index(changed_paths)
    entry = index.get(path)
    if entry is not None:
        if location.start_line is None:
            return FindingScopeVerdict(
                scope=EvidenceScope.PR_DELTA,
                path=entry.path,
                reason="finding path is in the authenticated changed-file inventory",
            )
        if location.start_line <= 0:
            return FindingScopeVerdict(
                scope=EvidenceScope.UNMAPPED,
                path=entry.path,
                reason="line-level evidence must use a positive line number",
            )
        end_line = location.end_line if location.end_line is not None else location.start_line
        if end_line < location.start_line:
            return FindingScopeVerdict(
                scope=EvidenceScope.UNMAPPED,
                path=entry.path,
                reason="finding line range is inverted",
            )
        if not entry.patch_available:
            # Truncated GitHub patches still prove the path changed; line
            # membership cannot be denied, so path-level PR-delta stands.
            return FindingScopeVerdict(
                scope=EvidenceScope.PR_DELTA,
                path=entry.path,
                reason="changed path has no inline patch; path-level PR-delta attribution stands",
            )
        claimed = set(range(location.start_line, end_line + 1))
        if claimed & set(entry.changed_lines):
            return FindingScopeVerdict(
                scope=EvidenceScope.PR_DELTA,
                path=entry.path,
                reason="finding line intersects an authenticated changed hunk",
            )
        return FindingScopeVerdict(
            scope=EvidenceScope.REPOSITORY_BASELINE,
            path=entry.path,
            reason=(
                "path changed in the PR but the claimed line is outside every "
                "authenticated changed hunk"
            ),
        )

    if path in context_dependency_paths:
        return FindingScopeVerdict(
            scope=EvidenceScope.CONTEXT_DEPENDENCY,
            path=path,
            reason="finding is in unchanged dependency/context closure, not the PR delta",
        )

    return FindingScopeVerdict(
        scope=EvidenceScope.REPOSITORY_BASELINE,
        path=path,
        reason="finding path is base-identical across the authenticated PR tuple",
    )


def detect_apply_patch_failures(log_text: str) -> tuple[ToolEvent, ...]:
    """Extract apply_patch / workspace-miss failures from a Strix execution log."""

    events: list[ToolEvent] = []
    for line in log_text.splitlines():
        if not APPLY_PATCH_FAILURE_RE.search(line):
            continue
        target = "unknown"
        path_match = re.search(
            r"(?:file not found:\s*|missing file:\s*|apply_patch missing file:\s*)"
            r"(/workspace/\S+|\S+)",
            line,
            re.IGNORECASE,
        )
        if path_match:
            target = path_match.group(1).rstrip(".,;")
        events.append(
            ToolEvent(
                tool="apply_patch",
                success=False,
                target_path=target,
                detail=line.strip(),
            )
        )
    return tuple(events)


def workspace_contains_expected_diff(
    workspace_root: Path,
    relative_path: str,
    expected_snippet: str,
) -> bool:
    """Return whether the exact scan workspace file contains the expected bytes."""

    if not expected_snippet:
        return False
    try:
        safe = _require_safe_relative_path(relative_path)
    except EvidenceBindingError:
        return False
    candidate = workspace_root / safe
    if candidate.is_symlink():
        return False
    try:
        resolved_root = workspace_root.resolve(strict=True)
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(resolved_root)
    except (ValueError, FileNotFoundError, OSError):
        return False
    if not candidate.is_file():
        return False
    try:
        text = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return expected_snippet in text


def classify_remediation(
    *,
    finding_confirmed: bool,
    fix_proposed: bool,
    tool_events: Sequence[ToolEvent],
    workspace_root: Path | None,
    relative_path: str | None,
    expected_snippet: str | None,
    source_commit_sha: str | None,
    report_claims_already_applied: bool,
) -> RemediationVerdict:
    """Derive remediation state; never mark applied after a failed edit tool."""

    failures = [event for event in tool_events if not event.success]
    if failures:
        if report_claims_already_applied:
            return RemediationVerdict(
                state=RemediationState.REMEDIATION_FAILED,
                reason=(
                    "report claims a fix was applied but apply_patch/edit failed "
                    f"({failures[0].detail or failures[0].target_path})"
                ),
                allows_already_applied_claim=False,
            )
        return RemediationVerdict(
            state=RemediationState.REMEDIATION_FAILED,
            reason=f"edit tool failed: {failures[0].detail or failures[0].target_path}",
            allows_already_applied_claim=False,
        )

    if source_commit_sha is not None:
        if not FULL_SHA_RE.fullmatch(source_commit_sha):
            raise EvidenceBindingError("source commit receipt must be a full SHA")
        return RemediationVerdict(
            state=RemediationState.FIX_COMMITTED_TO_SOURCE,
            reason="exact source commit receipt is present",
            allows_already_applied_claim=True,
        )

    if (
        workspace_root is not None
        and relative_path is not None
        and expected_snippet is not None
        and workspace_contains_expected_diff(workspace_root, relative_path, expected_snippet)
    ):
        return RemediationVerdict(
            state=RemediationState.FIX_APPLIED_IN_SCAN_WORKSPACE,
            reason="expected diff bytes are present in the exact scan workspace",
            allows_already_applied_claim=True,
        )

    if report_claims_already_applied:
        return RemediationVerdict(
            state=RemediationState.REMEDIATION_FAILED,
            reason=(
                "report claims a fix was applied without workspace-byte proof or "
                "source commit receipt"
            ),
            allows_already_applied_claim=False,
        )

    if fix_proposed:
        return RemediationVerdict(
            state=RemediationState.FIX_PROPOSED,
            reason="a fix was proposed but not proven applied in the scan workspace",
            allows_already_applied_claim=False,
        )

    if finding_confirmed:
        return RemediationVerdict(
            state=RemediationState.FINDING_CONFIRMED,
            reason="finding is confirmed without a proven remediation",
            allows_already_applied_claim=False,
        )

    raise EvidenceBindingError("remediation evidence inputs are incomplete")


def sanitize_remediation_report_text(report_text: str, log_text: str) -> str:
    """Rewrite false 'already applied' claims when apply_patch missed the workspace."""

    failures = detect_apply_patch_failures(log_text)
    if not failures or not ALREADY_APPLIED_RE.search(report_text):
        return report_text

    marker = (
        "\n\n[strix-evidence-binding] Remediation claim rejected: apply_patch/"
        "edit missed the materialized scan workspace "
        f"({failures[0].target_path}). State={RemediationState.REMEDIATION_FAILED.value}. "
        "Do not treat this finding as already repaired.\n"
    )
    cleaned = ALREADY_APPLIED_RE.sub("remediation NOT applied", report_text)
    return cleaned + marker


def pr_delta_findings_block_merge(verdicts: Sequence[FindingScopeVerdict]) -> bool:
    """Return whether any authenticated PR-delta finding must block the PR lane."""

    return any(verdict.scope is EvidenceScope.PR_DELTA for verdict in verdicts)


def baseline_only_findings(verdicts: Sequence[FindingScopeVerdict]) -> bool:
    """Return whether every mapped finding is baseline or context dependency."""

    mapped = [verdict for verdict in verdicts if verdict.scope is not EvidenceScope.UNMAPPED]
    if not mapped:
        return False
    return all(
        verdict.scope
        in {EvidenceScope.REPOSITORY_BASELINE, EvidenceScope.CONTEXT_DEPENDENCY}
        for verdict in mapped
    )


def verdict_to_jsonable(verdict: FindingScopeVerdict | RemediationVerdict) -> dict[str, Any]:
    """Serialize a verdict dataclass for CI artifacts."""

    payload = asdict(verdict)
    for key, value in list(payload.items()):
        if isinstance(value, Enum):
            payload[key] = value.value
    return payload


def _parse_binding(raw: Mapping[str, Any]) -> PullRequestBinding:
    """Build a binding from a JSON object."""

    return PullRequestBinding(
        repository=str(raw["repository"]),
        pull_request=int(raw["pull_request"]),
        state=str(raw["state"]),
        base_ref=str(raw["base_ref"]),
        base_sha=str(raw["base_sha"]),
        head_sha=str(raw["head_sha"]),
    )


def _parse_changed_paths(raw: Sequence[Mapping[str, Any]]) -> tuple[ChangedPath, ...]:
    """Build changed-path rows from a JSON array."""

    rows: list[ChangedPath] = []
    for item in raw:
        lines = item.get("changed_lines", [])
        if not isinstance(lines, list) or not all(isinstance(value, int) for value in lines):
            raise EvidenceBindingError("changed_lines must be a list of integers")
        previous = item.get("previous_path")
        rows.append(
            ChangedPath(
                path=_require_safe_relative_path(str(item["path"])),
                status=str(item["status"]),
                previous_path=(
                    _require_safe_relative_path(str(previous)) if previous else None
                ),
                changed_lines=frozenset(lines),
                patch_available=bool(item.get("patch_available", True)),
            )
        )
    return tuple(rows)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry for gate and failed-check consumers."""

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    classify = sub.add_parser("classify-finding", help="Classify one finding location")
    classify.add_argument("--binding-json", required=True)
    classify.add_argument("--changed-paths-json", required=True)
    classify.add_argument("--path", required=True)
    classify.add_argument("--start-line", type=int)
    classify.add_argument("--end-line", type=int)
    classify.add_argument("--context-path", action="append", default=[])
    classify.add_argument("--report-head-sha")
    classify.add_argument("--report-base-sha")

    remediate = sub.add_parser("classify-remediation", help="Classify remediation state")
    remediate.add_argument("--log-file")
    remediate.add_argument("--report-file")
    remediate.add_argument("--workspace")
    remediate.add_argument("--relative-path")
    remediate.add_argument("--expected-snippet")
    remediate.add_argument("--source-commit-sha")
    remediate.add_argument("--fix-proposed", action="store_true")
    remediate.add_argument("--finding-confirmed", action="store_true", default=True)

    sanitize = sub.add_parser("sanitize-report", help="Strip false already-applied claims")
    sanitize.add_argument("--report-file", required=True)
    sanitize.add_argument("--log-file", required=True)
    sanitize.add_argument("--output-file")

    args = parser.parse_args(argv)
    try:
        if args.command == "classify-finding":
            binding = _parse_binding(json.loads(Path(args.binding_json).read_text(encoding="utf-8")))
            changed = _parse_changed_paths(
                json.loads(Path(args.changed_paths_json).read_text(encoding="utf-8"))
            )
            verdict = classify_finding_scope(
                binding,
                changed,
                FindingLocation(args.path, args.start_line, args.end_line),
                context_dependency_paths=frozenset(args.context_path),
                report_head_sha=args.report_head_sha,
                report_base_sha=args.report_base_sha,
            )
            json.dump(verdict_to_jsonable(verdict), sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
            return 0 if verdict.scope is not EvidenceScope.UNMAPPED else 2

        if args.command == "classify-remediation":
            log_text = Path(args.log_file).read_text(encoding="utf-8") if args.log_file else ""
            report_text = (
                Path(args.report_file).read_text(encoding="utf-8") if args.report_file else ""
            )
            verdict = classify_remediation(
                finding_confirmed=args.finding_confirmed,
                fix_proposed=args.fix_proposed,
                tool_events=detect_apply_patch_failures(log_text),
                workspace_root=Path(args.workspace) if args.workspace else None,
                relative_path=args.relative_path,
                expected_snippet=args.expected_snippet,
                source_commit_sha=args.source_commit_sha,
                report_claims_already_applied=bool(ALREADY_APPLIED_RE.search(report_text)),
            )
            json.dump(verdict_to_jsonable(verdict), sys.stdout, indent=2, sort_keys=True)
            sys.stdout.write("\n")
            return 0 if verdict.allows_already_applied_claim else 2

        if args.command == "sanitize-report":
            report_text = Path(args.report_file).read_text(encoding="utf-8")
            log_text = Path(args.log_file).read_text(encoding="utf-8")
            cleaned = sanitize_remediation_report_text(report_text, log_text)
            if args.output_file:
                Path(args.output_file).write_text(cleaned, encoding="utf-8")
            else:
                sys.stdout.write(cleaned)
            return 0
    except (EvidenceBindingError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    return 2  # pragma: no cover - argparse requires a subcommand


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    raise SystemExit(main())
