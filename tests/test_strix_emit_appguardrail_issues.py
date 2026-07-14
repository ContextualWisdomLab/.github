"""Unit tests for the source-side Strix -> appguardrail issue emitter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import strix_emit_appguardrail_issues as emit

SOURCE_REPO = "ContextualWisdomLab/example-service"

SQLI_REPORT = """\
# Vulnerability Report

Model: github_models/openai/gpt-5
Title: SQL Injection in login handler
Severity: HIGH
CVSS Score: 8.1
CVSS Vector: CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H
Target: backend/app/auth.py
Endpoint: /api/login
Method: POST

Description:
User input is concatenated directly into a SQL query.

Impact:
An attacker can read or modify arbitrary rows.

Code Locations:
backend/app/auth.py:42-45

Remediation:
Use parameterized queries.
"""

# Bold-markdown variant with a /workspace-prefixed location.
XSS_REPORT = """\
## Reflected XSS in search page

- **Severity:** MEDIUM
- **CVSS Score:** 5.4
- **Target:** frontend/src/search.tsx
- **Endpoint:** /search
- **Method:** GET

**Description:** Query parameter is rendered without escaping.

**Code Locations**
/workspace/example-service/frontend/src/search.tsx:88

**Remediation:** Escape user-controlled output.
"""

# Critical finding with no code location at all.
NO_LOCATION_REPORT = """\
Title: Missing Content Security Policy
Severity: CRITICAL
Endpoint: all frontend pages
Description: No CSP header is set on any response.
Remediation: Add a restrictive Content-Security-Policy header.
"""

NOT_A_FINDING = """\
# Scan Notes

Some prose with no Title field.
"""


def write_run(tmp_path: Path, reports: dict[str, str], run_name: str = "run-1") -> Path:
    """Create a strix_runs/<run>/vulnerabilities tree and return the run dir."""
    run_dir = tmp_path / "strix_runs" / run_name
    vuln_dir = run_dir / "vulnerabilities"
    vuln_dir.mkdir(parents=True)
    for name, text in reports.items():
        (vuln_dir / name).write_text(text, encoding="utf-8")
    return tmp_path / "strix_runs"


def make_context(**overrides) -> emit.EmitContext:
    """Build an EmitContext with sensible test defaults.

    Defaults to a full-repo scan (``scan_scope=SCOPE_FULL``) so close-on-fix
    reconciliation is exercised; override ``scan_scope`` to model a PR-scoped run.
    """
    values = {
        "source_repo": SOURCE_REPO,
        "pr_number": "42",
        "head_sha": "a" * 40,
        "run_url": "https://github.com/ContextualWisdomLab/.github/actions/runs/1",
        "scan_complete": True,
        "scan_scope": emit.SCOPE_FULL,
    }
    values.update(overrides)
    return emit.EmitContext(**values)


class FakeClient:
    """In-memory stand-in for GitHubIssueClient used to assert executed ops."""

    def __init__(self, existing: list[dict] | None = None) -> None:
        self.existing = existing or []
        self.created: list[dict] = []
        self.updated: list[dict] = []
        self.comments: list[dict] = []
        self.closed: list[int] = []
        self.ensured_labels: list[str] = []

    def list_scope_issues(self, repo_short):
        return self.existing

    def ensure_labels(self, labels):
        self.ensured_labels.extend(labels)

    def create_issue(self, title, body, labels):
        self.created.append({"title": title, "body": body, "labels": list(labels)})

    def update_issue(self, number, body, labels):
        self.updated.append({"number": number, "body": body, "labels": list(labels)})

    def comment_issue(self, number, comment):
        self.comments.append({"number": number, "comment": comment})

    def close_issue(self, number, comment):
        self.comments.append({"number": number, "comment": comment})
        self.closed.append(number)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #


def test_parses_all_fields_from_plain_report():
    """A plain-text report yields a fully populated finding."""
    finding = emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO, "sqli.md")
    assert finding is not None
    assert finding.title == "SQL Injection in login handler"
    assert finding.severity == "HIGH"
    assert finding.cvss == "8.1"
    assert finding.cvss_vector.startswith("CVSS:3.1")
    assert finding.endpoint == "/api/login"
    assert finding.method == "POST"
    assert finding.model == "github_models/openai/gpt-5"
    assert finding.code_location == "backend/app/auth.py:42-45"
    assert "parameterized" in finding.remediation
    assert "arbitrary rows" in finding.impact


def test_parses_bold_markdown_and_normalizes_workspace_location():
    """Bold-markdown fields parse and /workspace prefixes are stripped for dedup."""
    finding = emit.parse_finding_markdown(XSS_REPORT, SOURCE_REPO, "xss.md")
    assert finding is not None
    assert finding.title == "Reflected XSS in search page"
    assert finding.severity == "MEDIUM"
    assert (
        finding.code_location == "/workspace/example-service/frontend/src/search.tsx:88"
    )
    assert finding.normalized_location == "frontend/src/search.tsx:88"
    assert finding.description == "Query parameter is rendered without escaping."
    assert finding.remediation == "Escape user-controlled output."


def test_parses_heading_sections_and_code_locations():
    """Markdown heading sections preserve evidence and location details."""
    report = """\
