#!/usr/bin/env python3
"""Fail-closed validator for organization object-storage contracts.

The central repository owns only the reusable policy and this check. Product
repositories keep their own S3 or S3-compatible adapters. The contract is
provider-neutral: AWS-managed S3 and HTTPS S3-compatible endpoints share one
``object_storage`` capability. CSAP and SOC 2 appear only as design
constraints, never as a certification claim.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1"
CAPABILITY = "object_storage"
MAX_CONTRACT_BYTES = 65536
ALLOWED_PROVIDER_CLASSES = frozenset({"aws_s3", "s3_compatible"})
ALLOWED_CREDENTIAL_MECHANISMS = frozenset(
    {"scoped_secret_registry", "workload_identity"}
)
ALLOWED_PRIVATE_NETWORK_TRUST = frozenset({"explicit_allowlist", "denied"})
ALLOWED_DIGESTS = frozenset({"sha256", "sha384", "sha512"})
REQUIRED_LIFECYCLE_STATES = (
    "pending",
    "available",
    "consumed",
    "archived",
    "held",
)
FORBIDDEN_HIGH_CARDINALITY_LABELS = frozenset(
    {"bucket", "object_key", "credential", "raw_pii"}
)
FORBIDDEN_EXACT_HOSTS = frozenset(
    {
        "localhost",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
        "instance-data.ec2.internal",
        "kubernetes.default.svc",
    }
)
ALWAYS_FORBIDDEN_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".invalid",
    ".test",
    ".nip.io",
    ".sslip.io",
    ".xip.io",
    ".lvh.me",
    ".localtest.me",
)
DENIED_PRIVATE_NETWORK_SUFFIXES = (
    ".internal",
    ".corp",
    ".lan",
    ".home",
    ".intranet",
    ".private",
    ".svc",
    ".localdomain",
)
MAX_TCP_PORT = 65535
MAX_DNS_HOST_LENGTH = 253
ALLOWED_TOP_LEVEL = (
    "schema_version",
    "capability",
    "repository",
    "provider_class",
    "endpoint_policy",
    "credentials",
    "permissions",
    "encryption",
    "integrity",
    "lifecycle",
    "rollback",
    "observability",
    "database_object_names",
    "tenant_purpose_bound",
    "assurance_posture",
)
ENDPOINT_POLICY_KEYS = (
    "transport",
    "host_allowlist",
    "allow_wildcards",
    "follow_redirects",
    "dns_pinning",
    "private_network_trust",
    "custom_endpoint",
)
CREDENTIAL_KEYS = (
    "broadcast",
    "browser_long_lived",
    "ambient_process_wide",
    "mechanism",
)
PERMISSION_KEYS = ("public_acls", "public_buckets", "least_privilege")
ENCRYPTION_KEYS = ("server_side",)
INTEGRITY_KEYS = ("content_length", "digest", "fail_closed_read")
LIFECYCLE_KEYS = (
    "states",
    "consumed_implies_immediate_delete",
    "zero_retention_explicit",
    "legal_hold_distinct",
)
ROLLBACK_KEYS = ("delete_customer_data_on_partial_migration",)
OBSERVABILITY_KEYS = ("high_cardinality_labels_forbid",)


class ObjectStorageContractError(ValueError):
    """Raised when a contract file fails a fail-closed policy check."""


def _reject_non_finite_json_constant(token: str) -> None:
    """Reject NaN and Infinity, which are not finite RFC 8259 numbers."""
    raise ObjectStorageContractError(
        f"contract contains a non-finite JSON number: {token}"
    )


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build an object while rejecting duplicate JSON keys."""
    seen: set[str] = set()
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise ObjectStorageContractError(f"duplicate object key {key!r}")
        seen.add(key)
        result[key] = value
    return result


def _is_dns_label_char(char: str) -> bool:
    """Return whether *char* is an ASCII lowercase DNS label character."""
    return char.isascii() and (char.islower() or char.isdigit() or char == "-")


def _label_is_integer_token(label: str) -> bool:
    """Return whether *label* is a decimal or ``0x`` hexadecimal integer token."""
    if label.isdigit() and label.isascii():
        return True
    return (
        label.startswith("0x")
        and len(label) > 2
        and all(char in "0123456789abcdef" for char in label[2:])
    )


