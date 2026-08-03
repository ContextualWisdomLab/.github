"""Focused contracts for changed-file review context concurrency."""

from collections.abc import Callable, Iterable, Iterator
from typing import Any

from scripts.ci import noema_review_gate as noema


class RecordingExecutor:
    """Synchronous executor double that records worker and map contracts."""

    instances: list["RecordingExecutor"] = []

    def __init__(self, *, max_workers: int) -> None:
        """Record the configured worker limit."""
        self.max_workers = max_workers
        self.map_inputs: list[tuple[str, ...]] = []
        self.instances.append(self)

    def __enter__(self) -> "RecordingExecutor":
        """Return the executor double for context-manager use."""
        return self

    def __exit__(self, *args: object) -> bool:
        """Propagate exceptions raised by the code under test."""
        return False

    def map(
        self,
        function: Callable[[str], str],
        values: Iterable[str],
    ) -> Iterator[str]:
        """Record ordered inputs and evaluate them synchronously."""
        ordered_values = tuple(values)
        self.map_inputs.append(ordered_values)
        return map(function, ordered_values)


def install_recording_executor(monkeypatch: Any) -> None:
    """Install a fresh recording executor double."""
    RecordingExecutor.instances.clear()
    monkeypatch.setattr(noema.concurrent.futures, "ThreadPoolExecutor", RecordingExecutor)


def test_single_file_context_does_not_create_executor(monkeypatch: Any) -> None:
    """Keep the one-file fast path strictly serial."""
    install_recording_executor(monkeypatch)
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: ["src/only.py"])
    monkeypatch.setattr(noema, "fetch_head_file_content", lambda repo, path, head_sha: "only content")

    context = noema.changed_file_context("owner/repo", 7, "head")

    assert RecordingExecutor.instances == []
    assert context == "### src/only.py\nonly content"


def test_parallel_file_context_uses_bounded_map_and_scrubs_errors(monkeypatch: Any) -> None:
    """Verify bounded parallel mapping, stable order, and error redaction."""
    install_recording_executor(monkeypatch)
    paths = [f"src/file_{index}.py" for index in range(noema.MAX_CONTEXT_WORKERS + 2)]
    sensitive_value = "".join(("github_", "pat_", "123456789"))
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: paths)

    def fake_fetch_head_file_content(repo: str, path: str, head_sha: str) -> str:
        """Return deterministic content while exercising error and empty paths."""
        if path == paths[0]:
            raise RuntimeError(f"API error token {sensitive_value}")
        if path == paths[-1]:
            return ""
        return f"content for {path}"

    monkeypatch.setattr(noema, "fetch_head_file_content", fake_fetch_head_file_content)

    context = noema.changed_file_context("owner/repo", 7, "head")

    assert len(RecordingExecutor.instances) == 1
    executor = RecordingExecutor.instances[0]
    assert executor.max_workers == min(noema.MAX_CONTEXT_WORKERS, len(paths))
    assert executor.max_workers <= noema.MAX_CONTEXT_WORKERS
    assert executor.max_workers <= len(paths)
    assert executor.map_inputs == [tuple(paths)]
    assert "Unavailable from head content API: API error token ***" in context
    assert sensitive_value not in context
    assert "No UTF-8 text content available from head content API." in context

    section_positions = [context.index(f"### {path}") for path in paths]
    assert section_positions == sorted(section_positions)


def test_parallel_file_context_worker_count_tracks_small_batches(monkeypatch: Any) -> None:
    """Limit worker creation to the number of files in a small batch."""
    install_recording_executor(monkeypatch)
    paths = ["src/first.py", "src/second.py"]
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: paths)
    monkeypatch.setattr(noema, "fetch_head_file_content", lambda repo, path, head_sha: path)

    noema.changed_file_context("owner/repo", 7, "head")

    executor = RecordingExecutor.instances[0]
    assert executor.max_workers == len(paths)
    assert executor.map_inputs == [tuple(paths)]
