"""Regression tests for distinct OpenCode review and status surfaces."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

import pytest

from scripts.ci import opencode_review_surfaces as surfaces

ORIGINWEAVE_47_FILES = [
    "crates/originweave-destination/src/lib.rs",
    "crates/originweave-destination/src/resolution.rs",
    "crates/originweave-destination/tests/resolution_freshness.rs",
]
HEAD = "79cf275686e2376a51783a2d03128eca21e7c0e5"


def test_crates_paths_are_rust_crate_surfaces() -> None:
    """OriginWeave-style crates/ changes are Rust crate surfaces, not 'Changed file'."""
    classified = surfaces.classify_surfaces(ORIGINWEAVE_47_FILES)
    assert len(classified) == 1
    assert classified[0]["kind"] == "rust-crate"
    assert "Rust crate: originweave-destination" in classified[0]["surface"]
    assert "3 files" in classified[0]["surface"]
    assert classified[0]["surface"].startswith("Changed file") is False


def test_src_layouts_are_language_surfaces() -> None:
    """src/ Python and TypeScript layouts keep language-specific labels."""
    python_surface = surfaces.classify_changed_path("src/originweave/resolution.py")
    typescript_surface = surfaces.classify_changed_path("src/lib/resolution.ts")
    assert python_surface["kind"] == "python"
    assert python_surface["surface"].startswith("Python package:")
    assert typescript_surface["kind"] == "typescript"
    assert typescript_surface["surface"].startswith("TypeScript/JavaScript:")


def test_mermaid_labels_originweave_crate_not_changed_file_inventory() -> None:
    """The #47 mermaid must name the Rust crate instead of 'Changed file (3 files)'."""
    diagram = surfaces.emit_mermaid(ORIGINWEAVE_47_FILES)
    assert "Changed file (3 files)" not in diagram
    assert "originweave-destination" in diagram
    assert "sequenceDiagram" in diagram or "classDiagram" in diagram


def test_mermaid_uses_public_rust_api_when_source_exists(tmp_path: Path) -> None:
    """A class diagram is preferred when the changed crate exposes public types."""
    source = tmp_path / "crates/originweave-destination/src/resolution.rs"
    source.parent.mkdir(parents=True)
    source.write_text(
        "pub struct FreshResolutionSnapshot {\n    address: String,\n}\n"
        "pub fn resolve_fresh() {}\n",
        encoding="utf-8",
    )
    diagram = surfaces.emit_mermaid(
        ["crates/originweave-destination/src/resolution.rs"],
        source_root=tmp_path,
    )
    assert "classDiagram" in diagram
    assert "FreshResolutionSnapshot" in diagram
    assert "resolve_fresh" in diagram
    assert "class FreshResolutionSnapshot" in diagram
    assert "class resolve_fresh" in diagram
    assert "FreshResolutionSnapshot --> resolve_fresh" not in diagram
    assert " --> " not in diagram
    assert "Changed file" not in diagram


def test_coverage_fail_review_mentions_crate_files_not_central_workflow() -> None:
    """A coverage-gate failure still produces a review of the changed crate files."""
    review = surfaces.build_fallback_review(
        changed_files=ORIGINWEAVE_47_FILES,
        head_sha=HEAD,
        run_id="31951179896",
        run_attempt="1",
        coverage_result="failure",
    )
    comment = surfaces.build_status_comment(
        result="COVERAGE_BLOCKED",
        head_sha=HEAD,
        run_id="31951179896",
        run_attempt="1",
        coverage_result="failure",
        coverage_summary="## Coverage Decision\n\n- Result: FAIL\n",
    )
    surfaces.distinct_surfaces(review, comment)
    assert review != comment
    for path in ORIGINWEAVE_47_FILES:
        assert path in review
        assert path not in comment
    assert ".github/workflows/opencode-review.yml:1" not in review
    assert "Coverage gate: `failure`" in review
    assert "Coverage gate: `failure`" in comment
    assert "## Pull request overview" in review
    assert "## Pull request overview" not in comment
    assert "## Findings" not in comment


