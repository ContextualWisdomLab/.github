import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.ci import opencode_review_normalize_output as norm


def anchor_manifest(manifest: Path) -> None:
    """Bind the manifest bytes to the simulated trusted Actions step output."""
    os.environ["OPENCODE_ARTIFACT_MANIFEST_SHA256"] = hashlib.sha256(
        manifest.read_bytes()
    ).hexdigest()


def seal_artifacts(runner_temp: Path, *paths: Path) -> None:
    """Write the exact current-run digest manifest used by the normalizer."""
    artifacts = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
        if path.is_file()
    }
    manifest = runner_temp / norm.TRUSTED_ARTIFACT_MANIFEST
    manifest.write_text(
        json.dumps(
            {
                "schema": 1,
                "head_sha": "head",
                "run_id": "run",
                "run_attempt": "attempt",
                "artifacts": artifacts,
            }
        ),
        encoding="utf-8",
    )
    manifest.chmod(0o600)
    anchor_manifest(manifest)
    for path in paths:
        if path.exists():
            path.chmod(0o600)


def source_line_receipt(line_text: str) -> str:
    """Return the exact source-line receipt expected by the trusted normalizer."""
    digest = hashlib.sha256(line_text.encode()).hexdigest()
    return f"source-line-sha256={digest}"


@pytest.fixture(autouse=True)
def clear_caches(tmp_path, monkeypatch):
    changed_files = tmp_path / "opencode-changed-files.txt"
    changed_files.write_text("scripts/ci/example.py\n", encoding="utf-8")
    default_source = tmp_path / "scripts" / "ci" / "example.py"
    default_source.parent.mkdir(parents=True)
    default_source.write_text(
        "\n".join(f"line {line}" for line in range(1, 129)), encoding="utf-8"
    )
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("OPENCODE_SOURCE_WORKDIR", str(tmp_path))
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))
    monkeypatch.delenv("OPENCODE_EVIDENCE_FILE", raising=False)
    monkeypatch.delenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", raising=False)
    seal_artifacts(tmp_path, changed_files)
    norm.current_changed_files.cache_clear()
    norm.trusted_execution_receipts.cache_clear()


def check_structural_approval(
    path: Path, *, head: str = "head", run: str = "run", attempt: str = "attempt"
) -> int:
    """Call the structural gate with explicit trusted workflow identity."""
    return norm.check_structural_approval(path, head, run, attempt)


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


def adversarial_validation(
    *,
    status="passed",
    outcomes=("falsified", "falsified"),
    path="scripts/ci/example.py",
):
    return {
        "status": status,
        "probes": [
            {
                "path": path,
                "line": 7 + index,
                "hypothesis": f"The changed path fails under adversarial scenario {index + 1}.",
                "attack_or_counterexample": f"Exercise boundary or failure input {index + 1}.",
                "evidence": (
                    f"Focused source trace at {path}:{7 + index} and regression command {index + 1} "
                    "disproved or confirmed the hypothesis. "
                    + source_line_receipt(f"line {7 + index}")
                ),
                "outcome": outcome,
            }
            for index, outcome in enumerate(outcomes)
        ],
        "residual_risk": "Provider and platform behavior outside the bounded current-head evidence remains monitored.",
    }


def require_adversarial_validation(tmp_path, monkeypatch, *paths):
    changed_files = tmp_path / "opencode-changed-files.txt"
    changed_files.write_text("\n".join(paths) + "\n", encoding="utf-8")
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))
    for path in paths:
        source_path = tmp_path / path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "\n".join(f"line {line}" for line in range(1, 129)),
            encoding="utf-8",
        )
    monkeypatch.setenv("OPENCODE_SOURCE_WORKDIR", str(tmp_path))
    monkeypatch.setenv("OPENCODE_REQUIRE_ADVERSARIAL_VALIDATION", "true")
    seal_artifacts(tmp_path, changed_files, tmp_path / "opencode-review-evidence.md")
    norm.current_changed_files.cache_clear()


def test_adversarial_probe_location_requires_a_source_root(monkeypatch):
    """Missing trusted source material fails closed with an explicit reason."""
    monkeypatch.delenv("OPENCODE_SOURCE_WORKDIR")

    assert (
        norm.adversarial_probe_location_error("scripts/ci/example.py", 1)
        == "trusted current-head source root is unavailable"
    )


def test_adversarial_probe_location_rejects_missing_and_escaping_paths(
    tmp_path, monkeypatch
):
    """Nonexistent paths and symlink escapes cannot authorize evidence."""
    source_root = tmp_path / "source"
    source_root.mkdir()
    monkeypatch.setenv("OPENCODE_SOURCE_WORKDIR", str(source_root))

    assert "does not exist" in norm.adversarial_probe_location_error("missing.py", 1)

    outside = tmp_path / "outside.py"
    outside.write_text("outside\n", encoding="utf-8")
    (source_root / "escape.py").symlink_to(outside)
    assert "outside" in norm.adversarial_probe_location_error("escape.py", 1)


def test_adversarial_probe_location_rejects_non_files_and_oversize_files(
    tmp_path, monkeypatch
):
    """Only bounded regular source files are eligible for line evidence."""
    source_root = tmp_path / "source"
    source_root.mkdir()
    monkeypatch.setenv("OPENCODE_SOURCE_WORKDIR", str(source_root))

    (source_root / "directory.py").mkdir()
    assert "not a regular" in norm.adversarial_probe_location_error("directory.py", 1)

    (source_root / "oversize.py").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    assert "exceeds the bounded 2 MiB" in norm.adversarial_probe_location_error(
        "oversize.py", 1
    )


def test_adversarial_probe_location_reports_read_failures(tmp_path, monkeypatch):
    """A read error remains visible instead of accepting an unverified line."""
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_file = source_root / "unreadable.py"
    source_file.write_text("line\n", encoding="utf-8")
    monkeypatch.setenv("OPENCODE_SOURCE_WORKDIR", str(source_root))
    original_read_bytes = Path.read_bytes

    def fail_target_read(path):
        if path == source_file:
            raise OSError("simulated read failure")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", fail_target_read)

    assert "could not be read" in norm.adversarial_probe_location_error(
        "unreadable.py", 1
    )


