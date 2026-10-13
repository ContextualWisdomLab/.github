"""정확한 공개 Git 객체만 자격증명 없는 merge tree로 재구성한다."""
from __future__ import annotations

import importlib
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _module():
    """구현 전에도 collection이 아닌 원하는 assertion으로 RED를 만든다."""
    assert (ROOT / "scripts/ci/materialize_public_review_source.py").is_file(), "trusted public materializer missing"
    return importlib.import_module("scripts.ci.materialize_public_review_source")


def _git(path: Path, *args: str) -> str:
    """실제 합성 저장소 명령을 실행한다."""
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("GIT_") and key not in ("GH_TOKEN", "GITHUB_TOKEN", "BASH_ENV", "HTTPS_PROXY")}
    result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True,
                            check=False, env=environment)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def history(tmp_path: Path):
    """서로 독립적인 base/head와 완전한 실제 Git history를 만든다."""
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-q")
    _git(source, "config", "user.email", "fixture@example.invalid")
    _git(source, "config", "user.name", "Synthetic fixture")
    (source / "normal file.txt").write_text("root\n")
    _git(source, "add", ".")
    _git(source, "commit", "-qm", "root")
    root = _git(source, "rev-parse", "HEAD")
    _git(source, "checkout", "-qb", "base")
    (source / "base.txt").write_text("base\n")
    _git(source, "add", ".")
    _git(source, "commit", "-qm", "base")
    base = _git(source, "rev-parse", "HEAD")
    _git(source, "checkout", "-qb", "head", root)
    (source / "head.txt").write_text("head\n")
    _git(source, "add", ".")
    _git(source, "commit", "-qm", "head")
    head = _git(source, "rev-parse", "HEAD")
    temp = tmp_path / "runner-temp"
    temp.mkdir()
    return source, root, base, head, temp


def _runner(source: Path, seen: list):
    """HTTPS network만 로컬 fixture로 치환하며 실제 Git 동작은 유지한다."""
    def execute(argv, **kwargs):
        seen.append((list(argv), dict(kwargs["env"])))
        local = list(argv)
        if "fetch" in local:
            index = local.index("https://github.com/ContextualWisdomLab/example.git")
            local[index] = str(source)
            local[1:1] = ["-c", "protocol.file.allow=always"]
        return subprocess.run(local, **kwargs)
    return execute


def _materialize(history, **overrides):
    """정상 public 입력과 실제 Git 경계로 helper를 실행한다."""
    source, root, base, head, temp = history
    seen = []
    values = dict(repository="ContextualWisdomLab/example", base_sha=base, head_sha=head,
                  is_private="false", runner_temp=temp, run_id="123", run_attempt="1",
                  git_executable=Path(shutil.which("git")), runner=_runner(source, seen))
    values.update(overrides)
    return _module().materialize_public_source(**values), seen


def test_public_materialization_preserves_tree_history_and_uses_no_credentials(history, monkeypatch):
    """정상 tree는 같고 runner credential·Git config는 child로 전달되지 않는다."""
    source, root, base, head, temp = history
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN", "GITHUB_CONTEXT_JSON",
                 "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0", "GIT_DIR",
                 "GIT_CONFIG_PARAMETERS", "GIT_ASKPASS", "BASH_ENV", "PYTHONPATH", "HTTPS_PROXY"):
        monkeypatch.setenv(name, "synthetic-poison")
    output, seen = _materialize(history)
    assert output == temp / "opencode-coverage-123-1"
    expected = _git(source, "merge-tree", "--write-tree", base, head).splitlines()[0]
    assert _git(output, "rev-parse", "HEAD^{tree}") == expected
    assert _git(output, "cat-file", "-t", root) == "commit"
    assert _git(output, "merge-base", base, head) == root
    assert _git(output, "show", "HEAD:normal file.txt") == "root"
    assert _git(output, "config", "--local", "core.hooksPath") == "/dev/null"
    assert "https://github.com/ContextualWisdomLab/example.git" in seen[1][0]
    for argv, env in seen:
        assert not any("TOKEN" in key or "KEY" in key or key in ("GIT_DIR", "GIT_CONFIG_COUNT", "BASH_ENV", "PYTHONPATH", "HTTPS_PROXY", "GITHUB_CONTEXT_JSON") for key in env)
        assert "synthetic-poison" not in str(env) + str(argv)
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert "http.followRedirects=false" in argv
        assert "protocol.https.allow=always" in argv


