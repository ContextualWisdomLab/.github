import json

from scripts.ci import opencode_review_normalize_output as norm


FULL_SUMMARY = """\
Approval sufficiency: affirmative evidence supported approval beyond the absence of blockers.
Verification posture: CodeGraph inspected scripts/ci/example.py on the current head.
Linter/static: actionlint and bash -n passed.
TDD/regression: pytest covered the changed behavior.
Coverage: coverage execution evidence proves 100% test coverage.
Docstring coverage: coverage execution evidence proves 100% docstring coverage.
DAG: Mermaid DAG was checked.
PoC/execution: local PoC executed successfully.
DDD/domain: domain invariants were reviewed.
CDD/context: context evidence was reviewed.
Similar issues: no related regressions were found.
Claim/concept check: external claims were verified.
Standards search: relevant standards were searched.
Compatibility/convention: compatibility and naming conventions were checked.
Breaking-change/backcompat: no breaking change was found.
Performance: performance risk was checked.
Developer experience: developer workflow impact was checked.
User experience: user, operator, API, CLI, docs, status-check, and workflow-reader impact was checked.
Visual/DOM: no web UI surface was present, so non-web interaction evidence was checked instead.
Accessibility/i18n: accessibility and localization impact was checked.
Supply-chain/license: supply-chain and license risk was checked.
Packaging: package and build contracts were checked.
Security/privacy: security impact was checked.
"""


def control(**overrides):
    value = {
        "head_sha": "head",
        "run_id": "run",
        "run_attempt": "attempt",
        "result": "APPROVE",
        "reason": "scripts/ci/example.py is source-backed.",
        "summary": FULL_SUMMARY,
        "findings": [],
    }
    value.update(overrides)
    return value


def finding(**overrides):
    value = {
        "path": "scripts/ci/example.py",
        "line": 7,
        "severity": "HIGH",
        "title": "Broken invariant",
        "problem": "The invariant is not preserved.",
        "root_cause": "The branch omits the guard.",
        "fix_direction": "Restore the guard.",
        "regression_test_direction": "Add a focused regression test.",
        "suggested_diff": "- old\n+ new",
    }
    value.update(overrides)
    return value


def test_structural_review_detection_accepts_phrases_patterns_and_clean_text():
    assert norm.admits_missing_structural_review("No changed files", "")
    assert norm.admits_missing_structural_review("Could not inspect the changed files", "")
    assert norm.admits_missing_structural_review("", "Source files were not inspected")
    assert norm.admits_missing_structural_review("structural exploration was not possible", "summary")
    assert norm.admits_missing_structural_review("reason", "evidence was truncated")
    assert norm.admits_missing_structural_review("", "structural analysis was incomplete")
    assert norm.admits_missing_structural_review("", "zero changed files")
    assert norm.admits_missing_structural_review("STRUCTURAL EXPLORATION WAS NOT POSSIBLE", "")
    assert not norm.admits_missing_structural_review("scripts/ci/example.py checked", "")


def test_changed_file_and_verification_posture_detection():
    assert norm.mentions_changed_file_evidence("README.md", "")
    assert norm.mentions_changed_file_evidence("scripts/ci/example.py", "")
    assert norm.mentions_changed_file_evidence("", "Checked some_script.sh")
    assert norm.mentions_changed_file_evidence("Modified a.ts", "and b.tsx")
    assert norm.mentions_changed_file_evidence("updated package.json", "")
    assert norm.mentions_changed_file_evidence("checked Dockerfile", "")
    assert norm.mentions_changed_file_evidence("reviewed AGENTS.md", "")
    assert norm.mentions_changed_file_evidence("The file dir/sub/app.js is good", "")
    assert norm.mentions_changed_file_evidence("Fixed bug in module.rs", "")
    assert not norm.mentions_changed_file_evidence("No path here", "")
    assert not norm.mentions_changed_file_evidence("Security/privacy: checked", "")
    assert not norm.mentions_changed_file_evidence("changed some code", "no file listed here")
    assert not norm.mentions_changed_file_evidence("invalid.ext", "not a valid extension")
    assert norm.mentions_verification_posture("", FULL_SUMMARY)
    assert not norm.mentions_verification_posture("", FULL_SUMMARY.replace("CodeGraph", "graph"))


