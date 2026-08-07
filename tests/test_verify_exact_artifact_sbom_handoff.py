"""Behavior and hostile-input tests for exact artifact/SBOM handoff verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path

import pytest

from scripts.ci import verify_exact_artifact_sbom_handoff as verifier

SCHEMA = "https://cyclonedx.org/schema/bom-1.7.schema.json"
PREDICATE = "https://cyclonedx.org/bom"


def _digest(path: Path) -> str:
    """Return one fixture file's SHA-256 digest."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _serial_number(name: str, digest: str) -> str:
    """Return the canonical UUIDv5 serial number for one exact subject."""
    identity = f"urn:cwl:artifact:{name}:sha256:{digest}"
    return f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, identity)}"


def _sbom(name: str, digest: str) -> dict[str, object]:
    """Return the minimum valid CycloneDX root-component fixture."""
    return {
        "$schema": SCHEMA,
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "serialNumber": _serial_number(name, digest),
        "version": 1,
        "metadata": {
            "component": {
                "type": "file",
                "name": name,
                "hashes": [{"alg": "SHA-256", "content": digest}],
                "properties": [
                    {"name": "cwl:artifact:filename", "value": name}
                ],
            }
        },
    }


def _write_json(path: Path, value: object) -> None:
    """Write deterministic fixture JSON."""
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _identity(arguments: argparse.Namespace) -> dict[str, object]:
    """Return the exact identity document expected by the verifier."""
    return {
        "schema_version": "1.0",
        "source_repository": arguments.source_repository,
        "source_sha": arguments.source_sha,
        "evidence_artifact_name": arguments.evidence_artifact_name,
        "evidence_artifact_digest": arguments.evidence_artifact_digest,
        "predicate_type": arguments.predicate_type,
        "cyclonedx_schema": arguments.cyclonedx_schema,
        "artifacts": {
            "wheel": {
                "filename": arguments.wheel_filename,
                "sha256": arguments.wheel_sha256,
                "sbom_filename": arguments.wheel_sbom_filename,
                "sbom_sha256": arguments.wheel_sbom_sha256,
            },
            "sdist": {
                "filename": arguments.sdist_filename,
                "sha256": arguments.sdist_sha256,
                "sbom_filename": arguments.sdist_sbom_filename,
                "sbom_sha256": arguments.sdist_sbom_sha256,
            },
        },
    }


def _rewrite_checksums(
    root: Path,
    arguments: argparse.Namespace,
    *,
    entries: dict[str, str] | None = None,
    sort_entries: bool = True,
) -> None:
    """Rewrite and externally reseal the checksum control file."""
    values = entries or {
        arguments.wheel_filename: arguments.wheel_sha256,
        arguments.wheel_sbom_filename: arguments.wheel_sbom_sha256,
        arguments.sdist_filename: arguments.sdist_sha256,
        arguments.sdist_sbom_filename: arguments.sdist_sbom_sha256,
        "source-identity.json": arguments.source_identity_sha256,
    }
    names = sorted(values) if sort_entries else list(values)
    (root / "checksums.sha256").write_text(
        "".join(f"{values[name]}  {name}\n" for name in names),
        encoding="utf-8",
    )
    arguments.checksum_sha256 = _digest(root / "checksums.sha256")


