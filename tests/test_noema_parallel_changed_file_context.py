"""Concurrency regressions for Noema changed-file evidence collection."""

from __future__ import annotations

import threading
import time

from scripts.ci import noema_review_gate as noema


def test_changed_file_context_fetches_concurrently_and_preserves_order(monkeypatch) -> None:
    """Independent reads run concurrently and keep success/error/empty order."""

    paths = ["src/slow.py", "src/fast.py", "src/empty.py", "src/error.py"]
    rendezvous = threading.Barrier(len(paths), timeout=2)

    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: paths)

    def fetch_content(repo: str, path: str, head_sha: str) -> str:
        rendezvous.wait()
        if path == "src/slow.py":
            time.sleep(0.05)
            return "slow content"
        if path == "src/fast.py":
            return "fast content"
        if path == "src/empty.py":
            return ""
        raise RuntimeError("Authorization: Bearer should-not-leak")

    monkeypatch.setattr(noema, "fetch_head_file_content", fetch_content)

    context = noema.changed_file_context("owner/repo", 7, "a" * 40)

    headings = [f"### {path}" for path in paths]
    assert [context.index(heading) for heading in headings] == sorted(
        context.index(heading) for heading in headings
    )
    assert "slow content" in context
    assert "fast content" in context
    assert "No UTF-8 text content available from head content API." in context
    assert "Authorization: Bearer ***" in context
    assert "should-not-leak" not in context


def test_changed_file_context_caps_parallel_workers(monkeypatch) -> None:
    """The API fan-out remains bounded even when the context budget is full."""

    paths = [f"src/file_{index}.py" for index in range(noema.MAX_CONTEXT_FILES)]
    observed_workers: list[int] = []
    real_executor = noema.concurrent.futures.ThreadPoolExecutor

    def bounded_executor(*, max_workers: int):
        observed_workers.append(max_workers)
        return real_executor(max_workers=max_workers)

    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: paths)
    monkeypatch.setattr(
        noema,
        "fetch_head_file_content",
        lambda repo, path, head_sha: f"content for {path}",
    )
    monkeypatch.setattr(noema.concurrent.futures, "ThreadPoolExecutor", bounded_executor)

    context = noema.changed_file_context("owner/repo", 7, "b" * 40)

    assert observed_workers == [noema.MAX_CONTEXT_FETCH_WORKERS]
    assert context.count("### src/file_") == noema.MAX_CONTEXT_FILES
