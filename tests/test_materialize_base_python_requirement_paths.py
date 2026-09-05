"""Regression contracts for repository-relative requirements lock discovery."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.ci import materialize_base_python_requirements as materializer


def _git(repo: Path, *args: str) -> str:
    """Run one deterministic Git command in the fixture repository."""
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class BaseHashLockPathTests(unittest.TestCase):
    """Protect direct ``requirements`` directory child discovery."""

    def test_collects_hash_locks_under_any_requirements_directory(self) -> None:
        """Use the complete repository-relative path, not only the basename."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            _git(repo, "init")
            _git(repo, "config", "user.name", "Test")
            _git(repo, "config", "user.email", "test@example.invalid")

            root_requirements = repo / "requirements"
            nested_requirements = repo / "service" / "requirements"
            root_requirements.mkdir()
            nested_requirements.mkdir(parents=True)
            (root_requirements / "ci.txt").write_text(
                "ci-demo==1 --hash=sha256:" + ("a" * 64) + "\n",
                encoding="utf-8",
            )
            (nested_requirements / "package.txt").write_text(
                "service-demo==1 --hash=sha256:" + ("b" * 64) + "\n",
                encoding="utf-8",
            )
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "base")
            base_sha = _git(repo, "rev-parse", "HEAD")

            locks = materializer.base_hash_locks(repo, base_sha)

            self.assertEqual(
                [path for path, _content in locks],
                [
                    "requirements/ci.txt",
                    "service/requirements/package.txt",
                ],
            )


if __name__ == "__main__":
    unittest.main()