def _valid_handoff(tmp_path: Path) -> argparse.Namespace:
    """Create one complete exact six-file handoff and its CLI arguments."""
    root = tmp_path / "evidence"
    root.mkdir(parents=True)
    wheel = root / "example-1.0.0-py3-none-any.whl"
    sdist = root / "example-1.0.0.tar.gz"
    wheel.write_bytes(b"wheel-bytes\x00")
    sdist.write_bytes(b"sdist-bytes\xff")
    wheel_sha = _digest(wheel)
    sdist_sha = _digest(sdist)
    wheel_sbom = root / "example-wheel.cdx.json"
    sdist_sbom = root / "example-sdist.cdx.json"
    _write_json(wheel_sbom, _sbom(wheel.name, wheel_sha))
    _write_json(sdist_sbom, _sbom(sdist.name, sdist_sha))

    arguments = argparse.Namespace(
        source_repository="ContextualWisdomLab/example",
        source_sha="a" * 40,
        evidence_artifact_name="release-evidence",
        evidence_artifact_digest="sha256:" + ("b" * 64),
        evidence_root=str(root),
        wheel_filename=wheel.name,
        wheel_sha256=wheel_sha,
        wheel_sbom_filename=wheel_sbom.name,
        wheel_sbom_sha256=_digest(wheel_sbom),
        sdist_filename=sdist.name,
        sdist_sha256=sdist_sha,
        sdist_sbom_filename=sdist_sbom.name,
        sdist_sbom_sha256=_digest(sdist_sbom),
        source_identity_sha256="",
        checksum_sha256="",
        predicate_type=PREDICATE,
        cyclonedx_schema=SCHEMA,
        output_manifest=str(tmp_path / "verified.json"),
    )
    _write_json(root / "source-identity.json", _identity(arguments))
    arguments.source_identity_sha256 = _digest(root / "source-identity.json")
    _rewrite_checksums(root, arguments)
    return arguments


def _reseal_json_member(
    arguments: argparse.Namespace,
    filename: str,
    value: object,
) -> None:
    """Rewrite one JSON member while preserving every outer digest binding."""
    root = Path(arguments.evidence_root)
    _write_json(root / filename, value)
    if filename == arguments.wheel_sbom_filename:
        arguments.wheel_sbom_sha256 = _digest(root / filename)
    elif filename == arguments.sdist_sbom_filename:
        arguments.sdist_sbom_sha256 = _digest(root / filename)
    _write_json(root / "source-identity.json", _identity(arguments))
    arguments.source_identity_sha256 = _digest(root / "source-identity.json")
    _rewrite_checksums(root, arguments)


def test_valid_handoff_is_verified_and_manifest_is_deterministic(tmp_path: Path) -> None:
    """Verify the happy path and deterministic sorted output contract."""
    arguments = _valid_handoff(tmp_path)
    manifest = verifier.verify(arguments)
    output = Path(arguments.output_manifest)

    assert manifest["result"] == "PASS"
    assert len(manifest["files"]) == 6
    assert json.loads(output.read_text(encoding="utf-8")) == manifest
    assert output.read_text(encoding="utf-8").endswith("\n")