def test_adversarial_validation_requires_two_falsified_material_probes(
    tmp_path, monkeypatch
):
    require_adversarial_validation(tmp_path, monkeypatch, "scripts/ci/example.py")
    approved = control(adversarial_validation=adversarial_validation())
    assert (
        norm.valid_control(
            approved,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is not None
    )

    one_probe = control(
        adversarial_validation=adversarial_validation(outcomes=("falsified",))
    )
    assert (
        norm.valid_control(
            one_probe,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is None
    )

    confirmed_probe = control(
        adversarial_validation=adversarial_validation(
            outcomes=("falsified", "confirmed")
        )
    )
    assert (
        norm.valid_control(
            confirmed_probe,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is None
    )


def test_adversarial_validation_rejects_duplicate_probe_evidence(tmp_path, monkeypatch):
    """Repeated probes cannot satisfy the independent material-change minimum."""
    require_adversarial_validation(tmp_path, monkeypatch, "scripts/ci/example.py")
    probe = adversarial_validation()["probes"][0]
    duplicate = control(
        adversarial_validation={
            "status": "passed",
            "probes": [probe, dict(probe)],
            "residual_risk": "External provider behavior remains monitored.",
        }
    )

    reasons: list[str] = []
    assert (
        norm.valid_control(
            duplicate,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
            rejection_reasons=reasons,
        )
        is None
    )
    assert "duplicates an earlier probe" in reasons[-1]


def test_adversarial_validation_canonicalizes_case_and_whitespace_for_duplicates(
    tmp_path, monkeypatch
):
    """Cosmetic text drift cannot disguise reused adversarial evidence."""
    require_adversarial_validation(tmp_path, monkeypatch, "scripts/ci/example.py")
    probe = adversarial_validation()["probes"][0]
    disguised = dict(probe)
    disguised["hypothesis"] = f"  {probe['hypothesis'].upper()}  "
    disguised["attack_or_counterexample"] = (
        f"  {probe['attack_or_counterexample'].upper()}  "
    )
    disguised["evidence"] = "  " + probe["evidence"].replace(" ", "   ") + "  "
    duplicate = control(
        adversarial_validation={
            "status": "passed",
            "probes": [probe, disguised],
            "residual_risk": "External provider behavior remains monitored.",
        }
    )

    reasons: list[str] = []
    assert (
        norm.valid_control(
            duplicate,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
            rejection_reasons=reasons,
        )
        is None
    )
    assert "duplicates an earlier probe" in reasons[-1]


def test_adversarial_validation_rejects_unbound_or_mismatched_source_receipts(
    tmp_path, monkeypatch
):
    """Lexical proof prose cannot authorize approval without exact line binding."""
    require_adversarial_validation(tmp_path, monkeypatch, "scripts/ci/example.py")
    validation = adversarial_validation()

    lexical_only = dict(validation["probes"][0])
    lexical_only["evidence"] = "scripts/ci/example.py:7 source trace showed safe"
    missing = control(
        adversarial_validation={
            **validation,
            "probes": [lexical_only, validation["probes"][1]],
        }
    )
    missing_reasons: list[str] = []
    assert (
        norm.valid_control(
            missing,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
            rejection_reasons=missing_reasons,
        )
        is None
    )
    assert "source-line-sha256 receipt" in missing_reasons[-1]

    mismatched = dict(validation["probes"][0])
    mismatched["evidence"] = re.sub(
        r"source-line-sha256=[0-9a-f]{64}",
        "source-line-sha256=" + "0" * 64,
        mismatched["evidence"],
    )
    invalid = control(
        adversarial_validation={
            **validation,
            "probes": [mismatched, validation["probes"][1]],
        }
    )
    mismatch_reasons: list[str] = []
    assert (
        norm.valid_control(
            invalid,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
            rejection_reasons=mismatch_reasons,
        )
        is None
    )
    assert "does not match the cited current-head line" in mismatch_reasons[-1]


def test_adversarial_source_receipt_helpers_fail_closed_at_trust_boundaries(
    tmp_path, monkeypatch
):
    """Receipt helpers reject missing roots, files, lines, and receipt counts."""
    monkeypatch.delenv("OPENCODE_SOURCE_WORKDIR")
    assert norm.adversarial_probe_source_line_digest("scripts/ci/example.py", 1) is None

    monkeypatch.setenv("OPENCODE_SOURCE_WORKDIR", str(tmp_path))
    assert norm.adversarial_probe_source_line_digest("missing.py", 1) is None

    one_line = tmp_path / "one_line.py"
    one_line.write_text("trusted line\n", encoding="utf-8")
    assert norm.adversarial_probe_source_line_digest("one_line.py", 2) is None

    assert (
        norm.adversarial_probe_source_receipt_error("no receipt", "one_line.py", 1)
        == "must contain exactly one source-line-sha256 receipt"
    )
    receipt = "source-line-sha256=" + "0" * 64
    assert (
        norm.adversarial_probe_source_receipt_error(receipt, "missing.py", 1)
        == "source-line receipt could not be verified from the trusted tree"
    )


def test_adversarial_request_changes_requires_confirmed_probe_at_finding(
    tmp_path, monkeypatch
):
    require_adversarial_validation(tmp_path, monkeypatch, "scripts/ci/example.py")
    blocked = control(
        result="REQUEST_CHANGES",
        findings=[finding(line=8)],
        adversarial_validation=adversarial_validation(
            status="failed", outcomes=("falsified", "confirmed")
        ),
    )
    assert (
        norm.valid_control(
            blocked,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is not None
    )

    wrong_anchor = control(
        result="REQUEST_CHANGES",
        findings=[finding(line=99)],
        adversarial_validation=adversarial_validation(
            status="failed", outcomes=("falsified", "confirmed")
        ),
    )
    assert (
        norm.valid_control(
            wrong_anchor,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is None
    )


def test_adversarial_validation_accepts_one_probe_for_non_code_change(
    tmp_path, monkeypatch
):
    require_adversarial_validation(tmp_path, monkeypatch, "README.md")
    approved = control(
        reason="README.md is source-backed.",
        summary=FULL_SUMMARY.replace("scripts/ci/example.py", "README.md"),
        adversarial_validation=adversarial_validation(
            outcomes=("falsified",), path="README.md"
        ),
    )
    assert (
        norm.valid_control(
            approved,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is not None
    )


def test_adversarial_validation_rejects_each_malformed_contract_branch(
    tmp_path, monkeypatch
):
    require_adversarial_validation(tmp_path, monkeypatch, "scripts/ci/example.py")
    valid = adversarial_validation()
    first_probe = valid["probes"][0]
    second_probe = valid["probes"][1]
    cases = [
        (None, "APPROVE", [], "must be an object"),
        ({}, "APPROVE", [], "status must be passed or failed"),
        (
            {**valid, "residual_risk": ""},
            "APPROVE",
            [],
            "residual_risk must be a non-empty string",
        ),
        ({**valid, "probes": "bad"}, "APPROVE", [], "probes must be a list"),
        (
            {**valid, "probes": [None, second_probe]},
            "APPROVE",
            [],
            "probe 1 must be an object",
        ),
        (
            {**valid, "probes": [{**first_probe, "path": ""}, second_probe]},
            "APPROVE",
            [],
            "path must be a non-empty string",
        ),
        (
            {**valid, "probes": [{**first_probe, "path": "../secret"}, second_probe]},
            "APPROVE",
            [],
            "path is unsafe",
        ),
        (
            {**valid, "probes": [{**first_probe, "path": "other.py"}, second_probe]},
            "APPROVE",
            [],
            "path is not a current-head changed file",
        ),
        (
            {**valid, "probes": [{**first_probe, "line": 0}, second_probe]},
            "APPROVE",
            [],
            "line must be a positive integer",
        ),
        (
            {**valid, "probes": [{**first_probe, "line": 999}, second_probe]},
            "APPROVE",
            [],
            "exceeds the current-head file length",
        ),
        (
            {**valid, "probes": [{**first_probe, "evidence": ""}, second_probe]},
            "APPROVE",
            [],
            "field evidence must be non-empty",
        ),
        (
            {
                **valid,
                "probes": [
                    {**first_probe, "evidence": "The retry logic handles this case."},
                    second_probe,
                ],
            },
            "APPROVE",
            [],
            "independent proof",
        ),
        (
            {
                **valid,
                "probes": [
                    {**first_probe, "evidence": "Increasing delays are present."},
                    second_probe,
                ],
            },
            "APPROVE",
            [],
            "must cite",
        ),
        (
            {**valid, "probes": [{**first_probe, "outcome": "unknown"}, second_probe]},
            "APPROVE",
            [],
            "outcome must be falsified or confirmed",
        ),
        ({**valid, "status": "failed"}, "APPROVE", [], "status=passed"),
        ({**valid, "status": "passed"}, "REQUEST_CHANGES", [], "status=failed"),
        (
            {**valid, "status": "failed"},
            "REQUEST_CHANGES",
            [],
            "at least one confirmed adversarial probe",
        ),
    ]
    for value, result, findings, expected in cases:
        assert expected in norm.adversarial_validation_error(
            value,
            result=result,
            findings=findings,
        )


def test_structural_gate_logs_adversarial_contract_failure(
    tmp_path, monkeypatch, capsys
):
    require_adversarial_validation(tmp_path, monkeypatch, "scripts/ci/example.py")
    control_file = tmp_path / "control.json"
    control_file.write_text(
        json.dumps(control(findings=None, adversarial_validation=None)),
        encoding="utf-8",
    )
    assert check_structural_approval(control_file) == 4
    assert "adversarial_validation must be an object" in capsys.readouterr().err


def test_runtime_tool_claim_requires_trusted_workflow_receipt(
    tmp_path, monkeypatch, capsys
):
    require_adversarial_validation(tmp_path, monkeypatch, "scripts/ci/example.py")
    validation = adversarial_validation()
    validation["probes"][0]["evidence"] = (
        "Source trace at scripts/ci/example.py:7 and React DevTools confirmed the "
        "component did not re-render. " + source_line_receipt("line 7")
    )
    claimed = control(adversarial_validation=validation)

    assert (
        norm.valid_control(
            claimed,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is None
    )
    control_file = tmp_path / "control.json"
    control_file.write_text(json.dumps(claimed), encoding="utf-8")
    assert check_structural_approval(control_file) == 4
    assert (
        "claims react-devtools execution without a trusted workflow receipt"
        in capsys.readouterr().err
    )

    receipts = tmp_path / "opencode-execution-receipts.txt"
    receipts.write_text(
        "OPENCODE_EXECUTION_RECEIPT tool=react-devtools status=passed\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_EXECUTION_RECEIPTS_FILE", str(receipts))
    seal_artifacts(
        tmp_path,
        tmp_path / "opencode-changed-files.txt",
        tmp_path / "opencode-review-evidence.md",
        receipts,
    )
    norm.trusted_execution_receipts.cache_clear()
    assert (
        norm.valid_control(
            claimed,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is not None
    )
    assert check_structural_approval(control_file) == 0


def test_runtime_tool_claim_gate_covers_summary_and_allows_explicit_limitations(
    tmp_path, monkeypatch, capsys
):
    require_adversarial_validation(tmp_path, monkeypatch, "scripts/ci/example.py")
    summary_claim = control(
        summary=FULL_SUMMARY + "\nReact DevTools confirmed stable rendering.",
        adversarial_validation=adversarial_validation(),
    )
    assert (
        norm.valid_control(
            summary_claim,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is None
    )
    control_file = tmp_path / "summary-claim.json"
    control_file.write_text(json.dumps(summary_claim), encoding="utf-8")
    assert check_structural_approval(control_file) == 4
    assert (
        "review claims react-devtools execution without a trusted workflow receipt"
        in capsys.readouterr().err
    )

    limitation = control(
        summary=FULL_SUMMARY + "\nPlaywright was not executed in this non-web change.",
        adversarial_validation=adversarial_validation(),
    )
    assert (
        norm.valid_control(
            limitation,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is not None
    )


def test_runtime_tool_receipt_reader_and_claim_direction_edges(tmp_path, monkeypatch):
    missing_receipts = tmp_path / "opencode-execution-receipts.txt"
    monkeypatch.setenv("OPENCODE_EXECUTION_RECEIPTS_FILE", str(missing_receipts))
    norm.trusted_execution_receipts.cache_clear()
    assert norm.trusted_execution_receipts() == frozenset()

    assert (
        norm.claimed_runtime_tool("Verified with Playwright on the changed view.")
        == "playwright"
    )
    assert norm.claimed_runtime_tool("Was not verified with Playwright.") == ""
    assert norm.claimed_runtime_tool("Playwright evidence was unavailable.") == ""
    assert (
        norm.claimed_runtime_tool(
            "Playwright evidence was unavailable; Selenium confirmed the fallback."
        )
        == "selenium"
    )

    bounded_evidence = tmp_path / "opencode-review-evidence.md"
    bounded_evidence.write_text("trusted evidence", encoding="utf-8")
    monkeypatch.setenv(
        "OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(tmp_path / "missing.md")
    )
    monkeypatch.setenv("OPENCODE_EVIDENCE_FILE", str(bounded_evidence))
    seal_artifacts(
        tmp_path,
        tmp_path / "opencode-changed-files.txt",
        bounded_evidence,
    )
    assert norm.approval_repair_evidence_file() == bounded_evidence


@pytest.mark.parametrize(
    ("claim", "tool_slug"),
    [
        ("Headless Chromium rendered the page successfully.", "headless-chromium"),
        ("I opened the changed view in Chrome and verified it.", "chrome"),
        ("A real browser confirmed the dialog focus order.", "browser"),
        ("Puppeteer passed the interaction check.", "puppeteer"),
        ("Firefox verified the responsive layout.", "firefox"),
        ("Playwright navigated to the route and captured a screenshot.", "playwright"),
        ("Chrome displayed the production page.", "chrome"),
        ("Cypress completed the checkout flow.", "cypress"),
        ("Selenium produced a browser trace.", "selenium"),
        ("I took a screenshot in Safari.", "safari"),
        ("Cypress confirms the dialog focus order.", "cypress"),
        ("Selenium validates the production route.", "selenium"),
        ("Chrome reports a clean console.", "chrome"),
        ("The browser test passes.", "browser"),
        ("Playwright does confirm the current route.", "playwright"),
        (
            "Playwright was not installed, but verified the production route.",
            "playwright",
        ),
    ],
)
def test_runtime_tool_claim_blocks_browser_alias_and_negation_bypasses(
    claim, tool_slug
):
    assert norm.claimed_runtime_tool(claim) == tool_slug


@pytest.mark.parametrize(
    "limitation",
    [
        "Headless Chromium was not executed.",
        "Puppeteer wasn't used for this review.",
        "The layout was never inspected in Firefox.",
        "The route was checked without a browser.",
        "Cypress does not confirm the dialog focus order.",
        "The browser test does not pass.",
    ],
)
def test_runtime_tool_claim_allows_explicit_browser_execution_limitations(limitation):
    assert norm.claimed_runtime_tool(limitation) == ""


def test_every_claimed_runtime_tool_requires_its_own_receipt(tmp_path, monkeypatch):
    receipts = tmp_path / "opencode-execution-receipts.txt"
    receipts.write_text(
        "OPENCODE_EXECUTION_RECEIPT tool=chrome status=passed\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENCODE_EXECUTION_RECEIPTS_FILE", str(receipts))
    seal_artifacts(
        tmp_path,
        tmp_path / "opencode-changed-files.txt",
        tmp_path / "opencode-review-evidence.md",
        receipts,
    )
    norm.trusted_execution_receipts.cache_clear()
    claim = "Chrome verified the route; Playwright captured the screenshot."

    assert norm.claimed_runtime_tools(claim) == ("chrome", "playwright")
    assert norm.unreceipted_runtime_tool_claim(claim) == "playwright"

    receipts.write_text(
        "OPENCODE_EXECUTION_RECEIPT tool=chrome status=passed\n"
        "OPENCODE_EXECUTION_RECEIPT tool=playwright status=observed\n",
        encoding="utf-8",
    )
    seal_artifacts(
        tmp_path,
        tmp_path / "opencode-changed-files.txt",
        tmp_path / "opencode-review-evidence.md",
        receipts,
    )
    norm.trusted_execution_receipts.cache_clear()
    assert norm.unreceipted_runtime_tool_claim(claim) == ""


def test_structural_review_detection_accepts_phrases_patterns_and_clean_text():
    assert norm.admits_missing_structural_review("No changed files", "")
    assert norm.admits_missing_structural_review(
        "Could not inspect the changed files", ""
    )
    assert norm.admits_missing_structural_review("", "Source files were not inspected")
    assert norm.admits_missing_structural_review(
        "structural exploration was not possible", "summary"
    )
    assert norm.admits_missing_structural_review("reason", "evidence was truncated")
    assert norm.admits_missing_structural_review(
        "", "structural analysis was incomplete"
    )
    assert norm.admits_missing_structural_review("", "zero changed files")
    assert norm.admits_missing_structural_review(
        "STRUCTURAL EXPLORATION WAS NOT POSSIBLE", ""
    )
    assert not norm.admits_missing_structural_review(
        "scripts/ci/example.py checked", ""
    )


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
    assert not norm.mentions_changed_file_evidence(
        "changed some code", "no file listed here"
    )
    assert not norm.mentions_changed_file_evidence(
        "invalid.ext", "not a valid extension"
    )
    assert norm.mentions_verification_posture("", FULL_SUMMARY)
    assert not norm.mentions_verification_posture(
        "", FULL_SUMMARY.replace("CodeGraph", "graph")
    )


def test_actual_changed_file_detection_prefers_current_head_file_list(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("OPENCODE_CHANGED_FILES_FILE", raising=False)
    norm.current_changed_files.cache_clear()
    assert norm.current_changed_files() == frozenset()
    assert not norm.mentions_actual_changed_file("scripts/ci/example.py", "")

    changed_files = tmp_path / "opencode-changed-files.txt"
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
    seal_artifacts(tmp_path, changed_files, tmp_path / "opencode-review-evidence.md")
    norm.current_changed_files.cache_clear()

    monkeypatch.delenv("OPENCODE_CHANGED_FILES_FILE", raising=False)
    norm.current_changed_files.cache_clear()
    assert not norm.mentions_actual_changed_file(
        "No executable changes here", "no changed files"
    )
    assert norm.mentions_verification_posture(
        "No executable changes here", "no changed files"
    )
    assert norm.mentions_full_coverage("No executable changes here", "no changed files")
    assert not norm.mentions_actual_changed_file("No changes", "no changes")
    assert norm.mentions_verification_posture("No changes", "no changes")
    assert norm.mentions_full_coverage("No changes", "no changes")
    assert not norm.mentions_actual_changed_file(
        "No UI codebase changes", "No UI codebase changes"
    )
    assert norm.mentions_verification_posture(
        "No UI codebase changes", "No UI codebase changes"
    )
    assert norm.mentions_full_coverage(
        "No UI codebase changes", "No UI codebase changes"
    )
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))
    seal_artifacts(tmp_path, changed_files, tmp_path / "opencode-review-evidence.md")
    norm.current_changed_files.cache_clear()

    assert norm.current_changed_files() == frozenset(
        {
            ".github/workflows/opencode-review.yml",
            "scripts/ci/opencode_review_normalize_output.py",
        }
    )
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

    monkeypatch.setenv(
        "OPENCODE_CHANGED_FILES_FILE",
        str(tmp_path / "opencode-changed-files-missing.txt"),
    )
    norm.current_changed_files.cache_clear()
    assert norm.current_changed_files() == frozenset()
    assert not norm.mentions_actual_changed_file("scripts/ci/example.py", "")


@pytest.mark.parametrize(
    "evidence",
    [
        "No command was run; the output reported no result.",
        "No test ran and no result was reported.",
        "The probe was not executed.",
        "No assertion passed.",
    ],
)
def test_adversarial_evidence_rejects_explicit_non_execution(evidence):
    """Proof keywords cannot turn an explicit no-execution claim into evidence."""
    assert (
        norm.adversarial_evidence_rejection_reason(evidence, "scripts/ci/example.py")
        == "explicitly denies execution or an observed result"
    )


def test_adversarial_evidence_rejects_exact_changed_path_without_independent_proof():
    """A changed path is location metadata, not an execution receipt."""
    assert "must cite" in norm.adversarial_evidence_rejection_reason(
        "scripts/ci/example.py passed.",
        "scripts/ci/example.py",
    )


@pytest.mark.parametrize(
    "unsafe_path",
    [
        r"C:\\Windows\\win.ini",
        "C:/Windows/win.ini",
        "C:relative.py",
        r"..\\..\\scripts\\ci\\example.py",
        "//server/share/file.py",
        "/etc/passwd",
    ],
)
def test_adversarial_validation_rejects_cross_platform_unsafe_paths(
    tmp_path, monkeypatch, unsafe_path
):
    """Windows, UNC, absolute, and backslash traversal paths are never anchors."""
    require_adversarial_validation(tmp_path, monkeypatch, "scripts/ci/example.py")
    error = norm.adversarial_validation_error(
        adversarial_validation(path=unsafe_path),
        result="APPROVE",
        findings=[],
    )
    assert "path is unsafe" in error


def test_trusted_artifact_digest_and_identity_are_fail_closed(tmp_path, monkeypatch):
    """Artifact tampering and stale run identity invalidate current-head evidence."""
    changed_files = tmp_path / "opencode-changed-files.txt"
    assert norm.artifact_identity_error("head", "run", "attempt") == ""
    assert norm.current_changed_files() == frozenset({"scripts/ci/example.py"})

    changed_files.write_text("attacker.py\n", encoding="utf-8")
    norm.current_changed_files.cache_clear()
    assert norm.current_changed_files() == frozenset()
    assert (
        norm.valid_control(
            control(reason="attacker.py reviewed."),
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is None
    )

    changed_files.write_text("scripts/ci/example.py\n", encoding="utf-8")
    seal_artifacts(tmp_path, changed_files)
    manifest = tmp_path / norm.TRUSTED_ARTIFACT_MANIFEST
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["run_id"] = "stale-run"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    manifest.chmod(0o600)
    anchor_manifest(manifest)
    assert "run_id" in norm.artifact_identity_error("head", "run", "attempt")
    assert "explicit" in norm.artifact_identity_error("head", "-", "attempt")


def test_trusted_artifact_path_rejects_escape_symlink_and_writable_file(
    tmp_path, monkeypatch
):
    """Only the exact runner-owned regular artifact with safe mode is accepted."""
    changed_files = tmp_path / "opencode-changed-files.txt"
    outside = tmp_path.parent / "opencode-changed-files.txt"
    outside.write_text("attacker.py\n", encoding="utf-8")
    outside.chmod(0o600)
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(outside))
    assert norm.trusted_artifact_path("OPENCODE_CHANGED_FILES_FILE") is None

    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))
    changed_files.unlink()
    changed_files.symlink_to(outside)
    seal_artifacts(tmp_path, changed_files)
    assert norm.trusted_artifact_path("OPENCODE_CHANGED_FILES_FILE") is None

    changed_files.unlink()
    changed_files.write_text("scripts/ci/example.py\n", encoding="utf-8")
    seal_artifacts(tmp_path, changed_files)
    changed_files.chmod(0o622)
    assert norm.trusted_artifact_path("OPENCODE_CHANGED_FILES_FILE") is None

    monkeypatch.delenv("RUNNER_TEMP")
    assert norm.trusted_runner_temp() is None
    assert norm.safe_runner_artifact(changed_files, changed_files.name) is None
    assert norm.trusted_artifact_manifest() is None


def test_trusted_artifact_helpers_reject_malformed_sources(tmp_path, monkeypatch):
    """Every unsafe root, manifest, file, and digest branch fails closed."""
    changed_files = tmp_path / "opencode-changed-files.txt"
    manifest = tmp_path / norm.TRUSTED_ARTIFACT_MANIFEST

    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "missing-root"))
    assert norm.trusted_runner_temp() is None
    root_file = tmp_path / "root-file"
    root_file.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("RUNNER_TEMP", str(root_file))
    assert norm.trusted_runner_temp() is None
    symlink_root = tmp_path / "symlink-root"
    symlink_root.symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setenv("RUNNER_TEMP", str(symlink_root))
    assert norm.trusted_runner_temp() is None

    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    assert norm.safe_runner_artifact(tmp_path / "missing", "missing") is None
    manifest.unlink()
    assert norm.trusted_artifact_manifest() is None
    assert "missing or unsafe" in norm.artifact_identity_error("head", "run", "attempt")

    manifest.write_text("{", encoding="utf-8")
    manifest.chmod(0o600)
    anchor_manifest(manifest)
    assert norm.trusted_artifact_manifest() is None
    manifest.write_text("[]", encoding="utf-8")
    anchor_manifest(manifest)
    assert norm.trusted_artifact_manifest() is None
    manifest.write_text(json.dumps({"schema": 2}), encoding="utf-8")
    anchor_manifest(manifest)
    assert norm.trusted_artifact_manifest() is None

    seal_artifacts(tmp_path, changed_files)
    monkeypatch.delenv("OPENCODE_ARTIFACT_MANIFEST_SHA256")
    assert norm.trusted_artifact_manifest() is None
    monkeypatch.setenv("OPENCODE_ARTIFACT_MANIFEST_SHA256", "not-a-digest")
    assert norm.trusted_artifact_manifest() is None
    monkeypatch.setenv("OPENCODE_ARTIFACT_MANIFEST_SHA256", "0" * 64)
    assert norm.trusted_artifact_manifest() is None
    manifest.write_bytes(b"\xff")
    manifest.chmod(0o600)
    anchor_manifest(manifest)
    assert norm.trusted_artifact_manifest() is None

    seal_artifacts(tmp_path, changed_files)
    monkeypatch.delenv("OPENCODE_CHANGED_FILES_FILE")
    assert norm.trusted_artifact_path("OPENCODE_CHANGED_FILES_FILE") is None
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))
    changed_files.write_text("", encoding="utf-8")
    seal_artifacts(tmp_path, changed_files)
    assert norm.trusted_artifact_path("OPENCODE_CHANGED_FILES_FILE") is None

    changed_files.write_text("scripts/ci/example.py\n", encoding="utf-8")
    seal_artifacts(tmp_path, changed_files)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["artifacts"] = []
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    manifest.chmod(0o600)
    anchor_manifest(manifest)
    assert norm.trusted_artifact_path("OPENCODE_CHANGED_FILES_FILE") is None

    seal_artifacts(tmp_path, changed_files)
    actual_uid = norm.os.getuid()
    monkeypatch.setattr(norm.os, "getuid", lambda: actual_uid + 1)
    assert norm.safe_runner_artifact(changed_files, changed_files.name) is None


def test_empty_changed_manifest_blocks_adversarial_and_material_claims(
    tmp_path, monkeypatch
):
    """Missing current-head scope cannot validate a probe or trivialization claim."""
    monkeypatch.delenv("OPENCODE_CHANGED_FILES_FILE")
    norm.current_changed_files.cache_clear()
    error = norm.adversarial_validation_error(
        adversarial_validation(),
        result="APPROVE",
        findings=[],
    )
    assert "manifest is unavailable or empty" in error
    assert not norm.contradicts_material_changed_file_scope("simple typo fix", "")


def test_valid_control_rejects_missing_artifact_provenance(tmp_path):
    """An otherwise valid approval cannot pass without the run provenance manifest."""
    (tmp_path / norm.TRUSTED_ARTIFACT_MANIFEST).unlink()
    reasons: list[str] = []
    assert (
        norm.valid_control(
            control(),
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
            rejection_reasons=reasons,
        )
        is None
    )
    assert "trusted artifact provenance failed" in reasons[-1]


def test_structural_gate_rejects_stale_or_identityless_invocation(tmp_path):
    """The standalone structural mode requires an exact current-run identity."""
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps(control()), encoding="utf-8")
    assert check_structural_approval(approval, run="stale-run") == 4
    assert norm.main(["prog", "--check-structural-approval", str(approval)]) == 64


def test_preferred_review_language_handles_unreadable_and_unknown_evidence(
    tmp_path, monkeypatch
):
    evidence = tmp_path / "opencode-review-evidence.md"
    evidence.write_text(
        "## Review language evidence\nPreferred review language: `Spanish`\n",
        encoding="utf-8",
    )
    norm.current_changed_files.cache_clear()
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))
    changed_files = tmp_path / "opencode-changed-files.txt"
    changed_files.write_text(
        "scripts/ci/opencode_review_normalize_output.py\n",
        encoding="utf-8",
    )
    seal_artifacts(tmp_path, changed_files, evidence)

    assert norm.preferred_review_language() is None

    monkeypatch.setattr(norm, "read_text_lossy", lambda _path: None)
    assert norm.preferred_review_language() is None


