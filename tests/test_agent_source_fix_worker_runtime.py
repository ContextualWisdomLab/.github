from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts" / "ci"))

import agent_source_fix_worker as worker  # noqa: E402


HEAD = "a" * 40
BASE = "b" * 40
BODY = "@cwl-source-fix repair the bounded defect"


def claim(body: str = BODY) -> dict[str, object]:
    return {
        "actor": "seonghobae",
        "base_ref": "main",
        "base_sha": BASE,
        "comment_id": 7001,
        "head_ref": "fix/current-pr",
        "head_sha": HEAD,
        "instruction_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "pr_number": 42,
        "repository": "ContextualWisdomLab/.github",
        "write_mode": "existing-pr-files-only",
    }


def install_claim_env(monkeypatch: pytest.MonkeyPatch, value: dict[str, object] | None = None) -> dict[str, object]:
    current = claim() if value is None else value
    env = {
        "REQUESTED_BY": current["actor"],
        "PR_BASE_REF": current["base_ref"],
        "PR_BASE_SHA": current["base_sha"],
        "SOURCE_COMMENT_ID": current["comment_id"],
        "PR_HEAD_REF": current["head_ref"],
        "PR_HEAD_SHA": current["head_sha"],
        "INSTRUCTION_SHA256": current["instruction_sha256"],
        "PR_NUMBER": current["pr_number"],
        "TARGET_REPOSITORY": current["repository"],
    }
    for name, item in env.items():
        monkeypatch.setenv(name, str(item))
    monkeypatch.setenv("INVOCATION_KEY", worker.claim_key(current))
    return current


def completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr=stderr)


def live_comment(body: str = BODY) -> dict[str, Any]:
    return {
        "body": body,
        "author_association": "OWNER",
        "issue_url": "https://api.github.com/repos/ContextualWisdomLab/.github/issues/42",
        "user": {"login": "seonghobae", "type": "User"},
    }


def live_pull(*, changed_files: Any = 1) -> dict[str, Any]:
    return {
        "state": "open",
        "changed_files": changed_files,
        "head": {
            "sha": HEAD,
            "ref": "fix/current-pr",
            "repo": {"full_name": "ContextualWisdomLab/.github"},
        },
        "base": {"sha": BASE, "ref": "main"},
    }


def test_safe_error_redacts_bounds_and_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "redact_text", lambda text: "cleaned secret")
    assert worker._safe_error(RuntimeError(" secret\nvalue "), limit=7) == "cleaned"
    monkeypatch.setattr(worker, "redact_text", lambda text: "")
    assert worker._safe_error(ValueError("anything")) == "ValueError"


def test_env_requires_nonempty_and_strips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXAMPLE", " value ")
    assert worker._env("EXAMPLE") == "value"
    monkeypatch.delenv("EXAMPLE")
    with pytest.raises(ValueError, match="EXAMPLE"):
        worker._env("EXAMPLE")


def test_run_is_argv_only_and_supports_unchecked_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(*args, **kwargs):
        calls.append({"args": args, **kwargs})
        return completed("ok", returncode=3)

    monkeypatch.setattr(worker.subprocess, "run", fake_run)
    result = worker.run(["tool", "arg"], cwd=tmp_path, env={"X": "1"}, input_text="input", check=False)
    assert result.stdout == "ok"
    assert calls[0]["args"][0] == ["tool", "arg"]
    assert calls[0]["cwd"] == str(tmp_path)
    assert calls[0]["shell"] is False and calls[0]["check"] is False


@pytest.mark.parametrize(
    ("stderr", "stdout", "redacted", "needle"),
    [
        ("stderr detail", "stdout detail", "safe stderr", "safe stderr"),
        ("", "stdout detail", "safe stdout", "safe stdout"),
        ("", "", "", "command failed"),
    ],
)
def test_run_failure_uses_bounded_redacted_detail(
    monkeypatch: pytest.MonkeyPatch,
    stderr: str,
    stdout: str,
    redacted: str,
    needle: str,
) -> None:
    monkeypatch.setattr(worker.subprocess, "run", lambda *args, **kwargs: completed(stdout, stderr, 7))
    monkeypatch.setattr(worker, "redact_text", lambda text: redacted)
    with pytest.raises(RuntimeError, match=needle):
        worker.run(["bad"])


