import hashlib
import json
import runpy
import shutil
import sys
import threading
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


def test_copy_workspace_excludes_credential_bearing_paths(tmp_path):
    """A repo checkout's credential files must never ride into the writable sandbox."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "script.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / ".env").write_text("SECRET=leaked\n", encoding="utf-8")
    (repo / ".env.production").write_text("SECRET=leaked\n", encoding="utf-8")
    (repo / ".npmrc").write_text("//registry.example.com/:_authToken=leaked\n", encoding="utf-8")
    (repo / ".netrc").write_text("machine example.com login x password leaked\n", encoding="utf-8")
    (repo / ".git-credentials").write_text("https://x:leaked@example.com\n", encoding="utf-8")
    (repo / ".ssh").mkdir()
    (repo / ".ssh" / "id_rsa").write_text("leaked-key\n", encoding="utf-8")
    (repo / ".aws").mkdir()
    (repo / ".aws" / "credentials").write_text("leaked\n", encoding="utf-8")

    copied = sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])

    assert (copied / "script.py").read_text(encoding="utf-8") == "print('ok')\n"
    for excluded in (
        ".env",
        ".env.production",
        ".npmrc",
        ".netrc",
        ".git-credentials",
        ".ssh",
        ".aws",
    ):
        assert not (copied / excluded).exists(), excluded


def test_copy_workspace_preserves_env_templates_but_excludes_env_secrets(tmp_path):
    """Committed dotenv templates survive the copy while real dotenv secrets are excluded.

    ``.env.*`` in ``DEFAULT_IGNORE`` exists to exclude credential-bearing
    dotenv variants such as ``.env.local`` or ``.env.production``, but the
    same glob also matches committed, secret-free templates like
    ``.env.example`` that verification commands may rely on for local
    defaults. Those specific template names must remain in the copy even
    though they match the exclusion glob.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "script.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / ".env.example").write_text("SECRET=set-me\n", encoding="utf-8")
    (repo / ".env.sample").write_text("SECRET=set-me\n", encoding="utf-8")
    (repo / ".env.template").write_text("SECRET=set-me\n", encoding="utf-8")
    (repo / ".env").write_text("SECRET=leaked\n", encoding="utf-8")
    (repo / ".env.local").write_text("SECRET=leaked\n", encoding="utf-8")
    (repo / ".env.production").write_text("SECRET=leaked\n", encoding="utf-8")

    copied = sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])

    assert (copied / "script.py").read_text(encoding="utf-8") == "print('ok')\n"
    for preserved in (".env.example", ".env.sample", ".env.template"):
        assert (copied / preserved).exists(), preserved
        assert (copied / preserved).read_text(encoding="utf-8") == "SECRET=set-me\n"
    for excluded in (".env", ".env.local", ".env.production"):
        assert not (copied / excluded).exists(), excluded


