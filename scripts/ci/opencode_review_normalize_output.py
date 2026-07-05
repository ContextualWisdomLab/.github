#!/usr/bin/env python3
"""Normalize OpenCode review output into the strict approval-gate contract."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

STRUCTURAL_FAILURE_PHRASES = (
    "structural exploration was not possible",
    "structural exploration not possible",
    "structural exploration is not required",
    "structural exploration not required",
    "structural analysis is not required",
    "structural analysis not required",
    "structural review is not required",
    "structural review not required",
    "no structural exploration required",
    "no structural analysis required",
    "no structural review required",
    "structural exploration is unnecessary",
    "structural analysis is unnecessary",
    "structural review is unnecessary",
    "changed files could not be inspected",
    "source files could not be inspected",
    "required files could not be inspected",
    "could not access changed files",
    "could not access the changed files",
    "could not access source files",
    "could not access the source files",
    "could not access required files",
    "could not access required evidence",
    "evidence was truncated",
    "truncated evidence",
    "no changes detected",
    "no changes were detected",
    "no changes found",
    "no changes were found",
    "no files or changes were found",
    "no files or changes found",
    "no actionable changes to review",
    "no changes to review",
    "no changed files",
)

STRUCTURAL_FAILURE_PATTERNS = (
    re.compile(
        r"\b(?:could not|cannot|can't|unable to)\s+"
        r"(?:inspect|access|review)\s+(?:the\s+)?"
        r"(?:changed|source|required)\s+files?\b"
    ),
    re.compile(
        r"\b(?:changed|source|required)\s+files?\s+"
        r"(?:could not|cannot|can't|were not|was not)\s+"
        r"(?:be\s+)?(?:inspected|accessed|reviewed)\b"
    ),
    re.compile(
        r"\b(?:structural\s+(?:exploration|analysis|review))\s+"
        r"(?:was\s+)?(?:unavailable|incomplete|blocked|not possible)\b"
    ),
    re.compile(
        r"\bno\s+(?:files?\s+or\s+)?changes?\s+"
        r"(?:were\s+)?(?:detected|found|present)\b"
    ),
    re.compile(r"\bno\s+(?:actionable\s+)?changes?\s+to\s+review\b"),
    re.compile(r"\b(?:no|zero)\s+changed\s+files?\b"),
)

NON_ACTIONABLE_FAILED_CHECK_REVIEW_PHRASES = (
    "deterministic missing-string markers",
    "deterministic missing string markers",
    "strix report locations",
    "failed-check evidence below",
    "map each failed check to exact local source lines",
)

MODEL_FAILURE_APPROVAL_PHRASES = (
    "model attempts did not emit a usable current-head control block",
    "all configured opencode model attempts failed",
    "all configured model attempts failed",
    "deterministic fallback approval",
    "deterministic current-head evidence instead of model prose",
    "model-output instability",
    "model output instability",
    "primary=failed",
    "fallback=failed",
    "catalog_fallback=failed",
)

CHANGED_FILE_EVIDENCE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z0-9_.-]+/){1,64}(?:[A-Za-z0-9_.@+-]+\."
    r"(?:py|js|jsx|ts|tsx|mjs|cjs|sh|bash|yml|yaml|json|jsonc|toml|lock|md|txt|css|scss|html|sql|go|rs|java|kt|swift|rb|php|cs|xml|ini|cfg)"
    r"|Dockerfile|Makefile|README|LICENSE|AGENTS\.md)(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])[A-Za-z0-9_.-]+\."
    r"(?:py|js|jsx|ts|tsx|mjs|cjs|sh|bash|yml|yaml|json|jsonc|toml|lock|md|txt|css|scss|html|sql|go|rs|java|kt|swift|rb|php|cs|xml|ini|cfg)"
    r"(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])(?:Dockerfile|Makefile|README|LICENSE|AGENTS\.md)(?![A-Za-z0-9_])"
)

APPROVAL_VERIFICATION_LABELS = (
    "approval sufficiency:",
    "verification posture:",
    "linter/static:",
    "tdd/regression:",
    "coverage:",
    "docstring coverage:",
    "dag:",
    "poc/execution:",
    "ddd/domain:",
    "cdd/context:",
    "similar issues:",
    "claim/concept check:",
    "standards search:",
    "compatibility/convention:",
    "breaking-change/backcompat:",
    "performance:",
    "developer experience:",
    "user experience:",
    "visual/dom:",
    "accessibility/i18n:",
    "supply-chain/license:",
    "packaging:",
    "security/privacy:",
)

APPROVAL_VERIFICATION_PATTERNS = {
    label: re.compile(re.escape(label)) for label in APPROVAL_VERIFICATION_LABELS
}

SOURCE_LIKE_CHANGED_FILE_EXTENSIONS = frozenset(
    {
        ".bash",
        ".cjs",
        ".cfg",
        ".cs",
        ".css",
        ".go",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsonc",
        ".jsx",
        ".kt",
        ".mjs",
        ".php",
        ".py",
        ".rb",
        ".rs",
        ".scss",
        ".sh",
        ".sql",
        ".swift",
        ".toml",
        ".ts",
        ".tsx",
        ".xml",
        ".yaml",
        ".yml",
    }
)

SOURCE_KIND_FALSE_PHRASES = (
    "no source file changed",
    "no source files changed",
    "no source code changed",
    "no source changes",
    "no supported source files",
    "no supported changed source files",
    "no supported changed source files or package manifests",
    "no source files or package manifests",
)

TEST_KIND_FALSE_PHRASES = (
    "no test file changed",
    "no test files changed",
    "no tests changed",
    "no test changes",
)

EXECUTABLE_KIND_FALSE_PHRASES = (
    "no executable changes",
    "no executable file changed",
    "no executable files changed",
)

MATERIAL_CHANGE_FALSE_PHRASES = (
    "change in a string is safe",
    "docs-only typo",
    "documentation-only typo",
    "documentation string typo",
    "just a string change",
    "no tests are needed",
    "no tests needed",
    "no verification is needed",
    "no verification needed",
    "only a string change",
    "safe string change",
    "simple typo fix",
    "string typo fix",
    "string with no functional impact",
    "string-only change",
    "typo fix in documentation string",
    "typo-only change",
    "typo fix with no functional impact",
)

COVERAGE_FAILURE_PHRASES = (
    "not measured",
    "unmeasured",
    "partial",
    "not proven",
    "n/a",
    "skipped",
    "unavailable",
    "missing",
    "unknown",
    "did not prove",
    "does not prove",
    "did not run",
    "did not publish",
    "job did not run",
    "job did not publish",
)

EVIDENCE_REPAIR_ENV_VARS = (
    "OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE",
    "OPENCODE_EVIDENCE_FILE",
)

HANGUL_RE = re.compile(r"[가-힣]")
PREFERRED_REVIEW_LANGUAGE_RE = re.compile(
    r"Preferred review language:\s*`?([A-Za-z]+)`?", re.IGNORECASE
)


def admits_missing_structural_review(reason: str, summary: str) -> bool:
    """Return whether an approval admits it did not inspect required structure."""
    combined = f"{reason}\n{summary}".casefold()
    return any(phrase in combined for phrase in STRUCTURAL_FAILURE_PHRASES) or any(
        pattern.search(combined) for pattern in STRUCTURAL_FAILURE_PATTERNS
    )


def control_review_text(value: dict[str, Any]) -> str:
    """Return human review text from a control block for policy validation."""
    chunks = [str(value.get("reason", "")), str(value.get("summary", ""))]
    for finding in value.get("findings", []) or []:
        if not isinstance(finding, dict):
            continue
        chunks.extend(str(finding.get(field, "")) for field in (
            "path",
            "line",
            "severity",
            "title",
            "problem",
            "root_cause",
            "fix_direction",
            "regression_test_direction",
            "suggested_diff",
        ))
    return "\n".join(chunks)


def preferred_review_language() -> str | None:
    """Return the bounded-evidence review language contract, when present."""
    evidence_file = approval_repair_evidence_file()
    if evidence_file is None:
        return None
    evidence_text = read_text_lossy(evidence_file)
    if evidence_text is None:
        return None
    section = section_between_markers(evidence_text, "Review language evidence")
    match = PREFERRED_REVIEW_LANGUAGE_RE.search(section)
    if not match:
        return None
    language = match.group(1).strip().casefold()
    if language in {"korean", "english"}:
        return language
    return None


def violates_review_language_contract(value: dict[str, Any]) -> bool:
    """Return whether review prose ignores the preferred PR language."""
    language = preferred_review_language()
    if language != "korean":
        return False
    return not HANGUL_RE.search(control_review_text(value))


def contains_non_actionable_failed_check_review(value: dict[str, Any]) -> bool:
    """Return whether a review punts failed-check diagnosis back to the reader."""
    return bool(non_actionable_failed_check_review_phrase(value))


def non_actionable_failed_check_review_phrase(value: dict[str, Any]) -> str:
    """Return the failed-check deflection phrase found in the review, if any."""
    combined = control_review_text(value).casefold()
    return next((phrase for phrase in NON_ACTIONABLE_FAILED_CHECK_REVIEW_PHRASES if phrase in combined), "")


def model_failure_approval_phrase(reason: str, summary: str) -> str:
    """Return the model-failure approval phrase found in approval prose, if any."""
    combined = f"{reason}\n{summary}".casefold()
    return next((phrase for phrase in MODEL_FAILURE_APPROVAL_PHRASES if phrase in combined), "")


def mentions_changed_file_evidence(reason: str, summary: str) -> bool:
    """Return whether an approval names at least one concrete changed file/path."""
    return bool(CHANGED_FILE_EVIDENCE_PATTERN.search(f"{reason}\n{summary}"))


def current_changed_files() -> set[str]:
    """Return the exact current-head changed files when the workflow provides them."""
    changed_files_path = os.environ.get("OPENCODE_CHANGED_FILES_FILE")
    if not changed_files_path:
        return set()
    try:
        return {
            line.strip()
            for line in Path(changed_files_path)
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        }
    except OSError:
        return set()


def changed_file_is_source_like(path: str) -> bool:
    """Return whether a changed path can affect executable or workflow behavior."""
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    if normalized.startswith(".github/workflows/"):
        return True
    if name in {"Dockerfile", "Makefile"}:
        return True
    return Path(name).suffix.casefold() in SOURCE_LIKE_CHANGED_FILE_EXTENSIONS


def changed_file_is_test_like(path: str) -> bool:
    """Return whether a changed path is part of a test surface."""
    normalized = path.replace("\\", "/").casefold()
    name = normalized.rsplit("/", 1)[-1]
    parts = normalized.split("/")
    return (
        any(part in {"test", "tests", "__tests__"} for part in parts)
        or name.startswith("test_")
        or name.startswith("test-")
        or "_test." in name
        or "-test." in name
        or ".test." in name
        or ".spec." in name
    )


def changed_file_is_material(path: str) -> bool:
    """Return whether a changed path is too risky for trivial-string approval claims."""
    return changed_file_is_source_like(path) or changed_file_is_test_like(path)


def contradicts_changed_file_kinds(reason: str, summary: str) -> bool:
    """Return whether approval prose denies changed file kinds that evidence lists."""
    changed_files = current_changed_files()
    if not changed_files:
        return False

    combined = f"{reason}\n{summary}".casefold()
    combined_for_kind_claims = combined.replace(
        "no supported changed source files or package manifests",
        "",
    ).replace(
        "no supported source files or package manifests",
        "",
    )
    has_source_like_change = any(changed_file_is_source_like(path) for path in changed_files)
    has_test_like_change = any(changed_file_is_test_like(path) for path in changed_files)
    if has_source_like_change and any(phrase in combined_for_kind_claims for phrase in SOURCE_KIND_FALSE_PHRASES):
        return True
    if has_source_like_change and any(phrase in combined_for_kind_claims for phrase in EXECUTABLE_KIND_FALSE_PHRASES):
        return True
    if has_test_like_change and any(phrase in combined for phrase in TEST_KIND_FALSE_PHRASES):
        return True
    return False


def contradicts_material_changed_file_scope(reason: str, summary: str) -> bool:
    """Return whether approval prose trivializes material current-head changes."""
    changed_files = current_changed_files()
    if not changed_files:
        return False
    if not any(changed_file_is_material(path) for path in changed_files):
        return False

    combined = f"{reason}\n{summary}".casefold()
    return any(phrase in combined for phrase in MATERIAL_CHANGE_FALSE_PHRASES)


def mentions_actual_changed_file(reason: str, summary: str) -> bool:
    """Return whether an approval names an exact current-head changed file."""
    changed_files = current_changed_files()
    if not changed_files:
        return mentions_changed_file_evidence(reason, summary)
    combined = f"{reason}\n{summary}"
    return any(changed_file in combined for changed_file in changed_files)


def mentions_verification_posture(reason: str, summary: str) -> bool:
    """Return whether an approval records the concrete review surfaces checked."""
    combined = f"{reason}\n{summary}".casefold()
    return (
        all(label in combined for label in APPROVAL_VERIFICATION_LABELS)
        and "codegraph" in combined
    )


def label_section(text: str, label: str) -> str:
    """Return text after a verification label until the next known label."""

    def label_starts(candidate: str) -> list[int]:
        """Return exact verification-label starts without suffix collisions."""
        starts = []
        pattern = APPROVAL_VERIFICATION_PATTERNS.get(candidate)
        if pattern is None:
            pattern = re.compile(re.escape(candidate))
        for match in pattern.finditer(text):
            index = match.start()
            if (
                candidate == "coverage:"
                and text[max(0, index - 10) : index] == "docstring "
            ):
                continue
            starts.append(index)
        return starts

    starts = label_starts(label)
    if not starts:
        return ""
    start = starts[-1] + len(label)
    next_starts = [
        candidate_start
        for candidate in APPROVAL_VERIFICATION_LABELS
        if candidate != label
        for candidate_start in label_starts(candidate)
        if candidate_start >= start
    ]
    end = min(next_starts) if next_starts else len(text)
    return text[start:end]


def coverage_section_is_valid(section: str) -> bool:
    """Return whether one approval coverage label cites acceptable evidence."""
    if "coverage execution evidence" not in section:
        return False
    if (
        "not applicable" in section
        and (
            "no supported source files or package manifests" in section
            or "no supported changed source files or package manifests" in section
        )
    ):
        return True
    if any(phrase in section for phrase in COVERAGE_FAILURE_PHRASES):
        return False
    if "supported repository test suites passed" in section:
        return True
    if "configured repository docstring gates passed" in section:
        return True
    if "docstring coverage was advisory" in section:
        return True
    if "100%" in section:
        return True
    return False


def mentions_full_coverage(reason: str, summary: str) -> bool:
    """Return whether test and docstring coverage labels cite valid evidence."""
    combined = f"{reason}\n{summary}".casefold()
    coverage_section = label_section(combined, "coverage:")
    docstring_section = label_section(combined, "docstring coverage:")
    required_sections = (coverage_section, docstring_section)
    if not all(required_sections):
        return False
    return all(coverage_section_is_valid(section) for section in required_sections)


def approval_repair_evidence_file() -> Path | None:
    """Return the bounded evidence file used for approval-summary repair."""
    for env_name in EVIDENCE_REPAIR_ENV_VARS:
        value = os.environ.get(env_name, "").strip()
        if not value:
            continue
        path = Path(value)
        if path.is_file():
            return path
    return None


def read_text_lossy(path: Path) -> str | None:
    """Read text while preserving progress across invalid UTF-8 bytes."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def section_between_markers(text: str, marker: str) -> str:
    """Return a markdown section body from a bounded evidence file."""
    marker_line = f"## {marker}"
    start = text.find(marker_line)
    if start == -1:
        return ""
    start += len(marker_line)
    next_section = text.find("\n## ", start)
    if next_section == -1:
        return text[start:]
    return text[start:next_section]


