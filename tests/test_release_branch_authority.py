"""Release admission distinguishes protected production lineage from the default branch."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci.release_branch_authority import (
    ReleaseBranchAuthorityError,
    admit_protected_production_lineage,
    evaluate_release_authority,
    main,
    production_remote_tip,
    resolve_production_branch,
)

MAIN_TIP = "a" * 40
OTHER_TIP = "b" * 40


def _git(repo: Path, *args: str) -> str:
    """Run one git command in ``repo`` and return stdout."""

    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    """Create a repository with a local identity and no remotes."""

    repo = tmp_path / "consumer"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(repo, "config", "user.email", "release-authority@example.com")
    _git(repo, "config", "user.name", "Release Authority Test")
    return repo


def _commit(repo: Path, filename: str, body: str) -> str:
    """Write ``filename``, commit it, and return the new HEAD."""

    (repo / filename).write_text(body + "\n", encoding="utf-8")
    _git(repo, "add", filename)
    _git(repo, "commit", "-m", body)
    return _git(repo, "rev-parse", "HEAD")


def _git_flow_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """Return a repo whose ``develop`` tip is not on protected ``main``."""

    repo = _init_repo(tmp_path)
    main_tip = _commit(repo, "README.md", "production")
    _git(repo, "update-ref", "refs/remotes/origin/main", main_tip)
    _git(repo, "checkout", "-b", "develop")
    develop_tip = _commit(repo, "feature.txt", "integration only")
    _git(repo, "update-ref", "refs/remotes/origin/develop", develop_tip)
    return repo, main_tip, develop_tip


def test_github_flow_uses_default_main_as_production_authority() -> None:
    """A protected default ``main`` is production authority without an extra input."""

    assert resolve_production_branch("main", "") == "main"
    assert resolve_production_branch("master", "") == "master"


def test_git_flow_requires_explicit_production_branch() -> None:
    """``develop`` as the default branch is not production authority."""

    with pytest.raises(
        ReleaseBranchAuthorityError,
        match="production branch authority is required",
    ):
        resolve_production_branch("develop", "")


def test_explicit_production_branch_must_be_main_or_master() -> None:
    """Callers cannot rename the integration branch into production authority."""

    assert resolve_production_branch("develop", "main") == "main"
    assert resolve_production_branch("develop", "master") == "master"
    with pytest.raises(ReleaseBranchAuthorityError, match="main or master"):
        resolve_production_branch("develop", "develop")
    with pytest.raises(ReleaseBranchAuthorityError, match="safe ref component"):
        resolve_production_branch("../main", "")
    with pytest.raises(ReleaseBranchAuthorityError, match="safe ref component"):
        resolve_production_branch("feature/../main", "")
    with pytest.raises(ReleaseBranchAuthorityError, match="safe ref component"):
        resolve_production_branch("main@{1}", "")
    with pytest.raises(ReleaseBranchAuthorityError, match="safe ref component"):
        resolve_production_branch("", "")
    with pytest.raises(ReleaseBranchAuthorityError, match="safe ref component"):
        resolve_production_branch("develop", "main\n")


def test_unprotected_or_off_lineage_commits_fail_closed() -> None:
    """Protection and production ancestry are both required."""

    with pytest.raises(ReleaseBranchAuthorityError, match="not protected"):
        admit_protected_production_lineage(
            production_branch="main",
            release_commit=MAIN_TIP,
            production_tip=MAIN_TIP,
            production_protected=False,
            release_is_ancestor_of_production_tip=True,
        )
    with pytest.raises(ReleaseBranchAuthorityError, match="ancestor of the protected production"):
        admit_protected_production_lineage(
            production_branch="main",
            release_commit=OTHER_TIP,
            production_tip=MAIN_TIP,
            production_protected=True,
            release_is_ancestor_of_production_tip=False,
        )
    with pytest.raises(ReleaseBranchAuthorityError, match="40-character"):
        admit_protected_production_lineage(
            production_branch="main",
            release_commit="abc",
            production_tip=MAIN_TIP,
            production_protected=True,
            release_is_ancestor_of_production_tip=True,
        )
    with pytest.raises(ReleaseBranchAuthorityError, match="not a boolean"):
        admit_protected_production_lineage(
            production_branch="main",
            release_commit=MAIN_TIP,
            production_tip=MAIN_TIP,
            production_protected="true",  # type: ignore[arg-type]
            release_is_ancestor_of_production_tip=True,
        )
    with pytest.raises(ReleaseBranchAuthorityError, match="main or master"):
        admit_protected_production_lineage(
            production_branch="develop",
            release_commit=MAIN_TIP,
            production_tip=MAIN_TIP,
            production_protected=True,
            release_is_ancestor_of_production_tip=True,
        )
    admit_protected_production_lineage(
        production_branch="main",
        release_commit=MAIN_TIP,
        production_tip=MAIN_TIP,
        production_protected=True,
        release_is_ancestor_of_production_tip=True,
    )


def test_git_flow_rejects_develop_only_ancestry(tmp_path: Path) -> None:
    """A commit that exists only on ``develop`` cannot be released."""

    repo, _main_tip, develop_tip = _git_flow_repo(tmp_path)
    with pytest.raises(
        ReleaseBranchAuthorityError,
        match="ancestor of the protected production branch",
    ):
        evaluate_release_authority(
            repo,
            default_branch="develop",
            production_branch="main",
            release_commit=develop_tip,
            production_protected=True,
        )


def test_git_flow_admits_commit_on_protected_main(tmp_path: Path) -> None:
    """The same repository admits the commit that is on protected ``main``."""

    repo, main_tip, _develop_tip = _git_flow_repo(tmp_path)
    assert (
        evaluate_release_authority(
            repo,
            default_branch="develop",
            production_branch="main",
            release_commit=main_tip,
            production_protected=True,
        )
        == "main"
    )


def test_github_flow_admits_ancestor_of_default_main(tmp_path: Path) -> None:
    """GitHub Flow stays valid when the default branch is protected ``main``."""

    repo = _init_repo(tmp_path)
    main_tip = _commit(repo, "README.md", "production")
    _git(repo, "update-ref", "refs/remotes/origin/main", main_tip)
    assert (
        evaluate_release_authority(
            repo,
            default_branch="main",
            production_branch="",
            release_commit=main_tip,
            production_protected=True,
        )
        == "main"
    )


def test_non_sha_production_tip_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful rev-parse that is not 40 lowercase hex is not a tip."""

    repo = _init_repo(tmp_path)

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if "rev-parse" in command:
            return subprocess.CompletedProcess(command, 0, stdout="not-a-sha\n", stderr="")
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ReleaseBranchAuthorityError, match="production tip is unavailable"):
        production_remote_tip(repo, "main")


