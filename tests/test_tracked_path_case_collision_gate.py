"""Tests for the tracked-path case-collision gate."""

from __future__ import annotations

import subprocess

import pytest

from scripts.ci import tracked_path_case_collision_gate as gate


def test_find_case_collisions_reports_directory_and_file_collisions():
    """Paths that differ only by case collide at the directory or file level."""
    paths = [".jules/bolt.md", ".jules/palette.md", ".Jules/palette.md", "README.md", "docs/Readme.md"]

    collisions = gate.find_case_collisions(paths)

    assert collisions == {
        ".jules": [".Jules", ".jules"],
        ".jules/palette.md": [".Jules/palette.md", ".jules/palette.md"],
    }


def test_find_case_collisions_accepts_clean_tree_and_unicode_casefold():
    """A clean tree yields nothing; non-ASCII case pairs are folded too."""
    assert gate.find_case_collisions(["a/b.txt", "a/c.txt", "docs/Readme.md", ""]) == {}
    assert gate.find_case_collisions(["Straße.md", "STRASSE.md"]) == {"strasse.md": ["STRASSE.md", "Straße.md"]}


def test_tracked_paths_reads_git_ls_files(tmp_path):
    """Tracked paths come from the checkout, including nested directories."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "sub/a.txt"], check=True)

    assert gate.tracked_paths(tmp_path) == ["sub/a.txt"]


@pytest.mark.parametrize(
    ("lines", "expected"),
    [("a.md\nb.md\n", 0), ("x/A.md\nx/a.md\n", gate.COLLISION)],
)
def test_main_exit_codes_from_paths_file(tmp_path, capsys, lines, expected):
    """Exit 0 on a clean list and 1 with an ::error:: annotation on a collision."""
    paths_file = tmp_path / "paths.txt"
    paths_file.write_text(lines, encoding="utf-8")

    assert gate.main(["--paths-file", str(paths_file)]) == expected
    captured = capsys.readouterr()
    assert ("::error::" in captured.out) == (expected == gate.COLLISION)


def test_main_fails_closed_when_paths_cannot_be_read(tmp_path, capsys):
    """An unreadable path list is a tool error, never a pass."""
    assert gate.main(["--paths-file", str(tmp_path / "missing.txt")]) == gate.TOOL_ERROR
    assert "could not read" in capsys.readouterr().err
    assert gate.main(["--repo-root", str(tmp_path)]) == gate.TOOL_ERROR