def test_workflow_anchor_forbidden_unless_file_is_in_diff() -> None:
    """The central workflow file is not a finding on an unrelated product PR."""
    assert (
        surfaces.coverage_anchor_allowed(
            ".github/workflows/opencode-review.yml",
            ORIGINWEAVE_47_FILES,
        )
        is False
    )
    assert (
        surfaces.coverage_anchor_allowed(
            ".github/workflows/opencode-review.yml",
            [".github/workflows/opencode-review.yml"],
        )
        is True
    )


def test_korean_status_and_review_keep_identifiers() -> None:
    """Korean PRs stay Korean while crate paths remain unchanged."""
    review = surfaces.build_fallback_review(
        changed_files=ORIGINWEAVE_47_FILES,
        head_sha=HEAD,
        run_id="1",
        run_attempt="1",
        language="korean",
        coverage_result="failure",
    )
    comment = surfaces.build_status_comment(
        result="COVERAGE_BLOCKED",
        head_sha=HEAD,
        run_id="1",
        run_attempt="1",
        coverage_result="failure",
        language="korean",
    )
    surfaces.distinct_surfaces(review, comment)
    assert "변경 파일" in review
    assert "게이트 상태" in comment
    assert "originweave-destination" in review


def test_review_event_keeps_request_changes_and_downgrades_approve() -> None:
    """Coverage failure may not publish APPROVE; code findings stay REQUEST_CHANGES."""
    assert surfaces.review_event_when_coverage_blocks("APPROVE") == "COMMENT"
    assert surfaces.review_event_when_coverage_blocks("REQUEST_CHANGES") == "REQUEST_CHANGES"
    assert surfaces.review_event_when_coverage_blocks("COMMENT") == "COMMENT"


def test_distinct_surfaces_reject_duplicated_overview() -> None:
    """The #47 publication shape — identical overview on both surfaces — fails."""
    body = "## Pull request overview\n\n## Findings\n"
    with pytest.raises(ValueError, match="must not equal"):
        surfaces.distinct_surfaces(body, body)
    with pytest.raises(ValueError, match="status comment must not contain"):
        surfaces.distinct_surfaces("review", "## Pull request overview\n")
    with pytest.raises(ValueError, match="formal review must not reuse"):
        surfaces.distinct_surfaces("## OpenCode Review Overview\n", "status")
    with pytest.raises(ValueError, match="formal review must not reuse"):
        surfaces.distinct_surfaces("## OpenCode Review Status\n", "status")


def test_rejects_path_traversal() -> None:
    """Publisher path classification fails closed on parent-directory segments."""
    with pytest.raises(ValueError, match="bounded repository path"):
        surfaces.posix_path("../secrets")
    assert surfaces.posix_path("./crates/originweave-destination/src/lib.rs") == (
        "crates/originweave-destination/src/lib.rs"
    )
    assert (
        surfaces.classify_changed_path("./.github/workflows/ci.yml")["kind"] == "workflow"
    )


def test_empty_paths_use_generic_evidence_diagram() -> None:
    """No changed files still produce a bounded evidence flowchart."""
    assert "OpenCode evidence" in surfaces.emit_mermaid([])


def test_conflict_state_marks_blocked_paths() -> None:
    """DIRTY merge state keeps the conflict node on classified surfaces."""
    diagram = surfaces.emit_mermaid(["docs/readme.md"], merge_state="DIRTY")
    assert "Merge conflict blocks this path" in diagram
    assert "Docs: readme.md" in diagram


