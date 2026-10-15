"""Regression controls for admission and consumer path identity."""
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from scripts.ci import premerge_review_tooling as caller
from tests.test_noema_child_environment_composition import composition


@pytest.mark.parametrize("field", ["GITHUB_OUTPUT", "NOEMA_HWP_MCP_SOURCE"])
@pytest.mark.parametrize("suffix", [" ", "\t", "\n", "\r", "\u00a0", "\x01", "\x7f"])
def test_consumer_alias_rejected_before_child_or_output_write(tmp_path, monkeypatch, field, suffix):
    """Valid distinct private raw/stripped names cannot redirect accepted capability."""
    scenario = "retry" if field == "GITHUB_OUTPUT" else "hwp"
    args, paths, output, children, context = composition(tmp_path, monkeypatch, scenario)
    ordinary = Path(context[field])
    suffixed = ordinary.with_name(ordinary.name + suffix)
    if field == "GITHUB_OUTPUT":
        suffixed.write_bytes(b"RAW_OUTPUT_SENTINEL")
        suffixed.chmod(0o600)
    else:
        shutil.copytree(ordinary, suffixed)
        # Keep the admitted raw inventory valid while distinguishing its sibling.
        (ordinary / "dist/tools/read.js").write_text("throw new Error('UNADMITTED_SIBLING');\n")
    context[field] = str(suffixed)
    admission = json.loads(paths["admission"].read_text())
    admission["prepare_transport"] = context
    paths["admission"].write_text(json.dumps(admission))
    args[args.index("--admission-digest") + 1] = hashlib.sha256(paths["admission"].read_bytes()).hexdigest()
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert caller.production_main(args) == 1
    assert children == []
    assert not paths["verdict"].exists()
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert output.read_bytes() == b""


@pytest.mark.parametrize("scenario", ["retry", "hwp"])
def test_ordinary_capability_identity_still_reaches_actual_consumer(tmp_path, monkeypatch, scenario):
    """An unchanged accepted identity stays nonempty through the real child seam."""
    args, paths, output, children, context = composition(tmp_path, monkeypatch, scenario)
    assert caller.production_main(args) == (1 if scenario == "retry" else 0)
    assert len(children) == 1
    assert children[0]["GITHUB_OUTPUT"] == context["GITHUB_OUTPUT"]
    assert children[0]["NOEMA_HWP_MCP_SOURCE"] == context["NOEMA_HWP_MCP_SOURCE"]
    assert children[0]["NOEMA_LLM_MODEL"] == "auto"
    assert "NODE_OPTIONS" not in children[0]
    if scenario == "retry":
        assert "transport_retry_next_attempt=2\n" in output.read_text()
        assert not paths["verdict"].exists()
    else:
        assert paths["verdict"].exists()