## Unsafe deserialization

Severity: HIGH

### Description
Untrusted bytes are decoded into an executable object.

### Impact
An attacker can execute arbitrary code.

### Code Locations
backend/codec.py:17-21

### Remediation
Use a data-only serialization format.
"""
    finding = emit.parse_finding_markdown(report, SOURCE_REPO, "heading.md")

    assert finding is not None
    assert finding.title == "Unsafe deserialization"
    assert finding.code_location == "backend/codec.py:17-21"
    assert (
        finding.description == "Untrusted bytes are decoded into an executable object."
    )
    assert finding.impact == "An attacker can execute arbitrary code."
    assert finding.remediation == "Use a data-only serialization format."


def test_no_location_finding_parses_with_empty_location():
    """A finding without any code location keeps an empty location but still parses."""
    finding = emit.parse_finding_markdown(NO_LOCATION_REPORT, SOURCE_REPO, "csp.md")
    assert finding is not None
    assert finding.severity == "CRITICAL"
    assert finding.code_location == ""
    assert finding.normalized_location == ""


def test_non_finding_report_returns_none():
    """Reports without a Title are not findings."""
    assert emit.parse_finding_markdown(NOT_A_FINDING, SOURCE_REPO) is None


def test_parse_run_dir_dedups_duplicate_model_reports(tmp_path):
    """Duplicate reports of the same vulnerability collapse to one finding."""
    runs = write_run(
        tmp_path,
        {
            "a.md": SQLI_REPORT,
            "b.md": SQLI_REPORT,  # duplicate finding from another model
            "c.md": XSS_REPORT,
            "d.md": NO_LOCATION_REPORT,
            "e.md": NOT_A_FINDING,
        },
    )
    findings = emit.parse_run_dir(runs, SOURCE_REPO)
    assert len(findings) == 3
    titles = {f.title for f in findings}
    assert "SQL Injection in login handler" in titles


# --------------------------------------------------------------------------- #
# Hashing
# --------------------------------------------------------------------------- #


def test_dedup_hash_is_stable_and_whitespace_insensitive():
    """Cosmetic title whitespace does not change the dedup hash; location does."""
    base = emit.finding_dedup_hash(
        SOURCE_REPO, "SQL Injection", "backend/app/auth.py:42-45"
    )
    wrapped = emit.finding_dedup_hash(
        SOURCE_REPO, "SQL   Injection\n", "backend/app/auth.py:42-45"
    )
    workspace = emit.finding_dedup_hash(
        SOURCE_REPO,
        "SQL Injection",
        "/workspace/example-service/backend/app/auth.py:42-45",
    )
    other = emit.finding_dedup_hash(
        SOURCE_REPO, "SQL Injection", "backend/app/auth.py:99"
    )
    assert base == wrapped == workspace
    assert base != other
    assert len(base) == 64


def test_short_hash_length():
    """Short hash is the configured prefix length."""
    finding = emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)
    assert len(finding.short_hash) == emit.SHORT_HASH_LENGTH
    assert finding.finding_hash.startswith(finding.short_hash)


# --------------------------------------------------------------------------- #
# Issue content
# --------------------------------------------------------------------------- #


def test_issue_title_and_labels():
    """Issue title and labels follow the documented format."""
    finding = emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)
    title = emit.build_issue_title(finding)
    assert (
        title
        == "[strix] example-service HIGH: SQL Injection in login handler (backend/app/auth.py:42-45)"
    )
    labels = emit.build_issue_labels(finding)
    assert "strix" in labels
    assert "security" in labels
    assert "repo:example-service" in labels
    assert "severity:high" in labels
    assert all(not label.startswith("strix-finding:") for label in labels)


def test_issue_body_carries_markers():
    """Issue body embeds the finding/severity/location reconciliation markers."""
    finding = emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)
    body = emit.build_issue_body(finding, make_context())
    assert emit.marker_value(body, emit.FINDING_MARKER_PREFIX) == finding.finding_hash
    assert emit.marker_value(body, emit.SEVERITY_MARKER_PREFIX) == "HIGH"
    assert (
        emit.marker_value(body, emit.LOCATION_MARKER_PREFIX)
        == "backend/app/auth.py:42-45"
    )
    assert "pull/42" in body
    assert ("commit/" + "a" * 40) in body


def test_sparse_issue_body_omits_absent_optional_sections():
    """A sparse finding remains useful without inventing optional evidence."""
    finding = emit.Finding(
        source_repo=SOURCE_REPO,
        title="Sparse report",
        severity="MEDIUM",
        code_location="",
    )
    body = emit.build_issue_body(
        finding,
        make_context(pr_number="", head_sha="", run_url=""),
    )

    assert "(no code location reported)" in body
    assert "CVSS score" not in body
    assert "CVSS vector" not in body
    assert "Target:" not in body
    assert "Detected by model" not in body
    assert "### Impact" not in body
    assert "Source repository" in body


def test_issue_finding_hash_prefers_marker_then_label():
    """Existing-issue hash extraction reads the marker, falling back to the label."""
    finding = emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)
    body = emit.build_issue_body(finding, make_context())
    assert emit.issue_finding_hash({"body": body}) == finding.finding_hash
    label_only = {
        "body": "",
        "labels": [{"name": f"strix-finding:{finding.short_hash}"}],
    }
    assert emit.issue_finding_hash(label_only) == finding.short_hash
    assert emit.issue_finding_hash({"body": "", "labels": ["unrelated"]}) == ""
    assert emit._issue_label_names({"labels": [{}, "", None]}) == []


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #


def existing_issue_for(report: str, *, number: int, state: str = "open", context=None):
    """Build an existing-issue dict mirroring what the tracker would return."""
    finding = emit.parse_finding_markdown(report, SOURCE_REPO)
    body = emit.build_issue_body(finding, context or make_context())
    return {
        "number": number,
        "state": state,
        "title": emit.build_issue_title(finding),
        "body": body,
        "labels": [{"name": name} for name in emit.build_issue_labels(finding)],
    }


def test_plan_creates_issue_for_new_finding():
    """A finding with no existing issue plans a create."""
    findings = [emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)]
    ops = emit.plan_operations(findings, [], make_context(scan_complete=False))
    assert len(ops) == 1
    assert ops[0].action == "create"
    assert "strix" in ops[0].labels


def test_plan_ignores_existing_issues_without_finding_identity():
    """Unrelated tracker issues cannot suppress a new Strix finding."""
    finding = emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)
    unrelated = {"number": 99, "state": "open", "body": "", "labels": []}

    ops = emit.plan_operations([finding], [unrelated], make_context())

    assert [operation.action for operation in ops] == ["create"]


def test_plan_updates_without_comment_when_unchanged():
    """An unchanged finding refreshes the body but does not comment."""
    finding = emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)
    existing = existing_issue_for(SQLI_REPORT, number=7)
    ops = emit.plan_operations([finding], [existing], make_context())
    actions = [op.action for op in ops]
    assert actions == ["update"]
    assert ops[0].issue_number == 7


def test_plan_comments_when_severity_changes():
    """A severity change on an existing finding plans an update plus a comment."""
    # Existing issue recorded HIGH; new run reports the same finding as CRITICAL.
    existing = existing_issue_for(SQLI_REPORT, number=7)
    escalated = SQLI_REPORT.replace("Severity: HIGH", "Severity: CRITICAL")
    finding = emit.parse_finding_markdown(escalated, SOURCE_REPO)
    ops = emit.plan_operations([finding], [existing], make_context())
    actions = [op.action for op in ops]
    assert actions == ["update", "comment"]
    assert "severity" in ops[1].comment.lower()


def test_plan_reopens_closed_issue_when_finding_returns():
    """A closed issue whose finding reappears is updated back to open."""
    finding = emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)
    existing = existing_issue_for(SQLI_REPORT, number=7, state="closed")
    ops = emit.plan_operations([finding], [existing], make_context())
    assert ops[0].action == "update"
    assert "reopen" in ops[0].reason


def test_close_on_fix_closes_missing_open_issue_only_for_full_scope():
    """An open issue absent from a complete FULL-repo scan is closed.

    Close-on-fix is safe only for a whole-repo scan, which sees every finding;
    this test pins that a clean full scan closes the stale issue.
    """
    current = emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)
    stale = existing_issue_for(XSS_REPORT, number=9)  # not in current run
    live = existing_issue_for(SQLI_REPORT, number=7)
    context = make_context(scan_complete=True, scan_scope=emit.SCOPE_FULL)
    ops = emit.plan_operations([current], [live, stale], context)
    close_ops = [op for op in ops if op.action == "close"]
    assert len(close_ops) == 1
    assert close_ops[0].issue_number == 9
    assert ("a" * 40) in close_ops[0].comment


def test_pr_scoped_complete_scan_closes_nothing():
    """The scope guard: a completed PR-scoped scan never closes issues.

    A PR-scoped scan only inspects the PR's changed files, so a finding's
    absence means "outside this PR", not "fixed". Neither a zero-finding clean
    PR nor a subset scan may close still-valid open issues in untouched files.
    """
    stale = existing_issue_for(XSS_REPORT, number=9)
    live = existing_issue_for(SQLI_REPORT, number=7)
    # Zero findings (a clean PR): must not close every open Strix issue.
    zero_ops = emit.plan_operations(
        [], [live, stale], make_context(scan_complete=True, scan_scope=emit.SCOPE_PR)
    )
    assert all(op.action != "close" for op in zero_ops)
    # A subset scan that only re-reports one finding must not close the other.
    current = emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)
    subset_ops = emit.plan_operations(
        [current],
        [live, stale],
        make_context(scan_complete=True, scan_scope=emit.SCOPE_PR),
    )
    assert all(op.action != "close" for op in subset_ops)


def test_unknown_scope_complete_scan_closes_nothing():
    """An unknown/unset scope is treated as unsafe: close-on-fix stays off."""
    current = emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)
    stale = existing_issue_for(XSS_REPORT, number=9)
    context = make_context(scan_complete=True, scan_scope="unknown")
    assert context.close_on_fix_enabled is False
    ops = emit.plan_operations([current], [stale], context)
    assert all(op.action != "close" for op in ops)


def test_incomplete_scan_never_closes():
    """The close-on-fix guard: an incomplete scan closes nothing even at full scope."""
    current = emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)
    stale = existing_issue_for(XSS_REPORT, number=9)
    context = make_context(scan_complete=False, scan_scope=emit.SCOPE_FULL)
    assert context.close_on_fix_enabled is False
    ops = emit.plan_operations([current], [stale], context)
    assert all(op.action != "close" for op in ops)


def test_close_on_fix_ignores_already_closed_issues():
    """Already-closed stale issues are not re-closed."""
    current = emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)
    stale_closed = existing_issue_for(XSS_REPORT, number=9, state="closed")
    ops = emit.plan_operations(
        [current], [stale_closed], make_context(scan_complete=True)
    )
    assert all(op.action != "close" for op in ops)


# --------------------------------------------------------------------------- #
# Execution
# --------------------------------------------------------------------------- #


def test_execute_plan_dry_run_logs_without_mutation():
    """Dry-run logs each op and counts it, calling no client methods."""
    findings = [emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)]
    ops = emit.plan_operations(findings, [], make_context(scan_complete=False))
    messages: list[str] = []
    counts = emit.execute_plan(ops, None, dry_run=True, log=messages.append)
    assert counts["create"] == 1
    assert any("DRY-RUN" in m and "CREATE" in m for m in messages)


def test_execute_plan_applies_operations_via_client():
    """A live plan drives create/comment/close through the client."""
    context = make_context(scan_complete=True)
    current = emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)
    stale = existing_issue_for(XSS_REPORT, number=9, context=context)
    ops = emit.plan_operations([current], [stale], context)
    client = FakeClient()
    messages: list[str] = []
    counts = emit.execute_plan(ops, client, dry_run=False, log=messages.append)
    assert counts["create"] == 1
    assert counts["close"] == 1
    assert len(client.created) == 1
    assert client.closed == [9]


def test_execute_plan_applies_update_and_comment():
    """A severity escalation drives update + comment through the client."""
    existing = existing_issue_for(SQLI_REPORT, number=7)
    escalated = SQLI_REPORT.replace("Severity: HIGH", "Severity: CRITICAL")
    finding = emit.parse_finding_markdown(escalated, SOURCE_REPO)
    ops = emit.plan_operations([finding], [existing], make_context(scan_complete=False))
    client = FakeClient()
    counts = emit.execute_plan(ops, client, dry_run=False, log=lambda *_: None)
    assert counts["update"] == 1
    assert counts["comment"] == 1
    assert client.updated[0]["number"] == 7
    assert client.comments[0]["number"] == 7


def test_execute_plan_rejects_unknown_operation_fail_closed():
    """An unsupported mutation cannot be logged as a successful issue write."""
    operation = emit.Operation(
        action="rename",
        finding_hash="a" * 64,
        short_hash="a" * emit.SHORT_HASH_LENGTH,
        title="unsupported",
    )
    messages: list[str] = []

    counts = emit.execute_plan(
        [operation], FakeClient(), dry_run=False, log=messages.append
    )

    assert counts["error"] == 1
    assert counts.get("rename", 0) == 0
    assert any("unsupported issue operation" in message for message in messages)


def test_execute_plan_exposes_client_errors():
    """A failing operation is logged as an error and counted for fail-closed exit."""

    class BoomClient(FakeClient):
        def create_issue(self, title, body, labels):
            raise RuntimeError("token gho_deadbeefdeadbeefdeadbeef expired")

    findings = [emit.parse_finding_markdown(SQLI_REPORT, SOURCE_REPO)]
    ops = emit.plan_operations(findings, [], make_context(scan_complete=False))
    messages: list[str] = []
    counts = emit.execute_plan(ops, BoomClient(), dry_run=False, log=messages.append)
    assert counts["error"] == 1
    assert any(message.startswith("::error::") for message in messages)
    # Token must be scrubbed from the warning.
    assert all("gho_deadbeef" not in m for m in messages)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("validator", "value"),
    [
        (emit.validated_source_repo, "attacker/repo"),
        (emit.validated_issues_repo, "ContextualWisdomLab/not-appguardrail"),
        (emit.validated_pr_number, "0"),
        (emit.validated_head_sha, "short"),
        (emit.validated_run_url, "https://example.com/actions/runs/1"),
        (emit.validated_token_env, "GITHUB_TOKEN"),
    ],
)
def test_cli_validators_reject_untrusted_mutation_scope(validator, value):
    """CLI metadata cannot redirect issue writes or credential lookup."""
    with pytest.raises(emit.argparse.ArgumentTypeError):
        validator(value)


def test_validated_run_dir_rejects_symlink_missing_and_resolution_failure(
    tmp_path, monkeypatch
):
    """Report roots must be real directories with a resolvable trusted path."""
    missing = tmp_path / "missing"
    with pytest.raises(emit.argparse.ArgumentTypeError):
        emit.validated_run_dir(str(missing))

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(emit.argparse.ArgumentTypeError):
        emit.validated_run_dir(str(link))

    original_is_symlink = Path.is_symlink

    def fail_stat(path):
        if path == real:
            raise OSError("simulated stat failure")
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", fail_stat)
    with pytest.raises(emit.argparse.ArgumentTypeError, match="could not be resolved"):
        emit.validated_run_dir(str(real))


def test_cli_validators_accept_bounded_metadata(tmp_path):
    """Expected organization metadata passes without lossy rewriting."""
    assert emit.validated_source_repo(SOURCE_REPO) == SOURCE_REPO
    assert (
        emit.validated_issues_repo(emit.DEFAULT_ISSUES_REPO) == emit.DEFAULT_ISSUES_REPO
    )
    assert emit.validated_pr_number("42") == "42"
    assert emit.validated_head_sha("A" * 40) == "a" * 40
    run_url = "https://github.com/ContextualWisdomLab/.github/actions/runs/1"
    assert emit.validated_run_url(run_url) == run_url
    assert emit.validated_token_env(emit.DEFAULT_TOKEN_ENV) == emit.DEFAULT_TOKEN_ENV
    tmp_path.mkdir(exist_ok=True)
    assert emit.validated_run_dir(str(tmp_path)) == tmp_path.resolve()


def test_run_without_token_fails_closed(tmp_path, monkeypatch, capsys):
    """Without a token the live CLI fails and never claims collection succeeded."""
    runs = write_run(tmp_path, {"a.md": SQLI_REPORT, "b.md": XSS_REPORT})
    monkeypatch.delenv(emit.DEFAULT_TOKEN_ENV, raising=False)
    code = emit.run(
        [
            "--run-dir",
            str(runs),
            "--source-repo",
            SOURCE_REPO,
            "--pr-number",
            "42",
            "--head-sha",
            "a" * 40,
        ]
    )
    out = capsys.readouterr().out
    assert code == 2
    assert "::error::" in out
    assert "--dry-run explicitly" in out
    assert "Parsed 2 distinct" in out
    assert "close-on-fix is disabled" in out


def test_run_forced_dry_run_flag(tmp_path, monkeypatch, capsys):
    """--dry-run forces planning even when a token is present."""
    runs = write_run(tmp_path, {"a.md": SQLI_REPORT})
    monkeypatch.setenv(emit.DEFAULT_TOKEN_ENV, "gho_" + "x" * 30)
    code = emit.run(
        [
            "--run-dir",
            str(runs),
            "--source-repo",
            SOURCE_REPO,
            "--scan-complete",
            "--dry-run",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "DRY-RUN" in out


def test_run_filters_low_findings_and_rejects_unknown_severity(
    tmp_path, monkeypatch, capsys
):
    """Only Medium+ findings are filed; unknown severity blocks reconciliation."""
    low = SQLI_REPORT.replace("Severity: HIGH", "Severity: LOW")
    runs = write_run(tmp_path, {"low.md": low})
    assert (
        emit.run(["--run-dir", str(runs), "--source-repo", SOURCE_REPO, "--dry-run"])
        == 0
    )
    out = capsys.readouterr().out
    assert "0 meet the MEDIUM+ issue policy" in out
    assert "1 lower-severity" in out

    unknown_runs = write_run(
        tmp_path,
        {"unknown.md": SQLI_REPORT.replace("Severity: HIGH", "Severity: BOGUS")},
        "run-2",
    )
    assert (
        emit.run(
            [
                "--run-dir",
                str(unknown_runs),
                "--source-repo",
                SOURCE_REPO,
                "--dry-run",
            ]
        )
        == 1
    )
    assert "without a recognized severity" in capsys.readouterr().out


def test_run_reports_parse_label_and_mutation_failures(tmp_path, monkeypatch, capsys):
    """Every collection-stage failure returns nonzero with a concrete log reason."""
    runs = write_run(tmp_path, {"a.md": SQLI_REPORT})
    monkeypatch.setenv(emit.DEFAULT_TOKEN_ENV, "gho_" + "t" * 30)

    monkeypatch.setattr(
        emit,
        "parse_run_dir",
        lambda *_: (_ for _ in ()).throw(RuntimeError("bad report")),
    )
    args = ["--run-dir", str(runs), "--source-repo", SOURCE_REPO]
    assert emit.run(args) == 1
    assert "could not parse reports" in capsys.readouterr().out

    monkeypatch.undo()
    monkeypatch.setenv(emit.DEFAULT_TOKEN_ENV, "gho_" + "t" * 30)

    class BadLabelClient(FakeClient):
        def ensure_labels(self, labels):
            raise RuntimeError("label permission denied")

    monkeypatch.setattr(emit, "GitHubIssueClient", lambda repo, token: BadLabelClient())
    assert emit.run(args) == 1
    assert "Could not provision" in capsys.readouterr().out

    class BadCreateClient(FakeClient):
        def create_issue(self, title, body, labels):
            raise RuntimeError("issue permission denied")

    monkeypatch.setattr(
        emit, "GitHubIssueClient", lambda repo, token: BadCreateClient()
    )
    assert emit.run(args) == 1
    out = capsys.readouterr().out
    assert "::error::Strix issue emit failed" in out
    assert "error=1" in out


def test_run_defensively_rejects_unknown_severity_from_any_parser(
    tmp_path, monkeypatch, capsys
):
    """The CLI revalidates severity even when a parser substitute returns data."""
    runs = write_run(tmp_path, {"a.md": SQLI_REPORT})
    unknown = emit.parse_finding_markdown(
        SQLI_REPORT.replace("Severity: HIGH", "Severity: BOGUS"), SOURCE_REPO
    )
    monkeypatch.setattr(emit, "parse_run_dir", lambda *_: [unknown])

    code = emit.run(["--run-dir", str(runs), "--source-repo", SOURCE_REPO, "--dry-run"])

    assert code == 1
    assert "without a recognized severity" in capsys.readouterr().out


def test_iter_vulnerability_files_skips_symlinked_dir(tmp_path):
    """Symlinked vulnerabilities directories are ignored."""
    runs = write_run(tmp_path, {"a.md": SQLI_REPORT})
    evil = tmp_path / "strix_runs" / "run-evil"
    evil.mkdir()
    (evil / "vulnerabilities").symlink_to(runs / "run-1" / "vulnerabilities")
    files = emit.iter_vulnerability_files(runs)
    # Only the real directory's report is returned.
    assert len(files) == 1


def test_iter_vulnerability_files_skips_symlinked_files_and_directories(tmp_path):
    """Only real regular Markdown report files enter reconciliation."""
    runs = write_run(tmp_path, {"a.md": SQLI_REPORT})
    vuln_dir = runs / "run-1" / "vulnerabilities"
    (vuln_dir / "linked.md").symlink_to(vuln_dir / "a.md")
    (vuln_dir / "directory.md").mkdir()

    files = emit.iter_vulnerability_files(runs)

    assert [path.name for path in files] == ["a.md"]


def test_severity_rank_orders_and_handles_unknown():
    """Severity ranking orders known levels and returns -1 for unknown."""
    assert emit.severity_rank("CRITICAL") > emit.severity_rank("LOW")
    assert emit.severity_rank("bogus") == -1


def test_scrub_redacts_tokens():
    """Token scrubbing removes GitHub token shapes."""
    assert "gho_" not in emit._scrub("leak gho_" + "a" * 30)
    assert "github_pat_" not in emit._scrub("pat github_pat_" + "a" * 30)


# --------------------------------------------------------------------------- #
# Location edge cases
# --------------------------------------------------------------------------- #


PROSE_LOCATION_REPORT = """\
Title: Insecure Deserialization
Severity: HIGH

