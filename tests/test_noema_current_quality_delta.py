"""New current-source coverage controls; no predecessor cohorts replayed."""
import hashlib
import json
import os
import runpy
import sys
from pathlib import Path

import pytest
from scripts.ci import premerge_review_tooling as caller
from scripts.ci import noema_review_document as document
from tests.test_noema_production_cli_coverage import setup_caller


def context_fixture(tmp_path):
    """Create a minimal pinned regular Node and complete reader namespace."""
    output = tmp_path / "output"
    output.touch(mode=0o600)
    reader = tmp_path / "reader"
    reader.mkdir()
    (reader / "body").write_bytes(b"fixture")
    node = tmp_path / "node"
    node.write_bytes(b"fixture executable identity")
    node.chmod(0o700)
    return {"GITHUB_OUTPUT": str(output), "NOEMA_TRANSPORT_RETRY_ATTEMPT": "0",
            "NOEMA_HWP_MCP_SOURCE": str(reader), "NOEMA_NODE_EXECUTABLE": str(node),
            "node_sha256": hashlib.sha256(node.read_bytes()).hexdigest(),
            "hwp_files": {"body": hashlib.sha256(b"fixture").hexdigest()}}


@pytest.mark.parametrize("case", ["none", "output_only", "document_only", "integer_path", "output_relative", "output_hardlink", "empty", "list", "incomplete", "relative_node", "root_symlink", "node_symlink", "nonexecutable", "bad_digest", "empty_inventory", "unsafe_name", "bad_inventory_digest", "supplier_symlink", "supplier_fifo", "root_file", "node_directory", "both", "internal_control"])
def test_new_prepare_transport_shape_and_capability_cases(tmp_path, case):
    """Exercise newly introduced helper branches with explicit native file kinds."""
    context = context_fixture(tmp_path)
    node, reader = Path(context["NOEMA_NODE_EXECUTABLE"]), Path(context["NOEMA_HWP_MCP_SOURCE"])
    if case == "none":
        assert caller.accepted_prepare_transport(None) == {}
        return
    if case == "output_only":
        context = {k: context[k] for k in ("GITHUB_OUTPUT", "NOEMA_TRANSPORT_RETRY_ATTEMPT")}
    elif case == "document_only":
        context = {k: v for k, v in context.items() if k not in ("GITHUB_OUTPUT", "NOEMA_TRANSPORT_RETRY_ATTEMPT")}
    elif case == "integer_path": context["GITHUB_OUTPUT"] = 3
    elif case == "output_relative": context["GITHUB_OUTPUT"] = "output"
    elif case == "output_hardlink": os.link(context["GITHUB_OUTPUT"], tmp_path / "second")
    elif case == "empty": context = {}
    elif case == "list": context = []
    elif case == "incomplete": context.pop("node_sha256")
    elif case == "relative_node": context["NOEMA_NODE_EXECUTABLE"] = "node"
    elif case == "root_symlink":
        link = tmp_path / "reader-link"; link.symlink_to(reader); context["NOEMA_HWP_MCP_SOURCE"] = str(link)
    elif case == "node_symlink":
        link = tmp_path / "node-link"; link.symlink_to(node); context["NOEMA_NODE_EXECUTABLE"] = str(link)
    elif case == "nonexecutable": node.chmod(0o600)
    elif case == "bad_digest": context["node_sha256"] = "bad"
    elif case == "empty_inventory": context["hwp_files"] = {}
    elif case == "unsafe_name": context["hwp_files"] = {"../escape": "a" * 64}
    elif case == "bad_inventory_digest": context["hwp_files"] = {"body": 4}
    elif case == "supplier_symlink": (reader / "link").symlink_to(reader / "body")
    elif case == "supplier_fifo": os.mkfifo(reader / "fifo")
    elif case == "root_file": context["NOEMA_HWP_MCP_SOURCE"] = str(node)
    elif case == "node_directory": context["NOEMA_NODE_EXECUTABLE"] = str(reader)
    elif case == "internal_control": context["GITHUB_OUTPUT"] = str(tmp_path / "a\x01b")
    if case in ("both", "output_only", "document_only"):
        result = caller.accepted_prepare_transport(context)
        assert result == {k: v for k, v in context.items() if k not in ("hwp_files", "node_sha256")}
    else:
        with pytest.raises(ValueError): caller.accepted_prepare_transport(context)


@pytest.mark.parametrize("target", ["manifest", "unchanged"])
def test_new_live_read_manifest_identity_and_success(tmp_path, monkeypatch, target):
    """Revalidate manifest rather than admission after a live metadata wait."""
    args, paths, _, events = setup_caller(tmp_path, monkeypatch, "prepare")
    original = caller.subprocess.run

    def metadata(*args, **kwargs):
        """Complete metadata before independently changing the manifest bytes."""
        response = original(*args, **kwargs)
        if target == "manifest": paths["manifest"].write_text("{}")
        return response

    monkeypatch.setattr(caller.subprocess, "run", metadata)
    assert caller.production_main(args) == (1 if target == "manifest" else 0)
    assert events == ([] if target == "manifest" else ["prepare"])


def test_new_run_mode_admits_output_transport(tmp_path, monkeypatch):
    """The combined controller's issuance closure validates the new context too."""
    args, paths, _, events = setup_caller(tmp_path, monkeypatch, "run")
    data = json.loads(paths["admission"].read_text())
    output = tmp_path / "accepted-output"; output.touch(mode=0o600)
    data["prepare_transport"] = {"GITHUB_OUTPUT": str(output), "NOEMA_TRANSPORT_RETRY_ATTEMPT": "2"}
    paths["admission"].write_text(json.dumps(data))
    args[args.index("--admission-digest") + 1] = hashlib.sha256(paths["admission"].read_bytes()).hexdigest()
    assert caller.production_main(args) == 0
    assert events == ["prepare", "publish"]


def test_new_document_cli_explicit_executable_inprocess(tmp_path, monkeypatch):
    """Execute actual document CLI and Node with only synthetic supplier functions."""
    import shutil
    from tests.test_noema_child_environment_composition import composition
    _, _, _, _, context = composition(tmp_path, monkeypatch, "hwp")
    # Restore subprocess to the native adapter: composition installs a fixture
    # controller seam, not a replacement for the actual Node document reader.
    monkeypatch.undo()
    monkeypatch.setenv("NOEMA_HWP_MCP_SOURCE", context["NOEMA_HWP_MCP_SOURCE"])
    monkeypatch.setenv("NOEMA_NODE_EXECUTABLE", context["NOEMA_NODE_EXECUTABLE"])
    monkeypatch.delenv("NODE_OPTIONS", raising=False)
    path = tmp_path / "probe.hwpx"; path.write_bytes(b"NEW_DOCUMENT_EXECUTABLE_BOUNDARY")
    monkeypatch.setattr(sys, "argv", [document.__file__, str(path)])
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(document.__file__, run_name="__main__")
    assert stopped.value.code == 0