def changed_files_from_evidence(text: str) -> list[str]:
    """Return changed file paths listed in bounded PR evidence."""
    section = section_between_markers(text, "Changed files")
    files: list[str] = []
    seen: set[str] = set()
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^[-*+]\s+", "", line)
        parts = line.split("\t")
        path = parts[-1].strip()
        if not path or path.startswith("["):
            continue
        if not CHANGED_FILE_EVIDENCE_PATTERN.fullmatch(path):
            continue
        if path in seen:
            continue
        files.append(path)
        seen.add(path)
    return files


def evidence_coverage_mode(text: str) -> str | None:
    """Return the coverage mode proven by bounded evidence."""
    section = text.casefold()
    if "- result: pass" not in section:
        return None
    if "- test coverage: 100%" in section and "- docstring coverage: 100%" in section:
        return "full"
    if (
        "- test evidence: supported repository test suites passed" in section
        and "- docstring evidence: configured repository docstring gates passed or docstring coverage was advisory" in section
    ):
        return "suite_passed"
    no_source = (
        "no supported source files or package manifests" in section
        or "no supported changed source files or package manifests" in section
    )
    test_na = "- test coverage: not applicable" in section
    docstring_na = "- docstring coverage: not applicable" in section
    if no_source and test_na and docstring_na:
        return "not_applicable"
    return None


