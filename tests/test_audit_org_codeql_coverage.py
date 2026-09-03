from io import StringIO
import json
from pathlib import Path

from scripts.ci import audit_org_codeql_coverage as audit


def covered_by_default_setup(name: str) -> dict:
    """Return a repository payload covered by GitHub's native default-setup."""
    return {
        "name": name,
        "archived": False,
        "default_setup_state": "configured",
        "has_recent_codeql_analysis": False,
    }


def covered_by_recent_analysis(name: str) -> dict:
    """Return a repository payload covered by a recent CodeQL analysis run."""
    return {
        "name": name,
        "archived": False,
        "default_setup_state": None,
        "has_recent_codeql_analysis": True,
    }


def uncovered(name: str, archived: bool = False) -> dict:
    """Return a repository payload with zero CodeQL coverage from any source."""
    return {
        "name": name,
        "archived": archived,
        "default_setup_state": None,
        "has_recent_codeql_analysis": False,
    }


def test_empty_repository_list_reports_no_gaps() -> None:
    assert audit.audit_codeql_coverage([]) == []


def test_all_covered_repositories_report_no_gaps() -> None:
    repositories = [
        covered_by_default_setup("CalendarWeave"),
        covered_by_recent_analysis("contextual-orchestrator"),
    ]

    assert audit.audit_codeql_coverage(repositories) == []


def test_uncovered_repository_is_flagged() -> None:
    repositories = [uncovered("Orgmetra")]

    assert audit.audit_codeql_coverage(repositories) == [
        "Orgmetra has no CodeQL coverage from any source "
        "(no default-setup, no recent analysis)"
    ]


def test_mixed_covered_and_uncovered_flags_only_gaps() -> None:
    repositories = [
        covered_by_default_setup("naruon"),
        uncovered("j-planner"),
        covered_by_recent_analysis("noema"),
        uncovered("life-os"),
    ]

    assert audit.audit_codeql_coverage(repositories) == [
        "j-planner has no CodeQL coverage from any source "
        "(no default-setup, no recent analysis)",
        "life-os has no CodeQL coverage from any source "
        "(no default-setup, no recent analysis)",
    ]


def test_archived_uncovered_repository_is_excluded() -> None:
    repositories = [uncovered("trivy-sarif-repro", archived=True)]

    assert audit.audit_codeql_coverage(repositories) == []


def test_default_setup_alone_counts_as_coverage() -> None:
    repositories = [covered_by_default_setup("PolicyWeave")]

    assert audit.audit_codeql_coverage(repositories) == []


def test_recent_analysis_alone_counts_as_coverage() -> None:
    repositories = [covered_by_recent_analysis("TEPP")]

    assert audit.audit_codeql_coverage(repositories) == []


def test_load_payload_reads_from_stdin(monkeypatch) -> None:
    monkeypatch.setattr(
        audit.sys, "stdin", StringIO(json.dumps([uncovered("disksage")]))
    )

    assert audit.load_payload(None, audit.sys.stdin) == [uncovered("disksage")]


def test_load_payload_reads_from_file_arg(tmp_path) -> None:
    payload_path = tmp_path / "repositories.json"
    payload_path.write_text(json.dumps([covered_by_default_setup("EmbedRelay")]), encoding="utf-8")

    payload = audit.load_payload(payload_path, StringIO())

    assert payload == [covered_by_default_setup("EmbedRelay")]


def test_main_fail_path_reports_gaps_from_stdin(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        audit.sys, "stdin", StringIO(json.dumps([uncovered("LineageWeave")]))
    )

    assert audit.main([]) == 1
    captured = capsys.readouterr()
    assert (
        "ERROR: LineageWeave has no CodeQL coverage from any source "
        "(no default-setup, no recent analysis)" in captured.err
    )
    assert "FAIL: 1 repositories have no CodeQL coverage" in captured.err


def test_main_pass_path_reports_from_file_arg(tmp_path, capsys) -> None:
    payload_path = tmp_path / "repositories.json"
    payload_path.write_text(
        json.dumps([covered_by_default_setup("ELUNVERA"), covered_by_recent_analysis("Orgmetra")]),
        encoding="utf-8",
    )

    assert audit.main([str(payload_path)]) == 0
    assert (
        "PASS: all 2 repositories have real CodeQL coverage"
        in capsys.readouterr().out
    )


def test_main_reports_malformed_json_load_reason(monkeypatch, capsys) -> None:
    monkeypatch.setattr(audit.sys, "stdin", StringIO("not json"))

    assert audit.main([]) == 2
    assert "ERROR: unable to load repository JSON:" in capsys.readouterr().err


def test_main_rejects_non_list_json_root(monkeypatch, capsys) -> None:
    monkeypatch.setattr(audit.sys, "stdin", StringIO(json.dumps({"name": "not-a-list"})))

    assert audit.main([]) == 2
    assert (
        "ERROR: unable to load repository JSON: repository JSON root must be a list"
        in capsys.readouterr().err
    )


def test_parse_args_accepts_positional_path() -> None:
    args = audit.parse_args(["repositories.json"])

    assert args.repositories_json == Path("repositories.json")


def test_parse_args_defaults_to_none() -> None:
    args = audit.parse_args([])

    assert args.repositories_json is None