@pytest.mark.parametrize("value", ["true", "", "unknown", "False", "0"])
def test_non_public_visibility_stops_before_fetch(history, value):
    """False 문자열 이외 입력은 경로 생성이나 fetch를 허용하지 않는다."""
    with pytest.raises(_module().MaterializationError, match="public visibility"):
        _materialize(history, is_private=value)
    assert not list(history[-1].iterdir())


@pytest.mark.parametrize("value", ["../example", "org/../repo", "org/repo/other", "org/r\n", "-evil/repo", "org/..", "https://github.com/org/repo", "org/r%2f", "org/r?token=x", "org/r#x"])
def test_invalid_repository_stops_before_fetch(history, value):
    """경로·옵션·URL·record injection을 API 경계에서 거부한다."""
    with pytest.raises(_module().MaterializationError, match="repository"):
        _materialize(history, repository=value)
    assert not list(history[-1].iterdir())


@pytest.mark.parametrize("field,value", [("base_sha", "a" * 39), ("head_sha", "a" * 40 + "\n"), ("head_sha", "A" * 40), ("base_sha", "--upload-pack=evil")])
def test_invalid_sha_stops_before_fetch(history, field, value):
    """오직 정확한 lowercase commit SHA만 허용한다."""
    with pytest.raises(_module().MaterializationError, match="commit SHA"):
        _materialize(history, **{field: value})
    assert not list(history[-1].iterdir())


def test_existing_output_is_not_deleted(history):
    """외부가 만든 destination을 정상화 명목으로 지우지 않는다."""
    output = history[-1] / "opencode-coverage-123-1"
    output.mkdir()
    (output / "sentinel").write_text("foreign")
    with pytest.raises(_module().MaterializationError, match="output"):
        _materialize(history)
    assert (output / "sentinel").read_text() == "foreign"


def test_symlinked_temp_is_rejected(history, tmp_path):
    """Runner temp의 symlink를 따라 외부 output을 생성하지 않는다."""
    alias = tmp_path / "alias"
    alias.symlink_to(history[-1], target_is_directory=True)
    with pytest.raises(_module().MaterializationError, match="temporary root"):
        _materialize(history, runner_temp=alias)
    assert not list(history[-1].iterdir())


def test_fetch_failure_cleans_only_owned_output(history):
    """인증·이동 ref fallback 없이 실패를 전달하고 외부 파일을 보존한다."""
    temp = history[-1]
    sentinel = temp / "other-job"
    sentinel.write_text("foreign")
    def fail(argv, **kwargs):
        if "fetch" in argv:
            return subprocess.CompletedProcess(argv, 1, b"", b"synthetic-secret")
        return subprocess.run(argv, **kwargs)
    with pytest.raises(_module().MaterializationError, match="git command failed") as error:
        _materialize(history, runner=fail)
    assert "synthetic-secret" not in str(error.value)
    assert sentinel.read_text() == "foreign"
    assert not (temp / "opencode-coverage-123-1").exists()


def test_tracked_symlink_is_rejected_before_checkout(history):
    """Direct fetch도 기존 archive의 symlink 거부를 보존한다."""
    source, root, base, head, temp = history
    (source / "escape").symlink_to("../../outside")
    _git(source, "add", "escape")
    _git(source, "commit", "-qm", "symlink")
    with pytest.raises(_module().MaterializationError, match="source entry"):
        _materialize(history, head_sha=_git(source, "rev-parse", "HEAD"))
    assert not list(temp.iterdir())


