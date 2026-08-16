"""Fail-first hardening contracts for object-storage policy documents."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import validate_object_storage_contract as validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "cwl-object-storage-v1.schema.json"
EXAMPLE = ROOT / "schemas" / "examples" / "cwl-object-storage-v1.example.json"
ONE_SHOT_REPAIR_WORKFLOW = (
    ROOT / ".github" / "workflows" / "repair-object-storage-contract.yml"
)


def _valid_contract() -> dict:
    """Return an independent mutable copy of the published example."""
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_one_shot_repair_workflow_is_absent() -> None:
    """Completed one-shot writers must not remain to grant contents: write."""
    assert not ONE_SHOT_REPAIR_WORKFLOW.exists()


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
        "2130706433",
        "2851992574",
        "127.1",
        "127.0.1",
        "0x7f000001",
        "0x7f.0.0.1",
        "a" * 254,
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


def test_exact_dns_hosts_still_accept_numeric_dns_labels() -> None:
    """A numeric label is allowed only when the name is not an IP alias."""
    assert validator.is_exact_dns_host("1.s3.amazonaws.com")
    assert validator.is_exact_dns_host("0xz.example.com")
    assert validator.is_exact_dns_host("0x.example.com")


def test_explicit_allowlist_rejects_decimal_metadata_ip_alias() -> None:
    """Decimal IPv4 aliases must not enter an explicit host allowlist."""
    contract = _valid_contract()
    contract["endpoint_policy"]["private_network_trust"] = "explicit_allowlist"
    contract["endpoint_policy"]["host_allowlist"] = ["2851992574"]
    contract["endpoint_policy"].pop("custom_endpoint", None)
    with pytest.raises(validator.ObjectStorageContractError, match="exact DNS"):
        validator.validate_contract(contract)


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
