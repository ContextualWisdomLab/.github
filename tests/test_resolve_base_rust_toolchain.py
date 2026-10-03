"""The coverage image installs only an exact Rust release pinned on the trusted base."""

from __future__ import annotations

<<<<<<< HEAD
import subprocess
=======
import runpy
import subprocess
import sys
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)
from pathlib import Path

import pytest

from scripts.ci import resolve_base_rust_toolchain as resolver


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, files: dict[str, str]) -> str:
    if not (repo / ".git").exists():
        repo.mkdir(parents=True, exist_ok=True)
        _git(repo, "init", "-q")
        _git(repo, "config", "user.name", "Test")
        _git(repo, "config", "user.email", "test@example.invalid")
    for name, content in files.items():
        (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "fixture")
    return _git(repo, "rev-parse", "HEAD")


def test_unpinned_base_keeps_the_distribution_toolchain(tmp_path: Path) -> None:
    base = _commit(tmp_path, {"README.md": "no pin\n"})
    assert resolver.resolve(tmp_path, base) == ""


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("rust-toolchain.toml", '[toolchain]\nchannel = "1.97.1"\nprofile = "minimal"\n'),
        ("rust-toolchain", "1.97.1\n"),
        ("rust-toolchain", '[toolchain]\nchannel = "1.97.1"\n'),
    ],
)
def test_exact_base_release_is_selected(tmp_path: Path, name: str, content: str) -> None:
    base = _commit(tmp_path, {name: content})
    assert resolver.resolve(tmp_path, base) == "1.97.1"


@pytest.mark.parametrize(
    "content",
    [
        '[toolchain]\nchannel = "stable"\n',
        '[toolchain]\nchannel = "nightly-2026-09-01"\n',
        '[toolchain]\nchannel = "1.97"\n',
        '[toolchain]\nchannel = "1.97.1; curl evil"\n',
        '[toolchain]\nchannel = "../../evil"\n',
        '[toolchain]\npath = "/opt/custom"\nchannel = "1.97.1"\n',
        "[toolchain\n",
        "",
    ],
)
def test_unsupported_base_pins_fall_back_to_the_central_release(
    tmp_path: Path, content: str
) -> None:
    base = _commit(tmp_path, {"rust-toolchain.toml": content})
    assert resolver.resolve(tmp_path, base) == resolver.CENTRAL_RUST_TOOLCHAIN


def test_pull_request_head_pin_is_ignored(tmp_path: Path) -> None:
    base = _commit(tmp_path, {"rust-toolchain.toml": '[toolchain]\nchannel = "1.97.1"\n'})
    _commit(tmp_path, {"rust-toolchain.toml": '[toolchain]\nchannel = "1.80.0"\n'})
    assert resolver.resolve(tmp_path, base) == "1.97.1"


def test_invalid_base_sha_is_rejected(tmp_path: Path) -> None:
    _commit(tmp_path, {"README.md": "x\n"})
    with pytest.raises(ValueError):
        resolver.resolve(tmp_path, "HEAD")


def test_central_release_is_itself_exact() -> None:
    assert resolver.EXACT_RELEASE_RE.fullmatch(resolver.CENTRAL_RUST_TOOLCHAIN)
<<<<<<< HEAD
=======


def test_cli_prints_resolved_release_and_rejects_untrusted_sha(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """The CLI prints a trusted-base pin and reports malformed revision input."""

    base = _commit(tmp_path, {"rust-toolchain": "1.97.1\n"})
    assert resolver.main(["--repo-root", str(tmp_path), "--base-sha", base]) == 0
    assert capsys.readouterr().out == "1.97.1\n"

    assert resolver.main(["--repo-root", str(tmp_path), "--base-sha", "HEAD"]) == 1
    assert "base SHA must be" in capsys.readouterr().err


def test_script_entrypoint_uses_the_trusted_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """The executable script resolves and prints the exact base-commit toolchain."""

    base = _commit(tmp_path, {"rust-toolchain.toml": '[toolchain]\nchannel = "1.97.1"\n'})
    _commit(tmp_path, {"rust-toolchain.toml": '[toolchain]\nchannel = "1.80.0"\n'})
    script = Path(resolver.__file__)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(script), "--repo-root", str(tmp_path), "--base-sha", base],
    )

    with pytest.raises(SystemExit) as exited:
        runpy.run_path(str(script), run_name="__main__")

    assert exited.value.code == 0
    assert capsys.readouterr().out == "1.97.1\n"
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)
