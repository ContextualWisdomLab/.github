import json
import runpy
import sys

import pytest

from scripts.ci.opencode_inline_comment_fallback import (
    DEFAULT_SINGLE_COMMENT_RETRY_LIMIT,
    LEFTOVER_DIFF_REASONS,
    MANUAL_EDIT_HEADING,
    MANUAL_EDIT_MAX_CHARS,
    apply_github_suggestion_blocks,
    applyable_suggestion_ranges,
    decode_manual_edit_field,
    encode_manual_edit_field,
    format_applyable_origin,
    parse_applyable_origin_field,
    strip_left_origin_fields,
    leftover_diff_fence_reason,
    leftover_diff_fence_receipts,
    leftover_manual_edit_text,
    sanitize_leftover_excerpt,
    parse_leftover_diff_receipts,
    remap_left_comment_to_right_hunk,
    render_leftover_diff_receipts,
    right_hunk_anchor_line,
    comment_on_changed_hunk,
    count_removed_suggestion_lines,
    extract_suggestion_replacement,
    format_applyable_range,
    filter_payload_comments_to_hunks,
    github_error_is_unprocessable,
    github_publication_error_phrase,
    iter_single_comment_payloads,
    main,
    parse_refused_locations,
    parse_refused_receipts,
    parse_unified_diff_hunk_lines,
    record_attached_receipt,
    record_refused_receipt,
    parse_applyable_ranges,
    render_applyable_receipts,
    render_github_suggestion_block,
    suggestion_comment_range,
    render_inline_comment_failure_body,
    render_inline_comment_receipts,
    render_single_comment_review,
    single_comment_range_fields,
    single_comment_retry_limit,
    trusted_finding_locations,
    write_hunk_filtered_payload,
    write_single_comment_payloads,
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
            {"path": "scripts/ci/close-->comment.py", "line": 8},
            {"path": "scripts/ci/fence```suggestion.py", "line": 9},
            "not-an-object",
        )
    )

    assert locations == [
        ("scripts/ci/example.py", 7),
        ("scripts/ci/other.py", 12),
    ]
    assert trusted_finding_locations({"findings": None}) == []
    assert trusted_finding_locations({}) == []


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


def test_github_publication_error_phrase_prefers_json_error_messages():
    phrase = github_publication_error_phrase(
        "gh: HTTP 422: Unprocessable Entity "
        "(https://api.github.com/repos/org/repo/pulls/1/reviews)\n"
        '{"message":"Validation Failed","errors":['
        '{"resource":"PullRequestReview","field":"comments","code":"custom",'
        '"message":"pull_request_review_thread.path is invalid"},'
        '{"message":"Review comments is invalid"}'
        "]}\n"
    )

    assert phrase.startswith("GitHub HTTP 422:")
    assert "pull_request_review_thread.path is invalid" in phrase
    assert "Review comments is invalid" in phrase
    assert "https://api.github.com" not in phrase


def test_github_publication_error_phrase_falls_back_to_http_line():
    assert (
        github_publication_error_phrase(
            "post failed\ngh: Validation Failed (HTTP 422)\n"
        )
        == "GitHub HTTP 422: Validation Failed (HTTP 422)"
    )
    assert (
        github_publication_error_phrase("GitHub HTTP 422: already normalized\n")
        == "GitHub HTTP 422: already normalized"
    )
    assert github_publication_error_phrase("status code 422 only") == "GitHub HTTP 422"
    assert (
        github_publication_error_phrase("https://api.github.example/HTTP 422")
        == "GitHub HTTP 422: 422"
    )
    assert render_inline_comment_receipts([], "GitHub HTTP 422") == []
    assert github_publication_error_phrase("") == "GitHub review write failed"
    assert (
        github_publication_error_phrase("secondary rate limit")
        == "GitHub review write failed"
    )
    assert github_publication_error_phrase("{") == "GitHub review write failed"
    assert (
        github_publication_error_phrase('{"errors":"not-a-list","message":"x"}')
        == "GitHub review write failed"
    )
    assert (
        github_publication_error_phrase('{"errors":[{"code":"custom"}]}')
        == "GitHub review write failed"
    )
    assert (
        github_publication_error_phrase('{"errors":[1,{"message":""}]}')
        == "GitHub review write failed"
    )


def test_fallback_body_attaches_error_phrase_to_each_receipt():
    body = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/example.py", "line": 7}),
        error_text=(
            '{"errors":[{"message":"Line could not be resolved"}]}'
        ),
    )

    assert "## Inline comment publication receipts" in body
    assert (
        "- `scripts/ci/example.py:7` — GitHub HTTP 422: Line could not be resolved"
        in body
    )


def test_mixed_success_receipts_list_only_refused_path_lines():
    refused = parse_refused_locations(
        "scripts/ci/other.py:12\n# note\n../escape.py:1\n"
        "scripts/ci/example.py:0\nbadline\nscripts/ci/other.py:12\n"
        "scripts/ci/skip.py:x\n"
    )
    assert refused == [("scripts/ci/other.py", 12)]

    body = render_inline_comment_failure_body(
        "## Findings\nattached example.py:7\n",
        control(
            {"path": "scripts/ci/example.py", "line": 7},
            {"path": "scripts/ci/other.py", "line": 12},
        ),
        error_text='{"errors":[{"message":"Line could not be resolved"}]}',
        refused_locations=refused,
    )

    assert "accepted some inline comments" in body
    assert (
        "- `scripts/ci/other.py:12` — GitHub HTTP 422: Line could not be resolved"
        in body
    )
    assert "scripts/ci/example.py:7`" not in body
    assert parse_refused_locations("") == []
    assert parse_refused_receipts(
        "scripts/ci/a.py:3\tGitHub HTTP 422: path is invalid\n"
        "scripts/ci/b.py:9\tGitHub HTTP 422: Line could not be resolved\n"
    ) == [
        ("scripts/ci/a.py", 3, "GitHub HTTP 422: path is invalid"),
        ("scripts/ci/b.py", 9, "GitHub HTTP 422: Line could not be resolved"),
    ]
    all_attached = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/example.py", "line": 7}),
        refused_locations=[],
    )
    assert "were still refused" not in all_attached
    assert "did not accept the inline review comments" not in all_attached


def test_mixed_success_receipts_keep_per_comment_422_phrases(tmp_path):
    receipts = [
        (
            "scripts/ci/example.py",
            7,
            "GitHub HTTP 422: pull_request_review_thread.path is invalid",
        ),
        (
            "scripts/ci/other.py",
            12,
            "GitHub HTTP 422: Line could not be resolved",
        ),
    ]
    body = render_inline_comment_failure_body(
        "## Findings\n",
        control(
            {"path": "scripts/ci/example.py", "line": 7},
            {"path": "scripts/ci/other.py", "line": 12},
            {"path": "scripts/ci/ok.py", "line": 4},
        ),
        refused_receipts=receipts,
    )
    assert "accepted some inline comments" in body
    assert (
        "- `scripts/ci/example.py:7` — GitHub HTTP 422: "
        "pull_request_review_thread.path is invalid"
        in body
    )
    assert (
        "- `scripts/ci/other.py:12` — GitHub HTTP 422: Line could not be resolved"
        in body
    )
    assert "scripts/ci/ok.py:4" not in body
    unmatched = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/example.py", "line": 7}),
        refused_receipts=[("scripts/ci/missing.py", 1, "GitHub HTTP 422")],
    )
    assert "were still refused" not in unmatched

    dest = tmp_path / "refused.txt"
    record_refused_receipt(
        dest,
        "scripts/ci/example.py",
        7,
        '{"errors":[{"message":"pull_request_review_thread.path is invalid"}]}',
    )
    record_refused_receipt(
        dest,
        "scripts/ci/other.py",
        12,
        '{"errors":[{"message":"Line could not be resolved"}]}',
    )
    assert parse_refused_receipts(dest.read_text(encoding="utf-8")) == receipts

    comment = tmp_path / "comment.json"
    comment.write_text(
        json.dumps(
            {
                "comments": [
                    {"path": "scripts/ci/example.py", "line": 7, "body": "x"}
                ]
            }
        ),
        encoding="utf-8",
    )
    error = tmp_path / "err.txt"
    error.write_text(
        '{"errors":[{"message":"pull_request_review_thread.path is invalid"}]}\n',
        encoding="utf-8",
    )
    dest2 = tmp_path / "cli-refused.txt"
    assert (
        main(
            [
                "--record-refusal",
                "--refused-locations",
                str(dest2),
                "--comment-file",
                str(comment),
                "--error-file",
                str(error),
            ]
        )
        == 0
    )
    assert "example.py:7\tGitHub HTTP 422: pull_request_review_thread.path is invalid" in dest2.read_text(
        encoding="utf-8"
    )
    assert main(["--record-refusal"]) == 2
    loc_only = tmp_path / "loc-only.txt"
    loc_only.write_text("scripts/ci/example.py:7\n", encoding="utf-8")
    control_only = tmp_path / "control-only.json"
    body_only = tmp_path / "body-only.md"
    out_only = tmp_path / "out-loc.md"
    control_only.write_text(
        json.dumps(control({"path": "scripts/ci/example.py", "line": 7})),
        encoding="utf-8",
    )
    body_only.write_text("## Findings\n", encoding="utf-8")
    assert (
        main(
            [
                "--control",
                str(control_only),
                "--body",
                str(body_only),
                "--output",
                str(out_only),
                "--refused-locations",
                str(loc_only),
            ]
        )
        == 0
    )
    assert "`scripts/ci/example.py:7`" in out_only.read_text(encoding="utf-8")
    two_control = tmp_path / "two-control.json"
    two_out = tmp_path / "two-out.md"
    two_control.write_text(
        json.dumps(
            control(
                {"path": "scripts/ci/example.py", "line": 7},
                {"path": "scripts/ci/other.py", "line": 12},
            )
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--control",
                str(two_control),
                "--body",
                str(body_only),
                "--output",
                str(two_out),
                "--refused-locations",
                str(dest),
            ]
        )
        == 0
    )
    two_text = two_out.read_text(encoding="utf-8")
    assert "pull_request_review_thread.path is invalid" in two_text
    assert "Line could not be resolved" in two_text
    dest3 = tmp_path / "skip.txt"
    record_refused_receipt(dest3, "../escape.py", 1, "HTTP 422")
    assert dest3.read_text(encoding="utf-8") == "" if dest3.exists() else True
    if dest3.exists():
        assert dest3.read_text(encoding="utf-8") == ""
    bad_comment = tmp_path / "bad-comment.json"
    bad_comment.write_text("{}", encoding="utf-8")
    assert (
        main(
            [
                "--record-refusal",
                "--refused-locations",
                str(dest2),
                "--comment-file",
                str(bad_comment),
                "--error-file",
                str(error),
            ]
        )
        == 2
    )