def test_copy_workspace_extra_ignore_overrides_env_template_allowlist(tmp_path):
    """An explicit caller exclusion for a template name is not restored by the allowlist.

    ``DEFAULT_ENV_TEMPLATE_ALLOWLIST`` exists to carve committed, secret-free
    templates back out of the broad ``.env.*`` glob in ``DEFAULT_IGNORE``. It
    must never also override a caller's own explicit ``extra_ignores`` (the
    ``--ignore`` CLI flag) -- for example because in a particular repository
    ``.env.example`` happens to carry something sensitive despite the
    generic name. If the allowlist restored a name regardless of *why* it
    was ignored, that explicit exclusion would be silently defeated and the
    file would ride into the writable, command-readable sandbox anyway.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "script.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / ".env.example").write_text("SECRET=actually-sensitive\n", encoding="utf-8")
    (repo / ".env.sample").write_text("SECRET=set-me\n", encoding="utf-8")

    copied = sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [".env.example"])

    assert (copied / "script.py").read_text(encoding="utf-8") == "print('ok')\n"
    assert not (copied / ".env.example").exists()
    # A template the caller did NOT explicitly exclude is still preserved --
    # the allowlist keeps working for everything except the explicit ask.
    assert (copied / ".env.sample").exists()
    assert (copied / ".env.sample").read_text(encoding="utf-8") == "SECRET=set-me\n"


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


def test_copy_workspace_rejects_relative_symlink_escaping_via_parent_traversal(
    tmp_path,
):
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


def test_copy_workspace_rejects_escape_via_intermediate_directory_alias(tmp_path):
    """An intermediate alias component inside a target is resolved, not skipped.

    ``self-alias`` points at ``.`` (its own parent, the repo root) -- entirely
    legitimate and safe standing on its own. But ``link``'s target,
    ``self-alias/../outside-secret.txt``, only *looks* safe if the whole
    string is collapsed lexically in one step (``self-alias/..`` cancels to
    nothing, leaving what looks like a plain in-repo reference). Resolved for
    real, component by component, following ``self-alias`` lands at the repo
    root itself (zero depth), so the very next ``..`` immediately exits the
    repo. A check that only ran ``os.path.normpath`` on the whole target
    string once would miss this; walking one component at a time must not.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "self-alias").symlink_to(".", target_is_directory=True)
    (repo / "link").symlink_to("self-alias/../outside-secret.txt")

    with pytest.raises(ValueError, match="workspace symlink escapes the sandbox root"):
        sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])


def test_copy_workspace_rejects_unresolvable_symlink_cycle(tmp_path):
    """A symlink cycle that never terminates fails closed instead of hanging.

    The walk tracks every symlink it is currently in the middle of
    following; revisiting one of those without ever leaving the sandbox root
    means the chain cannot be resolved to a real, bounded target, so it
    becomes the same ``ValueError`` every other unresolvable case in this
    function raises.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a").symlink_to("b")
    (repo / "b").symlink_to("a")

    with pytest.raises(ValueError, match="workspace symlink could not be resolved"):
        sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])


def test_copy_workspace_accepts_the_same_symlink_referenced_twice_non_recursively(
    tmp_path,
):
    """A symlink resolved twice in one chain, not as part of a loop, is accepted.

    ``link -> shared/../shared/file.txt`` references ``shared`` twice, but
    the first reference is fully resolved (and its bookkeeping cleared)
    before the second one is ever reached -- this is not a cycle, just an
    ordinary path that happens to name the same symlink in two places, and
    the OS itself resolves it without issue. A cycle check that treats
    "already resolved once, earlier" the same as "currently being resolved"
    would reject this valid path.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "real_dir").mkdir()
    (repo / "real_dir" / "file.txt").write_text("payload", encoding="utf-8")
    (repo / "shared").symlink_to("real_dir", target_is_directory=True)
    (repo / "link").symlink_to("shared/../shared/file.txt")

    copied = sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])

    assert (copied / "link").is_symlink()
    assert (copied / "link").read_text(encoding="utf-8") == "payload"


def test_copy_workspace_keeps_internal_symlinks_intact(tmp_path):
    """A symlink whose target stays inside the copied tree is preserved and still resolves."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "real.txt").write_text("payload", encoding="utf-8")
    (repo / "link.txt").symlink_to("real.txt")

    copied = sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])

    assert (copied / "link.txt").is_symlink()
    assert (copied / "link.txt").read_text(encoding="utf-8") == "payload"


def test_copy_workspace_keeps_cross_directory_symlink_using_parent_traversal(tmp_path):
    """A relative ``..`` that climbs back into the repo, not out of it, is accepted.

    ``subdir/link.txt -> ../sibling.txt`` needs exactly one ``..`` to reach a
    real sibling file at the repo root -- a common, legitimate pattern (e.g.
    ``bin/tool -> ../lib/tool``). This must not be confused with a ``..``
    that pops above the sandbox root itself.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "sibling.txt").write_text("payload", encoding="utf-8")
    subdir = repo / "subdir"
    subdir.mkdir()
    (subdir / "link.txt").symlink_to("../sibling.txt")

    copied = sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])

    assert (copied / "subdir" / "link.txt").is_symlink()
    assert (copied / "subdir" / "link.txt").read_text(encoding="utf-8") == "payload"


