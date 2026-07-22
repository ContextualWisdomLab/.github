"""Tests for inert pull-request source materialization."""

from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import runpy
import stat
import subprocess
import sys
import time

import pytest

from scripts.ci import materialize_pr_review_source as materializer


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "materialize_pr_review_source.py"


def git(repo: Path, *args: str) -> str:
    """Run Git in a test repository and return stdout."""
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def build_repository(tmp_path: Path) -> tuple[Path, Path, str, str]:
    """Create a work repository and an isolated bare clone."""
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "--quiet")
    git(work, "config", "user.name", "test")
    git(work, "config", "user.email", "test@example.com")
    (work / "README.md").write_text("base\n", encoding="utf-8")
    git(work, "add", "README.md")
    git(work, "commit", "--quiet", "-m", "base fixture")
    base_sha = git(work, "rev-parse", "HEAD")
    (work / "src").mkdir()
    (work / "src" / "app.py").write_text("print('review data')\n", encoding="utf-8")
    executable = work / "run.sh"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    os.symlink("src/app.py", work / "app-link")
    (work / ".codegraph").mkdir()
    (work / ".codegraph" / "config.json").write_text(
        '{"untrusted": true}\n', encoding="utf-8"
    )
    git(work, "add", ".")
    git(work, "commit", "--quiet", "-m", "fixture")
    head_sha = git(work, "rev-parse", "HEAD")
    bare = tmp_path / "objects.git"
    subprocess.run(
        ["git", "clone", "--quiet", "--bare", str(work), str(bare)],
        check=True,
    )
    return work, bare, base_sha, head_sha


def test_materializes_only_inert_validated_blobs(tmp_path: Path) -> None:
    """Executable, symlink, and CodeGraph-controlled paths stay inert."""
    _work, bare, base_sha, head_sha = build_repository(tmp_path)
    source = tmp_path / "source"
    manifest = tmp_path / "manifest.json"

    completed = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--git-dir",
            str(bare),
            "--head-sha",
            head_sha,
            "--output-dir",
            str(source),
            "--manifest",
            str(manifest),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert (source / "src" / "app.py").read_text(
        encoding="utf-8"
    ) == "print('review data')\n"
    assert stat.S_IMODE((source / "run.sh").stat().st_mode) == 0o444
    assert not (source / "app-link").is_symlink()
    assert (source / "app-link").read_text(encoding="utf-8") == "src/app.py"
    assert not (source / ".codegraph").exists()
    assert (source / ".git").is_file()
    assert git(source, "rev-parse", "HEAD") == head_sha
    assert git(source, "merge-base", base_sha, head_sha) == base_sha
    assert set(git(source, "diff", "--name-only", base_sha, head_sha).splitlines()) == {
        ".codegraph/config.json",
        "app-link",
        "run.sh",
        "src/app.py",
    }

    evidence = json.loads(manifest.read_text(encoding="utf-8"))
    assert evidence["head_sha"] == head_sha
    assert evidence["written_files"] == 4
    assert {entry["path"] for entry in evidence["skipped"]} == {
        ".codegraph/config.json"
    }
    representations = {
        entry["path"]: entry["representation"]
        for entry in evidence["special_representations"]
    }
    assert representations == {
        "app-link": "inert-regular-file",
        "run.sh": "non-executable-regular-file",
    }


def test_rejects_non_bare_git_directory(tmp_path: Path) -> None:
    """A normal work repository cannot be confused with the object store."""
    work, _bare, _base_sha, head_sha = build_repository(tmp_path)
    args = materializer.parse_args(
        [
            "--git-dir",
            str(work / ".git"),
            "--head-sha",
            head_sha,
            "--output-dir",
            str(tmp_path / "source"),
            "--manifest",
            str(tmp_path / "manifest.json"),
        ]
    )

    try:
        materializer.materialize(args)
    except ValueError as exc:
        assert "isolated bare repository" in str(exc)
    else:
        raise AssertionError("non-bare repository was accepted")


def test_rejects_unsafe_tree_paths() -> None:
    """Traversal and absolute paths fail closed before filesystem writes."""
    for unsafe in (
        b"../escape",
        b"/absolute",
        b"a/../escape",
        b"directory\\file",
        b"directory//file",
        b"./file",
    ):
        try:
            materializer.safe_relative_path(unsafe)
        except ValueError:
            continue
        raise AssertionError(f"unsafe path was accepted: {unsafe!r}")