def test_fallback_body_explains_missing_trusted_locations():
    body = render_inline_comment_failure_body("overview\n", control())

    assert "GitHub did not accept the inline review comments" in body
    assert "no trusted path:line findings" in body
    assert "- `" not in body
    with_error = render_inline_comment_failure_body(
        "overview\n",
        control(),
        error_text='{"errors":[{"message":"Review comments is invalid"}]}',
    )
    assert "GitHub error: GitHub HTTP 422: Review comments is invalid" in with_error


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

    error_path = tmp_path / "gh-error.txt"
    error_path.write_text(
        '{"errors":[{"message":"pull_request_review_thread.path is invalid"}]}\n',
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--control",
                str(control_path),
                "--body",
                str(body_path),
                "--output",
                str(output_path),
                "--error-file",
                str(error_path),
            ]
        )
        == 0
    )
    written = output_path.read_text(encoding="utf-8")
    assert (
        "- `scripts/ci/example.py:7` — GitHub HTTP 422: "
        "pull_request_review_thread.path is invalid"
        in written
    )
    two_findings = tmp_path / "two.json"
    two_findings.write_text(
        json.dumps(
            control(
                {"path": "scripts/ci/example.py", "line": 7},
                {"path": "scripts/ci/other.py", "line": 12},
            )
        ),
        encoding="utf-8",
    )
    refused_path = tmp_path / "refused.txt"
    refused_path.write_text("scripts/ci/other.py:12\n", encoding="utf-8")
    assert (
        main(
            [
                "--control",
                str(two_findings),
                "--body",
                str(body_path),
                "--output",
                str(output_path),
                "--error-file",
                str(error_path),
                "--refused-locations",
                str(refused_path),
            ]
        )
        == 0
    )
    mixed = output_path.read_text(encoding="utf-8")
    assert "accepted some inline comments" in mixed
    assert "`scripts/ci/other.py:12`" in mixed
    assert "`scripts/ci/example.py:7`" not in mixed
    assert (
        main(
            [
                "--control",
                str(control_path),
                "--body",
                str(body_path),
                "--output",
                str(output_path),
                "--refused-locations",
                str(tmp_path / "missing-refused.txt"),
            ]
        )
        == 2
    )

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
    assert (
        main(
            [
                "--control",
                str(control_path),
                "--body",
                str(body_path),
                "--output",
                str(output_path),
                "--error-file",
                str(tmp_path / "missing-error.txt"),
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


def test_github_error_is_unprocessable_detects_real_422_bodies():
    assert github_error_is_unprocessable(
        '{"message":"Validation Failed","errors":['
        '{"message":"pull_request_review_thread.path is invalid"}]}'
    )
    assert github_error_is_unprocessable("gh: HTTP 422: Unprocessable Entity")
    assert not github_error_is_unprocessable("Resource not accessible by integration")
    assert not github_error_is_unprocessable("")


def test_iter_single_comment_payloads_keeps_only_safe_comments():
    payload = {
        "event": "REQUEST_CHANGES",
        "body": "review body",
        "commit_id": "a" * 40,
        "comments": [
            {
                "path": "scripts/ci/example.py",
                "line": 7,
                "side": "RIGHT",
                "body": "first",
            },
            {"path": "../escape.py", "line": 1, "body": "bad"},
            {"path": "scripts/ci/other.py", "line": 12, "body": "second"},
            {"path": "scripts/ci/plain.py", "line": 4, "body": "no-side"},
            "not-an-object",
            {"path": "scripts/ci/empty.py", "line": 3, "body": "  "},
        ],
    }

    singles = iter_single_comment_payloads(payload)
    assert [(item["path"], item["line"], item["side"]) for item in singles] == [
        ("scripts/ci/example.py", 7, "RIGHT"),
        ("scripts/ci/other.py", 12, "RIGHT"),
        ("scripts/ci/plain.py", 4, "RIGHT"),
    ]
    first = render_single_comment_review(
        singles[0], event="REQUEST_CHANGES", review_body="review body"
    )
    assert first["event"] == "REQUEST_CHANGES"
    assert first["body"] == "review body"
    assert first["comments"] == [
        {
            "path": "scripts/ci/example.py",
            "line": 7,
            "side": "RIGHT",
            "body": "first",
        }
    ]
    later = render_single_comment_review(
        singles[1], event="COMMENT", review_body=""
    )
    assert later["event"] == "COMMENT"
    assert later["body"] == ""
    assert later["comments"][0]["path"] == "scripts/ci/other.py"
    assert iter_single_comment_payloads({"comments": []}) == []
    assert iter_single_comment_payloads({"comments": "bad"}) == []
    assert iter_single_comment_payloads({"commit_id": "", "comments": [{}]}) == []


def test_single_comment_retry_keeps_multiline_start_line_and_start_side(tmp_path):
    assert single_comment_range_fields({"start_line": 5, "start_side": "RIGHT"}, 7, "RIGHT") == {
        "start_line": 5,
        "start_side": "RIGHT",
    }
    assert single_comment_range_fields({"start_line": 7}, 7, "RIGHT") == {}
    assert single_comment_range_fields({"start_line": 8, "start_side": "RIGHT"}, 7, "RIGHT") == {}
    assert single_comment_range_fields({"start_line": 0, "start_side": "RIGHT"}, 7, "RIGHT") == {}
    assert single_comment_range_fields({"start_line": 5, "start_side": "NOPE"}, 7, "RIGHT") == {
        "start_line": 5,
        "start_side": "RIGHT",
    }
    assert single_comment_range_fields({"start_line": 5}, 7, "LEFT") == {
        "start_line": 5,
        "start_side": "LEFT",
    }

    hunks = parse_unified_diff_hunk_lines(EXAMPLE_UNIFIED_DIFF)
    remapped = apply_github_suggestion_blocks(
        _batch_payload(
            {
                "path": "scripts/ci/example.py",
                "line": 5,
                "side": "LEFT",
                "body": MULTILINE_DIFF_BODY,
            }
        ),
        hunks,
    )
    comment = remapped["comments"][0]
    assert comment["side"] == "RIGHT"
    assert comment["start_line"] == 5
    assert comment["line"] == 7
    assert comment["start_side"] == "RIGHT"
    payload = {
        "event": "REQUEST_CHANGES",
        "body": "review body",
        "commit_id": remapped["commit_id"],
        "comments": remapped["comments"],
    }
    singles = iter_single_comment_payloads(payload)
    assert singles[0]["start_line"] == 5
    assert singles[0]["start_side"] == "RIGHT"
    assert singles[0]["line"] == 7
    rendered = render_single_comment_review(
        singles[0], event="REQUEST_CHANGES", review_body="review body"
    )
    assert rendered["comments"][0]["start_line"] == 5
    assert rendered["comments"][0]["start_side"] == "RIGHT"
    assert rendered["comments"][0]["line"] == 7
    assert "_left_origin_path" not in rendered["comments"][0]

    output_dir = tmp_path / "singles"
    assert write_single_comment_payloads(payload, output_dir) == 1
    written = json.loads((output_dir / "comment-000.json").read_text(encoding="utf-8"))
    assert written["comments"][0]["start_line"] == 5
    assert written["comments"][0]["start_side"] == "RIGHT"
    assert written["comments"][0]["line"] == 7
    assert "start_line" not in render_single_comment_review(
        {
            "path": "scripts/ci/example.py",
            "line": 7,
            "side": "RIGHT",
            "body": "single",
            "commit_id": "c" * 40,
        },
        event="COMMENT",
        review_body="",
    )["comments"][0]

    payload_path = tmp_path / "batch.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    cli_dir = tmp_path / "cli-singles"
    assert (
        main(
            [
                "--split-payload",
                str(payload_path),
                "--output-dir",
                str(cli_dir),
            ]
        )
        == 0
    )
    cli_written = json.loads((cli_dir / "comment-000.json").read_text(encoding="utf-8"))
    assert cli_written["comments"][0]["start_line"] == 5
    assert cli_written["comments"][0]["start_side"] == "RIGHT"
    assert cli_written["comments"][0]["line"] == 7


def test_cli_splits_batch_payload_into_single_comment_files(tmp_path):
    payload = tmp_path / "batch.json"
    payload.write_text(
        json.dumps(
            {
                "event": "REQUEST_CHANGES",
                "body": "review body",
                "commit_id": "b" * 40,
                "comments": [
                    {
                        "path": "scripts/ci/example.py",
                        "line": 7,
                        "side": "RIGHT",
                        "body": "first",
                    },
                    {
                        "path": "scripts/ci/other.py",
                        "line": 12,
                        "side": "LEFT",
                        "body": "second",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "singles"

    assert (
        main(
            [
                "--split-payload",
                str(payload),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 0
    )
    files = sorted(output_dir.glob("comment-*.json"))
    assert [path.name for path in files] == ["comment-000.json", "comment-001.json"]
    first = json.loads(files[0].read_text(encoding="utf-8"))
    assert first["event"] == "COMMENT"
    assert first["comments"][0]["line"] == 7
    assert (
        main(
            [
                "--split-payload",
                str(tmp_path / "missing-batch.json"),
                "--output-dir",
                str(output_dir),
            ]
        )
        == 2
    )
    assert main(["--split-payload", str(payload)]) == 2
    error_path = tmp_path / "422.txt"
    error_path.write_text("gh: HTTP 422: Unprocessable Entity\n", encoding="utf-8")
    assert main(["--is-unprocessable", "--error-file", str(error_path)]) == 0
    error_path.write_text("Resource not accessible by integration\n", encoding="utf-8")
    assert main(["--is-unprocessable", "--error-file", str(error_path)]) == 1
    assert main(["--is-unprocessable"]) == 2
    assert main([]) == 2


def _batch_payload(*comments: dict[str, object]) -> dict[str, object]:
    """Return a batch review payload for retry-limit tests."""
    return {
        "event": "REQUEST_CHANGES",
        "body": "review body",
        "commit_id": "c" * 40,
        "comments": list(comments),
    }


def test_single_comment_retry_limit_defaults_and_rejects_invalid(monkeypatch):
    monkeypatch.delenv("OPENCODE_INLINE_COMMENT_RETRY_LIMIT", raising=False)
    assert single_comment_retry_limit() == DEFAULT_SINGLE_COMMENT_RETRY_LIMIT
    assert single_comment_retry_limit(5) == 5
    assert single_comment_retry_limit("3") == 3
    assert single_comment_retry_limit(" 8 ") == 8
    assert single_comment_retry_limit(0) == DEFAULT_SINGLE_COMMENT_RETRY_LIMIT
    assert single_comment_retry_limit(-1) == DEFAULT_SINGLE_COMMENT_RETRY_LIMIT
    assert single_comment_retry_limit(True) == DEFAULT_SINGLE_COMMENT_RETRY_LIMIT
    assert single_comment_retry_limit("abc") == DEFAULT_SINGLE_COMMENT_RETRY_LIMIT
    assert single_comment_retry_limit("0") == DEFAULT_SINGLE_COMMENT_RETRY_LIMIT
    monkeypatch.setenv("OPENCODE_INLINE_COMMENT_RETRY_LIMIT", "4")
    assert single_comment_retry_limit() == 4
    monkeypatch.setenv("OPENCODE_INLINE_COMMENT_RETRY_LIMIT", "nope")
    assert single_comment_retry_limit() == DEFAULT_SINGLE_COMMENT_RETRY_LIMIT


def test_write_single_comment_payloads_caps_retry_and_records_deferred(tmp_path):
    payload = _batch_payload(
        {"path": "scripts/ci/a.py", "line": 1, "body": "one"},
        {"path": "scripts/ci/b.py", "line": 2, "body": "two"},
        {"path": "scripts/ci/c.py", "line": 3, "body": "three"},
    )
    output_dir = tmp_path / "singles"
    deferred = tmp_path / "deferred.txt"
    assert write_single_comment_payloads(payload, output_dir, limit=1, deferred_path=deferred) == 1
    files = sorted(output_dir.glob("comment-*.json"))
    assert [path.name for path in files] == ["comment-000.json"]
    assert parse_refused_locations(deferred.read_text(encoding="utf-8")) == [
        ("scripts/ci/b.py", 2),
        ("scripts/ci/c.py", 3),
    ]
    empty_deferred = tmp_path / "none.txt"
    assert write_single_comment_payloads(payload, tmp_path / "all", limit=20, deferred_path=empty_deferred) == 3
    assert empty_deferred.read_text(encoding="utf-8") == ""


def test_mixed_success_receipts_list_attached_beside_refused():
    body = render_inline_comment_failure_body(
        "## Findings\n",
        control(
            {"path": "scripts/ci/ok.py", "line": 4},
            {"path": "scripts/ci/example.py", "line": 7},
            {"path": "scripts/ci/later.py", "line": 20},
            {"path": "scripts/ci/skip.py", "line": 9},
        ),
        refused_receipts=[
            (
                "scripts/ci/example.py",
                7,
                "GitHub HTTP 422: pull_request_review_thread.path is invalid",
            )
        ],
        attached_locations=[("scripts/ci/ok.py", 4), ("scripts/ci/missing.py", 1)],
        deferred_locations=[("scripts/ci/later.py", 20), ("scripts/ci/later.py", 20)],
        retry_limit=1,
    )
    assert "GitHub accepted these trusted current-head finding locations:" in body
    assert "- `scripts/ci/ok.py:4`" in body
    assert "These trusted current-head finding locations were still refused:" in body
    assert (
        "- `scripts/ci/example.py:7` — GitHub HTTP 422: "
        "pull_request_review_thread.path is invalid"
        in body
    )
    assert "were not retried (retry limit 1):" in body
    assert "- `scripts/ci/later.py:20`" in body
    assert "scripts/ci/skip.py:9" not in body
    assert "scripts/ci/missing.py:1" not in body
    deferred_only = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/later.py", "line": 20}),
        refused_locations=[],
        deferred_locations=[("scripts/ci/later.py", 20)],
        retry_limit=1,
    )
    assert "were not retried (retry limit 1):" in deferred_only
    assert "- `scripts/ci/later.py:20`" in deferred_only
    assert "did not copy suggested diffs" in deferred_only
    attached_only = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/ok.py", "line": 4}),
        refused_receipts=[],
        attached_locations=[("scripts/ci/ok.py", 4)],
    )
    assert "- `scripts/ci/ok.py:4`" in attached_only
    assert "were still refused" not in attached_only
    attached_without_refused_kw = render_inline_comment_failure_body(
        "## Findings\n",
        control(
            {"path": "scripts/ci/ok.py", "line": 4},
            {"path": "scripts/ci/later.py", "line": 20},
        ),
        attached_locations=[("scripts/ci/ok.py", 4)],
        deferred_locations=[("scripts/ci/later.py", 20)],
        retry_limit=1,
    )
    assert "- `scripts/ci/ok.py:4`" in attached_without_refused_kw
    assert "were not retried (retry limit 1):" in attached_without_refused_kw
    assert "were still refused" not in attached_without_refused_kw
    empty_outcome_files = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/ok.py", "line": 4}),
        attached_locations=[],
        deferred_locations=[],
    )
    assert "were still refused" not in empty_outcome_files
    assert "did not accept the inline review comments" not in empty_outcome_files


def test_cli_records_attached_and_bounded_split(tmp_path):
    payload = tmp_path / "batch.json"
    payload.write_text(
        json.dumps(
            _batch_payload(
                {"path": "scripts/ci/a.py", "line": 1, "side": "RIGHT", "body": "one"},
                {"path": "scripts/ci/b.py", "line": 2, "side": "RIGHT", "body": "two"},
            )
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "singles"
    deferred = tmp_path / "deferred.txt"
    assert (
        main(
            [
                "--split-payload",
                str(payload),
                "--output-dir",
                str(output_dir),
                "--retry-limit",
                "1",
                "--deferred-locations",
                str(deferred),
            ]
        )
        == 0
    )
    assert [path.name for path in sorted(output_dir.glob("comment-*.json"))] == [
        "comment-000.json"
    ]
    assert "scripts/ci/b.py:2" in deferred.read_text(encoding="utf-8")

    comment = tmp_path / "comment.json"
    comment.write_text(
        json.dumps({"comments": [{"path": "scripts/ci/a.py", "line": 1, "body": "x"}]}),
        encoding="utf-8",
    )
    attached = tmp_path / "attached.txt"
    assert (
        main(
            [
                "--record-attach",
                "--attached-locations",
                str(attached),
                "--comment-file",
                str(comment),
            ]
        )
        == 0
    )
    assert attached.read_text(encoding="utf-8") == "scripts/ci/a.py:1\n"
    record_attached_receipt(tmp_path / "skip.txt", "../escape.py", 1)
    record_attached_receipt(tmp_path / "skip.txt", "scripts/ci/a.py", 0)
    assert not (tmp_path / "skip.txt").exists()
    assert main(["--record-attach"]) == 2
    string_line = tmp_path / "string-line.json"
    string_line.write_text(
        json.dumps({"comments": [{"path": "scripts/ci/a.py", "line": "1"}]}),
        encoding="utf-8",
    )
    dest_empty = tmp_path / "empty-attach.txt"
    assert (
        main(
            [
                "--record-attach",
                "--attached-locations",
                str(dest_empty),
                "--comment-file",
                str(string_line),
            ]
        )
        == 0
    )
    assert not dest_empty.exists() or dest_empty.read_text(encoding="utf-8") == ""
    assert (
        main(
            [
                "--record-attach",
                "--attached-locations",
                str(attached),
                "--comment-file",
                str(tmp_path / "missing-comment.json"),
            ]
        )
        == 2
    )
    bad_comment = tmp_path / "bad-comment.json"
    bad_comment.write_text("{}", encoding="utf-8")
    assert (
        main(
            [
                "--record-attach",
                "--attached-locations",
                str(attached),
                "--comment-file",
                str(bad_comment),
            ]
        )
        == 2
    )

    control_path = tmp_path / "control.json"
    body_path = tmp_path / "body.md"
    output_path = tmp_path / "out.md"
    refused = tmp_path / "refused.txt"
    control_path.write_text(
        json.dumps(
            control(
                {"path": "scripts/ci/a.py", "line": 1},
                {"path": "scripts/ci/b.py", "line": 2},
                {"path": "scripts/ci/c.py", "line": 3},
            )
        ),
        encoding="utf-8",
    )
    body_path.write_text("## Findings\n", encoding="utf-8")
    refused.write_text(
        "scripts/ci/b.py:2\tGitHub HTTP 422: Line could not be resolved\n",
        encoding="utf-8",
    )
    assert (
        main(
            [
                "--control",
                str(control_path),
                "--body",
                str(body_path),
                "--output",
                str(output_path),
                "--refused-locations",
                str(refused),
                "--attached-locations",
                str(attached),
                "--deferred-locations",
                str(deferred),
                "--retry-limit",
                "1",
            ]
        )
        == 0
    )
    written = output_path.read_text(encoding="utf-8")
    assert "- `scripts/ci/a.py:1`" in written
    assert "- `scripts/ci/b.py:2` — GitHub HTTP 422: Line could not be resolved" in written
    assert "- `scripts/ci/c.py:3`" not in written
    assert "scripts/ci/b.py:2`" in written or "were still refused" in written
    assert "were not retried (retry limit 1):" in written
    assert "- `scripts/ci/b.py:2`" in written or "scripts/ci/b.py:2" in written
    assert main(
        [
            "--control",
            str(control_path),
            "--body",
            str(body_path),
            "--output",
            str(output_path),
            "--attached-locations",
            str(tmp_path / "missing-attached.txt"),
        ]
    ) == 2
    assert main(
        [
            "--control",
            str(control_path),
            "--body",
            str(body_path),
            "--output",
            str(output_path),
            "--deferred-locations",
            str(tmp_path / "missing-deferred.txt"),
        ]
    ) == 2


EXAMPLE_UNIFIED_DIFF = """\
diff --git a/scripts/ci/example.py b/scripts/ci/example.py
index 1111111..2222222 100644
--- a/scripts/ci/example.py
+++ b/scripts/ci/example.py
@@ -5,7 +5,8 @@ def run():
     keep
     keep
     keep
-    old
+    new
     keep
     keep
     keep
diff --git a/scripts/ci/removed.py b/scripts/ci/removed.py
index 3333333..0000000 100644
--- a/scripts/ci/removed.py
+++ /dev/null
@@ -10,3 +0,0 @@ leftover
-gone
-gone
-gone
diff --git a/scripts/ci/added.py b/scripts/ci/added.py
new file mode 100644
index 0000000..4444444
--- /dev/null
+++ b/scripts/ci/added.py
@@ -0,0 +1 @@
+created
diff --git a/old/name.py b/scripts/ci/renamed.py
similarity index 90%
rename from old/name.py
rename to scripts/ci/renamed.py
index 5555555..6666666 100644
--- a/old/name.py
+++ b/scripts/ci/renamed.py
@@ -2 +2 @@
-old
+new
"""


def test_parse_unified_diff_hunk_lines_covers_github_commentable_ranges():
    hunks = parse_unified_diff_hunk_lines(EXAMPLE_UNIFIED_DIFF)

    assert hunks["scripts/ci/example.py"]["RIGHT"] == set(range(5, 13))
    assert hunks["scripts/ci/example.py"]["LEFT"] == set(range(5, 12))
    assert hunks["scripts/ci/removed.py"]["LEFT"] == {10, 11, 12}
    assert hunks["scripts/ci/removed.py"]["RIGHT"] == set()
    assert hunks["scripts/ci/added.py"]["RIGHT"] == {1}
    assert hunks["scripts/ci/added.py"]["LEFT"] == set()
    assert hunks["scripts/ci/renamed.py"]["RIGHT"] == {2}
    assert hunks["old/name.py"]["LEFT"] == {2}
    assert parse_unified_diff_hunk_lines("") == {}
    assert parse_unified_diff_hunk_lines("+++ not-a-path\n--- also-bad\n") == {}
    assert comment_on_changed_hunk("scripts/ci/example.py", 5, hunks)
    assert comment_on_changed_hunk("scripts/ci/example.py", 12, hunks)
    assert not comment_on_changed_hunk("scripts/ci/example.py", 20, hunks)
    assert comment_on_changed_hunk(
        "scripts/ci/removed.py", 11, hunks, side="LEFT"
    )
    assert not comment_on_changed_hunk(
        "scripts/ci/removed.py", 11, hunks, side="RIGHT"
    )
    assert not comment_on_changed_hunk("../escape.py", 1, hunks)
    assert not comment_on_changed_hunk("scripts/ci/example.py", 0, hunks)
    assert comment_on_changed_hunk(
        "scripts/ci/example.py", 7, hunks, side="NOPE"
    )


def test_filter_payload_comments_to_hunks_drops_off_hunk_before_post():
    hunks = parse_unified_diff_hunk_lines(EXAMPLE_UNIFIED_DIFF)
    payload = _batch_payload(
        {"path": "scripts/ci/example.py", "line": 7, "side": "RIGHT", "body": "on hunk"},
        {"path": "scripts/ci/example.py", "line": 20, "side": "RIGHT", "body": "past hunk"},
        {"path": "scripts/ci/example.py", "line": 20, "side": "RIGHT", "body": "duplicate skip"},
        {"path": "scripts/ci/removed.py", "line": 11, "side": "LEFT", "body": "deleted"},
        {"path": "scripts/ci/missing.py", "line": 3, "body": "unchanged path"},
        {"path": "../escape.py", "line": 1, "body": "unsafe"},
        "not-an-object",
    )

    filtered, skipped = filter_payload_comments_to_hunks(payload, hunks)
    assert [item["line"] for item in filtered["comments"]] == [7, 11]
    assert skipped == [
        ("scripts/ci/example.py", 20),
        ("scripts/ci/missing.py", 3),
    ]
    unchanged, no_skip = filter_payload_comments_to_hunks(payload, {})
    assert unchanged["comments"] == payload["comments"]
    assert no_skip == []
    no_comments, empty_skip = filter_payload_comments_to_hunks(
        {"event": "COMMENT", "comments": "bad"}, hunks
    )
    assert no_comments["comments"] == "bad"
    assert empty_skip == []


def test_skipped_receipts_list_off_hunk_locations():
    body = render_inline_comment_failure_body(
        "## Findings\n",
        control(
            {"path": "scripts/ci/example.py", "line": 7},
            {"path": "scripts/ci/example.py", "line": 20},
            {"path": "scripts/ci/ok.py", "line": 4},
        ),
        attached_locations=[("scripts/ci/ok.py", 4)],
        skipped_locations=[
            ("scripts/ci/example.py", 20),
            ("scripts/ci/foreign.py", 1),
        ],
    )
    assert "GitHub accepted these trusted current-head finding locations:" in body
    assert "- `scripts/ci/ok.py:4`" in body
    assert (
        "were not posted because they sit outside every current-head changed hunk:"
        in body
    )
    assert "- `scripts/ci/example.py:20`" in body
    assert "scripts/ci/foreign.py" not in body
    skipped_only = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/example.py", "line": 20}),
        skipped_locations=[("scripts/ci/example.py", 20)],
    )
    assert (
        "were not posted because they sit outside every current-head changed hunk:"
        in skipped_only
    )
    assert "did not copy suggested diffs" in skipped_only
    assert "did not accept the inline review comments" not in skipped_only
    skipped_with_deferred = render_inline_comment_failure_body(
        "## Findings\n",
        control(
            {"path": "scripts/ci/later.py", "line": 20},
            {"path": "scripts/ci/example.py", "line": 20},
        ),
        deferred_locations=[("scripts/ci/later.py", 20)],
        skipped_locations=[("scripts/ci/example.py", 20)],
        retry_limit=1,
    )
    assert "were not retried (retry limit 1):" in skipped_with_deferred
    assert (
        "were not posted because they sit outside every current-head changed hunk:"
        in skipped_with_deferred
    )


def test_cli_filters_payload_to_current_head_hunks(tmp_path):
    payload = tmp_path / "batch.json"
    payload.write_text(
        json.dumps(
            _batch_payload(
                {
                    "path": "scripts/ci/example.py",
                    "line": 7,
                    "side": "RIGHT",
                    "body": "keep",
                },
                {
                    "path": "scripts/ci/example.py",
                    "line": 20,
                    "side": "RIGHT",
                    "body": "drop",
                },
            )
        ),
        encoding="utf-8",
    )
    hunks_diff = tmp_path / "hunks.diff"
    hunks_diff.write_text(EXAMPLE_UNIFIED_DIFF, encoding="utf-8")
    output = tmp_path / "filtered.json"
    skipped = tmp_path / "skipped.txt"

    assert (
        main(
            [
                "--filter-hunks",
                "--payload",
                str(payload),
                "--hunks-diff",
                str(hunks_diff),
                "--output",
                str(output),
                "--skipped-locations",
                str(skipped),
            ]
        )
        == 0
    )
    filtered = json.loads(output.read_text(encoding="utf-8"))
    assert [item["line"] for item in filtered["comments"]] == [7]
    assert skipped.read_text(encoding="utf-8") == "scripts/ci/example.py:20\n"
    assert write_hunk_filtered_payload(
        json.loads(payload.read_text(encoding="utf-8")),
        parse_unified_diff_hunk_lines(EXAMPLE_UNIFIED_DIFF),
        tmp_path / "again.json",
    ) == 1
    assert main(["--filter-hunks"]) == 2
    assert (
        main(
            [
                "--filter-hunks",
                "--payload",
                str(tmp_path / "missing.json"),
                "--hunks-diff",
                str(hunks_diff),
                "--output",
                str(output),
            ]
        )
        == 2
    )

    control_path = tmp_path / "control.json"
    body_path = tmp_path / "body.md"
    receipt = tmp_path / "receipt.md"
    control_path.write_text(
        json.dumps(control({"path": "scripts/ci/example.py", "line": 20})),
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
                str(receipt),
                "--skipped-locations",
                str(skipped),
            ]
        )
        == 0
    )
    assert "scripts/ci/example.py:20" in receipt.read_text(encoding="utf-8")
    assert (
        main(
            [
                "--control",
                str(control_path),
                "--body",
                str(body_path),
                "--output",
                str(receipt),
                "--skipped-locations",
                str(tmp_path / "missing-skipped.txt"),
            ]
        )
        == 2
    )


SUGGESTED_DIFF_BODY = """\
### HIGH replace old line

- Location: `scripts/ci/example.py:7`
- Problem: The old line is wrong.
- Root cause: The review found the current-head hunk.
- Fix: Replace the old line.
- Regression test: Keep the hunk prefilter.

#### Suggested diff
```diff
@@ -7 +7 @@
-    old
+    new
```
"""


def test_extract_suggestion_replacement_from_unified_and_plain_diffs():
    assert (
        extract_suggestion_replacement("@@ -7 +7 @@\n-    old\n+    new\n")
        == "    new"
    )
    assert extract_suggestion_replacement(
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,2 +1,3 @@\n keep\n-old\n+new1\n+new2\n"
    ) == "new1\nnew2"
    assert extract_suggestion_replacement("plain replacement") == "plain replacement"
    assert extract_suggestion_replacement("Cannot provide diff - inaccessible") is None
    assert extract_suggestion_replacement("n/a") is None
    assert extract_suggestion_replacement("") is None
    assert extract_suggestion_replacement("- only removed\n") is None
    assert extract_suggestion_replacement("+has ``` fence") is None
    assert extract_suggestion_replacement("plain ``` no") is None
    assert render_github_suggestion_block("    new") == "```suggestion\n    new\n```"


def test_apply_github_suggestion_blocks_on_surviving_right_comments():
    payload = _batch_payload(
        {
            "path": "scripts/ci/example.py",
            "line": 7,
            "side": "RIGHT",
            "body": SUGGESTED_DIFF_BODY,
        },
        {
            "path": "scripts/ci/removed.py",
            "line": 11,
            "side": "LEFT",
            "body": SUGGESTED_DIFF_BODY,
        },
        {
            "path": "scripts/ci/plain.py",
            "line": 4,
            "side": "RIGHT",
            "body": "no suggested diff here",
        },
        {
            "path": "scripts/ci/done.py",
            "line": 2,
            "side": "RIGHT",
            "body": "already\n\n```suggestion\nkept\n```\n",
        },
        "not-an-object",
    )
    updated = apply_github_suggestion_blocks(payload)
    bodies = [item["body"] if isinstance(item, dict) else item for item in updated["comments"]]
    assert "```suggestion\n    new\n```" in bodies[0]
    assert "```diff" in bodies[0]
    assert "start_line" not in updated["comments"][0]
    assert "```suggestion" not in bodies[1]
    assert bodies[2] == "no suggested diff here"
    assert bodies[3].count("```suggestion") == 1
    assert bodies[4] == "not-an-object"
    unchanged = apply_github_suggestion_blocks({"event": "COMMENT", "comments": "bad"})
    assert unchanged["comments"] == "bad"
    second_fence = apply_github_suggestion_blocks(
        _batch_payload(
            {
                "path": "scripts/ci/example.py",
                "line": 7,
                "side": "RIGHT",
                "body": (
                    "#### Suggested diff\n```diff\nCannot provide diff\n```\n\n"
                    "#### Suggested diff\n```diff\n+fixed\n```\n"
                ),
            }
        )
    )
    assert "```suggestion\nfixed\n```" in second_fence["comments"][0]["body"]


def test_write_hunk_filtered_payload_adds_suggestion_on_surviving_hunk(tmp_path):
    payload = _batch_payload(
        {
            "path": "scripts/ci/example.py",
            "line": 7,
            "side": "RIGHT",
            "body": SUGGESTED_DIFF_BODY,
        },
        {
            "path": "scripts/ci/example.py",
            "line": 20,
            "side": "RIGHT",
            "body": SUGGESTED_DIFF_BODY,
        },
    )
    output = tmp_path / "filtered.json"
    skipped = tmp_path / "skipped.txt"
    assert (
        write_hunk_filtered_payload(
            payload,
            parse_unified_diff_hunk_lines(EXAMPLE_UNIFIED_DIFF),
            output,
            skipped_path=skipped,
        )
        == 1
    )
    filtered = json.loads(output.read_text(encoding="utf-8"))
    assert filtered["comments"][0]["line"] == 7
    assert "start_line" not in filtered["comments"][0]
    assert "```suggestion\n    new\n```" in filtered["comments"][0]["body"]
    assert skipped.read_text(encoding="utf-8") == "scripts/ci/example.py:20\n"
    empty_hunks_out = tmp_path / "unfiltered.json"
    assert write_hunk_filtered_payload(payload, {}, empty_hunks_out) == 2
    unfiltered = json.loads(empty_hunks_out.read_text(encoding="utf-8"))
    assert "```suggestion\n    new\n```" in unfiltered["comments"][0]["body"]
    assert "start_line" not in unfiltered["comments"][0]


MULTILINE_DIFF_BODY = """\
### HIGH replace three lines

- Location: `scripts/ci/example.py:5`

#### Suggested diff
```diff
@@ -5,3 +5,2 @@
-    keep
-    keep
-    keep
+    first
+    second
```
"""


def test_suggestion_comment_range_spans_on_hunk_removed_lines():
    hunks = parse_unified_diff_hunk_lines(EXAMPLE_UNIFIED_DIFF)
    diff = (
        "@@ -5,3 +5,2 @@\n"
        "-    keep\n"
        "-    keep\n"
        "-    keep\n"
        "+    first\n"
        "+    second\n"
    )
    assert count_removed_suggestion_lines(diff) == 3
    assert count_removed_suggestion_lines(
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n-old\n+new\n"
    ) == 1
    assert suggestion_comment_range(
        "scripts/ci/example.py", 5, diff, hunks
    ) == (5, 7)
    assert suggestion_comment_range(
        "scripts/ci/example.py", 11, diff, hunks
    ) == (None, 11)
    assert suggestion_comment_range(
        "scripts/ci/example.py", 5, diff, {}
    ) == (None, 5)
    assert suggestion_comment_range(
        "scripts/ci/example.py", 7, "-old\n+new\n", hunks
    ) == (None, 7)
    assert suggestion_comment_range("../escape.py", 5, diff, hunks)[0] is None
    assert suggestion_comment_range("scripts/ci/example.py", 0, diff, hunks) == (
        None,
        1,
    )
    assert suggestion_comment_range(
        "scripts/ci/example.py", 5, diff, hunks, side="NOPE"
    ) == (5, 7)
    assert suggestion_comment_range(
        "scripts/ci/example.py", "5", diff, hunks
    ) == (None, 1)


def test_apply_github_suggestion_blocks_sets_multiline_range(tmp_path):
    hunks = parse_unified_diff_hunk_lines(EXAMPLE_UNIFIED_DIFF)
    payload = _batch_payload(
        {
            "path": "scripts/ci/example.py",
            "line": 5,
            "side": "RIGHT",
            "body": MULTILINE_DIFF_BODY,
        },
        {
            "path": "scripts/ci/example.py",
            "line": 11,
            "side": "RIGHT",
            "body": MULTILINE_DIFF_BODY,
        },
    )
    updated = apply_github_suggestion_blocks(payload, hunks)
    first, second = updated["comments"]
    assert first["start_line"] == 5
    assert first["line"] == 7
    assert first["start_side"] == "RIGHT"
    assert "```suggestion\n    first\n    second\n```" in first["body"]
    assert "start_line" not in second
    assert second["line"] == 11
    already = apply_github_suggestion_blocks(
        _batch_payload(
            {
                "path": "scripts/ci/example.py",
                "line": 5,
                "side": "RIGHT",
                "body": MULTILINE_DIFF_BODY + "\n```suggestion\nkept\n```\n",
            }
        ),
        hunks,
    )
    assert already["comments"][0]["start_line"] == 5
    assert already["comments"][0]["body"].count("```suggestion") == 1
    no_line = apply_github_suggestion_blocks(
        _batch_payload(
            {
                "path": "scripts/ci/example.py",
                "line": True,
                "side": "RIGHT",
                "body": MULTILINE_DIFF_BODY,
            }
        ),
        hunks,
    )
    assert "start_line" not in no_line["comments"][0]
    assert "```suggestion" in no_line["comments"][0]["body"]
    output = tmp_path / "ranged.json"
    assert write_hunk_filtered_payload(payload, hunks, output) == 2
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["comments"][0]["start_line"] == 5
    assert written["comments"][0]["line"] == 7


def test_applyable_ranges_parse_and_render_path_start_end():
    assert format_applyable_range("scripts/ci/example.py", 5, 5) == (
        "scripts/ci/example.py:5"
    )
    assert format_applyable_range("scripts/ci/example.py", 5, 7) == (
        "scripts/ci/example.py:5-7"
    )
    parsed = parse_applyable_ranges(
        "\n".join(
            [
                "scripts/ci/example.py:5-7",
                "scripts/ci/ok.py:4",
                "scripts/ci/example.py:5-7",
                "../escape.py:1-2",
                "scripts/ci/bad.py:7-3",
                "scripts/ci/nope.py:abc",
                "scripts/ci/nope.py:1-x",
                "# comment",
                "",
                "not-a-location",
            ]
        )
    )
    assert parsed == [
        ("scripts/ci/example.py", 5, 7, None, None),
        ("scripts/ci/ok.py", 4, 4, None, None),
    ]
    assert render_applyable_receipts(parsed) == [
        "- `scripts/ci/example.py:5-7`",
        "- `scripts/ci/ok.py:4`",
    ]
    assert applyable_suggestion_ranges({"comments": "bad"}) == []
    assert applyable_suggestion_ranges(
        {
            "comments": [
                {
                    "path": "scripts/ci/removed.py",
                    "line": 11,
                    "side": "LEFT",
                    "body": "```suggestion\nremoved = True\n```\n",
                }
            ]
        }
    ) == []
    payload = apply_github_suggestion_blocks(
        _batch_payload(
            {
                "path": "scripts/ci/example.py",
                "line": 5,
                "side": "RIGHT",
                "body": MULTILINE_DIFF_BODY,
            },
            {
                "path": "scripts/ci/example.py",
                "line": 7,
                "side": "RIGHT",
                "body": SUGGESTED_DIFF_BODY,
            },
            {
                "path": "scripts/ci/plain.py",
                "line": 4,
                "side": "RIGHT",
                "body": "no suggestion",
            },
        ),
        parse_unified_diff_hunk_lines(EXAMPLE_UNIFIED_DIFF),
    )
    assert applyable_suggestion_ranges(payload) == [
        ("scripts/ci/example.py", 5, 7, None, None),
        ("scripts/ci/example.py", 7, 7, None, None),
    ]
    swapped = applyable_suggestion_ranges(
        {
            "comments": [
                {
                    "path": "scripts/ci/example.py",
                    "line": 5,
                    "start_line": 7,
                    "body": "```suggestion\nx\n```",
                },
                {
                    "path": "scripts/ci/example.py",
                    "line": 7,
                    "start_line": 5,
                    "body": "```suggestion\ny\n```",
                },
                "not-an-object",
            ]
        }
    )
    assert swapped == [("scripts/ci/example.py", 5, 7, None, None)]
    assert applyable_suggestion_ranges(
        {
            "comments": [
                {
                    "path": "../escape.py",
                    "line": 1,
                    "body": "```suggestion\nx\n```",
                },
                {
                    "path": "scripts/ci/example.py",
                    "line": True,
                    "body": "```suggestion\nx\n```",
                },
                {
                    "path": "scripts/ci/example.py",
                    "line": 5,
                    "start_line": 0,
                    "body": "```suggestion\nx\n```",
                },
            ]
        }
    ) == []


def test_overview_receipts_list_applyable_suggestion_ranges(tmp_path):
    body = render_inline_comment_failure_body(
        "## Findings\n",
        control(
            {"path": "scripts/ci/example.py", "line": 5},
            {"path": "scripts/ci/ok.py", "line": 4},
            {"path": "scripts/ci/skip.py", "line": 9},
        ),
        skipped_locations=[("scripts/ci/skip.py", 9)],
        applyable_locations=[
            ("scripts/ci/example.py", 5, 7),
            ("scripts/ci/ok.py", 4, 4),
            ("scripts/ci/foreign.py", 1, 2),
        ],
    )
    assert "GitHub can apply these suggested replacements:" in body
    assert "- `scripts/ci/example.py:5-7`" in body
    assert "- `scripts/ci/ok.py:4`" in body
    assert "scripts/ci/foreign.py" not in body
    assert "sit outside every current-head changed hunk" in body
    applyable_only = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/example.py", "line": 5}),
        applyable_locations=[("scripts/ci/example.py", 5, 7)],
    )
    assert "GitHub can apply these suggested replacements:" in applyable_only
    assert "- `scripts/ci/example.py:5-7`" in applyable_only
    assert "did not accept the inline review comments" not in applyable_only
    empty_applyable = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/ok.py", "line": 4}),
        applyable_locations=[],
    )
    assert "GitHub can apply these suggested replacements:" not in empty_applyable

    payload = tmp_path / "batch.json"
    payload.write_text(
        json.dumps(
            _batch_payload(
                {
                    "path": "scripts/ci/example.py",
                    "line": 5,
                    "side": "RIGHT",
                    "body": MULTILINE_DIFF_BODY,
                }
            )
        ),
        encoding="utf-8",
    )
    hunks_diff = tmp_path / "hunks.diff"
    hunks_diff.write_text(EXAMPLE_UNIFIED_DIFF, encoding="utf-8")
    output = tmp_path / "filtered.json"
    applyable = tmp_path / "applyable.txt"
    assert (
        main(
            [
                "--filter-hunks",
                "--payload",
                str(payload),
                "--hunks-diff",
                str(hunks_diff),
                "--output",
                str(output),
                "--applyable-locations",
                str(applyable),
            ]
        )
        == 0
    )
    assert applyable.read_text(encoding="utf-8") == "scripts/ci/example.py:5-7\n"
    control_path = tmp_path / "control.json"
    body_path = tmp_path / "body.md"
    receipt = tmp_path / "receipt.md"
    control_path.write_text(
        json.dumps(control({"path": "scripts/ci/example.py", "line": 5})),
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
                str(receipt),
                "--applyable-locations",
                str(applyable),
            ]
        )
        == 0
    )
    assert "scripts/ci/example.py:5-7" in receipt.read_text(encoding="utf-8")
    assert (
        main(
            [
                "--control",
                str(control_path),
                "--body",
                str(body_path),
                "--output",
                str(receipt),
                "--applyable-locations",
                str(tmp_path / "missing-applyable.txt"),
            ]
        )
        == 2
    )


CANNOT_PROVIDE_DIFF_BODY = """\
### HIGH no replacement

- Location: `scripts/ci/example.py:12`

#### Suggested diff
```diff
Cannot provide diff - original file inaccessible
```
"""

NA_DIFF_BODY = """\
### HIGH n/a

#### Suggested diff
```diff
n/a
```
"""


def test_leftover_diff_receipts_separate_left_and_cannot_provide_from_applyable():
    hunks = parse_unified_diff_hunk_lines(EXAMPLE_UNIFIED_DIFF)
    payload = apply_github_suggestion_blocks(
        _batch_payload(
            {
                "path": "scripts/ci/example.py",
                "line": 5,
                "side": "RIGHT",
                "body": MULTILINE_DIFF_BODY,
            },
            {
                "path": "scripts/ci/example.py",
                "line": 12,
                "side": "RIGHT",
                "body": CANNOT_PROVIDE_DIFF_BODY,
            },
            {
                "path": "scripts/ci/removed.py",
                "line": 11,
                "side": "LEFT",
                "body": SUGGESTED_DIFF_BODY,
            },
            {
                "path": "scripts/ci/example.py",
                "line": 8,
                "side": "RIGHT",
                "body": NA_DIFF_BODY,
            },
            {
                "path": "scripts/ci/plain.py",
                "line": 4,
                "side": "RIGHT",
                "body": "no suggested diff",
            },
        ),
        hunks,
    )
    applyable = applyable_suggestion_ranges(payload)
    leftover = leftover_diff_fence_receipts(payload)
    leftover_keys = {(path, line) for path, line, _reason, _excerpt in leftover}
    applyable_starts = {(path, start) for path, start, _end, *_rest in applyable}
    cannot_excerpt = leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY)
    left_excerpt = leftover_manual_edit_text(SUGGESTED_DIFF_BODY)
    na_excerpt = leftover_manual_edit_text(NA_DIFF_BODY)
    assert applyable == [("scripts/ci/example.py", 5, 7, None, None)]
    assert leftover == [
        ("scripts/ci/example.py", 12, "cannot-provide", cannot_excerpt),
        ("scripts/ci/removed.py", 11, "LEFT", left_excerpt),
        ("scripts/ci/example.py", 8, "cannot-provide", na_excerpt),
    ]
    assert left_excerpt == "    new"
    assert na_excerpt == "n/a"
    assert cannot_excerpt
    assert leftover_keys.isdisjoint(applyable_starts)
    assert leftover_diff_fence_reason(
        {"side": "RIGHT", "body": CANNOT_PROVIDE_DIFF_BODY}
    ) == "cannot-provide"
    assert leftover_diff_fence_reason(
        {"side": "LEFT", "body": SUGGESTED_DIFF_BODY}
    ) == "LEFT"
    assert leftover_diff_fence_reason(
        {"side": "RIGHT", "body": "already\n```suggestion\nnew\n```\n"}
    ) is None
    assert leftover_diff_fence_reason({"side": "RIGHT", "body": "no fence"}) is None
    assert leftover_diff_fence_receipts({"comments": "bad"}) == []
    assert leftover_diff_fence_receipts(
        {
            "comments": [
                {
                    "path": "../escape.py",
                    "line": 1,
                    "side": "LEFT",
                    "body": SUGGESTED_DIFF_BODY,
                },
                {
                    "path": "scripts/ci/example.py",
                    "line": 12,
                    "side": "RIGHT",
                    "body": CANNOT_PROVIDE_DIFF_BODY,
                },
                {
                    "path": "scripts/ci/example.py",
                    "line": 12,
                    "side": "RIGHT",
                    "body": CANNOT_PROVIDE_DIFF_BODY,
                },
                "not-an-object",
            ]
        }
    ) == [("scripts/ci/example.py", 12, "cannot-provide", cannot_excerpt)]
    parsed = parse_leftover_diff_receipts(
        "scripts/ci/example.py:12\tcannot-provide\n"
        "scripts/ci/removed.py:11\tLEFT\t    new\n"
        "scripts/ci/example.py:9\tunknown\n"
    )
    assert parsed == [
        ("scripts/ci/example.py", 12, "cannot-provide", ""),
        ("scripts/ci/removed.py", 11, "LEFT", "    new"),
    ]
    assert LEFTOVER_DIFF_REASONS == {"LEFT", "cannot-provide"}
    assert render_leftover_diff_receipts(parsed) == [
        "- `scripts/ci/example.py:12` — cannot-provide",
        "- `scripts/ci/removed.py:11` — LEFT",
        f"  {MANUAL_EDIT_HEADING}",
        "  ```diff",
        "      new",
        "  ```",
    ]


def test_overview_lists_applyable_and_leftover_under_distinct_headings(tmp_path):
    body = render_inline_comment_failure_body(
        "## Findings\n",
        control(
            {"path": "scripts/ci/example.py", "line": 5},
            {"path": "scripts/ci/example.py", "line": 12},
            {"path": "scripts/ci/removed.py", "line": 11},
            {"path": "scripts/ci/foreign.py", "line": 1},
        ),
        applyable_locations=[("scripts/ci/example.py", 5, 7)],
        leftover_locations=[
            (
                "scripts/ci/example.py",
                12,
                "cannot-provide",
                leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY),
            ),
            ("scripts/ci/removed.py", 11, "LEFT", leftover_manual_edit_text(SUGGESTED_DIFF_BODY)),
            ("scripts/ci/foreign.py", 1, "cannot-provide", "ignored"),
        ],
    )
    applyable_heading = "GitHub can apply these suggested replacements:"
    leftover_heading = (
        "These comments still have a suggested-diff fence that GitHub cannot apply:"
    )
    assert applyable_heading in body
    assert leftover_heading in body
    applyable_section = body.split(applyable_heading, 1)[1].split(leftover_heading, 1)[0]
    leftover_section = body.split(leftover_heading, 1)[1]
    assert "- `scripts/ci/example.py:5-7`" in applyable_section
    assert "cannot-provide" not in applyable_section
    assert "LEFT" not in applyable_section
    assert leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY) not in applyable_section
    assert MANUAL_EDIT_HEADING not in applyable_section
    assert "```diff" not in applyable_section
    assert "- `scripts/ci/example.py:12` — cannot-provide" in leftover_section
    assert "- `scripts/ci/removed.py:11` — LEFT" in leftover_section
    assert MANUAL_EDIT_HEADING in leftover_section
    assert "```diff" in leftover_section
    assert "```suggestion" not in leftover_section
    assert leftover_manual_edit_text(SUGGESTED_DIFF_BODY) in leftover_section
    assert leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY) in leftover_section
    assert "scripts/ci/example.py:5-7" not in leftover_section
    leftover_only = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/example.py", "line": 12}),
        leftover_locations=[
            (
                "scripts/ci/example.py",
                12,
                "cannot-provide",
                leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY),
            )
        ],
    )
    assert leftover_heading in leftover_only
    assert applyable_heading not in leftover_only
    empty_leftover = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/ok.py", "line": 4}),
        leftover_locations=[],
    )
    assert leftover_heading not in empty_leftover

    payload = tmp_path / "batch.json"
    payload.write_text(
        json.dumps(
            _batch_payload(
                {
                    "path": "scripts/ci/example.py",
                    "line": 5,
                    "side": "RIGHT",
                    "body": MULTILINE_DIFF_BODY,
                },
                {
                    "path": "scripts/ci/example.py",
                    "line": 12,
                    "side": "RIGHT",
                    "body": CANNOT_PROVIDE_DIFF_BODY,
                },
                {
                    "path": "scripts/ci/removed.py",
                    "line": 11,
                    "side": "LEFT",
                    "body": SUGGESTED_DIFF_BODY,
                },
            )
        ),
        encoding="utf-8",
    )
    hunks_diff = tmp_path / "hunks.diff"
    hunks_diff.write_text(EXAMPLE_UNIFIED_DIFF, encoding="utf-8")
    output = tmp_path / "filtered.json"
    applyable = tmp_path / "applyable.txt"
    leftover = tmp_path / "leftover.txt"
    assert (
        main(
            [
                "--filter-hunks",
                "--payload",
                str(payload),
                "--hunks-diff",
                str(hunks_diff),
                "--output",
                str(output),
                "--applyable-locations",
                str(applyable),
                "--leftover-diff-locations",
                str(leftover),
            ]
        )
        == 0
    )
    assert applyable.read_text(encoding="utf-8") == "scripts/ci/example.py:5-7\n"
    leftover_text = leftover.read_text(encoding="utf-8")
    assert (
        "scripts/ci/example.py:12\tcannot-provide\t"
        + encode_manual_edit_field(leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY))
        + "\n"
    ) in leftover_text
    assert (
        "scripts/ci/removed.py:11\tLEFT\t"
        + encode_manual_edit_field(leftover_manual_edit_text(SUGGESTED_DIFF_BODY))
        + "\n"
    ) in leftover_text
    assert "scripts/ci/example.py:5-7" not in leftover_text
    control_path = tmp_path / "control.json"
    body_path = tmp_path / "body.md"
    receipt = tmp_path / "receipt.md"
    control_path.write_text(
        json.dumps(
            control(
                {"path": "scripts/ci/example.py", "line": 5},
                {"path": "scripts/ci/example.py", "line": 12},
                {"path": "scripts/ci/removed.py", "line": 11},
            )
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
                str(receipt),
                "--applyable-locations",
                str(applyable),
                "--leftover-diff-locations",
                str(leftover),
            ]
        )
        == 0
    )
    rendered = receipt.read_text(encoding="utf-8")
    assert applyable_heading in rendered
    assert leftover_heading in rendered
    assert "- `scripts/ci/example.py:5-7`" in rendered
    assert "- `scripts/ci/example.py:12` — cannot-provide" in rendered
    assert "- `scripts/ci/removed.py:11` — LEFT" in rendered
    assert MANUAL_EDIT_HEADING in rendered
    assert "```suggestion" not in rendered.split(leftover_heading, 1)[1]
    applyable_rendered = rendered.split(applyable_heading, 1)[1].split(leftover_heading, 1)[0]
    assert leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY) not in applyable_rendered
    assert leftover_manual_edit_text(SUGGESTED_DIFF_BODY) in rendered.split(leftover_heading, 1)[1]
    assert (
        main(
            [
                "--control",
                str(control_path),
                "--body",
                str(body_path),
                "--output",
                str(receipt),
                "--leftover-diff-locations",
                str(tmp_path / "missing-leftover.txt"),
            ]
        )
        == 2
    )


