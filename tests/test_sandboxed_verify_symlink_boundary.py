"""Security contracts for sandboxed verification symlink handling."""

import json

import subprocess
from pathlib import Path

import pytest

from scripts.ci import sandboxed_verify


def test_copy_workspace_rejects_symlink_that_escapes_repository(tmp_path: Path) -> None:
    """An untrusted repository symlink must not expose a host-side path."""
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "runner-secret.txt"
    outside.write_text("host-only", encoding="utf-8")
    (repo / "escape").symlink_to("../runner-secret.txt")

    with pytest.raises(ValueError, match="symlink escapes repository"):
        sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", ())


def test_copy_workspace_rejects_absolute_symlink_into_original_checkout(
    tmp_path: Path,
) -> None:
    """An absolute link must not reconnect the copy to its source checkout."""
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "target.txt"
    target.write_text("mutable source", encoding="utf-8")
    (repo / "absolute-alias.txt").symlink_to(target)

    with pytest.raises(ValueError, match="absolute target"):
        sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", ())


def test_copy_workspace_preserves_repository_internal_symlink(tmp_path: Path) -> None:
    """A relative symlink whose resolved target stays in the repository is safe."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "target.txt").write_text("review me", encoding="utf-8")
    (repo / "alias.txt").symlink_to("target.txt")

    copied = sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", ())

    assert (copied / "alias.txt").is_symlink()
    assert (copied / "alias.txt").read_text(encoding="utf-8") == "review me"


def test_copy_workspace_does_not_validate_ignored_symlinks(tmp_path: Path) -> None:
    """A link excluded from the copy is outside the command's path boundary."""
    repo = tmp_path / "repo"
    ignored = repo / "node_modules"
    ignored.mkdir(parents=True)
    outside = tmp_path / "package-cache"
    outside.mkdir()
    (ignored / "external-package").symlink_to(outside, target_is_directory=True)

    copied = sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", ())

    assert not (copied / "node_modules").exists()


def test_main_classifies_repository_path_boundary_without_traceback(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A rejected repository link must emit stable, non-sensitive evidence."""
    repo = tmp_path / "repo"
    repo.mkdir()
    sensitive_target = tmp_path / "runner-secret.txt"
    sensitive_target.write_text("host-only", encoding="utf-8")
    (repo / "escape").symlink_to(sensitive_target)

    exit_code = sandboxed_verify.main(
        ["--repo-root", str(repo), "--", "verify"]
    )
    captured = capsys.readouterr()
    lines = [
        line
        for line in captured.out.splitlines()
        if line.startswith(sandboxed_verify.RESULT_MARKER)
    ]
    payload = json.loads(lines[0].removeprefix(sandboxed_verify.RESULT_MARKER))

    assert exit_code == sandboxed_verify.PATH_BOUNDARY_EXIT_CODE
    assert payload["exit_code"] == sandboxed_verify.PATH_BOUNDARY_EXIT_CODE
    assert payload["path_boundary_rejected"] is True
    assert "repository path boundary rejected" in captured.err
    assert str(sensitive_target) not in captured.err
    assert "Traceback" not in captured.err


def test_timeout_without_partial_streams_still_emits_failed_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A silent timeout must retain deterministic fail-closed evidence."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def timeout_runner(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired(["verify"], 1)

    monkeypatch.setattr(sandboxed_verify, "run_command", timeout_runner)

    assert (
        sandboxed_verify.main(
            ["--repo-root", str(repo), "--timeout", "1", "--", "verify"]
        )
        == 124
    )
    lines = [
        line
        for line in capsys.readouterr().out.splitlines()
        if line.startswith(sandboxed_verify.RESULT_MARKER)
    ]
    assert len(lines) == 1
    payload = json.loads(lines[0].removeprefix(sandboxed_verify.RESULT_MARKER))
    assert payload["exit_code"] == 124
    assert payload["output_limit_bytes"] == 1_048_576
    assert payload["output_limited"] is False
    assert payload["output_limit_unsupported"] is False
    assert payload["sandboxed"] is True
