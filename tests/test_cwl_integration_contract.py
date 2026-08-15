"""Contract tests for the CWL organization integration profile.

These tests intentionally use only the Python standard library so that the
central contract can be verified without adding a runtime dependency.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

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


def test_shared_schemas_use_json_schema_2020_12() -> None:
    """Shared JSON schemas must remain on the organization Draft 2020-12 baseline."""

    for path in (EVENT_SCHEMA, COMMAND_SCHEMA):
        schema = _load(path)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["$id"].startswith("https://contextualwisdomlab.github.io/schemas/")


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


def test_w3c_traceparent_pattern_accepts_reference_example() -> None:
    """Both profiles must accept the W3C trace-context reference shape."""

    event_schema = _load(EVENT_SCHEMA)
    event_example = _load(EVENT_EXAMPLE)
    command_schema = _load(COMMAND_SCHEMA)
    command_example = _load(COMMAND_EXAMPLE)

    event_pattern = event_schema["properties"]["data"]["properties"]["metadata"]["properties"]["traceparent"]["pattern"]
    command_pattern = command_schema["properties"]["traceparent"]["pattern"]

    assert re.fullmatch(event_pattern, event_example["data"]["metadata"]["traceparent"])
    assert re.fullmatch(command_pattern, command_example["traceparent"])


def test_documented_external_contract_baselines_are_present() -> None:
    """The canonical contract and doctoring file must name every pinned baseline."""

    contract_text = CONTRACT.read_text(encoding="utf-8")
    doctoring_text = DOCTORING.read_text(encoding="utf-8")

    for token in (
        "OpenAPI 3.2.0",
        "AsyncAPI 3.0.0",
        "CloudEvents 1.0",
        "JSON Schema Draft 2020-12",
        "RFC 9457",
        "RFC 9562",
        "W3C Trace Context",
        "W3C PROV-O",
    ):
        assert token in contract_text
        assert token in doctoring_text
