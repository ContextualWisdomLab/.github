#!/usr/bin/env python3
"""Apply the fail-first tests and bounded source fix for PR 1008."""

from __future__ import annotations

import argparse
from pathlib import Path


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact source fragment or fail without partial mutation."""
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one {label}")
    return text.replace(old, new)


def apply_tests() -> None:
    """Add regressions for untrusted metadata and mutable output paths."""
    workspace_path = Path("tests/test_uv_workspace_fail_closed.py")
    workspace = workspace_path.read_text(encoding="utf-8")
    workspace = _replace_once(
        workspace,
        '''[tool.uv.workspace]
members = ["packages/*"]
""",
''',
        '''[tool.uv.workspace]
members = ["packages/*"]
credential = "sk_live_should_not_be_logged"
""",
''',
        "uv workspace fixture",
    )
    workspace = _replace_once(
        workspace,
        '''    with pytest.raises(
        RuntimeError,
        match=r"uv workspace.*packages/\\*.*not supported",
    ):
        materializer.materialize(repo, base_sha, tmp_path / "output")

    assert not bootstrap_called
''',
        '''    with pytest.raises(
        RuntimeError,
        match=r"uv workspace.*not supported",
    ) as raised:
        materializer.materialize(repo, base_sha, tmp_path / "output")

    error_message = str(raised.value)
    assert "packages/*" not in error_message
    assert "sk_live_should_not_be_logged" not in error_message
    assert not bootstrap_called
''',
        "workspace rejection assertion",
    )
    workspace_path.write_text(workspace, encoding="utf-8")

    tests_path = Path("tests/test_materialize_base_python_requirements.py")
    tests = tests_path.read_text(encoding="utf-8")
    tests = _replace_once(
        tests,
        '''    with pytest.raises(ValueError, match="must not be a symlink"):
        materializer.materialize(tmp_path, "a" * 40, output)
''',
        '''    with pytest.raises(ValueError, match="non-symlink directory"):
        materializer.materialize(tmp_path, "a" * 40, output)
''',
        "output symlink assertion",
    )

    marker = "def test_materialize_rejects_symlink_substitution_during_creation("
    if marker not in tests:
        tests += '''


def test_materialize_accepts_an_existing_empty_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An existing empty real directory remains a supported trusted destination."""
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(materializer, "base_hash_locks", lambda *_args: [])

    assert materializer.materialize(tmp_path, "a" * 40, output) == []
    assert (output / "manifest.json").read_text(encoding="utf-8") == "[]\\n"
    assert (output / "manifest.txt").read_text(encoding="utf-8") == ""


def test_materialize_rejects_symlink_substitution_during_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path swapped to a symlink during creation cannot receive trusted files."""
    output = tmp_path / "output"
    attacker_directory = tmp_path / "attacker"
    attacker_directory.mkdir()
    original_mkdir = Path.mkdir

    def substitute_symlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == output:
            path.symlink_to(attacker_directory, target_is_directory=True)
            return
        original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", substitute_symlink)
    monkeypatch.setattr(materializer, "base_hash_locks", lambda *_args: [])

    with pytest.raises(ValueError, match="non-symlink directory"):
        materializer.materialize(tmp_path, "a" * 40, output)

    assert list(attacker_directory.iterdir()) == []


def test_materialize_detects_output_path_replacement_after_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Directory-descriptor writes never follow a replacement output path."""
    output = tmp_path / "output"
    detached_output = tmp_path / "detached-output"
    attacker_directory = tmp_path / "attacker"
    attacker_directory.mkdir()
    monkeypatch.setattr(materializer, "base_hash_locks", lambda *_args: [])
    original_write = getattr(materializer, "_write_output_file", None)
    swapped = False

    def replace_path_then_write(
        output_descriptor: int,
        file_name: str,
        content: bytes,
    ) -> None:
        nonlocal swapped
        if not swapped:
            output.rename(detached_output)
            output.symlink_to(attacker_directory, target_is_directory=True)
            swapped = True
        assert original_write is not None
        original_write(output_descriptor, file_name, content)

    monkeypatch.setattr(
        materializer,
        "_write_output_file",
        replace_path_then_write,
        raising=False,
    )

    with pytest.raises(ValueError, match="changed during materialization"):
        materializer.materialize(tmp_path, "a" * 40, output)

    assert list(attacker_directory.iterdir()) == []
    assert (detached_output / "manifest.json").read_text(encoding="utf-8") == "[]\\n"
