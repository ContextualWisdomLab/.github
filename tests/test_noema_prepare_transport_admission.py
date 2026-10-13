"""New fail-closed controls for explicitly admitted prepare transport."""
import hashlib
import json
from pathlib import Path

import pytest
from scripts.ci import premerge_review_tooling as caller
from tests.test_noema_child_environment_composition import composition


@pytest.mark.parametrize("mutation", ["ambient", "retry", "output_mode", "output_symlink", "reader", "node", "incomplete"])
def test_rejected_transport_never_reaches_child(tmp_path, monkeypatch, mutation):
    """Invalid accepted transport rejects before any child or output write."""
    args, paths, output, children, context = composition(tmp_path, monkeypatch, "hwp")
    if mutation == "ambient":
        context["NODE_OPTIONS"] = "--require=ambient"
    elif mutation == "retry":
        context["NOEMA_TRANSPORT_RETRY_ATTEMPT"] = "3"
    elif mutation == "output_mode":
        output.chmod(0o666)
    elif mutation == "output_symlink":
        link = tmp_path / "output-link"
        link.symlink_to(output)
        context["GITHUB_OUTPUT"] = str(link)
    elif mutation == "reader":
        (Path(context["NOEMA_HWP_MCP_SOURCE"]) / "dist/tools/read.js").write_text("changed supplier")
    elif mutation == "node":
        context["node_sha256"] = "0" * 64
    else:
        context.pop("NOEMA_NODE_EXECUTABLE")
    admission = json.loads(paths["admission"].read_text())
    admission["prepare_transport"] = context
    paths["admission"].write_text(json.dumps(admission))
    args[args.index("--admission-digest") + 1] = hashlib.sha256(paths["admission"].read_bytes()).hexdigest()
    assert caller.production_main(args) == 1
    assert children == []
    assert output.read_bytes() == b""
    assert not paths["verdict"].exists()


def test_publisher_never_receives_prepare_transport_or_inference(tmp_path, monkeypatch):
    """A publisher ignores even a prepare transport object and receives no loader."""
    _, _, _, _, context = composition(tmp_path, monkeypatch, "hwp")
    scope = {"repository": "ContextualWisdomLab/example", "reviewer": "cwl-noema-review[bot]"}
    response = {"token": "SYNTHETIC_WRITE", "permissions": {
        "contents": "read", "metadata": "read", "pull_requests": "write"},
        "repositories": [{"full_name": scope["repository"]}]}
    environment = caller.phase_environment_from_issuance(
        "publish", response, scope=scope, reviewer_actor=scope["reviewer"],
        installation_id=7, inference_key="SYNTHETIC_NOT_FOR_PUBLISH", prepare_transport=context,
    )
    caller.require_phase_environment("publish", environment)
    assert set(environment) == {"PATH", "GH_TOKEN", "NOEMA_REVIEW_ACTOR",
                                "NOEMA_REVIEW_INSTALLATION_ID", "NOEMA_REVIEW_TOKEN_SOURCE"}
    assert environment["PATH"] == "/usr/bin:/bin"
