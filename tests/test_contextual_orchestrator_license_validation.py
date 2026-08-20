"""Regression tests for pre-install contextual-orchestrator license validation."""

from __future__ import annotations

from email.parser import BytesParser
import hashlib
import io
import pathlib
import zipfile

import pytest

from scripts.ci import validate_contextual_orchestrator_licenses as validator


def _wheel_bytes(
    name: str,
    version: str,
    license_headers: str = "License-Expression: MIT\n",
) -> bytes:
    """Build a minimal in-memory wheel carrying controlled METADATA."""
    metadata = (
        "Metadata-Version: 2.4\n"
        f"Name: {name}\n"
        f"Version: {version}\n"
        f"{license_headers}\n"
    ).encode()
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr(f"{name}-{version}.dist-info/METADATA", metadata)
    return payload.getvalue()


def test_parse_locked_packages_binds_each_pin_to_sha256_closure() -> None:
    """Every package pin retains only exact artifacts admitted by the lock."""
    first_hash = "a" * 64
    second_hash = "b" * 64
    lock = (
        "demo-package==1.2.3 \\\n"
        f"    --hash=sha256:{first_hash} \\\n"
        f"    --hash=sha256:{second_hash}\n"
        "# via demo\n"
    )

    packages = validator.parse_locked_packages(lock)

    assert packages == (
        validator.LockedPackage(
            "demo-package",
            "1.2.3",
            frozenset({first_hash, second_hash}),
        ),
    )


def test_parse_locked_packages_rejects_missing_hash_duplicate_and_orphan_hash() -> None:
    """Malformed or ambiguous lock closures fail before any metadata query."""
    digest = "a" * 64
    with pytest.raises(validator.LicenseValidationError, match="no SHA-256 closure"):
        validator.parse_locked_packages("demo-package==1.2.3\n")
    with pytest.raises(validator.LicenseValidationError, match="duplicate package pin"):
        validator.parse_locked_packages(
            "demo-package==1.2.3 \\\n"
            f"  --hash=sha256:{digest}\n"
            "demo_package==1.2.3 \\\n"
            f"  --hash=sha256:{digest}\n"
        )
    with pytest.raises(validator.LicenseValidationError, match="orphan SHA-256"):
        validator.parse_locked_packages(f"--hash=sha256:{digest}\n")


def test_select_locked_artifact_requires_metadata_identity_and_lock_digest() -> None:
    """PyPI artifact URLs cannot replace the lock as artifact authority."""
    locked_digest = "a" * 64
    package = validator.LockedPackage(
        "demo-package",
        "1.2.3",
        frozenset({locked_digest}),
    )
    metadata = {
        "info": {"name": "demo-package", "version": "1.2.3"},
        "urls": [
            {
                "packagetype": "bdist_wheel",
                "filename": "demo_package-1.2.3-py3-none-any.whl",
                "url": "https://files.pythonhosted.org/demo.whl",
                "size": 100,
                "digests": {"sha256": "b" * 64},
            }
        ],
    }
    with pytest.raises(validator.LicenseValidationError, match="no hash-bound"):
        validator.select_locked_artifact(package, metadata)

    metadata["urls"][0]["digests"]["sha256"] = locked_digest
    artifact = validator.select_locked_artifact(package, metadata)
    assert artifact.sha256 == locked_digest

    metadata["info"]["version"] = "9.9.9"
    with pytest.raises(validator.LicenseValidationError, match="identity mismatch"):
        validator.select_locked_artifact(package, metadata)


def test_downloaded_artifact_digest_and_size_are_rechecked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Downloaded bytes must match metadata size and the lock-bound digest."""
    payload = b"wheel-bytes"
    artifact = validator.LockedArtifact(
        "demo.whl",
        "https://files.pythonhosted.org/demo.whl",
        hashlib.sha256(payload).hexdigest(),
        len(payload),
    )

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

    class Opener:
        def open(self, *_args: object, **_kwargs: object) -> Response:
            return Response(payload)

    monkeypatch.setattr(validator, "_opener", lambda: Opener())
    assert validator._download_locked_artifact(artifact) == payload

    bad = validator.LockedArtifact(
        artifact.filename,
        artifact.url,
        "0" * 64,
        artifact.size,
    )
    with pytest.raises(validator.LicenseValidationError, match="digest mismatch"):
        validator._download_locked_artifact(bad)


def test_artifact_metadata_identity_and_spdx_are_fail_closed() -> None:
    """Artifact metadata must match the pin and use approved SPDX licenses."""
    payload = _wheel_bytes(
        "demo-package",
        "1.2.3",
        "License-Expression: MIT OR Apache-2.0\n",
    )
    parsed = validator._metadata_from_artifact(
        payload,
        "demo_package-1.2.3-py3-none-any.whl",
    )
    assert parsed["Name"] == "demo-package"
    assert validator._license_from_metadata(parsed) == "MIT OR Apache-2.0"

    gpl = BytesParser().parsebytes(
        b"Metadata-Version: 2.4\nName: demo\nVersion: 1\n"
        b"License-Expression: GPL-3.0-only\n\n"
    )
    with pytest.raises(validator.LicenseValidationError, match="disallowed SPDX"):
        validator._license_from_metadata(gpl)

    malformed = BytesParser().parsebytes(
        b"Metadata-Version: 2.4\nName: demo\nVersion: 1\n"
        b"License-Expression: MIT OR\n\n"
    )
    with pytest.raises(validator.LicenseValidationError, match="incomplete SPDX"):
        validator._license_from_metadata(malformed)


def test_classifier_fallback_accepts_only_known_permissive_classifiers() -> None:
    """Legacy metadata may fall back to a bounded OSI classifier map."""
    metadata = BytesParser().parsebytes(
        b"Metadata-Version: 2.1\nName: demo\nVersion: 1\n"
        b"License: UNKNOWN\n"
        b"Classifier: License :: OSI Approved :: MIT License\n\n"
    )
    assert validator._license_from_metadata(metadata) == "MIT"


def test_source_license_requires_approved_mit_evidence(
    tmp_path: pathlib.Path,
) -> None:
    """A checkout must carry a recognizable approved source license."""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\n",
        encoding="utf-8",
    )
    (tmp_path / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    assert validator.validate_source_license(tmp_path) == "MIT"
    (tmp_path / "LICENSE").write_text("LGPL-3.0-only\n", encoding="utf-8")
    with pytest.raises(validator.LicenseValidationError):
        validator.validate_source_license(tmp_path)