def test_rejects_symlink_ancestors_for_manifest_and_output(tmp_path: Path) -> None:
    """Existing parent links cannot redirect source or provenance writes."""
    outside = tmp_path / "outside"
    intended = tmp_path / "intended"
    outside.mkdir()
    intended.mkdir()
    os.symlink(outside, intended / "linked-parent")

    for option_path, option in (
        (intended / "linked-parent" / "manifest.json", "--manifest"),
        (intended / "linked-parent" / "source", "--output-dir"),
    ):
        try:
            materializer.reject_symlink_components(option_path, option)
        except ValueError as exc:
            assert option in str(exc)
            assert "symbolic-link path component" in str(exc)
        else:
            raise AssertionError(f"{option} accepted a symlink ancestor")
    assert not (outside / "manifest.json").exists()


def test_tree_file_limit_stops_streaming_producer_early(
    monkeypatch, tmp_path: Path
) -> None:
    """The parser terminates Git as soon as the next entry exceeds the limit."""
    oid = "a" * 40

    def record(name: str) -> bytes:
        return f"100644 blob {oid} 1\t{name}\0".encode()

    producer = (
        "import os,time; "
        f"os.write(1, {record('one')!r}); "
        f"os.write(1, {record('two')!r}); "
        "time.sleep(30)"
    )

    def open_producer(_git_dir: Path, _head_sha: str):
        return subprocess.Popen(
            [sys.executable, "-c", producer],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    monkeypatch.setattr(materializer, "open_tree_reader", open_producer)
    started = time.monotonic()
    try:
        materializer.parse_tree(
            tmp_path,
            oid,
            max_files=1,
            max_bytes=10,
            timeout_seconds=10,
        )
    except ValueError as exc:
        assert "--max-files (2 > 1)" in str(exc)
    else:
        raise AssertionError("oversized streaming tree was accepted")
    assert time.monotonic() - started < 5


def test_tree_byte_limit_fails_before_materializing_output(tmp_path: Path) -> None:
    """Accumulated blob sizes are rejected before the output directory exists."""
    _work, bare, _base_sha, head_sha = build_repository(tmp_path)
    output = tmp_path / "bounded-source"
    args = materializer.parse_args(
        [
            "--git-dir",
            str(bare),
            "--head-sha",
            head_sha,
            "--output-dir",
            str(output),
            "--manifest",
            str(tmp_path / "bounded-manifest.json"),
            "--max-bytes",
            "1",
        ]
    )

    try:
        materializer.materialize(args)
    except ValueError as exc:
        assert "--max-bytes" in str(exc)
    else:
        raise AssertionError("oversized tree bytes were accepted")
    assert not output.exists()


def test_tree_metadata_budget_stops_large_paths_before_append(
    monkeypatch, tmp_path: Path
) -> None:
    """Aggregate path metadata is bounded independently of blob payload bytes."""
    oid = "a" * 40
    record = f"100644 blob {oid} 1\t{'x' * 256}\0".encode()
    producer = f"import os; os.write(1, {record!r})"

    def open_producer(_git_dir: Path, _head_sha: str):
        return subprocess.Popen(
            [sys.executable, "-c", producer],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    monkeypatch.setattr(materializer, "open_tree_reader", open_producer)
    try:
        materializer.parse_tree(
            tmp_path,
            oid,
            max_files=10,
            max_bytes=10,
            max_tree_metadata_bytes=128,
            timeout_seconds=10,
        )
    except ValueError as exc:
        assert "--max-tree-metadata-bytes" in str(exc)
    else:
        raise AssertionError("oversized tree path metadata was accepted")


def test_argument_git_and_path_validation_edges(monkeypatch, tmp_path: Path) -> None:
    """Malformed limits, Git identities, and output paths fail before writes."""
    with pytest.raises(argparse.ArgumentTypeError, match="positive"):
        materializer.positive_int("0")
    with pytest.raises(SystemExit):
        materializer.parse_args(
            [
                "--git-dir",
                str(tmp_path),
                "--head-sha",
                "short",
                "--output-dir",
                str(tmp_path / "out"),
                "--manifest",
                str(tmp_path / "manifest"),
            ]
        )

    monkeypatch.setattr(
        materializer.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, stdout=b"", stderr=b"git detail"
        ),
    )
    with pytest.raises(RuntimeError, match="git detail"):
        materializer.git_bytes(tmp_path, "rev-parse", "HEAD")

    not_directory = tmp_path / "not-directory"
    not_directory.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="resolve to a directory"):
        materializer.validate_git_dir(not_directory, "a" * 40)

    responses = iter((b"true\n", b"b" * 40 + b"\n"))
    monkeypatch.setattr(materializer, "git_bytes", lambda *args: next(responses))
    with pytest.raises(ValueError, match="exact requested commit"):
        materializer.validate_git_dir(tmp_path, "a" * 40)

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="must not already exist"):
        materializer.validate_output_path(existing, tmp_path)
    with pytest.raises(ValueError, match="must not overlap"):
        materializer.validate_output_path(tmp_path / "nested", tmp_path)

    with pytest.raises(ValueError, match="non-UTF-8"):
        materializer.safe_relative_path(b"bad-\xff")


