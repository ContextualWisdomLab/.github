"""Pin the Strix CI lock's google-cloud-bigquery version and SHA-256 digests."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements-strix-ci-hashes.txt"
PACKAGE = "google-cloud-bigquery==3.43.0"
HASHES = (
    "a39217f14f215472ce9da816f20ebaf77fdb1db7ccdc8360772d8bf6bafb55c2",
    "e3dc25ab9ac8b2b089408493177d4d4508b098c80c3931786fbc20b075298fe6",
)


def test_strix_lock_pins_google_cloud_bigquery_with_sha256() -> None:
    """CWE-494: Dependabot must not land a version without matching hashes.

    The Strix installer uses ``pip install --require-hashes``. A 3.43.0
    line without both published wheel digests, or a leftover 3.42.2 pin,
    would install from an unreviewed control sphere (CWE-829).
    """
    text = LOCK.read_text(encoding="utf-8")

    assert f"{PACKAGE} \\" in text
    assert "google-cloud-bigquery==3.42.2" not in text
    for digest in HASHES:
        assert f"--hash=sha256:{digest}" in text
