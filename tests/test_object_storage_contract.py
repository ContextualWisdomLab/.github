"""Contracts for the organization-wide object-storage policy check."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ci import validate_object_storage_contract as validator


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "schemas" / "examples" / "cwl-object-storage-v1.example.json"
SCHEMA = ROOT / "schemas" / "cwl-object-storage-v1.schema.json"
POLICY = ROOT / "docs" / "object-storage" / "CWL_OBJECT_STORAGE_CONTRACT.md"
DOCTORING = ROOT / "docs" / "doctoring" / "object-storage-contract.md"
CHANGELOG = ROOT / "CHANGELOG.md"
ARCHITECTURE = ROOT / "ARCHITECTURE.md"


def _valid_contract() -> dict:
    """Return a mutable copy of the checked-in valid example."""
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def test_checked_in_example_passes_the_executable_policy() -> None:
    """The published naruon-shaped example must satisfy the fail-closed check."""
    validator.validate_contract(validator.load_contract_path(EXAMPLE))
    assert validator.main(["--path", str(EXAMPLE)]) == 0


def test_schema_required_keys_match_production_constants() -> None:
    """The JSON Schema must not drift from the executable allowlist."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["required"] == list(validator.ALLOWED_TOP_LEVEL)
    assert set(schema["properties"]) == set(validator.ALLOWED_TOP_LEVEL)
    assert schema["additionalProperties"] is False


def test_reject_duplicate_keys_and_non_object_root() -> None:
    """Duplicate keys and array roots are untrusted evidence."""
    with pytest.raises(validator.ObjectStorageContractError, match="duplicate"):
        validator.load_contract_bytes(b'{"schema_version":"1","schema_version":"2"}')
    with pytest.raises(validator.ObjectStorageContractError, match="JSON object"):
        validator.load_contract_bytes(b"[]")


def test_load_contract_bytes_rejects_empty_oversize_encoding_and_trailing() -> None:
    """The loader must fail closed before any policy field is trusted."""
    with pytest.raises(validator.ObjectStorageContractError, match="empty"):
        validator.load_contract_bytes(b"")
    with pytest.raises(validator.ObjectStorageContractError, match="65536"):
        validator.load_contract_bytes(b"{" + (b"a" * 65537))
    with pytest.raises(validator.ObjectStorageContractError, match="UTF-8"):
        validator.load_contract_bytes(b"\xff\xfe")
    with pytest.raises(validator.ObjectStorageContractError, match="NUL"):
        validator.load_contract_bytes(b'{"a":"x\x00y"}')
    with pytest.raises(validator.ObjectStorageContractError, match="not JSON"):
        validator.load_contract_bytes(b"{")
    with pytest.raises(validator.ObjectStorageContractError, match="trailing"):
        validator.load_contract_bytes(b'{"schema_version":"1"}{}')


def test_load_contract_path_reports_unreadable_files(tmp_path: Path) -> None:
    """A missing path is a contract failure, not a crash."""
    missing = tmp_path / "absent.json"
    with pytest.raises(validator.ObjectStorageContractError, match="cannot read"):
        validator.load_contract_path(missing)
    assert validator.main(["--path", str(missing)]) == 1


def test_is_exact_dns_host_rejects_wildcards_ports_and_empty_labels() -> None:
    """Exact-host allowlists cannot contain wildcard or port syntax."""
    assert validator.is_exact_dns_host("s3.ap-northeast-2.amazonaws.com")
    assert validator.is_exact_dns_host("localhost") is False
    assert validator.is_exact_dns_host("") is False
    assert validator.is_exact_dns_host(None) is False
    assert validator.is_exact_dns_host("a..b") is False
    assert validator.is_exact_dns_host("*.example.com") is False
    assert validator.is_exact_dns_host("example.com:443") is False
    assert validator.is_exact_dns_host(".example.com") is False
    assert validator.is_exact_dns_host("example.com.") is False
    assert validator.is_exact_dns_host("-bad.example.com") is False
    assert validator.is_exact_dns_host("bad-.example.com") is False
    assert validator.is_exact_dns_host("bad_name.example.com") is False
    assert validator.is_exact_dns_host("a" * 64 + ".example.com") is False