def _integer_token_value(label: str) -> int | None:
    """Return the integer value of a decimal or ``0x`` hex DNS label."""
    if not _label_is_integer_token(label):
        return None
    if label.startswith("0x"):
        return int(label, 16)
    return int(label)


def _is_ip_literal_or_alias(host: str) -> bool:
    """Return whether *host* is an IP literal or a numeric IP alias."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return True
    return all(_label_is_integer_token(label) for label in host.split("."))


def host_embeds_ip_alias(host: str) -> bool:
    """Return whether *host* embeds an IPv4 literal or a 32-bit numeric alias.

    A single numeric DNS label is still allowed when it is an octet (0-255).
    A 32-bit decimal or hexadecimal alias, or four consecutive octet labels,
    is a rebinding hostname even when the remaining labels are ordinary DNS.
    Integers above ``0xFFFFFFFF`` are not IPv4 aliases.
    """
    labels = host.split(".")
    for label in labels:
        value = _integer_token_value(label)
        if value is not None and 255 < value <= 0xFFFFFFFF:
            return True
    for index in range(len(labels) - 3):
        octets = [_integer_token_value(label) for label in labels[index : index + 4]]
        if all(value is not None and value <= 255 for value in octets):
            return True
    return False


def host_matches_suffix(host: str, suffixes: tuple[str, ...]) -> bool:
    """Return whether *host* equals or ends with one DNS suffix in *suffixes*."""
    for suffix in suffixes:
        bare = suffix[1:]
        if host == bare or host.endswith(suffix):
            return True
    return False


def is_denied_private_network_host(host: str) -> bool:
    """Return whether *host* is implicit-local under a denied private-network policy."""
    if "." not in host:
        return True
    return host_matches_suffix(host, DENIED_PRIVATE_NETWORK_SUFFIXES)


def is_exact_dns_host(host: str) -> bool:
    """Return whether *host* is one exact lowercase DNS name.

    Localhost, link-local metadata names, IP literals, decimal or hexadecimal
    IP aliases, embedded IPv4 sequences, Unicode, case aliases, RFC 6761
    ``.test`` / ``.invalid``, and DNS-rebinding helper suffixes are not exact
    allowlist members.
    """
    if not isinstance(host, str) or not host or len(host) > MAX_DNS_HOST_LENGTH:
        return False
    if any(char in host for char in "*:/@ \t\\"):
        return False
    if host.startswith(".") or host.endswith("."):
        return False
    if host != host.lower():
        return False
    if host in FORBIDDEN_EXACT_HOSTS or host_matches_suffix(
        host, ALWAYS_FORBIDDEN_HOST_SUFFIXES
    ):
        return False
    if _is_ip_literal_or_alias(host) or host_embeds_ip_alias(host):
        return False
    labels = host.split(".")
    for label in labels:
        if not label or len(label) > 63:
            return False
        if label.startswith("-") or label.endswith("-"):
            return False
        if not all(_is_dns_label_char(char) for char in label):
            return False
    return True


def parse_https_endpoint_host(url: str) -> str:
    """Return the exact host of an HTTPS endpoint, rejecting redirects and userinfo."""
    if not url.startswith("https://"):
        raise ObjectStorageContractError(
            "custom endpoints must use https:// and must not follow redirects"
        )
    remainder = url[len("https://") :]
    if not remainder or remainder.startswith("/"):
        raise ObjectStorageContractError("custom endpoint is missing a host")
    authority = remainder.split("/", 1)[0]
    if "@" in authority:
        raise ObjectStorageContractError(
            "custom endpoints must not embed credentials"
        )
    host, separator, port = authority.partition(":")
    if separator and (
        not port.isdigit()
        or not port.isascii()
        or port == "0"
        or int(port) > MAX_TCP_PORT
    ):
        raise ObjectStorageContractError("custom endpoint port is invalid")
    if not is_exact_dns_host(host):
        raise ObjectStorageContractError(
            f"custom endpoint host {host!r} is not an exact DNS name"
        )
    return host


def load_contract_bytes(raw: bytes) -> dict[str, Any]:
    """Parse a bounded UTF-8 JSON object and reject duplicate keys."""
    if len(raw) > MAX_CONTRACT_BYTES:
        raise ObjectStorageContractError("contract exceeds 65536 bytes")
    if not raw:
        raise ObjectStorageContractError("contract is empty")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ObjectStorageContractError("contract is not UTF-8") from exc
    if "\x00" in text:
        raise ObjectStorageContractError("contract contains a NUL byte")
    decoder = json.JSONDecoder(
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=_reject_non_finite_json_constant,
    )
    try:
        data, index = decoder.raw_decode(text)
    except json.JSONDecodeError as exc:
        raise ObjectStorageContractError(
            f"contract is not JSON: {exc.msg}"
        ) from exc
    if text[index:].strip():
        raise ObjectStorageContractError("contract has trailing JSON data")
    if not isinstance(data, dict):
        raise ObjectStorageContractError("contract root must be a JSON object")
    return data


def load_contract_path(path: Path) -> dict[str, Any]:
    """Read one contract file through the bounded UTF-8 loader."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ObjectStorageContractError(f"cannot read {path}: {exc}") from exc
    return load_contract_bytes(raw)