CANNOT_PROVIDE_DIFF_BODY = """\
### HIGH no replacement

- Location: `scripts/ci/blocked.py:4`

#### Suggested diff
```diff
Cannot provide diff - inaccessible
```
"""


def test_leftover_diff_fences_are_not_applyable_suggestions():
    left_comment = {
        "path": "scripts/ci/removed.py",
        "line": 11,
        "side": "LEFT",
        "body": SUGGESTED_DIFF_BODY,
    }
    cannot_comment = {
        "path": "scripts/ci/blocked.py",
        "line": 4,
        "side": "RIGHT",
        "body": CANNOT_PROVIDE_DIFF_BODY,
    }
    applyable_comment = {
        "path": "scripts/ci/example.py",
        "line": 7,
        "side": "RIGHT",
        "body": SUGGESTED_DIFF_BODY,
    }
    assert leftover_diff_fence_reason(left_comment) == "LEFT"
    assert leftover_diff_fence_reason(cannot_comment) == "cannot-provide"
    assert leftover_diff_fence_reason({"body": "no fence"}) is None
    assert leftover_diff_fence_reason({"body": 12, "side": "LEFT"}) is None
    assert leftover_diff_fence_reason({"body": "```suggestion\nx\n```"}) is None
    assert leftover_diff_fence_reason(
        {"body": "```diff\nn/a\n```\n\n```suggestion\nkept\n```\n"}
    ) is None
    converted = apply_github_suggestion_blocks(
        _batch_payload(applyable_comment, left_comment, cannot_comment)
    )
    assert leftover_diff_fence_reason(converted["comments"][0]) is None
    assert leftover_diff_fence_receipts({"comments": "bad"}) == []
    assert leftover_diff_fence_receipts(
        _batch_payload(
            converted["comments"][0],
            left_comment,
            cannot_comment,
            {
                "path": "scripts/ci/removed.py",
                "line": 11,
                "side": "LEFT",
                "body": SUGGESTED_DIFF_BODY,
            },
            {
                "path": "../escape.py",
                "line": 1,
                "side": "LEFT",
                "body": SUGGESTED_DIFF_BODY,
            },
            {
                "path": "scripts/ci/blocked.py",
                "line": True,
                "side": "RIGHT",
                "body": CANNOT_PROVIDE_DIFF_BODY,
            },
            "not-an-object",
        )
    ) == [
        ("scripts/ci/removed.py", 11, "LEFT", leftover_manual_edit_text(SUGGESTED_DIFF_BODY)),
        (
            "scripts/ci/blocked.py",
            4,
            "cannot-provide",
            leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY),
        ),
    ]
    parsed = parse_leftover_diff_receipts(
        "\n".join(
            [
                "scripts/ci/removed.py:11\tLEFT\t    new",
                "scripts/ci/blocked.py:4\tcannot-provide\tCannot provide diff - inaccessible",
                "scripts/ci/removed.py:11\tLEFT",
                "scripts/ci/example.py:7\tHTTP 422",
                "scripts/ci/ok.py:4",
                "../escape.py:1\tLEFT",
                "# comment",
                "",
            ]
        )
    )
    assert parsed == [
        ("scripts/ci/removed.py", 11, "LEFT", "    new"),
        (
            "scripts/ci/blocked.py",
            4,
            "cannot-provide",
            "Cannot provide diff - inaccessible",
        ),
    ]
    assert render_leftover_diff_receipts(parsed) == [
        "- `scripts/ci/removed.py:11` — LEFT",
        f"  {MANUAL_EDIT_HEADING}",
        "  ```diff",
        "      new",
        "  ```",
        "- `scripts/ci/blocked.py:4` — cannot-provide",
        f"  {MANUAL_EDIT_HEADING}",
        "  ```diff",
        "  Cannot provide diff - inaccessible",
        "  ```",
    ]