def test_actual_changed_file_detection_prefers_current_head_file_list(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENCODE_CHANGED_FILES_FILE", raising=False)
    assert norm.current_changed_files() == set()
    assert norm.mentions_actual_changed_file("scripts/ci/example.py", "")

    changed_files = tmp_path / "changed-files.txt"
    changed_files.write_text(
        "\n".join(
            [
                ".github/workflows/opencode-review.yml",
                "scripts/ci/opencode_review_normalize_output.py",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))

    assert norm.current_changed_files() == {
        ".github/workflows/opencode-review.yml",
        "scripts/ci/opencode_review_normalize_output.py",
    }
    assert norm.mentions_actual_changed_file(
        "Reviewed .github/workflows/opencode-review.yml.",
        "",
    )
    assert norm.mentions_actual_changed_file(
        "",
        "Reviewed scripts/ci/opencode_review_normalize_output.py.",
    )
    assert not norm.mentions_actual_changed_file(
        "Reviewed README.md.",
        "Ran scripts/ci/test_strix_quick_gate.sh.",
    )

    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(tmp_path / "missing.txt"))
    assert norm.current_changed_files() == set()
    assert norm.mentions_actual_changed_file("scripts/ci/example.py", "")


def test_preferred_review_language_handles_unreadable_and_unknown_evidence(tmp_path, monkeypatch):
    evidence = tmp_path / "evidence.md"
    evidence.write_text(
        "## Review language evidence\nPreferred review language: `Spanish`\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))

    assert norm.preferred_review_language() is None

    monkeypatch.setattr(norm, "read_text_lossy", lambda _path: None)
    assert norm.preferred_review_language() is None


def test_changed_file_kind_contradictions_are_rejected(tmp_path, monkeypatch):
    changed_files = tmp_path / "changed-files.txt"
    changed_files.write_text(
        "\n".join(
            [
                ".github/workflows/opencode-review.yml",
                "scripts/ci/test_strix_quick_gate.sh",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))

    false_summary = (
        FULL_SUMMARY.replace("scripts/ci/example.py", ".github/workflows/opencode-review.yml")
        .replace(
            "Linter/static: actionlint and bash -n passed.",
            "Linter/static: Not applicable (no source files changed).",
        )
        .replace(
            "TDD/regression: pytest covered the changed behavior.",
            "TDD/regression: Not applicable (no test files changed).",
        )
        .replace(
            "PoC/execution: local PoC executed successfully.",
            "PoC/execution: Not applicable (no executable changes).",
        )
    )
    approval = control(
        reason="No blockers found after inspecting .github/workflows/opencode-review.yml.",
        summary=false_summary,
    )

    assert norm.changed_file_is_source_like(".github/workflows/opencode-review.yml")
    assert norm.changed_file_is_source_like("Dockerfile")
    assert norm.changed_file_is_source_like("src/app.py")
    assert not norm.changed_file_is_source_like("README.md")
    assert norm.changed_file_is_test_like("scripts/ci/test_strix_quick_gate.sh")
    assert norm.changed_file_is_test_like("tests/README.md")
    assert norm.contradicts_changed_file_kinds(approval["reason"], approval["summary"])
    assert norm.valid_control(
        approval,
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    ) is None

    path = tmp_path / "approval.json"
    path.write_text(json.dumps(approval), encoding="utf-8")
    assert norm.check_structural_approval(path) == 4

    changed_files.write_text("scripts/deploy.sh\n", encoding="utf-8")
    assert norm.contradicts_changed_file_kinds(
        "Reviewed scripts/deploy.sh.",
        "PoC/execution: Not applicable (no executable changes).",
    )

    changed_files.write_text("tests/README.md\n", encoding="utf-8")
    assert norm.contradicts_changed_file_kinds(
        "Reviewed tests/README.md.",
        "TDD/regression: Not applicable (no tests changed).",
    )

    changed_files.write_text("scripts/deploy.sh\n", encoding="utf-8")
    assert not norm.contradicts_changed_file_kinds(
        "Reviewed scripts/deploy.sh.",
        "PoC/execution: bash -n scripts/deploy.sh passed.",
    )

    monkeypatch.delenv("OPENCODE_CHANGED_FILES_FILE")
    assert not norm.contradicts_changed_file_kinds(approval["reason"], approval["summary"])


def test_material_changed_file_scope_rejects_trivial_string_approval(tmp_path, monkeypatch):
    changed_files = tmp_path / "changed-files.txt"
    changed_files.write_text(
        "\n".join(
            [
                ".github/workflows/strix.yml",
                "scripts/ci/test_strix_quick_gate.sh",
                "tests/test_opencode_agent_contract.py",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))

    summary = (
        "Approval sufficiency: The change is a simple typo fix in a string with no functional impact. "
        "Verification posture: No verification needed for a string typo fix. "
        "Linter/static: The file was not checked by a linter but the change in a string is safe. "
        "TDD/regression: No tests are needed for a string change.\n"
        + FULL_SUMMARY.replace("scripts/ci/example.py", ".github/workflows/strix.yml")
    )
    approval = control(
        reason="Typo fix with no functional impact",
        summary=summary,
    )

    assert norm.changed_file_is_material(".github/workflows/strix.yml")
    assert norm.changed_file_is_material("scripts/ci/test_strix_quick_gate.sh")
    assert norm.changed_file_is_material("tests/test_opencode_agent_contract.py")
    assert not norm.changed_file_is_material("README.md")
    assert norm.contradicts_material_changed_file_scope(
        approval["reason"],
        approval["summary"],
    )
    assert norm.valid_control(
        approval,
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    ) is None

    path = tmp_path / "approval.json"
    path.write_text(json.dumps(approval), encoding="utf-8")
    assert norm.check_structural_approval(path) == 4

    changed_files.write_text("README.md\n", encoding="utf-8")
    assert not norm.contradicts_material_changed_file_scope(
        approval["reason"],
        approval["summary"],
    )


def test_material_changed_file_scope_rejects_false_documentation_typo_reason(tmp_path, monkeypatch):
    changed_files = tmp_path / "changed-files.txt"
    changed_files.write_text(
        "\n".join(
            [
                ".github/workflows/opencode-review.yml",
                "scripts/ci/run_opencode_review_model_pool.sh",
                "tests/test_opencode_agent_contract.py",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))

    approval = control(
        reason="Typo fix in documentation string",
        summary=FULL_SUMMARY.replace(
            "scripts/ci/example.py",
            "scripts/ci/run_opencode_review_model_pool.sh",
        ),
    )

    assert norm.contradicts_material_changed_file_scope(
        approval["reason"],
        approval["summary"],
    )
    assert norm.valid_control(
        approval,
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    ) is None

    path = tmp_path / "approval.json"
    path.write_text(json.dumps(approval), encoding="utf-8")
    assert norm.check_structural_approval(path) == 4


def test_label_and_full_coverage_detection():
    combined = FULL_SUMMARY.casefold()
    assert "100%" in norm.label_section(combined, "coverage:")
    assert norm.label_section(combined, "missing:") == ""
    text_coverage = "performance: FAST docstring coverage: 100% something else coverage: 100%"
    assert norm.label_section(text_coverage, "performance:") == " FAST "
    assert norm.mentions_full_coverage("", FULL_SUMMARY)
    no_source_summary = FULL_SUMMARY.replace(
        "coverage execution evidence proves 100% test coverage",
        "coverage execution evidence reports test coverage as not applicable because no supported changed source files or package manifests were found",
    ).replace(
        "coverage execution evidence proves 100% docstring coverage",
        "coverage execution evidence reports docstring coverage as not applicable because no supported changed source files or package manifests were found",
    )
    assert norm.mentions_full_coverage("", no_source_summary)
    suite_passed_summary = FULL_SUMMARY.replace(
        "coverage execution evidence proves 100% test coverage",
        "coverage execution evidence reports supported repository test suites passed",
    ).replace(
        "coverage execution evidence proves 100% docstring coverage",
        "coverage execution evidence reports configured repository docstring gates passed or docstring coverage was advisory",
    )
    assert norm.mentions_full_coverage("", suite_passed_summary)
    advisory_summary = FULL_SUMMARY.replace(
        "coverage execution evidence proves 100% docstring coverage",
        "coverage execution evidence reports docstring coverage was advisory",
    )
    assert norm.mentions_full_coverage("", advisory_summary)
    assert not norm.mentions_full_coverage("", "")
    assert not norm.mentions_full_coverage("", FULL_SUMMARY.replace("100%", "99%", 1))
    assert not norm.mentions_full_coverage("", FULL_SUMMARY.replace("100%", "not applicable", 1))
    assert not norm.mentions_full_coverage(
        "",
        FULL_SUMMARY.replace(
            "coverage execution evidence proves 100% test coverage",
            "coverage execution evidence did not prove 100% test coverage",
        ),
    )
    assert norm.evidence_coverage_mode(
        "- Result: PASS\n"
        "- Test coverage: not applicable (no supported source files or package manifests)\n"
    ) is None
    assert not norm.mentions_full_coverage(
        "",
        FULL_SUMMARY.replace("coverage execution evidence", "measured evidence", 1),
    )
    assert not norm.mentions_full_coverage("", FULL_SUMMARY.replace("proves 100%", "not proven"))


def test_check_structural_approval_rejects_invalid_or_unsafe_approvals(tmp_path, monkeypatch):
    assert norm.check_structural_approval(tmp_path / "missing.json") == 65
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{", encoding="utf-8")
    assert norm.check_structural_approval(bad_json) == 65
    non_dict = tmp_path / "list.json"
    non_dict.write_text("[]", encoding="utf-8")
    assert norm.check_structural_approval(non_dict) == 4

    cases = [
        control(reason="No changed files"),
        control(reason="No source path", summary=FULL_SUMMARY.replace("scripts/ci/example.py", "source file")),
        control(summary="scripts/ci/example.py\nCoverage: coverage execution evidence proves 100%."),
        control(summary=FULL_SUMMARY.replace("100%", "99%", 1)),
        control(
            reason="scripts/ci/example.py checked.",
            summary=(
                FULL_SUMMARY
                + "\nOpenCode model attempts did not emit a usable current-head control block, "
                "so the approval gate used deterministic current-head evidence instead of model prose."
            ),
        ),
    ]
    for index, value in enumerate(cases):
        path = tmp_path / f"case-{index}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        assert norm.check_structural_approval(path) == 4

    changed_files = tmp_path / "changed-files.txt"
    changed_files.write_text("tests/actual_changed_file.py\n", encoding="utf-8")
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))
    wrong_file = tmp_path / "wrong-file.json"
    wrong_file.write_text(json.dumps(control()), encoding="utf-8")
    assert norm.check_structural_approval(wrong_file) == 4
    monkeypatch.delenv("OPENCODE_CHANGED_FILES_FILE")

    request_changes = tmp_path / "request.json"
    request_changes.write_text(json.dumps(control(result="REQUEST_CHANGES")), encoding="utf-8")
    assert norm.check_structural_approval(request_changes) == 0

    generic_deflection = tmp_path / "generic-deflection.json"
    generic_deflection.write_text(
        json.dumps(
            control(
                result="REQUEST_CHANGES",
                summary=(
                    "The review could not map each failed check to exact local source lines "
                    "from the available logs, so it needs better failed-check evidence."
                ),
                findings=[
                    finding(
                        title="Generic failed-check deflection",
                        problem="The failed-check diagnosis did not produce source-backed findings.",
                    )
                ],
            )
        ),
        encoding="utf-8",
    )
    assert norm.check_structural_approval(generic_deflection) == 4


def test_valid_control_filters_shape_head_and_review_contract():
    kwargs = {
        "expected_head_sha": "head",
        "expected_run_id": "run",
        "expected_run_attempt": "attempt",
    }
    assert norm.valid_control([], **kwargs) is None
    assert norm.valid_control(control(head_sha="other"), **kwargs) is None
    assert norm.valid_control(control(run_id="other"), **kwargs) is None
    assert norm.valid_control(control(run_attempt="other"), **kwargs) is None
    assert norm.valid_control(control(result="COMMENT"), **kwargs) is None
    assert norm.valid_control(control(reason=""), **kwargs) is None
    assert norm.valid_control(control(summary=""), **kwargs) is None
    assert norm.valid_control(control(findings="bad"), **kwargs) is None
    assert norm.valid_control(control(findings=[finding()]), **kwargs) is None
    assert norm.valid_control(control(result="REQUEST_CHANGES", findings=[]), **kwargs) is None
    assert norm.valid_control(control(reason="No changed files"), **kwargs) is None
    assert norm.valid_control(
        control(reason="No source path", summary=FULL_SUMMARY.replace("scripts/ci/example.py", "source file")),
        **kwargs,
    ) is None
    assert norm.valid_control(control(summary="scripts/ci/example.py"), **kwargs) is None
    assert norm.valid_control(control(summary=FULL_SUMMARY.replace("100%", "99%", 1)), **kwargs) is None
    assert (
        norm.valid_control(
            control(
                summary=(
                    FULL_SUMMARY
                    + "\nModel outcomes: primary=failed, fallback=failed, "
                    "second_fallback=failed, catalog_fallback=failed."
                )
            ),
            **kwargs,
        )
        is None
    )

    request = control(result="REQUEST_CHANGES", findings=[finding()])
    assert norm.valid_control(dict(request, findings=["bad"]), **kwargs) is None
    assert norm.valid_control(dict(request, findings=[finding(line=True)]), **kwargs) is None
    assert norm.valid_control(dict(request, findings=[finding(line=0)]), **kwargs) is None
    assert norm.valid_control(dict(request, findings=[finding(line="10")]), **kwargs) is None
    assert norm.valid_control(dict(request, findings=[finding(title="")]), **kwargs) is None
    invalid_finding = finding()
    invalid_finding.pop("severity")
    assert norm.valid_control(dict(request, findings=[invalid_finding]), **kwargs) is None
    assert (
        norm.valid_control(
            dict(
                request,
                summary=(
                    "The review could not map each failed check to exact local source lines "
                    "from the available logs, so it needs better failed-check evidence."
                ),
            ),
            **kwargs,
        )
        is None
    )
    assert norm.valid_control(request, **kwargs)["result"] == "REQUEST_CHANGES"

    approve_without_findings_key = control()
    approve_without_findings_key.pop("findings")
    assert norm.valid_control(approve_without_findings_key, **kwargs)["findings"] == []


def test_valid_control_repairs_approval_summary_from_bounded_evidence(tmp_path, monkeypatch):
    evidence = tmp_path / "bounded-review-evidence.md"
    evidence.write_text(
        """\
# OpenCode bounded PR review evidence

## CodeGraph evidence

The workflow initialized CodeGraph before this evidence file was built.

## Coverage execution evidence

# Coverage Evidence

## Coverage Decision

- Result: PASS
- Test coverage: 100%
- Docstring coverage: 100%

## Changed files

M\tscripts/ci/example.py
A\t.github/workflows/opencode-review.yml

## Changed file history evidence
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))

    repaired = norm.valid_control(
        control(reason="Current-head review completed.", summary="No blockers were found."),
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    )

    assert repaired is not None
    assert "scripts/ci/example.py" in repaired["summary"]
    assert "CodeGraph" in repaired["summary"]
    assert "No blockers were found" not in repaired["summary"]
    assert norm.mentions_verification_posture(repaired["reason"], repaired["summary"])
    assert norm.mentions_full_coverage(repaired["reason"], repaired["summary"])


def test_valid_control_repairs_summary_from_invalid_utf8_evidence(tmp_path, monkeypatch):
    evidence = tmp_path / "bounded-review-evidence.md"
    evidence.write_bytes(
        b"# OpenCode bounded PR review evidence\n\n"
        b"\xea invalid byte from model transcript\n\n"
        b"## Coverage execution evidence\n\n"
        b"# Coverage Evidence\n\n"
        b"## Coverage Decision\n\n"
        b"- Result: PASS\n"
        b"- Test coverage: 100%\n"
        b"- Docstring coverage: 100%\n\n"
        b"## Changed files\n\n"
        b"M\tscripts/ci/opencode_review_normalize_output.py\n"
    )
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))

    repaired = norm.valid_control(
        control(reason="Current-head review completed.", summary="No blockers were found."),
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    )

    assert repaired is not None
    assert "scripts/ci/opencode_review_normalize_output.py" in repaired["summary"]
    assert "No blockers were found" not in repaired["summary"]
    assert norm.mentions_verification_posture(repaired["reason"], repaired["summary"])
    assert norm.mentions_full_coverage(repaired["reason"], repaired["summary"])


def test_valid_control_repairs_fragile_approval_reason_from_bounded_evidence(tmp_path, monkeypatch):
    evidence = tmp_path / "bounded-review-evidence.md"
    evidence.write_text(
        """\
# OpenCode bounded PR review evidence

## Review language evidence

- Preferred review language: `English`

## Coverage execution evidence

### Coverage measurement

- Result: PASS
- Reason: no supported changed source files or package manifests were found, so coverage measurement is not applicable for this head.

## Coverage Decision

- Result: PASS
- Test coverage: not applicable (no supported changed source files or package manifests)
- Docstring coverage: not applicable (no supported changed source files or package manifests)

## Changed files

M\t.github/workflows/r.yml

## Changed file history evidence
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_EVIDENCE_FILE", str(evidence))
    monkeypatch.delenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", raising=False)
    changed_files = tmp_path / "changed-files.txt"
    changed_files.write_text(".github/workflows/r.yml\n", encoding="utf-8")
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))

    repaired = norm.valid_control(
        control(
            reason="Dependency version bump with no source changes",
            summary=(
                "Approval sufficiency: Dependency version bump with no source changes. "
                "Verification posture: No verification needed for workflow-only updates. "
                "Linter/static: Not applicable. TDD/regression: Not applicable. "
                "Coverage: Not applicable. Docstring coverage: Not applicable. "
                "DAG: Not applicable. PoC/execution: Not applicable. "
                "DDD/domain: Not applicable. CDD/context: Not applicable. "
                "Similar issues: Not applicable. Claim/concept check: Not applicable. "
                "Standards search: Not applicable. Compatibility/convention: Not applicable. "
                "Breaking-change/backcompat: Not applicable. Performance: Not applicable. "
                "Developer experience: Not applicable. User experience: Not applicable. "
                "Visual/DOM: Not applicable. Accessibility/i18n: Not applicable. "
                "Supply-chain/license: Not applicable. Packaging: Not applicable. "
                "Security/privacy: Not applicable."
            ),
        ),
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    )

    assert repaired is not None
    assert ".github/workflows/r.yml" in repaired["reason"]
    assert "no source changes" not in repaired["reason"].casefold()
    assert "no verification needed" not in repaired["summary"].casefold()
    assert norm.mentions_actual_changed_file(repaired["reason"], repaired["summary"])
    assert norm.mentions_full_coverage(repaired["reason"], repaired["summary"])


def test_valid_control_repair_overrides_earlier_invalid_coverage_labels(tmp_path, monkeypatch):
    evidence = tmp_path / "bounded-review-evidence.md"
    evidence.write_text(
        """\
# OpenCode bounded PR review evidence

## Coverage execution evidence

# Coverage Evidence

## Coverage Decision

- Result: PASS
- Test coverage: 100%
- Docstring coverage: 100%

## Changed files

M\tscripts/ci/opencode_review_normalize_output.py
M\ttests/test_opencode_review_normalize_output.py
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))

    repaired = norm.valid_control(
        control(
            reason="No blockers found in the PR changes.",
            summary="""\
Inspected the PR changes and found no actionable blockers.
Verification posture: CodeGraph was available, but the model summarized too broadly.
Linter/static: Not applicable.
TDD/regression: Not applicable.
Coverage: Not applicable.
Docstring coverage: Not applicable.
DAG: Not applicable.
PoC/execution: Not applicable.
DDD/domain: Not applicable.
CDD/context: Not applicable.
Similar issues: Not applicable.
Claim/concept check: Not applicable.
Standards search: Not applicable.
Compatibility/convention: Not applicable.
Breaking-change/backcompat: Not applicable.
Performance: Not applicable.
Developer experience: Not applicable.
User experience: Not applicable.
Security/privacy: Not applicable.
""",
        ),
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    )

    assert repaired is not None
    assert "scripts/ci/opencode_review_normalize_output.py" in repaired["summary"]
    assert "Not applicable." not in repaired["summary"]
    assert norm.mentions_full_coverage(repaired["reason"], repaired["summary"])


def test_valid_control_repair_drops_contradictory_changed_file_kind_claims(tmp_path, monkeypatch):
    evidence = tmp_path / "bounded-review-evidence.md"
    changed_files = tmp_path / "changed-files.txt"
    evidence.write_text(
        """\
# OpenCode bounded PR review evidence

## Coverage execution evidence

# Coverage Evidence

## Coverage Decision

- Result: PASS
- Test coverage: 100%
- Docstring coverage: 100%

## Changed files

M\tapps/desktop/src/App.tsx
M\tapps/desktop/src/App.test.tsx
""",
        encoding="utf-8",
    )
    changed_files.write_text(
        "apps/desktop/src/App.tsx\napps/desktop/src/App.test.tsx\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))

    repaired = norm.valid_control(
        control(
            reason="No blocking issues found in the inspected files.",
            summary="""\
Inspected changes in PR #475. No blocking issues were found.
Verification posture: CodeGraph was mentioned.
Linter/static: Not applicable (no linter changes).
TDD/regression: Not applicable (no test changes).
Coverage: Not applicable (no coverage changes).
Docstring coverage: Not applicable (no docstring changes).
DAG: Not applicable (no DAG changes).
PoC/execution: Not applicable (no executable changes).
DDD/domain: Not applicable.
CDD/context: Not applicable.
Similar issues: Not applicable.
Claim/concept check: Not applicable.
Standards search: Not applicable.
Compatibility/convention: Not applicable.
Breaking-change/backcompat: Not applicable.
Performance: Not applicable.
Developer experience: Not applicable.
User experience: Not applicable.
Security/privacy: Not applicable.
""",
        ),
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    )

    assert repaired is not None
    assert "apps/desktop/src/App.tsx" in repaired["summary"]
    assert "no executable changes" not in repaired["summary"]
    assert "no test changes" not in repaired["summary"]
    assert not norm.contradicts_changed_file_kinds(repaired["reason"], repaired["summary"])


def test_valid_control_repair_drops_material_trivialization(tmp_path, monkeypatch):
    evidence = tmp_path / "bounded-review-evidence.md"
    changed_files = tmp_path / "changed-files.txt"
    evidence.write_text(
        """\
# OpenCode bounded PR review evidence

## Coverage execution evidence

# Coverage Evidence

## Coverage Decision

- Result: PASS
- Test coverage: 100%
- Docstring coverage: 100%

## Changed files

M\t.github/workflows/strix.yml
M\tscripts/ci/test_strix_quick_gate.sh
""",
        encoding="utf-8",
    )
    changed_files.write_text(
        ".github/workflows/strix.yml\nscripts/ci/test_strix_quick_gate.sh\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))

    repaired = norm.valid_control(
        control(
            reason="Current-head evidence was reviewed.",
            summary=(
                "The change is a simple typo fix in a string with no functional impact. "
                "No tests are needed for a string change."
            ),
        ),
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    )

    assert repaired is not None
    assert ".github/workflows/strix.yml" in repaired["summary"]
    assert "simple typo fix" not in repaired["summary"]
    assert "no tests are needed" not in repaired["summary"].casefold()
    assert not norm.contradicts_material_changed_file_scope(
        repaired["reason"],
        repaired["summary"],
    )


def test_valid_control_does_not_repair_unsafe_or_unproven_approval(tmp_path, monkeypatch):
    evidence = tmp_path / "bounded-review-evidence.md"
    evidence.write_text(
        """\
# OpenCode bounded PR review evidence

## Coverage execution evidence

## Coverage Decision

- Result: FAIL
- Test coverage: not proven 100%
- Docstring coverage: not proven 100%

## Changed files

M\tscripts/ci/example.py
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))
    kwargs = {
        "expected_head_sha": "head",
        "expected_run_id": "run",
        "expected_run_attempt": "attempt",
    }

    assert norm.valid_control(control(reason="No changed files"), **kwargs) is None
    assert norm.valid_control(control(summary="No blockers were found."), **kwargs) is None


def test_approval_repair_evidence_helpers_cover_edge_cases(tmp_path, monkeypatch):
    assert norm.section_between_markers("## Other\nbody", "Changed files") == ""
    assert norm.changed_files_from_evidence(
        """\
## Changed files


# comment
M\tscripts/ci/example.py
M\tscripts/ci/example.py
A\t[tree truncated after 5 paths]
M\tnot a valid path
A\t.github/workflows/opencode-review.yml
M\ttests/test_opencode_review_normalize_output.py
M\tscripts/ci/pr_review_merge_scheduler.py
M\topencode.jsonc
M\tREADME.md
## Next
"""
    ) == [
        "scripts/ci/example.py",
        ".github/workflows/opencode-review.yml",
        "tests/test_opencode_review_normalize_output.py",
        "scripts/ci/pr_review_merge_scheduler.py",
        "opencode.jsonc",
        "README.md",
    ]
    assert norm.changed_files_from_evidence(
        """\
## Changed files

- .jules/sentinel.md
- frontend/src/components/EmailDetail.test.tsx
- [tree truncated after 5 paths]
"""
    ) == [
        ".jules/sentinel.md",
        "frontend/src/components/EmailDetail.test.tsx",
    ]

    summary = norm.build_approval_repair_summary(
        "No blockers were found.",
        """\
## Coverage execution evidence
- Result: PASS
- Test coverage: 100%
- Docstring coverage: 100%
## Changed files
M\tscripts/ci/example.py
M\t.github/workflows/opencode-review.yml
M\ttests/test_opencode_review_normalize_output.py
M\tscripts/ci/pr_review_merge_scheduler.py
M\topencode.jsonc
M\tREADME.md
""",
    )
    assert summary is not None
    assert "and 1 more" in summary

    no_source_summary = norm.build_approval_repair_summary(
        "No blockers were found.",
        """\
## Coverage execution evidence
- Result: PASS
- Test coverage: not applicable (no supported changed source files or package manifests)
- Docstring coverage: not applicable (no supported changed source files or package manifests)
## Changed files
M\tscripts/ci/example.py
""",
    )
    assert no_source_summary is not None
    assert "test coverage as not applicable" in no_source_summary
    assert "docstring coverage as not applicable" in no_source_summary
    assert norm.mentions_full_coverage("", no_source_summary)

    suite_passed_summary = norm.build_approval_repair_summary(
        "No blockers were found.",
        """\
## Coverage execution evidence
- Result: PASS
- Test evidence: supported repository test suites passed
- Docstring evidence: configured repository docstring gates passed or docstring coverage was advisory
## Changed files
M\tscripts/ci/example.py
""",
    )
    assert suite_passed_summary is not None
    assert "supported repository test suites passed" in suite_passed_summary
    assert "docstring coverage was advisory" in suite_passed_summary
    assert norm.mentions_full_coverage("", suite_passed_summary)

    evidence = tmp_path / "bounded-review-evidence.md"
    evidence.write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))
    original_read_text = norm.Path.read_text

    def raise_for_evidence(path, *args, **kwargs):
        if path == evidence:
            raise OSError("cannot read evidence")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(norm.Path, "read_text", raise_for_evidence)
    assert norm.repair_approval_summary("reason", "summary") == "summary"


