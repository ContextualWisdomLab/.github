"""Concurrency regressions for Noema changed-file evidence collection."""

from __future__ import annotations

import threading
import time

from scripts.ci import noema_review_gate as noema


def test_changed_file_context_fetches_concurrently_and_preserves_order(monkeypatch) -> None:
    """Independent content reads run concurrently without reordering evidence."""

    paths = ["src/slow.py", "src/fast.py", "src/error.py"]
    rendezvous = threading.Barrier(len(paths), timeout=2)

    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: paths)

    def fetch_content(repo: str, path: str, head_sha: str) -> str:
        rendezvous.wait()
        if path == "src/slow.py":
            time.sleep(0.05)
            return "slow content"
        if path == "src/fast.py":
            return "fast content"
        raise RuntimeError("Authorization: Bearer should-not-leak")

    monkeypatch.setattr(noema, "fetch_head_file_content", fetch_content)

    context = noema.changed_file_context("owner/repo", 7, "a" * 40)

    assert context.index("### src/slow.py") < context.index("### src/fast.py")
    assert context.index("### src/fast.py") < context.index("### src/error.py")
    assert "slow content" in context
    assert "fast content" in context
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

    assert observed_workers == [10]
    assert context.count("### src/file_") == noema.MAX_CONTEXT_FILES


def test_changed_file_context_handles_zero_context_budget(monkeypatch) -> None:
    """A zero configured file budget fails closed before creating an executor."""

    monkeypatch.setattr(noema, "MAX_CONTEXT_FILES", 0)
    monkeypatch.setattr(
        noema,
        "fetch_changed_file_paths",
        lambda repo, number: ["src/file.py"],
    )

    assert (
        noema.changed_file_context("owner/repo", 7, "c" * 40)
        == "Changed file context unavailable: no paths to check."
    )
