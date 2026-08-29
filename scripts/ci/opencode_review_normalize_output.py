#!/usr/bin/env python3
"""Normalize OpenCode review output into the strict approval-gate contract."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
from functools import lru_cache
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

try:
    from adversarial_evidence import (
        SOURCE_LINE_RECEIPT_RE,
        adversarial_evidence_rejection_reason,
    )
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts.ci.adversarial_evidence import (
        SOURCE_LINE_RECEIPT_RE,
        adversarial_evidence_rejection_reason,
    )

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
BULLET_PREFIX_PATTERN = re.compile(r"^[-*+]\s+")

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

TRUSTED_ARTIFACT_NAMES = {
    "OPENCODE_CHANGED_FILES_FILE": "opencode-changed-files.txt",
    "OPENCODE_EVIDENCE_FILE": "opencode-review-evidence.md",
    "OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE": "opencode-review-evidence.md",
    "OPENCODE_EXECUTION_RECEIPTS_FILE": "opencode-execution-receipts.txt",
}
TRUSTED_ARTIFACT_MANIFEST = "opencode-artifact-manifest.json"

HANGUL_RE = re.compile(r"[가-힣]")
PREFERRED_REVIEW_LANGUAGE_RE = re.compile(
    r"Preferred review language:\s*`?([A-Za-z]+)`?", re.IGNORECASE
)
RUNTIME_TOOL_PATTERN = re.compile(
    r"\b(?:react\s+devtools|chrome\s+devtools|browser\s+devtools|"
    r"headless\s+chromium|playwright|cypress|selenium|puppeteer|webdriver|"
    r"chromium|chrome|firefox|safari|browser)\b",
    re.IGNORECASE,
)
RUNTIME_ASSERTION_PATTERN = re.compile(
    r"\b(?:ran|executed|used|observed|verified|confirmed|validated|passed|"
    r"proved|demonstrated|showed|launched|opened|inspected|rendered|exercised|"
    r"tested|checked|navigated|visited|browsed|loaded|displayed|captured|recorded|"
    r"profiled|traced|clicked|typed|submitted|interacted|completed|succeeded|"
    r"worked|generated|produced|took|reproduced|replayed|debugged|runs|executes|"
    r"uses|observes|verifies|confirms|validates|passes|proves|demonstrates|shows|"
    r"launches|opens|inspects|renders|exercises|checks|navigates|visits|browses|"
    r"loads|displays|captures|records|profiles|traces|clicks|types|submits|"
    r"interacts|completes|succeeds|works|generates|produces|takes|reproduces|"
    r"replays|debugs|reports|indicates|(?:did|does|do)\s+(?:run|execute|use|"
    r"observe|verify|confirm|validate|pass|prove|demonstrate|show|launch|open|"
    r"inspect|render|exercise|check|navigate|visit|browse|load|display|capture|"
    r"record|profile|trace|click|type|submit|interact|complete|succeed|work|"
    r"generate|produce|take|reproduce|replay|debug|report|indicate))\b",
    re.IGNORECASE,
)
NEGATED_RUNTIME_ASSERTION_PATTERN = re.compile(
    r"(?:\b(?:did|could|was|were|is|are|has|have)\s+not\b|\bnot\b|\bnever\b|"
    r"\bwithout\b|\b(?:didn't|couldn't|wasn't|weren't|isn't|aren't|"
    r"hasn't|haven't)\b)",
    re.IGNORECASE,
)
EXECUTION_RECEIPT_PATTERN = re.compile(
    r"^OPENCODE_EXECUTION_RECEIPT\s+"
    r"tool=(react-devtools|chrome-devtools|browser-devtools|headless-chromium|"
    r"playwright|cypress|selenium|puppeteer|webdriver|chromium|chrome|firefox|"
    r"safari|browser)\s+"
    r"status=(?:passed|observed)$",
    re.IGNORECASE | re.MULTILINE,
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
    adversarial_validation = value.get("adversarial_validation")
    if isinstance(adversarial_validation, dict):
        chunks.append(
            json.dumps(adversarial_validation, ensure_ascii=False, sort_keys=True)
        )
    for finding in value.get("findings", []) or []:
        if not isinstance(finding, dict):
            continue
        chunks.extend(
            str(finding.get(field, ""))
            for field in (
                "path",
                "line",
                "severity",
                "title",
                "problem",
                "root_cause",
                "fix_direction",
                "regression_test_direction",
                "suggested_diff",
            )
        )
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


def non_actionable_failed_check_review_phrase(value: dict[str, Any]) -> str:
    """Return the failed-check deflection phrase found in the review, if any."""
    combined = control_review_text(value).casefold()
    return next(
        (
            phrase
            for phrase in NON_ACTIONABLE_FAILED_CHECK_REVIEW_PHRASES
            if phrase in combined
        ),
        "",
    )


def model_failure_approval_phrase(reason: str, summary: str) -> str:
    """Return the model-failure approval phrase found in approval prose, if any."""
    combined = f"{reason}\n{summary}".casefold()
    return next(
        (phrase for phrase in MODEL_FAILURE_APPROVAL_PHRASES if phrase in combined), ""
    )


def mentions_changed_file_evidence(reason: str, summary: str) -> bool:
    """Return whether an approval names at least one concrete changed file/path."""
    return bool(CHANGED_FILE_EVIDENCE_PATTERN.search(f"{reason}\n{summary}"))


def trusted_runner_temp() -> Path | None:
    """Return the runner-owned artifact root, rejecting missing or symlink roots."""
    value = os.environ.get("RUNNER_TEMP", "").strip()
    if not value:
        return None
    root = Path(value)
    try:
        if stat.S_ISLNK(root.lstat().st_mode) or not root.is_dir():
            return None
        return root.resolve(strict=True)
    except OSError:
        return None


def safe_runner_artifact(path: Path, expected_name: str) -> Path | None:
    """Return an exact runner-temp regular file with safe ownership and mode."""
    root = trusted_runner_temp()
    if root is None:
        return None
    expected = root / expected_name
    try:
        file_stat = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError:
        return None
    if (
        resolved != expected
        or stat.S_ISLNK(file_stat.st_mode)
        or not stat.S_ISREG(file_stat.st_mode)
    ):
        return None
    if file_stat.st_uid != os.getuid() or file_stat.st_mode & 0o022:
        return None
    return resolved


def trusted_artifact_manifest() -> dict[str, Any] | None:
    """Load the runner manifest only when its trusted-step digest still matches."""
    root = trusted_runner_temp()
    if root is None:
        return None
    manifest_path = safe_runner_artifact(
        root / TRUSTED_ARTIFACT_MANIFEST, TRUSTED_ARTIFACT_MANIFEST
    )
    if manifest_path is None:
        return None
    expected_digest = os.environ.get("OPENCODE_ARTIFACT_MANIFEST_SHA256", "").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        return None
    try:
        manifest_bytes = manifest_path.read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != expected_digest:
            return None
        value = json.loads(manifest_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict) or value.get("schema") != 1:
        return None
    return value


def trusted_artifact_path(env_name: str) -> Path | None:
    """Resolve and digest-check one exact workflow artifact path."""
    expected_name = TRUSTED_ARTIFACT_NAMES[env_name]
    supplied = os.environ.get(env_name, "").strip()
    if not supplied:
        return None
    path = safe_runner_artifact(Path(supplied), expected_name)
    manifest = trusted_artifact_manifest()
    if path is None or manifest is None or path.stat().st_size <= 0:
        return None
    artifacts = manifest.get("artifacts")
    expected_digest = (
        artifacts.get(expected_name) if isinstance(artifacts, dict) else None
    )
    if not isinstance(expected_digest, str) or not expected_digest:
        return None
    actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path if actual_digest == expected_digest else None


def artifact_identity_error(
    expected_head_sha: str,
    expected_run_id: str,
    expected_run_attempt: str,
) -> str:
    """Return why the trusted artifact manifest is not bound to this run."""
    if not all((expected_head_sha, expected_run_id, expected_run_attempt)) or "-" in {
        expected_head_sha,
        expected_run_id,
        expected_run_attempt,
    }:
        return "expected head, run, and attempt identities must be explicit"
    manifest = trusted_artifact_manifest()
    if manifest is None:
        return "runner artifact provenance manifest is missing or unsafe"
    expected = {
        "head_sha": expected_head_sha,
        "run_id": expected_run_id,
        "run_attempt": expected_run_attempt,
    }
    mismatches = [
        field for field, value in expected.items() if manifest.get(field) != value
    ]
    if mismatches:
        return "artifact provenance identity mismatch: " + ", ".join(mismatches)
    return ""


@lru_cache(maxsize=1)
def current_changed_files() -> frozenset[str]:
    """Return the exact current-head changed files when the workflow provides them."""
    changed_files_path = trusted_artifact_path("OPENCODE_CHANGED_FILES_FILE")
    if changed_files_path is None:
        return frozenset()
    return frozenset(
        line.strip()
        for line in changed_files_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def runtime_tool_slug(tool_name: str) -> str:
    """Return the canonical receipt slug for a browser execution tool."""
    return re.sub(r"\s+", "-", tool_name.strip().casefold())


@lru_cache(maxsize=1)
def trusted_execution_receipts() -> frozenset[str]:
    """Return browser tools backed by trusted workflow execution receipts."""
    receipt_path = trusted_artifact_path("OPENCODE_EXECUTION_RECEIPTS_FILE")
    if receipt_path is None:
        return frozenset()
    receipt_text = receipt_path.read_text(encoding="utf-8")
    return frozenset(
        runtime_tool_slug(match.group(1))
        for match in EXECUTION_RECEIPT_PATTERN.finditer(receipt_text)
    )


def runtime_assertion_is_negated(
    text: str,
    assertion: re.Match[str],
    *,
    suffix: str = "",
) -> bool:
    """Return whether a nearby negation applies to this execution assertion."""
    prefix = text[max(0, assertion.start() - 40) : assertion.start()]
    prefix = re.split(r"[,;]|\bbut\b|\bhowever\b", prefix, flags=re.IGNORECASE)[-1]
    return NEGATED_RUNTIME_ASSERTION_PATTERN.search(f"{prefix}{suffix}") is not None


def claimed_runtime_tools(text: str) -> tuple[str, ...]:
    """Return every browser tool asserted as executed, excluding explicit limits."""
    claimed_tools: list[str] = []
    for tool_match in RUNTIME_TOOL_PATTERN.finditer(text):
        before = text[max(0, tool_match.start() - 96) : tool_match.start()]
        after = text[tool_match.end() : tool_match.end() + 96]
        before = re.split(r"[.;\n]", before)[-1]
        after = re.split(r"[.;\n]", after)[0]
        before_matches = list(RUNTIME_ASSERTION_PATTERN.finditer(before))
        if before_matches:
            before_match = before_matches[-1]
            if not runtime_assertion_is_negated(
                before,
                before_match,
                suffix=before[before_match.end() :],
            ):
                claimed_tools.append(runtime_tool_slug(tool_match.group(0)))
                continue
        if any(
            not runtime_assertion_is_negated(after, after_match)
            for after_match in RUNTIME_ASSERTION_PATTERN.finditer(after)
        ):
            claimed_tools.append(runtime_tool_slug(tool_match.group(0)))
    return tuple(dict.fromkeys(claimed_tools))


def claimed_runtime_tool(text: str) -> str:
    """Return the first browser tool asserted as executed, if one exists."""
    return next(iter(claimed_runtime_tools(text)), "")


def unreceipted_runtime_tool_claim(text: str) -> str:
    """Return an asserted browser tool missing a trusted execution receipt."""
    receipts = trusted_execution_receipts()
    for tool_slug in claimed_runtime_tools(text):
        if tool_slug not in receipts:
            return tool_slug
    return ""


def adversarial_validation_required() -> bool:
    """Return whether the central workflow requires structured attack probes."""
    return os.environ.get("OPENCODE_REQUIRE_ADVERSARIAL_VALIDATION", "").casefold() in {
        "1",
        "true",
        "yes",
    }


def required_adversarial_probe_count() -> int:
    """Require two probes for material changes and one for non-code changes."""
    changed_files = current_changed_files()
    if any(changed_file_is_material(path) for path in changed_files):
        return 2
    return 1


def adversarial_probe_location_error(path: str, line: int) -> str:
    """Return why a probe path/line is not present in the bounded source tree."""
    source_root_text = os.environ.get("OPENCODE_SOURCE_WORKDIR", "").strip()
    if not source_root_text:
        return "trusted current-head source root is unavailable"
    try:
        source_root = Path(source_root_text).resolve(strict=True)
        source_path = source_root.joinpath(*PurePosixPath(path).parts).resolve(
            strict=True
        )
    except OSError:
        return "path does not exist in the trusted current-head source tree"
    try:
        source_path.relative_to(source_root)
    except ValueError:
        return "path resolves outside the trusted current-head source tree"
    try:
        source_stat = source_path.stat()
        if not stat.S_ISREG(source_stat.st_mode):
            return "path is not a regular current-head source file"
        if source_stat.st_size > 2 * 1024 * 1024:
            return "source file exceeds the bounded 2 MiB probe limit"
        line_count = len(source_path.read_bytes().splitlines())
    except OSError:
        return "source file could not be read from the trusted current-head tree"
    if line > line_count:
        return f"line {line} exceeds the current-head file length {line_count}"
    return ""


def adversarial_probe_source_line_digest(path: str, line: int) -> str | None:
    """Return the SHA-256 digest of the exact trusted current-head line bytes."""
    source_root_text = os.environ.get("OPENCODE_SOURCE_WORKDIR", "").strip()
    if not source_root_text:
        return None
    try:
        source_root = Path(source_root_text).resolve(strict=True)
        source_path = source_root.joinpath(*PurePosixPath(path).parts).resolve(
            strict=True
        )
        source_path.relative_to(source_root)
        source_lines = source_path.read_bytes().splitlines()
    except (OSError, ValueError):
        return None
    if line > len(source_lines):
        return None
    return hashlib.sha256(source_lines[line - 1]).hexdigest()


def adversarial_probe_source_receipt_error(
    evidence: str,
    path: str,
    line: int,
) -> str:
    """Verify one model receipt against the exact trusted source-line bytes."""
    receipts = SOURCE_LINE_RECEIPT_RE.findall(evidence)
    if len(receipts) != 1:
        return "must contain exactly one source-line-sha256 receipt"
    expected_digest = adversarial_probe_source_line_digest(path, line)
    if expected_digest is None:
        return "source-line receipt could not be verified from the trusted tree"
    if receipts[0].casefold() != expected_digest:
        return "source-line-sha256 receipt does not match the cited current-head line"
    return ""


def repair_adversarial_probe_source_bindings(value: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize only the trusted path and line citation of LLM probes.

    The model remains solely responsible for the hypothesis, counterexample,
    observed proof, outcome, finding, and verdict. Repair runs only when the
    original model evidence already names an independent proof class, an
    observed result, and the exact valid source-line digest from the immutable
    current-head tree. Missing or mismatched digests remain rejected.
    """
    validation = value.get("adversarial_validation")
    if not isinstance(validation, dict):
        return value
    probes = validation.get("probes")
    if not isinstance(probes, list):
        return value

    repaired_probes: list[Any] = []
    changed = False
    for probe in probes:
        if not isinstance(probe, dict):
            repaired_probes.append(probe)
            continue
        path_value = probe.get("path")
        line_value = probe.get("line")
        evidence_value = probe.get("evidence")
        if (
            not isinstance(path_value, str)
            or not path_value.strip()
            or isinstance(line_value, bool)
            or not isinstance(line_value, int)
            or line_value <= 0
            or not isinstance(evidence_value, str)
            or not evidence_value.strip()
        ):
            repaired_probes.append(probe)
            continue

        normalized_path = path_value.strip()
        if ".." in PurePosixPath(normalized_path).parts:
            repaired_probes.append(probe)
            continue
        receipt_error = adversarial_probe_source_receipt_error(
            evidence_value,
            normalized_path,
            line_value,
        )
        if receipt_error:
            repaired_probes.append(probe)
            continue
        digest = SOURCE_LINE_RECEIPT_RE.findall(evidence_value)[0].casefold()

        lexical_evidence = SOURCE_LINE_RECEIPT_RE.sub("", evidence_value).strip()
        receipt_bound_evidence = (
            f"{lexical_evidence} source-line-sha256={digest}"
        ).strip()
        if adversarial_evidence_rejection_reason(receipt_bound_evidence, ""):
            repaired_probes.append(probe)
            continue

        canonical_evidence = (
            f"{lexical_evidence} Trusted current-head source binding at "
            f"{normalized_path}:{line_value}; source-line-sha256={digest}"
        ).strip()
        repaired_probes.append(
            {**probe, "path": normalized_path, "evidence": canonical_evidence}
        )
        changed = True

    if not changed:
        return value
    return {
        **value,
        "adversarial_validation": {**validation, "probes": repaired_probes},
    }


