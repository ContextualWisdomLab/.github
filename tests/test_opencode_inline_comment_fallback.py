import json
import runpy
import sys

import pytest

from scripts.ci.opencode_inline_comment_fallback import (
    format_leftover_range,
    leftover_finding_range,
    main,
    render_inline_comment_failure_body,
    trusted_finding_locations,
    trusted_finding_ranges,
)


def control(*findings: dict[str, object]) -> dict[str, object]:
    """Return a REQUEST_CHANGES control object for fallback tests."""
    return {
        "result": "REQUEST_CHANGES",
        "findings": list(findings),
    }


def test_trusted_finding_locations_keeps_first_safe_path_line_pairs():
    locations = trusted_finding_locations(
        control(
            {"path": "scripts/ci/example.py", "line": 7},
            {"path": 12, "line": 1},
            {"path": "../escape.py", "line": 1},
            {"path": "scripts/ci/example.py", "line": 7},
            {"path": "/abs.py", "line": 3},
            {"path": "scripts/ci/other.py", "line": 0},
            {"path": "scripts/ci/other.py", "line": True},
            {"path": "scripts/ci/other.py", "line": 12},
            {"path": "scripts/ci/string-line.py", "line": "9"},
            {"path": "scripts/ci/bad-line.py", "line": "1.5"},
            {"path": "scripts/ci/zero-string.py", "line": "0"},
            {"path": "scripts/ci/none-line.py", "line": None},
            {"path": "scripts/ci/<script>.py", "line": 4},
            {"path": "scripts/ci/`tick`.py", "line": 5},
            {"path": "scripts/ci/a&b.py", "line": 6},
            {"path": "scripts/ci/close-->comment.py", "line": 8},
            {"path": "scripts/ci/fence```suggestion.py", "line": 9},
            "not-an-object",
        )
    )

    assert locations == [
        ("scripts/ci/example.py", 7),
        ("scripts/ci/other.py", 12),
        ("scripts/ci/string-line.py", 9),
    ]
    assert trusted_finding_locations({"findings": None}) == []
    assert trusted_finding_locations({}) == []


def test_leftover_finding_range_keeps_start_end_and_rejects_inverted():
    assert leftover_finding_range(
        {"path": "scripts/ci/example.py", "start_line": 7, "line": 12}
    ) == ("scripts/ci/example.py", 7, 12, "RIGHT")
    assert leftover_finding_range(
        {"path": "scripts/ci/example.py", "start_line": "7", "line": "12"}
    ) == ("scripts/ci/example.py", 7, 12, "RIGHT")
    assert leftover_finding_range(
        {"path": "scripts/ci/example.py", "line": 9}
    ) == ("scripts/ci/example.py", 9, 9, "RIGHT")
    assert leftover_finding_range(
        {
            "path": "scripts/ci/example.py",
            "start_line": 7,
            "line": 12,
            "side": "LEFT",
        }
    ) == ("scripts/ci/example.py", 7, 12, "LEFT")
    assert leftover_finding_range(
        {"path": "scripts/ci/example.py", "start_line": 12, "line": 7}
    ) is None
    assert leftover_finding_range({"path": "../escape.py", "line": 1}) is None
    assert leftover_finding_range({"path": "scripts/ci/example.py", "line": 0}) is None
    assert format_leftover_range("scripts/ci/example.py", 7, 7) == (
        "scripts/ci/example.py:7"
    )
    assert format_leftover_range("scripts/ci/example.py", 7, 12) == (
        "scripts/ci/example.py:7-12"
    )
    assert format_leftover_range("scripts/ci/example.py", 7, 12, "LEFT") == (
        "scripts/ci/example.py:7-12 LEFT"
    )
    assert trusted_finding_ranges(
        control(
            {"path": "scripts/ci/example.py", "start_line": 7, "line": 12},
            {"path": "scripts/ci/example.py", "start_line": 7, "line": 12},
            {"path": "scripts/ci/example.py", "start_line": 20, "line": 9},
            {"path": "README.md", "line": 3},
            {
                "path": "scripts/ci/deleted.py",
                "start_line": 2,
                "line": 4,
                "side": "LEFT",
            },
            "not-an-object",
        )
    ) == [
        ("scripts/ci/example.py", 7, 12, "RIGHT"),
        ("README.md", 3, 3, "RIGHT"),
        ("scripts/ci/deleted.py", 2, 4, "LEFT"),
    ]
    assert trusted_finding_ranges({"findings": None}) == []
    assert trusted_finding_ranges({}) == []
    locations = trusted_finding_locations(
        control(
            {"path": "scripts/ci/example.py", "start_line": 7, "line": 12},
            {"path": "scripts/ci/example.py", "line": 12},
        )
    )
    assert locations == [("scripts/ci/example.py", 12)]


