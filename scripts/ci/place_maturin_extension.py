#!/usr/bin/env python3
"""Copy a built wheel's extension modules into the project's Python source tree.

Projects such as fast-mlsirm set pytest ``pythonpath = ["python"]``, so the test
suite imports ``python/<package>`` rather than the installed wheel, and an
extension that exists only in site-packages is shadowed (``cannot import name
'_core'``). This mirrors what ``maturin develop`` does: only compiled extension
members are copied, only into package directories the source tree already has.
"""

from __future__ import annotations

import pathlib
import sys
import tomllib
import zipfile

EXTENSION_SUFFIXES = (".so", ".pyd")


def _inside(path: pathlib.Path, root: pathlib.Path) -> bool:
    """Return whether path is root or is contained by root."""

    return path == root or root in path.parents


def place(wheel: pathlib.Path, project_dir: pathlib.Path) -> list[pathlib.Path]:
    """Copy wheel extensions into existing project package directories."""

    project = project_dir.resolve()
    pyproject = tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))
    python_source = pyproject.get("tool", {}).get("maturin", {}).get("python-source", ".")
    if not isinstance(python_source, str):
        raise ValueError("tool.maturin.python-source must be a string")
    source_root = (project / python_source).resolve()
    if not _inside(source_root, project):
        raise ValueError("tool.maturin.python-source escapes the project directory")

    placed = []
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            if member.is_dir() or not member.filename.endswith(EXTENSION_SUFFIXES):
                continue
            target = (source_root / member.filename).resolve()
            if not _inside(target, source_root):
                raise ValueError(f"wheel member escapes the source tree: {member.filename}")
            if not target.parent.is_dir():
                continue
            target.write_bytes(archive.read(member))
            placed.append(target)
    return placed


def main(argv: list[str]) -> int:
    """Run extension placement and return its process status."""

    if len(argv) != 2:
        print("usage: place_maturin_extension.py WHEEL PROJECT_DIR", file=sys.stderr)
        return 2
    try:
        placed = place(pathlib.Path(argv[0]), pathlib.Path(argv[1]))
    except (OSError, ValueError, zipfile.BadZipFile, tomllib.TOMLDecodeError) as exc:
        print(f"Could not place the built extension in the source tree: {exc}", file=sys.stderr)
        return 1
    for path in placed:
        print(f"Placed built extension at {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