Description:
The bug is triggered at backend/loader.py:73 inside the request handler.
"""

KEYWORD_LOCATION_REPORT = """\
Title: Directory Traversal
Severity: HIGH
Affected file backend/files.py:12 handles the path unsafely.
"""


def test_location_falls_back_to_prose_reference():
    """A location mentioned only in prose is recovered by the end-of-text fallback."""
    finding = emit.parse_finding_markdown(PROSE_LOCATION_REPORT, SOURCE_REPO)
    assert finding.code_location == "backend/loader.py:73"


def test_location_line_with_file_keyword_is_used():
    """A location line containing a file/path keyword is treated as a location."""
    finding = emit.parse_finding_markdown(KEYWORD_LOCATION_REPORT, SOURCE_REPO)
    assert finding.code_location == "backend/files.py:12"


def test_iter_vulnerability_files_on_missing_dir(tmp_path):
    """A non-existent run directory yields no report files."""
    assert emit.iter_vulnerability_files(tmp_path / "nope") == []


def test_report_count_and_size_limits_fail_closed(tmp_path, monkeypatch):
    """Oversized report sets and files abort instead of dropping evidence."""
    runs = write_run(tmp_path, {"a.md": SQLI_REPORT})
    monkeypatch.setattr(emit, "MAX_REPORT_FILES", 0)
    with pytest.raises(RuntimeError, match="report count"):
        emit.iter_vulnerability_files(runs)

    monkeypatch.setattr(emit, "MAX_REPORT_FILES", 200)
    monkeypatch.setattr(emit, "MAX_REPORT_BYTES", 1)
    with pytest.raises(RuntimeError, match="limit is 1"):
        emit.parse_run_dir(runs, SOURCE_REPO)


def test_parse_run_dir_fails_on_unreadable_file(tmp_path, monkeypatch):
    """An unreadable report aborts reconciliation instead of losing a finding."""
    runs = write_run(tmp_path, {"a.md": SQLI_REPORT, "b.md": XSS_REPORT})
    original = Path.read_text

    def flaky_read_text(self, *args, **kwargs):
        if self.name == "a.md":
            raise OSError("permission denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    with pytest.raises(RuntimeError, match="Could not read Strix report"):
        emit.parse_run_dir(runs, SOURCE_REPO)


def test_relocated_finding_is_new_identity_and_closes_old():
    """A moved finding forks a new hash: create the new issue, close the stale one."""
    existing = existing_issue_for(SQLI_REPORT, number=7)  # old location
    moved = SQLI_REPORT.replace(
        "backend/app/auth.py:42-45", "backend/app/auth.py:200-210"
    )
    finding = emit.parse_finding_markdown(moved, SOURCE_REPO)
    ops = emit.plan_operations([finding], [existing], make_context(scan_complete=True))
    actions = [op.action for op in ops]
    assert "create" in actions
    close_ops = [op for op in ops if op.action == "close"]
    assert [op.issue_number for op in close_ops] == [7]


def test_issue_number_handles_bad_values():
    """Issue-number parsing tolerates missing/invalid numbers."""
    assert emit._issue_number({"number": "5"}) == 5
    assert emit._issue_number({}) is None
    assert emit._issue_number({"number": "x"}) is None


# --------------------------------------------------------------------------- #
# GitHubIssueClient (gh subprocess wrapper)
# --------------------------------------------------------------------------- #


class FakeCompleted:
    """Stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_client_list_scope_issues_filters_pull_requests(monkeypatch):
    """list_scope_issues slurps pages and drops pull requests."""
    calls = {}

    def fake_run(
        args, input=None, capture_output=None, text=None, env=None, check=None
    ):
        calls["args"] = args
        calls["token"] = env["GH_TOKEN"]
        page = [{"number": 1, "title": "issue"}, {"number": 2, "pull_request": {}}]
        return FakeCompleted(stdout=json.dumps([page]))

    monkeypatch.setattr(emit.subprocess, "run", fake_run)
    client = emit.GitHubIssueClient(
        "ContextualWisdomLab/appguardrail", "gho_" + "t" * 30
    )
    issues = client.list_scope_issues("example-service")
    assert [i["number"] for i in issues] == [1]
    assert calls["token"].startswith("gho_")
    assert "labels=strix,repo:example-service" in calls["args"]