def test_fallback_body_cites_each_trusted_path_line():
    body = render_inline_comment_failure_body(
        "## Findings\n\nexisting body\n",
        control(
            {"path": "scripts/ci/example.py", "line": 7},
            {"path": "README.md", "line": 3},
        ),
    )

    assert body.startswith("## Findings\n\nexisting body")
    assert "GitHub did not accept the inline review comments" in body
    assert "- `scripts/ci/example.py:7`" in body
    assert "- `README.md:3`" in body
    assert "did not copy suggested diffs into this PR-level body" in body
    ranged = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/example.py", "start_line": 7, "line": 12}),
    )
    assert "- `scripts/ci/example.py:7-12`" in ranged
    assert "- `scripts/ci/example.py:7`" not in ranged
    leftover_left = render_inline_comment_failure_body(
        "## Findings\n",
        control(
            {
                "path": "scripts/ci/example.py",
                "start_line": 7,
                "line": 12,
                "side": "LEFT",
            }
        ),
    )
    assert "- `scripts/ci/example.py:7-12 LEFT`" in leftover_left


def test_fallback_body_explains_missing_trusted_locations():
    body = render_inline_comment_failure_body("overview\n", control())

    assert "GitHub did not accept the inline review comments" in body
    assert "no trusted path:line findings" in body
    assert "- `" not in body


def test_cli_writes_fallback_and_rejects_unreadable_control(tmp_path, monkeypatch):
    control_path = tmp_path / "control.json"
    body_path = tmp_path / "body.md"
    output_path = tmp_path / "fallback.md"
    control_path.write_text(
        json.dumps(
            control({"path": "scripts/ci/example.py", "line": 7}),
        ),
        encoding="utf-8",
    )
    body_path.write_text("## Findings\n", encoding="utf-8")

    assert (
        main(
            [
                "--control",
                str(control_path),
                "--body",
                str(body_path),
                "--output",
                str(output_path),
            ]
        )
        == 0
    )
    written = output_path.read_text(encoding="utf-8")
    assert "- `scripts/ci/example.py:7`" in written

    assert (
        main(
            [
                "--control",
                str(tmp_path / "missing.json"),
                "--body",
                str(body_path),
                "--output",
                str(output_path),
            ]
        )
        == 2
    )
    bad_json = tmp_path / "list.json"
    bad_json.write_text("[]", encoding="utf-8")
    assert (
        main(
            [
                "--control",
                str(bad_json),
                "--body",
                str(body_path),
                "--output",
                str(output_path),
            ]
        )
        == 2
    )
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert (
        main(
            [
                "--control",
                str(broken),
                "--body",
                str(body_path),
                "--output",
                str(output_path),
            ]
        )
        == 2
    )
    assert (
        main(
            [
                "--control",
                str(control_path),
                "--body",
                str(tmp_path / "missing-body.md"),
                "--output",
                str(output_path),
            ]
        )
        == 2
    )

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "opencode_inline_comment_fallback.py",
            "--control",
            str(control_path),
            "--body",
            str(body_path),
            "--output",
            str(output_path),
        ],
    )
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(
            "scripts/ci/opencode_inline_comment_fallback.py", run_name="__main__"
        )
    assert excinfo.value.code == 0