def test_run_without_cwd_and_gh_json(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    def fake_subprocess(*args, **kwargs):
        seen.append(kwargs["cwd"])
        return completed('{"ok": true}')

    monkeypatch.setattr(worker.subprocess, "run", fake_subprocess)
    assert worker.gh_json(["repos/example"]) == {"ok": True}
    assert seen == [None]
    monkeypatch.setattr(worker, "run", lambda *args, **kwargs: completed(""))
    assert worker.gh_json(["repos/example"]) is None


def test_static_claim_and_claim_key(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = install_claim_env(monkeypatch)
    assert worker.static_claim() == expected
    assert worker.claim_key(expected) == worker.claim_key(dict(reversed(list(expected.items()))))
    assert len(worker.claim_key(expected)) == 64


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("repository", "OtherOrg/repo", "target_repository"),
        ("head_ref", "-bad", "ref"),
        ("base_ref", "-bad", "ref"),
        ("head_sha", "bad", "SHA"),
        ("base_sha", "bad", "SHA"),
        ("actor", "bad user", "actor"),
        ("instruction_sha256", "bad", "instruction digest"),
        ("pr_number", 0, "number/comment"),
        ("comment_id", 0, "number/comment"),
    ],
)
def test_validate_static_inputs_rejects_malformed_claim(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object, message: str
) -> None:
    current = claim()
    current[field] = value
    monkeypatch.setattr(worker, "static_claim", lambda: current)
    with pytest.raises(ValueError, match=message):
        worker.validate_static_inputs()


def test_validate_static_inputs_rejects_bad_key_and_accepts_exact_key(monkeypatch: pytest.MonkeyPatch) -> None:
    current = claim()
    monkeypatch.setattr(worker, "static_claim", lambda: current)
    monkeypatch.setenv("INVOCATION_KEY", "bad")
    with pytest.raises(ValueError, match="invocation key is invalid"):
        worker.validate_static_inputs()
    monkeypatch.setenv("INVOCATION_KEY", "0" * 64)
    with pytest.raises(ValueError, match="does not match"):
        worker.validate_static_inputs()
    monkeypatch.setenv("INVOCATION_KEY", worker.claim_key(current))
    assert worker.validate_static_inputs() == current


def test_flatten_pages_accepts_supported_shapes_and_rejects_malformed() -> None:
    assert worker._flatten_pages([]) == []
    assert worker._flatten_pages([{"id": 1}]) == [{"id": 1}]
    assert worker._flatten_pages([[{"id": 1}], [{"id": 2}]]) == [{"id": 1}, {"id": 2}]
    with pytest.raises(ValueError, match="empty"):
        worker._flatten_pages(None)
    with pytest.raises(ValueError, match="malformed"):
        worker._flatten_pages([[{"id": 1}], ["bad"]])
    with pytest.raises(ValueError, match="malformed"):
        worker._flatten_pages({"id": 1})


@pytest.mark.parametrize(
    ("path", "safe"),
    [
        ("src/file.py", True),
        ("", False),
        (" src/file.py", False),
        ("/absolute", False),
        ("src/../escape", False),
        ("src/bad\0name", False),
        ("src/bad\rname", False),
        ("src/bad\nname", False),
        ("src/`bad`", False),
    ],
)
def test_safe_path(path: str, safe: bool) -> None:
    assert worker._safe_path(path) is safe


@pytest.mark.parametrize(
    ("path", "control"),
    [
        (".github", True),
        (".github/workflows/x.yml", True),
        ("scripts/ci", True),
        ("scripts/ci/x.py", True),
        (".git/config", True),
        ("src/file.py", False),
    ],
)
def test_control_plane_path(path: str, control: bool) -> None:
    assert worker._is_control_plane_path(path) is control