def test_cli_renders_originweave_surfaces(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The workflow CLI emits the split surfaces used by the publisher."""
    changed = tmp_path / "changed.txt"
    changed.write_text("\n".join(ORIGINWEAVE_47_FILES) + "\n", encoding="utf-8")
    assert (
        surfaces.main(
            [
                "emit-mermaid",
                "--changed-files-file",
                str(changed),
            ]
        )
        == 0
    )
    mermaid = capsys.readouterr().out
    assert "Changed file (3 files)" not in mermaid
    assert "originweave-destination" in mermaid

    assert (
        surfaces.main(
            [
                "build-status",
                "--result",
                "COVERAGE_BLOCKED",
                "--head-sha",
                HEAD,
                "--run-id",
                "31951179896",
                "--run-attempt",
                "1",
                "--coverage-result",
                "failure",
                "--coverage-summary",
                "llvm-tools-preview missing",
            ]
        )
        == 0
    )
    status = capsys.readouterr().out
    assert "## Pull request overview" not in status
    assert "## Findings" not in status
    assert "llvm-tools-preview missing" not in status
    assert "Coverage gate: `failure`" in status

    assert (
        surfaces.main(
            [
                "build-fallback-review",
                "--changed-files-file",
                str(changed),
                "--head-sha",
                HEAD,
                "--run-id",
                "31951179896",
                "--run-attempt",
                "1",
                "--coverage-result",
                "failure",
            ]
        )
        == 0
    )
    review = capsys.readouterr().out
    assert "crates/originweave-destination/src/resolution.rs" in review
    assert ".github/workflows/opencode-review.yml:1" not in review
    surfaces.distinct_surfaces(review, status)


def test_script_entrypoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The executable workflow entrypoint delegates to main."""
    changed = tmp_path / "changed.txt"
    changed.write_text("docs/guide.md\n", encoding="utf-8")
    script = Path(surfaces.__file__)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(script), "emit-mermaid", "--changed-files-file", str(changed)],
    )
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(script), run_name="__main__")


def test_remaining_classifiers_cover_common_layouts() -> None:
    """Workflow, CI, backend, frontend, Go, and loose files keep specific labels."""
    assert surfaces.classify_changed_path(".github/workflows/ci.yml")["kind"] == "workflow"
    assert surfaces.classify_changed_path("scripts/ci/gate.sh")["kind"] == "ci"
    assert surfaces.classify_changed_path("backend/api.py")["kind"] == "backend"
    assert surfaces.classify_changed_path("frontend/app.tsx")["kind"] == "frontend"
    assert surfaces.classify_changed_path("pkg/main.go")["kind"] == "go"
    assert surfaces.classify_changed_path("lib.rs")["kind"] == "rust"
    assert surfaces.classify_changed_path("module.py")["kind"] == "python"
    assert surfaces.classify_changed_path("app.ts")["kind"] == "typescript"
    assert surfaces.classify_changed_path("tests/test_resolution.py")["kind"] == "tests"
    assert surfaces.classify_changed_path("LICENSE")["kind"] == "other"


def test_central_workflow_in_diff_is_a_workflow_surface_not_line_one_finding() -> None:
    """When the central workflow actually changed, name it as a workflow surface."""
    review = surfaces.build_fallback_review(
        changed_files=[".github/workflows/opencode-review.yml"],
        head_sha=HEAD,
        run_id="1",
        run_attempt="1",
    )
    assert ".github/workflows/opencode-review.yml" in review
    assert ".github/workflows/opencode-review.yml:1" not in review
    assert "Workflow: opencode-review.yml" in surfaces.emit_mermaid(
        [".github/workflows/opencode-review.yml"]
    )


def test_fallback_review_empty_file_list() -> None:
    """Missing changed-file evidence still produces a distinct review body."""
    review = surfaces.build_fallback_review(
        changed_files=[],
        head_sha=HEAD,
        run_id="1",
        run_attempt="1",
    )
    assert "No changed product files" in review
    assert ".github/workflows/opencode-review.yml:1" not in review