def test_client_ensure_labels_creates_only_missing_labels(monkeypatch):
    """Label bootstrap reads all labels and creates missing bounded labels."""
    recorded = []

    def fake_run(args, input=None, **kwargs):
        recorded.append((args, input))
        if "GET" in args:
            return FakeCompleted(stdout=json.dumps([[{"name": "strix"}]]))
        return FakeCompleted(stdout="{}")

    monkeypatch.setattr(emit.subprocess, "run", fake_run)
    client = emit.GitHubIssueClient(emit.DEFAULT_ISSUES_REPO, "gho_" + "t" * 30)
    client.ensure_labels(["strix", "security", "repo:example-service"])

    created = [json.loads(payload) for args, payload in recorded if "POST" in args]
    assert {item["name"] for item in created} == {
        "security",
        "repo:example-service",
    }
    assert all(len(item["color"]) == 6 for item in created)


def test_client_ensure_labels_tolerates_create_race_and_rejects_real_error(
    monkeypatch,
):
    """A concurrent label create is harmless, while other API errors propagate."""
    client = emit.GitHubIssueClient(emit.DEFAULT_ISSUES_REPO, "gho_" + "t" * 30)
    calls = 0

    def race_then_fail(args, stdin=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "[]"
        raise RuntimeError("already_exists")

    monkeypatch.setattr(client, "_run", race_then_fail)
    client.ensure_labels(["strix"])

    calls = 0

    def real_failure(args, stdin=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return "[]"
        raise RuntimeError("permission denied")

    monkeypatch.setattr(client, "_run", real_failure)
    with pytest.raises(RuntimeError, match="permission denied"):
        client.ensure_labels(["strix"])


def test_client_write_methods_invoke_gh(monkeypatch):
    """create/update/comment/close send the expected gh payloads."""
    recorded = []

    def fake_run(args, input=None, **kwargs):
        recorded.append((args, input))
        return FakeCompleted(stdout="{}")

    monkeypatch.setattr(emit.subprocess, "run", fake_run)
    client = emit.GitHubIssueClient("owner/repo", "gho_" + "t" * 30)
    client.create_issue("t", "b", ["strix"])
    client.update_issue(3, "b2", ["strix"])
    client.comment_issue(3, "hi")
    client.close_issue(4, "bye")
    joined = " ".join(" ".join(a) for a, _ in recorded)
    assert "repos/owner/repo/issues" in joined
    assert "repos/owner/repo/issues/3" in joined
    assert "PATCH" in joined
    # close_issue comments then patches state closed.
    assert any("closed" in (payload or "") for _, payload in recorded)


def test_client_raises_scrubbed_error_on_failure(monkeypatch):
    """A non-zero gh exit raises a scrubbed RuntimeError."""

    def fake_run(args, input=None, **kwargs):
        return FakeCompleted(returncode=1, stderr="bad token gho_" + "z" * 30)

    monkeypatch.setattr(emit.subprocess, "run", fake_run)
    client = emit.GitHubIssueClient("owner/repo", "gho_" + "t" * 30)
    with pytest.raises(RuntimeError) as excinfo:
        client.create_issue("t", "b", [])
    assert "gho_" not in str(excinfo.value)


def test_client_error_defaults_message_when_stderr_empty(monkeypatch):
    """A silent gh failure still raises a generic error message."""

    def fake_run(args, input=None, **kwargs):
        return FakeCompleted(returncode=1, stderr="")

    monkeypatch.setattr(emit.subprocess, "run", fake_run)
    client = emit.GitHubIssueClient("owner/repo", "gho_" + "t" * 30)
    with pytest.raises(RuntimeError, match="gh command failed"):
        client.comment_issue(1, "x")


@pytest.mark.parametrize(
    ("label", "color"),
    [
        ("strix", "5319e7"),
        ("security", "d73a4a"),
        ("severity:critical", "b60205"),
        ("severity:high", "d93f0b"),
        ("severity:medium", "fbca04"),
        ("repo:example-service", "0e8a16"),
        ("other", "cfd3d7"),
    ],
)
def test_label_style_is_stable(label, color):
    """Emitter-owned label categories have deterministic colors."""
    assert emit.label_style(label)[0] == color


# --------------------------------------------------------------------------- #
# CLI live + degradation paths
# --------------------------------------------------------------------------- #


def test_run_live_applies_plan(tmp_path, monkeypatch, capsys):
    """With a token and a working client the CLI creates issues live."""
    runs = write_run(tmp_path, {"a.md": SQLI_REPORT})
    monkeypatch.setenv(emit.DEFAULT_TOKEN_ENV, "gho_" + "t" * 30)
    client = FakeClient(existing=[])
    monkeypatch.setattr(emit, "GitHubIssueClient", lambda repo, token: client)
    code = emit.run(
        ["--run-dir", str(runs), "--source-repo", SOURCE_REPO, "--scan-complete"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert len(client.created) == 1
    assert "strix" in client.ensured_labels
    assert "security" in client.ensured_labels
    assert "create=1" in out
    assert "dry-run" not in out


def test_run_full_scope_closes_stale_issue(tmp_path, monkeypatch, capsys):
    """A full-repo scan (--scope full) reconciles and closes stale issues via the CLI."""
    runs = write_run(tmp_path, {"a.md": SQLI_REPORT})
    monkeypatch.setenv(emit.DEFAULT_TOKEN_ENV, "gho_" + "t" * 30)
    stale = existing_issue_for(XSS_REPORT, number=9)
    client = FakeClient(existing=[stale])
    monkeypatch.setattr(emit, "GitHubIssueClient", lambda repo, token: client)
    code = emit.run(
        [
            "--run-dir",
            str(runs),
            "--source-repo",
            SOURCE_REPO,
            "--scan-complete",
            "--scope",
            "full",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert client.closed == [9]
    assert "close=1" in out


def test_run_pr_scope_never_closes_stale_issue(tmp_path, monkeypatch, capsys):
    """A completed PR-scoped scan (default --scope pr) closes nothing via the CLI."""
    runs = write_run(tmp_path, {"a.md": SQLI_REPORT})
    monkeypatch.setenv(emit.DEFAULT_TOKEN_ENV, "gho_" + "t" * 30)
    stale = existing_issue_for(XSS_REPORT, number=9)
    client = FakeClient(existing=[stale])
    monkeypatch.setattr(emit, "GitHubIssueClient", lambda repo, token: client)
    code = emit.run(
        ["--run-dir", str(runs), "--source-repo", SOURCE_REPO, "--scan-complete"]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert client.closed == []
    assert "close=0" in out
    assert "PR-scoped" in out


def test_run_fails_closed_when_read_fails(tmp_path, monkeypatch, capsys):
    """A failure reading existing issues blocks an incomplete reconciliation."""
    runs = write_run(tmp_path, {"a.md": SQLI_REPORT})
    monkeypatch.setenv(emit.DEFAULT_TOKEN_ENV, "gho_" + "t" * 30)

    class BadReadClient(FakeClient):
        def list_scope_issues(self, repo_short):
            raise RuntimeError("gho_" + "z" * 30 + " unauthorized")

    monkeypatch.setattr(emit, "GitHubIssueClient", lambda repo, token: BadReadClient())
    code = emit.run(["--run-dir", str(runs), "--source-repo", SOURCE_REPO])
    out = capsys.readouterr().out
    assert code == 1
    assert "::error::" in out
    assert "refusing an incomplete reconciliation" in out
    assert "gho_" not in out


def test_run_exits_early_when_nothing_to_do(tmp_path, monkeypatch, capsys):
    """No findings and nothing to reconcile exits cleanly without planning."""
    empty = tmp_path / "strix_runs" / "run-1" / "vulnerabilities"
    empty.mkdir(parents=True)
    monkeypatch.delenv(emit.DEFAULT_TOKEN_ENV, raising=False)
    code = emit.run(
        [
            "--run-dir",
            str(tmp_path / "strix_runs"),
            "--source-repo",
            SOURCE_REPO,
            "--dry-run",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "nothing to reconcile" in out
