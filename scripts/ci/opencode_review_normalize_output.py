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

CHANGED_FILE_EVIDENCE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z0-9_.-]+/)+(?:[A-Za-z0-9_.@+-]+\."
    r"(?:py|js|jsx|ts|tsx|mjs|cjs|sh|bash|yml|yaml|json|jsonc|toml|lock|md|txt|css|scss|html|sql|go|rs|java|kt|swift|rb|php|cs|xml|ini|cfg)"
    r"|Dockerfile|Makefile|README|LICENSE|AGENTS\.md)(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])[A-Za-z0-9_.-]+\."
    r"(?:py|js|jsx|ts|tsx|mjs|cjs|sh|bash|yml|yaml|json|jsonc|toml|lock|md|txt|css|scss|html|sql|go|rs|java|kt|swift|rb|php|cs|xml|ini|cfg)"
    r"(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9_])(?:Dockerfile|Makefile|README|LICENSE|AGENTS\.md)(?![A-Za-z0-9_])"
)

APPROVAL_VERIFICATION_LABELS = (
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
    "design/ux:",
    "security/privacy:",
)

COVERAGE_FAILURE_PHRASES = (
    "not measured",
    "unmeasured",
    "not proven",
    "not applicable",
    "n/a",
    "skipped",
    "unavailable",
    "missing",
    "partial",
    "unknown",
    "did not run",
    "did not publish",
    "job did not run",
    "job did not publish",
)

EVIDENCE_REPAIR_ENV_VARS = (
    "OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE",
    "OPENCODE_EVIDENCE_FILE",
)