def adversarial_validation_error(
    value: Any,
    *,
    result: str,
    findings: list[Any],
) -> str:
    """Return why structured adversarial evidence is not publishable."""
    if value is None and not adversarial_validation_required():
        return ""
    if not isinstance(value, dict):
        return "adversarial_validation must be an object"

    status = value.get("status")
    if status not in {"passed", "failed"}:
        return "adversarial_validation.status must be passed or failed"
    residual_risk = value.get("residual_risk")
    if not isinstance(residual_risk, str) or not residual_risk.strip():
        return "adversarial_validation.residual_risk must be a non-empty string"

    probes = value.get("probes")
    if not isinstance(probes, list):
        return "adversarial_validation.probes must be a list"
    minimum_probes = required_adversarial_probe_count()
    if len(probes) < minimum_probes:
        return (
            "adversarial_validation requires at least "
            f"{minimum_probes} concrete probe(s) for this changed-file scope"
        )

    changed_files = current_changed_files()
    confirmed_locations: set[tuple[str, int]] = set()
    probe_identities: set[tuple[str, int, str, str, str, str]] = set()
    for index, probe in enumerate(probes, start=1):
        if not isinstance(probe, dict):
            return f"adversarial probe {index} must be an object"
        path = probe.get("path")
        if not isinstance(path, str) or not path.strip():
            return f"adversarial probe {index} path must be a non-empty string"
        path = path.strip()
        posix_path = PurePosixPath(path)
        windows_path = PureWindowsPath(path)
        if (
            "\\" in path
            or path.startswith(("/", "//"))
            or posix_path.is_absolute()
            or windows_path.is_absolute()
            or bool(windows_path.drive)
            or ".." in posix_path.parts
            or path != posix_path.as_posix()
        ):
            return f"adversarial probe {index} path is unsafe"
        if not changed_files:
            return "trusted current-head changed-file manifest is unavailable or empty"
        if path not in changed_files:
            return f"adversarial probe {index} path is not a current-head changed file"
        line = probe.get("line")
        if isinstance(line, bool) or not isinstance(line, int) or line <= 0:
            return f"adversarial probe {index} line must be a positive integer"
        location_error = adversarial_probe_location_error(path, line)
        if location_error:
            return f"adversarial probe {index} {location_error}"
        for field in ("hypothesis", "attack_or_counterexample", "evidence"):
            field_value = probe.get(field)
            if not isinstance(field_value, str) or not field_value.strip():
                return f"adversarial probe {index} field {field} must be non-empty"
        probe_evidence = str(probe.get("evidence") or "")
        runtime_tool = unreceipted_runtime_tool_claim(probe_evidence)
        if runtime_tool:
            return (
                f"adversarial probe {index} claims {runtime_tool} execution "
                "without a trusted workflow receipt"
            )
        evidence_error = adversarial_evidence_rejection_reason(
            probe_evidence,
            path,
            line,
        )
        if evidence_error:
            return f"adversarial probe {index} evidence {evidence_error}"
        receipt_error = adversarial_probe_source_receipt_error(
            probe_evidence,
            path,
            line,
        )
        if receipt_error:
            return f"adversarial probe {index} evidence {receipt_error}"
        outcome = probe.get("outcome")
        if outcome not in {"falsified", "confirmed"}:
            return f"adversarial probe {index} outcome must be falsified or confirmed"
        probe_identity = (
            path,
            line,
            " ".join(str(probe["hypothesis"]).split()).casefold(),
            " ".join(str(probe["attack_or_counterexample"]).split()).casefold(),
            " ".join(probe_evidence.split()).casefold(),
            outcome,
        )
        if probe_identity in probe_identities:
            return (
                f"adversarial probe {index} duplicates an earlier probe after "
                "canonical normalization"
            )
        probe_identities.add(probe_identity)
        if outcome == "confirmed":
            confirmed_locations.add((path, line))

    if result == "APPROVE":
        if status != "passed":
            return "APPROVE requires adversarial_validation.status=passed"
        if confirmed_locations:
            return "APPROVE cannot contain a confirmed adversarial probe"
    else:
        if status != "failed":
            return "REQUEST_CHANGES requires adversarial_validation.status=failed"
        if not confirmed_locations:
            return "REQUEST_CHANGES requires at least one confirmed adversarial probe"
        finding_locations = {
            (str(finding.get("path") or "").strip(), finding.get("line"))
            for finding in findings
            if isinstance(finding, dict)
        }
        if not confirmed_locations.intersection(finding_locations):
            return (
                "REQUEST_CHANGES requires a confirmed adversarial probe anchored "
                "to a published finding"
            )
    return ""


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
    has_source_like_change = any(
        changed_file_is_source_like(path) for path in changed_files
    )
    has_test_like_change = any(
        changed_file_is_test_like(path) for path in changed_files
    )
    if has_source_like_change and any(
        phrase in combined for phrase in SOURCE_KIND_FALSE_PHRASES
    ):
        return True
    if has_source_like_change and any(
        phrase in combined for phrase in EXECUTABLE_KIND_FALSE_PHRASES
    ):
        return True
    if has_test_like_change and any(
        phrase in combined for phrase in TEST_KIND_FALSE_PHRASES
    ):
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
        return False
    combined = f"{reason}\n{summary}"
    return any(changed_file in combined for changed_file in changed_files)