def test_tree_entry_parser_covers_gitlink_and_malformed_records() -> None:
    """Tree metadata accepts only exact blob and gitlink shapes."""
    oid = "a" * 40
    mode, kind, parsed_oid, size, path = materializer.parse_tree_entry(
        f"160000 commit {oid} -\tvendor/submodule".encode()
    )
    assert (mode, kind, parsed_oid, path.as_posix()) == (
        "160000",
        "commit",
        oid,
        "vendor/submodule",
    )
    assert size == len(f"Submodule commit {oid}\n".encode())

    for record, reason in (
        (b"not-a-tree-entry", "could not parse"),
        (b"100644 blob short 1\tfile", "invalid object id"),
        (f"100644 tree {oid} 1\tfile".encode(), "unsupported"),
    ):
        with pytest.raises(ValueError, match=reason):
            materializer.parse_tree_entry(record)


def test_process_termination_handles_finished_and_stubborn_producers() -> None:
    """Producer cleanup returns early or escalates from terminate to kill."""

    class Finished:
        def poll(self):
            return 0

    materializer.terminate_process(Finished())

    class Stubborn:
        terminated = False
        killed = False
        waits = 0

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("git", timeout)
            return 0

    process = Stubborn()
    materializer.terminate_process(process)
    assert process.terminated and process.killed and process.waits == 2


def test_tree_reader_missing_stdout_and_timeout(monkeypatch, tmp_path: Path) -> None:
    """Missing pipes and stalled enumeration terminate without materialization."""
    terminated = []

    class Missing:
        stdout = None

    missing = Missing()
    monkeypatch.setattr(materializer, "open_tree_reader", lambda *args: missing)
    monkeypatch.setattr(materializer, "terminate_process", terminated.append)
    with pytest.raises(RuntimeError, match="stdout pipe"):
        materializer.parse_tree(
            tmp_path,
            "a" * 40,
            max_files=1,
            max_bytes=1,
            timeout_seconds=1,
        )
    assert terminated == [missing]

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    monkeypatch.setattr(materializer, "open_tree_reader", lambda *args: process)
    monkeypatch.setattr(
        materializer,
        "terminate_process",
        lambda candidate: (candidate.kill(), candidate.wait()),
    )
    with pytest.raises(ValueError, match="tree-timeout-seconds"):
        materializer.parse_tree(
            tmp_path,
            "a" * 40,
            max_files=1,
            max_bytes=1,
            timeout_seconds=0,
        )