def test_current_permission_accepts_writer_and_rejects_bad_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "gh_json", lambda args: {"permission": "ADMIN"})
    assert worker._current_permission("ContextualWisdomLab/.github", "user") == "admin"
    monkeypatch.setattr(worker, "gh_json", lambda args: [])
    with pytest.raises(ValueError, match="malformed"):
        worker._current_permission("ContextualWisdomLab/.github", "user")
    monkeypatch.setattr(worker, "gh_json", lambda args: {"permission": "read"})
    with pytest.raises(PermissionError, match="read"):
        worker._current_permission("ContextualWisdomLab/.github", "user")
    monkeypatch.setattr(worker, "gh_json", lambda args: {})
    with pytest.raises(PermissionError, match="none"):
        worker._current_permission("ContextualWisdomLab/.github", "user")


def test_source_comment_and_pull_request_require_objects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "gh_json", lambda args: {"ok": True})
    assert worker._source_comment("repo", 1) == {"ok": True}
    assert worker._pull_request("repo", 1) == {"ok": True}
    monkeypatch.setattr(worker, "gh_json", lambda args: [])
    with pytest.raises(ValueError, match="comment response"):
        worker._source_comment("repo", 1)
    with pytest.raises(ValueError, match="pull request response"):
        worker._pull_request("repo", 1)


def test_pr_files_filters_removed_and_control_plane_and_sorts(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        {"filename": "z.py", "status": "modified"},
        {"filename": ".github/x.yml", "status": "modified"},
        {"filename": "old.py", "status": "removed"},
        {"filename": "a.py", "status": "added"},
    ]
    monkeypatch.setattr(worker, "gh_json", lambda args: records)
    assert worker._pr_files("repo", 1, 4) == ("a.py", "z.py")


@pytest.mark.parametrize("count", [0, worker.MAX_PR_FILES + 1])
def test_pr_files_rejects_invalid_count(monkeypatch: pytest.MonkeyPatch, count: int) -> None:
    monkeypatch.setattr(worker, "gh_json", lambda args: [])
    with pytest.raises(ValueError, match="requires"):
        worker._pr_files("repo", 1, count)


def test_pr_files_rejects_incomplete_unsafe_duplicate_and_empty_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "gh_json", lambda args: [{"filename": "a.py", "status": "modified"}])
    with pytest.raises(ValueError, match="incomplete"):
        worker._pr_files("repo", 1, 2)
    monkeypatch.setattr(worker, "gh_json", lambda args: [{"filename": "../bad", "status": "modified"}])
    with pytest.raises(ValueError, match="unsafe or duplicate"):
        worker._pr_files("repo", 1, 1)
    monkeypatch.setattr(
        worker,
        "gh_json",
        lambda args: [
            {"filename": "a.py", "status": "modified"},
            {"filename": "a.py", "status": "modified"},
        ],
    )
    with pytest.raises(ValueError, match="unsafe or duplicate"):
        worker._pr_files("repo", 1, 2)
    monkeypatch.setattr(
        worker,
        "gh_json",
        lambda args: [
            {"filename": ".github/a.yml", "status": "modified"},
            {"filename": "old.py", "status": "removed"},
        ],
    )
    with pytest.raises(ValueError, match="no existing"):
        worker._pr_files("repo", 1, 2)


def install_live_context(monkeypatch: pytest.MonkeyPatch, body: str = BODY) -> tuple[dict[str, Any], dict[str, Any]]:
    comment = live_comment(body)
    pull = live_pull()
    monkeypatch.setattr(worker, "_current_permission", lambda repository, actor: "write")
    monkeypatch.setattr(worker, "_source_comment", lambda repository, comment_id: comment)
    monkeypatch.setattr(worker, "_pull_request", lambda repository, pr_number: pull)
    monkeypatch.setattr(worker, "_pr_files", lambda repository, pr_number, changed_files: ("src/fix.py",))
    return comment, pull


def test_live_context_returns_instruction_and_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    current = claim()
    install_live_context(monkeypatch)
    assert worker.live_context(current) == ("repair the bounded defect", ("src/fix.py",))