def test_main_prints_success_and_returns_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exercise the public command-line success entrypoint."""
    arguments = _valid_handoff(tmp_path)
    argv: list[str] = []
    for name, value in vars(arguments).items():
        argv.extend(("--" + name.replace("_", "-"), str(value)))

    assert verifier.main(argv) == 0
    assert "6 files" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("attribute", "value", "message"),
    [
        ("source_repository", "not-a-repository", "owner/name"),
        ("source_sha", "A" * 40, "lowercase 40-character"),
        ("evidence_artifact_digest", "sha256:nope", "sha256:<hex>"),
        ("wheel_sha256", "0" * 63, "wheel SHA-256"),
    ],
)
def test_invalid_external_identifiers_fail_closed(
    tmp_path: Path, attribute: str, value: str, message: str
) -> None:
    """Reject malformed repository, source, artifact, and file digests."""
    arguments = _valid_handoff(tmp_path)
    setattr(arguments, attribute, value)
    with pytest.raises(verifier.EvidenceError, match=message):
        verifier.verify(arguments)


@pytest.mark.parametrize(
    "filename", ["", ".", "..", "../escape.whl", "a\\b.whl", "a\x00b.whl"]
)
def test_unsafe_filenames_are_rejected(tmp_path: Path, filename: str) -> None:
    """Keep every evidence member at one non-hostile root-level filename."""
    arguments = _valid_handoff(tmp_path)
    arguments.wheel_filename = filename
    with pytest.raises(verifier.EvidenceError, match="filename"):
        verifier.verify(arguments)


def test_duplicate_expected_filenames_are_rejected(tmp_path: Path) -> None:
    """Require six distinct semantic evidence members."""
    arguments = _valid_handoff(tmp_path)
    arguments.sdist_filename = arguments.wheel_filename
    with pytest.raises(verifier.EvidenceError, match="distinct"):
        verifier.verify(arguments)


@pytest.mark.parametrize("kind", ["missing", "file", "symlink"])
def test_evidence_root_must_be_a_real_directory(tmp_path: Path, kind: str) -> None:
    """Reject absent, regular-file, and symlink roots."""
    arguments = _valid_handoff(tmp_path)
    target = tmp_path / "bad-root"
    if kind == "file":
        target.write_text("not a directory", encoding="utf-8")
    elif kind == "symlink":
        target.symlink_to(Path(arguments.evidence_root), target_is_directory=True)
    arguments.evidence_root = str(target)
    with pytest.raises(verifier.EvidenceError, match="evidence root"):
        verifier.verify(arguments)


def test_extra_missing_and_nonregular_members_fail_cardinality(tmp_path: Path) -> None:
    """Reject extras, omissions, directories, and symlinks in the sealed root."""
    arguments = _valid_handoff(tmp_path)
    root = Path(arguments.evidence_root)
    (root / "extra.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(verifier.EvidenceError, match="cardinality"):
        verifier.verify(arguments)
    (root / "extra.txt").unlink()
    (root / arguments.wheel_filename).unlink()
    with pytest.raises(verifier.EvidenceError, match="cardinality"):
        verifier.verify(arguments)

    arguments = _valid_handoff(tmp_path / "again")
    root = Path(arguments.evidence_root)
    (root / arguments.wheel_filename).unlink()
    (root / arguments.wheel_filename).mkdir()
    with pytest.raises(verifier.EvidenceError, match="non-regular"):
        verifier.verify(arguments)

    arguments = _valid_handoff(tmp_path / "third")
    root = Path(arguments.evidence_root)
    target = root / arguments.sdist_filename
    target.unlink()
    target.symlink_to(arguments.wheel_filename)
    with pytest.raises(verifier.EvidenceError, match="non-regular"):
        verifier.verify(arguments)


def test_distribution_digest_mismatch_fails_before_semantic_parsing(
    tmp_path: Path,
) -> None:
    """Reject changed bytes even when filenames and control files are unchanged."""
    arguments = _valid_handoff(tmp_path)
    Path(arguments.evidence_root, arguments.wheel_filename).write_bytes(b"tampered")
    with pytest.raises(verifier.EvidenceError, match="digest mismatch"):
        verifier.verify(arguments)


@pytest.mark.parametrize(
    "payload",
    [
        "not canonical\n",
        ("0" * 64) + "  duplicate\n" + ("1" * 64) + "  duplicate\n",
    ],
)
def test_malformed_or_duplicate_checksum_lines_are_rejected(
    tmp_path: Path, payload: str
) -> None:
    """Reject malformed and duplicate checksum records after external resealing."""
    arguments = _valid_handoff(tmp_path)
    checksum = Path(arguments.evidence_root, "checksums.sha256")
    checksum.write_text(payload, encoding="utf-8")
    arguments.checksum_sha256 = _digest(checksum)
    with pytest.raises(verifier.EvidenceError, match="checksum"):
        verifier.verify(arguments)


def test_unsorted_wrong_set_and_wrong_value_checksums_are_rejected(
    tmp_path: Path,
) -> None:
    """Bind exactly the other five evidence files in canonical order and value."""
    arguments = _valid_handoff(tmp_path)
    root = Path(arguments.evidence_root)
    values = {
        arguments.wheel_filename: arguments.wheel_sha256,
        arguments.wheel_sbom_filename: arguments.wheel_sbom_sha256,
        arguments.sdist_filename: arguments.sdist_sha256,
        arguments.sdist_sbom_filename: arguments.sdist_sbom_sha256,
        "source-identity.json": arguments.source_identity_sha256,
    }
    reversed_values = dict(reversed(list(sorted(values.items()))))
    _rewrite_checksums(root, arguments, entries=reversed_values, sort_entries=False)
    with pytest.raises(verifier.EvidenceError, match="sorted"):
        verifier.verify(arguments)

    values.pop(arguments.sdist_sbom_filename)
    _rewrite_checksums(root, arguments, entries=values)
    with pytest.raises(verifier.EvidenceError, match="exactly"):
        verifier.verify(arguments)

    values[arguments.sdist_sbom_filename] = arguments.sdist_sbom_sha256
    values[arguments.wheel_filename] = "f" * 64
    _rewrite_checksums(root, arguments, entries=values)
    with pytest.raises(verifier.EvidenceError, match="handoff mismatch"):
        verifier.verify(arguments)


def test_source_identity_must_be_an_exact_object(tmp_path: Path) -> None:
    """Reject non-object and semantically mismatched source identities."""
    arguments = _valid_handoff(tmp_path)
    root = Path(arguments.evidence_root)
    _write_json(root / "source-identity.json", [])
    arguments.source_identity_sha256 = _digest(root / "source-identity.json")
    _rewrite_checksums(root, arguments)
    with pytest.raises(verifier.EvidenceError, match="JSON object"):
        verifier.verify(arguments)

    identity = _identity(arguments)
    identity["source_sha"] = "c" * 40
    _write_json(root / "source-identity.json", identity)
    arguments.source_identity_sha256 = _digest(root / "source-identity.json")
    _rewrite_checksums(root, arguments)
    with pytest.raises(verifier.EvidenceError, match="exactly match"):
        verifier.verify(arguments)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: [], "JSON object"),
        (lambda value: {**value, "$schema": "wrong"}, "unexpected CycloneDX schema"),
        (lambda value: {**value, "bomFormat": "SPDX"}, "specification 1.7"),
        (lambda value: {**value, "specVersion": "1.6"}, "specification 1.7"),
        (lambda value: {**value, "version": "1"}, "document version"),
        (lambda value: {**value, "serialNumber": "urn:uuid:wrong"}, "serial number"),
        (lambda value: {**value, "metadata": {}}, "root component"),
        (
            lambda value: {
                **value,
                "metadata": {
                    "component": {
                        **value["metadata"]["component"],
                        "name": "wrong",
                    }
                },
            },
            "root component",
        ),
        (
            lambda value: {
                **value,
                "metadata": {
                    "component": {
                        **value["metadata"]["component"],
                        "type": "library",
                    }
                },
            },
            "root component type",
        ),
        (
            lambda value: {
                **value,
                "metadata": {
                    "component": {
                        **value["metadata"]["component"],
                        "properties": [],
                    }
                },
            },
            "filename property",
        ),
        (
            lambda value: {
                **value,
                "metadata": {
                    "component": {
                        **value["metadata"]["component"],
                        "hashes": [],
                    }
                },
            },
            "canonical SHA-256",
        ),
        (
            lambda value: {
                **value,
                "metadata": {
                    "component": {
                        **value["metadata"]["component"],
                        "hashes": [
                            *value["metadata"]["component"]["hashes"],
                            {"alg": "SHA-1", "content": "0" * 40},
                        ],
                    }
                },
            },
            "canonical SHA-256",
        ),
        (
            lambda value: {
                **value,
                "metadata": {
                    "component": {
                        **value["metadata"]["component"],
                        "hashes": [
                            {
                                **value["metadata"]["component"]["hashes"][0],
                                "unexpected": "field",
                            }
                        ],
                    }
                },
            },
            "canonical SHA-256",
        ),
    ],
)
def test_cyclonedx_semantics_fail_closed(
    tmp_path: Path, mutation: object, message: str
) -> None:
    """Reject malformed document and exact root-component subject bindings."""
    arguments = _valid_handoff(tmp_path)
    root = Path(arguments.evidence_root)
    original = json.loads(
        (root / arguments.wheel_sbom_filename).read_text(encoding="utf-8")
    )
    altered = mutation(original)  # type: ignore[operator]
    _reseal_json_member(arguments, arguments.wheel_sbom_filename, altered)
    with pytest.raises(verifier.EvidenceError, match=message):
        verifier.verify(arguments)


def test_strict_json_rejects_duplicate_keys_bad_utf8_nonfinite_and_oversize(
    tmp_path: Path,
) -> None:
    """Exercise strict bounded JSON parsing boundaries directly."""
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"a":1,"a":2}', encoding="utf-8")
    with pytest.raises(verifier.EvidenceError, match="duplicate"):
        verifier._load_json(duplicate)

    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    with pytest.raises(verifier.EvidenceError, match="invalid JSON"):
        verifier._load_json(malformed)

    bad_utf8 = tmp_path / "bad.json"
    bad_utf8.write_bytes(b"\xff")
    with pytest.raises(verifier.EvidenceError, match="UTF-8"):
        verifier._load_json(bad_utf8)

    for literal in ("NaN", "Infinity", "-Infinity"):
        constant = tmp_path / f"{literal.removeprefix('-')}.json"
        constant.write_text('{"value":' + literal + "}", encoding="utf-8")
        with pytest.raises(verifier.EvidenceError, match="non-finite"):
            verifier._load_json(constant)

    oversized = tmp_path / "oversized.json"
    oversized.write_text('{"padding":"aaaa"}', encoding="utf-8")
    with pytest.raises(verifier.EvidenceError, match="exceeds"):
        verifier._load_json(oversized, maximum_bytes=2)


def test_regular_file_and_output_publication_edges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cover missing inputs, output symlinks, and temporary cleanup fallback."""
    missing = tmp_path / "missing"
    with pytest.raises(verifier.EvidenceError, match="missing"):
        verifier._require_regular_file(missing)

    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(verifier.EvidenceError, match="regular"):
        verifier._require_regular_file(directory)

    output = tmp_path / "output.json"
    output.symlink_to(missing)
    with pytest.raises(verifier.EvidenceError, match="symlink"):
        verifier._atomic_json(output, {"result": "PASS"})
    output.unlink()

    monkeypatch.setattr(os, "replace", lambda source, destination: None)
    verifier._atomic_json(output, {"result": "PASS"})
    assert not output.exists()


