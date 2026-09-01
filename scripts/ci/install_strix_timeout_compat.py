#!/usr/bin/env python3
"""Install the reviewed Strix timeout launcher into the pinned scripts root."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import hashlib
import hmac
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile


class CompatibilityInstallError(RuntimeError):
    """Raised when trusted Strix executable evidence is missing or inconsistent."""


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one regular file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def required_environment(environ: Mapping[str, str], name: str) -> str:
    """Read one non-empty installer input or fail with its exact missing name."""
    value = environ.get(name, "")
    if not value:
        raise CompatibilityInstallError(f"{name} is required for Strix compatibility.")
    return value


def install_compatibility_launcher(
    *,
    environ: Mapping[str, str] = os.environ,
    source_path: Path | None = None,
) -> Path | None:
    """Install an atomic launcher only for the GitHub Actions Strix consumer."""
    if environ.get("GITHUB_ACTIONS") != "true" or not environ.get(
        "STRIX_EXECUTABLE_PATH"
    ):
        return None

    executable = Path(required_environment(environ, "STRIX_EXECUTABLE_PATH"))
    scripts_root = Path(required_environment(environ, "STRIX_EXECUTABLE_ROOT"))
    expected_digest = required_environment(environ, "STRIX_EXECUTABLE_SHA256").lower()
    github_env = Path(required_environment(environ, "GITHUB_ENV"))
    launcher_source = source_path or Path(__file__).with_name("strix_timeout_compat.py")

    if executable.is_symlink() or launcher_source.is_symlink() or github_env.is_symlink():
        raise CompatibilityInstallError("Strix compatibility inputs must not be symlinks.")

    try:
        resolved_root = scripts_root.resolve(strict=True)
        resolved_executable = executable.resolve(strict=True)
        resolved_source = launcher_source.resolve(strict=True)
        resolved_github_env = github_env.resolve(strict=True)
        resolved_executable.relative_to(resolved_root)
    except (OSError, ValueError) as exc:
        raise CompatibilityInstallError(
            "Strix compatibility inputs must resolve inside the pinned scripts root."
        ) from exc

    if not resolved_root.is_dir() or not resolved_executable.is_file():
        raise CompatibilityInstallError("Pinned Strix executable evidence is not regular.")
    if not resolved_source.is_file() or not resolved_github_env.is_file():
        raise CompatibilityInstallError(
            "Compatibility source and GITHUB_ENV must be regular files."
        )
    if not os.access(resolved_executable, os.X_OK):
        raise CompatibilityInstallError("Pinned Strix executable is not executable.")
    if resolved_root.stat().st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise CompatibilityInstallError("Pinned Strix scripts root is group/world writable.")
    if len(expected_digest) != 64 or any(
        character not in "0123456789abcdef" for character in expected_digest
    ):
        raise CompatibilityInstallError("STRIX_EXECUTABLE_SHA256 is malformed.")
    if not hmac.compare_digest(sha256_file(resolved_executable), expected_digest):
        raise CompatibilityInstallError(
            "Pinned Strix executable digest changed before wrapping."
        )

    target = resolved_root / "strix-contextual-orchestrator"
    temporary_handle, temporary_name = tempfile.mkstemp(
        prefix=".strix-contextual-orchestrator.",
        dir=resolved_root,
    )
    os.close(temporary_handle)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(resolved_source, temporary)
        temporary.chmod(0o555)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)

    target_digest = sha256_file(target)
    with resolved_github_env.open("a", encoding="utf-8") as stream:
        stream.write(f"STRIX_EXECUTABLE_PATH={target}\n")
        stream.write(f"STRIX_EXECUTABLE_SHA256={target_digest}\n")
    return target


def main(
    installer: Callable[[], object] = install_compatibility_launcher,
) -> None:
    """Install from the current trusted GitHub Actions environment."""
    try:
        installer()
    except CompatibilityInstallError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":  # pragma: no cover - exercised by shell integration tests.
    main()