def test_live_context_rejects_comment_authority_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    current = claim()
    comment, _ = install_live_context(monkeypatch)
    comment["user"]["login"] = "other"
    with pytest.raises(PermissionError, match="actor"):
        worker.live_context(current)
    comment["user"] = {"login": "seonghobae", "type": "Bot"}
    with pytest.raises(PermissionError, match="Bot-authored"):
        worker.live_context(current)
    comment["user"] = {"login": "seonghobae", "type": "User"}
    comment["author_association"] = "NONE"
    with pytest.raises(PermissionError, match="trusted association"):
        worker.live_context(current)


def test_live_context_rejects_comment_identity_and_instruction_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    current = claim()
    comment, _ = install_live_context(monkeypatch)
    comment["issue_url"] = "https://api.github.com/repos/ContextualWisdomLab/.github/issues/41"
    with pytest.raises(ValueError, match="claimed pull request"):
        worker.live_context(current)
    comment["issue_url"] = "https://api.github.com/repos/ContextualWisdomLab/.github/issues/42"
    comment["body"] = "x" * (worker.MAX_COMMENT_CHARS + 1)
    with pytest.raises(ValueError, match="bounded comment"):
        worker.live_context(current)
    comment["body"] = "no command"
    with pytest.raises(ValueError, match="no longer contains"):
        worker.live_context(current)
    comment["body"] = "@cwl-source-fix changed"
    with pytest.raises(ValueError, match="changed after dispatch"):
        worker.live_context(current)


def test_live_context_rejects_pull_identity_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    current = claim()
    _, pull = install_live_context(monkeypatch)
    cases = [
        (lambda: pull.update(state="closed"), "open pull request"),
        (lambda: pull["head"]["repo"].update(full_name="Other/repo"), "same-repository"),
        (lambda: pull["head"].update(ref="other"), "head ref moved"),
        (lambda: pull["head"].update(sha="c" * 40), "head SHA moved"),
        (lambda: pull["base"].update(ref="develop"), "base ref moved"),
        (lambda: pull["base"].update(sha="d" * 40), "base SHA moved"),
        (lambda: pull.update(changed_files="1"), "changed_files"),
    ]
    for mutate, message in cases:
        fresh = live_pull()
        pull.clear()
        pull.update(fresh)
        mutate()
        with pytest.raises(ValueError, match=message):
            worker.live_context(current)


def test_live_context_rejects_empty_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    body = "@cwl-source-fix"
    current = claim(body)
    install_live_context(monkeypatch, body)
    with pytest.raises(ValueError, match="concrete repair"):
        worker.live_context(current)


def test_checkout_target_runs_bounded_git_sequence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    current = claim()
    commands: list[list[str]] = []

    def fake_run(args, **kwargs):
        commands.append(list(args))
        if "rev-parse" in args:
            return completed(HEAD + "\n")
        return completed()

    monkeypatch.setattr(worker, "run", fake_run)
    worker.checkout_target(current, tmp_path)
    assert commands[0][:3] == ["git", "init", "-q"]
    assert ["gh", "auth", "setup-git"] in commands
    assert any("fetch" in command for command in commands)
    assert any(command[-2:] == ["user.name", "github-actions[bot]"] for command in commands)


def test_checkout_target_rejects_fetched_head_drift(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_run(args, **kwargs):
        if "rev-parse" in args:
            return completed("c" * 40 + "\n")
        return completed()

    monkeypatch.setattr(worker, "run", fake_run)
    with pytest.raises(ValueError, match="fetched PR head"):
        worker.checkout_target(claim(), tmp_path)


def test_write_and_restore_model_files_with_and_without_existing_files(tmp_path: Path) -> None:
    backups = worker._write_model_files(tmp_path, "repair", ("src/a.py",))
    assert backups == (None, None)
    config = json.loads((tmp_path / "opencode.jsonc").read_text())
    assert config["model"] == "contextual-orchestrator/orchestrator/free"
    assert config["permission"]["bash"] == "deny"
    assert "src/a.py" in (tmp_path / "source-fix-prompt.md").read_text()
    worker._restore_model_files(tmp_path, backups)
    assert not (tmp_path / "opencode.jsonc").exists()
    assert not (tmp_path / "source-fix-prompt.md").exists()

    (tmp_path / "opencode.jsonc").write_text("old-config", encoding="utf-8")
    (tmp_path / "source-fix-prompt.md").write_text("old-prompt", encoding="utf-8")
    backups = worker._write_model_files(tmp_path, "repair", ("src/a.py",))
    assert backups[0] is not None and backups[1] is not None
    worker._restore_model_files(tmp_path, backups)
    assert (tmp_path / "opencode.jsonc").read_text() == "old-config"
    assert (tmp_path / "source-fix-prompt.md").read_text() == "old-prompt"


def test_run_model_requires_orchestrator_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", raising=False)
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="base URL"):
        worker.run_model(tmp_path, "repair", ("a.py",))
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", "http://gateway")
    with pytest.raises(RuntimeError, match="token"):
        worker.run_model(tmp_path, "repair", ("a.py",))


