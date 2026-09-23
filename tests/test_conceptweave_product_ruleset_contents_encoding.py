from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from scripts.ci import reconcile_conceptweave_product_ruleset as p
from scripts.ci.reconcile_ruleset_governance import RulesetGovernanceError


MANIFEST = Path("config/conceptweave-product-ruleset.json")


def workflow_payload(text: str, *, blob_sha: str = "a" * 40) -> dict[str, str]:
    """Build one GitHub Contents API workflow response with an immutable blob identity."""

    return {
        "type": "file",
        "encoding": "base64",
        "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
        "sha": blob_sha,
    }


def test_decode_workflow_accepts_github_line_wrapped_base64() -> None:
    """GitHub Contents API line wrapping must not invalidate a legitimate workflow."""

    text = (
        "name: Product\n"
        "jobs:\n"
        "  acceptance:\n"
        "    name: 'Product acceptance'\n"
        "    metadata: 'Product metadata-only'\n"
    )
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    wrapped = "\n".join(encoded[index : index + 60] for index in range(0, len(encoded), 60)) + "\n"
    payload = {"type": "file", "encoding": "base64", "content": wrapped}

    assert p._decode_workflow(payload) == text


def test_product_manifest_has_unadopted_workflow_blob_coordinate() -> None:
    """Initial owner source must reserve, but never guess, the protected Product blob identity."""

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert "product_workflow_blob_sha" in manifest
    assert manifest["product_workflow_blob_sha"] is None


def test_base_product_workflow_requires_exact_reviewed_blob_coordinate(monkeypatch) -> None:
    """Marker-compatible workflow drift must fail before owner-plane mutation."""

    text = (
        "name: Product\n"
        "'Product acceptance'\n"
        "'Product metadata-only'\n"
        "cancel-in-progress: false\n"
    )
    payload = workflow_payload(text, blob_sha="a" * 40)
    monkeypatch.setattr(p, "_gh_api", lambda *args, **kwargs: payload)

    p._assert_base_product_workflow("b" * 40, expected_blob_sha="a" * 40)
    with pytest.raises(RulesetGovernanceError, match="blob"):
        p._assert_base_product_workflow("b" * 40, expected_blob_sha="c" * 40)