def require_mapping(value: Any, name: str) -> dict[str, Any]:
    """Return *value* when it is an object, otherwise fail closed."""
    if not isinstance(value, dict):
        raise ObjectStorageContractError(f"{name} must be an object")
    return value


def require_bool(value: Any, name: str, expected: bool) -> None:
    """Require an exact boolean policy value."""
    if value is not expected:
        raise ObjectStorageContractError(f"{name} must be {str(expected).lower()}")


def require_text(value: Any, name: str) -> str:
    """Return a nonempty string or fail closed."""
    if not isinstance(value, str) or not value:
        raise ObjectStorageContractError(f"{name} must be a nonempty string")
    return value


def require_allowed(value: Any, name: str, allowed: frozenset[str]) -> str:
    """Return *value* when it is one of the closed allowed strings."""
    text = require_text(value, name)
    if text not in allowed:
        raise ObjectStorageContractError(
            f"{name} must be one of {sorted(allowed)}"
        )
    return text


def reject_unknown_keys(
    mapping: Mapping[str, Any], allowed: Sequence[str], name: str
) -> None:
    """Reject keys that are not in the closed allowlist."""
    unknown = sorted(set(mapping) - set(allowed))
    if unknown:
        raise ObjectStorageContractError(f"unknown {name} keys: {unknown}")


def validate_endpoint_policy(policy: Mapping[str, Any]) -> None:
    """Validate HTTPS, exact-host allowlists, and explicit private-network trust."""
    reject_unknown_keys(policy, ENDPOINT_POLICY_KEYS, "endpoint_policy")
    if require_text(policy.get("transport"), "endpoint_policy.transport") != "https":
        raise ObjectStorageContractError("endpoint_policy.transport must be https")
    require_bool(policy.get("allow_wildcards"), "endpoint_policy.allow_wildcards", False)
    require_bool(
        policy.get("follow_redirects"), "endpoint_policy.follow_redirects", False
    )
    require_bool(policy.get("dns_pinning"), "endpoint_policy.dns_pinning", True)
    require_allowed(
        policy.get("private_network_trust"),
        "endpoint_policy.private_network_trust",
        ALLOWED_PRIVATE_NETWORK_TRUST,
    )
    hosts = policy.get("host_allowlist")
    if not isinstance(hosts, list) or not hosts:
        raise ObjectStorageContractError(
            "endpoint_policy.host_allowlist must be a nonempty list"
        )
    seen: set[str] = set()
    private_network_trust = policy.get("private_network_trust")
    for host in hosts:
        if not isinstance(host, str) or not is_exact_dns_host(host):
            raise ObjectStorageContractError(
                f"endpoint host {host!r} is not an exact DNS name"
            )
        if private_network_trust == "denied" and is_denied_private_network_host(host):
            if "." not in host:
                raise ObjectStorageContractError(
                    f"endpoint host {host!r} is a single-label name"
                )
            raise ObjectStorageContractError(
                f"endpoint host {host!r} is a private-network name"
            )
        if host in seen:
            raise ObjectStorageContractError(f"duplicate endpoint host {host!r}")
        seen.add(host)
    custom = policy.get("custom_endpoint")
    if custom is None:
        return
    host = parse_https_endpoint_host(
        require_text(custom, "endpoint_policy.custom_endpoint")
    )
    if host not in seen:
        raise ObjectStorageContractError(
            "custom endpoint host is not on the exact allowlist"
        )