def test_run_model_strips_repository_credentials_and_restores_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", "http://gateway")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_TOKEN", "gateway-token")
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL", "PR_REVIEW_MERGE_TOKEN", "OPENCODE_APPROVE_TOKEN"):
        monkeypatch.setenv(name, "secret")
    seen: dict[str, Any] = {}

    def fake_run(args, **kwargs):
        seen.update(kwargs)
        assert args[:2] == ["opencode", "run"]
        return completed()

    monkeypatch.setattr(worker, "run", fake_run)
    worker.run_model(tmp_path, "repair", ("src/a.py",))
    assert all(name not in seen["env"] for name in ("GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_URL", "PR_REVIEW_MERGE_TOKEN", "OPENCODE_APPROVE_TOKEN"))
    assert seen["env"]["MODEL"] == "contextual-orchestrator/orchestrator/free"
    assert not (tmp_path / "opencode.jsonc").exists()
    assert not (tmp_path / "source-fix-prompt.md").exists()


def test_run_model_restores_files_after_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", "http://gateway")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_TOKEN", "gateway-token")
    (tmp_path / "opencode.jsonc").write_text("original", encoding="utf-8")
    monkeypatch.setattr(worker, "run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("model failed")))
    with pytest.raises(RuntimeError, match="model failed"):
        worker.run_model(tmp_path, "repair", ("src/a.py",))
    assert (tmp_path / "opencode.jsonc").read_text() == "original"
    assert not (tmp_path / "source-fix-prompt.md").exists()


def test_changed_paths_combines_tracked_and_untracked(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    outputs = iter([completed("b.py\0a.py\0"), completed("c.py\0a.py\0")])
    monkeypatch.setattr(worker, "run", lambda *args, **kwargs: next(outputs))
    assert worker.changed_paths(tmp_path) == ("a.py", "b.py", "c.py")


def test_validate_changes_handles_empty_outside_python_yaml_and_other(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(worker, "changed_paths", lambda workspace: ())
    assert worker.validate_changes(tmp_path, ("a.py",)) == ()

    monkeypatch.setattr(worker, "changed_paths", lambda workspace: ("outside.py",))
    with pytest.raises(RuntimeError, match="outside authenticated"):
        worker.validate_changes(tmp_path, ("a.py",))

    for name in ("a.py", "b.yml", "c.yaml", "note.md"):
        (tmp_path / name).write_text("content", encoding="utf-8")
    monkeypatch.setattr(worker, "changed_paths", lambda workspace: ("a.py", "b.yml", "c.yaml", "note.md"))
    calls: list[list[str]] = []
    monkeypatch.setattr(worker, "run", lambda args, **kwargs: calls.append(list(args)) or completed())
    assert worker.validate_changes(tmp_path, ("a.py", "b.yml", "c.yaml", "note.md")) == ("a.py", "b.yml", "c.yaml", "note.md")
    assert ["git", "diff", "--check"] in calls
    assert any(command[:3] == ["python3", "-m", "py_compile"] for command in calls)
    assert any(command[:2] == ["ruby", "-e"] for command in calls)

    monkeypatch.setattr(worker, "changed_paths", lambda workspace: ("note.md",))
    calls.clear()
    assert worker.validate_changes(tmp_path, ("note.md",)) == ("note.md",)
    assert calls == [["git", "diff", "--check"]]


def test_validate_changes_ignores_deleted_python_and_yaml_for_syntax(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(worker, "changed_paths", lambda workspace: ("gone.py", "gone.yml"))
    calls: list[list[str]] = []
    monkeypatch.setattr(worker, "run", lambda args, **kwargs: calls.append(list(args)) or completed())
    assert worker.validate_changes(tmp_path, ("gone.py", "gone.yml")) == ("gone.py", "gone.yml")
    assert calls == [["git", "diff", "--check"]]


def test_post_result_is_best_effort(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(worker, "run", lambda args, **kwargs: calls.append((args, kwargs)) or completed())
    worker._post_result("repo", 1, "body")
    assert json.loads(calls[0][1]["input_text"]) == {"body": "body"}
    monkeypatch.setattr(worker, "run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret")))
    monkeypatch.setattr(worker, "_safe_error", lambda exc, limit=1200: "safe")
    worker._post_result("repo", 1, "body")
    output = capsys.readouterr().out
    assert "warning" in output and "safe" in output


def install_execute(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, paths: tuple[str, ...]) -> tuple[dict[str, object], list[str]]:
    current = claim()
    monkeypatch.setattr(worker, "validate_static_inputs", lambda: current)
    monkeypatch.setattr(worker, "live_context", lambda value: ("repair", ("src/a.py",)))
    monkeypatch.setattr(worker.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    monkeypatch.setattr(worker, "checkout_target", lambda value, workspace: None)
    monkeypatch.setattr(worker, "run_model", lambda workspace, instruction, allowed: None)
    monkeypatch.setattr(worker, "validate_changes", lambda workspace, allowed: paths)
    monkeypatch.setattr(worker.shutil, "rmtree", lambda *args, **kwargs: None)
    comments: list[str] = []
    monkeypatch.setattr(worker, "_post_result", lambda repository, pr_number, body: comments.append(body))
    return current, comments


def test_execute_noop_posts_result_without_commit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, comments = install_execute(monkeypatch, tmp_path, ())
    assert worker.execute() == 0
    assert "without a repository edit" in comments[-1]


def test_execute_pushes_bounded_commit_on_unchanged_head(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    current, comments = install_execute(monkeypatch, tmp_path, ("src/a.py",))
    monkeypatch.setattr(worker, "_pull_request", lambda repository, pr_number: {"head": {"sha": HEAD}})
    commands: list[list[str]] = []

    def fake_run(args, **kwargs):
        commands.append(list(args))
        if args[-2:] == ["rev-parse", "HEAD"]:
            return completed("d" * 40 + "\n")
        return completed()

    monkeypatch.setattr(worker, "run", fake_run)
    assert worker.execute() == 0
    assert any("commit" in command for command in commands)
    assert any("push" in command for command in commands)
    assert "d" * 40 in comments[-1]
    assert "src/a.py" in comments[-1]
    assert current["head_ref"] == "fix/current-pr"


def test_execute_fails_closed_if_head_moves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, comments = install_execute(monkeypatch, tmp_path, ("src/a.py",))
    monkeypatch.setattr(worker, "_pull_request", lambda repository, pr_number: {"head": {"sha": "c" * 40}})
    with pytest.raises(RuntimeError, match="head moved"):
        worker.execute()
    assert "failed closed" in comments[-1]


def test_execute_reports_model_failure_and_reraises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, comments = install_execute(monkeypatch, tmp_path, ())
    monkeypatch.setattr(worker, "run_model", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("model failed")))
    monkeypatch.setattr(worker, "_safe_error", lambda exc, limit=1200: "safe failure")
    with pytest.raises(RuntimeError, match="model failed"):
        worker.execute()
    assert "safe failure" in comments[-1]


def test_main_validate_only_and_execute(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(worker, "validate_static_inputs", lambda: claim())
    assert worker.main(["--validate-only"]) == 0
    assert "claim is valid" in capsys.readouterr().out
    monkeypatch.setattr(worker, "execute", lambda: 17)
    assert worker.main([]) == 17
