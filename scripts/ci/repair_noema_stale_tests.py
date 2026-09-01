#!/usr/bin/env python3
"""Align stale Noema tests with the protected-main changed-file contract.

The production API already returns path/status pairs and intentionally removed
CodeGraph side-loading. These old fixtures were merged after that API change and
must not block the independent truncated-completion repair.
"""

from pathlib import Path


PATH = Path("tests/test_noema_review_gate.py")


def main() -> int:
    """Replace only the obsolete API fixtures and context-builder scenario."""
    text = PATH.read_text(encoding="utf-8")

    text = text.replace(
        'monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: ["tool.py"])',
        'monkeypatch.setattr(noema, "fetch_changed_files", lambda repo, number: [("tool.py", "modified")])',
    )
    text = text.replace(
        'monkeypatch.setattr(noema, "build_review_context", lambda repo, number, value: "context")',
        'monkeypatch.setattr(noema, "build_review_context", lambda repo, number, value, changed_files=None: "context")',
    )
    text = text.replace(
        'monkeypatch.setattr(noema, "build_review_context", lambda repo, number, pr: "context")',
        'monkeypatch.setattr(noema, "build_review_context", lambda repo, number, pr, changed_files=None: "context")',
    )

    start_marker = "def test_review_context_builders_include_codegraph_threads_and_files"
    end_marker = "\n\nclass FakeResponse:"
    if text.count(start_marker) != 1:
        raise SystemExit(
            f"expected one obsolete context-builder test, found {text.count(start_marker)}"
        )
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    replacement = '''def test_review_context_builders_include_threads_and_files(monkeypatch):
    assert noema.truncate_text("abc", 10) == "abc"
    assert "truncated 2 characters" in noema.truncate_text("abcdef", 4)
    assert "missing PR head SHA" in noema.changed_file_context("owner/repo", 7, "")

    original_fetch_files = noema.fetch_changed_files
    monkeypatch.setattr(noema, "fetch_changed_files", lambda repo, number: [])
    assert "no changed files" in noema.changed_file_context("owner/repo", 7, "head")
    monkeypatch.setattr(noema, "fetch_changed_files", original_fetch_files)

    encoded = base64.b64encode(b"print('hello')\\n").decode("ascii")
    calls = []

    def fake_run(args, stdin=None):
        calls.append(args)
        target = args[2]
        if target.endswith("/files"):
            return "\\n".join(
                [
                    json.dumps(["src/a.py", "modified"]),
                    json.dumps(["README.md", "modified"]),
                    json.dumps(["empty.txt", "modified"]),
                ]
            ) + "\\n"
        if "contents/src/a.py" in target:
            return encoded
        if "contents/README.md" in target:
            raise RuntimeError("Command failed: token secret")
        if "contents/empty.txt" in target:
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(noema, "run", fake_run)
    pr = make_pr(
        headRefOid="head sha",
        baseRefOid="base sha",
        reviewThreads={
            "nodes": [
                {
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/a.py",
                    "line": 3,
                    "comments": {
                        "nodes": [
                            {
                                "author": {"login": "reviewer"},
                                "body": "check call site",
                            }
                        ]
                    },
                },
                {
                    "isResolved": True,
                    "isOutdated": False,
                    "path": "README.md",
                    "comments": {"nodes": []},
                },
            ]
        },
    )

    context = noema.build_review_context("owner/repo", 7, pr)

    assert "CodeGraph context" not in context
    assert "Thread open at src/a.py:3" in context
    assert "reviewer: check call site" in context
    assert "### src/a.py" in context
    assert "print('hello')" in context
    assert "Unavailable from head content API" in context
    assert "No UTF-8 text content available" in context
    assert any("/files" in call[2] for call in calls)


def test_review_context_reports_omitted_files(monkeypatch):
    files = [
        (f"src/file_{index}.py", "modified")
        for index in range(noema.MAX_CONTEXT_FILES + 1)
    ]
    monkeypatch.setattr(noema, "fetch_changed_files", lambda repo, number: files)
    monkeypatch.setattr(
        noema, "fetch_file_content_at_ref", lambda repo, path, ref: "x"
    )

    context = noema.changed_file_context("owner/repo", 7, "head")

    assert "1 changed files omitted from context budget" in context
'''
    text = text[:start] + replacement + text[end:]

    if "fetch_changed_file_paths" in text:
        raise SystemExit("obsolete fetch_changed_file_paths fixture remains")
    if "load_codegraph_context" in text:
        raise SystemExit("obsolete CodeGraph fixture remains")
    if 'lambda repo, number, pr: "context"' in text:
        raise SystemExit("obsolete three-argument build_review_context fixture remains")

    PATH.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