def test_changed_file_kind_contradictions_are_rejected(tmp_path, monkeypatch):
    changed_files = tmp_path / "opencode-changed-files.txt"
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
    seal_artifacts(tmp_path, changed_files, tmp_path / "opencode-review-evidence.md")
    norm.current_changed_files.cache_clear()

    false_summary = (
        FULL_SUMMARY.replace(
            "scripts/ci/example.py", ".github/workflows/opencode-review.yml"
        )
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
    assert (
        norm.valid_control(
            approval,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is None
    )

    path = tmp_path / "approval.json"
    path.write_text(json.dumps(approval), encoding="utf-8")
    assert check_structural_approval(path) == 4

    changed_files.write_text("scripts/deploy.sh\n", encoding="utf-8")
    seal_artifacts(tmp_path, changed_files, tmp_path / "opencode-review-evidence.md")
    norm.current_changed_files.cache_clear()
    assert norm.contradicts_changed_file_kinds(
        "Reviewed scripts/deploy.sh.",
        "PoC/execution: Not applicable (no executable changes).",
    )

    changed_files.write_text("tests/README.md\n", encoding="utf-8")
    seal_artifacts(tmp_path, changed_files, tmp_path / "opencode-review-evidence.md")
    norm.current_changed_files.cache_clear()
    assert norm.contradicts_changed_file_kinds(
        "Reviewed tests/README.md.",
        "TDD/regression: Not applicable (no tests changed).",
    )

    changed_files.write_text("scripts/deploy.sh\n", encoding="utf-8")
    seal_artifacts(tmp_path, changed_files, tmp_path / "opencode-review-evidence.md")
    norm.current_changed_files.cache_clear()
    assert not norm.contradicts_changed_file_kinds(
        "Reviewed scripts/deploy.sh.",
        "PoC/execution: bash -n scripts/deploy.sh passed.",
    )

    monkeypatch.delenv("OPENCODE_CHANGED_FILES_FILE")
    norm.current_changed_files.cache_clear()
    assert not norm.contradicts_changed_file_kinds(
        approval["reason"], approval["summary"]
    )


def test_material_changed_file_scope_rejects_trivial_string_approval(
    tmp_path, monkeypatch
):
    changed_files = tmp_path / "opencode-changed-files.txt"
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
    seal_artifacts(tmp_path, changed_files, tmp_path / "opencode-review-evidence.md")
    norm.current_changed_files.cache_clear()

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
    assert (
        norm.valid_control(
            approval,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is None
    )

    path = tmp_path / "approval.json"
    path.write_text(json.dumps(approval), encoding="utf-8")
    assert check_structural_approval(path) == 4

    changed_files.write_text("README.md\n", encoding="utf-8")
    seal_artifacts(tmp_path, changed_files, tmp_path / "opencode-review-evidence.md")
    norm.current_changed_files.cache_clear()
    assert not norm.contradicts_material_changed_file_scope(
        approval["reason"],
        approval["summary"],
    )


def test_material_changed_file_scope_rejects_false_documentation_typo_reason(
    tmp_path, monkeypatch
):
    changed_files = tmp_path / "opencode-changed-files.txt"
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
    seal_artifacts(tmp_path, changed_files, tmp_path / "opencode-review-evidence.md")
    norm.current_changed_files.cache_clear()

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
    assert (
        norm.valid_control(
            approval,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is None
    )

    path = tmp_path / "approval.json"
    path.write_text(json.dumps(approval), encoding="utf-8")
    assert check_structural_approval(path) == 4


def test_label_and_full_coverage_detection(tmp_path, monkeypatch):
    combined = FULL_SUMMARY.casefold()
    assert "100%" in norm.label_section(combined, "coverage:")
    assert norm.label_section(combined, "missing:") == ""
    text_coverage = (
        "performance: FAST docstring coverage: 100% something else coverage: 100%"
    )
    assert norm.label_section(text_coverage, "performance:") == " FAST "
    assert norm.mentions_full_coverage("", FULL_SUMMARY)
    no_source_summary = FULL_SUMMARY.replace(
        "coverage execution evidence proves 100% test coverage",
        "coverage execution evidence reports test coverage as not applicable because no supported changed source files or package manifests were found",
    ).replace(
        "coverage execution evidence proves 100% docstring coverage",
        "coverage execution evidence reports docstring coverage as not applicable because no supported changed source files or package manifests were found",
    )
    assert not norm.mentions_full_coverage("", no_source_summary)
    assert norm.contradicts_changed_file_kinds("", no_source_summary)


    changed_files = tmp_path / "opencode-changed-files.txt"
    changed_files.write_text("README.md\n", encoding="utf-8")
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))
    seal_artifacts(tmp_path, changed_files)
    norm.current_changed_files.cache_clear()
    assert norm.mentions_full_coverage("", no_source_summary)
    assert not norm.contradicts_changed_file_kinds("", no_source_summary)
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
    assert not norm.mentions_full_coverage(
        "", FULL_SUMMARY.replace("100%", "not applicable", 1)
    )
    assert not norm.mentions_full_coverage(
        "",
        FULL_SUMMARY.replace(
            "coverage execution evidence proves 100% test coverage",
            "coverage execution evidence did not prove 100% test coverage",
        ),
    )
    assert (
        norm.evidence_coverage_mode(
            "- Result: PASS\n"
            "- Test coverage: not applicable (no supported source files or package manifests)\n"
        )
        is None
    )
    assert not norm.mentions_full_coverage(
        "",
        FULL_SUMMARY.replace("coverage execution evidence", "measured evidence", 1),
    )
    assert not norm.mentions_full_coverage(
        "", FULL_SUMMARY.replace("proves 100%", "not proven")
    )


def test_label_section_scans_labels_once_and_prefers_longest_label():
    """Parse adjacent labels without rescanning the input for every label."""
    text = "docstring coverage: 100% coverage: 98% performance: measured"

    assert norm.label_section(text, "docstring coverage:") == " 100% "
    assert norm.label_section(text, "coverage:") == " 98% "
    assert norm.label_section(text, "performance:") == " measured"
    alternatives = norm.ANY_LABEL_PATTERN.pattern.split("|")
    assert alternatives.index(re.escape("docstring coverage:")) < alternatives.index(
        re.escape("coverage:")
    )


def test_label_section_preserves_custom_label_lookup():
    """Repository-specific labels retain the helper's backwards-compatible path."""
    text = "custom evidence: measured coverage: 98%"

    assert norm.label_section(text, "custom evidence:") == " measured "


def test_check_structural_approval_rejects_invalid_or_unsafe_approvals(
    tmp_path, monkeypatch
):
    assert check_structural_approval(tmp_path / "missing.json") == 65
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{", encoding="utf-8")
    assert check_structural_approval(bad_json) == 65
    non_dict = tmp_path / "list.json"
    non_dict.write_text("[]", encoding="utf-8")
    assert check_structural_approval(non_dict) == 4

    cases = [
        control(reason="No changed files"),
        control(
            reason="No source path",
            summary=FULL_SUMMARY.replace("scripts/ci/example.py", "source file"),
        ),
        control(
            summary="scripts/ci/example.py\nCoverage: coverage execution evidence proves 100%."
        ),
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
        assert check_structural_approval(path) == 4

    changed_files = tmp_path / "opencode-changed-files.txt"
    changed_files.write_text("tests/actual_changed_file.py\n", encoding="utf-8")
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))
    seal_artifacts(tmp_path, changed_files, tmp_path / "opencode-review-evidence.md")
    norm.current_changed_files.cache_clear()
    wrong_file = tmp_path / "wrong-file.json"
    wrong_file.write_text(json.dumps(control()), encoding="utf-8")
    assert check_structural_approval(wrong_file) == 4
    monkeypatch.delenv("OPENCODE_CHANGED_FILES_FILE")
    norm.current_changed_files.cache_clear()

    request_changes = tmp_path / "request.json"
    request_changes.write_text(
        json.dumps(control(result="REQUEST_CHANGES", findings=[finding()])),
        encoding="utf-8",
    )
    assert check_structural_approval(request_changes) == 0

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
    assert check_structural_approval(generic_deflection) == 4


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
    assert (
        norm.valid_control(control(result="REQUEST_CHANGES", findings=[]), **kwargs)
        is None
    )
    assert norm.valid_control(control(reason="No changed files"), **kwargs) is None
    assert (
        norm.valid_control(
            control(
                reason="No source path",
                summary=FULL_SUMMARY.replace("scripts/ci/example.py", "source file"),
            ),
            **kwargs,
        )
        is None
    )
    assert (
        norm.valid_control(control(summary="scripts/ci/example.py"), **kwargs) is None
    )
    assert (
        norm.valid_control(
            control(summary=FULL_SUMMARY.replace("100%", "99%", 1)), **kwargs
        )
        is None
    )
    assert (
        norm.valid_control(
            control(
                summary=(
                    FULL_SUMMARY + "\nModel outcomes: primary=failed, fallback=failed, "
                    "second_fallback=failed, catalog_fallback=failed."
                )
            ),
            **kwargs,
        )
        is None
    )

    request = control(result="REQUEST_CHANGES", findings=[finding()])
    assert norm.valid_control(dict(request, findings=["bad"]), **kwargs) is None
    assert (
        norm.valid_control(dict(request, findings=[finding(line=True)]), **kwargs)
        is None
    )
    assert (
        norm.valid_control(dict(request, findings=[finding(line=0)]), **kwargs) is None
    )
    assert (
        norm.valid_control(dict(request, findings=[finding(line="10")]), **kwargs)
        is None
    )
    assert (
        norm.valid_control(dict(request, findings=[finding(title="")]), **kwargs)
        is None
    )
    invalid_finding = finding()
    invalid_finding.pop("severity")
    assert (
        norm.valid_control(dict(request, findings=[invalid_finding]), **kwargs) is None
    )
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


def test_valid_control_canonicalizes_known_safe_finding_field_drift():
    kwargs = {
        "expected_head_sha": "head",
        "expected_run_id": "run",
        "expected_run_attempt": "attempt",
    }

    aliased = finding(priority="P1")
    del aliased["severity"]
    normalized = norm.valid_control(
        control(result="REQUEST_CHANGES", findings=[aliased]), **kwargs
    )
    assert normalized is not None
    assert normalized["findings"][0]["severity"] == "P1"
    assert "priority" not in normalized["findings"][0]

    diffless = finding()
    del diffless["suggested_diff"]
    assert (
        norm.valid_control(
            control(result="REQUEST_CHANGES", findings=[diffless]), **kwargs
        )
        is None
    )

    blank_diff = finding(suggested_diff="  ")
    assert (
        norm.valid_control(
            control(result="REQUEST_CHANGES", findings=[blank_diff]), **kwargs
        )
        is None
    )

    canonical_severity_wins = finding(priority="P2")
    normalized = norm.valid_control(
        control(result="REQUEST_CHANGES", findings=[canonical_severity_wins]),
        **kwargs,
    )
    assert normalized is not None
    assert normalized["findings"][0]["severity"] == "HIGH"
    assert "priority" not in normalized["findings"][0]

    blank_alias = finding(priority="   ")
    del blank_alias["severity"]
    assert (
        norm.valid_control(
            control(result="REQUEST_CHANGES", findings=[blank_alias]), **kwargs
        )
        is None
    )

    no_remedy = finding(fix_direction="", suggested_diff="")
    assert (
        norm.valid_control(
            control(result="REQUEST_CHANGES", findings=[no_remedy]), **kwargs
        )
        is None
    )


def test_approval_gate_rejects_prose_fix_direction_without_suggested_diff(tmp_path):
    bash_command = shutil.which("bash")
    if bash_command is None:
        pytest.skip("bash is unavailable")
    try:
        subprocess.run(
            [bash_command, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        pytest.skip(f"bash is not usable for this regression test: {exc}")

    repo_root = Path(__file__).resolve().parents[1]
    gate_script = repo_root / "scripts" / "ci" / "opencode_review_approve_gate.sh"
    control_data = control(
        result="REQUEST_CHANGES",
        findings=[finding(fix_direction="Restore the guard.")],
    )
    del control_data["findings"][0]["suggested_diff"]
    comment_file = tmp_path / "comment.md"
    comment_file.write_text(
        "\n".join(
            [
                "<!-- opencode-review-gate head_sha=head run_id=run run_attempt=attempt -->",
                "<!-- opencode-review-control-v1",
                json.dumps(control_data),
                "-->",
                "",
            ]
        ),
        encoding="utf-8",
    )

    completed_process = subprocess.run(
        [
            bash_command,
            str(gate_script),
            "head",
            "run",
            "attempt",
            str(comment_file),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert completed_process.returncode == 4
    assert completed_process.stdout.strip() == "NO_CONCLUSION"
    assert (
        "finding 1 field suggested_diff must be a non-empty string"
        in completed_process.stderr
    )


def test_valid_control_rejects_meaningless_approval_before_evidence_repair(
    tmp_path, monkeypatch
):
    evidence = tmp_path / "opencode-review-evidence.md"
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
    norm.current_changed_files.cache_clear()
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))
    seal_artifacts(tmp_path, tmp_path / "opencode-changed-files.txt", evidence)

    repaired = norm.valid_control(
        control(reason="x", summary="y"),
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    )

    assert repaired is None


def test_valid_control_accepts_model_confirms_with_bounded_current_head_receipt(
    tmp_path, monkeypatch
):
    evidence = tmp_path / "opencode-review-evidence.md"
    evidence.write_text(
        """\
# OpenCode bounded PR review evidence

## CodeGraph evidence

The workflow initialized CodeGraph before this evidence file was built.

## Coverage execution evidence

## Coverage Decision

- Result: PASS
- Test evidence: supported repository test suites passed
- Docstring evidence: configured repository docstring gates passed or docstring coverage was advisory

## Changed files

M\tsrc/main/java/example/LogSanitizer.java
M\tsrc/test/java/example/LogSanitizerTest.java
""",
        encoding="utf-8",
    )
    changed_files = tmp_path / "opencode-changed-files.txt"
    changed_files.write_text(
        "src/main/java/example/LogSanitizer.java\n"
        "src/test/java/example/LogSanitizerTest.java\n",
        encoding="utf-8",
    )
    for path in (
        "src/main/java/example/LogSanitizer.java",
        "src/test/java/example/LogSanitizerTest.java",
    ):
        source_path = tmp_path / path
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            "\n".join(f"line {line}" for line in range(1, 65)),
            encoding="utf-8",
        )
    monkeypatch.setenv("OPENCODE_EVIDENCE_FILE", str(evidence))
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))
    monkeypatch.setenv("OPENCODE_REQUIRE_ADVERSARIAL_VALIDATION", "true")
    seal_artifacts(tmp_path, changed_files, evidence)
    norm.current_changed_files.cache_clear()

    candidate = control(
        reason=(
            "src/main/java/example/LogSanitizer.java hardens log input and adds "
            "a regression test."
        ),
        summary=FULL_SUMMARY.replace(
            "scripts/ci/example.py",
            "src/main/java/example/LogSanitizer.java",
        ),
        adversarial_validation={
            "status": "passed",
            "probes": [
                {
                    "path": "src/main/java/example/LogSanitizer.java",
                    "line": 20,
                    "hypothesis": "A line break bypasses sanitization.",
                    "attack_or_counterexample": "Pass CR, LF, and Unicode separators.",
                    "evidence": (
                        "Test at src/main/java/example/LogSanitizer.java:20 confirms "
                        "every separator is replaced. " + source_line_receipt("line 20")
                    ),
                    "outcome": "falsified",
                },
                {
                    "path": "src/test/java/example/LogSanitizerTest.java",
                    "line": 40,
                    "hypothesis": "The regression test omits a control character.",
                    "attack_or_counterexample": "Compare the test input with the sanitizer replacements.",
                    "evidence": (
                        "Source trace at src/test/java/example/LogSanitizerTest.java:40 "
                        "confirms all replacements are asserted. "
                        + source_line_receipt("line 40")
                    ),
                    "outcome": "falsified",
                },
            ],
            "residual_risk": "Only characters outside the documented sanitizer contract remain.",
        },
    )

    repaired = norm.valid_control(
        candidate,
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    )

    assert repaired is not None
    assert "supported repository test suites passed" in repaired["summary"]


def test_valid_control_repairs_summary_from_invalid_utf8_evidence(
    tmp_path, monkeypatch
):
    evidence = tmp_path / "opencode-review-evidence.md"
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
    changed_files = tmp_path / "opencode-changed-files.txt"
    changed_files.write_text(
        "scripts/ci/opencode_review_normalize_output.py\n",
        encoding="utf-8",
    )
    norm.current_changed_files.cache_clear()
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))
    seal_artifacts(tmp_path, changed_files, evidence)

    repaired = norm.valid_control(
        control(
            reason=(
                "Reviewed current-head changed-file evidence in "
                "scripts/ci/opencode_review_normalize_output.py."
            ),
            summary=FULL_SUMMARY.replace(
                "scripts/ci/example.py",
                "scripts/ci/opencode_review_normalize_output.py",
            ),
        ),
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    )

    assert repaired is not None
    assert "scripts/ci/opencode_review_normalize_output.py" in repaired["summary"]
    assert norm.mentions_verification_posture(repaired["reason"], repaired["summary"])
    assert norm.mentions_full_coverage(repaired["reason"], repaired["summary"])


