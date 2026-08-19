"""Contract tests for the CWL organization integration profile.

These tests intentionally use only the Python standard library so that the
central contract can be verified without adding a runtime dependency.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
EVENT_SCHEMA = ROOT / "schemas" / "cwl-event-envelope-v1.schema.json"
COMMAND_SCHEMA = ROOT / "schemas" / "cwl-command-envelope-v1.schema.json"
EVENT_EXAMPLE = ROOT / "schemas" / "examples" / "cwl-event-envelope-v1.example.json"
COMMAND_EXAMPLE = ROOT / "schemas" / "examples" / "cwl-command-envelope-v1.example.json"
CONTRACT = ROOT / "docs" / "integration" / "CWL_ECOSYSTEM_INTEGRATION_CONTRACT.md"
DOCTORING = ROOT / "docs" / "doctoring" / "ecosystem-integration-standards.md"
RFC3339_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})$"
)
RFC3339_LEAP_SECOND_DATES = frozenset(
    {
        "1972-06-30",
        "1972-12-31",
        "1973-12-31",
        "1974-12-31",
        "1975-12-31",
        "1976-12-31",
        "1977-12-31",
        "1978-12-31",
        "1979-12-31",
        "1981-06-30",
        "1982-06-30",
        "1983-06-30",
        "1985-06-30",
        "1987-12-31",
        "1989-12-31",
        "1990-12-31",
        "1992-06-30",
        "1993-06-30",
        "1994-06-30",
        "1995-12-31",
        "1997-06-30",
        "1998-12-31",
        "2005-12-31",
        "2008-12-31",
        "2012-06-30",
        "2015-06-30",
        "2016-12-31",
    }
)


def _load(path: Path) -> dict:
    """Load a JSON contract fixture from *path*."""

    return json.loads(path.read_text(encoding="utf-8"))


def _assert_uri_reference(value: str, path: str) -> None:
    """Assert that *value* is a bounded URI-reference without whitespace."""

    assert not any(character.isspace() for character in value), path
    parsed = urlsplit(value)
    assert parsed.scheme or parsed.path, path


def _assert_date_time(value: str, path: str) -> None:
    """Assert strict RFC 3339 lexical form plus a real offset-aware instant."""

    assert RFC3339_DATE_TIME.fullmatch(value), path
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    if normalized[17:19] == "60":
        parsed = datetime.fromisoformat(normalized[:17] + "59" + normalized[19:])
        utc = parsed.astimezone(timezone.utc)
        assert (
            utc.hour == 23
            and utc.minute == 59
            and utc.date().isoformat() in RFC3339_LEAP_SECOND_DATES
        ), path
        return
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


def test_date_time_profile_rejects_non_rfc3339_lexical_forms() -> None:
    """All event and command timestamps reject broad ISO 8601 alternatives."""

    event_schema = _load(EVENT_SCHEMA)
    command_schema = _load(COMMAND_SCHEMA)

    event = copy.deepcopy(_load(EVENT_EXAMPLE))
    event["time"] = "2026-08-15 10:00:00+00:00"
    _assert_invalid(event, event_schema)

    metadata_fields = ("occurred_at", "recorded_at", "available_at")
    for field_name in metadata_fields:
        candidate = copy.deepcopy(_load(EVENT_EXAMPLE))
        candidate["data"]["metadata"][field_name] = "2026-08-15 10:00:00+00:00"
        _assert_invalid(candidate, event_schema)

    command = copy.deepcopy(_load(COMMAND_EXAMPLE))
    command["requested_at"] = "2026-08-15 10:00:00+00:00"
    _assert_invalid(command, command_schema)

    for value in (
        "2026-08-15T10:00:00Z",
        "2026-08-15T10:00:00.123456789+09:00",
    ):
        _assert_date_time(value, "$.timestamp")


def test_date_time_profile_handles_rfc3339_leap_seconds() -> None:
    """Accept an announced leap second and reject impossible placements."""

    _assert_date_time("2016-12-31T23:59:60Z", "$.timestamp")
    _assert_date_time("2017-01-01T00:59:60+01:00", "$.timestamp")
    for value in (
        "2016-12-31T23:58:60Z",
        "2017-01-01T00:00:60Z",
        "2017-01-01T00:59:60Z",
    ):
        try:
            _assert_date_time(value, "$.timestamp")
        except (AssertionError, ValueError):
            continue
        raise AssertionError(f"impossible leap second accepted: {value}")


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