def test_copy_workspace_keeps_symlink_dangling_from_a_missing_internal_target(tmp_path):
    """A symlink whose target was never present is accepted, not treated as an escape.

    A dangling target is not evidence of an escape attempt: the link's own
    normalized path still lands inside the sandbox root, it simply names a
    file that does not exist. Verification must still run against the rest
    of the copy instead of aborting the whole copy over a broken link.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "dangling.txt").symlink_to("does-not-exist.txt")

    copied = sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])

    assert (copied / "dangling.txt").is_symlink()
    assert not (copied / "dangling.txt").exists()


def test_copy_workspace_accepts_internal_symlink_when_sandbox_root_is_reached_via_symlinked_ancestor(
    tmp_path,
):
    """A benign internal symlink is accepted even when an *ancestor* of the sandbox
    root is itself reached through a symlink (for example a symlinked default
    temp directory, unrelated to anything the copied repository controls).

    Before this fix, ``_reject_escaping_symlinks`` walked ``destination.rglob("*")``
    -- the *unresolved* path -- but checked each symlink's position with
    ``path.relative_to(root)``, where ``root`` is ``destination`` fully
    *resolved*. When some ancestor directory leading to ``destination`` is a
    symlink, those two strings diverge even though they name the same real
    location, so ``relative_to`` raised ``ValueError`` for every symlink in an
    entirely legitimate copy, aborting the whole run with no actual escape
    present.
    """
    real_root = tmp_path / "real_sandbox_root"
    real_root.mkdir()
    linked_root = tmp_path / "linked_sandbox_root"
    linked_root.symlink_to(real_root, target_is_directory=True)

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "real.txt").write_text("payload", encoding="utf-8")
    (repo / "link.txt").symlink_to("real.txt")

    copied = sandboxed_verify.copy_workspace(repo, linked_root, [])

    assert (copied / "link.txt").is_symlink()
    assert (copied / "link.txt").read_text(encoding="utf-8") == "payload"


def test_copy_workspace_still_rejects_escape_when_sandbox_root_is_reached_via_symlinked_ancestor(
    tmp_path,
):
    """A genuinely escaping symlink is still rejected when the sandbox root is
    itself reached through a symlinked ancestor -- walking from the resolved
    root (this fix) must not weaken the escape check itself.
    """
    real_root = tmp_path / "real_sandbox_root"
    real_root.mkdir()
    linked_root = tmp_path / "linked_sandbox_root"
    linked_root.symlink_to(real_root, target_is_directory=True)

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "evil.txt").symlink_to("/etc/passwd")

    with pytest.raises(ValueError, match="workspace symlink escapes the sandbox root"):
        sandboxed_verify.copy_workspace(repo, linked_root, [])


def test_copy_workspace_rejects_symlink_chain_past_the_hop_limit(tmp_path):
    """A long, never-repeating, never-escaping symlink chain still fails closed.

    Purely lexical normalization means a chain of distinct symlink names can
    walk forever without ever revisiting a path or leaving the sandbox root;
    the hop limit exists precisely to bound that case instead of hanging.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    chain_length = sandboxed_verify.MAXIMUM_SYMLINK_HOPS + 5
    for index in range(chain_length):
        (repo / f"hop-{index}").symlink_to(f"hop-{index + 1}")
    (repo / f"hop-{chain_length}").write_text("payload", encoding="utf-8")

    with pytest.raises(ValueError, match="workspace symlink could not be resolved"):
        sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])