def test_valid_control_rejects_fragile_approval_reason_before_evidence_repair(
    tmp_path, monkeypatch
):
    evidence = tmp_path / "opencode-review-evidence.md"
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
    norm.current_changed_files.cache_clear()
    monkeypatch.setenv("OPENCODE_EVIDENCE_FILE", str(evidence))
    monkeypatch.delenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", raising=False)
    changed_files = tmp_path / "opencode-changed-files.txt"
    changed_files.write_text(".github/workflows/r.yml\n", encoding="utf-8")
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))
    seal_artifacts(tmp_path, changed_files, evidence)
    norm.current_changed_files.cache_clear()

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

    assert repaired is None


def test_valid_control_rejects_invalid_coverage_labels_before_evidence_repair(
    tmp_path, monkeypatch
):
    evidence = tmp_path / "opencode-review-evidence.md"
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
    changed_files = tmp_path / "opencode-changed-files.txt"
    changed_files.write_text(
        "scripts/ci/opencode_review_normalize_output.py\n"
        "tests/test_opencode_review_normalize_output.py\n",
        encoding="utf-8",
    )
    norm.current_changed_files.cache_clear()
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))
    seal_artifacts(tmp_path, changed_files, evidence)

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

    assert repaired is None


def test_valid_control_rejects_contradictory_changed_file_kind_claims(
    tmp_path, monkeypatch
):
    evidence = tmp_path / "opencode-review-evidence.md"
    changed_files = tmp_path / "opencode-changed-files.txt"
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
    norm.current_changed_files.cache_clear()
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))
    seal_artifacts(tmp_path, changed_files, evidence)
    norm.current_changed_files.cache_clear()

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

    assert repaired is None