def test_overview_receipts_distinguish_applyable_from_leftover_diff_fences(tmp_path):
    body = render_inline_comment_failure_body(
        "## Findings\n",
        control(
            {"path": "scripts/ci/example.py", "line": 5},
            {"path": "scripts/ci/removed.py", "line": 11},
            {"path": "scripts/ci/blocked.py", "line": 4},
        ),
        applyable_locations=[("scripts/ci/example.py", 5, 7)],
        leftover_locations=[
            ("scripts/ci/removed.py", 11, "LEFT", leftover_manual_edit_text(SUGGESTED_DIFF_BODY)),
            (
                "scripts/ci/blocked.py",
                4,
                "cannot-provide",
                leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY),
            ),
            ("scripts/ci/foreign.py", 1, "LEFT", "ignored"),
            ("scripts/ci/blocked.py", 4, "LEFT", "duplicate"),
            ("scripts/ci/example.py", 5, "HTTP 422", "not leftover"),
        ],
    )
    assert "GitHub can apply these suggested replacements:" in body
    assert "- `scripts/ci/example.py:5-7`" in body
    assert "These comments still have a suggested-diff fence that GitHub cannot apply:" in body
    assert "- `scripts/ci/removed.py:11` — LEFT" in body
    assert "- `scripts/ci/blocked.py:4` — cannot-provide" in body
    leftover_body = body.split(
        "These comments still have a suggested-diff fence that GitHub cannot apply:", 1
    )[1]
    applyable_body = body.split("GitHub can apply these suggested replacements:", 1)[1].split(
        "These comments still have a suggested-diff fence that GitHub cannot apply:", 1
    )[0]
    assert MANUAL_EDIT_HEADING in leftover_body
    assert "```suggestion" not in leftover_body
    assert leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY) in leftover_body
    assert leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY) not in applyable_body
    assert leftover_manual_edit_text(SUGGESTED_DIFF_BODY) not in applyable_body
    assert body.index("GitHub can apply these suggested replacements:") < body.index(
        "These comments still have a suggested-diff fence that GitHub cannot apply:"
    )
    assert "scripts/ci/foreign.py" not in body
    leftover_only = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/removed.py", "line": 11}),
        leftover_locations=[
            ("scripts/ci/removed.py", 11, "LEFT", leftover_manual_edit_text(SUGGESTED_DIFF_BODY))
        ],
    )
    assert "These comments still have a suggested-diff fence that GitHub cannot apply:" in leftover_only
    assert "- `scripts/ci/removed.py:11` — LEFT" in leftover_only
    assert "GitHub can apply these suggested replacements:" not in leftover_only
    assert "did not accept the inline review comments" not in leftover_only
    empty_leftover = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/ok.py", "line": 4}),
        leftover_locations=[],
    )
    assert (
        "These comments still have a suggested-diff fence that GitHub cannot apply:"
        not in empty_leftover
    )
    refused_with_leftover = render_inline_comment_failure_body(
        "## Findings\n",
        control(
            {"path": "scripts/ci/example.py", "line": 7},
            {"path": "scripts/ci/blocked.py", "line": 4},
        ),
        refused_receipts=[],
        leftover_locations=[
            (
                "scripts/ci/blocked.py",
                4,
                "cannot-provide",
                leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY),
            )
        ],
    )
    assert "- `scripts/ci/blocked.py:4` — cannot-provide" in refused_with_leftover
    refused_locations_with_leftover = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/removed.py", "line": 11}),
        refused_locations=[],
        leftover_locations=[
            ("scripts/ci/removed.py", 11, "LEFT", leftover_manual_edit_text(SUGGESTED_DIFF_BODY))
        ],
    )
    assert "- `scripts/ci/removed.py:11` — LEFT" in refused_locations_with_leftover
    empty_trusted_leftover = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/ok.py", "line": 4}),
        leftover_locations=[("scripts/ci/removed.py", 11, "LEFT")],
    )
    assert (
        "These comments still have a suggested-diff fence that GitHub cannot apply:"
        not in empty_trusted_leftover
    )

    payload = tmp_path / "batch.json"
    payload.write_text(
        json.dumps(
            _batch_payload(
                {
                    "path": "scripts/ci/example.py",
                    "line": 7,
                    "side": "RIGHT",
                    "body": SUGGESTED_DIFF_BODY,
                },
                {
                    "path": "scripts/ci/removed.py",
                    "line": 11,
                    "side": "LEFT",
                    "body": SUGGESTED_DIFF_BODY,
                },
                {
                    "path": "scripts/ci/blocked.py",
                    "line": 4,
                    "side": "RIGHT",
                    "body": CANNOT_PROVIDE_DIFF_BODY,
                },
            )
        ),
        encoding="utf-8",
    )
    hunks_diff = tmp_path / "hunks.diff"
    hunks_diff.write_text(
        EXAMPLE_UNIFIED_DIFF
        + "diff --git a/scripts/ci/blocked.py b/scripts/ci/blocked.py\n"
        + "--- a/scripts/ci/blocked.py\n+++ b/scripts/ci/blocked.py\n"
        + "@@ -4,1 +4,1 @@\n-    old\n+    new\n",
        encoding="utf-8",
    )
    output = tmp_path / "filtered.json"
    leftover = tmp_path / "leftover.txt"
    applyable = tmp_path / "applyable.txt"
    assert (
        main(
            [
                "--filter-hunks",
                "--payload",
                str(payload),
                "--hunks-diff",
                str(hunks_diff),
                "--output",
                str(output),
                "--applyable-locations",
                str(applyable),
                "--leftover-diff-locations",
                str(leftover),
            ]
        )
        == 0
    )
    assert applyable.read_text(encoding="utf-8") == "scripts/ci/example.py:7\n"
    assert leftover.read_text(encoding="utf-8") == (
        "scripts/ci/removed.py:11\tLEFT\t"
        + encode_manual_edit_field(leftover_manual_edit_text(SUGGESTED_DIFF_BODY))
        + "\n"
        + "scripts/ci/blocked.py:4\tcannot-provide\t"
        + encode_manual_edit_field(leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY))
        + "\n"
    )
    control_path = tmp_path / "control.json"
    body_path = tmp_path / "body.md"
    receipt = tmp_path / "receipt.md"
    control_path.write_text(
        json.dumps(
            control(
                {"path": "scripts/ci/example.py", "line": 7},
                {"path": "scripts/ci/removed.py", "line": 11},
                {"path": "scripts/ci/blocked.py", "line": 4},
            )
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
                str(receipt),
                "--applyable-locations",
                str(applyable),
                "--leftover-diff-locations",
                str(leftover),
            ]
        )
        == 0
    )
    receipt_text = receipt.read_text(encoding="utf-8")
    assert "scripts/ci/example.py:7" in receipt_text
    assert "scripts/ci/removed.py:11` — LEFT" in receipt_text
    assert "scripts/ci/blocked.py:4` — cannot-provide" in receipt_text
    leftover_receipt = receipt_text.split(
        "These comments still have a suggested-diff fence that GitHub cannot apply:", 1
    )[1]
    applyable_receipt = receipt_text.split(
        "GitHub can apply these suggested replacements:", 1
    )[1].split(
        "These comments still have a suggested-diff fence that GitHub cannot apply:", 1
    )[0]
    assert MANUAL_EDIT_HEADING in leftover_receipt
    assert "```suggestion" not in leftover_receipt
    assert leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY) in leftover_receipt
    assert leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY) not in applyable_receipt
    assert (
        main(
            [
                "--control",
                str(control_path),
                "--body",
                str(body_path),
                "--output",
                str(receipt),
                "--leftover-diff-locations",
                str(tmp_path / "missing-leftover.txt"),
            ]
        )
        == 2
    )


