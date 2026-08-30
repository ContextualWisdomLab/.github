import json
import runpy
import shutil
import sys
from pathlib import Path

import pytest

from scripts.ci import sandboxed_verify


def test_scrubbed_env_uses_sandbox_paths_and_drops_secrets(monkeypatch, tmp_path):
    """Sandbox env keeps basic runtime variables but drops credentials."""
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    monkeypatch.setenv("CUSTOM_PASSWORD", "secret")
    monkeypatch.setenv("LANG", "C.UTF-8")

    env = sandboxed_verify.scrubbed_env(tmp_path)

    assert env["PATH"] == "/usr/bin"
    assert env["LANG"] == "C.UTF-8"
    assert "GITHUB_TOKEN" not in env
    assert "CUSTOM_PASSWORD" not in env
    assert env["SANDBOXED_VERIFY"] == "1"
    assert Path(env["HOME"]).is_dir()
    assert Path(env["TMPDIR"]).is_dir()


def test_scrubbed_env_allows_named_credentials_without_printing_values(monkeypatch, tmp_path, capsys):
    """Allowed secret names are recorded, but secret values are not printed."""
    monkeypatch.setenv("GITHUB_TOKEN", "secret-value")
    monkeypatch.setenv("OTHER_TOKEN", "other-secret")

    env = sandboxed_verify.scrubbed_env(tmp_path, ["GITHUB_TOKEN"])

    assert env["GITHUB_TOKEN"] == "secret-value"
    assert "OTHER_TOKEN" not in env

    sandboxed_verify.emit_result(
        command=["true"],
        copied_repo=tmp_path / "repo",
        sandbox_root=tmp_path,
        exit_code=0,
        elapsed_seconds=0.1,
        kept=False,
        allowed_env=["GITHUB_TOKEN"],
        network="required",
        evidence_note="fetch private dependency",
    )
    output = capsys.readouterr().out

    assert "GITHUB_TOKEN" in output
    assert "required" in output
    assert "fetch private dependency" in output
    assert "secret-value" not in output
    assert "other-secret" not in output


def test_copy_workspace_excludes_default_noise_and_keeps_sources(tmp_path):
    """Workspace copy excludes VCS/cache directories and preserves source files."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "script.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / ".git").mkdir()
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (repo / "__pycache__").mkdir()
    (repo / "__pycache__" / "x.pyc").write_bytes(b"cache")

    copied = sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])

    assert (copied / "script.py").read_text(encoding="utf-8") == "print('ok')\n"
    assert not (copied / ".git").exists()
    assert not (copied / "__pycache__").exists()


def test_copy_workspace_rejects_missing_repo_root(tmp_path):
    """Workspace copy fails clearly when the source root is invalid."""
    with pytest.raises(ValueError, match="repo root is not a directory"):
        sandboxed_verify.copy_workspace(tmp_path / "missing", tmp_path / "sandbox", [])


def test_copy_workspace_rejects_absolute_symlink_escaping_sandbox_root(tmp_path):
    """A workspace symlink pointing at a host path outside the copy fails the whole copy closed.

    ``shutil.copytree(..., symlinks=True)`` preserves a symlink's exact target
    string instead of dereferencing it. Left unchecked, a repository-supplied
    symlink pointing outside the copied tree would still be a live symlink
    inside the workspace handed to sandboxed commands, so a command that
    follows it could read or write host files outside the intended sandbox
    boundary — defeating the point of the isolation this module provides.
    Failing the whole copy closed guarantees the resulting tree can never be
    used to reach outside the sandbox root through that link.
    """
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("host-only-content", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "escape-link").symlink_to(outside)

    with pytest.raises(ValueError, match="workspace symlink escapes the sandbox root"):
        sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])


def test_copy_workspace_rejects_relative_symlink_escaping_via_parent_traversal(tmp_path):
    """A relative, ``..``-laden symlink target that exits the copied tree is also rejected."""
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("host-only-content", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    sandbox = tmp_path / "sandbox"
    # Once copied to sandbox/repo/escape-link, two ".." segments reach tmp_path.
    (repo / "escape-link").symlink_to(Path("../../outside-secret.txt"))

    with pytest.raises(ValueError, match="workspace symlink escapes the sandbox root"):
        sandboxed_verify.copy_workspace(repo, sandbox, [])


def test_copy_workspace_rejects_directory_symlink_escaping_sandbox_root(tmp_path):
    """A directory symlink escaping the copy is rejected without recursing into it.

    Descending into an escaping directory symlink to look for further
    problems would itself be an unbounded walk of host filesystem the sandbox
    is supposed to keep out of reach; the escaping symlink must be rejected
    at the point it is found, not traversed.
    """
    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("host-only-content", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "escape-dir").symlink_to(outside_dir, target_is_directory=True)

    with pytest.raises(ValueError, match="workspace symlink escapes the sandbox root"):
        sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])


def test_copy_workspace_rejects_unresolvable_symlink_cycle(tmp_path):
    """A symlink cycle that cannot be resolved fails closed instead of crashing.

    Resolving a symlink cycle raises ``RuntimeError`` on some Python versions
    and ``OSError`` (ELOOP) on others; either way it must become the same
    ``ValueError`` every other escape case in this function raises.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a").symlink_to("b")
    (repo / "b").symlink_to("a")

    with pytest.raises(ValueError, match="workspace symlink could not be resolved"):
        sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])