def test_parse_https_endpoint_host_rejects_http_userinfo_and_bad_ports() -> None:
    """Custom endpoints stay HTTPS, credential-free, and exact-host."""
    assert (
        validator.parse_https_endpoint_host("https://objects.example.example/path")
        == "objects.example.example"
    )
    assert (
        validator.parse_https_endpoint_host("https://objects.example.example:9000")
        == "objects.example.example"
    )
    with pytest.raises(validator.ObjectStorageContractError, match="https://"):
        validator.parse_https_endpoint_host("http://objects.example.example")
    with pytest.raises(validator.ObjectStorageContractError, match="missing a host"):
        validator.parse_https_endpoint_host("https://")
    with pytest.raises(validator.ObjectStorageContractError, match="missing a host"):
        validator.parse_https_endpoint_host("https:///bucket")
    with pytest.raises(validator.ObjectStorageContractError, match="embed credentials"):
        validator.parse_https_endpoint_host("https://user:pass@objects.example.example")
    with pytest.raises(validator.ObjectStorageContractError, match="port"):
        validator.parse_https_endpoint_host("https://objects.example.example:0")
    with pytest.raises(validator.ObjectStorageContractError, match="port"):
        validator.parse_https_endpoint_host("https://objects.example.example:abc")
    with pytest.raises(validator.ObjectStorageContractError, match="exact DNS"):
        validator.parse_https_endpoint_host("https://*.example.example")


def test_validate_contract_accepts_zero_retention_only_when_explicit() -> None:
    """Consumed-delete is allowed only when the product opts into zero retention."""
    contract = _valid_contract()
    contract["lifecycle"]["consumed_implies_immediate_delete"] = True
    with pytest.raises(validator.ObjectStorageContractError, match="zero retention"):
        validator.validate_contract(contract)
    contract["lifecycle"]["zero_retention_explicit"] = True
    validator.validate_contract(contract)


def test_validate_contract_rejects_policy_regressions() -> None:
    """Each required fail-closed control must have a unique rejection."""
    cases = [
        ("schema_version", "2", "schema_version"),
        ("capability", "s3", "object_storage"),
        ("repository", "other/naruon", "ContextualWisdomLab"),
        ("provider_class", "gcs", "provider_class"),
        ("database_object_names", "camelCase", "multiword_snake_case"),
        ("tenant_purpose_bound", False, "tenant_purpose_bound"),
        ("assurance_posture", "certified", "design_constraints_only"),
    ]
    for field, value, needle in cases:
        contract = _valid_contract()
        contract[field] = value
        with pytest.raises(validator.ObjectStorageContractError, match=needle):
            validator.validate_contract(contract)


def test_is_cwl_repository_rejects_nested_and_dot_names() -> None:
    """Repository identity is a single owner/name pair in this organization."""
    assert validator.is_cwl_repository("ContextualWisdomLab/naruon")
    assert validator.is_cwl_repository("ContextualWisdomLab/.github")
    assert not validator.is_cwl_repository("naruon")
    assert not validator.is_cwl_repository("ContextualWisdomLab/")
    assert not validator.is_cwl_repository("ContextualWisdomLab/naruon/extra")
    assert not validator.is_cwl_repository("ContextualWisdomLab/.hidden.")
    assert not validator.is_cwl_repository("ContextualWisdomLab/bad name")


