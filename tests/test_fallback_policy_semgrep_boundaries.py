"""Contracts for narrowly justified fallback-policy Semgrep suppressions."""

from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.ci import contextual_fallback_policy as policy


_SHA1_RULE = (
    "python.lang.security.insecure-hash-algorithms."
    "insecure-hash-algorithm-sha1"
)
_EXEC_RULE = "python.lang.security.audit.exec-detected.exec-detected"


def test_git_blob_identity_uses_non_security_sha1_with_rule_scope(
    tmp_path: Path,
) -> None:
    """Git receipt identity remains exact while documenting non-security use."""
    candidate = tmp_path / "source.py"
    candidate.write_bytes(b"print('verified')\n")
    expected = hashlib.sha1(
        b"blob 18\0print('verified')\n", usedforsecurity=False
    ).hexdigest()

    assert policy.git_blob_sha(candidate) == expected

    source = Path(policy.__file__).read_text(encoding="utf-8")
    assert "usedforsecurity=False" in source
    assert f"nosemgrep: {_SHA1_RULE}" in source


def test_noema_core_exec_has_exact_rule_scoped_trust_comment() -> None:
    """The shared-globals loader documents its fixed, verified sibling input."""
    source = Path("scripts/ci/noema_review_gate.py").read_text(encoding="utf-8")

    assert "Noema core is a fixed regular non-symlink sibling" in source
    assert f"nosemgrep: {_EXEC_RULE}" in source
    assert "exec(compile(_CORE_PATH.read_bytes()" in source
