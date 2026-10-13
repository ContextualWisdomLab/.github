"""Unexecuted current-helper edge cases identified by retained arc reconciliation."""
import hashlib
import json
from pathlib import Path

import pytest
from scripts.ci import premerge_review_tooling as caller
from tests.test_noema_current_quality_delta import context_fixture
from tests.test_noema_production_cli_coverage import setup_caller


@pytest.mark.parametrize("case", ["boolean_retry", "inventory_list", "bad_hash_length", "nested_reader"])
def test_new_current_helper_remaining_shapes(tmp_path, case):
    """Reject distinct malformed shapes and accept an exact nested inventory."""
    context = context_fixture(tmp_path)
    if case == "boolean_retry":
        context["NOEMA_TRANSPORT_RETRY_ATTEMPT"] = True
    elif case == "inventory_list":
        context["hwp_files"] = ["body"]
    elif case == "bad_hash_length":
        context["hwp_files"] = {"body": "a" * 63}
    else:
        root = Path(context["NOEMA_HWP_MCP_SOURCE"])
        (root / "nested").mkdir()
        (root / "nested/body").write_bytes(b"nested accepted")
        context["hwp_files"]["nested/body"] = hashlib.sha256(b"nested accepted").hexdigest()
        result = caller.accepted_prepare_transport(context)
        assert result["NOEMA_HWP_MCP_SOURCE"] == str(root)
        return
    with pytest.raises(ValueError):
        caller.accepted_prepare_transport(context)


def test_new_admission_only_does_not_consume_prepare_context(tmp_path, monkeypatch):
    """Preflight with pinned extra context is not phase execution or supplier admission."""
    args, paths, _, events = setup_caller(tmp_path, monkeypatch, "admit")
    data = json.loads(paths["admission"].read_text())
    data["prepare_transport"] = {"GITHUB_OUTPUT": str(tmp_path / "missing-output"),
                                 "NOEMA_TRANSPORT_RETRY_ATTEMPT": "0"}
    paths["admission"].write_text(json.dumps(data))
    args[args.index("--admission-digest") + 1] = hashlib.sha256(paths["admission"].read_bytes()).hexdigest()
    assert caller.production_main(args) == 0
    assert events == []
    assert not (tmp_path / "missing-output").exists()
