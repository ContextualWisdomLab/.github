"""New unmeasured current executable/error boundaries, not old cohort replay."""
import subprocess
from pathlib import Path

import pytest
from scripts.ci import noema_review_document as document
from scripts.ci import premerge_review_tooling as caller
from tests.test_noema_current_quality_delta import context_fixture


@pytest.mark.parametrize("case", ["missing_retry", "null_inventory", "extra_file"])
def test_new_missing_context_and_inventory_topology(tmp_path, case):
    """Each otherwise-valid accepted context reaches one unmeasured denial."""
    context = context_fixture(tmp_path)
    if case == "missing_retry":
        context.pop("NOEMA_TRANSPORT_RETRY_ATTEMPT")
    elif case == "null_inventory":
        context["hwp_files"] = None
    else:
        (Path(context["NOEMA_HWP_MCP_SOURCE"]) / "unlisted").write_bytes(b"unlisted supplier")
    with pytest.raises(ValueError):
        caller.accepted_prepare_transport(context)


@pytest.mark.parametrize("failure", ["timeout", "oserror"])
def test_new_explicit_node_document_launch_errors(tmp_path, monkeypatch, failure):
    """The actual consumer honors explicit Node on both native launch exceptions."""
    reader = tmp_path / "reader"
    reader.mkdir()
    node = tmp_path / "explicit-node"
    monkeypatch.setenv("NOEMA_HWP_MCP_SOURCE", str(reader))
    monkeypatch.setenv("NOEMA_NODE_EXECUTABLE", str(node))
    observed = []

    def launch(command, **kwargs):
        """Record actual consumer argv and raise an inert subprocess boundary error."""
        observed.append(command)
        assert command[0] == str(node)
        assert command[2] == str(reader)
        assert Path(command[3]).read_bytes() == b"NEW_HWP_BOUNDARY"
        if failure == "timeout":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        raise OSError("FIXTURE_EXECUTABLE_UNAVAILABLE")

    monkeypatch.setattr(document.subprocess, "run", launch)
    with pytest.raises(document.DocumentReadError, match="timed out|could not start"):
        document.extract_review_document("new.hwpx", b"NEW_HWP_BOUNDARY")
    assert len(observed) == 1
