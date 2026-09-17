import json

import pytest

from scripts.ci import refresh_gap_baseline_inventory as rgbi


def _pr(number, *, title="fix(scope): do a thing", state="DIRTY", draft=False, review="CHANGES_REQUESTED"):
    return {
        "number": number,
        "title": title,
        "headRefOid": f"{number:040x}",
        "baseRefName": "main",
        "mergeStateStatus": state,
        "isDraft": draft,
        "reviewDecision": review,
    }


class _Done:
    def __init__(self, stdout="", stderr=""):
        self.stdout = stdout
        self.stderr = stderr


def test_fetch_open_prs_returns_parsed_json_on_first_try(monkeypatch):
    payload = json.dumps([_pr(1)])
    monkeypatch.setattr(rgbi.subprocess, "run", lambda *a, **k: _Done(stdout=payload))
    assert rgbi.fetch_open_prs() == [_pr(1)]


def test_fetch_open_prs_retries_transient_5xx_then_succeeds(monkeypatch):
    replies = [_Done(stderr="HTTP 502: Bad Gateway"), _Done(stdout=json.dumps([_pr(2)]))]
    monkeypatch.setattr(rgbi.subprocess, "run", lambda *a, **k: replies.pop(0))
    assert rgbi.fetch_open_prs(attempts=3) == [_pr(2)]


def test_fetch_open_prs_raises_after_exhausting_attempts(monkeypatch):
    monkeypatch.setattr(rgbi.subprocess, "run", lambda *a, **k: _Done(stderr="HTTP 504"))
    with pytest.raises(RuntimeError, match="no JSON in 2 tries: HTTP 504"):
        rgbi.fetch_open_prs(attempts=2)


def test_render_row_is_contract_conformant_and_escapes_pipes():
    row = rgbi.render_row(_pr(1347, title="fix: a | b\nc", state="BLOCKED", draft=True, review=None))
    assert row.startswith("| #1347 | fix: a / b c | `")
    assert "`main` | BLOCKED | REVIEW_REQUIRED | draft |" in row
    assert f"{1347:040x}" in row


def test_render_row_rejects_unmappable_merge_state():
    with pytest.raises(ValueError, match="unmappable mergeStateStatus 'UNKNOWN'"):
        rgbi.render_row(_pr(9, state="UNKNOWN"))


def test_render_row_handles_missing_title():
    assert rgbi.render_row(_pr(5, title=None, state="CLEAN")).startswith("| #5 |  | `")


def test_render_section_orders_desc_and_tallies_states_and_drafts():
    section = rgbi.render_section(
        [_pr(10, state="BEHIND"), _pr(30, state="CLEAN", draft=True), _pr(20, state="BEHIND")],
        "2026-09-09 20:00 KST",
    )
    lines = section.splitlines()
    assert lines[0] == rgbi.SECTION_HEADING
    assert "스냅샷 요약: total 3; BEHIND=2; CLEAN=1; draft=1" in section
    assert "반환한 3개 열린 PR" in section
    body = [ln for ln in lines if ln.startswith("| #")]
    assert [ln.split()[1] for ln in body] == ["#30", "#20", "#10"]


BASE_DOC = "\n".join(
    [
        "# Product and Technical Gap Baseline",
        "",
        "현재 열린 PR 수: **7** (old snapshot)",
        "",
        "## 3. Gap register",
        "",
        "G-01 text",
        "",
        rgbi.SECTION_HEADING,
        "",
        "old intro",
        "",
        "| PR | title | exact head SHA | base | metadata | review | mode |",
        "|---|---|---|---|---|---|---|",
        "| #99 | stale | `" + "9" * 40 + "` | `main` | DIRTY | REVIEW_REQUIRED | ready |",
        "",
        "## 5. Next section",
        "",
        "tail stays",
        "",
    ]
)


def test_splice_updates_count_and_replaces_only_section_four():
    section = rgbi.render_section([_pr(42, state="CLEAN")], "2026-09-09 20:00 KST")
    out = rgbi.splice(BASE_DOC, section, 1)
    assert "현재 열린 PR 수: **1** (old snapshot)" in out
    assert "| #99 | stale" not in out
    assert "| #42 |" in out
    assert out.startswith("# Product and Technical Gap Baseline\n")
    assert out.rstrip().endswith("## 5. Next section\n\ntail stays".rstrip())
    assert "G-01 text" in out


def test_splice_raises_when_header_count_line_is_missing():
    with pytest.raises(ValueError, match="header 'PR count' line not found"):
        rgbi.splice("no header here\n\n" + rgbi.SECTION_HEADING + "\n\n## 5. x\n", "x", 1)


def test_main_rewrites_the_named_file_in_place(monkeypatch, tmp_path, capsys):
    doc = tmp_path / "gap.md"
    doc.write_text(BASE_DOC, encoding="utf-8")
    monkeypatch.setattr(rgbi, "fetch_open_prs", lambda: [_pr(42, state="CLEAN"), _pr(7, state="BLOCKED")])

    assert rgbi.main([str(doc)]) == 0

    written = doc.read_text(encoding="utf-8")
    assert "현재 열린 PR 수: **2**" in written
    assert written.count("\n| #") == 2
    assert "refreshed" in capsys.readouterr().out
