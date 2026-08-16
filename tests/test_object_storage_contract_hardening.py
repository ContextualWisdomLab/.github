"""Fail-first hardening contracts for object-storage policy documents."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import validate_object_storage_contract as validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "cwl-object-storage-v1.schema.json"
EXAMPLE = ROOT / "schemas" / "examples" / "cwl-object-storage-v1.example.json"


def _valid_contract() -> dict:
    """Return an independent mutable copy of the published example."""
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_schema_closes_every_nested_policy_object() -> None:
    """The portable schema must express the executable nested-key boundary."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    expected = {
        "endpoint_policy": validator.ENDPOINT_POLICY_KEYS,
        "credentials": validator.CREDENTIAL_KEYS,
        "permissions": validator.PERMISSION_KEYS,
        "encryption": validator.ENCRYPTION_KEYS,
        "integrity": validator.INTEGRITY_KEYS,
        "lifecycle": validator.LIFECYCLE_KEYS,
        "rollback": validator.ROLLBACK_KEYS,
        "observability": validator.OBSERVABILITY_KEYS,
    }
    for name, keys in expected.items():
        definition = schema["properties"][name]
        assert definition["type"] == "object"
        assert definition["additionalProperties"] is False
        assert set(definition["properties"]) == set(keys)
        required = set(keys)
        if name == "endpoint_policy":
            required.remove("custom_endpoint")
        assert set(definition["required"]) == required


def test_loader_rejects_non_finite_json_constants() -> None:
    """NaN and infinity are not RFC 8259 JSON contract values."""
    for token in (b"NaN", b"Infinity", b"-Infinity"):
        with pytest.raises(validator.ObjectStorageContractError, match="finite"):
            validator.load_contract_bytes(b'{"unexpected":' + token + b"}")


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "api.localhost",
        "169.254.169.254",
        "127.0.0.1",
        "metadata.google.internal",
        "metadata.goog",
        "OBJECTS.EXAMPLE.COM",
        "objécts.example.com",
    ],
)
def test_exact_dns_hosts_reject_local_metadata_literal_and_noncanonical_names(
    host: str,
) -> None:
    """An exact allowlist must not admit metadata, IP, Unicode, or case aliases."""
    assert validator.is_exact_dns_host(host) is False


def test_denied_private_network_policy_rejects_single_label_hosts() -> None:
    """A denied private-network policy cannot admit an implicitly local host."""
    contract = _valid_contract()
    contract["endpoint_policy"]["private_network_trust"] = "denied"
    contract["endpoint_policy"]["host_allowlist"] = ["minio"]
    contract["endpoint_policy"]["custom_endpoint"] = "https://minio"
    with pytest.raises(validator.ObjectStorageContractError, match="single-label"):
        validator.validate_contract(contract)


def test_custom_endpoint_rejects_out_of_range_port() -> None:
    """A syntactically numeric port still must fit the TCP port range."""
    with pytest.raises(validator.ObjectStorageContractError, match="port"):
        validator.parse_https_endpoint_host("https://objects.example.example:65536")


def test_observability_labels_fail_closed_without_type_errors() -> None:
    """Malformed or duplicate telemetry labels produce policy errors, not crashes."""
    contract = _valid_contract()
    contract["observability"]["high_cardinality_labels_forbid"] = [
        "bucket",
        "object_key",
        "credential",
        {},
    ]
    with pytest.raises(validator.ObjectStorageContractError, match="nonempty strings"):
        validator.validate_contract(contract)

    contract = _valid_contract()
    contract["observability"]["high_cardinality_labels_forbid"].append("bucket")
    with pytest.raises(validator.ObjectStorageContractError, match="duplicate"):
        validator.validate_contract(contract)