def test_fallback_review_rejects_accidental_central_workflow_citation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A synthesized body may not mention the central workflow unless it changed."""
    monkeypatch.setattr(surfaces, "CENTRAL_WORKFLOW_ANCHOR", "Coverage is a separate gate")
    with pytest.raises(ValueError, match="must not cite"):
        surfaces.build_fallback_review(
            changed_files=ORIGINWEAVE_47_FILES,
            head_sha=HEAD,
            run_id="1",
            run_attempt="1",
        )


def test_distinct_surfaces_reject_findings_on_status_comment() -> None:
    """Status comments cannot carry the formal findings block."""
    with pytest.raises(ValueError, match="status comment must not contain"):
        surfaces.distinct_surfaces("review", "## Findings\n")


def test_rust_api_symbols_skip_missing_and_symlink_sources(tmp_path: Path) -> None:
    """Public-API extraction ignores absent or symlinked sources."""
    assert surfaces.rust_api_symbols(None, ORIGINWEAVE_47_FILES) == []
    missing = surfaces.rust_api_symbols(
        tmp_path, ["crates/originweave-destination/src/lib.rs"]
    )
    assert missing == []
    target = tmp_path / "outside.rs"
    target.write_text("pub struct Leak {}\n", encoding="utf-8")
    linked = tmp_path / "crates/originweave-destination/src/lib.rs"
    linked.parent.mkdir(parents=True)
    linked.symlink_to(target)
    assert (
        surfaces.rust_api_symbols(tmp_path, ["crates/originweave-destination/src/lib.rs"])
        == []
    )


def test_rust_api_symbols_replace_invalid_utf8(tmp_path: Path) -> None:
    """A malformed Rust text blob cannot abort review-surface publication."""
    source = tmp_path / "lib.rs"
    source.write_bytes(b"pub struct BrokenEncoding {\xff\n}\n")

    assert surfaces.rust_api_symbols(tmp_path, ["lib.rs"]) == ["BrokenEncoding"]


def test_crates_root_and_grouped_python_surfaces() -> None:
    """A bare crates/ path and repeated src/ files keep specific labels."""
    assert surfaces.classify_changed_path("crates")["kind"] == "rust-crate"
    grouped = surfaces.classify_surfaces(
        ["src/one.py", "src/two.py", "docs/a.md", "docs/b.md"]
    )
    python = next(item for item in grouped if item["kind"] == "python")
    docs = next(item for item in grouped if item["kind"] == "docs")
    assert "2 files" in python["surface"]
    assert "2 files" in docs["surface"]


def test_surfaces_cover_remaining_review_branches(tmp_path: Path) -> None:
    """Empty paths, duplicate symbols, loose Rust files, and control blocks are covered."""
    assert surfaces.classify_surfaces(["", "  "]) == []
    source = tmp_path / "lib.rs"
    source.write_text(
        "pub struct Once {}\npub struct Once {}\n",
        encoding="utf-8",
    )
    assert surfaces.rust_api_symbols(tmp_path, ["README.md", "lib.rs"]) == ["Once"]
    diagram = surfaces.emit_mermaid(["lib.rs"], source_root=tmp_path)
    assert "classDiagram" in diagram
    assert "Once -->" not in diagram
    loose = surfaces.emit_mermaid(["src/resolution.rs"])
    assert "Rust crate" in loose
    quoted = surfaces._quote_label('Fresh\r\n"Snapshot"')
    assert '"' not in quoted
    assert "\n" not in quoted
    status = surfaces.build_status_comment(
        result="APPROVE",
        head_sha=HEAD,
        run_id="1",
        run_attempt="1",
        coverage_result="success",
        language="korean",
        control_block="<!-- opencode-review-control-v1\n{}\n-->",
    )
    assert "커버리지 증거 작업이 통과하지 않아" not in status
    assert "opencode-review-control-v1" in status
    review = surfaces.build_fallback_review(
        changed_files=["lib.rs"],
        head_sha=HEAD,
        run_id="1",
        run_attempt="1",
        source_root=tmp_path,
        language="korean",
    )
    assert "변경 API" in review
    assert "`Once`" in review


def test_cargo_toml_is_a_rust_surface() -> None:
    """Root Cargo.toml is a Rust manifest, not a generic changed file."""
    classified = surfaces.classify_changed_path("Cargo.toml")
    assert classified["kind"] == "rust"
    assert classified["surface"].startswith("Rust manifest:")
    diagram = surfaces.emit_mermaid(["Cargo.toml", "crates/demo/src/lib.rs"])
    assert "Changed file" not in diagram
    assert "demo" in diagram or "Rust" in diagram


def test_extract_model_prose_strips_sentinel_and_control() -> None:
    """Publisher keeps walkthrough text and drops the control-plane trailer."""
    raw = (
        "## Verdict\n\nREQUEST_CHANGES\n\n"
        "Walkthrough of crates/originweave-destination/src/resolution.rs\n"
        "<!-- opencode-review-gate head_sha=abc run_id=1 run_attempt=1 -->\n"
        "<!-- opencode-review-control-v1\n"
        '{"result":"REQUEST_CHANGES"}\n'
        "-->\n"
    )
    prose = surfaces.extract_model_prose(raw)
    assert "Walkthrough of crates/originweave-destination/src/resolution.rs" in prose
    assert "opencode-review-gate" not in prose
    assert "opencode-review-control-v1" not in prose


def test_format_request_changes_keeps_model_prose_and_strips_fake_anchor() -> None:
    """REQUEST_CHANGES keeps the model walkthrough and never cites workflow:1."""
    body = surfaces.format_request_changes_review(
        model_prose=(
            "## Pull request overview\n\n"
            "Reviewed resolution.rs and the freshness test.\n\n"
            "```mermaid\nsequenceDiagram\n  Caller->>Crate: resolve\n```\n"
        ),
        findings=[
            {
                "severity": "HIGH",
                "path": ".github/workflows/opencode-review.yml",
                "line": 1,
                "title": "Coverage evidence failed",
                "problem": "gate failed",
                "root_cause": "sandbox",
                "fix_direction": "fix rustc",
                "regression_test_direction": "rerun",
            }
        ],
        head_sha=HEAD,
        run_id="31951179896",
        run_attempt="1",
        reason="coverage blocked",
        changed_files=ORIGINWEAVE_47_FILES,
    )
    assert "Reviewed resolution.rs and the freshness test." in body
    assert "sequenceDiagram" in body
    assert "## Findings" in body
    assert ".github/workflows/opencode-review.yml:1" not in body
    assert "Review process" in body


def test_format_request_changes_rebuilds_when_model_prose_missing() -> None:
    """Without model prose, structured findings still form a review body."""
    body = surfaces.format_request_changes_review(
        model_prose="",
        findings=[
            {
                "severity": "P1",
                "path": "crates/originweave-destination/src/resolution.rs",
                "line": 12,
                "title": "Stale snapshot",
            }
        ],
        head_sha=HEAD,
        run_id="1",
        run_attempt="1",
    )
    assert "## Verdict" in body
    assert "crates/originweave-destination/src/resolution.rs:12" in body


def test_cli_extract_and_format_request_changes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Workflow CLIs keep model prose and emit a status-safe comment separately."""
    model = tmp_path / "model.md"
    model.write_text(
        "## Verdict\n\nREQUEST_CHANGES\n\nRelated PRs: none\n"
        "<!-- opencode-review-gate head_sha=h run_id=1 run_attempt=1 -->\n",
        encoding="utf-8",
    )
    findings = tmp_path / "findings.json"
    findings.write_text(
        '[{"severity":"HIGH","path":"crates/demo/src/lib.rs","line":4,"title":"Bug"}]',
        encoding="utf-8",
    )
    changed = tmp_path / "changed.txt"
    changed.write_text("crates/demo/src/lib.rs\n", encoding="utf-8")
    assert surfaces.main(["extract-prose", "--model-body-file", str(model)]) == 0
    assert "Related PRs: none" in capsys.readouterr().out
    assert (
        surfaces.main(
            [
                "format-request-changes",
                "--head-sha",
                HEAD,
                "--run-id",
                "1",
                "--run-attempt",
                "1",
                "--model-body-file",
                str(model),
                "--findings-json-file",
                str(findings),
                "--changed-files-file",
                str(changed),
                "--reason",
                "bug",
            ]
        )
        == 0
    )
    rendered = capsys.readouterr().out
    assert "Related PRs: none" in rendered
    assert "crates/demo/src/lib.rs:4" in rendered
    assert (
        surfaces.main(
            [
                "build-status",
                "--result",
                "REQUEST_CHANGES",
                "--head-sha",
                HEAD,
                "--run-id",
                "1",
                "--run-attempt",
                "1",
                "--coverage-result",
                "failure",
                "--model-pool-outcome",
                "success",
                "--verdict",
                "REQUEST_CHANGES",
                "--formal-review-url",
                "https://github.com/ContextualWisdomLab/OriginWeave/pull/47#pullrequestreview-1",
            ]
        )
        == 0
    )
    status = capsys.readouterr().out
    assert "## Findings" not in status
    assert "Model pool: `success`" in status
    assert "Verdict: `REQUEST_CHANGES`" in status
    assert "pullrequestreview-1" in status


