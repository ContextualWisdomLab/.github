import json
import runpy
import sys

import pytest

from scripts.ci.opencode_inline_comment_fallback import (
    DEFAULT_SINGLE_COMMENT_RETRY_LIMIT,
    github_error_is_unprocessable,
    github_publication_error_phrase,
    iter_single_comment_payloads,
    main,
    render_inline_comment_failure_body,
    render_inline_comment_receipts,
    render_single_comment_review,
    single_comment_range_fields,
    single_comment_retry_limit,
    strip_leftover_diff_fences,
    trusted_finding_locations,
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
    assert (
        github_publication_error_phrase("status code 422 only")
        == "GitHub review write failed"
    )
    assert (
        github_publication_error_phrase("https://api.github.example/HTTP 422")
        == "GitHub HTTP 422: 422"
    )
    assert render_inline_comment_receipts([], "GitHub HTTP 422") == []
    assert (
        github_publication_error_phrase(
            '{"errors":[{"message":"path `<script>` & `diff`"}]}'
        )
        == (
            "GitHub HTTP 422: path "
            "\\u0060\\u003cscript\\u003e\\u0060 \\u0026 \\u0060diff\\u0060"
        )
    )
    assert render_inline_comment_receipts(
        [("scripts/ci/example.py", 7)],
        "GitHub HTTP 422: path <script> & `diff`",
    ) == [
        "- `scripts/ci/example.py:7` — GitHub HTTP 422: path "
        "\\u003cscript\\u003e \\u0026 \\u0060diff\\u0060"
    ]
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
    assert not github_error_is_unprocessable(
        "gh: HTTP 403 Forbidden sha=154a33d092422abc issue #422"
    )
    assert not github_error_is_unprocessable("status code 422 only")


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
    assert single_comment_range_fields(
        {"start_line": 5, "start_side": "RIGHT"}, 7, "RIGHT"
    ) == {"start_line": 5, "start_side": "RIGHT"}
    assert single_comment_range_fields({"start_line": 7}, 7, "RIGHT") == {}
    assert single_comment_range_fields({"start_line": 8, "start_side": "RIGHT"}, 7, "RIGHT") == {}
    assert single_comment_range_fields({"start_line": 0, "start_side": "RIGHT"}, 7, "RIGHT") == {}
    assert single_comment_range_fields(
        {"start_line": 5, "start_side": "NOPE"}, 7, "RIGHT"
    ) == {"start_line": 5, "start_side": "RIGHT"}
    ranged = {
        "event": "REQUEST_CHANGES",
        "body": "review body",
        "commit_id": "b" * 40,
        "comments": [
            {
                "path": "scripts/ci/example.py",
                "line": 7,
                "start_line": 5,
                "start_side": "RIGHT",
                "side": "RIGHT",
                "body": "```suggestion\n    first\n    second\n```\n",
            }
        ],
    }
    ranged_singles = iter_single_comment_payloads(ranged)
    assert ranged_singles[0]["start_line"] == 5
    assert ranged_singles[0]["start_side"] == "RIGHT"
    assert ranged_singles[0]["line"] == 7
    rendered_range = render_single_comment_review(
        ranged_singles[0], event="REQUEST_CHANGES", review_body="review body"
    )
    assert rendered_range["comments"][0]["start_line"] == 5
    assert rendered_range["comments"][0]["start_side"] == "RIGHT"
    assert rendered_range["comments"][0]["line"] == 7
    assert (
        strip_leftover_diff_fences(
            "keep prose\n```diff\n- leftover\n+ leftover\n```\n"
        )
        == "keep prose"
    )
    leftover_only = iter_single_comment_payloads(
        {
            "commit_id": "c" * 40,
            "comments": [
                {
                    "path": "scripts/ci/example.py",
                    "line": 7,
                    "body": "```diff\n- leftover\n+ leftover\n```\n",
                },
                {
                    "path": "scripts/ci/example.py",
                    "line": 8,
                    "body": "apply this\n```patch\n- leftover\n```\n",
                },
            ],
        }
    )
    assert [(item["path"], item["line"], item["body"]) for item in leftover_only] == [
        ("scripts/ci/example.py", 8, "apply this"),
    ]


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
    assert single_comment_retry_limit(None) == DEFAULT_SINGLE_COMMENT_RETRY_LIMIT
    assert single_comment_retry_limit(True) == DEFAULT_SINGLE_COMMENT_RETRY_LIMIT
    assert single_comment_retry_limit(0) == DEFAULT_SINGLE_COMMENT_RETRY_LIMIT
    assert single_comment_retry_limit(-1) == DEFAULT_SINGLE_COMMENT_RETRY_LIMIT
    assert single_comment_retry_limit(3) == 3
    assert single_comment_retry_limit("7") == 7
    assert single_comment_retry_limit("0") == DEFAULT_SINGLE_COMMENT_RETRY_LIMIT
    assert single_comment_retry_limit("nope") == DEFAULT_SINGLE_COMMENT_RETRY_LIMIT
    deferred = tmp_path / "deferred.txt"
    assert (
        main(
            [
                "--split-payload",
                str(payload),
                "--output-dir",
                str(tmp_path / "capped"),
                "--retry-limit",
                "1",
                "--deferred-locations",
                str(deferred),
            ]
        )
        == 0
    )
    assert [path.name for path in sorted((tmp_path / "capped").glob("comment-*.json"))] == [
        "comment-000.json"
    ]
    assert "scripts/ci/other.py:12" in deferred.read_text(encoding="utf-8")
    assert (
        write_single_comment_payloads(
            json.loads(payload.read_text(encoding="utf-8")),
            tmp_path / "direct",
            limit=1,
        )
        == 1
    )
    error_path = tmp_path / "422.txt"
    error_path.write_text("gh: HTTP 422: Unprocessable Entity\n", encoding="utf-8")
    assert main(["--is-unprocessable", "--error-file", str(error_path)]) == 0
    error_path.write_text("Resource not accessible by integration\n", encoding="utf-8")
    assert main(["--is-unprocessable", "--error-file", str(error_path)]) == 1
    assert main(["--is-unprocessable"]) == 2
    assert main([]) == 2
