"""Regression tests for trusted base Python lock installation."""

from __future__ import annotations

import io
import json
import pathlib
import subprocess

import pytest

from scripts.ci import install_base_python_locks as installer


def write_candidate(
    root: pathlib.Path,
    *,
    generated_file: str,
    source: str,
    content: str = "demo==1 --hash=sha256:" + ("a" * 64) + "\n",
) -> None:
    """Append one manifest entry and write its materialized lock."""
    manifest_path = root / "manifest.json"
    manifest = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else []
    )
    manifest.append({"file": generated_file, "source": source})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (root / generated_file).write_text(content, encoding="utf-8")


def test_recovers_partial_supplement_with_same_directory_lock(tmp_path) -> None:
    """An optional supplement can join its sibling lock without widening scope."""
    write_candidate(
        tmp_path,
        generated_file="requirements-000.txt",
        source="backend/requirements-agent.txt",
    )
    write_candidate(
        tmp_path,
        generated_file="requirements-001.txt",
        source="backend/requirements-hashes.txt",
    )
    commands: list[list[str]] = []

    def fake_runner(command: list[str], **kwargs):
        commands.append(command)
        requirements = [
            command[index + 1]
            for index, argument in enumerate(command)
            if argument == "-r"
        ]
        if (
            "--dry-run" in command
            and len(requirements) == 1
            and requirements[0].endswith("requirements-000.txt")
        ):
            return subprocess.CompletedProcess(
                command,
                1,
                stdout=(
                    "ERROR: In --require-hashes mode, all requirements must have "
                    "their versions pinned with ==: httpx>=0.27"
                ),
            )
        return subprocess.CompletedProcess(command, 0, stdout="")

    stdout = io.StringIO()
    stderr = io.StringIO()
    result = installer.install_materialized_locks(
        tmp_path,
        runner=fake_runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert len(commands) == 4
    assert "--dry-run" in commands[0]
    assert "--ignore-installed" in commands[0]
    assert "--dry-run" in commands[1]
    assert "--ignore-installed" in commands[1]
    assert "--dry-run" in commands[2]
    assert commands[2].count("-r") == 2
    assert "--dry-run" not in commands[3]
    assert commands[3].count("-r") == 2
    assert stderr.getvalue() == ""
    assert "Recovered trusted base Python supplement" in stdout.getvalue()
    assert "candidates=2 installed=2 skipped=0" in stdout.getvalue()


def test_skips_partial_candidate_without_completing_sibling(tmp_path) -> None:
    """An unrecoverable hash-bearing supplement remains visible and non-fatal."""
    write_candidate(
        tmp_path,
        generated_file="requirements-000.txt",
        source="backend/requirements-agent.txt",
    )

    def fake_runner(command: list[str], **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=(
                "ERROR: In --require-hashes mode, all requirements must have "
                "their versions pinned with ==: httpx>=0.27"
            ),
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    result = installer.install_materialized_locks(
        tmp_path,
        runner=fake_runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "requirements-agent.txt" in stderr.getvalue()
    assert "httpx>=0.27" in stderr.getvalue()
    assert "candidates=1 installed=0 skipped=1" in stdout.getvalue()


def test_failed_same_directory_group_still_skips_partial_candidates(tmp_path) -> None:
    """A sibling group that remains incomplete cannot become an install plan."""
    write_candidate(
        tmp_path,
        generated_file="requirements-000.txt",
        source="backend/requirements-agent.txt",
    )
    write_candidate(
        tmp_path,
        generated_file="requirements-001.txt",
        source="backend/requirements-extra.txt",
    )
    commands: list[list[str]] = []

    def fake_runner(command: list[str], **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=(
                "ERROR: In --require-hashes mode, all requirements must have "
                "their versions pinned with ==: httpx>=0.27"
            ),
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    result = installer.install_materialized_locks(
        tmp_path,
        runner=fake_runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert len(commands) == 3
    assert commands[-1].count("-r") == 2
    assert "installed=0 skipped=2" in stdout.getvalue()
    assert stderr.getvalue().count("httpx>=0.27") == 2


@pytest.mark.parametrize(
    "failure_output",
    [
        "",
        ("ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE"),
        "WARNING: Retrying after connection broken by ConnectionError",
        "ERROR: Could not fetch URL https://pypi.org/simple/demo/",
        "pip resolver crashed without a classified dependency error",
    ],
)
def test_unclassified_preflight_failure_is_fatal(tmp_path, failure_output: str) -> None:
    """Hash, network, empty, and unknown preflight failures fail closed."""
    write_candidate(
        tmp_path,
        generated_file="requirements-000.txt",
        source="requirements-hashes.txt",
    )

    def fake_runner(command: list[str], **kwargs):
        return subprocess.CompletedProcess(command, 23, stdout=failure_output)

    stderr = io.StringIO()
    result = installer.install_materialized_locks(
        tmp_path,
        runner=fake_runner,
        stderr=stderr,
    )

    assert result == 23
    assert "only incomplete hash closures" in stderr.getvalue()
    assert "requirements-hashes.txt" in stderr.getvalue()
    if failure_output:
        assert failure_output in stderr.getvalue()


def test_explicit_python_incompatibility_is_visible_and_nonfatal(tmp_path) -> None:
    """A base lock for another interpreter may defer to coverage execution."""
    write_candidate(
        tmp_path,
        generated_file="requirements-000.txt",
        source="requirements-hashes.txt",
    )

    def fake_runner(command: list[str], **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=(
                "ERROR: Package 'demo' requires a different Python: "
                "3.14.0 not in '<3.14,>=3.10'"
            ),
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    result = installer.install_materialized_locks(
        tmp_path,
        runner=fake_runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "requires a different Python" in stderr.getvalue()
    assert "candidates=1 installed=0 skipped=1" in stdout.getvalue()


def test_unavailable_binary_version_for_runner_interpreter_is_nonfatal(tmp_path) -> None:
    """A pinned package without a compatible runner binary may defer safely."""
    write_candidate(
        tmp_path,
        generated_file="requirements-000.txt",
        source="fuzz/requirements-atheris.txt",
    )

    def fake_runner(command: list[str], **kwargs):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=(
                "ERROR: Could not find a version that satisfies the requirement "
                "atheris==3.0.0 (from versions: 3.1.0)\n"
                "ERROR: No matching distribution found for atheris==3.0.0"
            ),
        )

    stdout = io.StringIO()
    stderr = io.StringIO()
    result = installer.install_materialized_locks(
        tmp_path,
        runner=fake_runner,
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert "atheris==3.0.0" in stderr.getvalue()
    assert "candidates=1 installed=0 skipped=1" in stdout.getvalue()


def test_fatal_same_directory_group_failure_aborts(tmp_path) -> None:
    """A group cannot turn a registry or integrity failure into a skip."""
    write_candidate(
        tmp_path,
        generated_file="requirements-000.txt",
        source="backend/requirements-agent.txt",
    )
    write_candidate(
        tmp_path,
        generated_file="requirements-001.txt",
        source="backend/requirements-hashes.txt",
    )
    call_count = 0

    def fake_runner(command: list[str], **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return subprocess.CompletedProcess(
                command,
                1,
                stdout=(
                    "ERROR: In --require-hashes mode, all requirements must have "
                    "their versions pinned with ==: httpx>=0.27"
                ),
            )
        return subprocess.CompletedProcess(
            command,
            29,
            stdout="ERROR: Could not fetch URL https://pypi.org/simple/httpx/",
        )

    stderr = io.StringIO()
    result = installer.install_materialized_locks(
        tmp_path,
        runner=fake_runner,
        stderr=stderr,
    )

    assert result == 29
    assert call_count == 3
    assert "Could not fetch URL" in stderr.getvalue()


@pytest.mark.parametrize(
    ("manifest_text", "candidate_files", "error"),
    [
        (None, (), "regular non-symlink"),
        ("{not-json", (), "manifest is invalid"),
        ("{}", (), "must be a JSON array"),
        ("[1]", (), "entries must be objects"),
        (
            '[{"file":"requirements-000.txt","source":"/absolute.txt"}]',
            ("requirements-000.txt",),
            "unsafe source path",
        ),
        (
            (
                '[{"file":"requirements-000.txt","source":"one.txt"},'
                '{"file":"requirements-000.txt","source":"two.txt"}]'
            ),
            ("requirements-000.txt",),
            "duplicate file names",
        ),
        (
            '[{"file":"requirements-000.txt","source":"missing.txt"}]',
            (),
            "must be a regular file",
        ),
    ],
)
def test_manifest_validation_failures(
    tmp_path,
    manifest_text: str | None,
    candidate_files: tuple[str, ...],
    error: str,
) -> None:
    """Malformed trusted materializer output fails before any pip command."""
    if manifest_text is not None:
        (tmp_path / "manifest.json").write_text(manifest_text, encoding="utf-8")
    for candidate_file in candidate_files:
        (tmp_path / candidate_file).write_text("lock", encoding="utf-8")

    with pytest.raises(ValueError, match=error):
        installer._manifest_entries(tmp_path)


def test_bounded_failure_output_preserves_root_and_tail() -> None:
    """Long resolver logs retain their leading context and final root cause."""
    output = "\n".join(f"line-{index}" for index in range(150))

    bounded = installer._bounded_failure_output(output)

    assert bounded.splitlines()[0] == "line-0"
    assert "30 dependency-resolution log lines omitted" in bounded
    assert bounded.splitlines()[-1] == "line-149"


def test_rejects_unsafe_manifest_before_running_pip(tmp_path) -> None:
    """Generated and source paths must remain inside trusted materializer output."""
    (tmp_path / "manifest.json").write_text(
        json.dumps([{"file": "../escape.txt", "source": "/absolute/lock.txt"}]),
        encoding="utf-8",
    )
    called = False

    def fake_runner(command: list[str], **kwargs):
        nonlocal called
        called = True
        return subprocess.CompletedProcess(command, 0, stdout="")

    stderr = io.StringIO()
    result = installer.install_materialized_locks(
        tmp_path,
        runner=fake_runner,
        stderr=stderr,
    )

    assert result == 2
    assert not called
    assert "unsafe file name" in stderr.getvalue()


def test_install_failure_after_successful_preflight_is_fatal(tmp_path) -> None:
    """A registry or hash race after preflight must fail the image build."""
    write_candidate(
        tmp_path,
        generated_file="requirements-000.txt",
        source="requirements-hashes.txt",
    )
    call_count = 0

    def fake_runner(command: list[str], **kwargs):
        nonlocal call_count
        call_count += 1
        return subprocess.CompletedProcess(
            command,
            0 if call_count == 1 else 19,
            stdout="",
        )

    stderr = io.StringIO()
    result = installer.install_materialized_locks(
        tmp_path,
        runner=fake_runner,
        stderr=stderr,
    )

    assert result == 19
    assert "failed during installation" in stderr.getvalue()


def test_main_forwards_requirements_root(monkeypatch, tmp_path) -> None:
    """The CLI delegates the exact requirements root to the installer."""
    seen: list[pathlib.Path] = []

    def fake_install(root: pathlib.Path) -> int:
        seen.append(root)
        return 7

    monkeypatch.setattr(installer, "install_materialized_locks", fake_install)

    assert installer.main(["--requirements-root", str(tmp_path)]) == 7
    assert seen == [tmp_path]
