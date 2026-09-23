from __future__ import annotations

import base64

from scripts.ci import reconcile_conceptweave_product_ruleset as p


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