def mentions_verification_posture(reason: str, summary: str) -> bool:
    """Return whether an approval records the concrete review surfaces checked."""
    combined = f"{reason}\n{summary}".casefold()
    if not current_changed_files() and (
        "no executable changes" in combined
        or "no changed files" in combined
        or "no changes" in combined
        or "no ui codebase changes" in combined
    ):
        # Handle no-op PRs with empty/no changed files where deep verification labels may be omitted by model.
        return True
    return (
        all(label in combined for label in APPROVAL_VERIFICATION_LABELS)
        and "codegraph" in combined
    )


def label_section(text: str, label: str) -> str:
    """Return text after a verification label until the next known label."""

    def label_starts(candidate: str, start_index: int = 0) -> list[int]:
        """Return exact verification-label starts without suffix collisions."""
        starts = []
        index = text.find(candidate, start_index)
        while index != -1:
            if (
                candidate == "coverage:"
                and text[max(0, index - 10) : index] == "docstring "
            ):
                index = text.find(candidate, index + len(candidate))
                continue
            starts.append(index)
            index = text.find(candidate, index + len(candidate))
        return starts

    starts = label_starts(label)
    if not starts:
        return ""
    start = starts[-1] + len(label)

    end = len(text)
    for candidate in APPROVAL_VERIFICATION_LABELS:
        if candidate == label:
            continue
        candidate_starts = label_starts(candidate, start)
        if candidate_starts and candidate_starts[0] < end:
            end = candidate_starts[0]

    return text[start:end]


