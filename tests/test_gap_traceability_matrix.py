"""Tests for the Gap-to-work traceability matrix."""

import json

import pytest

from scripts.ci import gap_traceability_matrix as gtm

REGISTER = """# Baseline

Prose mentions G-99 and G-01 but defines nothing.

| Gap ID | 상태 | evidence |
|---|---|---|
| CONTROL-SELF-HOSTED-EXECUTION-01 | **Draft** `x` | a \\| b |
| G-01 | [linked](https://example.com/G-02) text | e |

| ID | 결과 | 증거 |
|---|---|---|
| PRD-01 | find sender | retrieval |
| not an id | ignored | x |

| PR | title |
|---|---|
| G-03 | wrong table header, not a register row |

| Gap ID | Status |
| --- | --- |
| G-01 | duplicate definition |
| G-04 |
"""


def _write(tmp_path, name, data):
    """Write JSON or text fixture data and return the path."""
    path = tmp_path / name
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def test_parse_register_reads_only_register_tables():
    """Rows count only under a Gap ID/ID header; prose and other tables do not."""
    entries = gtm.parse_register(REGISTER)
    assert [e.gap_id for e in entries] == [
        "CONTROL-SELF-HOSTED-EXECUTION-01",
        "G-01",
        "PRD-01",
        "G-01",
        "G-04",
    ]
    assert entries[0].description == "Draft x"
    assert entries[1].description == "linked text"
    assert entries[-1].description == ""
    assert entries[1].line == 8


def test_parse_register_ignores_fenced_examples():
    """Example tables inside fenced code are not register rows."""
    text = (
        "```md\n| Gap ID | x |\n|---|---|\n| G-90 | example |\n```\n"
        "| Gap ID | x |\n|---|---|\n| G-01 | real |\n"
        "````\n```\n| ID | x |\n|---|---|\n| G-91 | nested |\n````\n"
    )
    assert [e.gap_id for e in gtm.parse_register(text)] == ["G-01"]


def test_split_cells_respects_escaped_pipes():
    """An escaped pipe stays inside its cell."""
    assert gtm.split_cells("| a \\| b | c |") == ["a \\| b", "c"]
    assert gtm.split_cells("a | b \\|") == ["a", "b \\|"]


def test_shorten_marks_cut_text():
    """Long descriptions are cut with an ellipsis; short ones are unchanged."""
    assert gtm.shorten("abc", 5) == "abc"
    assert gtm.shorten("abcdefgh", 5) == "abcd…"


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Gap G-04 queue hygiene, G-09 green CI", {"G-04", "G-09"}),
        ("G-15를 보강한다", {"G-15"}),
        ("`CONTROL-OPENCODE-LATEST-REVIEW-01` evidence", {"CONTROL-OPENCODE-LATEST-REVIEW-01"}),
        ("`see G-01 here` only", set()),
        ("```\nG-01\n```\nG-02", {"G-02"}),
        ("<!-- G-01 -->", set()),
        ("https://x.test/G-01 and [G-02](https://x.test/G-03)", {"G-02"}),
        ("/G-01 foo.G-02 file-G-03 x_G-04", set()),
        ("G-150 G-1 G-01A G-01-extra g-01", {"G-150"}),
        ("deadbeefG-01 cafe0G-02", set()),
        ("G-17..G-22 and G-17–G-19", {"G-17", "G-22", "G-19"}),
        ("end of sentence. G-05.", {"G-05"}),
        ("PRD-08 / TRD-02", {"PRD-08", "TRD-02"}),
        ("line\r\nG-06\r\n", {"G-06"}),
        ("see https://x.test/a,G-07 and (https://x.test/b)G-08", {"G-08"}),
        ("G-02 <!-- G-01 never closed", {"G-02"}),
        ("[x](a b G-01 and G-03", {"G-01", "G-03"}),
        ("G-04/G-09 and G-01/PRD-02", {"G-04", "G-09", "G-01", "PRD-02"}),
        ("docs/G-01 and /G-02", set()),
        ("G-03\n```\nG-01 never closed", {"G-03"}),
        ("  ~~~~\nG-01\n  ~~~~\nG-02", {"G-02"}),
    ],
)
def test_extract_mentions(text, expected):
    """Mentions avoid code, URLs, path-like tokens and partial matches."""
    assert gtm.extract_mentions(text) == frozenset(expected)


def test_parse_work_items_handles_missing_fields():
    """Null bodies and missing keys are tolerated; drafts are preserved."""
    items = gtm.parse_work_items(
        [
            {"number": 3, "title": "G-01 fix", "body": None, "isDraft": True},
            {"number": 4, "isDraft": "false"},
        ],
        "pr",
    )
    assert items[0].mentions == frozenset({"G-01"})
    assert items[0].is_draft and items[0].url == ""
    assert items[1].is_draft is False