def test_copy_workspace_accepts_a_chain_of_exactly_the_hop_limit(tmp_path):
    """A chain of exactly MAXIMUM_SYMLINK_HOPS real symlinks is still accepted.

    The walk checks one position per iteration and only advances past it if
    it is itself a further symlink, so resolving a chain of N real symlinks
    needs N+1 checks: one per hop, plus one to confirm the final landing
    position is a real, non-symlink target. A chain of exactly the hop limit
    is something the OS can resolve without issue and must not be rejected.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    chain_length = sandboxed_verify.MAXIMUM_SYMLINK_HOPS
    for index in range(chain_length - 1):
        (repo / f"hop-{index}").symlink_to(f"hop-{index + 1}")
    (repo / f"hop-{chain_length - 1}").symlink_to("real.txt")
    (repo / "real.txt").write_text("payload", encoding="utf-8")

    copied = sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])

    assert (copied / "hop-0").is_symlink()
    assert (copied / "real.txt").read_text(encoding="utf-8") == "payload"


def test_copy_workspace_keeps_symlink_whose_target_was_excluded_from_the_copy(tmp_path):
    """A symlink into a directory excluded by DEFAULT_IGNORE is accepted, not an escape.

    ``shutil.copytree``'s ignore patterns can omit a symlink's target from
    the copy (for example a link into ``node_modules``) while the link
    itself, sitting outside the ignored directory, is still copied. The
    resulting dangling link is workspace-bound and must not abort the copy.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "leaf.js").write_text("module.exports = {}", encoding="utf-8")
    (repo / "bin-link.js").symlink_to("node_modules/leaf.js")

    copied = sandboxed_verify.copy_workspace(repo, tmp_path / "sandbox", [])

    assert not (copied / "node_modules").exists()
    assert (copied / "bin-link.js").is_symlink()
    assert not (copied / "bin-link.js").exists()


def test_timeout_output_text_normalizes_subprocess_payloads():
    """Timeout output normalization handles subprocess bytes and missing streams."""
    assert sandboxed_verify.timeout_output_text(None) == ""
    assert sandboxed_verify.timeout_output_text(b"byte-output") == "byte-output"
    assert sandboxed_verify.timeout_output_text("text-output") == "text-output"


def test_forward_bytes_flushes_text_before_binary_output():
    """Buffered wrapper diagnostics must precede forwarded command bytes."""
    events = []

    class BinaryStream:
        def write(self, output):
            events.append(("binary-write", output))

        def flush(self):
            events.append(("binary-flush", None))

    class TextStream:
        buffer = BinaryStream()

        def flush(self):
            events.append(("text-flush", None))

    sandboxed_verify._forward_bytes(TextStream(), b"command-output")

    assert events == [
        ("text-flush", None),
        ("binary-write", b"command-output"),
        ("binary-flush", None),
    ]


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


