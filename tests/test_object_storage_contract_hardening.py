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


@pytest.mark.parametrize(
    "host",
    [
        "s3.internal",
        "objects.corp",
        "minio.lan",
        "storage.home",
        "minio.intranet",
        "objects.private",
        "minio.default.svc",
        "objects.localdomain",
    ],
)
def test_denied_private_network_rejects_special_use_internal_suffixes(
    host: str,
) -> None:
    """A denied private-network policy cannot admit RFC 6761/6762 internal names."""
    contract = _valid_contract()
    contract["endpoint_policy"]["private_network_trust"] = "denied"
    contract["endpoint_policy"]["host_allowlist"] = [host]
    contract["endpoint_policy"].pop("custom_endpoint", None)
    with pytest.raises(validator.ObjectStorageContractError, match="private-network"):
        validator.validate_contract(contract)


def test_mdns_local_suffix_is_never_an_exact_allowlist_member() -> None:
    """Multicast .local names are not unicast object-storage endpoints."""
    assert validator.is_exact_dns_host("local") is False
    assert validator.is_exact_dns_host("minio.local") is False
    assert validator.is_denied_private_network_host("objects.example.example") is False
    contract = _valid_contract()
    contract["endpoint_policy"]["private_network_trust"] = "explicit_allowlist"
    contract["endpoint_policy"]["host_allowlist"] = ["minio.local"]
    contract["endpoint_policy"].pop("custom_endpoint", None)
    with pytest.raises(validator.ObjectStorageContractError, match="exact DNS"):
        validator.validate_contract(contract)


@pytest.mark.parametrize(
    "host",
    [
        "169.254.169.254.nip.io",
        "127.0.0.1.sslip.io",
        "10.0.0.1.xip.io",
        "metadata.lvh.me",
        "minio.localtest.me",
        "bucket.test",
        "objects.invalid",
    ],
)
def test_dns_rebinding_helper_suffixes_are_never_exact_hosts(host: str) -> None:
    """Rebinding helpers and RFC 6761 test names cannot enter any allowlist."""
    assert validator.is_exact_dns_host(host) is False
    contract = _valid_contract()
    contract["endpoint_policy"]["private_network_trust"] = "explicit_allowlist"
    contract["endpoint_policy"]["host_allowlist"] = [host]
    contract["endpoint_policy"].pop("custom_endpoint", None)
    with pytest.raises(validator.ObjectStorageContractError, match="exact DNS"):
        validator.validate_contract(contract)


@pytest.mark.parametrize(
    "host",
    [
        "169.254.169.254.attacker.example",
        "127.0.0.1.evil.example",
        "0xa.0xb.0xc.0xd.objects.example",
        "2851992574.attacker.example",
        "0x7f000001.attacker.example",
    ],
)
def test_embedded_ipv4_aliases_are_never_exact_hosts(host: str) -> None:
    """An IPv4 sequence or 32-bit alias remains a rebinding host on any suffix."""
    assert validator.host_embeds_ip_alias(host) is True
    assert validator.is_exact_dns_host(host) is False
    contract = _valid_contract()
    contract["endpoint_policy"]["private_network_trust"] = "explicit_allowlist"
    contract["endpoint_policy"]["host_allowlist"] = [host]
    contract["endpoint_policy"].pop("custom_endpoint", None)
    with pytest.raises(validator.ObjectStorageContractError, match="exact DNS"):
        validator.validate_contract(contract)


def test_embedded_ip_helper_keeps_octet_labels_and_oversize_integers() -> None:
    """Octet DNS labels stay valid; integers above 0xFFFFFFFF are not IPv4 aliases."""
    assert validator._integer_token_value("s3") is None
    assert validator._integer_token_value("1") == 1
    assert validator._integer_token_value("0x7f") == 127
    assert validator.host_embeds_ip_alias("1.s3.amazonaws.com") is False
    assert validator.host_embeds_ip_alias("1.2.3.example.com") is False
    assert validator.host_embeds_ip_alias("1.2.3.4294967296.example.com") is False
    assert validator.is_exact_dns_host("1.2.3.4294967296.example.com") is True