@pytest.mark.parametrize(
    "row",
    [{"title": "x"}, {"number": True}, {"number": 0}, {"number": "4"}, {"number": 1, "body": 5}],
)
def test_parse_work_items_rejects_bad_rows(row):
    """Rows without a positive integer number or with non-string text fail."""
    with pytest.raises(gtm.InputError):
        gtm.parse_work_items([row], "pr")


def test_build_matrix_classifies_links():
    """Linked, unlinked, dangling and duplicate cases are all reported."""
    entries = gtm.parse_register(REGISTER)
    work = gtm.parse_work_items(
        [
            {"number": 2, "title": "G-01 and G-99", "url": "u2"},
            {"number": 1, "title": "no id"},
        ],
        "pr",
    ) + gtm.parse_work_items([{"number": 7, "title": "PRD-01"}], "issue")
    matrix = gtm.build_matrix(entries, work, {"b": "2", "a": "1"})
    assert list(matrix["inputs"]) == ["a", "b"]
    assert matrix["gaps"]["G-01"]["prs"][0]["number"] == 2
    assert matrix["gaps"]["PRD-01"]["issues"][0]["number"] == 7
    assert matrix["unlinked_gaps"] == ["CONTROL-SELF-HOSTED-EXECUTION-01", "G-04"]
    assert [w["number"] for w in matrix["unlinked_work"]] == [1]
    assert list(matrix["dangling_references"]) == ["G-99"]
    assert matrix["duplicate_register_ids"] == {"G-01": [8, 21]}
    summary = matrix["summary"]
    assert summary["register_ids"] == 4 and summary["register_rows"] == 5
    assert summary["linked_work_items"] == 2 and summary["prs"] == 2
    assert gtm.build_matrix(entries, [])["inputs"] == {}


def test_render_markdown_covers_empty_and_populated_sections():
    """The report renders both empty and populated optional sections."""
    entries = gtm.parse_register(REGISTER)
    work = gtm.parse_work_items(
        [{"number": 2, "title": "G-01 G-99", "isDraft": True}], "pr"
    )
    text = gtm.render_markdown(gtm.build_matrix(entries, work), "now")
    assert "| G-01 | linked text | #2 (draft) | — |" in text
    assert "| G-99 | #2 (draft) |" in text
    assert "- G-01: lines 8, 21" in text
    clean = gtm.parse_register("| ID | d |\n|---|---|\n| G-01 | a\\|b |\n")
    empty = gtm.render_markdown(gtm.build_matrix(clean, []), "now")
    assert empty.count("None.") == 2
    assert "| G-01 | a\\|b | — | — |" in empty


def test_require_link_outcomes():
    """Known IDs pass, unknown-only fails, issues do not satisfy a PR check."""
    work = gtm.parse_work_items(
        [{"number": 1, "title": "G-01"}, {"number": 2, "title": "G-99"}, {"number": 3}],
        "pr",
    ) + gtm.parse_work_items([{"number": 4, "title": "G-01"}], "issue")
    known = {"G-01"}
    assert gtm.require_link(known, work, 1) == (0, "PR #1 links G-01")
    assert gtm.require_link(known, work, 2) == (1, "PR #2 links no known Gap ID (unknown: G-99)")
    assert gtm.require_link(known, work, 3) == (1, "PR #3 links no known Gap ID")
    assert gtm.require_link(known, work, 4)[0] == 2


def test_main_writes_reports(tmp_path, capsys):
    """The CLI writes JSON and Markdown and records input digests."""
    register = _write(tmp_path, "r.md", REGISTER)
    prs = _write(tmp_path, "p.json", [{"number": 1, "title": "G-04"}])
    issues = _write(tmp_path, "i.json", [{"number": 2, "body": "PRD-01"}])
    out_json, out_md = tmp_path / "m.json", tmp_path / "m.md"
    code = gtm.main(
        [
            "--register", str(register), "--prs", str(prs), "--issues", str(issues),
            "--output-json", str(out_json), "--output-md", str(out_md),
            "--generated-at", "T",
        ]
    )
    assert code == 0
    matrix = json.loads(out_json.read_text(encoding="utf-8"))
    assert set(matrix["inputs"]) == {"register_sha256", "prs_sha256", "issues_sha256"}
    assert "Generated: T." in out_md.read_text(encoding="utf-8")
    captured = capsys.readouterr()
    assert '"work_items": 2' in captured.out
    assert "duplicate register IDs" in captured.err


def test_main_duplicate_gate_and_register_only(tmp_path):
    """Duplicates fail only with --fail-on-duplicates; inventories are optional."""
    register = _write(tmp_path, "r.md", REGISTER)
    assert gtm.main(["--register", str(register)]) == 0
    assert gtm.main(["--register", str(register), "--fail-on-duplicates"]) == 3
    clean = _write(tmp_path, "c.md", "| ID | d |\n|---|---|\n| G-01 | a |\n")
    assert gtm.main(["--register", str(clean), "--fail-on-duplicates"]) == 0