def test_main_can_write_wrapper_result_to_exclusive_file(tmp_path, capsys):
    """A caller can separate trusted control evidence from command stdout."""
    repo = tmp_path / "repo"
    repo.mkdir()
    result_file = tmp_path / "handoff" / "result.txt"

    exit_code = sandboxed_verify.main(
        [
            "--repo-root",
            str(repo),
            "--result-file",
            str(result_file),
            "--",
            sys.executable,
            "-c",
            "import sys; "
            "sys.stdout.buffer.write(b'SANDBOXED_VERIFY_RESULT attacker-controlled\\n{\\\"fake\\\": true}') ; "
            "sys.stderr.buffer.write(b'no-final-newline')",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "attacker-controlled" in captured.out
    assert any(line == sandboxed_verify.RESULT_MARKER + " attacker-controlled" for line in captured.out.splitlines())
    assert result_file.read_text(encoding="utf-8").startswith(sandboxed_verify.RESULT_MARKER + " {")
    stdout_file = result_file.with_name(result_file.name + ".stdout")
    stderr_file = result_file.with_name(result_file.name + ".stderr")
    stdout_bytes = stdout_file.read_bytes()
    stderr_bytes = stderr_file.read_bytes()
    payload = json.loads(result_file.read_text(encoding="utf-8").removeprefix(sandboxed_verify.RESULT_MARKER).strip())
    assert stdout_bytes == b'SANDBOXED_VERIFY_RESULT attacker-controlled\n{"fake": true}'
    assert stderr_bytes == b"no-final-newline"
    assert payload["schema"] == "sandboxed_verify.execution.v1"
    assert payload["result_state"] == "completed"
    assert payload["timed_out"] is False
    assert payload["helper_id"] == "ContextualWisdomLab/.github:sandboxed_verify"
    assert payload["runtime"]["implementation"]
    assert payload["runtime"]["python_version"]
    assert payload["isolation"] == {
        "network_enforced": False,
        "os_process_isolation": "none",
        "workspace": "copy+scrubbed-env",
    }
    assert payload["stdout"] == {
        "file": stdout_file.name,
        "sha256": hashlib.sha256(stdout_bytes).hexdigest(),
        "size_bytes": len(stdout_bytes),
    }
    assert payload["stderr"] == {
        "file": stderr_file.name,
        "sha256": hashlib.sha256(stderr_bytes).hexdigest(),
        "size_bytes": len(stderr_bytes),
    }
    with pytest.raises(ValueError, match="result file already exists"):
        sandboxed_verify.emit_result(
            command=("true",),
            copied_repo=repo,
            sandbox_root=tmp_path,
            exit_code=0,
            elapsed_seconds=0,
            kept=False,
            allowed_env=(),
            network="default",
            evidence_note="",
            result_file=result_file,
        )


def test_result_envelope_is_not_visible_before_streams_are_complete(monkeypatch, tmp_path):
    """The envelope path becomes visible only after both streams are complete."""
    result_file = tmp_path / "evidence" / "result.json"
    first_stream_started = threading.Event()
    release_first_stream = threading.Event()
    envelope_write_started = threading.Event()
    release_envelope_write = threading.Event()
    original_write_all = sandboxed_verify._write_all

    def pause_publication(file_descriptor, content):
        if content == b"stdout":
            first_stream_started.set()
            assert release_first_stream.wait(timeout=2)
        elif content == b"envelope":
            envelope_write_started.set()
            assert release_envelope_write.wait(timeout=2)
        original_write_all(file_descriptor, content)

    monkeypatch.setattr(sandboxed_verify, "_write_all", pause_publication)
    writer = threading.Thread(
        target=sandboxed_verify._write_result_bundle,
        args=(result_file, b"envelope", b"stdout", b"stderr"),
    )
    writer.start()
    assert first_stream_started.wait(timeout=2)
    try:
        assert not result_file.exists()
    finally:
        release_first_stream.set()

    assert envelope_write_started.wait(timeout=2)
    try:
        assert not result_file.exists()
    finally:
        release_envelope_write.set()
        writer.join(timeout=2)

    assert not writer.is_alive()
    assert result_file.read_bytes() == b"envelope"
    assert result_file.with_name(result_file.name + ".stdout").read_bytes() == b"stdout"
    assert result_file.with_name(result_file.name + ".stderr").read_bytes() == b"stderr"


def test_result_file_rejects_symlinked_parent(tmp_path):
    """The trusted handoff must not follow a caller-controlled parent symlink."""
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="parent is not a regular directory"):
        sandboxed_verify.emit_result(
            command=("true",),
            copied_repo=tmp_path,
            sandbox_root=tmp_path,
            exit_code=0,
            elapsed_seconds=0,
            kept=False,
            allowed_env=(),
            network="default",
            evidence_note="",
            result_file=link / "result.json",
        )


def test_result_file_rejects_existing_symlink_ancestor(tmp_path):
    """An existing nested directory must not hide a symlink ancestor."""
    target = tmp_path / "target"
    nested = target / "nested"
    nested.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError, match="parent is not a regular directory"):
        sandboxed_verify.emit_result(
            command=("true",),
            copied_repo=tmp_path,
            sandbox_root=tmp_path,
            exit_code=0,
            elapsed_seconds=0,
            kept=False,
            allowed_env=(),
            network="default",
            evidence_note="",
            result_file=link / "nested" / "result.json",
        )

    assert not (nested / "result.json").exists()


