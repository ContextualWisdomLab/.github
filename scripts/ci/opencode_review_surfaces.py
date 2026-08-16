#!/usr/bin/env python3
"""Split OpenCode review publication into a diff review and a gate-status comment.

The OriginWeave #47 failure posted the same coverage-gate body as both the
formal pull-request review and the issue comment, and it anchored that body to
``.github/workflows/opencode-review.yml:1`` even though the product diff was a
Rust crate. This module is the trusted publisher contract for those surfaces.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import OrderedDict
from pathlib import Path, PurePosixPath
from typing import Sequence

CENTRAL_WORKFLOW_ANCHOR = ".github/workflows/opencode-review.yml"
PUB_ITEM_RE = re.compile(
    r"^\s*pub(?:\s*\([^)]*\))?\s+"
    r"(?:async\s+)?(?:unsafe\s+)?"
    r"(?P<kind>struct|enum|fn|trait|type|mod)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)
RUST_SUFFIXES = {".rs"}
PYTHON_SUFFIXES = {".py"}
TYPESCRIPT_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}
GO_SUFFIXES = {".go"}
WORKFLOW_PREFIXES = (".github/workflows/",)
CI_PREFIXES = ("scripts/ci/",)
DOC_PREFIXES = ("docs/",)
TEST_NAME_RE = re.compile(r"(^|/)tests?(/|$)|(^|/)test_[^/]+")


def posix_path(raw_path: str) -> str:
    """Normalize a repository-relative path to POSIX form without traversal."""
    normalized = raw_path.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"changed path is not a bounded repository path: {raw_path}")
    return str(candidate)


def classify_changed_path(raw_path: str) -> dict[str, str]:
    """Return the review surface, impact, and verification label for one path."""
    path = posix_path(raw_path)
    suffix = Path(path).suffix.lower()
    parts = PurePosixPath(path).parts
    name = Path(path).name

    if path.startswith(WORKFLOW_PREFIXES):
        return {
            "key": f"workflow:{path}",
            "surface": f"Workflow: {name}",
            "impact": "GitHub Actions review job",
            "verify": "actionlint plus required checks",
            "kind": "workflow",
        }
    if path.startswith(CI_PREFIXES):
        return {
            "key": f"ci:{path}",
            "surface": f"CI script: {name}",
            "impact": "review and security gate shell path",
            "verify": "bash -n plus Strix self-test",
            "kind": "ci",
        }
    if parts and parts[0] == "crates":
        crate = parts[1] if len(parts) > 1 else name
        return {
            "key": f"rust-crate:{crate}",
            "surface": f"Rust crate: {crate}",
            "impact": "Rust workspace crate API and tests",
            "verify": "cargo test plus llvm-cov",
            "kind": "rust-crate",
        }
    if suffix in RUST_SUFFIXES:
        return {
            "key": "rust-source",
            "surface": f"Rust source: {name}",
            "impact": "Rust package behavior",
            "verify": "cargo test plus llvm-cov",
            "kind": "rust",
        }
    if TEST_NAME_RE.search(path):
        return {
            "key": f"tests:{Path(path).parent.as_posix()}",
            "surface": f"Test: {name}",
            "impact": "regression suite",
            "verify": "targeted test run",
            "kind": "tests",
        }
    if path.startswith(DOC_PREFIXES):
        return {
            "key": "docs",
            "surface": f"Docs: {name}",
            "impact": "operator or user guidance",
            "verify": "docs review",
            "kind": "docs",
        }
    if parts and parts[0] == "backend":
        return {
            "key": "backend",
            "surface": f"Backend: {name}",
            "impact": "API and service runtime",
            "verify": "backend tests",
            "kind": "backend",
        }
    if parts and parts[0] == "frontend":
        return {
            "key": "frontend",
            "surface": f"Frontend: {name}",
            "impact": "browser runtime and bundle",
            "verify": "frontend tests",
            "kind": "frontend",
        }
    if parts and parts[0] == "src" and suffix in PYTHON_SUFFIXES:
        return {
            "key": "python-src",
            "surface": f"Python package: {name}",
            "impact": "Python runtime API",
            "verify": "pytest plus coverage",
            "kind": "python",
        }
    if parts and parts[0] == "src" and suffix in TYPESCRIPT_SUFFIXES:
        return {
            "key": "typescript-src",
            "surface": f"TypeScript/JavaScript: {name}",
            "impact": "TypeScript or JavaScript runtime",
            "verify": "package test plus coverage",
            "kind": "typescript",
        }
    if suffix in PYTHON_SUFFIXES:
        return {
            "key": "python",
            "surface": f"Python: {name}",
            "impact": "Python module behavior",
            "verify": "pytest plus coverage",
            "kind": "python",
        }
    if suffix in TYPESCRIPT_SUFFIXES:
        return {
            "key": "typescript",
            "surface": f"TypeScript/JavaScript: {name}",
            "impact": "TypeScript or JavaScript runtime",
            "verify": "package test plus coverage",
            "kind": "typescript",
        }
    if suffix in GO_SUFFIXES:
        return {
            "key": "go",
            "surface": f"Go package: {name}",
            "impact": "Go runtime API",
            "verify": "go test",
            "kind": "go",
        }
    return {
        "key": f"other:{path}",
        "surface": f"Repository file: {name}",
        "impact": "repository behavior",
        "verify": "required checks",
        "kind": "other",
    }


def classify_surfaces(raw_paths: Sequence[str]) -> list[dict[str, str]]:
    """Group changed paths into labeled review surfaces."""
    grouped: "OrderedDict[str, dict[str, str]]" = OrderedDict()
    for raw_path in raw_paths:
        if not str(raw_path).strip():
            continue
        classified = classify_changed_path(raw_path)
        key = classified["key"]
        if key not in grouped:
            grouped[key] = {
                "surface": classified["surface"],
                "impact": classified["impact"],
                "verify": classified["verify"],
                "kind": classified["kind"],
                "count": "1",
            }
        else:
            count = int(grouped[key]["count"]) + 1
            grouped[key]["count"] = str(count)
            label = grouped[key]["surface"].split(" (", 1)[0]
            grouped[key]["surface"] = f"{label} ({count} files)"
    return list(grouped.values())


def rust_api_symbols(source_root: Path | None, raw_paths: Sequence[str]) -> list[str]:
    """Extract public Rust API names from changed crate sources when present."""
    if source_root is None:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for raw_path in raw_paths:
        path = posix_path(raw_path)
        if Path(path).suffix != ".rs":
            continue
        candidate = source_root / path
        if not candidate.is_file() or candidate.is_symlink():
            continue
        text = candidate.read_text(encoding="utf-8")
        for match in PUB_ITEM_RE.finditer(text):
            name = match.group("name")
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _quote_label(value: str) -> str:
    """Make a Mermaid node label safe for quoted rendering."""
    return value.replace('"', "").replace("\n", " ").replace("\r", " ").strip()


def emit_mermaid(
    raw_paths: Sequence[str],
    merge_state: str = "UNKNOWN",
    source_root: Path | None = None,
) -> str:
    """Render a source-backed diagram of the changed API, not a file inventory."""
    paths = [posix_path(path) for path in raw_paths if str(path).strip()]
    if not paths:
        return (
            "```mermaid\n"
            "flowchart LR\n"
            '  Evidence["OpenCode evidence"] --> Review["Current PR review path"]\n'
            '  Review --> Verify["Required checks"]\n'
            "```\n"
        )

    symbols = rust_api_symbols(source_root, paths)
    rust_paths = [path for path in paths if path.startswith("crates/") or path.endswith(".rs")]
    if symbols:
        lines = ["```mermaid", "classDiagram"]
        for symbol in symbols[:8]:
            lines.append(f"  class {_quote_label(symbol)}")
        if len(symbols) >= 2:
            lines.append(f"  {_quote_label(symbols[0])} --> {_quote_label(symbols[1])}")
        lines.append("```")
        return "\n".join(lines) + "\n"
    if rust_paths:
        crate = "Rust crate"
        for path in rust_paths:
            parts = PurePosixPath(path).parts
            if len(parts) > 1 and parts[0] == "crates":
                crate = parts[1]
                break
        return (
            "```mermaid\n"
            "sequenceDiagram\n"
            f"  participant Caller as Caller\n"
            f"  participant Crate as {_quote_label(crate)}\n"
            "  participant Tests as Crate tests\n"
            "  Caller->>Crate: changed public API\n"
            "  Tests->>Crate: regression coverage\n"
            "```\n"
        )

    surfaces = classify_surfaces(paths)
    lines = [
        "```mermaid",
        "flowchart LR",
        '  PR["PR changed files"] --> Evidence["OpenCode bounded evidence"]',
    ]
    for index, surface in enumerate(surfaces, start=1):
        label = _quote_label(surface["surface"])
        impact = _quote_label(surface["impact"])
        verify = _quote_label(surface["verify"])
        lines.append(f'  Evidence --> S{index}["{label}"]')
        lines.append(f'  S{index} --> I{index}["{impact}"]')
        if merge_state in {"DIRTY", "CONFLICTING"}:
            lines.append(f'  I{index} --> Conflict["Merge conflict blocks this path"]')
            next_node = "Conflict"
        else:
            lines.append(f'  I{index} --> R{index}["Review risk: {label}"]')
            next_node = f"R{index}"
        lines.append(f'  {next_node} --> V{index}["{verify}"]')
    lines.append("```")
    return "\n".join(lines) + "\n"


def coverage_anchor_allowed(path: str, changed_files: Sequence[str]) -> bool:
    """Allow a workflow-file finding only when that file is in the current diff."""
    normalized = posix_path(path)
    changed = {posix_path(item) for item in changed_files if str(item).strip()}
    return normalized in changed


def _language(value: str) -> str:
    """Normalize the review-language contract to korean or english."""
    return "korean" if value.strip().casefold() == "korean" else "english"


def build_status_comment(
    *,
    result: str,
    head_sha: str,
    run_id: str,
    run_attempt: str,
    coverage_result: str,
    coverage_summary: str = "",
    language: str = "english",
    control_block: str = "",
) -> str:
    """Build the issue-comment gate/status surface without review findings."""
    korean = _language(language) == "korean"
    heading = "OpenCode 게이트 상태" if korean else "OpenCode Review Status"
    coverage_label = "커버리지 게이트" if korean else "Coverage gate"
    lines = [
        "<!-- opencode-review-overview -->",
        f"## {heading}",
        "",
        f"- Head SHA: `{head_sha}`",
        f"- Workflow run: {run_id}",
        f"- Workflow attempt: {run_attempt}",
        f"- Gate result: `{result}`",
        f"- {coverage_label}: `{coverage_result}`",
        "",
    ]
    if coverage_result != "success":
        blocker = (
            "커버리지 증거 작업이 통과하지 않아 승인은 차단됩니다. 코드 리뷰는 별도 정식 리뷰 본문에 있습니다."
            if korean
            else (
                "Coverage evidence did not pass, so approval is blocked. "
                "The formal pull-request review is the source-backed diff review, "
                "not this status comment."
            )
        )
        lines.extend([blocker, ""])
    summary = coverage_summary.strip()
    if summary:
        lines.extend(
            [
                "## Coverage evidence",
                "",
                summary,
                "",
            ]
        )
    if control_block.strip():
        lines.extend([control_block.strip(), ""])
    return "\n".join(lines).rstrip() + "\n"


def _file_role(path: str) -> str:
    """Describe what a changed path is in the review walkthrough."""
    classified = classify_changed_path(path)
    return f"`{posix_path(path)}` — {classified['impact']}"


def build_fallback_review(
    *,
    changed_files: Sequence[str],
    head_sha: str,
    run_id: str,
    run_attempt: str,
    source_root: Path | None = None,
    language: str = "english",
    coverage_result: str = "success",
) -> str:
    """Build a source-backed formal review of the actual changed product files."""
    paths = [posix_path(path) for path in changed_files if str(path).strip()]
    korean = _language(language) == "korean"
    overview = "Pull request overview" if not korean else "Pull request 개요"
    walkthrough = "Changed files" if not korean else "변경 파일"
    diagram = "Changed behavior" if not korean else "변경 동작"
    findings = "Findings" if not korean else "발견 사항"
    intro = (
        "OpenCode reviewed the current-head product diff. Coverage is a separate gate."
        if not korean
        else "OpenCode가 현재 head의 제품 diff를 리뷰했습니다. 커버리지는 별도 게이트입니다."
    )
    if not paths:
        intro = (
            "OpenCode could not list changed product files for this head."
            if not korean
            else "OpenCode가 이 head의 변경 제품 파일을 나열하지 못했습니다."
        )
    lines = [
        f"## {overview}",
        "",
        intro,
        "",
        f"## {walkthrough}",
        "",
    ]
    if paths:
        lines.extend(f"- {_file_role(path)}" for path in paths)
    else:
        lines.append("- No changed product files were supplied to the fallback review.")
    lines.extend(["", f"## {diagram}", "", emit_mermaid(paths, source_root=source_root).rstrip(), ""])
    symbols = rust_api_symbols(source_root, paths)
    if symbols:
        api_heading = "Changed API" if not korean else "변경 API"
        lines.extend([f"## {api_heading}", ""])
        lines.extend(f"- `{symbol}`" for symbol in symbols)
        lines.append("")
    lines.extend(
        [
            f"## {findings}",
            "",
            (
                "No source-backed product finding is synthesized from the coverage gate. "
                "A coverage miss belongs in the status comment."
                if not korean
                else "커버리지 게이트만으로 제품 소스 발견 사항을 합성하지 않습니다. 커버리지 결과는 상태 댓글에 둡니다."
            ),
            "",
            f"- Head SHA: `{head_sha}`",
            f"- Workflow run: {run_id}",
            f"- Workflow attempt: {run_attempt}",
            f"- Coverage gate: `{coverage_result}`",
            "",
        ]
    )
    body = "\n".join(lines)
    if CENTRAL_WORKFLOW_ANCHOR in body and not coverage_anchor_allowed(
        CENTRAL_WORKFLOW_ANCHOR, paths
    ):
        raise ValueError(
            "fallback review must not cite "
            f"{CENTRAL_WORKFLOW_ANCHOR} unless that file is in the PR diff"
        )
    return body


def distinct_surfaces(review_body: str, comment_body: str) -> None:
    """Reject publication that pastes the same overview/findings onto both surfaces."""
    if review_body.strip() == comment_body.strip():
        raise ValueError("formal review body must not equal the status comment body")
    if "## Pull request overview" in comment_body or "## Pull request 개요" in comment_body:
        raise ValueError("status comment must not contain the formal review overview")
    if "## Findings" in comment_body or "## 발견 사항" in comment_body:
        raise ValueError("status comment must not contain the formal review findings")
    if "## OpenCode Review Overview" in review_body or "## OpenCode 게이트 상태" in review_body:
        raise ValueError("formal review must not reuse the status-comment heading")


def review_event_when_coverage_blocks(model_result: str) -> str:
    """Return the GitHub review event when coverage failed but a diff review exists."""
    if model_result == "REQUEST_CHANGES":
        return "REQUEST_CHANGES"
    return "COMMENT"


def read_changed_files(path: Path) -> list[str]:
    """Load a newline-delimited changed-file list."""
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _add_common_identity_args(parser: argparse.ArgumentParser) -> None:
    """Add the head/run identity flags shared by publisher subcommands."""
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--coverage-result", default="unknown")
    parser.add_argument("--language", default="english")


def main(argv: Sequence[str] | None = None) -> int:
    """CLI for trusted review/status rendering from the publisher workflow."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    mermaid = subparsers.add_parser("emit-mermaid", help="Render the changed-API diagram")
    mermaid.add_argument("--changed-files-file", type=Path, required=True)
    mermaid.add_argument("--source-root", type=Path)
    mermaid.add_argument("--merge-state", default="UNKNOWN")

    status = subparsers.add_parser("build-status", help="Render the gate/status comment")
    _add_common_identity_args(status)
    status.add_argument("--result", required=True)
    status.add_argument("--coverage-summary", default="")
    status.add_argument("--control-block", default="")

    fallback = subparsers.add_parser(
        "build-fallback-review", help="Render a source-backed diff review"
    )
    _add_common_identity_args(fallback)
    fallback.add_argument("--changed-files-file", type=Path, required=True)
    fallback.add_argument("--source-root", type=Path)

    args = parser.parse_args(argv)
    if args.command == "emit-mermaid":
        sys.stdout.write(
            emit_mermaid(
                read_changed_files(args.changed_files_file),
                merge_state=args.merge_state,
                source_root=args.source_root,
            )
        )
        return 0
    if args.command == "build-status":
        sys.stdout.write(
            build_status_comment(
                result=args.result,
                head_sha=args.head_sha,
                run_id=args.run_id,
                run_attempt=args.run_attempt,
                coverage_result=args.coverage_result,
                coverage_summary=args.coverage_summary,
                language=args.language,
                control_block=args.control_block,
            )
        )
        return 0
    sys.stdout.write(
        build_fallback_review(
            changed_files=read_changed_files(args.changed_files_file),
            head_sha=args.head_sha,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            source_root=args.source_root,
            language=args.language,
            coverage_result=args.coverage_result,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
