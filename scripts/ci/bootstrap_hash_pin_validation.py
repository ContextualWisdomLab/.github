#!/usr/bin/env python3
"""Apply the focused hash-pin validation fix, then remove bootstrap files."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATERIALIZER = ROOT / "scripts/ci/materialize_base_python_requirements.py"
TESTS = ROOT / "tests/test_materialize_base_python_requirements.py"
SELF = ROOT / "scripts/ci/bootstrap_hash_pin_validation.py"
SELF_WORKFLOW = ROOT / ".github/workflows/bootstrap-hash-pin-validation.yml"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact fragment and reject stale or ambiguous input."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def patch_materializer(text: str) -> str:
    """Require every installable logical requirement to carry an actual hash."""
    old = '''    lines = _requirement_lines(content)
    if not lines:
        return False
    return any(line == "--require-hashes" for line in lines) or all(
        "--hash=" in line or line.startswith(("-r ", "--requirement "))
        for line in lines
    )
'''
    new = '''    lines = _requirement_lines(content)
    if not lines:
        return False

    requirement_lines: list[str] = []
    for line in lines:
        if line == "--require-hashes":
            continue
        # Generated candidates are renamed and installed independently, so an
        # include directive cannot be proven self-contained after materialization.
        # Reject it rather than mistaking a reference to another file for a hash.
        if line.startswith(("-r ", "--requirement ")):
            return False
        # Other standalone pip options can change indexes, hosts, or resolver
        # behavior without representing an installable hash-pinned requirement.
        if line.startswith("-") and "--hash=" not in line:
            return False
        requirement_lines.append(line)

    return bool(requirement_lines) and all(
        "--hash=" in line for line in requirement_lines
    )
'''
    return replace_once(text, old, new, "hash-pin predicate")


def patch_tests(text: str) -> str:
    """Pin the bypass regression and the self-contained-lock requirement."""
    old = '''def test_hash_pin_detection_includes_pinned_and_excludes_unpinned_or_empty() -> None:
    """Only fully hash-pinned, non-empty lock content is materialized."""
    assert not materializer._is_hash_pinned(b"# comment only\\n\\n")
    assert materializer._is_hash_pinned(b"--require-hashes\\ndemo==1\\n")
    assert materializer._is_hash_pinned(b"demo==1 --hash=sha256:" + b"a" * 64 + b"\\n")
    assert materializer._is_hash_pinned(b"-r other-hashes.txt\\n")
    assert not materializer._is_hash_pinned(b"untrusted==1\\n")
    # uv export / pip-compile multi-line continuation format (spec, then --hash= lines).
    assert materializer._is_hash_pinned(
        b"foo==1 \\\\\\n    --hash=sha256:"
        + b"a" * 64
        + b" \\\\\\n    --hash=sha256:"
        + b"b" * 64
        + b"\\n"
    )
'''
    new = '''def test_hash_pin_detection_includes_pinned_and_excludes_unpinned_or_empty() -> None:
    """Only self-contained, fully hash-pinned, non-empty lock content is accepted."""
    assert not materializer._is_hash_pinned(b"# comment only\\n\\n")
    assert not materializer._is_hash_pinned(b"--require-hashes\\ndemo==1\\n")
    assert materializer._is_hash_pinned(
        b"--require-hashes\\ndemo==1 --hash=sha256:" + b"a" * 64 + b"\\n"
    )
    assert materializer._is_hash_pinned(
        b"demo==1 --hash=sha256:" + b"a" * 64 + b"\\n"
    )
    assert not materializer._is_hash_pinned(b"-r other-hashes.txt\\n")
    assert not materializer._is_hash_pinned(b"--index-url https://example.invalid/simple\\n")
    assert not materializer._is_hash_pinned(b"untrusted==1\\n")
    # uv export / pip-compile multi-line continuation format (spec, then --hash= lines).
    assert materializer._is_hash_pinned(
        b"foo==1 \\\\\\n    --hash=sha256:"
        + b"a" * 64
        + b" \\\\\\n    --hash=sha256:"
        + b"b" * 64
        + b"\\n"
    )
'''
    return replace_once(text, old, new, "hash-pin tests")


def main() -> None:
    """Apply both focused edits only after exact base fragments are proven."""
    materializer = patch_materializer(MATERIALIZER.read_text(encoding="utf-8"))
    tests = patch_tests(TESTS.read_text(encoding="utf-8"))
    MATERIALIZER.write_text(materializer, encoding="utf-8")
    TESTS.write_text(tests, encoding="utf-8")
    SELF.unlink()
    SELF_WORKFLOW.unlink()


if __name__ == "__main__":
    main()