@pytest.mark.parametrize("pair", ["equal", "ancestor", "merge-head"])
def test_existing_merge_semantics_are_preserved(history, pair):
    """base==head·ancestor·merge commit도 기존 merge tree 의미를 유지한다."""
    source, root, base, head, temp = history
    if pair == "equal":
        head = base
    elif pair == "ancestor":
        head = root
    else:
        _git(source, "merge", "--no-ff", "--no-edit", base)
        head = _git(source, "rev-parse", "HEAD")
    output, _ = _materialize(history, head_sha=head)
    if pair in ("equal", "ancestor"):
        assert _git(output, "rev-parse", "HEAD") == base
    else:
        assert _git(output, "rev-parse", "HEAD^{tree}") == _git(source, "rev-parse", "HEAD^{tree}")


@pytest.mark.parametrize("name,value", [("run_id", "0"), ("run_attempt", "1\n"), ("run_id", "../x")])
def test_invalid_run_identity(history, name, value):
    """소유 output 이름은 검증된 숫자 run/attempt로만 구성한다."""
    with pytest.raises(_module().MaterializationError, match="run identity"):
        _materialize(history, **{name: value})


@pytest.mark.parametrize("path", ["relative", "/does-not-exist/git"])
def test_invalid_git_binary(history, path):
    """PATH의 임의 바이너리를 production에서 고르지 않는다."""
    with pytest.raises(_module().MaterializationError, match="git executable"):
        _materialize(history, git_executable=Path(path))


@pytest.mark.parametrize("root", [Path("relative"), Path("/tmp/line\nbreak"), Path("/")])
def test_unsafe_root_is_rejected_before_output(root):
    """상대 경로, 레코드 삽입, 전역 root를 거부한다."""
    with pytest.raises(_module().MaterializationError, match="temporary root"):
        _module()._temporary_root(root)


def test_shared_writable_temp_is_rejected(history):
    """다른 사용자에게 쓰기가 허용된 runner temp를 거부한다."""
    history[-1].chmod(0o777)
    with pytest.raises(_module().MaterializationError, match="temporary root"):
        _materialize(history)


@pytest.mark.parametrize("inventory", [b"broken\0", b"100644 blob a\t\xff\0", b"100644 blob a\t../outside\0", b"160000 commit a\tmodule\0", b"100644 blob a\t.GIT/config\0", b"100644 blob a\ta\\b\0", b"100644 blob a\ta\nb\0"])
def test_invalid_tree_inventory_is_closed(inventory):
    """기존 tar 경계와 동일하게 malformed·gitlink·위험 경로를 거부한다."""
    with pytest.raises(_module().MaterializationError, match="source entry"):
        _module()._admit_entries(inventory)


@pytest.mark.parametrize("error", [OSError("synthetic-secret"), subprocess.TimeoutExpired("git", 300)])
def test_git_start_and_deadline_errors_are_sanitized(history, error):
    """프로세스 시작 실패와 timeout도 정리 후 고정 오류만 반환한다."""
    def broken(*args, **kwargs):
        raise error
    with pytest.raises(_module().MaterializationError, match="git command failed") as caught:
        _materialize(history, runner=broken)
    assert "synthetic-secret" not in str(caught.value)
    assert not list(history[-1].iterdir())


@pytest.mark.parametrize("failure", ["type", "oid"])
def test_fetched_objects_must_match_exact_commit(history, failure):
    """부정확한 객체종류나 확인된 SHA 불일치는 checkout 전에 거부한다."""
    real = _runner(history[0], [])
    def wrong(argv, **kwargs):
        if failure == "type" and "cat-file" in argv:
            return subprocess.CompletedProcess(argv, 0, b"tag\n", b"")
        if failure == "oid" and "rev-parse" in argv:
            return subprocess.CompletedProcess(argv, 0, b"0" * 40 + b"\n", b"")
        return real(argv, **kwargs)
    with pytest.raises(_module().MaterializationError, match="commit object"):
        _materialize(history, runner=wrong)
    assert not list(history[-1].iterdir())