def test_tree_stream_record_and_exit_edge_cases(monkeypatch, tmp_path: Path) -> None:
    """EOF, bounded records, trailing bytes, wait timeout, and Git errors fail closed."""
    oid = "a" * 40

    def producer(payload: bytes, *, linger: bool = False):
        program = f"import os; os.write(1, {payload!r})"
        if linger:
            program += "; import time; time.sleep(30)"
        return subprocess.Popen(
            [sys.executable, "-c", program],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    monkeypatch.setattr(materializer, "MAX_TREE_RECORD_BYTES", 3)
    for payload in (b"abcd", b"abcd\0"):
        process = producer(payload, linger=True)
        monkeypatch.setattr(
            materializer, "open_tree_reader", lambda *args, p=process: p
        )
        with pytest.raises(ValueError, match="record-size"):
            materializer.parse_tree(
                tmp_path,
                oid,
                max_files=10,
                max_bytes=10,
                timeout_seconds=10,
            )

    monkeypatch.setattr(materializer, "MAX_TREE_RECORD_BYTES", 1024)
    process = producer(b"partial")
    monkeypatch.setattr(materializer, "open_tree_reader", lambda *args: process)
    with pytest.raises(ValueError, match="unterminated"):
        materializer.parse_tree(
            tmp_path,
            oid,
            max_files=10,
            max_bytes=10,
            timeout_seconds=10,
        )

    valid = f"100644 blob {oid} 1\tone".encode()
    process = producer(b"\0" + valid + b"\0")
    monkeypatch.setattr(materializer, "open_tree_reader", lambda *args: process)
    entries, total = materializer.parse_tree(
        tmp_path,
        oid,
        max_files=10,
        max_bytes=10,
        timeout_seconds=10,
    )
    assert len(entries) == 1 and total == 1

    class Selector:
        def register(self, *args):
            return None

        def select(self, timeout=None):
            return []

        def close(self):
            return None

    class Pipe(io.BytesIO):
        def fileno(self):
            return 1

    class Exited:
        stdout = Pipe()
        stderr = None

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(materializer.selectors, "DefaultSelector", Selector)
    monkeypatch.setattr(materializer, "open_tree_reader", lambda *args: Exited())
    assert materializer.parse_tree(
        tmp_path,
        oid,
        max_files=1,
        max_bytes=1,
        timeout_seconds=1,
    ) == ([], 0)

    class ReadySelector(Selector):
        def select(self, timeout=None):
            return [object()]

    class WaitFailure(Exited):
        stderr = io.BytesIO(b"tree failed")

        def __init__(self, result):
            self.result = result

        def wait(self, timeout=None):
            if self.result == "timeout":
                raise subprocess.TimeoutExpired("git", timeout)
            return self.result

    monkeypatch.setattr(materializer.selectors, "DefaultSelector", ReadySelector)
    monkeypatch.setattr(materializer.os, "read", lambda *args: b"")
    stopped = []
    monkeypatch.setattr(materializer, "terminate_process", stopped.append)
    timeout_process = WaitFailure("timeout")
    monkeypatch.setattr(materializer, "open_tree_reader", lambda *args: timeout_process)
    with pytest.raises(RuntimeError, match="did not exit"):
        materializer.parse_tree(
            tmp_path,
            oid,
            max_files=1,
            max_bytes=1,
            timeout_seconds=1,
        )
    assert stopped == [timeout_process]

    failed_process = WaitFailure(1)
    monkeypatch.setattr(materializer, "open_tree_reader", lambda *args: failed_process)
    with pytest.raises(RuntimeError, match="tree failed"):
        materializer.parse_tree(
            tmp_path,
            oid,
            max_files=1,
            max_bytes=1,
            timeout_seconds=1,
        )


def test_batch_blob_reader_rejects_pipe_header_size_and_truncation() -> None:
    """The batch protocol binds every blob header, type, size, and delimiter."""
    oid = "a" * 40

    class Batch:
        def __init__(self, payload: bytes, *, stdin=True):
            self.stdin = io.BytesIO() if stdin else None
            self.stdout = io.BytesIO(payload)

    with pytest.raises(RuntimeError, match="pipes"):
        materializer.read_blob(Batch(b"", stdin=False), oid, 1)
    for payload, size, reason in (
        (b"bad\n", 1, "unexpected object header"),
        (f"{oid} tree 1\n".encode(), 1, "not a blob"),
        (f"{oid} blob 2\n".encode(), 1, "size changed"),
        (f"{oid} blob 2\nx".encode(), 2, "truncated blob"),
    ):
        with pytest.raises(RuntimeError, match=reason):
            materializer.read_blob(Batch(payload), oid, size)


def test_inert_writer_closes_descriptor_after_fdopen_failure(
    monkeypatch, tmp_path: Path
) -> None:
    """A wrapper failure cannot leave a writable descriptor behind."""
    real_close = os.close

    def broken_fdopen(descriptor, *args, **kwargs):
        real_close(descriptor)
        raise RuntimeError("fdopen failed")

    monkeypatch.setattr(materializer.os, "fdopen", broken_fdopen)
    with pytest.raises(RuntimeError, match="fdopen failed"):
        materializer.write_inert_file(tmp_path / "inert", b"data")


def test_materialize_in_process_covers_gitlink_manifest_and_cli(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """The in-process path writes inert blobs, gitlink markers, provenance, and CLI output."""
    work, bare, _base_sha, fixture_head = build_repository(tmp_path)
    git(
        work,
        "update-index",
        "--add",
        "--cacheinfo",
        f"160000,{fixture_head},vendor/submodule",
    )
    git(work, "commit", "--quiet", "-m", "gitlink fixture")
    head_sha = git(work, "rev-parse", "HEAD")
    git(work, "push", "--quiet", str(bare), f"{head_sha}:refs/heads/master")

    def argv(output: Path, manifest: Path) -> list[str]:
        return [
            "--git-dir",
            str(bare),
            "--head-sha",
            head_sha,
            "--output-dir",
            str(output),
            "--manifest",
            str(manifest),
        ]

    output = tmp_path / "in-process-source"
    manifest = tmp_path / "in-process-manifest.json"
    metadata = materializer.materialize(materializer.parse_args(argv(output, manifest)))
    assert metadata["written_files"] == 5
    assert (output / "vendor" / "submodule").read_text(encoding="utf-8") == (
        f"Submodule commit {fixture_head}\n"
    )
    assert any(
        entry["representation"] == "gitlink-marker"
        for entry in metadata["special_representations"]
    )
    assert stat.S_IMODE(manifest.stat().st_mode) == 0o444

    cli_output = tmp_path / "cli-source"
    cli_manifest = tmp_path / "cli-manifest.json"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *argv(cli_output, cli_manifest)])
    assert materializer.main() == 0
    assert "Materialized inert PR source blobs" in capsys.readouterr().out


