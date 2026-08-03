"""Security regressions for trusted Python requirements lock materialization."""

from scripts.ci import materialize_base_python_requirements as materializer


def test_require_hashes_directive_does_not_replace_per_requirement_hashes() -> None:
    """A directive alone cannot authorize an unpinned package requirement."""
    assert not materializer._is_hash_pinned(
        b"--require-hashes\nrequests==2.31.0\n"
    )


def test_require_hashes_directive_accepts_an_actually_hashed_requirement() -> None:
    """Resolver metadata may accompany a package line carrying an actual hash."""
    assert materializer._is_hash_pinned(
        b"--require-hashes\n"
        b"--index-url https://pypi.org/simple\n"
        b"requests==2.31.0 --hash=sha256:"
        + b"a" * 64
        + b"\n"
    )


def test_directives_without_an_install_target_are_not_materialized() -> None:
    """An option-only file carries no dependency closure and remains excluded."""
    assert not materializer._is_hash_pinned(
        b"--require-hashes\n--no-index\n--prefer-binary\n"
    )


def test_unhashed_editable_requirement_remains_rejected() -> None:
    """Install-target options cannot be mistaken for harmless resolver metadata."""
    assert not materializer._is_hash_pinned(b"--require-hashes\n--editable .\n")