def test_valid_control_rejects_material_trivialization(tmp_path, monkeypatch):
    evidence = tmp_path / "opencode-review-evidence.md"
    changed_files = tmp_path / "opencode-changed-files.txt"
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
    norm.current_changed_files.cache_clear()
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))
    monkeypatch.setenv("OPENCODE_CHANGED_FILES_FILE", str(changed_files))
    seal_artifacts(tmp_path, changed_files, evidence)
    norm.current_changed_files.cache_clear()

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

    assert repaired is None


def test_valid_control_does_not_repair_unsafe_or_unproven_approval(
    tmp_path, monkeypatch
):
    evidence = tmp_path / "opencode-review-evidence.md"
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
    norm.current_changed_files.cache_clear()
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))
    seal_artifacts(tmp_path, tmp_path / "opencode-changed-files.txt", evidence)
    kwargs = {
        "expected_head_sha": "head",
        "expected_run_id": "run",
        "expected_run_attempt": "attempt",
    }

    assert norm.valid_control(control(reason="No changed files"), **kwargs) is None
    assert (
        norm.valid_control(control(summary="No blockers were found."), **kwargs) is None
    )


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
    assert norm.claimed_runtime_tool(summary) == ""

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
    assert not norm.mentions_full_coverage("", no_source_summary)

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

    evidence = tmp_path / "opencode-review-evidence.md"
    evidence.write_text("placeholder", encoding="utf-8")
    norm.current_changed_files.cache_clear()
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))
    seal_artifacts(tmp_path, tmp_path / "opencode-changed-files.txt", evidence)
    original_read_text = norm.Path.read_text

    def raise_for_evidence(path, *args, **kwargs):
        if path == evidence:
            raise OSError("cannot read evidence")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(norm.Path, "read_text", raise_for_evidence)
    assert norm.repair_approval_summary("reason", "summary") == "summary"