def coverage_section_is_valid(section: str) -> bool:
    """Return whether one approval coverage label cites acceptable evidence."""
    if "coverage execution evidence" not in section:
        return False
    if "not applicable" in section and (
        "no supported source files or package manifests" in section
        or "no supported changed source files or package manifests" in section
    ):
        return not any(
            changed_file_is_source_like(path) for path in current_changed_files()
        )
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
    if not current_changed_files() and (
        "no executable changes" in combined
        or "no changed files" in combined
        or "no changes" in combined
        or "no ui codebase changes" in combined
    ):
        return True
    coverage_section = label_section(combined, "coverage:")
    docstring_section = label_section(combined, "docstring coverage:")
    required_sections = (coverage_section, docstring_section)
    if not all(required_sections):
        return False
    return all(coverage_section_is_valid(section) for section in required_sections)


def approval_repair_evidence_file() -> Path | None:
    """Return the bounded evidence file used for approval-summary repair."""
    for env_name in EVIDENCE_REPAIR_ENV_VARS:
        path = trusted_artifact_path(env_name)
        if path is not None:
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
        line = BULLET_PREFIX_PATTERN.sub("", line)
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
        and "- docstring evidence: configured repository docstring gates passed or docstring coverage was advisory"
        in section
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
Standards search: standards and external-source claims require trusted bounded source evidence prepared outside the isolated model process; no evidence-backed standards blocker is present in bounded evidence.
Compatibility/convention: changed workflow/script conventions, object naming, and reserved-word safety for schema/API/config/code surfaces were checked in bounded evidence.
Breaking-change/backcompat: deployment evidence and changed-file history were checked for backward-compatibility risk.
Performance: changed surfaces were checked for performance risk in bounded evidence.
Developer experience: changed automation, review, test, setup, and maintenance surfaces were checked for helpful or obstructive DX impact in bounded evidence.
User experience: connected user, operator, API, CLI, documentation, review-comment, status-check, rendering, and workflow-reader behavior was checked for contradictions against code, docs, and tests in bounded evidence.
Visual/DOM: deterministic repair does not infer browser runtime execution; source-backed DOM/UI evidence and trusted workflow receipts were reviewed when present, and non-web surfaces used API/CLI/log/docs/workflow evidence instead.
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
            repaired_summary = build_approval_repair_summary(summary, evidence_text)
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