def test_leftover_manual_edit_excerpt_is_distinct_non_applyable_block(tmp_path):
    assert leftover_manual_edit_text(12) == ""
    assert leftover_manual_edit_text("no suggested-diff fence") == ""
    assert leftover_manual_edit_text("```diff\n\n```") == ""
    assert leftover_manual_edit_text(SUGGESTED_DIFF_BODY) == "    new"
    assert leftover_manual_edit_text(NA_DIFF_BODY) == "n/a"
    assert leftover_manual_edit_text(CANNOT_PROVIDE_DIFF_BODY).startswith(
        "Cannot provide"
    )
    assert leftover_manual_edit_text(
        "#### Suggested diff\n```diff\n\n```\n\n#### Suggested diff\n```diff\n+fixed\n```\n"
    ) == "fixed"
    assert leftover_manual_edit_text("```diff\n+has ``` fence\n```") == "has "
    long_text = "x" * (MANUAL_EDIT_MAX_CHARS + 25)
    bounded = leftover_manual_edit_text(f"```diff\n{long_text}\n```")
    assert bounded.endswith("…")
    assert len(bounded) == MANUAL_EDIT_MAX_CHARS + 1
    encoded = encode_manual_edit_field("keep\tthis\nline```end")
    assert "\t" not in encoded
    assert "```" not in encoded
    assert encoded == "keep this\\nlineend"
    assert decode_manual_edit_field(encoded) == "keep this\nlineend"
    assert encode_manual_edit_field(long_text).endswith("…")
    assert decode_manual_edit_field("") == ""
    assert leftover_manual_edit_text(
        "```diff\n<!-- opencode --><script>alert(1)</script>-->\n```"
    ) == " opencode scriptalert(1)/script"
    assert "-->" not in leftover_manual_edit_text("```diff\nclose --> comment\n```")
    assert sanitize_leftover_excerpt("a & b <c>") == "a  b c"
    assert encode_manual_edit_field("<!-- --> & <x>") == "   x"
    assert render_leftover_diff_receipts([("scripts/ci/a.py", 1, "LEFT")]) == [
        "- `scripts/ci/a.py:1` — LEFT"
    ]
    assert render_leftover_diff_receipts(
        [("scripts/ci/a.py", 1, "LEFT", 12)]  # type: ignore[list-item]
    ) == ["- `scripts/ci/a.py:1` — LEFT"]
    rendered = render_leftover_diff_receipts(
        [("scripts/ci/a.py", 1, "cannot-provide", "n/a")]
    )
    assert rendered == [
        "- `scripts/ci/a.py:1` — cannot-provide",
        f"  {MANUAL_EDIT_HEADING}",
        "  ```diff",
        "  n/a",
        "  ```",
    ]
    assert "```suggestion" not in "\n".join(rendered)
    parsed = parse_leftover_diff_receipts(
        "scripts/ci/a.py:1\tcannot-provide\tn/a\\nmore\n"
        "scripts/ci/b.py:2\tLEFT\n"
        "scripts/ci/c.py:x\tLEFT\n"
        "scripts/ci/d.py:3\n"
    )
    assert parsed == [
        ("scripts/ci/a.py", 1, "cannot-provide", "n/a\nmore"),
        ("scripts/ci/b.py", 2, "LEFT", ""),
    ]

    empty_fence_body = "#### Suggested diff\n```diff\n```\n"
    payload = _batch_payload(
        {
            "path": "scripts/ci/empty.py",
            "line": 4,
            "side": "RIGHT",
            "body": empty_fence_body,
        }
    )
    leftover_path = tmp_path / "leftover.txt"
    write_hunk_filtered_payload(
        payload,
        parse_unified_diff_hunk_lines(
            "diff --git a/scripts/ci/empty.py b/scripts/ci/empty.py\n"
            "--- a/scripts/ci/empty.py\n+++ b/scripts/ci/empty.py\n"
            "@@ -4,1 +4,1 @@\n-    old\n+    new\n"
        ),
        tmp_path / "filtered.json",
        leftover_path=leftover_path,
    )
    assert leftover_path.read_text(encoding="utf-8") == (
        "scripts/ci/empty.py:4\tcannot-provide\n"
    )
    assert leftover_diff_fence_receipts(payload) == [
        ("scripts/ci/empty.py", 4, "cannot-provide", "")
    ]