def build_approval_repair_summary(summary: str, evidence_text: str) -> str | None:
    """Append missing approval labels from bounded current-head evidence."""
    changed_files = changed_files_from_evidence(evidence_text)
    coverage_mode = evidence_coverage_mode(evidence_text)
    if not changed_files or coverage_mode is None:
        return None

    first_file = changed_files[0]
    file_list = ", ".join(changed_files[:5])
    if len(changed_files) > 5:
        file_list += f", and {len(changed_files) - 5} more"
    if coverage_mode == "not_applicable":
        coverage_line = (
            "Coverage: coverage execution evidence reports test coverage as not applicable "
            "because no supported changed source files or package manifests were found."
        )
        docstring_line = (
            "Docstring coverage: coverage execution evidence reports docstring coverage as not applicable "
            "because no supported changed source files or package manifests were found."
        )
    elif coverage_mode == "suite_passed":
        coverage_line = "Coverage: coverage execution evidence reports supported repository test suites passed."
        docstring_line = (
            "Docstring coverage: coverage execution evidence reports configured repository docstring gates passed "
            "or docstring coverage was advisory."
        )
    else:
        coverage_line = "Coverage: coverage execution evidence proves 100% test coverage for the current head."
        docstring_line = "Docstring coverage: coverage execution evidence proves 100% docstring coverage for the current head."

    language_line = ""
    if preferred_review_language() == "korean":
        language_line = (
            "Review language: 한국어 리뷰 언어 계약을 확인했고, 이 보강 요약은 "
            "현재 head의 bounded evidence에 근거합니다.\n"
        )

    repair = f"""\

Approval sufficiency: bounded evidence supplied affirmative approval evidence for changed files, coverage/docstring posture, risk surfaces, and current-head verification; approval is not based merely on the absence of known blockers.
{language_line}\
Verification posture: CodeGraph evidence was initialized and bounded current-head evidence reviewed for changed-file evidence including {file_list}.
Linter/static: workflow/static review evidence is bounded by the current-head GitHub Checks gate and changed-file evidence.
TDD/regression: coverage execution evidence and focused changed hunks were reviewed from bounded-review-evidence.md.
{coverage_line}
{docstring_line}
DAG: CodeGraph/source-backed behavior map connects {first_file} to the affected review, runtime, or workflow path and required checks.
PoC/execution: coverage-evidence job executed on the current head and reported PASS.
DDD/domain: workflow and repository-governance invariants were reviewed against changed files in bounded evidence.
CDD/context: CodeGraph evidence, changed-file history, and focused hunks were reviewed from bounded-review-evidence.md.
Similar issues: changed-file history evidence was reviewed for comparable local precedents.
Claim/concept check: bounded evidence, repository source, current-head workflow evidence, and, where numeric, scientific, statistical, or literature-backed claims are affected, original-paper/formula evidence and parameter-recovery expectations were used for claims.
Standards search: standards and external-source checks are delegated to configured OpenCode web_search/Context7/DeepWiki sources when applicable; no evidence-backed standards blocker is present in bounded evidence.
Compatibility/convention: changed workflow/script conventions, object naming, and reserved-word safety for schema/API/config/code surfaces were checked in bounded evidence.
Breaking-change/backcompat: deployment evidence and changed-file history were checked for backward-compatibility risk.
Performance: changed surfaces were checked for performance risk in bounded evidence.
Developer experience: changed automation, review, test, setup, and maintenance surfaces were checked for helpful or obstructive DX impact in bounded evidence.
User experience: connected user, operator, API, CLI, documentation, review-comment, status-check, rendering, and workflow-reader behavior was checked for contradictions against code, docs, and tests in bounded evidence.
Visual/DOM: Playwright visual, DOM locator, ARIA snapshot, console, and responsive evidence were checked when a web UI surface was present; for non-web surfaces, API/CLI/log/docs/workflow interaction evidence was reviewed instead.
Accessibility/i18n: accessibility, localization, and human-readable text surfaces were checked where UI, CLI, API message, docs, logs, or review text changed.
Supply-chain/license: dependency, package, model, container, and external-tool changes were checked in bounded evidence.
Packaging: package, build, test, lint, and security contracts were checked in bounded evidence.
Security/privacy: workflow-token, review-gate, and repository-automation security/privacy boundaries were checked in bounded evidence.
"""
    return f"{summary.rstrip()}\n{repair}"