def test_approval_language_contract_runs_after_evidence_repair(tmp_path, monkeypatch):
    evidence = tmp_path / "bounded-review-evidence.md"
    evidence.write_text(
        """\
## Review language evidence
Preferred review language: `Korean`
## Coverage execution evidence
- Result: PASS
- Test coverage: not applicable (no supported changed source files or package manifests)
- Docstring coverage: not applicable (no supported changed source files or package manifests)
## Changed files

- .jules/sentinel.md
- frontend/src/components/EmailDetail.test.tsx
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))

    reviewed = norm.valid_control(
        control(
            reason="Terminology alignment and test coverage improvements",
            summary=(
                "Approval sufficiency: Sufficient for terminology alignment. "
                "Verification posture: Verified test changes. "
                "Linter/static: No issues. TDD/regression: Tests updated. "
                "Coverage: Not applicable. Docstring coverage: Not applicable. "
                "DAG: Not applicable. PoC/execution: Tests pass. "
                "DDD/domain: Aligned. CDD/context: Matched PR intent. "
                "Similar issues: None. Claim/concept check: Verified. "
                "Standards search: N/A. Compatibility/convention: Follows patterns. "
                "Breaking-change/backcompat: None. Performance: No impact. "
                "Developer experience: Improved tests. User experience: Consistent terminology. "
                "Visual/DOM: No visual changes. Accessibility/i18n: Maintained. "
                "Supply-chain/license: No changes. Packaging: No changes. Security/privacy: No impact."
            ),
        ),
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    )

    assert reviewed is not None
    assert "한국어 리뷰 언어 계약" in reviewed["summary"]
    assert ".jules/sentinel.md" in reviewed["summary"]


def test_request_changes_still_enforces_korean_language_contract(tmp_path, monkeypatch):
    evidence = tmp_path / "bounded-review-evidence.md"
    evidence.write_text(
        """\
## Review language evidence
Preferred review language: `Korean`
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))

    assert (
        norm.valid_control(
            control(
                result="REQUEST_CHANGES",
                reason="Needs a fix",
                summary="The review found a bug.",
                findings=[finding()],
            ),
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is None
    )


def test_iter_json_objects_extracts_raw_and_embedded_json():
    assert norm.iter_json_objects('{"a": 1}') == [{"a": 1}]
    assert norm.iter_json_objects('prefix {"b": 2} suffix') == [{"b": 2}]
    assert norm.iter_json_objects('prefix {"wrapper": {"control": true}} suffix') == [
        {"wrapper": {"control": True}},
        {"control": True},
    ]
    assert norm.iter_json_objects("prefix {  } suffix") == [{}]
    assert norm.iter_json_objects("prefix {not json}") == []
    assert norm.iter_json_objects('prefix {"bad": } suffix') == []
    assert norm.iter_json_objects("no json here") == []


def test_escapes_html_comment_breakout(tmp_path):
    output = tmp_path / "opencode.txt"
    control_data = control(
        result="REQUEST_CHANGES",
        findings=[
            {
                "path": "test.py",
                "line": 1,
                "severity": "high",
                "title": "Test finding",
                "problem": "--> injected string with < and > and &",
                "root_cause": "test",
                "fix_direction": "test",
                "regression_test_direction": "test",
                "suggested_diff": "test",
            }
        ],
    )
    output.write_text("prefix\n" + json.dumps(control_data) + "\nsuffix", encoding="utf-8")
    assert norm.main(["prog", "head", "run", "attempt", str(output)]) == 0
    text = output.read_text(encoding="utf-8")

    control_block_marker = "<!-- opencode-review-control-v1\n"
    control_block_start = text.find(control_block_marker)
    control_block_end = text.rfind("\n-->")
    assert control_block_start != -1
    assert control_block_end != -1
    assert control_block_start < control_block_end

    # Extract the JSON control block itself to ensure no unescaped `<, >, &` exists.
    control_block_start += len(control_block_marker)
    json_text = text[control_block_start:control_block_end]

    escaped_fragments = ("\\u003c", "\\u003e", "\\u0026")
    raw_comment_breakout_fragments = ("-->", "<", ">", "&")

    assert all(fragment in json_text for fragment in escaped_fragments)
    assert all(fragment not in json_text for fragment in raw_comment_breakout_fragments)

    parsed_control = json.loads(json_text)
    assert parsed_control["findings"][0]["problem"] == "--> injected string with < and > and &"


def test_main_normalizes_valid_output_and_reports_failures(tmp_path, capsys):
    output = tmp_path / "opencode.txt"
    output.write_text("prefix\n" + json.dumps(control()) + "\nsuffix", encoding="utf-8")
    assert norm.main(["prog", "head", "run", "attempt", str(output)]) == 0
    normalized_text = output.read_text(encoding="utf-8")
    assert "opencode-review-control-v1" in normalized_text
    assert "\\u003c" not in normalized_text

    injection_output = tmp_path / "injection.txt"
    injection_control = control()
    injection_control["reason"] = "scripts/ci/example.py is source-backed. <script>alert(1)</script> & <!-- -->"
    injection_output.write_text("prefix\n" + json.dumps(injection_control) + "\nsuffix", encoding="utf-8")
    assert norm.main(["prog", "head", "run", "attempt", str(injection_output)]) == 0
    normalized_injection_text = injection_output.read_text(encoding="utf-8")
    assert "\\u003cscript\\u003ealert(1)\\u003c/script\\u003e \\u0026 \\u003c!-- --\\u003e" in normalized_injection_text

    invalid_utf8 = tmp_path / "invalid-utf8.txt"
    invalid_utf8.write_bytes(b"\xea invalid prefix\n" + json.dumps(control()).encode("utf-8"))
    assert norm.main(["prog", "head", "run", "attempt", str(invalid_utf8)]) == 0
    assert "opencode-review-control-v1" in invalid_utf8.read_text(encoding="utf-8")

    assert norm.main(["prog"]) == 64
    assert "usage:" in capsys.readouterr().err

    assert norm.main(["prog", "head", "run", "attempt", str(tmp_path)]) == 65
    assert "cannot read OpenCode output file" in capsys.readouterr().err

    no_control = tmp_path / "none.txt"
    no_control.write_text("{}", encoding="utf-8")
    assert norm.main(["prog", "head", "run", "attempt", str(no_control)]) == 4
    assert "NO_CONCLUSION" in capsys.readouterr().err

    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps(control()), encoding="utf-8")
    assert norm.main(["prog", "--check-structural-approval", str(approval)]) == 0

    generic_failed_check = tmp_path / "generic-failed-check.json"
    generic_failed_check.write_text(
        json.dumps(
            control(
                result="REQUEST_CHANGES",
                summary=(
                    "No deterministic missing-string markers or Strix report locations "
                    "were recognized."
                ),
                findings=[finding(problem="No deterministic missing-string markers were found.")],
            )
        ),
        encoding="utf-8",
    )
    assert norm.main(["prog", "--check-structural-approval", str(generic_failed_check)]) == 4
    assert "non-actionable failed-check deflection" in capsys.readouterr().err