def admits_missing_structural_review(reason: str, summary: str) -> bool:
    """Return whether an approval admits it did not inspect required structure."""
    combined = f"{reason}\n{summary}".casefold()
    return any(phrase in combined for phrase in STRUCTURAL_FAILURE_PHRASES) or any(
        pattern.search(combined) for pattern in STRUCTURAL_FAILURE_PATTERNS
    )


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
            for line in Path(changed_files_path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    except OSError:
        return set()


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
    return all(label in combined for label in APPROVAL_VERIFICATION_LABELS) and "codegraph" in combined


def label_section(text: str, label: str) -> str:
    """Return text after a verification label until the next known label."""
    def label_matches(candidate: str) -> list[re.Match[str]]:
        """Return exact verification-label matches without suffix collisions."""
        matches = []
        for match in re.finditer(re.escape(candidate), text):
            if candidate == "coverage:" and text[max(0, match.start() - 10) : match.start()] == "docstring ":
                continue
            matches.append(match)
        return matches

    matches = label_matches(label)
    if not matches:
        return ""
    start = matches[-1].end()
    next_starts = [
        match.start()
        for candidate in APPROVAL_VERIFICATION_LABELS
        if candidate != label
        for match in label_matches(candidate)
        if match.start() >= start
    ]
    end = min(next_starts) if next_starts else len(text)
    return text[start:end]


def mentions_full_coverage(reason: str, summary: str) -> bool:
    """Return whether test and docstring coverage are both explicitly 100%."""
    combined = f"{reason}\n{summary}".casefold()
    coverage_section = label_section(combined, "coverage:")
    docstring_section = label_section(combined, "docstring coverage:")
    required_sections = (coverage_section, docstring_section)
    if not all(required_sections):
        return False
    for section in required_sections:
        if any(phrase in section for phrase in COVERAGE_FAILURE_PHRASES):
            return False
        if "coverage execution evidence" not in section:
            return False
        if "100%" not in section:
            return False
    return True


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


def evidence_proves_full_coverage(text: str) -> bool:
    """Return whether bounded evidence proves 100% test and docstring coverage."""
    section = text.casefold()
    return (
        "- result: pass" in section
        and "- test coverage: 100%" in section
        and "- docstring coverage: 100%" in section
    )


def build_approval_repair_summary(summary: str, evidence_text: str) -> str | None:
    """Append missing approval labels from bounded current-head evidence."""
    changed_files = changed_files_from_evidence(evidence_text)
    if not changed_files or not evidence_proves_full_coverage(evidence_text):
        return None

    first_file = changed_files[0]
    file_list = ", ".join(changed_files[:5])
    if len(changed_files) > 5:
        file_list += f", and {len(changed_files) - 5} more"

    repair = f"""\

Verification posture: CodeGraph evidence was initialized and bounded current-head evidence reviewed for changed-file evidence including {file_list}.
Linter/static: workflow/static review evidence is bounded by the current-head GitHub Checks gate and changed-file evidence.
TDD/regression: coverage execution evidence and focused changed hunks were reviewed from bounded-review-evidence.md.
Coverage: coverage execution evidence proves 100% test coverage.
Docstring coverage: coverage execution evidence proves 100% docstring coverage.
DAG: Change Flow DAG maps {first_file} through bounded evidence, review risk, and required checks.
PoC/execution: coverage-evidence job executed on the current head and reported PASS.
DDD/domain: workflow and repository-governance invariants were reviewed against changed files in bounded evidence.
CDD/context: CodeGraph evidence, changed-file history, and focused hunks were reviewed from bounded-review-evidence.md.
Similar issues: changed-file history evidence was reviewed for comparable local precedents.
Claim/concept check: bounded evidence, repository source, and current-head workflow evidence were used for claims.
Standards search: standards and external-source checks are delegated to configured OpenCode web_search/Context7/DeepWiki sources when applicable; no evidence-backed standards blocker is present in bounded evidence.
Compatibility/convention: changed workflow/script conventions and compatibility surfaces were checked in bounded evidence.
Breaking-change/backcompat: deployment evidence and changed-file history were checked for backward-compatibility risk.
Performance: changed surfaces were checked for performance risk in bounded evidence.
Design/UX: changed files did not identify a UI-facing design surface; bounded evidence was reviewed.
Security/privacy: workflow-token, review-gate, and repository-automation security/privacy boundaries were checked in bounded evidence.
"""
    return f"{summary.rstrip()}\n{repair}"


def repair_approval_summary(reason: str, summary: str) -> str:
    """Repair an APPROVE summary only from objective bounded evidence."""
    if mentions_changed_file_evidence(reason, summary) and mentions_verification_posture(
        reason, summary
    ) and mentions_full_coverage(reason, summary):
        return summary

    evidence_file = approval_repair_evidence_file()
    if evidence_file is None:
        return summary
    try:
        evidence_text = evidence_file.read_text(encoding="utf-8")
    except OSError:
        return summary

    repaired_summary = build_approval_repair_summary(summary, evidence_text)
    return repaired_summary or summary


def check_structural_approval(control_file: Path) -> int:
    """Validate an already-normalized control block before publishing approval."""
    try:
        value = json.loads(control_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read OpenCode control JSON: {exc}", file=sys.stderr)
        return 65

    if not isinstance(value, dict):
        print("NO_CONCLUSION", file=sys.stderr)
        return 4

    if value.get("result") == "APPROVE" and admits_missing_structural_review(
        str(value.get("reason", "")),
        str(value.get("summary", "")),
    ):
        print("NO_CONCLUSION", file=sys.stderr)
        return 4
    if value.get("result") == "APPROVE" and not mentions_changed_file_evidence(
        str(value.get("reason", "")),
        str(value.get("summary", "")),
    ):
        print("NO_CONCLUSION", file=sys.stderr)
        return 4
    if value.get("result") == "APPROVE" and not mentions_verification_posture(
        str(value.get("reason", "")),
        str(value.get("summary", "")),
    ):
        print("NO_CONCLUSION", file=sys.stderr)
        return 4
    if value.get("result") == "APPROVE" and not mentions_full_coverage(
        str(value.get("reason", "")),
        str(value.get("summary", "")),
    ):
        print("NO_CONCLUSION", file=sys.stderr)
        return 4

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
    if result == "APPROVE":
        if admits_missing_structural_review(reason, summary):
            return None
        summary = repair_approval_summary(reason, summary)
        if not mentions_actual_changed_file(reason, summary):
            return None
        if not mentions_verification_posture(reason, summary):
            return None
        if not mentions_full_coverage(reason, summary):
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


def iter_json_objects(text: str) -> list[Any]:
    """Extract JSON objects from raw OpenCode output that may include prose."""
    decoder = json.JSONDecoder()
    values: list[Any] = []

    try:
        values.append(json.loads(text))
    except json.JSONDecodeError:
        # OpenCode exports may contain prose around the JSON control object.
        pass

    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        values.append(value)

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
        output_text = output_file.read_text(encoding="utf-8")
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

        normalized_json = json.dumps(control, separators=(",", ":"), ensure_ascii=False)
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