def test_result_bundle_preserves_large_binary_streams(tmp_path, capfdbinary):
    """Dedicated handoff files preserve large invalid UTF-8 output exactly."""
    repo = tmp_path / "repo"
    repo.mkdir()
    result_file = tmp_path / "evidence" / "result.json"
    stdout_bytes = (b"\xff\x00marker\n" * 131_072) + b"tail"
    stderr_bytes = b"\xfejson:{not-json}\r\nend"
    command = (
        "import sys; "
        "sys.stdout.buffer.write((b'\\xff\\x00marker\\n' * 131072) + b'tail'); "
        "sys.stderr.buffer.write(b'\\xfejson:{not-json}\\r\\nend')"
    )

    assert (
        sandboxed_verify.main(
            [
                "--repo-root",
                str(repo),
                "--result-file",
                str(result_file),
                "--",
                sys.executable,
                "-c",
                command,
            ]
        )
        == 0
    )
    capfdbinary.readouterr()

    assert result_file.with_name(result_file.name + ".stdout").read_bytes() == stdout_bytes
    assert result_file.with_name(result_file.name + ".stderr").read_bytes() == stderr_bytes


def test_result_file_distinguishes_timeout_from_exit_124(tmp_path, capsys):
    """A real timeout and a command exit 124 have different result states."""
    repo = tmp_path / "repo"
    repo.mkdir()
    timeout_result = tmp_path / "timeout" / "result.json"
    exit_result = tmp_path / "exit" / "result.json"

    assert (
        sandboxed_verify.main(
            [
                "--repo-root",
                str(repo),
                "--timeout",
                "1",
                "--result-file",
                str(timeout_result),
                "--",
                sys.executable,
                "-c",
                "import time; print('partial', flush=True); time.sleep(2)",
            ]
        )
        == 124
    )
    assert (
        sandboxed_verify.main(
            [
                "--repo-root",
                str(repo),
                "--result-file",
                str(exit_result),
                "--",
                sys.executable,
                "-c",
                "raise SystemExit(124)",
            ]
        )
        == 124
    )
    capsys.readouterr()

    timeout_payload = json.loads(
        timeout_result.read_text(encoding="utf-8").removeprefix(sandboxed_verify.RESULT_MARKER).strip()
    )
    exit_payload = json.loads(
        exit_result.read_text(encoding="utf-8").removeprefix(sandboxed_verify.RESULT_MARKER).strip()
    )
    assert timeout_payload["result_state"] == "timed_out"
    assert timeout_payload["timed_out"] is True
    assert exit_payload["result_state"] == "completed"
    assert exit_payload["timed_out"] is False
    assert timeout_result.with_name(timeout_result.name + ".stdout").read_bytes() == b"partial\n"


def test_result_file_failure_is_bounded_and_always_cleans_sandbox(monkeypatch, tmp_path, capsys):
    """A successful command with a handoff collision returns 125 and cleans up."""
    repo = tmp_path / "repo"
    repo.mkdir()
    sandbox = tmp_path / "sandbox"
    result_file = tmp_path / "result.json"
    result_file.write_text("occupied", encoding="utf-8")

    def make_sandbox(*, prefix):
        assert prefix == "sandboxed-verify-"
        sandbox.mkdir()
        return str(sandbox)

    monkeypatch.setattr(sandboxed_verify.tempfile, "mkdtemp", make_sandbox)

    assert (
        sandboxed_verify.main(
            [
                "--repo-root",
                str(repo),
                "--result-file",
                str(result_file),
                "--",
                "true",
            ]
        )
        == 125
    )
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "result file already exists" in captured.err
    assert not sandbox.exists()