REWRITE_UNIFIED_DIFF = """\
diff --git a/scripts/ci/rewrite.py b/scripts/ci/rewrite.py
--- a/scripts/ci/rewrite.py
+++ b/scripts/ci/rewrite.py
@@ -10,3 +20,3 @@
-old
-old
-old
+new
+new
+new
"""


MULTI_HUNK_UNIFIED_DIFF = """\
diff --git a/scripts/ci/multi.py b/scripts/ci/multi.py
--- a/scripts/ci/multi.py
+++ b/scripts/ci/multi.py
@@ -5,3 +5,3 @@
 keep
-old
+new
 keep
@@ -40,3 +50,3 @@
 keep
-old
+new
 keep
"""


def test_right_hunk_anchor_prefers_same_line_then_first_right_line():
    hunks = parse_unified_diff_hunk_lines(EXAMPLE_UNIFIED_DIFF + REWRITE_UNIFIED_DIFF)
    assert right_hunk_anchor_line("scripts/ci/example.py", 7, hunks) == 7
    assert right_hunk_anchor_line("scripts/ci/rewrite.py", 11, hunks) == 20
    assert right_hunk_anchor_line("scripts/ci/removed.py", 11, hunks) is None
    assert right_hunk_anchor_line("scripts/ci/example.py", 7, None) is None
    assert right_hunk_anchor_line("scripts/ci/example.py", 7, {}) is None
    assert right_hunk_anchor_line("../escape.py", 7, hunks) is None
    assert right_hunk_anchor_line("scripts/ci/example.py", 0, hunks) is None


