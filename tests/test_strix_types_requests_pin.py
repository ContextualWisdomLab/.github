"""Pin the Strix CI lock's types-requests version and SHA-256 digests."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements-strix-ci-hashes.txt"
PACKAGE = "types-requests==2.33.0.20260712"
HASHES = (
    "2141b67ab534a5c5cd2dac5034f2a35f42e699c5bf185eee608c5246a069d7fb",
    "de027e28c171d3da529689cbfa023b0b4eab188c8dfa22fd834eebd2cee6e7bb",
)


def test_strix_lock_pins_types_requests_with_sha256() -> None:
    """CWE-494: Dependabot must not land a version without matching hashes.

    The Strix installer uses ``pip install --require-hashes``. A
    2.33.0.20260712 line without both published wheel digests, or a leftover
    2.33.0.20260518 pin, would install from an unreviewed control sphere
    (CWE-829).
    """
    text = LOCK.read_text(encoding="utf-8")

    assert f"{PACKAGE} \\" in text
    assert "types-requests==2.33.0.20260518" not in text
    for digest in HASHES:
        assert f"--hash=sha256:{digest}" in text