def test_central_workflow_line_one_kept_when_that_file_changed() -> None:
    """A real edit to the central workflow may cite that file, including line 1."""
    body = surfaces.format_request_changes_review(
        model_prose="Inspected `.github/workflows/opencode-review.yml:1`.\n",
        findings=[
            {
                "path": ".github/workflows/opencode-review.yml",
                "line": 1,
                "title": "Workflow contract",
            }
        ],
        head_sha=HEAD,
        run_id="1",
        run_attempt="1",
        changed_files=[".github/workflows/opencode-review.yml"],
    )
    assert ".github/workflows/opencode-review.yml:1" in body


def test_format_request_changes_keeps_existing_findings_heading() -> None:
    """Structured findings append under an existing Findings heading."""
    body = surfaces.format_request_changes_review(
        model_prose="## Findings\n\nModel already started the findings list.\n",
        structured_findings="### 1. HIGH crates/demo/src/lib.rs:3 - Extra",
        head_sha=HEAD,
        run_id="1",
        run_attempt="1",
    )
    assert body.count("## Findings") == 1
    assert "Model already started the findings list." in body
    assert "crates/demo/src/lib.rs:3" in body


def test_format_request_changes_skips_duplicate_identity_and_string_findings() -> None:
    """Already-rendered identity/reason lines are not duplicated."""
    prose = (
        "## Verdict\n\nREQUEST_CHANGES\n\n"
        f"- Head SHA: `{HEAD}`\n"
        "- Reason: already stated\n"
    )
    body = surfaces.format_request_changes_review(
        model_prose=prose,
        structured_findings="### 1. HIGH crates/demo/src/lib.rs:2 - Bug",
        head_sha=HEAD,
        run_id="1",
        run_attempt="1",
        reason="already stated",
    )
    assert body.count(f"- Head SHA: `{HEAD}`") == 1
    assert body.count("- Reason: already stated") == 1
    assert "crates/demo/src/lib.rs:2" in body