def check_structural_approval(
    control_file: Path,
    expected_head_sha: str,
    expected_run_id: str,
    expected_run_attempt: str,
) -> int:
    """Validate a normalized control block bound to an explicit current run."""

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

    validation_reasons: list[str] = []
    normalized = valid_control(
        value,
        expected_head_sha=expected_head_sha,
        expected_run_id=expected_run_id,
        expected_run_attempt=expected_run_attempt,
        rejection_reasons=validation_reasons,
    )
    if normalized is None:
        detail = (
            validation_reasons[-1] if validation_reasons else "unknown validation error"
        )
        return reject(f"control identity/schema validation failed: {detail}")
    return 0


def canonicalize_finding_fields(finding: dict[str, Any]) -> dict[str, Any]:
    """Map known-safe model vocabulary drift onto the canonical finding schema.

    Findings only exist on REQUEST_CHANGES control blocks (valid_control rejects
    APPROVE blocks that carry findings), so rescuing a drifted finding can only
    publish a blocking review — it can never loosen approval evidence. The
    observed safe drift is repaired: ``priority`` used in place of
    ``severity``. Source-backed ``suggested_diff`` evidence must remain
    explicit because the downstream publication gate verifies it against the
    current-head diff.
    """

    def has_non_blank_text(field_candidate: Any) -> bool:
        """Return whether a field candidate is a non-blank string."""
        return isinstance(field_candidate, str) and bool(field_candidate.strip())

    finding = dict(finding)
    priority = finding.pop("priority", None)
    if not has_non_blank_text(finding.get("severity")) and has_non_blank_text(priority):
        finding["severity"] = priority
    return finding


