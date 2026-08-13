import json
import runpy
import sys

import pytest

from scripts.ci.opencode_inline_comment_fallback import (
    DEFAULT_SINGLE_COMMENT_RETRY_LIMIT,
    apply_github_suggestion_blocks,
    applyable_suggestion_ranges,
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
        ("scripts/ci/example.py", 5, 7),
        ("scripts/ci/ok.py", 4, 4),
    ]
    assert render_applyable_receipts(parsed) == [
        "- `scripts/ci/example.py:5-7`",
        "- `scripts/ci/ok.py:4`",
    ]
    assert applyable_suggestion_ranges({"comments": "bad"}) == []
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
        ("scripts/ci/example.py", 5, 7),
        ("scripts/ci/example.py", 7, 7),
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
    assert swapped == [("scripts/ci/example.py", 5, 7)]
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