def test_main_duplicate_gate_precedes_link_checks(tmp_path):
    """--fail-on-duplicates also applies to the link-check modes."""
    register = _write(tmp_path, "r.md", REGISTER)
    prs = _write(tmp_path, "p.json", [{"number": 5, "title": "G-04"}])
    args = ["--register", str(register), "--prs", str(prs), "--require-link", "5"]
    assert gtm.main(args) == 0
    assert gtm.main(args + ["--fail-on-duplicates"]) == 3


def test_main_unwritable_output_exits_input_error(tmp_path, capsys):
    """An output write failure exits 2, not the 'unlinked' code 1."""
    register = _write(tmp_path, "r.md", REGISTER)
    target = tmp_path / "missing-dir" / "m.json"
    assert gtm.main(["--register", str(register), "--output-json", str(target)]) == 2
    assert "cannot write" in capsys.readouterr().err


def test_main_require_link_from_inventory(tmp_path, capsys):
    """--require-link reads the PR inventory and needs --prs."""
    register = _write(tmp_path, "r.md", REGISTER)
    prs = _write(tmp_path, "p.json", [{"number": 5, "title": "G-04"}])
    assert gtm.main(["--register", str(register), "--prs", str(prs), "--require-link", "5"]) == 0
    assert gtm.main(["--register", str(register), "--prs", str(prs), "--require-link", "6"]) == 2
    assert gtm.main(["--register", str(register), "--require-link", "5"]) == 2
    assert "needs --prs" in capsys.readouterr().err


def test_main_require_link_from_event(tmp_path):
    """An event payload is checked directly, without an exported inventory."""
    register = _write(tmp_path, "r.md", REGISTER)
    good = _write(
        tmp_path, "e.json",
        {"pull_request": {"number": 9, "title": "x", "body": "Gap: G-04", "draft": False}},
    )
    bad = _write(tmp_path, "b.json", {"pull_request": {"number": 9, "title": "x", "body": None}})
    assert gtm.main(["--register", str(register), "--require-link-event", str(good)]) == 0
    assert gtm.main(["--register", str(register), "--require-link-event", str(bad)]) == 1


@pytest.mark.parametrize(
    "content",
    ["not json", json.dumps({"pull_request": "x"}), json.dumps([1])],
)
def test_main_rejects_bad_event(tmp_path, content):
    """Malformed or non-PR event payloads exit 2."""
    register = _write(tmp_path, "r.md", REGISTER)
    event = _write(tmp_path, "e.json", content)
    assert gtm.main(["--register", str(register), "--require-link-event", str(event)]) == 2


@pytest.mark.parametrize("content", ["{", json.dumps({"a": 1}), json.dumps([1])])
def test_main_rejects_bad_inventory(tmp_path, content):
    """Inventories must be JSON arrays of objects."""
    register = _write(tmp_path, "r.md", REGISTER)
    prs = _write(tmp_path, "p.json", content)
    assert gtm.main(["--register", str(register), "--prs", str(prs)]) == 2


def test_main_rejects_missing_or_empty_register(tmp_path, capsys):
    """A missing register or one without rows exits 2."""
    assert gtm.main(["--register", str(tmp_path / "absent.md")]) == 2
    empty = _write(tmp_path, "e.md", "# no tables\n")
    assert gtm.main(["--register", str(empty)]) == 2
    assert "no Gap ID rows" in capsys.readouterr().err


def test_main_rejects_conflicting_modes(tmp_path):
    """--require-link and --require-link-event are mutually exclusive."""
    with pytest.raises(SystemExit):
        gtm.main(["--require-link", "1", "--require-link-event", str(tmp_path)])


def test_live_register_parses_without_duplicates():
    """The repository's own baseline parses into unique register IDs."""
    with open("docs/product-technical-gap-baseline.md", encoding="utf-8") as handle:
        entries = gtm.parse_register(handle.read())
    ids = [entry.gap_id for entry in entries]
    assert len(ids) >= 20
    assert len(ids) == len(set(ids))
    assert {"G-01", "PRD-01", "G-17"} <= set(ids)


@pytest.mark.parametrize(
    "text",
    ["<!--" * 40000, "G-01-" * 40000, "](" * 40000, "](a " * 40000, "```\n" * 40000, "`" * 160000],
)
def test_mentions_stay_linear_on_hostile_bodies(text):
    """Hostile PR bodies finish quickly instead of backtracking quadratically."""
    import time

    started = time.perf_counter()
    gtm.extract_mentions(text)
    assert time.perf_counter() - started < 2.0