def test_approval_repair_summary_emits_korean_language_evidence(monkeypatch):
    """Cover the trusted Korean-language repair text without model translation."""
    monkeypatch.setattr(norm, "preferred_review_language", lambda: "korean")
    repaired = norm.build_approval_repair_summary(
        "scripts/ci/example.py를 검토했습니다.",
        """\
## Coverage execution evidence
- Result: PASS
- Test coverage: 100%
- Docstring coverage: 100%
## Changed files
M\tscripts/ci/example.py
""",
    )
    assert repaired is not None
    assert "한국어 리뷰 언어 계약" in repaired


def test_repair_approval_reason_fails_safe_when_evidence_is_unusable(
    tmp_path, monkeypatch
):
    """Keep or conservatively repair reasons when bounded evidence degrades."""
    evidence = tmp_path / "opencode-review-evidence.md"
    evidence.write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))
    seal_artifacts(tmp_path, tmp_path / "opencode-changed-files.txt", evidence)

    monkeypatch.setattr(norm, "mentions_actual_changed_file", lambda *_args: False)
    assert norm.repair_approval_reason("original", FULL_SUMMARY) == "original"

    monkeypatch.setattr(norm, "mentions_actual_changed_file", lambda *_args: True)
    monkeypatch.setattr(norm, "mentions_verification_posture", lambda *_args: True)
    monkeypatch.setattr(norm, "mentions_full_coverage", lambda *_args: True)
    monkeypatch.setattr(norm, "read_text_lossy", lambda _path: None)
    repaired = norm.repair_approval_reason("No source changes", FULL_SUMMARY)
    assert "the current changed files" in repaired


