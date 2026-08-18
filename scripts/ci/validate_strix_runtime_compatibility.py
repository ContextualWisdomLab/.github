#!/usr/bin/env python3
"""Validate the exact Strix lock and exercised cryptographic consumers."""

from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

REQUIRED_DISTRIBUTIONS = ("strix-agent", "cryptography")
EXACT_PIN = re.compile(r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s\\]+)")


def required_runtime_pins(lock_path: Path) -> dict[str, str]:
    """Return the exact Strix and cryptography pins from a compiled lock."""
    pins: dict[str, str] = {}
    for raw_line in lock_path.read_text(encoding="utf-8").splitlines():
        match = EXACT_PIN.match(raw_line.strip())
        if match and match.group("name").lower() in REQUIRED_DISTRIBUTIONS:
            pins[match.group("name").lower()] = match.group("version")
    missing = set(REQUIRED_DISTRIBUTIONS) - pins.keys()
    if missing:
        raise ValueError(f"compiled lock is missing exact pins: {sorted(missing)}")
    return pins


def verify_installed_versions(expected: dict[str, str]) -> None:
    """Fail when the installed environment differs from the compiled lock."""
    for distribution, expected_version in expected.items():
        actual_version = metadata.version(distribution)
        if actual_version != expected_version:
            raise RuntimeError(
                f"installed {distribution}=={actual_version}; expected {expected_version}"
            )


def exercise_cryptographic_consumers() -> None:
    """Exercise the PyJWT and pyOpenSSL APIs used through Strix dependencies."""
    import jwt
    from OpenSSL import crypto
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    encoded = jwt.encode({"sub": "strix-runtime-smoke"}, private_pem, algorithm="RS256")
    decoded = jwt.decode(encoded, public_pem, algorithms=["RS256"])
    if decoded.get("sub") != "strix-runtime-smoke":
        raise RuntimeError("PyJWT RS256 round trip returned unexpected claims")

    openssl_key = crypto.PKey()
    openssl_key.generate_key(crypto.TYPE_RSA, 2048)
    certificate = crypto.X509()
    certificate.set_version(2)
    certificate.set_serial_number(1)
    certificate.get_subject().CN = "strix-runtime-smoke"
    certificate.gmtime_adj_notBefore(0)
    certificate.gmtime_adj_notAfter(60)
    certificate.set_issuer(certificate.get_subject())
    certificate.set_pubkey(openssl_key)
    certificate.sign(openssl_key, "sha256")
    pem = crypto.dump_certificate(crypto.FILETYPE_PEM, certificate)
    if b"BEGIN CERTIFICATE" not in pem:
        raise RuntimeError("pyOpenSSL certificate round trip failed")


def main(argv: list[str]) -> int:
    """Run exact-version and executable compatibility checks."""
    if len(argv) != 2:
        print(f"usage: {argv[0]} <compiled-lock>", file=sys.stderr)
        return 2
    try:
        expected = required_runtime_pins(Path(argv[1]))
        verify_installed_versions(expected)
        exercise_cryptographic_consumers()
    except (OSError, ValueError, RuntimeError, metadata.PackageNotFoundError, ImportError) as exc:
        print(f"Strix runtime compatibility validation failed: {exc}", file=sys.stderr)
        return 1
    print(
        "Validated exact Strix/cryptography pins plus PyJWT RS256 and pyOpenSSL crypto APIs."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