def test_copy_workspace_keeps_internal_symlinks_intact(tmp_path):
    """A symlink whose target stays inside the copied tree is preserved and still resolves."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "real.txt").write_text("payload", encoding="utf-8")
    (repo / "link.txt").symlink_to("real.txt")

    copied = sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])

    assert (copied / "link.txt").is_symlink()
    assert (copied / "link.txt").read_text(encoding="utf-8") == "payload"


def test_timeout_output_text_normalizes_subprocess_payloads():
    """Timeout output normalization handles subprocess bytes and missing streams."""
    assert sandboxed_verify.timeout_output_text(None) == ""
    assert sandboxed_verify.timeout_output_text(b"byte-output") == "byte-output"
    assert sandboxed_verify.timeout_output_text("text-output") == "text-output"


def test_main_runs_command_in_copy_without_mutating_source(tmp_path, capsys):
    """The wrapper runs commands in the copied workspace, not the source tree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "input.txt").write_text("source-value", encoding="utf-8")
    command = (
        "from pathlib import Path; "
        "import sys; "
        "print(Path('input.txt').read_text()); "
        "print('stderr-ok', file=sys.stderr); "
        "Path('created.txt').write_text('sandbox-only')"
    )

    exit_code = sandboxed_verify.main(
        [
            "--repo-root",
            str(repo),
            "--timeout",
            "10",
            "--",
            sys.executable,
            "-c",
            command,
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "source-value" in captured.out
    assert "stderr-ok" in captured.err
    assert "SANDBOXED_VERIFY_RESULT" in captured.out
    result_line = [line for line in captured.out.splitlines() if line.startswith(sandboxed_verify.RESULT_MARKER)][-1]
    payload = json.loads(result_line.removeprefix(sandboxed_verify.RESULT_MARKER).strip())
    assert payload["sandboxed"] is True
    assert payload["exit_code"] == 0
    assert payload["allowed_env"] == []
    assert payload["network"] == "default"
    assert not (repo / "created.txt").exists()


def test_main_reports_allowed_env_network_stderr_timeout_and_kept_sandbox(monkeypatch, tmp_path, capsys):
    """The wrapper records optional evidence fields and handles command timeout."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("VISIBLE_TOKEN", "secret-value")
    command = (
        "import sys, time; "
        "print('timeout-out', flush=True); "
        "print('timeout-err', file=sys.stderr, flush=True); "
        "time.sleep(2)"
    )

    exit_code = sandboxed_verify.main(
        [
            "--repo-root",
            str(repo),
            "--timeout",
            "1",
            "--keep-sandbox",
            "--allow-env",
            "VISIBLE_TOKEN",
            "--network",
            "required",
            "--evidence-note",
            "needs private dependency",
            "--",
            sys.executable,
            "-c",
            command,
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 124
    assert "allowed env names=VISIBLE_TOKEN" in captured.out
    assert "network=required" in captured.out
    assert "timeout-out" in captured.out
    assert "timeout-err" in captured.err
    assert "command timed out after 1s" in captured.err
    result_line = [line for line in captured.out.splitlines() if line.startswith(sandboxed_verify.RESULT_MARKER)][-1]
    payload = json.loads(result_line.removeprefix(sandboxed_verify.RESULT_MARKER).strip())
    assert payload["allowed_env"] == ["VISIBLE_TOKEN"]
    assert payload["network"] == "required"
    assert payload["evidence_note"] == "needs private dependency"
    assert payload["sandbox"] != "(removed)"
    shutil.rmtree(payload["sandbox"], ignore_errors=True)


def test_parse_args_rejects_invalid_inputs():
    """The CLI rejects invocations without a command or with invalid options."""
    with pytest.raises(SystemExit):
        sandboxed_verify.parse_args(["--repo-root", "."])
    with pytest.raises(SystemExit):
        sandboxed_verify.parse_args(["--timeout", "0", "--", "true"])
    with pytest.raises(SystemExit):
        sandboxed_verify.parse_args(["--allow-env", "not-valid-name!", "--", "true"])


def test_module_main_entrypoint(monkeypatch, tmp_path):
    """The script entrypoint exits with the verification command status."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(sys, "argv", ["sandboxed_verify.py", "--repo-root", str(repo), "--", sys.executable, "-c", "raise SystemExit(0)"])
    module = sys.modules.pop("scripts.ci.sandboxed_verify", None)
    with pytest.raises(SystemExit) as exc_info:
        try:
            runpy.run_module("scripts.ci.sandboxed_verify", run_name="__main__")
        finally:
            if module is not None:
                sys.modules["scripts.ci.sandboxed_verify"] = module
    assert exc_info.value.code == 0
