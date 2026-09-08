#!/usr/bin/env python3
"""Install the trusted Strix 1.5.3 unbounded-inference launcher atomically."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import os
from pathlib import Path
import shutil
import stat
import tempfile


SUPPORTED_VERSION = "1.5.3"
STRIX_DISTRIBUTION = "strix-agent"
LAUNCHER_NAME = "cwl-strix-timeout-compat"


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest for one regular file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular_file(path: Path, label: str) -> Path:
    """Resolve and validate a regular, non-symlink file."""
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} must be a regular, non-symlink file.")
    return path.resolve(strict=True)


def _validate_installation(executable: Path, scripts_root: Path, expected_sha256: str) -> None:
    """Bind launcher installation to the hash-pinned Strix runtime selected by CI."""
    executable = _regular_file(executable, "STRIX_EXECUTABLE_PATH")
    if scripts_root.is_symlink() or not scripts_root.is_dir():
        raise RuntimeError("STRIX_EXECUTABLE_ROOT must be a regular directory.")
    scripts_root = scripts_root.resolve(strict=True)
    try:
        executable.relative_to(scripts_root)
    except ValueError as exc:
        raise RuntimeError("STRIX_EXECUTABLE_PATH is outside STRIX_EXECUTABLE_ROOT.") from exc
    if not expected_sha256 or len(expected_sha256) != 64:
        raise RuntimeError("STRIX_EXECUTABLE_SHA256 must be a 64-character digest.")
    try:
        int(expected_sha256, 16)
    except ValueError as exc:
        raise RuntimeError("STRIX_EXECUTABLE_SHA256 must be hexadecimal.") from exc
    if _sha256(executable) != expected_sha256.lower():
        raise RuntimeError("Pinned Strix executable changed before compatibility installation.")


def _require_supported_version() -> None:
    """Reject installation when the reviewed upstream source version changed."""
    try:
        installed_version = importlib.metadata.version(STRIX_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("Pinned Strix distribution is not installed.") from exc
    if installed_version != SUPPORTED_VERSION:
        raise RuntimeError(
            "Strix timeout compatibility supports exactly "
            f"{SUPPORTED_VERSION}; installed version is {installed_version}."
        )


def install_launcher(source: Path, scripts_root: Path) -> Path:
    """Copy the reviewed launcher atomically into the trusted Python scripts root."""
    source = _regular_file(source, "compatibility launcher source")
    scripts_root = scripts_root.resolve(strict=True)
    target = scripts_root / LAUNCHER_NAME
    if target.is_symlink():
        raise RuntimeError("Compatibility launcher destination must not be a symlink.")

    with tempfile.NamedTemporaryFile(dir=scripts_root, prefix=f".{LAUNCHER_NAME}.", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        shutil.copyfile(source, temporary)
        temporary.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return _regular_file(target, "installed compatibility launcher")


def _append_github_environment(github_env: Path, launcher: Path, scripts_root: Path) -> None:
    """Publish the launcher identity for later workflow steps without secret material."""
    if not github_env:
        raise RuntimeError("GITHUB_ENV is required for Strix compatibility installation.")
    launcher_sha256 = _sha256(launcher)
    with github_env.open("a", encoding="utf-8") as handle:
        handle.write(f"STRIX_EXECUTABLE_PATH={launcher}\n")
        handle.write(f"STRIX_EXECUTABLE_ROOT={scripts_root.resolve(strict=True)}\n")
        handle.write(f"STRIX_EXECUTABLE_SHA256={launcher_sha256}\n")
        handle.write("CWL_STRIX_UNBOUNDED_INFERENCE=1\n")


def build_parser() -> argparse.ArgumentParser:
    """Build the explicit trusted-input CLI contract."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--launcher", required=True, type=Path)
    parser.add_argument("--strix-executable", required=True, type=Path)
    parser.add_argument("--scripts-root", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--github-env", required=True, type=Path)
    return parser


def main() -> None:
    """Validate the installed Strix identity, install the shim, and publish it."""
    arguments = build_parser().parse_args()
    _require_supported_version()
    _validate_installation(
        arguments.strix_executable,
        arguments.scripts_root,
        arguments.expected_sha256,
    )
    launcher = install_launcher(arguments.launcher, arguments.scripts_root)
    _append_github_environment(arguments.github_env, launcher, arguments.scripts_root)
    print(f"Installed version-gated Strix timeout compatibility launcher: {launcher}")


if __name__ == "__main__":
    main()