'''
    tests_path.write_text(tests, encoding="utf-8")


def apply_source() -> None:
    """Redact untrusted metadata and bind all writes to an open directory."""
    source_path = Path("scripts/ci/materialize_base_python_requirements.py")
    source = source_path.read_text(encoding="utf-8")
    source = _replace_once(
        source,
        '''    try:
        workspace = metadata["tool"]["uv"]["workspace"]
    except (KeyError, TypeError):
        return

    raise RuntimeError(
        f"tracked base uv workspace in {pyproject_path} {workspace!r} is not "
        "supported by isolated lock materialization"
    )
''',
        '''    try:
        metadata["tool"]["uv"]["workspace"]
    except (KeyError, TypeError):
        return

    raise RuntimeError(
        f"tracked base uv workspace in {pyproject_path} is not supported by "
        "isolated lock materialization"
    )
''',
        "unredacted workspace rejection",
    )

    source = _replace_once(
        source,
        '''def materialize(
    repo_root: pathlib.Path,
    base_sha: str,
    output_dir: pathlib.Path,
) -> list[dict[str, str]]:
    """Write base lock blobs under generated names safe for a Docker build context."""
    if output_dir.exists() and output_dir.is_symlink():
        raise ValueError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, str]] = []
    for index, (source_path, content) in enumerate(
        base_hash_locks(repo_root.resolve(), base_sha)
    ):
        generated_name = f"requirements-{index:03d}.txt"
        destination = output_dir / generated_name
        destination.write_bytes(content)
        manifest.append({"file": generated_name, "source": source_path})

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\\n",
        encoding="utf-8",
    )
    (output_dir / "manifest.txt").write_text(
        "".join(f"{entry['file']}\\n" for entry in manifest),
        encoding="utf-8",
    )
    return manifest
''',
        '''def _open_output_directory(
    output_dir: pathlib.Path,
) -> tuple[int, os.stat_result]:
    """Atomically create or securely open one non-symlink output directory."""
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_dir.mkdir(mode=0o700)
    except FileExistsError:
        pass
    try:
        descriptor = os.open(
            output_dir,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
        )
    except OSError as exc:
        raise ValueError(
            "output directory must be a non-symlink directory"
        ) from exc
    return descriptor, os.fstat(descriptor)


def _write_output_file(
    output_descriptor: int,
    file_name: str,
    content: bytes,
) -> None:
    """Create one regular output file relative to an open directory."""
    descriptor = os.open(
        file_name,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=output_descriptor,
    )
    with os.fdopen(descriptor, "wb") as destination:
        destination.write(content)


def _verify_output_directory(
    output_dir: pathlib.Path,
    expected_identity: os.stat_result,
) -> None:
    """Reject replacement of the published output path during materialization."""
    current_identity = output_dir.stat(follow_symlinks=False)
    if not os.path.samestat(expected_identity, current_identity):
        raise ValueError("output directory changed during materialization")


def materialize(
    repo_root: pathlib.Path,
    base_sha: str,
    output_dir: pathlib.Path,
) -> list[dict[str, str]]:
    """Write base lock blobs without following mutable output path entries."""
    output_descriptor, output_identity = _open_output_directory(output_dir)
    try:
        manifest: list[dict[str, str]] = []
        for index, (source_path, content) in enumerate(
            base_hash_locks(repo_root.resolve(), base_sha)
        ):
            generated_name = f"requirements-{index:03d}.txt"
            _write_output_file(output_descriptor, generated_name, content)
            manifest.append({"file": generated_name, "source": source_path})

        _write_output_file(
            output_descriptor,
            "manifest.json",
            (json.dumps(manifest, indent=2, sort_keys=True) + "\\n").encode(
                "utf-8"
            ),
        )
        _write_output_file(
            output_descriptor,
            "manifest.txt",
            "".join(f"{entry['file']}\\n" for entry in manifest).encode("utf-8"),
        )
        _verify_output_directory(output_dir, output_identity)
        return manifest
    finally:
        os.close(output_descriptor)
''',
        "original materialize implementation",
    )
    source_path.write_text(source, encoding="utf-8")


def main() -> int:
    """Apply exactly one selected repair phase."""
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("tests", "source"))
    args = parser.parse_args()
    if args.phase == "tests":
        apply_tests()
    else:
        apply_source()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