def repair_approval_summary(reason: str, summary: str) -> str:
    """Repair an APPROVE summary only from objective bounded evidence."""
    evidence_file = approval_repair_evidence_file()
    if evidence_file is not None:
        evidence_text = read_text_lossy(evidence_file)
        if evidence_text is not None:
            repaired_summary = build_approval_repair_summary("", evidence_text)
            if repaired_summary:
                return repaired_summary

    if (
        mentions_changed_file_evidence(reason, summary)
        and mentions_verification_posture(reason, summary)
        and mentions_full_coverage(reason, summary)
    ):
        return summary
    return summary


def repair_approval_reason(reason: str, summary: str) -> str:
    """Replace fragile APPROVE reasons after bounded evidence repaired the summary."""
    evidence_file = approval_repair_evidence_file()
    if evidence_file is None:
        return reason

    if not (
        mentions_actual_changed_file(reason, summary)
        and mentions_verification_posture(reason, summary)
        and mentions_full_coverage(reason, summary)
    ):
        return reason

    reason_lower = reason.casefold()
    if (
        contradicts_changed_file_kinds(reason, summary)
        or contradicts_material_changed_file_scope(reason, summary)
        or admits_missing_structural_review(reason, summary)
        or model_failure_approval_phrase(reason, summary)
        or "no source changes" in reason_lower
        or "no verification needed" in reason_lower
        or "no execution required" in reason_lower
    ):
        evidence_text = read_text_lossy(evidence_file)
        changed_files = changed_files_from_evidence(evidence_text or "")
        file_hint = changed_files[0] if changed_files else "the current changed files"
        return (
            "Bounded current-head evidence repaired the model APPROVE conclusion "
            f"and verified changed-file evidence for {file_hint}."
        )
    return reason


