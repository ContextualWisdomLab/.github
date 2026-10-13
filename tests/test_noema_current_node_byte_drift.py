"""New actual executable-byte replacement control, not a forged digest replay."""
from pathlib import Path

import pytest
from scripts.ci import premerge_review_tooling as caller
from tests.test_noema_current_quality_delta import context_fixture


def test_actual_node_bytes_change_after_pin_is_rejected(tmp_path):
    """Keep the real original digest and mutate only independently pinned bytes."""
    context = context_fixture(tmp_path)
    node = Path(context["NOEMA_NODE_EXECUTABLE"])
    node.write_bytes(b"distinct executable after independent pin")
    with pytest.raises(ValueError, match="Node supplier bytes changed"):
        caller.accepted_prepare_transport(context)