@pytest.mark.parametrize(
    ("gate_name", "first_value", "second_value"),
    [
        ("mentions_actual_changed_file", True, False),
        ("mentions_verification_posture", True, False),
        ("mentions_full_coverage", True, False),
        ("contradicts_changed_file_kinds", False, True),
        ("contradicts_material_changed_file_scope", False, True),
        ("model_failure_approval_phrase", "", "model failed"),
    ],
)
def test_valid_control_rechecks_every_approval_gate_after_repair(
    monkeypatch, gate_name, first_value, second_value
):
    """Reject a repair that invalidates any already-checked approval invariant."""
    values = iter((first_value, second_value))
    monkeypatch.setattr(norm, gate_name, lambda *_args: next(values))
    monkeypatch.setattr(
        norm, "repair_approval_summary", lambda _reason, summary: summary
    )
    monkeypatch.setattr(norm, "repair_approval_reason", lambda reason, _summary: reason)

    assert (
        norm.valid_control(
            control(),
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is None
    )


def test_approval_language_contract_cannot_be_repaired_from_evidence(
    tmp_path, monkeypatch
):
    evidence = tmp_path / "opencode-review-evidence.md"
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
    changed_files = tmp_path / "opencode-changed-files.txt"
    changed_files.write_text(
        ".jules/sentinel.md\nfrontend/src/components/EmailDetail.test.tsx\n",
        encoding="utf-8",
    )
    norm.current_changed_files.cache_clear()
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))
    seal_artifacts(tmp_path, changed_files, evidence)

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

    assert reviewed is None


def test_request_changes_still_enforces_korean_language_contract(tmp_path, monkeypatch):
    evidence = tmp_path / "opencode-review-evidence.md"
    evidence.write_text(
        """\
## Review language evidence
Preferred review language: `Korean`
""",
        encoding="utf-8",
    )
    norm.current_changed_files.cache_clear()
    monkeypatch.setenv("OPENCODE_APPROVAL_REPAIR_EVIDENCE_FILE", str(evidence))
    seal_artifacts(tmp_path, tmp_path / "opencode-changed-files.txt", evidence)

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
    ]
    assert norm.iter_json_objects("prefix {  } suffix") == [{}]
    assert norm.iter_json_objects("prefix {not json}") == []
    assert norm.iter_json_objects('prefix {"bad": } suffix') == []
    assert norm.iter_json_objects("no json here") == []


@pytest.mark.parametrize("approve_first", [True, False])
def test_main_rejects_conflicting_current_run_controls_without_rewriting(
    tmp_path, capsys, approve_first
):
    """Control order cannot hide a contradictory current-run conclusion."""
    approve = control()
    request_changes = control(
        result="REQUEST_CHANGES",
        reason="A current-head defect requires a change.",
        summary="A source-backed blocking defect was reproduced.",
        findings=[finding()],
    )
    controls = [approve, request_changes]
    if not approve_first:
        controls.reverse()
    original = "review prose\n" + "\n".join(json.dumps(item) for item in controls)
    output = tmp_path / "conflicting-controls.txt"
    output.write_text(original, encoding="utf-8")

    assert norm.main(["normalizer", "head", "run", "attempt", str(output)]) == 4
    assert output.read_text(encoding="utf-8") == original
    assert "expected exactly one top-level current-run control candidate" in (
        capsys.readouterr().err
    )


def test_main_rejects_repeated_identical_current_run_controls(tmp_path, capsys):
    """Repeating the same control cannot manufacture unambiguous evidence."""
    encoded = json.dumps(control())
    original = f"{encoded}\n{encoded}\n"
    output = tmp_path / "duplicate-controls.txt"
    output.write_text(original, encoding="utf-8")

    assert norm.main(["normalizer", "head", "run", "attempt", str(output)]) == 4
    assert output.read_text(encoding="utf-8") == original
    assert "found 2" in capsys.readouterr().err


def test_main_rejects_nested_current_run_control_without_rewriting(tmp_path, capsys):
    """A valid control nested in model prose is never promoted for publication."""
    original = json.dumps({"review": "model prose", "control": control()})
    output = tmp_path / "nested-control.txt"
    output.write_text(original, encoding="utf-8")

    assert norm.main(["normalizer", "head", "run", "attempt", str(output)]) == 4
    assert output.read_text(encoding="utf-8") == original
    assert "no top-level current-run control" in capsys.readouterr().err


