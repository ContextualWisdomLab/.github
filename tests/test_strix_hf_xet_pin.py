"""Pin the Strix CI lock's hf-xet version and SHA-256 digests."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "requirements-strix-ci-hashes.txt"
PACKAGE = "hf-xet==1.6.0"
HASHES = (
    "0e6e21fa3cdfcdcd76748564bf593870a5e013f47d97cf10aed63aa222cff5b7",
    "23379c2f9ec8696d952b16414a2bae72cad86a52df869b050698ba60f538c675",
    "2e58454a340b3556dfa4972d5451aff4fba8dd42a236600ba1a1d2b1514f0fef",
    "35cec30d75c6f9eb9c16a77cef68e85a103b72e24d4b473714ec9ff06428bab9",
    "3dc3e35441ba395006af5aaacc40ef2e603c51ef46c3530b9156185f00935ea3",
    "4fc74352a17015bd0ee90038bc9efe38db894cde45f268b6712b04fce8cd0acb",
    "5153e6bb103ad49d6ea9f1b2e230db5a2ea32551ad09a706d2f61d7c7c80d80e",
    "5789835d7c6bc9436962853192082374297fb72d7eff7e7762ec25ceb7e25338",
    "633dc0cd71d32da58ab8c03ad38e2fac452c15c2b0a2866ebf6ededfe0a5061d",
    "70cbb9c896901600128cb9b6f06e132954fbede1db30f31f7c6c63f84cb7c31d",
    "75765820ce4700db3750c94acc8fe27c5fae4c9ec000a0dbac3ca082acf97765",
    "8fb4f71cba6129110c3374a33f919001ff130488fc23553698e34cc1c2a1198c",
    "948f15d3a9545cfe5932f6bd8b440f6ae630aee108f14b7bd6c561f7c2dcc522",
    "d62671bb130879cef0ee4c9ebe47a14af6c66ec53e6d84dc15936e5ffdfac82f",
    "f0906082d9932ae0c0057fa194041c22b4e2cdb46b2592ef3b91f020d62a081a",
    "f2f7278c05c22fd60cb436cda1269649b3e81db65ecdc8496e5e164aa4143e7b",
    "fb4fadde1b2b70bf4c0c14a6dccbe7194b1c28947fefd5bbe3fed9d940676c3b",
)


def test_strix_lock_pins_hf_xet_with_sha256() -> None:
    """CWE-494: Dependabot must not land a version without matching hashes.

    The Strix installer uses ``pip install --require-hashes``. A 1.6.0
    line without every published wheel digest, or a leftover 1.5.1 pin,
    would install from an unreviewed control sphere (CWE-829).
    """
    text = LOCK.read_text(encoding="utf-8")

    assert f"{PACKAGE} \\" in text
    assert "hf-xet==1.5.1" not in text
    for digest in HASHES:
        assert f"--hash=sha256:{digest}" in text
    assert text.count("--hash=sha256:") >= len(HASHES)