def test_dns_pinning_is_mandatory() -> None:
    """A later DNS TTL flip must not retarget an in-flight object transfer."""
    contract = _valid_contract()
    contract["endpoint_policy"]["dns_pinning"] = False
    with pytest.raises(
        validator.ObjectStorageContractError, match="dns_pinning must be true"
    ):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["endpoint_policy"].pop("dns_pinning", None)
    with pytest.raises(validator.ObjectStorageContractError, match="dns_pinning"):
        validator.validate_contract(contract)


def test_explicit_allowlist_still_admits_a_named_internal_host() -> None:
    """Operators may name one private DNS host after an explicit trust decision."""
    contract = _valid_contract()
    contract["endpoint_policy"]["private_network_trust"] = "explicit_allowlist"
    contract["endpoint_policy"]["host_allowlist"] = ["minio.internal"]
    contract["endpoint_policy"]["custom_endpoint"] = "https://minio.internal"
    validator.validate_contract(contract)
    contract["endpoint_policy"]["host_allowlist"] = ["minio.default.svc"]
    contract["endpoint_policy"]["custom_endpoint"] = "https://minio.default.svc"
    validator.validate_contract(contract)


@pytest.mark.parametrize(
    "host",
    [
        "instance-data",
        "instance-data.ec2.internal",
        "kubernetes.default.svc",
        "::1",
        "[::1]",
    ],
)
def test_metadata_cluster_and_ipv6_literals_are_never_exact_hosts(host: str) -> None:
    """Metadata, cluster-local, and IPv6 literals stay off the exact allowlist."""
    assert validator.is_exact_dns_host(host) is False


def test_tenant_purpose_bound_selection_is_mandatory() -> None:
    """Provider selection must stay tenant- and purpose-bound."""
    contract = _valid_contract()
    contract["tenant_purpose_bound"] = False
    with pytest.raises(
        validator.ObjectStorageContractError, match="tenant_purpose_bound must be true"
    ):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract.pop("tenant_purpose_bound", None)
    with pytest.raises(validator.ObjectStorageContractError, match="missing keys"):
        validator.validate_contract(contract)


def test_schema_encodes_value_level_closed_controls() -> None:
    """Portable schema consumers must see the same closed values as the validator."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    repository = schema["properties"]["repository"]
    assert repository["pattern"] == r"^ContextualWisdomLab/[A-Za-z0-9._-]*[A-Za-z0-9_-]$"
    hosts = schema["properties"]["endpoint_policy"]["properties"]["host_allowlist"]
    assert hosts["uniqueItems"] is True
    custom = schema["properties"]["endpoint_policy"]["properties"]["custom_endpoint"]
    assert custom["pattern"] == r"^https://"
    states = schema["properties"]["lifecycle"]["properties"]["states"]
    assert states["uniqueItems"] is True
    assert {item["contains"]["const"] for item in states["allOf"]} == set(
        validator.REQUIRED_LIFECYCLE_STATES
    )
    labels = schema["properties"]["observability"]["properties"][
        "high_cardinality_labels_forbid"
    ]
    assert labels["uniqueItems"] is True
    assert {item["contains"]["const"] for item in labels["allOf"]} == set(
        validator.FORBIDDEN_HIGH_CARDINALITY_LABELS
    )
    assert schema["properties"]["tenant_purpose_bound"]["const"] is True
    endpoint = schema["properties"]["endpoint_policy"]
    assert endpoint["properties"]["dns_pinning"]["const"] is True
    assert "dns_pinning" in endpoint["required"]
    lifecycle = schema["properties"]["lifecycle"]
    assert lifecycle["if"]["properties"]["consumed_implies_immediate_delete"][
        "const"
    ] is True
    assert lifecycle["then"]["properties"]["zero_retention_explicit"]["const"] is True


def test_product_acceptance_template_names_the_consumer_failure_lane() -> None:
    """Product repositories need the next write/read/delete proof, not more prose."""
    template = (
        ROOT / "docs" / "object-storage" / "PRODUCT_ACCEPTANCE_TEMPLATE.md"
    ).read_text(encoding="utf-8")
    assert "ContextualWisdomLab/naruon#1364" in template
    assert "write/read/delete" in template
    assert "partial" in template.lower()
    assert "timeout" in template.lower()
    assert "rebinding" in template.lower()