def check_structural_approval(control_file: Path) -> int:
    """Validate an already-normalized control block before publishing approval."""
    def reject(reason: str) -> int:
        """Reject approval with a stable no-conclusion reason."""
        print(f"NO_CONCLUSION: {reason}", file=sys.stderr)
        return 4

    try:
        value = json.loads(control_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read OpenCode control JSON: {exc}", file=sys.stderr)
        return 65

    if not isinstance(value, dict):
        return reject("control JSON is not an object")

    if value.get("result") == "APPROVE" and admits_missing_structural_review(
        str(value.get("reason", "")),
        str(value.get("summary", "")),
    ):
        return reject("approval admits missing structural review")
    if value.get("result") == "APPROVE" and not mentions_actual_changed_file(
        str(value.get("reason", "")),
        str(value.get("summary", "")),
    ):
        return reject("approval does not cite changed-file evidence")
    if value.get("result") == "APPROVE" and not mentions_verification_posture(
        str(value.get("reason", "")),
        str(value.get("summary", "")),
    ):
        return reject("approval does not include the required verification posture")
    if value.get("result") == "APPROVE" and not mentions_full_coverage(
        str(value.get("reason", "")),
        str(value.get("summary", "")),
    ):
        return reject("approval does not prove 100% coverage or an explicit no-source exception")
    if value.get("result") == "APPROVE" and contradicts_changed_file_kinds(
        str(value.get("reason", "")),
        str(value.get("summary", "")),
    ):
        return reject("approval contradicts changed file kinds")
    if value.get("result") == "APPROVE" and contradicts_material_changed_file_scope(
        str(value.get("reason", "")),
        str(value.get("summary", "")),
    ):
        return reject("approval trivializes material changed files")
    if value.get("result") == "APPROVE":
        phrase = model_failure_approval_phrase(
            str(value.get("reason", "")),
            str(value.get("summary", "")),
        )
        if phrase:
            return reject(f"approval depends on failed model output: {phrase}")
    # Generic failed-check deflections are invalid for both approvals and request-changes.
    phrase = non_actionable_failed_check_review_phrase(value)
    if phrase:
        return reject(f"non-actionable failed-check deflection: {phrase}")
    if violates_review_language_contract(value):
        return reject("review prose does not follow the preferred PR language")

    return 0


def valid_control(
    value: Any,
    *,
    expected_head_sha: str,
    expected_run_id: str,
    expected_run_attempt: str,
) -> dict[str, Any] | None:
    """Return a normalized control block when it matches the current run."""
    if not isinstance(value, dict):
        return None

    if value.get("head_sha") != expected_head_sha:
        return None
    if value.get("run_id") != expected_run_id:
        return None
    if value.get("run_attempt") != expected_run_attempt:
        return None

    result = value.get("result")
    if result not in {"APPROVE", "REQUEST_CHANGES"}:
        return None

    if not isinstance(value.get("reason"), str) or not value["reason"].strip():
        return None
    if not isinstance(value.get("summary"), str) or not value["summary"].strip():
        return None
    reason = value["reason"].strip()
    summary = value["summary"].strip()

    findings = value.get("findings")
    if findings is None and result == "APPROVE":
        findings = []
    if not isinstance(findings, list):
        return None
    if result == "APPROVE" and findings:
        return None
    if result == "REQUEST_CHANGES" and not findings:
        return None
    if contains_non_actionable_failed_check_review(value):
        return None
    if result != "APPROVE" and violates_review_language_contract(value):
        return None
    if result == "APPROVE":
        if admits_missing_structural_review(reason, summary):
            return None
        summary = repair_approval_summary(reason, summary)
        reason = repair_approval_reason(reason, summary)
        value = {**value, "reason": reason, "summary": summary}
        if violates_review_language_contract(value):
            return None
        if not mentions_actual_changed_file(reason, summary):
            return None
        if not mentions_verification_posture(reason, summary):
            return None
        if not mentions_full_coverage(reason, summary):
            return None
        if contradicts_changed_file_kinds(reason, summary):
            return None
        if contradicts_material_changed_file_scope(reason, summary):
            return None
        if model_failure_approval_phrase(reason, summary):
            return None

    required_finding_fields = (
        "path",
        "severity",
        "title",
        "problem",
        "root_cause",
        "fix_direction",
        "regression_test_direction",
        "suggested_diff",
    )
    for finding in findings:
        if not isinstance(finding, dict):
            return None
        line = finding.get("line")
        if isinstance(line, bool) or not isinstance(line, int) or line <= 0:
            return None
        for field in required_finding_fields:
            if not isinstance(finding.get(field), str) or not finding[field].strip():
                return None

    return {
        "head_sha": value["head_sha"],
        "run_id": value["run_id"],
        "run_attempt": value["run_attempt"],
        "result": result,
        "reason": reason,
        "summary": summary,
        "findings": findings,
    }


def extract_dicts(obj: Any) -> list[Any]:
    """Recursively extract all dictionaries from a JSON-like object."""
    results = []
    if isinstance(obj, dict):
        results.append(obj)
        for v in obj.values():
            results.extend(extract_dicts(v))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(extract_dicts(item))
    return results


def iter_json_objects(text: str) -> list[Any]:
    """Extract JSON objects from raw OpenCode output that may include prose."""
    decoder = json.JSONDecoder()
    values: list[Any] = []

    try:
        # Fast path for pure JSON payloads; avoid scanning and duplicate decodes.
        return extract_dicts(json.loads(text))
    except json.JSONDecodeError:
        # OpenCode exports may contain prose around the JSON control object.
        pass

    index = 0
    while True:
        index = text.find("{", index)
        if index == -1:
            break
        next_index = index + 1
        while next_index < len(text) and text[next_index] in " \t\r\n":
            next_index += 1
        if next_index < len(text) and text[next_index] not in {'"', "}"}:
            index += 1
            continue
        try:
            value, new_index = decoder.raw_decode(text, index)
            values.extend(extract_dicts(value))
            # ⚡ Bolt: Advance index to avoid O(N^2) redundant parsing of nested JSON blocks
            index = new_index
            continue
        except json.JSONDecodeError:
            pass
        index += 1

    return values


def main(argv: list[str]) -> int:
    """Run the normalizer CLI and write the publishable control block."""
    if len(argv) == 3 and argv[1] == "--check-structural-approval":
        return check_structural_approval(Path(argv[2]))

    if len(argv) != 5:
        print(
            "usage: opencode_review_normalize_output.py "
            "<expected_head_sha> <expected_run_id> <expected_run_attempt> <output_file>\n"
            "   or: opencode_review_normalize_output.py --check-structural-approval <control_json_file>",
            file=sys.stderr,
        )
        return 64

    expected_head_sha, expected_run_id, expected_run_attempt, output_file_arg = argv[1:]
    output_file = Path(output_file_arg)
    try:
        output_text = output_file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"cannot read OpenCode output file: {exc}", file=sys.stderr)
        return 65

    for value in iter_json_objects(output_text):
        control = valid_control(
            value,
            expected_head_sha=expected_head_sha,
            expected_run_id=expected_run_id,
            expected_run_attempt=expected_run_attempt,
        )
        if control is None:
            continue

        normalized_json = json.dumps(control, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        output_file.write_text(
            "\n".join(
                [
                    (
                        "<!-- opencode-review-gate "
                        f"head_sha={expected_head_sha} "
                        f"run_id={expected_run_id} "
                        f"run_attempt={expected_run_attempt} -->"
                    ),
                    "",
                    "<!-- opencode-review-control-v1",
                    normalized_json,
                    "-->",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return 0

    print("NO_CONCLUSION", file=sys.stderr)
    return 4


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