def test_main_converts_validation_errors_to_system_exit(tmp_path: Path) -> None:
    """Keep command-line failures compact and free of tracebacks by default."""
    arguments = _valid_handoff(tmp_path)
    arguments.source_repository = "bad"
    argv: list[str] = []
    for name, value in vars(arguments).items():
        argv.extend(("--" + name.replace("_", "-"), str(value)))
    with pytest.raises(SystemExit, match="sealed evidence verification failed"):
        verifier.main(argv)


def test_checksum_control_file_bounds_and_entrypoint_are_covered(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Cover bounded checksum decoding and the real module entrypoint."""
    checksum = tmp_path / "checksums.sha256"
    checksum.write_text(("0" * 64) + "  payload.bin\n", encoding="utf-8")
    monkeypatch.setattr(verifier, "_MAX_CONTROL_BYTES", 4)
    with pytest.raises(verifier.EvidenceError, match="size limit"):
        verifier._parse_checksums(checksum)

    monkeypatch.setattr(verifier, "_MAX_CONTROL_BYTES", 1024)
    checksum.write_bytes(b"\xff")
    with pytest.raises(verifier.EvidenceError, match="strict UTF-8"):
        verifier._parse_checksums(checksum)

    import runpy
    import sys

    arguments = _valid_handoff(tmp_path / "entrypoint")
    argv: list[str] = []
    for name, value in vars(arguments).items():
        argv.extend(("--" + name.replace("_", "-"), str(value)))
    monkeypatch.setattr(sys, "argv", [str(verifier.__file__), *argv])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(verifier.__file__), run_name="__main__")
    assert exit_info.value.code == 0
    assert "sealed evidence verification passed" in capsys.readouterr().out
