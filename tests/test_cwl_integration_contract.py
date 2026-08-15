"""Contract tests for the CWL organization integration profile.

These tests intentionally use only the Python standard library so that the
central contract can be verified without adding a runtime dependency.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
EVENT_SCHEMA = ROOT / "schemas" / "cwl-event-envelope-v1.schema.json"
COMMAND_SCHEMA = ROOT / "schemas" / "cwl-command-envelope-v1.schema.json"
EVENT_EXAMPLE = ROOT / "schemas" / "examples" / "cwl-event-envelope-v1.example.json"
COMMAND_EXAMPLE = ROOT / "schemas" / "examples" / "cwl-command-envelope-v1.example.json"
CONTRACT = ROOT / "docs" / "integration" / "CWL_ECOSYSTEM_INTEGRATION_CONTRACT.md"
DOCTORING = ROOT / "docs" / "doctoring" / "ecosystem-integration-standards.md"


def _load(path: Path) -> dict:
    """Load a JSON contract fixture from *path*."""

    return json.loads(path.read_text(encoding="utf-8"))


def _assert_uri_reference(value: str, path: str) -> None:
    """Assert that *value* is a bounded URI-reference without whitespace."""

    assert not any(character.isspace() for character in value), path
    parsed = urlsplit(value)
    assert parsed.scheme or parsed.path, path


def _assert_date_time(value: str, path: str) -> None:
    """Assert that *value* is an offset-aware RFC 3339-compatible timestamp."""

    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    assert parsed.tzinfo is not None, path


def _assert_profile_instance(instance: object, schema: dict, path: str = "$") -> None:
    """Validate the JSON Schema subset used by the two CWL v1 envelopes."""

    if "const" in schema:
        assert instance == schema["const"], path

    expected_type = schema.get("type")
    if expected_type == "object":
        assert isinstance(instance, dict), path
        properties = schema.get("properties", {})
        required = set(schema.get("required", ()))
        assert required <= set(instance), path
        if schema.get("additionalProperties") is False:
            assert set(instance) <= set(properties), path
        for name, value in instance.items():
            if name in properties:
                _assert_profile_instance(value, properties[name], f"{path}.{name}")
        return

    if expected_type == "string":
        assert isinstance(instance, str), path
        assert len(instance) >= schema.get("minLength", 0), path
        if "maxLength" in schema:
            assert len(instance) <= schema["maxLength"], path
        if "pattern" in schema:
            assert re.fullmatch(schema["pattern"], instance), path
        if schema.get("format") == "date-time":
            _assert_date_time(instance, path)
        elif schema.get("format") == "uri-reference":
            _assert_uri_reference(instance, path)


def _assert_invalid(instance: object, schema: dict) -> None:
    """Assert that *instance* is rejected by the CWL profile validator."""

    try:
        _assert_profile_instance(instance, schema)
    except (AssertionError, ValueError):
        return
    raise AssertionError("profile validator unexpectedly accepted invalid instance")


def _traceparent_schema(schema: dict) -> dict:
    """Return the traceparent property from either envelope schema."""

    if "traceparent" in schema["properties"]:
        return schema["properties"]["traceparent"]
    return schema["properties"]["data"]["properties"]["metadata"]["properties"]["traceparent"]


def test_shared_schemas_use_json_schema_2020_12() -> None:
    """Shared JSON schemas must remain on the organization Draft 2020-12 baseline."""

    for path in (EVENT_SCHEMA, COMMAND_SCHEMA):
        schema = _load(path)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"].startswith("https://contextualwisdomlab.github.io/schemas/")


def test_examples_validate_against_declared_profiles() -> None:
    """The published positive examples must satisfy their complete CWL profiles."""

    _assert_profile_instance(_load(EVENT_EXAMPLE), _load(EVENT_SCHEMA))
    _assert_profile_instance(_load(COMMAND_EXAMPLE), _load(COMMAND_SCHEMA))


def test_event_profile_pins_cloudevents_1_0_and_uuidv7() -> None:
    """The event profile must bind CloudEvents 1.0 and UUIDv7 identifiers."""

    schema = _load(EVENT_SCHEMA)
    example = _load(EVENT_EXAMPLE)

    assert schema["properties"]["specversion"]["const"] == "1.0"
    assert example["specversion"] == "1.0"
    uuid_pattern = schema["properties"]["id"]["pattern"]
    assert re.fullmatch(uuid_pattern, example["id"])
    assert example["datacontenttype"] == "application/json"


def test_event_example_contains_required_cwl_metadata() -> None:
    """The event example must cover every required CWL metadata field."""

    schema = _load(EVENT_SCHEMA)
    example = _load(EVENT_EXAMPLE)
    metadata_schema = schema["properties"]["data"]["properties"]["metadata"]
    metadata = example["data"]["metadata"]

    assert set(metadata_schema["required"]) <= set(metadata)
    assert example["time"] == metadata["occurred_at"]
    assert example["subject"] == metadata["subject_reference"]
    assert metadata["tenant_id"]
    assert metadata["purpose_code"]
    assert metadata["provenance_reference"]


def test_command_example_contains_required_control_context() -> None:
    """Commands must include authorization context, idempotency, and provenance."""

    schema = _load(COMMAND_SCHEMA)
    example = _load(COMMAND_EXAMPLE)

    assert set(schema["required"]) <= set(example)
    assert len(example["idempotency_key"]) >= 16
    for name in ("command_id", "correlation_id", "causation_id"):
        assert re.fullmatch(schema["properties"][name]["pattern"], example[name])


def test_traceparent_profile_rejects_forbidden_identifiers_and_flags() -> None:
    """Trace Context v1 must reject invalid IDs and nonzero reserved flag bits."""

    valid = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    invalid = (
        "ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        "00-00000000000000000000000000000000-00f067aa0ba902b7-01",
        "00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01",
        "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-02",
        "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-ff",
    )

    for schema_path in (EVENT_SCHEMA, COMMAND_SCHEMA):
        pattern = _traceparent_schema(_load(schema_path))["pattern"]
        assert re.fullmatch(pattern, valid)
        assert all(re.fullmatch(pattern, candidate) is None for candidate in invalid)


def test_type_profile_rejects_empty_or_punctuated_segments() -> None:
    """Event and command types must use non-empty lowercase snake-case segments."""

    valid = "org.contextualwisdomlab.identity.account.provision.v1"
    invalid = (
        "org.contextualwisdomlab.identity..provision.v1",
        "org.contextualwisdomlab.identity.account-.provision.v1",
        "org.contextualwisdomlab.identity.account.provision.v0",
    )

    for schema_path, property_name in (
        (EVENT_SCHEMA, "type"),
        (COMMAND_SCHEMA, "command_type"),
    ):
        pattern = _load(schema_path)["properties"][property_name]["pattern"]
        assert re.fullmatch(pattern, valid)
        assert all(re.fullmatch(pattern, candidate) is None for candidate in invalid)


def test_profiles_reject_unknown_properties_and_invalid_trace_context() -> None:
    """Negative examples must fail closed rather than drift beyond v1."""

    event_schema = _load(EVENT_SCHEMA)
    event = _load(EVENT_EXAMPLE)
    event["unexpected"] = True
    _assert_invalid(event, event_schema)

    command_schema = _load(COMMAND_SCHEMA)
    command = copy.deepcopy(_load(COMMAND_EXAMPLE))
    command["traceparent"] = (
        "00-00000000000000000000000000000000-00f067aa0ba902b7-01"
    )
    _assert_invalid(command, command_schema)


def test_documented_external_contract_baselines_are_present() -> None:
    """The canonical contract and doctoring file must name every pinned baseline."""

    contract_text = CONTRACT.read_text(encoding="utf-8")
    doctoring_text = DOCTORING.read_text(encoding="utf-8")

    for token in (
        "OpenAPI 3.2.0",
        "AsyncAPI 3.1.0",
        "CloudEvents 1.0",
        "JSON Schema Draft 2020-12",
        "RFC 9457",
        "RFC 9562",
        "W3C Trace Context",
        "W3C PROV-O",
    ):
        assert token in contract_text
        assert token in doctoring_text