def test_review_language_contract_rejects_english_only_korean_pr(tmp_path, monkeypatch, capsys):
    evidence = tmp_path / "bounded-review-evidence.md"
    evidence.write_text(
        "## Review language evidence\n\n- Preferred review language: `Korean`\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_EVIDENCE_FILE", str(evidence))

    assert norm.valid_control(
        control(),
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    ) is None

    korean_control = control(
        reason="scripts/ci/example.py 검토 완료.",
        summary=FULL_SUMMARY + "\n한국어 리뷰 문체를 유지했습니다.",
    )
    assert norm.valid_control(
        korean_control,
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    ) is not None

    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps(control()), encoding="utf-8")
    assert norm.main(["prog", "--check-structural-approval", str(approval)]) == 4
    assert "preferred PR language" in capsys.readouterr().err


def test_main_normalizes_and_escapes_html_markers(tmp_path):
    output = tmp_path / "opencode.txt"
    control_data = control(reason="Malicious --> comment", summary=FULL_SUMMARY + "\nBreakout <script>alert(1)</script>")
    output.write_text(json.dumps(control_data), encoding="utf-8")
    assert norm.main(["prog", "head", "run", "attempt", str(output)]) == 0

    saved_text = output.read_text(encoding="utf-8")
    assert "opencode-review-control-v1" in saved_text
    assert "<script>" not in saved_text
    assert "\\u003cscript\\u003e" in saved_text
    inner = saved_text.split("<!-- opencode-review-control-v1")[1]
    json_line = inner.splitlines()[1]
    assert json.loads(json_line)["summary"] == control_data["summary"]
    assert "-->" in inner
    assert "-->" not in inner.split("-->", 1)[0].strip()