def valid_control(
    value: Any,
    *,
    expected_head_sha: str,
    expected_run_id: str,
    expected_run_attempt: str,
    rejection_reasons: list[str] | None = None,
) -> dict[str, Any] | None:
    """Return a normalized control block when it matches the current run."""

    def reject(reason: str) -> None:
        """Record a bounded, non-secret reason for rejecting one candidate."""
        if rejection_reasons is not None:
            rejection_reasons.append(reason)
        return None

    if not isinstance(value, dict):
        return reject("candidate is not a JSON object")

    if value.get("head_sha") != expected_head_sha:
        return reject("head_sha does not match the current pull request head")
    if value.get("run_id") != expected_run_id:
        return reject("run_id does not match the current workflow run")
    if value.get("run_attempt") != expected_run_attempt:
        return reject("run_attempt does not match the current workflow attempt")

    provenance_error = artifact_identity_error(
        expected_head_sha,
        expected_run_id,
        expected_run_attempt,
    )
    if provenance_error:
        return reject(f"trusted artifact provenance failed: {provenance_error}")

    result = value.get("result")
    if result not in {"APPROVE", "REQUEST_CHANGES"}:
        return reject("result must be APPROVE or REQUEST_CHANGES")

    if not isinstance(value.get("reason"), str) or not value["reason"].strip():
        return reject("reason must be a non-empty string")
    if not isinstance(value.get("summary"), str) or not value["summary"].strip():
        return reject("summary must be a non-empty string")
    reason = value["reason"].strip()
    summary = value["summary"].strip()

    findings = value.get("findings")
    if findings is None and result == "APPROVE":
        findings = []
    if not isinstance(findings, list):
        return reject("findings must be an array")
    if result == "APPROVE" and findings:
        return reject("APPROVE cannot contain findings")
    if result == "REQUEST_CHANGES" and not findings:
        return reject("REQUEST_CHANGES requires at least one finding")
    value = repair_adversarial_probe_source_bindings(value)
    adversarial_error = adversarial_validation_error(
        value.get("adversarial_validation"),
        result=result,
        findings=findings,
    )
    if adversarial_error:
        return reject(adversarial_error)
    runtime_tool = unreceipted_runtime_tool_claim(control_review_text(value))
    if runtime_tool:
        return reject(
            f"review claims {runtime_tool} execution without a trusted workflow receipt"
        )
    failed_check_phrase = non_actionable_failed_check_review_phrase(value)
    if failed_check_phrase:
        return reject(f"non-actionable failed-check deflection: {failed_check_phrase}")
    if result != "APPROVE" and violates_review_language_contract(value):
        return reject("review prose does not follow the preferred PR language")
    if result == "APPROVE":
        if admits_missing_structural_review(reason, summary):
            return reject("approval admits missing structural review")
        if not mentions_actual_changed_file(reason, summary):
            return reject("approval does not cite changed-file evidence")
        if not mentions_verification_posture(reason, summary):
            return reject("approval does not include the required verification posture")
        if not mentions_full_coverage(reason, summary):
            return reject(
                "approval does not prove 100% coverage or an explicit no-source exception"
            )
        if contradicts_changed_file_kinds(reason, summary):
            return reject("approval contradicts changed file kinds")
        if contradicts_material_changed_file_scope(reason, summary):
            return reject("approval trivializes material changed files")
        model_failure_phrase = model_failure_approval_phrase(reason, summary)
        if model_failure_phrase:
            return reject(
                f"approval depends on failed model output: {model_failure_phrase}"
            )
        summary = repair_approval_summary(reason, summary)
        reason = repair_approval_reason(reason, summary)
        value = {**value, "reason": reason, "summary": summary}
        if violates_review_language_contract(value):
            return reject("review prose does not follow the preferred PR language")
        if not mentions_actual_changed_file(reason, summary):
            return reject("approval does not cite changed-file evidence")
        if not mentions_verification_posture(reason, summary):
            return reject("approval does not include the required verification posture")
        if not mentions_full_coverage(reason, summary):
            return reject(
                "approval does not prove 100% coverage or an explicit no-source exception"
            )
        if contradicts_changed_file_kinds(reason, summary):
            return reject("approval contradicts changed file kinds")
        if contradicts_material_changed_file_scope(reason, summary):
            return reject("approval trivializes material changed files")
        model_failure_phrase = model_failure_approval_phrase(reason, summary)
        if model_failure_phrase:
            return reject(
                f"approval depends on failed model output: {model_failure_phrase}"
            )

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
    normalized_findings = []
    for finding_index, finding in enumerate(findings, start=1):
        if not isinstance(finding, dict):
            return reject(f"finding {finding_index} is not an object")
        line = finding.get("line")
        if isinstance(line, bool) or not isinstance(line, int) or line <= 0:
            return reject(f"finding {finding_index} line must be a positive integer")
        finding = canonicalize_finding_fields(finding)
        for field in required_finding_fields:
            if not isinstance(finding.get(field), str) or not finding[field].strip():
                return reject(
                    f"finding {finding_index} field {field} must be a non-empty string"
                )
        normalized_findings.append(finding)

    normalized = {
        "head_sha": value["head_sha"],
        "run_id": value["run_id"],
        "run_attempt": value["run_attempt"],
        "result": result,
        "reason": reason,
        "summary": summary,
        "findings": normalized_findings,
    }
    if isinstance(value.get("adversarial_validation"), dict):
        normalized["adversarial_validation"] = value["adversarial_validation"]
    return normalized