def test_right_hunk_anchor_uses_same_at_hunk_not_path_min():
    hunks = parse_unified_diff_hunk_lines(MULTI_HUNK_UNIFIED_DIFF)
    assert hunks["scripts/ci/multi.py"]["LEFT"] == {5, 6, 7, 40, 41, 42}
    assert hunks["scripts/ci/multi.py"]["RIGHT"] == {5, 6, 7, 50, 51, 52}
    assert right_hunk_anchor_line("scripts/ci/multi.py", 6, hunks) == 6
    assert right_hunk_anchor_line("scripts/ci/multi.py", 41, hunks) == 50
    assert right_hunk_anchor_line("scripts/ci/multi.py", 41, hunks) != min(
        hunks["scripts/ci/multi.py"]["RIGHT"]
    )
    delete_then_edit = parse_unified_diff_hunk_lines(
        "diff --git a/scripts/ci/mixed.py b/scripts/ci/mixed.py\n"
        "--- a/scripts/ci/mixed.py\n+++ b/scripts/ci/mixed.py\n"
        "@@ -10,3 +0,0 @@\n-gone\n-gone\n-gone\n"
        "@@ -40,3 +50,3 @@\n keep\n-old\n+new\n keep\n"
    )
    assert right_hunk_anchor_line("scripts/ci/mixed.py", 11, delete_then_edit) is None
    assert right_hunk_anchor_line("scripts/ci/mixed.py", 41, delete_then_edit) == 50
    assert right_hunk_anchor_line(
        "scripts/ci/x.py", 2, {"scripts/ci/x.py": "bad"}
    ) is None
    assert right_hunk_anchor_line(
        "scripts/ci/x.py", 2, {"scripts/ci/x.py": {"RIGHT": {2, 3}, "SPANS": "bad"}}
    ) == 2
    assert right_hunk_anchor_line(
        "scripts/ci/x.py", 11, {"scripts/ci/x.py": {"RIGHT": {20}, "SPANS": "bad"}}
    ) is None
    assert right_hunk_anchor_line(
        "scripts/ci/x.py",
        11,
        {
            "scripts/ci/x.py": {
                "RIGHT": {20},
                "SPANS": [
                    None,
                    (1,),
                    ("n", {20}),
                    ({11}, "n"),
                    ({11}, set()),
                    ({11}, {20}),
                ],
            }
        },
    ) == 20
    assert right_hunk_anchor_line(
        "scripts/ci/x.py", 11, {"scripts/ci/x.py": {"RIGHT": "bad"}}
    ) is None


def test_remap_left_comment_onto_same_path_right_hunk():
    hunks = parse_unified_diff_hunk_lines(EXAMPLE_UNIFIED_DIFF + REWRITE_UNIFIED_DIFF)
    left_applyable = {
        "path": "scripts/ci/example.py",
        "line": 7,
        "side": "LEFT",
        "body": SUGGESTED_DIFF_BODY,
    }
    remapped = remap_left_comment_to_right_hunk(left_applyable, hunks)
    assert remapped["side"] == "RIGHT"
    assert remapped["line"] == 7
    assert remapped["body"] == SUGGESTED_DIFF_BODY
    rewrite = remap_left_comment_to_right_hunk(
        {
            "path": "scripts/ci/rewrite.py",
            "line": 11,
            "side": "LEFT",
            "start_line": 10,
            "start_side": "LEFT",
            "body": SUGGESTED_DIFF_BODY,
        },
        hunks,
    )
    assert rewrite["side"] == "RIGHT"
    assert rewrite["line"] == 20
    assert "start_line" not in rewrite
    assert "start_side" not in rewrite
    unchanged_right = {
        "path": "scripts/ci/example.py",
        "line": 7,
        "side": "RIGHT",
        "body": SUGGESTED_DIFF_BODY,
    }
    assert remap_left_comment_to_right_hunk(unchanged_right, hunks) is unchanged_right
    deleted_only = {
        "path": "scripts/ci/removed.py",
        "line": 11,
        "side": "LEFT",
        "body": SUGGESTED_DIFF_BODY,
    }
    assert remap_left_comment_to_right_hunk(deleted_only, hunks) is deleted_only
    cannot = {
        "path": "scripts/ci/example.py",
        "line": 8,
        "side": "LEFT",
        "body": CANNOT_PROVIDE_DIFF_BODY,
    }
    assert remap_left_comment_to_right_hunk(cannot, hunks) is cannot
    assert remap_left_comment_to_right_hunk(
        {"path": "scripts/ci/example.py", "line": 7, "side": "LEFT", "body": "no fence"},
        hunks,
    )["side"] == "LEFT"
    already = {
        "path": "scripts/ci/example.py",
        "line": 7,
        "side": "LEFT",
        "body": "```diff\n+x\n```\n```suggestion\nx\n```",
    }
    assert remap_left_comment_to_right_hunk(already, hunks) is already
    assert remap_left_comment_to_right_hunk(
        {
            "path": "../escape.py",
            "line": 7,
            "side": "LEFT",
            "body": SUGGESTED_DIFF_BODY,
        },
        hunks,
    )["side"] == "LEFT"
    assert remap_left_comment_to_right_hunk(left_applyable, None) is left_applyable


