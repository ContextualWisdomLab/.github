"""Pin the Strix CI lock's google-api-core version and SHA-256 digests."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements-strix-ci-hashes.txt"
PACKAGE = "google-api-core==2.34.0"
HASHES = (
    "98a779fe72de956eb1c9c2f47ff4c4432a668ece1a002ec38bed07ec2698ae59",
    "cdf9c67e7ca2402d86ccbfde5f2503fc83e3cc3f58cc78456ae96cad24a6d2de",
)


def test_strix_lock_pins_google_api_core_with_sha256() -> None:
    """CWE-494: Dependabot must not land a version without matching hashes.

    The Strix installer uses ``pip install --require-hashes``. A 2.34.0
    line without both published wheel digests, or a leftover 2.33.0 pin,
    would install from an unreviewed control sphere (CWE-829).
    """
    text = LOCK.read_text(encoding="utf-8")

    assert f"{PACKAGE} \\" in text
    assert "google-api-core==2.33.0" not in text
    for digest in HASHES:
        assert f"--hash=sha256:{digest}" in text