def test_format_request_changes_cli_handles_object_findings_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A non-list findings document is ignored instead of crashing publish."""
    findings = tmp_path / "findings.json"
    findings.write_text('{"nope": true}', encoding="utf-8")
    assert (
        surfaces.main(
            [
                "format-request-changes",
                "--head-sha",
                HEAD,
                "--run-id",
                "1",
                "--run-attempt",
                "1",
                "--findings-json-file",
                str(findings),
            ]
        )
        == 0
    )
    assert "## Verdict" in capsys.readouterr().out
    assert (
        surfaces.main(
            [
                "format-request-changes",
                "--head-sha",
                HEAD,
                "--run-id",
                "1",
                "--run-attempt",
                "1",
            ]
        )
        == 0
    )
    assert "REQUEST_CHANGES" in capsys.readouterr().out


def test_format_structured_findings_skips_non_mappings() -> None:
    """Non-object findings are ignored so a bad control array cannot crash publish."""
    assert surfaces.format_structured_findings(["skip", 1]) == ""


def test_publisher_workflow_cannot_replace_review_with_coverage_finding() -> None:
    """The #47 publisher shape — coverage REQUEST_CHANGES as the whole review — is gone."""
    workflow = Path(".github/workflows/opencode-review-dispatch.yml").read_text(
        encoding="utf-8"
    )
    assert "publish_fallback_diff_review" in workflow
    assert "opencode_review_surfaces.py build-status" in workflow
    assert "opencode_review_surfaces.py build-fallback-review" in workflow
    assert ".github/workflows/opencode-review.yml:1" not in workflow
    coverage_fn = workflow.split("request_changes_for_coverage_evidence_failure()", 1)[1]
    coverage_fn = coverage_fn.split("create_pull_review_with_payload()", 1)[0]
    assert "create_pull_review" not in coverage_fn
    assert "update_review_overview" in coverage_fn
    assert 'update_review_overview "COVERAGE_BLOCKED"' in coverage_fn
    fallback_fn = workflow.split("publish_fallback_diff_review()", 1)[1]
    fallback_fn = fallback_fn.split("request_changes_for_coverage_evidence_failure()", 1)[0]
    assert "create_pull_review" in fallback_fn
    assert "request_changes_for_coverage_evidence_failure" in fallback_fn
    assert fallback_fn.index("create_pull_review") < fallback_fn.index(
        "request_changes_for_coverage_evidence_failure"
    )
    model_skip = workflow.split("if [ \"$opencode_review_outcome\" != \"success\" ]; then", 1)[1]
    model_skip = model_skip.split("selected_review_output_file=", 1)[0]
    assert "publish_fallback_diff_review" in model_skip