def validate_credentials(credentials: Mapping[str, Any]) -> None:
    """Reject broadcast, browser, and ambient process-wide credentials."""
    reject_unknown_keys(credentials, CREDENTIAL_KEYS, "credentials")
    require_bool(credentials.get("broadcast"), "credentials.broadcast", False)
    require_bool(
        credentials.get("browser_long_lived"),
        "credentials.browser_long_lived",
        False,
    )
    require_bool(
        credentials.get("ambient_process_wide"),
        "credentials.ambient_process_wide",
        False,
    )
    require_allowed(
        credentials.get("mechanism"),
        "credentials.mechanism",
        ALLOWED_CREDENTIAL_MECHANISMS,
    )


def validate_permissions(permissions: Mapping[str, Any]) -> None:
    """Require least privilege and prohibit public ACLs or public buckets."""
    reject_unknown_keys(permissions, PERMISSION_KEYS, "permissions")
    require_bool(permissions.get("public_acls"), "permissions.public_acls", False)
    require_bool(
        permissions.get("public_buckets"), "permissions.public_buckets", False
    )
    require_bool(
        permissions.get("least_privilege"), "permissions.least_privilege", True
    )


def validate_encryption(encryption: Mapping[str, Any]) -> None:
    """Require server-side encryption without claiming a certification."""
    reject_unknown_keys(encryption, ENCRYPTION_KEYS, "encryption")
    if (
        require_text(encryption.get("server_side"), "encryption.server_side")
        != "required"
    ):
        raise ObjectStorageContractError("encryption.server_side must be required")


def validate_integrity(integrity: Mapping[str, Any]) -> None:
    """Require content-length plus SHA-256 or stronger fail-closed read checks."""
    reject_unknown_keys(integrity, INTEGRITY_KEYS, "integrity")
    require_bool(integrity.get("content_length"), "integrity.content_length", True)
    require_allowed(integrity.get("digest"), "integrity.digest", ALLOWED_DIGESTS)
    require_bool(
        integrity.get("fail_closed_read"), "integrity.fail_closed_read", True
    )


def validate_lifecycle(lifecycle: Mapping[str, Any]) -> None:
    """Keep consumed, legal-hold, and retention states distinct."""
    reject_unknown_keys(lifecycle, LIFECYCLE_KEYS, "lifecycle")
    states = lifecycle.get("states")
    if not isinstance(states, list):
        raise ObjectStorageContractError("lifecycle.states must be a list")
    missing = [state for state in REQUIRED_LIFECYCLE_STATES if state not in states]
    if missing:
        raise ObjectStorageContractError(
            f"lifecycle.states is missing required states: {missing}"
        )
    if any(not isinstance(state, str) or not state for state in states):
        raise ObjectStorageContractError(
            "lifecycle.states must contain nonempty strings"
        )
    consumed_deletes = lifecycle.get("consumed_implies_immediate_delete")
    zero_retention = lifecycle.get("zero_retention_explicit")
    if consumed_deletes is True and zero_retention is not True:
        raise ObjectStorageContractError(
            "consumed must not imply immediate deletion unless zero retention is explicit"
        )
    if consumed_deletes is not True and consumed_deletes is not False:
        raise ObjectStorageContractError(
            "lifecycle.consumed_implies_immediate_delete must be a boolean"
        )
    if zero_retention is not True and zero_retention is not False:
        raise ObjectStorageContractError(
            "lifecycle.zero_retention_explicit must be a boolean"
        )
    require_bool(
        lifecycle.get("legal_hold_distinct"),
        "lifecycle.legal_hold_distinct",
        True,
    )


def validate_rollback(rollback: Mapping[str, Any]) -> None:
    """Refuse rollback that deletes customer data after a partial migration."""
    reject_unknown_keys(rollback, ROLLBACK_KEYS, "rollback")
    require_bool(
        rollback.get("delete_customer_data_on_partial_migration"),
        "rollback.delete_customer_data_on_partial_migration",
        False,
    )