def iter_json_objects(text: str) -> list[Any]:
    """Extract top-level JSON values without promoting nested control objects."""
    decoder = json.JSONDecoder()
    values: list[Any] = []

    try:
        # Fast path for pure JSON payloads; preserve the single top-level value.
        return [json.loads(text)]
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
            values.append(value)
            # ⚡ Bolt: Advance index to avoid O(N^2) redundant parsing of nested JSON blocks
            index = new_index
            continue
        except json.JSONDecodeError:
            pass
        index += 1

    return values


def current_run_control_candidate(
    value: Any,
    expected_head_sha: str,
    expected_run_id: str,
    expected_run_attempt: str,
) -> bool:
    """Return whether a top-level value claims the exact current workflow run."""
    return bool(
        isinstance(value, dict)
        and value.get("head_sha") == expected_head_sha
        and value.get("run_id") == expected_run_id
        and value.get("run_attempt") == expected_run_attempt
    )


def main(argv: list[str]) -> int:
    """Run the normalizer CLI and write the publishable control block."""
    if len(argv) == 6 and argv[1] == "--check-structural-approval":
        return check_structural_approval(
            Path(argv[5]),
            argv[2],
            argv[3],
            argv[4],
        )

    if len(argv) != 5:
        print(
            "usage: opencode_review_normalize_output.py "
            "<expected_head_sha> <expected_run_id> <expected_run_attempt> <output_file>\n"
            "   or: opencode_review_normalize_output.py --check-structural-approval "
            "<expected_head_sha> <expected_run_id> <expected_run_attempt> <control_json_file>",
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

    values = iter_json_objects(output_text)
    current_candidates = [
        value
        for value in values
        if current_run_control_candidate(
            value,
            expected_head_sha,
            expected_run_id,
            expected_run_attempt,
        )
    ]
    if len(current_candidates) != 1:
        if current_candidates:
            print(
                "CONTROL_REJECTED: expected exactly one top-level current-run "
                f"control candidate, found {len(current_candidates)}",
                file=sys.stderr,
            )
        else:
            print(
                "CONTROL_REJECTED: no top-level current-run control JSON object was found",
                file=sys.stderr,
            )
        print("NO_CONCLUSION", file=sys.stderr)
        return 4

    rejection_reasons: list[str] = []
    control = valid_control(
        current_candidates[0],
        expected_head_sha=expected_head_sha,
        expected_run_id=expected_run_id,
        expected_run_attempt=expected_run_attempt,
        rejection_reasons=rejection_reasons,
    )
    if control is None:
        detail = (
            rejection_reasons[0]
            if rejection_reasons
            else "candidate failed an unspecified control validation"
        )
        print(f"CONTROL_REJECTED candidate=1: {detail}", file=sys.stderr)
        print("NO_CONCLUSION", file=sys.stderr)
        return 4

    normalized_json = (
        json.dumps(control, separators=(",", ":"), ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv))
