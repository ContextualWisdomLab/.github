"""Complete branch tests for the vendored strict fallback manifest parser."""

from __future__ import annotations

import pytest

from scripts.ci import contextual_fallback_policy as integration

integration.load_policy_module()

from contextual_orchestrator._fallback_manifest import (  # noqa: E402
    load_fallback_manifest,
)
from contextual_orchestrator._fallback_types import (  # noqa: E402
    FallbackManifestError,
)


def manifest_document() -> dict[str, object]:
    """Return a complete manifest fixture."""
    return {
        "schema_version": 1,
        "agents": {
            "noema": {
                "candidates": [
                    {
                        "candidate_id": "paid-primary",
                        "provider": "openai",
                        "model": "openai/paid",
                        "cost_tier": "paid",
                        "priority": 0,
                        "required_credentials": ["PAID_API_KEY"],
                        "repository_visibilities": ["public", "private"],
                        "capabilities": ["text", "structured_output"],
                    },
                    {
                        "candidate_id": "free-primary",
                        "provider": "nvidia-nim",
                        "model": "nvidia/free",
                        "cost_tier": "free",
                        "priority": 10,
                        "required_credentials": ["FREE_API_KEY"],
                        "repository_visibilities": ["public"],
                        "capabilities": ["text", "structured_output"],
                    },
                ]
            }
        },
    }


def candidate_at(document: dict[str, object], index: int = 0) -> dict[str, object]:
    """Return a mutable candidate object from the typed fixture."""
    return document["agents"]["noema"]["candidates"][index]  # type: ignore[index,return-value]


def agent_at(document: dict[str, object]) -> dict[str, object]:
    """Return the mutable Noema agent block from the typed fixture."""
    return document["agents"]["noema"]  # type: ignore[index,return-value]


def test_manifest_parses_candidates_without_reordering_source() -> None:
    """Manifest parsing preserves trusted declaration order and defaults."""
    candidates = load_fallback_manifest(manifest_document(), "noema")
    assert tuple(candidate.candidate_id for candidate in candidates) == (
        "paid-primary",
        "free-primary",
    )

    document = manifest_document()
    candidate = candidate_at(document)
    candidate.pop("priority")
    candidate.pop("required_credentials")
    candidate.pop("repository_visibilities")
    candidate.pop("capabilities")
    parsed = load_fallback_manifest(document, "noema")[0]
    assert parsed.priority == 100
    assert parsed.required_credentials == ()
    assert parsed.repository_visibilities == frozenset(
        {"public", "private", "internal"}
    )
    assert parsed.capabilities == frozenset({"text"})


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda document: document.update({"unknown": True}), "unknown manifest"),
        (lambda document: document.update({"schema_version": 2}), "schema_version"),
        (lambda document: document.update({"agents": []}), "agents must be"),
        (
            lambda document: document.update({"agents": {"bad agent": {}}}),
            "agent name",
        ),
        (
            lambda document: document.update({"agents": {1: {}}}),
            "agent name",
        ),
    ],
)
def test_manifest_rejects_invalid_root_control_data(mutator, message: str) -> None:
    """Versioned root keys and agent identifiers fail closed."""
    document = manifest_document()
    mutator(document)
    with pytest.raises(FallbackManifestError, match=message):
        load_fallback_manifest(document, "noema")


def test_manifest_rejects_non_object_root_and_missing_agent() -> None:
    """Programmatic inputs cannot bypass root and agent shape checks."""
    with pytest.raises(FallbackManifestError, match="manifest must be an object"):
        load_fallback_manifest([], "noema")  # type: ignore[arg-type]
    with pytest.raises(FallbackManifestError, match="was not found"):
        load_fallback_manifest(manifest_document(), "strix")


def test_manifest_rejects_invalid_agent_container_and_keys() -> None:
    """Agent blocks accept only a non-empty candidate array."""
    document = manifest_document()
    document["agents"]["noema"] = []  # type: ignore[index]
    with pytest.raises(FallbackManifestError, match="must be an object"):
        load_fallback_manifest(document, "noema")

    document = manifest_document()
    agent_at(document)["unknown"] = True
    with pytest.raises(FallbackManifestError, match="unknown agent keys"):
        load_fallback_manifest(document, "noema")

    document = manifest_document()
    agent_at(document)["candidates"] = {}
    with pytest.raises(FallbackManifestError, match="must be an array"):
        load_fallback_manifest(document, "noema")

    document = manifest_document()
    agent_at(document)["candidates"] = []
    with pytest.raises(FallbackManifestError, match="at least one"):
        load_fallback_manifest(document, "noema")


def test_manifest_rejects_non_object_candidate_and_unknown_keys() -> None:
    """Candidate entries use an exact schema."""
    document = manifest_document()
    agent_at(document)["candidates"][0] = []  # type: ignore[index]
    with pytest.raises(FallbackManifestError, match="candidate must be an object"):
        load_fallback_manifest(document, "noema")

    document = manifest_document()
    candidate_at(document)["unknown"] = True
    with pytest.raises(FallbackManifestError, match="unknown candidate keys"):
        load_fallback_manifest(document, "noema")


def test_manifest_rejects_missing_keys_bad_tier_and_bad_sequences() -> None:
    """Candidate schema failures are normalized as manifest errors."""
    document = manifest_document()
    del candidate_at(document)["model"]
    with pytest.raises(FallbackManifestError, match="missing candidate keys: model"):
        load_fallback_manifest(document, "noema")

    for tier in ("metered", [], None):
        document = manifest_document()
        candidate_at(document)["cost_tier"] = tier
        with pytest.raises(FallbackManifestError, match="free or paid"):
            load_fallback_manifest(document, "noema")

    for field in (
        "required_credentials",
        "repository_visibilities",
        "capabilities",
    ):
        for bad_value in ("not-array", ["ok", 1]):
            document = manifest_document()
            candidate_at(document)[field] = bad_value
            with pytest.raises(FallbackManifestError, match=f"{field} must be"):
                load_fallback_manifest(document, "noema")


def test_manifest_normalizes_candidate_validation_and_duplicates() -> None:
    """Unsafe fields and duplicate identities remain manifest errors."""
    document = manifest_document()
    candidate_at(document)["provider"] = "Bad/Provider"
    with pytest.raises(FallbackManifestError, match="provider"):
        load_fallback_manifest(document, "noema")

    document = manifest_document()
    candidate_at(document, 1)["candidate_id"] = "paid-primary"
    with pytest.raises(FallbackManifestError, match="duplicate candidate_id"):
        load_fallback_manifest(document, "noema")

    document = manifest_document()
    candidate_at(document, 1)["provider"] = "openai"
    candidate_at(document, 1)["model"] = "openai/paid"
    with pytest.raises(FallbackManifestError, match="duplicate provider/model"):
        load_fallback_manifest(document, "noema")