def test_left_leftover_becomes_applyable_on_same_path_right_hunk(tmp_path):
    hunks = parse_unified_diff_hunk_lines(EXAMPLE_UNIFIED_DIFF + REWRITE_UNIFIED_DIFF)
    payload = apply_github_suggestion_blocks(
        _batch_payload(
            {
                "path": "scripts/ci/example.py",
                "line": 7,
                "side": "LEFT",
                "body": SUGGESTED_DIFF_BODY,
            },
            {
                "path": "scripts/ci/rewrite.py",
                "line": 11,
                "side": "LEFT",
                "body": SUGGESTED_DIFF_BODY,
            },
            {
                "path": "scripts/ci/removed.py",
                "line": 11,
                "side": "LEFT",
                "body": SUGGESTED_DIFF_BODY,
            },
            {
                "path": "scripts/ci/example.py",
                "line": 8,
                "side": "LEFT",
                "body": CANNOT_PROVIDE_DIFF_BODY,
            },
        ),
        hunks,
    )
    comments = payload["comments"]
    assert comments[0]["side"] == "RIGHT"
    assert comments[0]["line"] == 7
    assert "```suggestion\n    new\n```" in comments[0]["body"]
    assert comments[1]["side"] == "RIGHT"
    assert comments[1]["line"] == 20
    assert "```suggestion\n    new\n```" in comments[1]["body"]
    assert comments[2]["side"] == "LEFT"
    assert "```suggestion" not in comments[2]["body"]
    assert comments[3]["side"] == "LEFT"
    assert leftover_diff_fence_reason(comments[3]) == "LEFT"
    applyable = applyable_suggestion_ranges(payload)
    leftover = leftover_diff_fence_receipts(payload)
    leftover_keys = {(path, line) for path, line, _reason, _excerpt in leftover}
    applyable_starts = {(path, start) for path, start, _end, *_rest in applyable}
    assert ("scripts/ci/example.py", 7) in applyable_starts
    assert ("scripts/ci/rewrite.py", 20) in applyable_starts
    assert leftover_keys.isdisjoint(applyable_starts)
    assert ("scripts/ci/removed.py", 11) in leftover_keys
    assert ("scripts/ci/example.py", 8) in leftover_keys
    assert leftover_diff_fence_reason(comments[0]) is None
    assert leftover_diff_fence_reason(comments[1]) is None

    body = render_inline_comment_failure_body(
        "## Findings\n",
        control(
            {"path": "scripts/ci/example.py", "line": 7},
            {"path": "scripts/ci/rewrite.py", "line": 11},
            {"path": "scripts/ci/removed.py", "line": 11},
            {"path": "scripts/ci/example.py", "line": 8},
        ),
        applyable_locations=applyable,
        leftover_locations=leftover,
    )
    applyable_heading = "GitHub can apply these suggested replacements:"
    leftover_heading = (
        "These comments still have a suggested-diff fence that GitHub cannot apply:"
    )
    applyable_section = body.split(applyable_heading, 1)[1].split(leftover_heading, 1)[0]
    leftover_section = body.split(leftover_heading, 1)[1]
    assert "- `scripts/ci/example.py:7`" in applyable_section
    assert "- `scripts/ci/rewrite.py:20`" in applyable_section
    assert "from LEFT `scripts/ci/example.py:7`" in applyable_section
    assert "from LEFT `scripts/ci/rewrite.py:11`" in applyable_section
    assert "scripts/ci/removed.py" not in applyable_section
    assert "cannot-provide" not in applyable_section
    assert MANUAL_EDIT_HEADING not in applyable_section
    assert "- `scripts/ci/removed.py:11` — LEFT" in leftover_section
    assert "- `scripts/ci/example.py:8` — LEFT" in leftover_section
    assert MANUAL_EDIT_HEADING in leftover_section
    assert "```suggestion" not in leftover_section
    assert "scripts/ci/rewrite.py:20" not in leftover_section

    payload_path = tmp_path / "batch.json"
    payload_path.write_text(
        json.dumps(
            _batch_payload(
                {
                    "path": "scripts/ci/example.py",
                    "line": 7,
                    "side": "LEFT",
                    "body": SUGGESTED_DIFF_BODY,
                },
                {
                    "path": "scripts/ci/rewrite.py",
                    "line": 11,
                    "side": "LEFT",
                    "body": SUGGESTED_DIFF_BODY,
                },
                {
                    "path": "scripts/ci/removed.py",
                    "line": 11,
                    "side": "LEFT",
                    "body": SUGGESTED_DIFF_BODY,
                },
                {
                    "path": "scripts/ci/example.py",
                    "line": 8,
                    "side": "LEFT",
                    "body": CANNOT_PROVIDE_DIFF_BODY,
                },
            )
        ),
        encoding="utf-8",
    )
    hunks_diff = tmp_path / "hunks.diff"
    hunks_diff.write_text(EXAMPLE_UNIFIED_DIFF + REWRITE_UNIFIED_DIFF, encoding="utf-8")
    output = tmp_path / "filtered.json"
    applyable_file = tmp_path / "applyable.txt"
    leftover_file = tmp_path / "leftover.txt"
    assert (
        main(
            [
                "--filter-hunks",
                "--payload",
                str(payload_path),
                "--hunks-diff",
                str(hunks_diff),
                "--output",
                str(output),
                "--applyable-locations",
                str(applyable_file),
                "--leftover-diff-locations",
                str(leftover_file),
            ]
        )
        == 0
    )
    applyable_text = applyable_file.read_text(encoding="utf-8")
    leftover_text = leftover_file.read_text(encoding="utf-8")
    assert "scripts/ci/example.py:7\tLEFT scripts/ci/example.py:7\n" in applyable_text
    assert "scripts/ci/rewrite.py:20\tLEFT scripts/ci/rewrite.py:11\n" in applyable_text
    assert "scripts/ci/removed.py" not in applyable_text
    assert "scripts/ci/removed.py:11\tLEFT\t" in leftover_text
    assert "scripts/ci/example.py:8\tLEFT\t" in leftover_text
    assert "scripts/ci/rewrite.py" not in leftover_text
    filtered = json.loads(output.read_text(encoding="utf-8"))
    sides = [(item["path"], item["side"], item["line"]) for item in filtered["comments"]]
    assert ("scripts/ci/example.py", "RIGHT", 7) in sides
    assert ("scripts/ci/rewrite.py", "RIGHT", 20) in sides
    assert ("scripts/ci/removed.py", "LEFT", 11) in sides


def test_multi_hunk_left_remap_attaches_to_same_at_hunk(tmp_path):
    hunks = parse_unified_diff_hunk_lines(MULTI_HUNK_UNIFIED_DIFF)
    remapped = remap_left_comment_to_right_hunk(
        {
            "path": "scripts/ci/multi.py",
            "line": 41,
            "side": "LEFT",
            "body": SUGGESTED_DIFF_BODY,
        },
        hunks,
    )
    assert remapped["side"] == "RIGHT"
    assert remapped["line"] == 50
    payload = apply_github_suggestion_blocks(
        _batch_payload(
            {
                "path": "scripts/ci/multi.py",
                "line": 41,
                "side": "LEFT",
                "body": SUGGESTED_DIFF_BODY,
            },
            {
                "path": "scripts/ci/multi.py",
                "line": 6,
                "side": "LEFT",
                "body": SUGGESTED_DIFF_BODY,
            },
        ),
        hunks,
    )
    comments = payload["comments"]
    assert comments[0]["line"] == 50
    assert comments[0]["side"] == "RIGHT"
    assert "```suggestion\n    new\n```" in comments[0]["body"]
    assert comments[1]["line"] == 6
    applyable = applyable_suggestion_ranges(payload)
    leftover = leftover_diff_fence_receipts(payload)
    assert applyable == [
        ("scripts/ci/multi.py", 50, 50, "scripts/ci/multi.py", 41),
        ("scripts/ci/multi.py", 6, 6, "scripts/ci/multi.py", 6),
    ]
    assert leftover == []
    body = render_inline_comment_failure_body(
        "## Findings\n",
        control(
            {"path": "scripts/ci/multi.py", "line": 41},
            {"path": "scripts/ci/multi.py", "line": 6},
        ),
        applyable_locations=applyable,
        leftover_locations=leftover,
    )
    assert "- `scripts/ci/multi.py:50` — from LEFT `scripts/ci/multi.py:41`" in body
    assert "- `scripts/ci/multi.py:6` — from LEFT `scripts/ci/multi.py:6`" in body
    assert "These comments still have a suggested-diff fence that GitHub cannot apply:" not in body
    assert "- `scripts/ci/multi.py:5`" not in body

    payload_path = tmp_path / "batch.json"
    payload_path.write_text(
        json.dumps(
            _batch_payload(
                {
                    "path": "scripts/ci/multi.py",
                    "line": 41,
                    "side": "LEFT",
                    "body": SUGGESTED_DIFF_BODY,
                }
            )
        ),
        encoding="utf-8",
    )
    hunks_diff = tmp_path / "hunks.diff"
    hunks_diff.write_text(MULTI_HUNK_UNIFIED_DIFF, encoding="utf-8")
    applyable_file = tmp_path / "applyable.txt"
    leftover_file = tmp_path / "leftover.txt"
    assert (
        main(
            [
                "--filter-hunks",
                "--payload",
                str(payload_path),
                "--hunks-diff",
                str(hunks_diff),
                "--output",
                str(tmp_path / "filtered.json"),
                "--applyable-locations",
                str(applyable_file),
                "--leftover-diff-locations",
                str(leftover_file),
            ]
        )
        == 0
    )
    assert applyable_file.read_text(encoding="utf-8") == (
        "scripts/ci/multi.py:50\tLEFT scripts/ci/multi.py:41\n"
    )
    assert leftover_file.read_text(encoding="utf-8") == ""
    posted = json.loads((tmp_path / "filtered.json").read_text(encoding="utf-8"))
    assert "_left_origin_path" not in posted["comments"][0]
    assert "_left_origin_line" not in posted["comments"][0]


def test_applyable_left_origin_parse_render_and_strip(tmp_path):
    assert format_applyable_origin(None, 11) == ""
    assert format_applyable_origin("scripts/ci/multi.py", None) == ""
    assert format_applyable_origin("scripts/ci/multi.py", 41) == (
        "LEFT scripts/ci/multi.py:41"
    )
    assert parse_applyable_origin_field("LEFT scripts/ci/multi.py:41") == (
        "scripts/ci/multi.py",
        41,
    )
    assert parse_applyable_origin_field("cannot-provide") == (None, None)
    assert parse_applyable_origin_field("LEFT no-colon") == (None, None)
    assert parse_applyable_origin_field("LEFT ../escape.py:1") == (None, None)
    assert parse_applyable_origin_field("LEFT scripts/ci/multi.py:x") == (None, None)
    parsed = parse_applyable_ranges(
        "\n".join(
            [
                "scripts/ci/multi.py:50\tLEFT scripts/ci/multi.py:41",
                "scripts/ci/ok.py:4",
                "scripts/ci/bad.py:5\tLEFT ../escape.py:1",
                "scripts/ci/also.py:6\tHTTP 422",
            ]
        )
    )
    assert parsed == [
        ("scripts/ci/multi.py", 50, 50, "scripts/ci/multi.py", 41),
        ("scripts/ci/ok.py", 4, 4, None, None),
        ("scripts/ci/bad.py", 5, 5, None, None),
        ("scripts/ci/also.py", 6, 6, None, None),
    ]
    assert render_applyable_receipts(parsed) == [
        "- `scripts/ci/multi.py:50` — from LEFT `scripts/ci/multi.py:41`",
        "- `scripts/ci/ok.py:4`",
        "- `scripts/ci/bad.py:5`",
        "- `scripts/ci/also.py:6`",
    ]
    assert render_applyable_receipts([("scripts/ci/ok.py", 4, 4)]) == [
        "- `scripts/ci/ok.py:4`"
    ]
    assert render_applyable_receipts(
        [("scripts/ci/ok.py", 4, 4, 12, "nope")]  # type: ignore[list-item]
    ) == ["- `scripts/ci/ok.py:4`"]
    remapped = remap_left_comment_to_right_hunk(
        {
            "path": "scripts/ci/rewrite.py",
            "line": 11,
            "side": "LEFT",
            "body": SUGGESTED_DIFF_BODY,
        },
        parse_unified_diff_hunk_lines(REWRITE_UNIFIED_DIFF),
    )
    assert remapped["_left_origin_path"] == "scripts/ci/rewrite.py"
    assert remapped["_left_origin_line"] == 11
    stripped = strip_left_origin_fields(_batch_payload(remapped, "not-an-object"))
    assert "_left_origin_path" not in stripped["comments"][0]
    assert "_left_origin_line" not in stripped["comments"][0]
    assert stripped["comments"][1] == "not-an-object"
    assert strip_left_origin_fields({"comments": "bad"})["comments"] == "bad"
    body = render_inline_comment_failure_body(
        "## Findings\n",
        control({"path": "scripts/ci/rewrite.py", "line": 11}),
        applyable_locations=[
            ("scripts/ci/rewrite.py", 20, 20, "scripts/ci/rewrite.py", 11)
        ],
    )
    assert (
        "- `scripts/ci/rewrite.py:20` — from LEFT `scripts/ci/rewrite.py:11`"
        in body
    )
    assert "GitHub can apply these suggested replacements:" in body
    assert applyable_suggestion_ranges(
        {
            "comments": [
                {
                    "path": "scripts/ci/example.py",
                    "line": 7,
                    "body": "```suggestion\nx\n```",
                    "_left_origin_path": "../escape.py",
                    "_left_origin_line": 11,
                }
            ]
        }
    ) == [("scripts/ci/example.py", 7, 7, None, None)]
    applyable_file = tmp_path / "applyable.txt"
    applyable_file.write_text(
        "scripts/ci/rewrite.py:20\tLEFT scripts/ci/rewrite.py:11\n",
        encoding="utf-8",
    )
    control_path = tmp_path / "control.json"
    body_path = tmp_path / "body.md"
    receipt = tmp_path / "receipt.md"
    control_path.write_text(
        json.dumps(control({"path": "scripts/ci/rewrite.py", "line": 11})),
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
                str(receipt),
                "--applyable-locations",
                str(applyable_file),
            ]
        )
        == 0
    )
    assert (
        "- `scripts/ci/rewrite.py:20` — from LEFT `scripts/ci/rewrite.py:11`"
        in receipt.read_text(encoding="utf-8")
    )