def test_nested_objects_must_be_objects_and_closed() -> None:
    """Unknown nested keys and non-objects fail before a weaker field is read."""
    contract = _valid_contract()
    contract["endpoint_policy"] = []
    with pytest.raises(validator.ObjectStorageContractError, match="endpoint_policy"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["endpoint_policy"]["extra"] = True
    with pytest.raises(validator.ObjectStorageContractError, match="unknown"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    del contract["integrity"]
    with pytest.raises(validator.ObjectStorageContractError, match="missing keys"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["unknown"] = True
    with pytest.raises(validator.ObjectStorageContractError, match="unknown"):
        validator.validate_contract(contract)


def test_endpoint_policy_https_exact_hosts_and_no_redirects() -> None:
    """HTTPS, exact hosts, and no automatic redirects are mandatory."""
    contract = _valid_contract()
    contract["endpoint_policy"]["transport"] = "http"
    with pytest.raises(validator.ObjectStorageContractError, match="https"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["endpoint_policy"]["allow_wildcards"] = True
    with pytest.raises(validator.ObjectStorageContractError, match="allow_wildcards"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["endpoint_policy"]["follow_redirects"] = True
    with pytest.raises(validator.ObjectStorageContractError, match="follow_redirects"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["endpoint_policy"]["private_network_trust"] = "rfc1918"
    with pytest.raises(validator.ObjectStorageContractError, match="private_network"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["endpoint_policy"]["host_allowlist"] = []
    with pytest.raises(validator.ObjectStorageContractError, match="host_allowlist"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["endpoint_policy"]["host_allowlist"] = ["*.example.com"]
    with pytest.raises(validator.ObjectStorageContractError, match="exact DNS"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["endpoint_policy"]["host_allowlist"] = [
        "objects.example.example",
        "objects.example.example",
    ]
    with pytest.raises(validator.ObjectStorageContractError, match="duplicate"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["endpoint_policy"]["custom_endpoint"] = "https://other.example.example"
    with pytest.raises(validator.ObjectStorageContractError, match="allowlist"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    del contract["endpoint_policy"]["custom_endpoint"]
    validator.validate_contract(contract)


def test_credentials_permissions_encryption_and_integrity_gates() -> None:
    """Public buckets, ambient credentials, and weak integrity fail closed."""
    contract = _valid_contract()
    contract["credentials"]["broadcast"] = True
    with pytest.raises(validator.ObjectStorageContractError, match="broadcast"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["credentials"]["browser_long_lived"] = True
    with pytest.raises(validator.ObjectStorageContractError, match="browser"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["credentials"]["ambient_process_wide"] = True
    with pytest.raises(validator.ObjectStorageContractError, match="ambient"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["credentials"]["mechanism"] = "os.getenv"
    with pytest.raises(validator.ObjectStorageContractError, match="mechanism"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["permissions"]["public_acls"] = True
    with pytest.raises(validator.ObjectStorageContractError, match="public_acls"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["permissions"]["public_buckets"] = True
    with pytest.raises(validator.ObjectStorageContractError, match="public_buckets"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["permissions"]["least_privilege"] = False
    with pytest.raises(validator.ObjectStorageContractError, match="least_privilege"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["encryption"]["server_side"] = "optional"
    with pytest.raises(validator.ObjectStorageContractError, match="server_side"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["integrity"]["content_length"] = False
    with pytest.raises(validator.ObjectStorageContractError, match="content_length"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["integrity"]["digest"] = "md5"
    with pytest.raises(validator.ObjectStorageContractError, match="digest"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["integrity"]["fail_closed_read"] = False
    with pytest.raises(validator.ObjectStorageContractError, match="fail_closed_read"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["integrity"]["digest"] = "sha512"
    validator.validate_contract(contract)


def test_lifecycle_rollback_and_observability_gates() -> None:
    """Retention, rollback, and telemetry labels stay fail closed."""
    contract = _valid_contract()
    contract["lifecycle"]["states"] = ["pending"]
    with pytest.raises(validator.ObjectStorageContractError, match="missing required"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["lifecycle"]["states"] = "pending"
    with pytest.raises(validator.ObjectStorageContractError, match="must be a list"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["lifecycle"]["states"] = [
        "pending",
        "available",
        "consumed",
        "archived",
        "held",
        "",
    ]
    with pytest.raises(validator.ObjectStorageContractError, match="nonempty"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["lifecycle"]["consumed_implies_immediate_delete"] = "yes"
    with pytest.raises(validator.ObjectStorageContractError, match="boolean"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["lifecycle"]["zero_retention_explicit"] = "yes"
    with pytest.raises(validator.ObjectStorageContractError, match="boolean"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["lifecycle"]["legal_hold_distinct"] = False
    with pytest.raises(validator.ObjectStorageContractError, match="legal_hold"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["rollback"]["delete_customer_data_on_partial_migration"] = True
    with pytest.raises(validator.ObjectStorageContractError, match="partial"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["observability"]["high_cardinality_labels_forbid"] = ["bucket"]
    with pytest.raises(validator.ObjectStorageContractError, match="raw_pii"):
        validator.validate_contract(contract)
    contract = _valid_contract()
    contract["observability"]["high_cardinality_labels_forbid"] = "bucket"
    with pytest.raises(validator.ObjectStorageContractError, match="must be a list"):
        validator.validate_contract(contract)


def test_require_text_and_cli_success_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Empty strings and successful CLI output stay explicit."""
    with pytest.raises(validator.ObjectStorageContractError, match="nonempty"):
        validator.require_text("", "field")
    with pytest.raises(validator.ObjectStorageContractError, match="nonempty"):
        validator.require_text(1, "field")
    destination = tmp_path / "contract.json"
    destination.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    assert validator.main(["--path", str(destination)]) == 0
    assert "object-storage contract passed" in capsys.readouterr().out


def test_policy_and_doctoring_record_buyer_visible_controls() -> None:
    """Prose must name the executable check, naruon consumer, and APA 7 sources."""
    policy = POLICY.read_text(encoding="utf-8")
    doctoring = DOCTORING.read_text(encoding="utf-8")
    changelog = CHANGELOG.read_text(encoding="utf-8")
    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    assert "object_storage" in policy
    assert "ContextualWisdomLab/naruon#1364" in policy
    assert "scripts/ci/validate_object_storage_contract.py" in policy
    assert "design constraints" in policy.lower()
    assert "not a blanket PII mask" in policy
    assert "tenant- and purpose-bound" in policy
    assert "DNS pinning" in policy
    assert "PRODUCT_ACCEPTANCE_TEMPLATE.md" in policy
    assert "APA 7" in doctoring or "References (APA 7th)" in doctoring
    assert "Amazon Web Services" in doctoring
    assert "Jackson" in doctoring
    assert "CWE-918" in doctoring
    assert "object-storage contract" in changelog
    assert "object-storage" in architecture.lower()