def test_materialize_preconditions_unsupported_entry_and_batch_failure(
    monkeypatch, tmp_path: Path
) -> None:
    """Manifest overlap, unsupported modes, and batch failures remain blocking."""
    git_dir = tmp_path / "objects.git"
    git_dir.mkdir()
    head = "a" * 40

    def args(output: Path, manifest: Path):
        return materializer.parse_args(
            [
                "--git-dir",
                str(git_dir),
                "--head-sha",
                head,
                "--output-dir",
                str(output),
                "--manifest",
                str(manifest),
            ]
        )

    monkeypatch.setattr(materializer, "validate_git_dir", lambda *unused: git_dir)
    monkeypatch.setattr(
        materializer, "validate_output_path", lambda output, unused: output
    )

    existing_manifest = tmp_path / "existing-manifest"
    existing_manifest.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest must not already exist"):
        materializer.materialize(args(tmp_path / "out-existing", existing_manifest))
    output = tmp_path / "out-overlap"
    with pytest.raises(ValueError, match="outside --output-dir"):
        materializer.materialize(args(output, output / "manifest"))

    class Batch:
        def __init__(self, *, result=0, stderr=None, stdin=True):
            self.stdin = io.BytesIO() if stdin else None
            self.stdout = io.BytesIO()
            self.stderr = io.BytesIO(stderr) if stderr is not None else None
            self.result = result

        def wait(self):
            return self.result

    unsupported_output = tmp_path / "unsupported-output"
    monkeypatch.setattr(
        materializer,
        "parse_tree",
        lambda *args, **kwargs: (
            [("999999", "blob", head, 0, PurePosixPath("bad"))],
            0,
        ),
    )
    monkeypatch.setattr(materializer, "open_batch_reader", lambda unused: Batch())
    with pytest.raises(ValueError, match="unsupported Git entry"):
        materializer.materialize(
            args(unsupported_output, tmp_path / "unsupported-manifest")
        )

    monkeypatch.setattr(materializer, "parse_tree", lambda *args, **kwargs: ([], 0))
    monkeypatch.setattr(
        materializer,
        "open_batch_reader",
        lambda unused: Batch(result=1, stderr=b"batch boom", stdin=False),
    )
    with pytest.raises(RuntimeError, match="batch boom"):
        materializer.materialize(
            args(tmp_path / "batch-output", tmp_path / "batch-manifest")
        )


def test_materializer_main_failure_dunder_and_missing_git_import(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """CLI failures are bounded, the dunder exits, and Git discovery fails closed."""
    monkeypatch.setattr(
        materializer,
        "materialize",
        lambda args: (_ for _ in ()).throw(ValueError("bounded failure")),
    )
    argv = [
        "--git-dir",
        str(tmp_path / "missing.git"),
        "--head-sha",
        "a" * 40,
        "--output-dir",
        str(tmp_path / "out"),
        "--manifest",
        str(tmp_path / "manifest"),
    ]
    assert materializer.main(argv) == 1
    assert "bounded failure" in capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *argv])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert exc.value.code == 1

    monkeypatch.setattr(materializer.shutil, "which", lambda unused: None)
    with pytest.raises(RuntimeError, match="absolute Git executable"):
        runpy.run_path(str(SCRIPT), run_name="materializer_without_git")
