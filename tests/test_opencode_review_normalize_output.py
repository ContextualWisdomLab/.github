import json

from scripts.ci import opencode_review_normalize_output as norm


FULL_SUMMARY = """\
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
User experience: user-facing behavior impact was checked.
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
    assert not norm.admits_missing_structural_review("scripts/ci/example.py checked", "")


def test_changed_file_and_verification_posture_detection():
    assert norm.mentions_changed_file_evidence("README.md", "")
    assert norm.mentions_changed_file_evidence("scripts/ci/example.py", "")
    assert not norm.mentions_changed_file_evidence("No path here", "")
    assert not norm.mentions_changed_file_evidence("Security/privacy: checked", "")
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


def test_label_and_full_coverage_detection():
    combined = FULL_SUMMARY.casefold()
    assert "100%" in norm.label_section(combined, "coverage:")
    assert norm.label_section(combined, "missing:") == ""
    assert norm.mentions_full_coverage("", FULL_SUMMARY)
    assert not norm.mentions_full_coverage("", "")
    assert not norm.mentions_full_coverage("", FULL_SUMMARY.replace("100%", "99%", 1))
    assert not norm.mentions_full_coverage(
        "",
        FULL_SUMMARY.replace("coverage execution evidence", "measured evidence", 1),
    )
    assert not norm.mentions_full_coverage("", FULL_SUMMARY.replace("proves 100%", "not proven"))


def test_check_structural_approval_rejects_invalid_or_unsafe_approvals(tmp_path):
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
    ]
    for index, value in enumerate(cases):
        path = tmp_path / f"case-{index}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        assert norm.check_structural_approval(path) == 4

    request_changes = tmp_path / "request.json"
    request_changes.write_text(json.dumps(control(result="REQUEST_CHANGES")), encoding="utf-8")
    assert norm.check_structural_approval(request_changes) == 0

    generic_deflection = tmp_path / "generic-deflection.json"
    generic_deflection.write_text(
        json.dumps(
            control(
                result="REQUEST_CHANGES",
                summary=(
                    "No deterministic missing-string markers or Strix report locations were "
                    "recognized. Use the failed-check evidence below to map each failed check "
                    "to exact local source lines before approving."
                ),
                findings=[
                    finding(
                        title="Generic failed-check deflection",
                        problem="No deterministic missing-string markers were recognized.",
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

    request = control(result="REQUEST_CHANGES", findings=[finding()])
    assert norm.valid_control(dict(request, findings=["bad"]), **kwargs) is None
    assert norm.valid_control(dict(request, findings=[finding(line=True)]), **kwargs) is None
    assert norm.valid_control(dict(request, findings=[finding(line=0)]), **kwargs) is None
    assert norm.valid_control(dict(request, findings=[finding(title="")]), **kwargs) is None
    assert (
        norm.valid_control(
            dict(
                request,
                summary=(
                    "No deterministic missing-string markers or Strix report locations were "
                    "recognized. Use the failed-check evidence below to map each failed check "
                    "to exact local source lines before approving."
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
    assert norm.mentions_verification_posture(repaired["reason"], repaired["summary"])
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
    assert norm.mentions_full_coverage(repaired["reason"], repaired["summary"])


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


def test_iter_json_objects_extracts_raw_and_embedded_json():
    assert norm.iter_json_objects('{"a": 1}') == [{"a": 1}, {"a": 1}]
    assert norm.iter_json_objects('prefix {"b": 2} suffix') == [{"b": 2}]
    assert norm.iter_json_objects("prefix {  } suffix") == [{}]
    assert norm.iter_json_objects("prefix {not json}") == []
    assert norm.iter_json_objects('prefix {"bad": } suffix') == []
    assert norm.iter_json_objects("no json here") == []


def test_main_normalizes_valid_output_and_reports_failures(tmp_path, capsys):
    output = tmp_path / "opencode.txt"
    output.write_text("prefix\n" + json.dumps(control()) + "\nsuffix", encoding="utf-8")
    assert norm.main(["prog", "head", "run", "attempt", str(output)]) == 0
    assert "opencode-review-control-v1" in output.read_text(encoding="utf-8")

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