def test_cli_requires_a_boolean_protection_flag(capsys: pytest.CaptureFixture[str]) -> None:
    """Admission without a true/false protection flag fails closed."""

    assert (
        main(
            [
                "--default-branch",
                "main",
                "--production-branch",
                "",
                "--release-commit",
                "d" * 40,
            ]
        )
        == 1
    )
    assert "not a boolean" in capsys.readouterr().err


def test_missing_production_tip_and_non_production_ref_fail_closed(tmp_path: Path) -> None:
    """Authority cannot be inferred from a missing tip or from ``develop``."""

    repo = _init_repo(tmp_path)
    _commit(repo, "README.md", "production")
    with pytest.raises(ReleaseBranchAuthorityError, match="production tip is unavailable"):
        evaluate_release_authority(
            repo,
            default_branch="main",
            production_branch="",
            release_commit="c" * 40,
            production_protected=True,
        )
    with pytest.raises(ReleaseBranchAuthorityError, match="main or master"):
        production_remote_tip(repo, "develop")


def test_cli_prints_resolved_branch_or_the_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The workflow entrypoint resolves GitHub Flow and rejects develop-only ancestry."""

    assert main(["--resolve-only", "--default-branch", "main", "--production-branch", ""]) == 0
    assert capsys.readouterr().out.strip() == "main"

    assert main(["--resolve-only", "--default-branch", "develop", "--production-branch", ""]) == 1
    assert "production branch authority is required" in capsys.readouterr().err

    repo, main_tip, develop_tip = _git_flow_repo(tmp_path)
    assert (
        main(
            [
                "--repo",
                str(repo),
                "--default-branch",
                "main",
                "--production-branch",
                "",
                "--release-commit",
                main_tip,
                "--protected",
                "true",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "--repo",
                str(repo),
                "--default-branch",
                "develop",
                "--production-branch",
                "main",
                "--release-commit",
                develop_tip,
                "--protected",
                "false",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out.strip() == "main"
    assert "not protected" in captured.err