@pytest.mark.parametrize(
    ("command", "expected_exit_code"),
    [
        ((sys.executable, "-c", "raise SystemExit(2)"), 2),
        ((sys.executable, "-c", "raise SystemExit(124)"), 124),
    ],
)
def test_result_file_failure_preserves_command_failure(
    command, expected_exit_code, tmp_path, capsys
):
    """Evidence rejection must not mask the command's nonzero exit status."""
    repo = tmp_path / "repo"
    repo.mkdir()
    result_file = tmp_path / "result.json"
    result_file.write_text("occupied", encoding="utf-8")

    exit_code = sandboxed_verify.main(
        [
            "--repo-root",
            str(repo),
            "--result-file",
            str(result_file),
            "--",
            *command,
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == expected_exit_code
    assert "result file already exists" in captured.err


def test_result_file_failure_preserves_timeout_status(monkeypatch, tmp_path, capsys):
    """Evidence rejection must not mask the wrapper's timeout status."""
    repo = tmp_path / "repo"
    repo.mkdir()
    result_file = tmp_path / "result.json"
    result_file.write_text("occupied", encoding="utf-8")

    def time_out(*_args, **_kwargs):
        raise sandboxed_verify.subprocess.TimeoutExpired(
            cmd=("slow-command",), timeout=1, output=b"partial-out", stderr=b"partial-err"
        )

    monkeypatch.setattr(sandboxed_verify, "run_command", time_out)

    exit_code = sandboxed_verify.main(
        [
            "--repo-root",
            str(repo),
            "--timeout",
            "1",
            "--result-file",
            str(result_file),
            "--",
            "slow-command",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 124
    assert "command timed out after 1s" in captured.err
    assert "result file already exists" in captured.err


def test_main_reports_a_clean_failure_when_the_workspace_copy_is_rejected(tmp_path, capsys):
    """A symlink-escape rejection from ``copy_workspace`` must not surface as an
    uncaught traceback.

    ``main()`` previously called ``copy_workspace`` with no ``except`` around
    it, so a rejected copy (see the ``test_copy_workspace_rejects_*`` tests
    above) propagated as an uncaught ``ValueError`` -- a raw Python traceback
    on stderr and Python's default uncaught-exception exit status, instead of
    the clean ``sandboxed-verify: ...`` message and coded exit this module
    uses for every other config-time rejection (e.g. the timeout path's 124).
    """
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("host-only-content", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "escape-link").symlink_to(outside)

    exit_code = sandboxed_verify.main(["--repo-root", str(repo), "--", "true"])
    captured = capsys.readouterr()

    assert exit_code == 125
    assert "Traceback" not in captured.err
    assert "workspace copy rejected" in captured.err
    assert "workspace symlink escapes the sandbox root" in captured.err
    result_line = [line for line in captured.out.splitlines() if line.startswith(sandboxed_verify.RESULT_MARKER)][-1]
    payload = json.loads(result_line.removeprefix(sandboxed_verify.RESULT_MARKER).strip())
    assert payload["exit_code"] == 125


def test_copy_rejection_is_recorded_in_trusted_result_bundle(tmp_path):
    """A rejected source tree must still produce explicit trusted evidence."""
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("host-only-content", encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "escape-link").symlink_to(outside)
    result_file = tmp_path / "evidence" / "result.json"

    exit_code = sandboxed_verify.main(
        [
            "--repo-root",
            str(repo),
            "--result-file",
            str(result_file),
            "--",
            "true",
        ]
    )

    assert exit_code == 125
    wrapper_result = json.loads(
        result_file.read_text(encoding="utf-8").removeprefix(sandboxed_verify.RESULT_MARKER).strip()
    )
    assert wrapper_result["result_state"] == "copy_rejected"
    assert wrapper_result["timed_out"] is False
    assert result_file.with_name(result_file.name + ".stdout").read_bytes() == b""
    assert result_file.with_name(result_file.name + ".stderr").read_bytes() == b""


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
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sandboxed_verify.py",
            "--repo-root",
            str(repo),
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(0)",
        ],
    )
    module = sys.modules.pop("scripts.ci.sandboxed_verify", None)
    with pytest.raises(SystemExit) as exc_info:
        try:
            runpy.run_module("scripts.ci.sandboxed_verify", run_name="__main__")
        finally:
            if module is not None:
                sys.modules["scripts.ci.sandboxed_verify"] = module
    assert exc_info.value.code == 0