def test_merge_conflict_is_not_reported_as_materialized(history):
    """충돌을 덮어쓰거나 HEAD-only로 fallback하지 않는다."""
    source, root, base, head, temp = history
    (source / "base.txt").write_text("conflicting\n")
    _git(source, "add", ".")
    _git(source, "commit", "-qm", "conflict")
    with pytest.raises(_module().MaterializationError, match="git command failed"):
        _materialize(history, head_sha=_git(source, "rev-parse", "HEAD"))
    assert not list(temp.iterdir())


def test_source_hook_and_filter_are_not_executed(history, tmp_path, monkeypatch):
    """호스트 global config와 template의 executable hook을 거부한다."""
    source, root, base, head, temp = history
    hosthome = tmp_path / "host-home"
    hosthome.mkdir()
    marker = tmp_path / "must-not-exist"
    hooks = hosthome / "templates/hooks"
    hooks.mkdir(parents=True)
    hook = hooks / "post-checkout"
    hook.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
    hook.chmod(0o755)
    (hosthome / ".gitconfig").write_text(
        f'[init]\n templateDir = {hooks.parent}\n[core]\n hooksPath = {hooks}\n'
        f'[filter "trap"]\n smudge = touch {marker}\n required = true\n'
        f'[url "file:///unavailable/"]\n insteadOf = https://github.com/\n')
    (source / ".gitattributes").write_text("*.txt filter=trap\n")
    _git(source, "add", ".gitattributes")
    _git(source, "commit", "-qm", "filter attributes")
    head = _git(source, "rev-parse", "HEAD")
    monkeypatch.setenv("HOME", str(hosthome))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(hosthome / ".gitconfig"))
    output, _ = _materialize(history, head_sha=head)
    assert (output / "head.txt").read_text() == "head\n"
    assert not marker.exists()


def test_replaced_output_is_preserved_on_failure(history, tmp_path):
    """실패 시 처음 소유한 inode가 아닌 교체 symlink를 삭제하지 않는다."""
    outside = tmp_path / "foreign"
    outside.mkdir()
    (outside / "sentinel").write_text("keep")
    def replaced(argv, **kwargs):
        output = kwargs["cwd"]
        output.rmdir()
        output.symlink_to(outside, target_is_directory=True)
        return subprocess.CompletedProcess(argv, 1, b"", b"")
    with pytest.raises(_module().MaterializationError):
        _materialize(history, runner=replaced)
    assert (outside / "sentinel").read_text() == "keep"
    assert (history[-1] / "opencode-coverage-123-1").is_symlink()


def test_main_reports_success_and_failure_without_sensitive_output(history, monkeypatch, capsys):
    """CLI 성공·고정 실패 메시지는 별도 entrypoint 계약으로 검사한다."""
    module = _module()
    args = ["--repository", "ContextualWisdomLab/example", "--base-sha", history[2],
            "--head-sha", history[3], "--is-private", "false"]
    monkeypatch.setenv("RUNNER_TEMP", str(history[-1]))
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    real = module.materialize_public_source
    def local(**kwargs):
        return real(**kwargs, git_executable=Path(shutil.which("git") or "/usr/bin/git"),
                    runner=_runner(history[0], []))
    monkeypatch.setattr(module, "materialize_public_source", local)
    assert module.main(args) == 0
    assert "without credentials or artifacts" in capsys.readouterr().out
    assert module.main(args) == 1
    assert capsys.readouterr().out == "::error::Public review source materialization refused.\n"


def test_module_entrypoint_runs_fail_closed(monkeypatch):
    """실제 __main__ 경로도 invalid tuple을 성공으로 바꾸지 않는다."""
    import runpy
    import sys
    monkeypatch.setattr(sys, "argv", ["materializer", "--repository", "bad", "--base-sha", "a" * 40,
                                     "--head-sha", "b" * 40, "--is-private", "false"])
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(ROOT / "scripts/ci/materialize_public_review_source.py"), run_name="__main__")
    assert caught.value.code == 1