def test_main_rejects_second_malformed_current_run_candidate(tmp_path, capsys):
    """A malformed second current-run claim makes the provider stream ambiguous."""
    malformed = {
        "head_sha": "head",
        "run_id": "run",
        "run_attempt": "attempt",
        "result": "APPROVE",
    }
    original = f"{json.dumps(control())}\n{json.dumps(malformed)}\n"
    output = tmp_path / "malformed-second-control.txt"
    output.write_text(original, encoding="utf-8")

    assert norm.main(["normalizer", "head", "run", "attempt", str(output)]) == 4
    assert output.read_text(encoding="utf-8") == original
    assert "found 2" in capsys.readouterr().err


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
    output.write_text(
        "prefix\n" + json.dumps(control_data) + "\nsuffix", encoding="utf-8"
    )
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
    assert (
        parsed_control["findings"][0]["problem"]
        == "--> injected string with < and > and &"
    )


def test_main_normalizes_valid_output_and_reports_failures(tmp_path, capsys):
    output = tmp_path / "opencode.txt"
    output.write_text("prefix\n" + json.dumps(control()) + "\nsuffix", encoding="utf-8")
    assert norm.main(["prog", "head", "run", "attempt", str(output)]) == 0
    normalized_text = output.read_text(encoding="utf-8")
    assert "opencode-review-control-v1" in normalized_text
    assert "\\u003c" not in normalized_text

    injection_output = tmp_path / "injection.txt"
    injection_control = control()
    injection_control["reason"] = (
        "scripts/ci/example.py is source-backed. <script>alert(1)</script> & <!-- -->"
    )
    injection_output.write_text(
        "prefix\n" + json.dumps(injection_control) + "\nsuffix", encoding="utf-8"
    )
    assert norm.main(["prog", "head", "run", "attempt", str(injection_output)]) == 0
    normalized_injection_text = injection_output.read_text(encoding="utf-8")
    assert (
        "\\u003cscript\\u003ealert(1)\\u003c/script\\u003e \\u0026 \\u003c!-- --\\u003e"
        in normalized_injection_text
    )

    invalid_utf8 = tmp_path / "invalid-utf8.txt"
    invalid_utf8.write_bytes(
        b"\xea invalid prefix\n" + json.dumps(control()).encode("utf-8")
    )
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
    assert (
        norm.main(
            [
                "prog",
                "--check-structural-approval",
                "head",
                "run",
                "attempt",
                str(approval),
            ]
        )
        == 0
    )

    generic_failed_check = tmp_path / "generic-failed-check.json"
    generic_failed_check.write_text(
        json.dumps(
            control(
                result="REQUEST_CHANGES",
                summary=(
                    "No deterministic missing-string markers or Strix report locations "
                    "were recognized."
                ),
                findings=[
                    finding(
                        problem="No deterministic missing-string markers were found."
                    )
                ],
            )
        ),
        encoding="utf-8",
    )
    assert (
        norm.main(
            [
                "prog",
                "--check-structural-approval",
                "head",
                "run",
                "attempt",
                str(generic_failed_check),
            ]
        )
        == 4
    )
    assert "non-actionable failed-check deflection" in capsys.readouterr().err


def test_review_language_contract_rejects_english_only_korean_pr(
    tmp_path, monkeypatch, capsys
):
    evidence = tmp_path / "opencode-review-evidence.md"
    evidence.write_text(
        "## Review language evidence\n\n- Preferred review language: `Korean`\n",
        encoding="utf-8",
    )
    norm.current_changed_files.cache_clear()
    monkeypatch.setenv("OPENCODE_EVIDENCE_FILE", str(evidence))
    seal_artifacts(tmp_path, tmp_path / "opencode-changed-files.txt", evidence)

    assert (
        norm.valid_control(
            control(),
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is None
    )

    korean_control = control(
        reason="scripts/ci/example.py 검토 완료.",
        summary=FULL_SUMMARY + "\n한국어 리뷰 문체를 유지했습니다.",
    )
    assert (
        norm.valid_control(
            korean_control,
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
        )
        is not None
    )

    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps(control()), encoding="utf-8")
    assert (
        norm.main(
            [
                "prog",
                "--check-structural-approval",
                "head",
                "run",
                "attempt",
                str(approval),
            ]
        )
        == 4
    )
    assert "preferred PR language" in capsys.readouterr().err


def test_main_normalizes_and_escapes_html_markers(tmp_path):
    output = tmp_path / "opencode.txt"
    control_data = control(
        reason="Malicious --> comment",
        summary=FULL_SUMMARY + "\nBreakout <script>alert(1)</script>",
    )
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


def test_main_logs_the_exact_control_rejection_reason(tmp_path, capsys):
    output = tmp_path / "model-output.md"
    output.write_text(
        json.dumps(
            control(
                adversarial_validation={
                    "status": "passed",
                    "probes": [
                        {
                            "path": "scripts/ci/example.py",
                            "line": 7,
                            "hypothesis": "The stale head is accepted.",
                            "attack_or_counterexample": "Submit a stale head.",
                            "evidence": "Source inspection at scripts/ci/example.py:7 mentions the branch.",
                            "outcome": "falsified",
                        },
                        {
                            "path": "scripts/ci/example.py",
                            "line": 8,
                            "hypothesis": "The current head is rejected.",
                            "attack_or_counterexample": "Submit the current head.",
                            "evidence": "Focused pytest for scripts/ci/example.py:8 passed with exit code 0.",
                            "outcome": "falsified",
                        },
                    ],
                    "residual_risk": "External provider availability remains variable.",
                }
            )
        ),
        encoding="utf-8",
    )

    assert norm.main(["normalizer", "head", "run", "attempt", str(output)]) == 4
    stderr = capsys.readouterr().err
    assert "CONTROL_REJECTED candidate=1" in stderr
    assert "adversarial probe 1 evidence must state the observed proof result" in stderr


def test_valid_control_repairs_trusted_model_probe_source_bindings(
    tmp_path, monkeypatch
):
    """Substantive LLM probes survive formatting drift without weaker evidence."""
    require_adversarial_validation(tmp_path, monkeypatch, "scripts/ci/example.py")
    validation = adversarial_validation()
    for probe in validation["probes"]:
        probe["evidence"] = (
            "Focused regression command passed and disproved the adversarial hypothesis. "
            + source_line_receipt(f"line {probe['line']}")
        )

    normalized = norm.valid_control(
        control(adversarial_validation=validation),
        expected_head_sha="head",
        expected_run_id="run",
        expected_run_attempt="attempt",
    )

    assert normalized is not None
    for index, probe in enumerate(normalized["adversarial_validation"]["probes"]):
        line = 7 + index
        assert f"scripts/ci/example.py:{line}" in probe["evidence"]
        assert source_line_receipt(f"line {line}") in probe["evidence"]
        assert probe["evidence"].count("source-line-sha256=") == 1


def test_probe_binding_repair_does_not_invent_independent_observation(
    tmp_path, monkeypatch
):
    """Canonical source binding cannot turn unsupported model prose into approval."""
    require_adversarial_validation(tmp_path, monkeypatch, "scripts/ci/example.py")
    validation = adversarial_validation()
    for index, probe in enumerate(validation["probes"]):
        probe["evidence"] = (
            f"Description at scripts/ci/example.py:{7 + index} repeats the hypothesis. "
            + source_line_receipt(f"line {7 + index}")
        )
    reasons = []

    assert (
        norm.valid_control(
            control(adversarial_validation=validation),
            expected_head_sha="head",
            expected_run_id="run",
            expected_run_attempt="attempt",
            rejection_reasons=reasons,
        )
        is None
    )
    assert any("executed command" in reason for reason in reasons)


@pytest.mark.parametrize(
    "validation",
    [
        None,
        {"probes": None},
        {"probes": [None]},
        {"probes": [{"path": 7, "line": 1, "evidence": "command passed"}]},
        {"probes": [{"path": "scripts/ci/example.py", "line": True, "evidence": "command passed"}]},
        {"probes": [{"path": "scripts/ci/example.py", "line": 0, "evidence": "command passed"}]},
        {"probes": [{"path": "scripts/ci/example.py", "line": 7, "evidence": 9}]},
        {"probes": [{"path": "missing.py", "line": 7, "evidence": "command passed"}]},
        {
            "probes": [
                {
                    "path": "../secrets/key.py",
                    "line": 7,
                    "evidence": "command passed",
                }
            ]
        },
    ],
)
def test_probe_binding_repair_preserves_unrepairable_shapes(validation):
    """Malformed, unsafe, or unverifiable model evidence remains unchanged."""
    candidate = control(adversarial_validation=validation)
    assert norm.repair_adversarial_probe_source_bindings(candidate) is candidate