def validate_observability(observability: Mapping[str, Any]) -> None:
    """Forbid high-cardinality bucket, key, credential, and raw-PII labels.

    Operational PII remains usable through the owning product. This check only
    blocks unbounded telemetry labels; it is not a blanket PII mask.
    """
    reject_unknown_keys(observability, OBSERVABILITY_KEYS, "observability")
    labels = observability.get("high_cardinality_labels_forbid")
    if not isinstance(labels, list):
        raise ObjectStorageContractError(
            "observability.high_cardinality_labels_forbid must be a list"
        )
    seen_labels: set[str] = set()
    for label in labels:
        if not isinstance(label, str) or not label:
            raise ObjectStorageContractError(
                "observability.high_cardinality_labels_forbid must contain nonempty strings"
            )
        if label in seen_labels:
            raise ObjectStorageContractError(
                f"duplicate observability label {label!r}"
            )
        seen_labels.add(label)
    missing = sorted(FORBIDDEN_HIGH_CARDINALITY_LABELS - seen_labels)
    if missing:
        raise ObjectStorageContractError(
            "observability must forbid high-cardinality labels: "
            f"{missing}"
        )


def is_cwl_repository(repository: str) -> bool:
    """Return whether *repository* is an owner/name pair in this organization."""
    owner, separator, name = repository.partition("/")
    if separator != "/" or owner != "ContextualWisdomLab" or not name:
        return False
    if "/" in name or name.endswith("."):
        return False
    return all(char.isalnum() or char in "._-" for char in name)


def validate_contract(data: Mapping[str, Any]) -> None:
    """Validate one loaded object-storage contract object."""
    reject_unknown_keys(data, ALLOWED_TOP_LEVEL, "contract")
    missing = [key for key in ALLOWED_TOP_LEVEL if key not in data]
    if missing:
        raise ObjectStorageContractError(f"contract is missing keys: {missing}")
    if require_text(data.get("schema_version"), "schema_version") != SCHEMA_VERSION:
        raise ObjectStorageContractError("schema_version must be 1")
    if require_text(data.get("capability"), "capability") != CAPABILITY:
        raise ObjectStorageContractError("capability must be object_storage")
    repository = require_text(data.get("repository"), "repository")
    if not is_cwl_repository(repository):
        raise ObjectStorageContractError(
            "repository must be ContextualWisdomLab/<name>"
        )
    require_allowed(
        data.get("provider_class"), "provider_class", ALLOWED_PROVIDER_CLASSES
    )
    validate_endpoint_policy(
        require_mapping(data.get("endpoint_policy"), "endpoint_policy")
    )
    validate_credentials(require_mapping(data.get("credentials"), "credentials"))
    validate_permissions(require_mapping(data.get("permissions"), "permissions"))
    validate_encryption(require_mapping(data.get("encryption"), "encryption"))
    validate_integrity(require_mapping(data.get("integrity"), "integrity"))
    validate_lifecycle(require_mapping(data.get("lifecycle"), "lifecycle"))
    validate_rollback(require_mapping(data.get("rollback"), "rollback"))
    validate_observability(
        require_mapping(data.get("observability"), "observability")
    )
    if (
        require_text(data.get("database_object_names"), "database_object_names")
        != "multiword_snake_case"
    ):
        raise ObjectStorageContractError(
            "database_object_names must be multiword_snake_case"
        )
    require_bool(
        data.get("tenant_purpose_bound"), "tenant_purpose_bound", True
    )
    if (
        require_text(data.get("assurance_posture"), "assurance_posture")
        != "design_constraints_only"
    ):
        raise ObjectStorageContractError(
            "assurance_posture must be design_constraints_only; "
            "CSAP and SOC 2 are design constraints, not certifications"
        )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the validator CLI."""
    parser = argparse.ArgumentParser(
        description="Validate a CWL object-storage contract."
    )
    parser.add_argument(
        "--path",
        required=True,
        help="Path to the JSON contract file.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Load and validate one contract path, returning a process exit code."""
    args = parse_args(argv)
    try:
        validate_contract(load_contract_path(Path(args.path)))
    except ObjectStorageContractError as exc:
        print(f"object-storage contract failed: {exc}", file=sys.stderr)
        return 1
    print("object-storage contract passed")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
